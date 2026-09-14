"""Safety boundaries for opt-in installed OTel verification."""
from contextlib import redirect_stdout
import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

PATH = Path(__file__).resolve().parents[1] / "test_otel.py"
spec = importlib.util.spec_from_file_location("otel_harness", PATH)
harness = importlib.util.module_from_spec(spec)
spec.loader.exec_module(harness)


class HarnessBoundaries(unittest.TestCase):
    def test_no_arguments_and_help_need_only_stdlib(self):
        for arguments in ([], ["--help"]):
            result = subprocess.run([sys.executable, "-I", "-S", str(PATH), *arguments], capture_output=True, timeout=10)
            self.assertEqual(result.returncode, 0)
            self.assertIn(b"--dependency-python", result.stdout)
            self.assertEqual(result.stderr, b"")

    def test_nonlocal_database_is_rejected_before_install(self):
        output = io.StringIO()
        with patch.object(harness, "install") as install, redirect_stdout(output):
            status = harness.main(["--wheel", "unused.whl", "--mongo-url", "mongodb://example.com"])
        self.assertEqual(status, 1)
        self.assertEqual(json.loads(output.getvalue())["code"], "invalid_local_mongo_url")
        install.assert_not_called()

    def test_invalid_report_path_is_not_written(self):
        with tempfile.TemporaryDirectory(prefix="sillage-otel-boundary-") as temporary:
            wheel = Path(temporary) / "fixture.whl"
            wheel.write_bytes(b"not installed")
            destination = Path(temporary) / "outside-report.json"
            with patch.object(harness, "install") as install, redirect_stdout(io.StringIO()):
                status = harness.main(["--wheel", str(wheel), "--sdk-python", sys.executable,
                    "--mongo-url", "mongodb://127.0.0.1:27021/?replicaSet=guardian-r102&directConnection=true",
                    "--report", str(destination)])
            self.assertEqual(status, 1)
            self.assertFalse(destination.exists())
            install.assert_not_called()

    def test_secrets_and_telemetry_destinations_are_not_inherited(self):
        names = ["OPENAI_API_KEY", "SILLAGE_INGEST_KEY", "GUARDIAN_API_KEY", "GITHUB_TOKEN", "MONGO_URL",
                 "HTTPS_PROXY", "PYTHONPATH", "OTEL_EXPORTER_OTLP_ENDPOINT", "LANGSMITH_API_KEY"]
        with patch.dict(os.environ, {name: "must-not-inherit" for name in names}):
            env = harness.environment()
        self.assertTrue(all(name not in env for name in names))
        self.assertEqual(env["PYTHON_DOTENV_DISABLED"], "1")
        self.assertEqual(env["LANGSMITH_TRACING"], "false")

    def test_duplicate_phases_rejected_before_install(self):
        with tempfile.TemporaryDirectory(prefix="sillage-otel-boundary-") as temporary:
            wheel = Path(temporary) / "fixture.whl"
            wheel.write_bytes(b"not installed")
            with patch.object(harness, "install") as install, redirect_stdout(io.StringIO()):
                status = harness.main(["--wheel", str(wheel), "--sdk-python", sys.executable,
                    "--mongo-url", "mongodb://127.0.0.1:27021/?replicaSet=guardian-r102&directConnection=true",
                    "--phases", "programmatic", "programmatic"])
            self.assertEqual(status, 1)
            install.assert_not_called()


if __name__ == "__main__":
    unittest.main()
