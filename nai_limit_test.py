# -*- coding: utf-8 -*-
"""Test: no output limits + screenshot/image-recognition without supervisor."""
from __future__ import annotations
import os, sys, tempfile
ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)
from nai.tools import SafeTools

ok = []
def check(name, cond, detail=""):
    ok.append((name, bool(cond)))
    print(("PASS " if cond else "FAIL ") + name + ("  " + str(detail) if detail else ""))

ws = tempfile.mkdtemp(prefix="nai_limit_")
big = os.path.join(ws, "big.txt")
with open(big, "w", encoding="utf-8") as f:
    f.write("X" * 500_000)  # 500KB — was refused at 200KB before

tools = SafeTools(ws)
tools.isolation.mode = "none"
tools.sandbox_enabled = False

# read_file returns the FULL 500KB, no refusal, no truncation
r = tools.read_file(big)
check("read_file no limit (500KB full)", len(r) == 500_000 and "truncat" not in r[:40],
      f"len={len(r)}")

# read_limit can be set and enforced
tools.set_read_limit("1000")
try:
    tools.read_file(big)
    check("read_limit enforces", False)
except Exception:
    check("read_limit enforces", True)
tools.set_read_limit("off")
r2 = tools.read_file(big)
check("read_limit off = unlimited again", len(r2) == 500_000)
check("set_read_limit accepts bytes/off",
      tools.set_read_limit("0").startswith("read_limit"))

# shell output cap is configurable (just check the field exists and cap logic)
check("shell_output_limit default 24000", tools.shell_output_limit == 24000)
tools.shell_output_limit = 0
import subprocess
out = tools.shell("echo hi")
check("shell output still works (unlimited cap)", "hi" in out)

# screenshot / detect_image no longer require supervisor master switch
try:
    err = ""
    try:
        tools.execute("screenshot", [])
    except Exception as e:
        err = str(e)
    check("screenshot does not require supervisor", "requires supervisor" not in err, err[:60])
except Exception as e:
    check("screenshot does not require supervisor", False, str(e)[:60])

print("\n===== %d/%d passed =====" % (sum(1 for _, c in ok if c), len(ok)))
sys.exit(0 if all(c for _, c in ok) else 1)
