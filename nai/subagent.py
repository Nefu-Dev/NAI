# -*- coding: utf-8 -*-
"""NAI sub-agents — decompose a job into parallel sub-agents.

A sub-agent is an independent worker with its own conversation context that runs
a subtask (with tools) and returns a result. NAI spawns several at once to e.g.
"read these 3 files and each summarize", "draft 3 versions", "check 3 folders".

Concurrency honest limit: the sub-agents share the single local GGUF model, and
LLM *generation* is serialized by worker.NaiModel._lock. What parallelizes for
real is their file / web / MCP I/O plus orchestration. This is documented in the
README; do not claim true parallel inference.

Public API:
  NaiSubAgent — one worker (own history + own SafeTools + own isolation)
  spawn_subagents(model, tasks, workspace, ...) -> list of result dicts
  fmt_results(results) -> a compact text block for the parent agent
"""
from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor, as_completed

from . import prompt as P
from .tools import SafeTools, ToolError

MAX_SUB_TOOL_CALLS = 40  # per sub-agent safety valve


class NaiSubAgent:
    def __init__(self, model, name: str, workspace: str,
                 confirm_hook=None, max_tokens: int = 1024):
        self.model = model
        self.name = name
        self.tools = SafeTools(workspace)
        self.tools.confirm_hook = confirm_hook
        self.history = []
        self.max_tokens = max_tokens

    # ---- a single subtask: chat loop with tools (mirrors NaiAgent._chat) ----
    def run(self, task: str):
        self.history.append({"role": "user", "content": task})
        executed = set()
        mt = int(self.max_tokens)
        while True:
            text, stats = self.model.generate(self._messages(), max_tokens=mt)
            calls = P.parse_tool_calls(text)
            if not calls:
                return P.strip_tool_markers(text), stats
            new_calls = [(n, a) for (n, a) in calls if (n, repr(a)) not in executed]
            if not new_calls:
                self.history.append({"role": "user", "content": P.NUDGE})
                t2, s2 = self.model.generate(self._messages(), max_tokens=mt)
                return P.strip_tool_markers(t2), s2
            for name, args in new_calls:
                executed.add((name, repr(args)))
                self.history.append({"role": "assistant",
                                     "content": P.fmt_tool_call(name, args)})
                try:
                    result = self.tools.execute(name, args)
                    ok = True
                except ToolError as e:
                    result, ok = str(e), False
                self.history.append({"role": "user", "content": P.fmt_result(ok, result)})
            if len(executed) >= MAX_SUB_TOOL_CALLS:
                self.history.append({"role": "user", "content": P.NUDGE})
                t2, s2 = self.model.generate(self._messages(), max_tokens=mt)
                return P.strip_tool_markers(t2), s2

    def _messages(self):
        from . import environment
        system = P.SYSTEM
        env = environment.environment_summary(self.tools.workspace)
        system = env + "\n\n" + system
        combined = [{"role": "system", "content": system}] + list(self.history)
        n_ctx = int(getattr(self.model, "n_ctx", 2048))
        budget = max(128, n_ctx - 256)

        def tl(msgs):
            return sum(max(1, len(m["content"]) // 2) for m in msgs)

        while len(combined) > 1 and tl(combined) > budget:
            combined.pop(1)
        return combined


def spawn_subagents(model, tasks, workspace, max_workers=None,
                    confirm_hook=None, max_tokens=1024):
    """Run `tasks` (iterable of strings) in parallel sub-agents.
    Returns a list aligned with `tasks`: {"ok": bool, "name", "text", "stats"|"error"}."""
    tasks = list(tasks)
    if not tasks:
        return []
    workers = min(max_workers or 4, len(tasks)) if tasks else 1
    results = [None] * len(tasks)

    with ThreadPoolExecutor(max_workers=workers) as ex:
        futs = {}
        for i, t in enumerate(tasks):
            sa = NaiSubAgent(model, f"subagent-{i + 1}", workspace,
                             confirm_hook=confirm_hook, max_tokens=max_tokens)
            futs[ex.submit(sa.run, t)] = i
        for f in as_completed(futs):
            i = futs[f]
            try:
                text, stats = f.result()
                results[i] = {"ok": True, "name": f"subagent-{i + 1}",
                              "text": text, "stats": stats}
            except Exception as e:
                results[i] = {"ok": False, "name": f"subagent-{i + 1}",
                              "error": str(e)}
    return results


def fmt_results(results):
    if not results:
        return "(no sub-agent tasks)"
    parts = []
    for i, r in enumerate(results, 1):
        if r.get("ok"):
            st = r.get("stats") or {}
            head = f"===== subagent-{i} result ({st.get('tokens', 0)} tok, " \
                   f"{st.get('tok_s', 0)} tok/s) ====="
            parts.append(f"{head}\n{r['text']}")
        else:
            parts.append(f"===== subagent-{i} ERROR =====\n{r.get('error')}")
    return "\n\n".join(parts)
