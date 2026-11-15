#!/usr/bin/env python3
"""Compatibility shim: `python main.py` still works.

The implementation lives in the `imgshrink` package. Prefer one of:

    python -m imgshrink
    imgshrink            # after `pip install -e .`
"""

from imgshrink.cli import run

if __name__ == "__main__":
    run()
