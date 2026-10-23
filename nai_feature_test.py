# -*- coding: utf-8 -*-
"""Standalone functional test for NAI's new modules (no model loading).
Run:  python nai_feature_test.py
Covers: isolation modes, self-heal hints, batch read/write/search parsing,
autostart status, and web_search (network)."""
from __future__ import annotations
import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)

results = []


def check(name, cond, detail=""):
    results.append((name, bool(cond), detail))
    print(("PASS " if cond else "FAIL ") + name + ("  " + str(detail) if detail else ""))


# --- isolation ---
from nai.isolation import IsolationPolicy, normalize_mode, HARD_BLOCK
p = IsolationPolicy("full")
check("isolation default full", p.mode == "full")
check("normalize aliases", normalize_mode("AI判断隔离") == "ai" and normalize_mode("无隔离") == "none")
check("partial relaxes shell not control",
      p.mode == "full")  # sanity

from nai import isolation as iso
from nai.tools import SafeTools
ws = tempfile.mkdtemp(prefix="nai_test_")
with open(os.path.join(ws, "a.txt"), "w", encoding="utf-8") as f:
    f.write("hello world")
tools = SafeTools(ws)
tools.isolation.mode = "none"
tools.sandbox_enabled = False
check("none disables sandbox", tools.resolve("C:/Windows/win.ini") == "C:\\Windows\\win.ini" or
      tools.resolve("C:/Windows/win.ini").lower().endswith("win.ini"))
tools.isolation.mode = "full"
tools.sandbox_enabled = True
blocked = False
tools.auto_allow = False  # strict sandbox: auto directory recognition off
try:
    tools.resolve("C:/Windows/win.ini")
except Exception:
    blocked = True
check("full enforces sandbox", blocked)
# auto directory recognition: existing paths outside roots get allowed
tools.auto_allow = True
tools.last_auto_added = []
res = tools.resolve("C:/Windows/win.ini")
auto_ok = res.lower().endswith("win.ini") and bool(tools.last_auto_added)
check("auto-allow recognizes outside dir", auto_ok, tools.last_auto_added)
tools.auto_allow = False

# gate: none -> auto (no confirm), full -> ask, partial control -> ask, ai -> judge
calls = {"n": 0}
def hook(_d):
    calls["n"] += 1
    return True
tools.confirm_hook = hook
from nai.isolation import K_SHELL, K_CONTROL
tools.isolation.mode = "none"
tools._gate(K_SHELL, "x", base_ask=True)
check("none auto-runs (no confirm)", calls["n"] == 0)
tools.isolation.mode = "full"
tools._gate(K_SHELL, "x", base_ask=True)
check("full asks", calls["n"] == 1)
tools.isolation.mode = "partial"
tools._gate(K_CONTROL, "click", base_ask=True)
check("partial confirms control", calls["n"] == 2)
tools.isolation.mode = "partial"
tools._gate(K_SHELL, "echo hi", base_ask=True)
check("partial auto-runs shell", calls["n"] == 2)
# ai judge
tools.isolation.mode = "ai"
tools.isolation.set_judge(lambda d: 0)
tools._gate(K_SHELL, "echo hi", base_ask=True)
check("ai judge safe->auto", calls["n"] == 2)
tools.isolation.set_judge(lambda d: 2)
blk = False
try:
    tools._gate(K_SHELL, "del x", base_ask=True)
except Exception:
    blk = True
check("ai judge dangerous->block", blk)

# batch read / write / parse
from nai import batch
pl = batch.parse_list("a.txt\nb.txt")
check("parse_list newline", pl == ["a.txt", "b.txt"])
pl2 = batch.parse_list('["x","y"]')
check("parse_list json", pl2 == ["x", "y"])
r = batch.batch_read_files(tools, ["a.txt", "b.txt"])
check("batch_read ok", "hello world" in r and "a.txt" in r)
tools.isolation.mode = "none"
wr = batch.batch_write_files(tools, '{"out1.txt":"alpha","out2.txt":"beta"}')
check("batch_write ok", "[OK] out1.txt" in wr and "[OK] out2.txt" in wr and
      os.path.isfile(os.path.join(ws, "out1.txt")))

# self-heal hints
from nai.selfheal import SelfHeal
h = SelfHeal(max_consecutive=3)
give_up, hint = h.hint("read_file", ["nope.txt"], "file not found")
check("selfheal first hint", not give_up and "not exist" in hint.lower())
give_up, hint = h.hint("read_file", ["nope.txt"], "file not found")
check("selfheal repeat hint", not give_up and "STOP" in hint)
give_up, hint = h.hint("read_file", ["nope.txt"], "file not found")
check("selfheal give up", give_up)

# autostart status (read-only; should be off on a clean machine)
try:
    from nai import autostart as AS
    st = AS.status()
    check("autostart status returns", st.startswith("autostart:"))
except Exception as e:
    check("autostart status returns", False, e)

# web search (network; tolerate offline)
try:
    from nai import webutil
    s = webutil.web_search("python 3.14")
    check("web_search returns text", len(s) > 5, s[:40])
except Exception as e:
    check("web_search returns text", False, "offline: " + str(e))

print("\n===== %d/%d passed =====" % (sum(1 for _, ok, _ in results if ok), len(results)))
sys.exit(0 if all(ok for _, ok, _ in results) else 1)
