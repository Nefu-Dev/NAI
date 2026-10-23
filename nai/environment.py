# -*- coding: utf-8 -*-
"""Environment snapshot injected into the system prompt so NAI knows this
computer (OS / Python / CPU / RAM / host / workspace / time)."""
from __future__ import annotations

import os
import platform
import socket
import sys
import time


def environment_summary(workspace: str = "") -> str:
    lines = ["Environment (this computer):"]
    try:
        lines.append(f"- OS: {platform.system()} {platform.release()} ({platform.machine()})")
    except Exception:
        lines.append(f"- OS: {platform.platform()}")
    try:
        lines.append(f"- Python: {sys.version.split()[0]}")
    except Exception:
        pass
    try:
        lines.append(f"- CPU: {platform.processor() or 'unknown'} · {os.cpu_count()} cores")
    except Exception:
        lines.append(f"- CPU cores: {os.cpu_count()}")
    try:
        import psutil
        vm = psutil.virtual_memory()
        lines.append(f"- RAM: {vm.total // 2**30} GB total, {vm.available // 2**30} GB free")
    except Exception:
        pass
    try:
        lines.append(f"- Host: {socket.gethostname()}")
    except Exception:
        pass
    lines.append(f"- Workspace: {workspace or os.getcwd()}")
    lines.append(f"- Date/time: {time.strftime('%Y-%m-%d %H:%M %A')}")
    return "\n".join(lines)
