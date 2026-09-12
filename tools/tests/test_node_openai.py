"""Run independent built-in Node provider adapter assertions without npm packages."""
from pathlib import Path
import shutil
import subprocess
import unittest


class NodeOpenAI(unittest.TestCase):
    def test_node_openai_adapters(self):
        node = shutil.which("node")
        self.assertIsNotNone(node, "Node is required for provider adapter verification")
        result = subprocess.run([node, "--test", str(Path(__file__).with_suffix(".mjs"))],
                                capture_output=True, text=True, timeout=60)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
