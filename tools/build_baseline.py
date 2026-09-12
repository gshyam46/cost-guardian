#!/usr/bin/env python
"""Build a real baseline with the same isolated, explicitly opted-in harness."""
from harness import main

if __name__ == "__main__":
    raise SystemExit(main(baseline=True))
