# -*- coding: utf-8 -*-
"""NAI agent loop: chat + tool calling (read/list/write file, shell).
Runs on a background thread; reports events through a callback.
"""
from __future__ import annotations

import os
import re
import time

from . import prompt as P
from .tools import SafeTools, ToolError
from .selfheal import SelfHeal

# The currently active model, exposed so sub-agent tools can reach the same
# (single, lock-guarded) model instance. Set by NaiAgent.
_ACTIVE_MODEL = None


def _current_model():
    return _ACTIVE_MODEL


class NaiAgent:
    def __init__(self, model, workspace: str, confirm_hook=None,
                 autoshell=True, max_tool_calls=None, max_tokens=2048):
        global _ACTIVE_MODEL
        self.model = model
        _ACTIVE_MODEL = model
        self.tools = SafeTools(workspace)
        self.tools.confirm_hook = confirm_hook
        self.autoshell = autoshell
        # Tool calls are UNLIMITED with no cap and no guard: the loop only ends
        # when the model answers without calling a tool, or repeats an already
        # executed call. (Interrupt anytime with Ctrl+C.)
        self.max_tool_calls = None
        self.max_tokens = max_tokens
        self.heal = SelfHeal()
        self.history = []
        self.rules = []
        self.rules_file = os.path.join(self.tools.workspace, "nai_rules.txt")
        self._load_rules()
        self.goal = None
        self.goal_file = os.path.join(self.tools.workspace, "nai_goal.txt")
        self._load_goal()
        # isolation mode (persisted across restarts)
        self.isolation_file = os.path.join(self.tools.workspace, "nai_isolation.txt")
        self._load_isolation()
        # project context (auto-read from README / nai_context.txt in the workspace)
        self.context = None
        self.context_source = None
        self.context_disabled = False
        self._discover_context()

    def _on(self, sink, kind, **kw):
        if sink:
            sink(kind, **kw)

    def run_turn(self, user_text, sink=None):
        """user_text -> events: 'token'|'tool'|'tool_result'|'tool_denied'|'done'."""
        self.history.append({"role": "user", "content": user_text})
        # code requests get a larger output budget so long code can stream fully
        if self._is_code_request(user_text):
            self._eff_max = min(12000, max(self.max_tokens, 2048))
        else:
            self._eff_max = self.max_tokens
        text, stats = self._chat(sink)
        self.history.append({"role": "assistant", "content": text})
        self._on(sink, "done", text=text, stats=stats)

    @staticmethod
    def _is_code_request(text: str) -> bool:
        if re.search(r"(代码|脚本|程序|函数|\.py|\.js|\.cpp|\.c\b|\.go\b|\.rs\b|\.java\b|code|function|script|program|implement|写个|写一个|编写)", text, re.IGNORECASE):
            return True
        return False

    def _chat(self, sink):
        executed = set()
        self.heal.reset()  # fresh self-heal state each turn
        mt = int(getattr(self, "_eff_max", self.max_tokens))
        while True:
            text, stats = self.model.generate(
                self._messages(),
                max_tokens=mt,
                stream_cb=lambda d: (self._on(sink, "token", text=d)),
            )
            calls = P.parse_tool_calls(text)
            if not calls:
                return P.strip_tool_markers(text), stats
            # execute only tool calls we have not run yet (avoids repeated-tool loops)
            new_calls = [(n, a) for (n, a) in calls if (n, repr(a)) not in executed]
            if not new_calls:
                # the model only repeated tools: nudge it to answer and finish
                self.history.append({"role": "user", "content": P.NUDGE})
                t2, s2 = self.model.generate(self._messages(), max_tokens=mt)
                return P.strip_tool_markers(t2), s2
            for name, args in new_calls:
                executed.add((name, repr(args)))
                self.history.append({"role": "assistant",
                                     "content": P.fmt_tool_call(name, args)})
                self._on(sink, "tool", name=name, args=args, raw=text)
                result, ok = self._exec(sink, name, args)
                if ok is None:  # user denied
                    self._on(sink, "tool_denied", name=name, args=args)
                    self.history.append({"role": "user",
                                         "content": P.fmt_result(False, "user denied this action")})
                else:
                    self._on(sink, "tool_result", name=name, ok=ok, result=result)
                    if ok:
                        self.heal.on_success()
                        self.history.append({"role": "user", "content": P.fmt_result(True, result)})
                    else:
                        # self-heal: inject a corrective hint, bounded; give up after
                        # too many consecutive failures and report the blocker.
                        give_up, hint = self.heal.hint(name, args, result)
                        nf = self.heal.fail_map.get(name, 0)
                        feedback = P.fmt_result(False, result)
                        if nf >= 2 or give_up:
                            feedback += "\n" + hint
                        self.history.append({"role": "user", "content": feedback})
                        if give_up:
                            self._on(sink, "tool_result", name=name, ok=False,
                                     result="(gave up after repeated failures)")
                            t2, s2 = self.model.generate(self._messages(), max_tokens=mt)
                            return P.strip_tool_markers(t2), s2
            # loop again so the model can keep working — unlimited, no cap.

    def _token_len(self, text: str) -> int:
        try:
            llm = getattr(self.model, "_llm", None)
            if llm is not None:
                return len(llm.tokenize(text.encode("utf-8", "replace"), add_bos=False))
        except Exception:
            pass
        return max(1, len(text) // 2)

    # ---------- persistent goal ----------
    def _load_goal(self):
        self.goal = None
        try:
            if os.path.isfile(self.goal_file):
                with open(self.goal_file, "r", encoding="utf-8") as f:
                    self.goal = f.read().strip() or None
        except OSError:
            self.goal = None

    def _save_goal(self):
        try:
            if self.goal:
                with open(self.goal_file, "w", encoding="utf-8") as f:
                    f.write(self.goal)
            elif os.path.isfile(self.goal_file):
                os.remove(self.goal_file)
        except OSError:
            pass

    def get_goal(self):
        self._load_goal()
        return self.goal

    def set_goal(self, text: str):
        self.goal = text.strip()
        self._save_goal()

    def clear_goal(self):
        self.goal = None
        self._save_goal()

    def _messages(self):
        from . import environment
        system = P.SYSTEM
        env = environment.environment_summary(self.tools.workspace)
        rules = self.get_rules()
        if rules:
            env += "\n\nUser rules (follow these strictly):\n- " + "\n- ".join(rules)
        goal = self.get_goal()
        if goal:
            env += ("\n\nACTIVE GOAL: " + goal +
                    "\nYou must keep working toward this goal using tools until it is fully "
                    "achieved. Do not end the conversation or claim it is done while the goal is "
                    "unmet. After each step, use tools to verify whether the goal is complete; if "
                    "not, continue with the next step instead of stopping.")
        ctx, src = self.get_context()
        if ctx:
            env += ("\n\nPROJECT CONTEXT (auto-read from " + (src or "context") +
                    " — use it to understand what the user is working on):\n" + ctx)
        system = env + "\n\n" + system
        n_ctx = int(getattr(self.model, "n_ctx", 2048))
        reserve = int(getattr(self, "max_tokens", 512)) + 256  # room for the reply
        budget = max(128, n_ctx - reserve)
        sys_len = self._token_len(system)
        hist = list(self.history)

        def hist_len(ml):
            return sys_len + sum(self._token_len(m["content"]) for m in ml)

        # 1) drop the oldest history turns until the request fits the context.
        while len(hist) > 1 and hist_len(hist) > budget:
            hist.pop(0)

        # 2) if a single (usually the largest) message still overflows, truncate
        #    it so the whole prompt never exceeds n_ctx (fixes the llama_cpp
        #    "Requested tokens exceed context window" crash from big tool results).
        combined = [{"role": "system", "content": system}] + hist
        for idx in range(len(combined) - 1, 0, -1):
            over = hist_len(combined) - budget
            if over <= 0:
                break
            cur = combined[idx]["content"]
            cut = max(0, len(cur) - int(over * 2.2) - 60)
            if cut <= 0:
                combined.pop(idx)
                continue
            combined[idx] = {**combined[idx],
                             "content": cur[:cut] + "\n...(truncated to fit context)"}
        return combined

    # ---------- persistent rules ----------
    def _load_rules(self):
        self.rules = []
        try:
            if os.path.isfile(self.rules_file):
                with open(self.rules_file, "r", encoding="utf-8") as f:
                    self.rules = [l.strip() for l in f.read().splitlines() if l.strip()]
        except OSError:
            pass

    def _save_rules(self):
        try:
            with open(self.rules_file, "w", encoding="utf-8") as f:
                f.write("\n".join(self.rules))
        except OSError:
            pass

    def get_rules(self):
        self._load_rules()
        return list(self.rules)

    def add_rule(self, text: str):
        self._load_rules()
        self.rules.append(text)
        self._save_rules()

    def clear_rules(self):
        self.rules = []
        self._save_rules()

    def _exec(self, sink, name, args):
        # shell confirmation is controlled here (autoshell + confirm_hook)
        if name == "shell" and not self.autoshell:
            return None, None
        try:
            result = self.tools.execute(name, args)
            return result, True
        except ToolError as e:
            return str(e), False

    def set_workspace(self, path):
        self.tools.workspace = os.path.realpath(path)
        self.tools.reload_allowed()  # pick up that workspace's nai_allowed.txt
        self._discover_context()     # re-read the new project's context

    def add_root(self, path):
        return self.tools.add_root(path)

    # ---------- project context (auto-read from the workspace) ----------
    CONTEXT_FILES = ("nai_context.txt", "CONTEXT.md", "context.md",
                     "README.md", "README.txt")

    def _discover_context(self):
        """Scan the workspace for a project context file and cache its text."""
        self.context = None
        self.context_source = None
        if self.context_disabled:
            return
        for name in self.CONTEXT_FILES:
            p = os.path.join(self.tools.workspace, name)
            if not os.path.isfile(p):
                continue
            try:
                with open(p, "r", encoding="utf-8", errors="replace") as f:
                    data = f.read(8000)
            except OSError:
                continue
            data = data.strip()
            if data:
                self.context = data[:6000]
                self.context_source = p
            return

    def get_context(self):
        """Return (context_text, source_path_or_None)."""
        if self.context_disabled:
            return None, None
        return self.context, self.context_source

    def set_context(self, path: str) -> bool:
        """Point the project context at a specific file. Returns success."""
        p = os.path.realpath(path)
        if not os.path.isfile(p):
            return False
        try:
            with open(p, "r", encoding="utf-8", errors="replace") as f:
                data = f.read(8000)
        except OSError:
            return False
        self.context = data.strip()[:6000]
        self.context_source = p
        self.context_disabled = False
        return True

    def clear_context(self):
        """Turn context injection off (rediscover with /context auto)."""
        self.context = None
        self.context_source = None
        self.context_disabled = True

    # ---------- isolation mode (full/partial/ai/none) ----------
    def _load_isolation(self):
        from .isolation import IsolationPolicy
        self.tools.isolation.load(self.isolation_file)
        self.tools.sandbox_enabled = self.tools.isolation.mode != "none"
        if self.tools.isolation.mode == "ai":
            self.tools.isolation.set_judge(self._judge_risk)

    def _save_isolation(self):
        try:
            self.tools.isolation.save(self.isolation_file)
        except Exception:
            pass

    def set_isolation(self, mode: str):
        """Switch isolation mode. Returns (mode, label)."""
        m, label = self.tools.set_isolation(mode)
        if m == "ai":
            self.tools.isolation.set_judge(self._judge_risk)
        self._save_isolation()
        return m, label

    def get_isolation(self):
        return self.tools.get_isolation()

    def _judge_risk(self, desc: str) -> int:
        """AI-judged isolation: the model rates an operation 0(safe)/1(risky)/2(dangerous)."""
        prompt = ("You are a safety reviewer for a local AI. Classify the risk of this "
                  "computer action: 0 = safe, 1 = risky (should ask the user), "
                  "2 = dangerous (must block). Reply with ONLY a single digit.\n"
                  "Action: " + (desc or ""))
        try:
            text, _ = self.model.generate([{"role": "user", "content": prompt}],
                                          max_tokens=8, temperature=0.0)
            for ch in text:
                if ch in "012":
                    return int(ch)
        except Exception:
            pass
        return 1  # judge unavailable -> ask
