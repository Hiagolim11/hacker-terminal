#!/usr/bin/env python3
"""Executable entry point for Hacker Terminal."""

import sys

from hackerterminal.launcher import forward


if __name__ == "__main__":
    # A Hacker Terminal already open takes the new window (fast, no GTK load).
    code = forward(sys.argv[1:])
    if code is None:
        from hackerterminal.cli import main

        code = main()
    raise SystemExit(code)
