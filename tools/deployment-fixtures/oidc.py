"""Owned loopback OIDC test server; never an account or production IdP."""
import base64
from collections import Counter
import hashlib
import hmac
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import re
import secrets
import threading
import time
from urllib.parse import parse_qs, urlencode, urlsplit


class OIDCFixture:
    def __init__(self, redirect_uri, *, client_id="deployment-fixture", client_secret=None, signer=None, jwk=None):
        self.redirect_uri = redirect_uri
        self.client_id = client_id
        self.client_secret = client_secret or secrets.token_urlsafe(32)
        self.counts = Counter()
        self.pending, self.codes = {}, {}
        self.lock = threading.Lock()
        if signer is None:
            from joserfc import jwt
            from joserfc.jwk import RSAKey
            key = RSAKey.generate_key(2048, parameters={"kid": "deployment-test-key", "alg": "RS256", "use": "sig"})
            signer = lambda claims: jwt.encode({"alg": "RS256", "kid": "deployment-test-key"}, claims, key)
            jwk = key.as_dict(private=False)
        self.signer, self.jwk = signer, jwk
        fixture = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"
            def log_message(self, *_args): pass
            def setup(self):
                super().setup()
                self.connection.settimeout(5)
            def reply(self, status, body=b"", *, content_type="application/json", location=None):
                self.send_response(status)
                self.send_header("Content-Type", content_type)
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Cache-Control", "no-store")
                self.send_header("Connection", "close")
                if location: self.send_header("Location", location)
                self.end_headers()
                self.wfile.write(body)
                self.close_connection = True
            def do_GET(self):
                try:
                    path = urlsplit(self.path)
                    if path.path == "/.well-known/openid-configuration" and not path.query:
                        fixture.counts["discovery"] += 1
                        value = {"issuer": fixture.origin, "authorization_endpoint": fixture.origin + "/authorize",
                            "token_endpoint": fixture.origin + "/token", "jwks_uri": fixture.origin + "/jwks",
                            "response_types_supported": ["code"], "id_token_signing_alg_values_supported": ["RS256"],
                            "token_endpoint_auth_methods_supported": ["client_secret_basic"],
                            "code_challenge_methods_supported": ["S256"]}
                        self.reply(200, json.dumps(value).encode())
                    elif path.path == "/jwks" and not path.query:
                        fixture.counts["jwks"] += 1
                        self.reply(200, json.dumps({"keys": [fixture.jwk]}).encode())
                    elif path.path == "/authorize":
                        values = parse_qs(path.query, keep_blank_values=True, strict_parsing=True)
                        expected = {"response_type": "code", "client_id": fixture.client_id,
                            "redirect_uri": fixture.redirect_uri, "scope": "openid profile", "code_challenge_method": "S256",
                            "response_mode": "query"}
                        assert set(values) == set(expected) | {"state", "nonce", "code_challenge"}
                        assert all(values[key] == [value] for key, value in expected.items())
                        assert all(len(values[key]) == 1 and re.fullmatch(r"[A-Za-z0-9_-]{40,128}", values[key][0])
                                   for key in ("state", "nonce", "code_challenge"))
                        with fixture.lock:
                            assert len(fixture.pending) < 32
                            handle = secrets.token_urlsafe(32)
                            fixture.pending[handle] = {key: values[key][0] for key in ("state", "nonce", "code_challenge")}
                            fixture.pending[handle]["created"] = time.monotonic()
                        fixture.counts["authorize"] += 1
                        html = ('<!doctype html><html lang="en"><title>Synthetic local identity</title><body>'
                            '<h1>Local identity fixture</h1><form method="post" action="/approve">'
                            '<input type="hidden" name="handle" value="' + handle + '">'
                            '<button>Continue as Synthetic Owner</button></form></body></html>')
                        self.reply(200, html.encode(), content_type="text/html; charset=utf-8")
                    else: self.reply(404, b'{}')
                except Exception: self.reply(400, b'{"error":"invalid_fixture_request"}')
            def do_POST(self):
                try:
                    assert self.path in ("/approve", "/token")
                    length = self.headers.get("Content-Length", "")
                    assert length.isdecimal() and 0 < int(length) <= 8192
                    values = parse_qs(self.rfile.read(int(length)).decode(), keep_blank_values=True, strict_parsing=True)
                    assert all(len(value) == 1 for value in values.values())
                    values = {key: value[0] for key, value in values.items()}
                    if self.path == "/approve":
                        assert set(values) == {"handle"}
                        with fixture.lock:
                            flow = fixture.pending.pop(values["handle"])
                            assert time.monotonic() - flow["created"] <= 120
                            code = secrets.token_urlsafe(32)
                            fixture.codes[code] = flow
                        fixture.counts["approved"] += 1
                        self.reply(303, location=fixture.redirect_uri + "?" + urlencode({"code": code, "state": flow["state"]}))
                    else:
                        expected = "Basic " + base64.b64encode((fixture.client_id + ":" + fixture.client_secret).encode()).decode()
                        assert hmac.compare_digest(self.headers.get("Authorization", ""), expected)
                        assert set(values) == {"grant_type", "code", "redirect_uri", "code_verifier"}
                        assert values["grant_type"] == "authorization_code" and values["redirect_uri"] == fixture.redirect_uri
                        with fixture.lock: flow = fixture.codes.pop(values["code"])
                        assert time.monotonic() - flow["created"] <= 120
                        challenge = base64.urlsafe_b64encode(hashlib.sha256(values["code_verifier"].encode()).digest()).decode().rstrip("=")
                        assert hmac.compare_digest(challenge, flow["code_challenge"])
                        now = int(time.time())
                        token = fixture.signer({"iss": fixture.origin, "sub": "deployment-owner", "aud": fixture.client_id,
                            "iat": now - 1, "exp": now + 120, "nonce": flow["nonce"], "name": "Synthetic Owner"})
                        fixture.counts["token"] += 1
                        self.reply(200, json.dumps({"id_token": token, "access_token": "synthetic-unused-token", "token_type": "Bearer"}).encode())
                except Exception: self.reply(400, b'{"error":"invalid_fixture_request"}')

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.server.daemon_threads = True
        self.origin = "http://127.0.0.1:" + str(self.server.server_port)
        self.thread = threading.Thread(target=self.server.serve_forever, kwargs={"poll_interval": .05}, daemon=True)

    def __enter__(self):
        self.thread.start()
        return self

    def __exit__(self, *_args):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(5)
        assert not self.thread.is_alive()
        self.pending.clear()
        self.codes.clear()
