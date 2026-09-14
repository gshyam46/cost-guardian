"""Build an offline wheel using the selected interpreter's build dependencies."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", default=str(Path(__file__).resolve().parent / "dist"))
    args = parser.parse_args()
    output = Path(args.output).resolve()
    output.mkdir(parents=True, exist_ok=True)
    # pip invokes the pinned PEP 517 backend without contacting an index. Build
    # tooling belongs in the selected isolated environment, never customer apps.
    env = dict(os.environ, SOURCE_DATE_EPOCH="1789257600", PYTHONHASHSEED="0")
    subprocess.run([sys.executable, "-m", "pip", "wheel", "--no-index", "--no-deps",
                    "--no-build-isolation", "--wheel-dir", str(output),
                    str(Path(__file__).resolve().parent)], env=env, check=True)
    wheel = output / "sillage_observe-0.2.0-py3-none-any.whl"
    print(json.dumps({"artifact": wheel.name,
                      "sha256": hashlib.sha256(wheel.read_bytes()).hexdigest()}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
