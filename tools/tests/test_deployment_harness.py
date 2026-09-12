"""Offline entrypoint, local issuer and transport-cut contracts."""
import base64
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import re
import socket
import socketserver
import subprocess
import sys
import tempfile
import threading
import unittest
from urllib.error import HTTPError
from urllib.parse import urlencode, urlsplit, parse_qs
from urllib.request import build_opener, ProxyHandler, HTTPRedirectHandler, Request

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT / "tools" / "deployment-fixtures"))
from harness import SYSTEM_KEYS
from oidc import OIDCFixture
from mongo_proxy import MongoProxy
import test_deployment as harness


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *_args): return None


class SafeEntrypoints(unittest.TestCase):
    def test_no_arguments_and_help_are_package_free(self):
        environment = {key: value for key, value in os.environ.items() if key.upper() in SYSTEM_KEYS}
        environment.update(MONGO_URL="mongodb://private.invalid/customer", GUARDIAN_OIDC_CLIENT_SECRET="private-secret")
        for script, arguments in (("tools/test_deployment.py", []), ("tools/test_deployment.py", ["--help"]),
                                  ("tools/deployment-fixtures/launch.py", [])):
            result = subprocess.run([sys.executable, "-I", "-S", str(ROOT / script), *arguments], env=environment,
                capture_output=True, text=True, timeout=15)
            self.assertEqual(result.returncode, 0)
            self.assertIn("usage:", result.stdout.lower())
            self.assertNotIn("private", result.stdout + result.stderr)

    def test_inherited_credentials_are_not_selected(self):
        from unittest.mock import patch
        with patch.dict(os.environ, {"MONGO_URL": "private", "OPENAI_API_KEY": "private", "PYTHONPATH": "private", "ProgramFiles": "synthetic-program-directory"}):
            environment = harness.system_environment()
        self.assertNotIn("MONGO_URL", environment)
        self.assertNotIn("OPENAI_API_KEY", environment)
        self.assertNotIn("PYTHONPATH", environment)
        self.assertEqual(next(value for key, value in environment.items() if key.upper() == "PROGRAMFILES"), "synthetic-program-directory")
        if os.name == "nt": self.assertIn("SYSTEMDRIVE", {key.upper() for key in environment})

    def test_node_browser_is_inert_without_explicit_run(self):
        import shutil
        result = subprocess.run([shutil.which("node"), str(ROOT / "tools/deployment-fixtures/browser.cjs")],
            env=harness.system_environment(), capture_output=True, text=True, timeout=15)
        self.assertEqual(result.returncode, 0)
        self.assertIn("Usage:", result.stdout)
        self.assertEqual(result.stderr, "")

    def test_uncertain_child_cleanup_retains_owned_database_marker(self):
        from unittest.mock import Mock
        admin, database = Mock(), Mock()
        owner = "a" * 32
        with self.assertRaisesRegex(harness.CheckFailed, "owned_child_cleanup_uncertain"):
            harness.remove_owned_database(admin, database, "guardian_deployment_test_" + owner, owner, children_clean=False)
        admin.drop_database.assert_not_called()
        database.assert_not_called()

    def test_stdin_launcher_runs_actual_module_without_ambient_configuration(self):
        with tempfile.TemporaryDirectory(prefix="guardian-deployment-launch-") as directory:
            Path(directory, "deployment.py").write_text("import os,json,sys\nprint(json.dumps({'arguments':sys.argv[1:],'private_present':'OPENAI_API_KEY' in os.environ}))\n")
            environment = harness.system_environment()
            incoming = {**environment, "OPENAI_API_KEY": "synthetic-ambient-secret"}
            result = subprocess.run([sys.executable, "-I", "-S", str(ROOT / "tools/deployment-fixtures/launch.py"), "--run"],
                input=json.dumps({"environment": environment, "arguments": ["check"]}),
                cwd=directory, env=incoming, capture_output=True, text=True, timeout=20)
            self.assertEqual(result.returncode, 0)
            self.assertEqual(json.loads(result.stdout), {"arguments": ["check"], "private_present": False})
            self.assertEqual(result.stderr, "")

    def test_constructor_failure_preserves_uncertain_owned_process_for_cleanup(self):
        from unittest.mock import Mock, patch
        process = Mock(stdout=io.BytesIO(), stderr=io.BytesIO())
        process.stdin.write.side_effect = KeyboardInterrupt()
        with patch.object(harness.subprocess, "Popen", return_value=process), patch.object(harness.Child, "close", side_effect=harness.CheckFailed("owned_child_cleanup_uncertain")):
            with self.assertRaises(harness.ChildStartupFailure) as failed:
                harness.Child(["synthetic-child"], {})
        self.assertIs(failed.exception.child.process, process)


class LocalOIDC(unittest.TestCase):
    def test_authorization_code_is_bound_to_pkce_nonce_and_consumed_once(self):
        claims = []
        signer = lambda value: claims.append(value) or "synthetic-signed-token"
        opener = build_opener(ProxyHandler({}), NoRedirect())
        with OIDCFixture("http://127.0.0.1:8001/api/guardian/auth/callback", signer=signer, jwk={"kid": "test"}) as fixture:
            verifier = "v" * 64
            query = {"response_type": "code", "client_id": fixture.client_id, "redirect_uri": fixture.redirect_uri,
                "scope": "openid profile", "code_challenge_method": "S256", "response_mode": "query",
                "state": "s" * 43, "nonce": "n" * 43,
                "code_challenge": base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip("=")}
            html = opener.open(fixture.origin + "/authorize?" + urlencode(query), timeout=2).read().decode()
            handle = re.search(r'name="handle" value="([A-Za-z0-9_-]+)"', html)[1]
            with self.assertRaises(HTTPError) as redirected:
                opener.open(Request(fixture.origin + "/approve", data=urlencode({"handle": handle}).encode()), timeout=2)
            self.assertEqual(redirected.exception.code, 303)
            callback = parse_qs(urlsplit(redirected.exception.headers["Location"]).query)
            body = urlencode({"grant_type": "authorization_code", "code": callback["code"][0],
                "redirect_uri": fixture.redirect_uri, "code_verifier": verifier}).encode()
            headers = {"Authorization": "Basic " + base64.b64encode((fixture.client_id + ":" + fixture.client_secret).encode()).decode()}
            result = json.loads(opener.open(Request(fixture.origin + "/token", data=body, headers=headers), timeout=2).read())
            self.assertEqual(result["id_token"], "synthetic-signed-token")
            self.assertEqual(claims[0]["nonce"], query["nonce"])
            self.assertEqual(claims[0]["iss"], fixture.origin)
            with self.assertRaises(HTTPError): opener.open(Request(fixture.origin + "/token", data=body, headers=headers), timeout=2)
            self.assertEqual(fixture.counts["token"], 1)
            port = fixture.server.server_port
        with self.assertRaises(OSError): socket.create_connection(("127.0.0.1", port), timeout=1)

    def test_wrong_redirect_never_issues_flow_or_secret(self):
        with OIDCFixture("http://127.0.0.1:8001/callback", signer=lambda _: "unused", jwk={}) as fixture:
            with self.assertRaises(HTTPError) as failed:
                build_opener(ProxyHandler({})).open(fixture.origin + "/authorize?redirect_uri=https%3A%2F%2Fexternal.invalid", timeout=2)
            self.assertEqual(failed.exception.code, 400)
            self.assertEqual(json.loads(failed.exception.read()), {"error": "invalid_fixture_request"})
            self.assertFalse(fixture.pending)


class CutDatabaseTransport(unittest.TestCase):
    def test_actual_connection_cut_and_restore(self):
        class Echo(socketserver.BaseRequestHandler):
            def handle(self):
                while data := self.request.recv(64): self.request.sendall(data)
        server = socketserver.ThreadingTCPServer(("127.0.0.1", 0), Echo)
        server.daemon_threads = True
        thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": .05}, daemon=True)
        thread.start()
        try:
            with MongoProxy("127.0.0.1", server.server_address[1]) as proxy:
                with socket.create_connection(("127.0.0.1", proxy.port), timeout=2) as connection:
                    connection.sendall(b"before")
                    self.assertEqual(connection.recv(64), b"before")
                    proxy.cut()
                    self.assertEqual(connection.recv(64), b"")
                proxy.restore()
                with socket.create_connection(("127.0.0.1", proxy.port), timeout=2) as connection:
                    connection.sendall(b"after")
                    self.assertEqual(connection.recv(64), b"after")
                port = proxy.port
            with self.assertRaises(OSError): socket.create_connection(("127.0.0.1", port), timeout=1)
        finally:
            server.shutdown(); server.server_close(); thread.join(2)


if __name__ == "__main__": unittest.main()
