# -*- coding: utf-8 -*-
"""NAI command-line entry:  python run_nai_cli.py
Beautiful console terminal — watch the AI think, call tools, and answer."""
from __future__ import annotations

import sys


def main():
    from nai.cli import main as climain
    climain()


if __name__ == "__main__":
    main()
