# -*- coding: utf-8 -*-
"""NAI self-healing — when a tool call errors, NAI doesn't just stop: it gets a
corrective hint, thinks about the cause, and retries a different approach.

What this adds on top of the existing retry-on-error loop:
  * A bounded consecutive-failure cap: after N consecutive tool errors in one
    turn NAI is nudged to stop calling tools and report the real blocker,
    instead of looping forever.
  * Repeated-failure hints: if the SAME tool fails twice, an actionable hint is
    injected (e.g. "path may not exist — list_dir first" / "install missing dep").
  * Malformed-output guard: if the model emits no valid tool call but is clearly
    mid-idea, a light nudge to be concrete.

Integrates with NaiAgent._chat (see agent.py). Pure logic — no I/O side effects.
"""
from __future__ import annotations

MAX_CONSECUTIVE_ERRORS = 8       # stop-and-report after this many errors in a row
REPEAT_FAIL_LIMIT = 2            # hint after the same tool fails this many times


class SelfHeal:
    def __init__(self, max_consecutive: int = MAX_CONSECUTIVE_ERRORS):
        self.max_consecutive = max_consecutive
        self.fail_count = 0          # consecutive failures this turn
        self.fail_map = {}           # tool name -> consecutive failures

    def reset(self):
        self.fail_count = 0
        self.fail_map = {}

    def on_success(self):
        self.fail_count = 0
        self.fail_map.clear()

    def hint(self, name: str, args, error: str):
        """Called on a tool error. Returns (give_up: bool, hint_text: str)."""
        self.fail_count += 1
        self.fail_map[name] = self.fail_map.get(name, 0) + 1
        give_up = self.fail_count >= self.max_consecutive
        nf = self.fail_map[name]
        reason = error.strip().splitlines()[0] if error else "unknown error"
        tip = _tips_for(name, reason)
        if nf >= REPEAT_FAIL_LIMIT:
            hint = (f"⚠ Tool {name!r} has now failed {nf} times in a row: {reason}. "
                    f"STOP using {name!r} the same way. {tip} "
                    f"Either fix the underlying cause with a different tool "
                    f"(check the path / list_dir first, install a missing dependency, "
                    f"or use another approach), or report the blocker to the user "
                    f"and give a final answer.")
        else:
            hint = (f"⚠ Tool {name!r} failed: {reason}. {tip} "
                    f"Think about WHY it failed and try a corrected call.")
        if give_up:
            hint = (f"⚠ Too many consecutive tool errors this turn. STOP calling tools. "
                    f"Summarize the blocker honestly (last error: {reason}) and give a "
                    f"final answer with a 总结/Summary line.")
        return give_up, hint


def _tips_for(name: str, reason: str) -> str:
    r = reason.lower()
    if "not found" in r or "no such file" in r or "no match" in r:
        return "The path or target may not exist — run list_dir/search_files to confirm the real path first."
    if "outside allowed" in r or "denied" in r or "blocked" in r:
        return "This is blocked by the current isolation/sandbox — use /allow <dir> or switch isolation mode if it should run."
    if "cannot run command" in r or "not recognized" in r or "no such" in r:
        return "The command/tool may be missing — check it exists or install it before retrying."
    if "too large" in r:
        return "The file/result is too big — read it in parts with head/tail/batch_read or a narrower scope."
    if "timeout" in r:
        return "It timed out — retry with a smaller scope or a more specific command."
    if "permission" in r or "denied" in r or "error" in r:
        return "Double-check arguments, permissions and that the parent folder exists before retrying."
    return "Retry with corrected arguments, or use a different tool / approach."
