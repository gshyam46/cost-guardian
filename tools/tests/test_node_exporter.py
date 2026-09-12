"""Include dependency-free Node exporter tests in the existing CI discovery job."""
import os
from pathlib import Path
import shutil
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[2]
SYSTEM_KEYS = {"SYSTEMROOT", "WINDIR", "SYSTEMDRIVE", "COMSPEC", "PATH", "PATHEXT", "TEMP", "TMP", "TMPDIR",
               "HOME", "USERPROFILE", "APPDATA", "LOCALAPPDATA", "LANG", "LC_ALL", "LC_CTYPE"}


class NodeExporter(unittest.TestCase):
    def test_node_background_exporter(self):
        node = shutil.which("node")
        if not node:
            self.fail("Node is required for exporter verification; install the repository-supported Node version")
        env = {key: value for key, value in os.environ.items() if key.upper() in SYSTEM_KEYS}
        result = subprocess.run([node, "--test", "tools/tests/node_exporter.test.mjs"], cwd=ROOT,
                                env=env, capture_output=True, text=True, timeout=60)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
