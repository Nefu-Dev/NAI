# -*- coding: utf-8 -*-
"""Local conversation records for NAI.

Every CLI turn is appended to a JSONL session file under
<workspace>/nai_history/<timestamp>.jsonl, so the conversation survives
restarts and can be cut back into at any time:

  /resume [idx|substr]  load a previous session into the model context
  /sessions             list saved sessions (newest first)
  /history [n]          print the last n turns of the current session
  /new                  start a fresh session (old one stays on disk)

Storage format: one JSON object per line, keys:
  {"event": "session_start"} | {"role": "user|assistant", "content": str, "ts": float}
Only user/assistant lines are replayed into the model context on resume.
"""
from __future__ import annotations

import json
import os
import time


class SessionLog:
    def __init__(self, workspace: str):
        self.dir = os.path.join(workspace, "nai_history")
        self.path = None
        self._ensure_dir()

    # ---------- lifecycle ----------
    def _ensure_dir(self):
        try:
            os.makedirs(self.dir, exist_ok=True)
        except OSError:
            pass

    def new(self) -> str:
        """Start a fresh session file (timestamped). Returns its path."""
        self._ensure_dir()
        ts = time.strftime("%Y%m%d_%H%M%S")
        self.path = os.path.join(self.dir, f"{ts}.jsonl")
        self._write({"event": "session_start", "ts": time.time()})
        return self.path

    def _write(self, obj):
        if not self.path:
            return
        try:
            with open(self.path, "a", encoding="utf-8") as f:
                f.write(json.dumps(obj, ensure_ascii=False) + "\n")
        except OSError:
            pass

    def append(self, role: str, content: str):
        """Append one turn (role: 'user' | 'assistant') to the current session."""
        if not self.path:
            self.new()
        self._write({"role": role, "content": content, "ts": time.time()})

    # ---------- listing / loading ----------
    def list_sessions(self):
        """Sessions newest-first: [{path, turns, first}]."""
        out = []
        try:
            names = sorted(os.listdir(self.dir), reverse=True)
        except OSError:
            return out
        for fn in names:
            if not fn.endswith(".jsonl"):
                continue
            p = os.path.join(self.dir, fn)
            turns = 0
            first = ""
            try:
                with open(p, "r", encoding="utf-8") as f:
                    for line in f:
                        if not line.strip():
                            continue
                        try:
                            o = json.loads(line)
                        except (ValueError, TypeError):
                            continue
                        if o.get("role") == "user":
                            turns += 1
                            if not first:
                                first = o.get("content", "").splitlines()[0][:60]
                        elif o.get("role") == "assistant":
                            turns += 1
            except OSError:
                continue
            out.append({"path": p, "turns": turns, "first": first})
        return out

    def load(self, path: str = None, max_turns: int = None):
        """Read a session file into [{role, content}] messages.

        max_turns limits how many complete turns (user+assistant) are kept
        from the tail — used by /resume to avoid overflowing the context.
        """
        path = path or self.path
        msgs = []
        try:
            with open(path, "r", encoding="utf-8") as f:
                for line in f:
                    if not line.strip():
                        continue
                    try:
                        o = json.loads(line)
                    except (ValueError, TypeError):
                        continue
                    if o.get("role") in ("user", "assistant"):
                        msgs.append({"role": o["role"], "content": o["content"]})
        except OSError:
            return msgs
        if max_turns:
            msgs = msgs[-(max_turns * 2):]
        return msgs

    def history_text(self, n: int = 10) -> str:
        """Recent turns of the CURRENT session as plain text (/history)."""
        msgs = self.load(self.path, max_turns=max(1, n))
        if not msgs:
            return "(no history yet)"
        lines = []
        for m in msgs:
            content = m["content"].replace("\n", " ")
            if len(content) > 200:
                content = content[:200] + "..."
            lines.append(f"{m['role']}: {content}")
        return "\n".join(lines)
