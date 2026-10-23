# -*- coding: utf-8 -*-
"""NAI entry point: GUI terminal, or --selftest for headless verification."""
from __future__ import annotations

import os
import sys


def main():
    args = sys.argv[1:]
    if "--selftest" in args:
        from nai.selftest import run
        sys.exit(run())
    from nai.gui import main as gmain
    gmain()


if __name__ == "__main__":
    main()
