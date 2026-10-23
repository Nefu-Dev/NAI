# -*- coding: utf-8 -*-
"""NAI autostart / persistence — register NAI to launch at Windows logon so it
"keeps running" across shutdown/restart, and persist the choice in the system.

Two mechanisms (both live in the Windows registry / Task Scheduler, i.e. stored
"in the system"):
  * Task Scheduler (preferred): a logon-triggered task, survives user account
    changes better, can run even if the user isn't focused.
  * Startup-registry Run key (fallback): HKCU\\...\\CurrentVersion\\Run.

Public API:
  register(command=None)   — create/refresh the autostart entry
  unregister()            — remove it
  status()                — "on"/"off"/"error" + detail
  command_for(repo)       — build the launch command (used by CLI/GUI)

Reversible and safe: nothing is ever run at build time; the entry only makes NAI
launch at next logon. `/autostart on|off|status` drives it interactively.
"""
from __future__ import annotations

import os
import subprocess
import sys

TASK_NAME = "NAI_Agent"
RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
RUN_VALUE = "NAI_Agent"


def _pythonw_or_python():
    # Prefer the venv python, else the running interpreter, else pythonw.
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # repo root
    venv = os.path.join(here, ".venv", "Scripts", "python.exe")
    if os.path.isfile(venv):
        return venv
    py = sys.executable
    return py.replace("python.exe", "pythonw.exe") if py.lower().endswith("python.exe") else py


def command_for(repo: str) -> str:
    """Build a launch command string that starts NAI's GUI terminal.

    Prefers the current SOURCE launcher (venv python + run_nai.py) so the
    autostart picks up the latest code; falls back to dist\\NAI.exe only when
    there is no usable venv python (e.g. the packaged build is the only copy).
    """
    venv = os.path.join(repo, ".venv", "Scripts", "python.exe")
    launcher = os.path.join(repo, "run_nai.py")
    if os.path.isfile(venv) and os.path.isfile(launcher):
        return f'"{venv}" "{launcher}"'
    exe = os.path.join(repo, "dist", "NAI.exe")
    if os.path.isfile(exe):
        return f'"{exe}"'
    return f'"{_pythonw_or_python()}" "{launcher}"'


def _schtasks(args):
    cmd = ["schtasks"] + args
    # NOTE: schtasks on a Chinese Windows emits cp936 text; we don't need its
    # output (only the exit code), so discard stdout/stderr to avoid any
    # decoding crash. CREATE_NO_WINDOW keeps it from flashing a console.
    return subprocess.run(cmd, capture_output=False, text=False,
                          stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                          creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))


def register(command: str = None) -> str:
    if os.name != "nt":
        return "autostart only supported on Windows"
    repo = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    cmd = command or command_for(repo)
    # Try Task Scheduler first (logon trigger, runs hidden minimized).
    # /TR has a 32-char-per-arg quoting quirk; keep the command simple.
    r = _schtasks(["/Create", "/F", "/TN", TASK_NAME, "/SC", "ONLOGON",
                   "/TR", cmd, "/RL", "LIMITED"])
    if r.returncode == 0:
        return f"autostart ON (Task Scheduler, at logon): {cmd}"
    # Fallback: HKCU Run registry value.
    try:
        import winreg
        k = winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE)
        winreg.SetValueEx(k, RUN_VALUE, 0, winreg.REG_SZ, cmd)
        winreg.CloseKey(k)
        return f"autostart ON (registry Run key): {cmd}"
    except Exception as e:
        return f"autostart register failed: {e}"


def unregister() -> str:
    if os.name != "nt":
        return "autostart only supported on Windows"
    r = _schtasks(["/Delete", "/F", "/TN", TASK_NAME])
    removed_task = r.returncode == 0
    removed_reg = False
    try:
        import winreg
        k = winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE)
        try:
            winreg.DeleteValue(k, RUN_VALUE)
            removed_reg = True
        except OSError:
            pass
        winreg.CloseKey(k)
    except Exception:
        pass
    if removed_task or removed_reg:
        return "autostart OFF (removed)"
    return "autostart not registered (nothing to remove)"


def status() -> str:
    if os.name != "nt":
        return "autostart only supported on Windows"
    r = _schtasks(["/Query", "/TN", TASK_NAME])
    task_on = r.returncode == 0
    reg_on = False
    try:
        import winreg
        k = winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_READ)
        try:
            reg_on = bool(winreg.QueryValueEx(k, RUN_VALUE)[0])
        except OSError:
            reg_on = False
        winreg.CloseKey(k)
    except Exception:
        pass
    detail = []
    if task_on:
        detail.append("Task Scheduler task present")
    if reg_on:
        detail.append("registry Run value present")
    state = "on" if (task_on or reg_on) else "off"
    return f"autostart: {state}" + ((" — " + "; ".join(detail)) if detail else "")
