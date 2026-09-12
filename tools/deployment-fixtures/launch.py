"""Pass explicit synthetic environment through stdin, then exec the real CLI."""
import json
import os
import subprocess
import sys


def main():
    if sys.argv[1:] != ["--run"]:
        print("Usage: python launch.py --run < synthetic-config.json")
        return 0
    try:
        config = json.loads(sys.stdin.buffer.read(65537))
        assert set(config) == {"environment", "arguments"}
        arguments = config["arguments"]
        assert arguments in (["check"], ["bootstrap"], ["run", "api"], ["run", "worker"])
        assert isinstance(config["environment"], dict)
        assert all(isinstance(key, str) and isinstance(value, str) for key, value in config["environment"].items())
        command = [sys.executable, "-m", "deployment", *arguments]
        if os.name == "nt":
            # The Windows Store venv launcher can crash inside CRT execve.
            # Keep an owned waiting parent; the harness reaps its whole tree.
            return subprocess.call(command, env=config["environment"], stdin=subprocess.DEVNULL,
                                   creationflags=subprocess.CREATE_NO_WINDOW)
        os.execve(sys.executable, command, config["environment"])
    except Exception:
        print('{"status":"failed","code":"fixture_configuration_invalid"}')
        return 1


if __name__ == "__main__": raise SystemExit(main())
