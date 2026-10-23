# -*- coding: utf-8 -*-
"""NAI isolation modes — user-selectable safety level for file / command /
control / web / MCP actions.

The user picks ONE of four modes (persisted to <workspace>/nai_isolation.txt
so the choice survives restarts):

  full    (全部隔离)          — default. Strict sandbox (only allowed roots) +
                                confirm on every shell command, file mutation
                                outside the workspace, PC control, MCP, web.
  partial (部分危险指令隔离)    — only *dangerous* instructions stay isolated:
                                dangerous commands / PC control / destructive
                                actions still ask; normal commands & file ops
                                auto-run (no per-action confirmation).
  ai      (AI判断隔离)        — the model itself judges each operation's risk;
                                judged safe -> auto-run, risky -> ask, dangerous
                                -> block. PC control always asks.
  none    (无隔离)            — no sandbox, no confirmation, no blocklist.
                                An absolute safety floor (destroy-the-system
                                commands) is NEVER disabled, even here.

Decisions are made per risk *kind* (file / shell / mcp / web / control /
clipboard) by :class:`IsolationPolicy`, then enforced by SafeTools._gate.
"""
from __future__ import annotations

import os

MODES = ("full", "partial", "ai", "none")

MODE_LABELS = {
    "full": "全部隔离",
    "partial": "部分危险指令隔离",
    "ai": "AI判断隔离",
    "none": "无隔离",
}

# Risk kinds (what kind of operation is being gated).
K_FILE = "file"        # write / move / copy / delete / mkdir / touch files
K_SHELL = "shell"      # run a command
K_MCP = "mcp"          # call an MCP tool
K_WEB = "web"          # open a URL / fetch a page / web search
K_CONTROL = "control"  # PC control (supervisor: click / type / press / scroll)
K_CLIPBOARD = "clipboard"

# Risk kinds that stay confirmed even in "partial" (dangerous-instruction-only
# isolation) because they can directly control the machine.
_ALWAYS_CONFIRM_PARTIAL = (K_CONTROL,)

# Absolute safety floor: these can destroy the OS or user data irrecoverably.
# Kept blocked in EVERY mode — including "none" — and cannot be disabled.
HARD_BLOCK = [
    "rm -rf /", "rm -rf c:", "rm -rf d:", "del /f /s", "rd /s",
    "format ", "diskpart", "bcdedit", "net user", "net localgroup",
    "reg delete", "sc delete", "shutdown ", "cipher /w", "takeown",
]


class IsolationPolicy:
    """Holds the current isolation mode + persistence. Decision logic is thin:
    SafeTools._gate maps mode+kind to auto / ask / block."""

    def __init__(self, mode: str = "full"):
        self.mode = mode if mode in MODES else "full"
        self._judge = None  # callable(desc:str) -> 0(safe)|1(risky)|2(dangerous)

    # ---- judge wiring (used only in "ai" mode) ----
    def set_judge(self, fn):
        self._judge = fn

    @property
    def judge(self):
        return self._judge

    # ---- queries ----
    def label(self):
        return MODE_LABELS.get(self.mode, self.mode)

    def describes(self):
        return {
            "full": "严格沙盒 + 每项操作逐条确认",
            "partial": "仅危险指令/电脑控制确认，普通命令与文件操作自动执行",
            "ai": "模型逐条判断操作风险（安全=自动，有风险=询问，危险=拦截）",
            "none": "无沙盒、无确认、无拦截（保留毁机级安全底线）",
        }.get(self.mode, self.mode)

    def relaxes(self, kind: str) -> bool:
        """True if the current mode auto-runs operations of `kind` (no confirm)."""
        if self.mode == "none":
            return True
        if self.mode == "partial":
            return kind not in _ALWAYS_CONFIRM_PARTIAL
        return False  # full: confirm everything; ai: judged per-op

    # ---- persistence ----
    def load(self, path: str):
        try:
            with open(path, "r", encoding="utf-8") as f:
                m = f.read().strip().lower()
            if m in MODES:
                self.mode = m
        except OSError:
            pass
        return self

    def save(self, path: str):
        try:
            with open(path, "w", encoding="utf-8") as f:
                f.write(self.mode)
        except OSError:
            pass


def normalize_mode(raw: str) -> str:
    raw = (raw or "").strip().lower()
    alias = {
        "全部隔离": "full", "完全隔离": "full", "严格": "full", "f": "full",
        "部分危险指令隔离": "partial", "部分": "partial", "危险隔离": "partial",
        "ai": "ai", "ai判断": "ai", "ai判断隔离": "ai", "智能判断": "ai", "判断": "ai",
        "无隔离": "none", "无": "none", "none": "none", "不隔离": "none", "n": "none",
    }
    if raw in alias:
        return alias[raw]
    if raw in MODES:
        return raw
    return "full"  # unknown -> safe default
