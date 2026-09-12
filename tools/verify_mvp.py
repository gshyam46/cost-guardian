#!/usr/bin/env python
"""Safe verification CLI. No arguments print help; live traffic requires opt-in."""
from harness import main

if __name__ == "__main__":
    raise SystemExit(main())
