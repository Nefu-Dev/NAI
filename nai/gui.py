# -*- coding: utf-8 -*-
"""NAI Claude-style CLI terminal (Tkinter).

Dark theme, streamed tokens ("watch inference"), live inference monitor,
model tools (read/list/write file, run commands) with visual confirmation,
and Chinese/English UI. Desktop app only — no HTML.
"""
from __future__ import annotations

import json
import os
import queue
import re
import sys
import threading
import time
import tkinter as tk
import tkinter.font as tkfont
from tkinter import ttk

from . import i18n
from .paths import default_workspace, resolve_model_path
from .history import SessionLog
from .worker import NaiModel
from .agent import NaiAgent

# ---- theme (Claude Code-ish) ----
BG = "#161617"
PANEL = "#1f1f20"
INPUT_BG = "#101011"
FG = "#e6e6e6"
MUTED = "#9aa0a6"
ACCENT = "#d97757"
GREEN = "#7cc47f"
BLUE = "#7aa2f7"
RED = "#f87171"
YELLOW = "#e5c07b"
BORDER = "#2c2c2e"
# dialogue colors: user = blue, NAI assistant = green
USER_MSG = "#82aaff"
ASST_MSG = "#7ee787"

CJK_RANGES = (
    (0x4E00, 0x9FFF), (0x3400, 0x4DBF), (0x3000, 0x303F),
    (0xFF00, 0xFFEF), (0x2018, 0x201F), (0x2000, 0x206F),
)


def _is_cjk(ch: str) -> bool:
    o = ord(ch)
    return any(a <= o <= b for a, b in CJK_RANGES)


# Absolute Windows paths (D:\... or D:/...) mentioned in user input — auto-added
# to the sandbox allowed roots (auto directory recognition).
_ABS_PATH_RE = re.compile(r"[A-Za-z]:[\\/][^\s\"',;()（）【】<>]*")

# How much of a tool result the GUI prints before noting truncation (read_file /
# read_project results are shown almost in full — no silent 200-char cut-off).
RESULT_DISPLAY_LIMIT = 30000


def cjk_runs(s: str):
    """Split into (segment, is_cjk) runs so we can use a CJK-capable font."""
    runs = []
    cur = ""
    cur_cjk = None
    for ch in s:
        cjk = _is_cjk(ch)
        if cur_cjk is None:
            cur_cjk = cjk
        if cjk != cur_cjk and cur:
            runs.append((cur, cur_cjk))
            cur = ""
            cur_cjk = cjk
        cur += ch
    if cur:
        runs.append((cur, cur_cjk if cur_cjk is not None else False))
    return runs


class NAIApp:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.lang = os.environ.get("NAI_LANG", "zh")
        self.t = lambda k: i18n.L[self.lang][k]
        self.workspace = default_workspace()
        self.autoshell = True
        self.busy = False
        self.pending_confirm = None       # threading.Event awaiting y/n
        self.pending_confirm_desc = ""
        self.ev = queue.Queue()
        self.speed_history = []
        self.turn_tokens = 0
        self.turn_start = time.time()
        self.uptime_start = time.time()

        self.root.title(self.t("app_title"))
        self.root.configure(bg=BG)
        self.root.geometry("1020x680")
        self.root.minsize(820, 520)

        self._fonts()
        self._build_ui()
        self._bind_keys()
        self._load_model()
        self._pump()
        self._tick_monitor()

    # ---------------- fonts ----------------
    def _fonts(self):
        self.f_mono = tkfont.Font(family="Cascadia Mono", size=10)
        if self.f_mono.measure("NAI") <= 0:
            self.f_mono = tkfont.Font(family="Consolas", size=10)
        self.f_cjk = tkfont.Font(family="Microsoft YaHei UI", size=10)
        self.f_big = tkfont.Font(family="Cascadia Mono", size=12, weight="bold")
        self.f_small = tkfont.Font(family="Microsoft YaHei UI", size=8)
        self.f_badge = tkfont.Font(family="Cascadia Mono", size=10, weight="bold")

    # ---------------- ui ----------------
    def _build_ui(self):
        root = self.root

        # header
        head = tk.Frame(root, bg=BG)
        head.pack(side="top", fill="x", padx=14, pady=(10, 4))
        tk.Label(head, text=self.t("header_badge"), font=self.f_badge,
                 fg=ACCENT, bg=BG).pack(side="left")
        self.lbl_model = tk.Label(head, text="", font=self.f_small, fg=MUTED, bg=BG)
        self.lbl_model.pack(side="left", padx=12)
        self.dot = tk.Canvas(head, width=12, height=12, bg=BG, highlightthickness=0)
        self.dot.pack(side="right")
        self._dot_color(MUTED)

        # main split: terminal | monitor
        paned = ttk.Panedwindow(root, orient="horizontal")
        paned.pack(fill="both", expand=True, padx=14, pady=6)

        term_frame = tk.Frame(paned, bg=BG)
        self.text = tk.Text(term_frame, bg=BG, fg=FG, font=self.f_mono,
                            insertbackground=FG, wrap="word", padx=12, pady=10,
                            relief="flat", borderwidth=0, highlightthickness=0,
                            spacing1=1, spacing3=3, state="disabled", cursor="arrow")
        self.text.tag_config("mono", font=self.f_mono, foreground=FG)
        self.text.tag_config("cjk", font=self.f_cjk, foreground=FG)
        self.text.tag_config("user", foreground=USER_MSG)
        self.text.tag_config("asst", foreground=ASST_MSG)
        self.text.tag_config("acc", foreground=ACCENT)
        self.text.tag_config("tool", foreground=YELLOW)
        self.text.tag_config("tres", foreground=GREEN)
        self.text.tag_config("terr", foreground=RED)
        self.text.tag_config("deny", foreground=RED)
        self.text.tag_config("dim", foreground=MUTED)
        self.text.tag_config("err", foreground=RED)
        # assistant color wins over the font-only mono/cjk tags
        self.text.tag_raise("asst")
        sb = ttk.Scrollbar(term_frame, command=self.text.yview)
        self.text.configure(yscrollcommand=sb.set)
        self.text.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")
        paned.add(term_frame, weight=3)

        monitor = tk.Frame(paned, bg=PANEL, width=200)
        monitor.pack_propagate(False)
        paned.add(monitor, weight=0)

        tk.Label(monitor, text=self.t("monitor_title"), font=self.f_badge,
                 fg=ACCENT, bg=PANEL).pack(anchor="w", padx=12, pady=(12, 4))
        self.mon = {}
        rows = [
            ("model", self.t("mon_model")), ("ctx", self.t("mon_ctx")),
            ("tokens", self.t("mon_tokens")), ("speed", self.t("mon_speed")),
            ("mem", self.t("mon_mem")), ("uptime", self.t("mon_uptime")),
            ("status", self.t("mon_status")), ("ws", self.t("workspace")),
            ("lang", self.t("lang")),
        ]
        for key, label in rows:
            f = tk.Frame(monitor, bg=PANEL)
            f.pack(fill="x", padx=12, pady=1)
            tk.Label(f, text=label, font=self.f_small, fg=MUTED, bg=PANEL,
                     width=9, anchor="w").pack(side="left")
            self.mon[key] = tk.Label(f, text="—", font=self.f_small, fg=FG,
                                     bg=PANEL, anchor="e")
            self.mon[key].pack(side="right", fill="x", expand=True)

        self.canvas = tk.Canvas(monitor, bg=PANEL, height=64, highlightthickness=0)
        self.canvas.pack(fill="x", padx=12, pady=(8, 4))
        tk.Label(monitor, text="tok/s", font=self.f_small, fg=MUTED,
                 bg=PANEL).pack(anchor="w", padx=12)

        # input row
        inp = tk.Frame(root, bg=INPUT_BG, highlightbackground=BORDER,
                       highlightthickness=1)
        inp.pack(fill="x", padx=14, pady=(0, 8))
        self.prompt = tk.Label(inp, text=self.t("prompt"), font=self.f_badge,
                               fg=ACCENT, bg=INPUT_BG)
        self.prompt.pack(side="left", padx=(12, 6), pady=8)
        self.entry = tk.Entry(inp, bg=INPUT_BG, fg=FG, font=self.f_cjk,
                              insertbackground=ACCENT, relief="flat",
                              highlightthickness=0)
        self.entry.pack(side="left", fill="x", expand=True, padx=(0, 12), pady=8)

        # status bar
        bar = tk.Frame(root, bg=BG)
        bar.pack(fill="x", padx=14, pady=(0, 6))
        self.status = tk.Label(bar, text=self.t("status_ready"),
                               font=self.f_small, fg=MUTED, bg=BG)
        self.status.pack(side="left")

        self._print(self.t("welcome"), "dim")

    def _bind_keys(self):
        self.entry.bind("<Return>", self._on_enter)
        self.root.bind("<Control-l>", lambda e: self._do_clear())
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

    # ---------------- model ----------------
    def _load_model(self):
        self._set_status("loading")
        try:
            path = resolve_model_path()
            self.model = NaiModel(path, n_ctx=None)
            self.agent = NaiAgent(self.model, workspace=self.workspace,
                                  confirm_hook=self._ask_confirm,
                                  autoshell=self.autoshell)
            # local conversation records (survive restarts; /resume to cut back in)
            self.log = SessionLog(self.workspace)
            self.log.new()
            self.lbl_model.config(text=f"{os.path.basename(path)} "
                                       f"· ctx {self.model.n_ctx} "
                                       f"· {os.path.getsize(path)/1e6:.0f} MB")
            self.mon["model"].config(text=os.path.basename(path))
            self.mon["ctx"].config(text=f"0/{self.model.n_ctx}")
            ctx, src = self.agent.get_context()
            if ctx:
                self._print(f"已自动加载项目上下文: {src}", "dim")
            sessions = self.log.list_sessions()
            if sessions:
                s = sessions[0]
                self._print(f"上次会话: {os.path.basename(s['path'])} · {s['turns']} 轮 · "
                            f"/resume 载入 · /sessions 查看", "dim")
            self._set_status("ready")
        except Exception as e:
            self._set_status("error")
            self._print(f"model load failed: {e}", "err")
            self.mon["status"].config(text="ERR", fg=RED)

    def _ask_confirm(self, desc: str) -> bool:
        if not self.autoshell and desc.startswith("run command"):
            return False
        # If called on the main thread, we cannot wait on the pump queue:
        # the pump only runs on the main thread and would never process the
        # request while we block (self-deadlock). Use a modal dialog directly.
        if threading.current_thread() is threading.main_thread():
            import tkinter.messagebox as mb
            return bool(mb.askyesno("NAI — 确认 / confirm", desc))
        ev = threading.Event()
        self.ev.put(("confirm_request", desc, ev))
        ev.wait(timeout=180)
        return bool(getattr(ev, "answer", False))

    # ---------------- events ----------------
    def _pump(self):
        try:
            while True:
                item = self.ev.get_nowait()
                self._handle(item)
        except queue.Empty:
            pass
        self.root.after(30, self._pump)

    def _handle(self, item):
        kind = item[0]
        if kind == "token":
            self._stream(item[1])
            self.turn_tokens += 1
        elif kind == "tool":
            self._print(self.t("tool_run").format(
                name=item[1], desc=", ".join(map(str, item[2]))), "tool")
        elif kind == "tool_result":
            desc = item[3] if isinstance(item[3], str) else str(item[3])
            if len(desc) > RESULT_DISPLAY_LIMIT:
                desc = desc[:RESULT_DISPLAY_LIMIT] + ("\n...(结果过长已省略，前 %d 字符)"
                                                      % RESULT_DISPLAY_LIMIT)
            self._print(self.t("tool_ok").format(desc=desc), "tres")
            for d in getattr(self.agent.tools, "last_auto_added", []) or []:
                self._print("已自动识别并放行目录: " + d, "acc")
        elif kind == "tool_denied":
            self._print(self.t("tool_denied").format(desc=item[1]), "deny")
        elif kind == "done":
            if len(item) >= 3 and isinstance(item[2], dict):
                ts = item[2].get("tok_s")
                if ts:
                    self.speed_history.append(float(ts))
            self.busy = False
            self.turn_tokens = 0
            self.prompt.config(text=self.t("prompt"))
            self.entry.config(state="normal")
            self.entry.focus_set()
            self._set_status("ready")
        elif kind == "confirm_request":
            _, desc, ev = item
            self.pending_confirm = ev
            self.pending_confirm_desc = desc
            self._set_status("wait_confirm")
            self.prompt.config(text="?")
            self._print(self.t("confirm_shell" if desc.startswith("run command")
                               else "confirm_write").format(
                cmd=desc.replace("run command: ", ""),
                path=desc.replace("write file ", "")), "deny")
            self.entry.config(state="normal")
            self.entry.delete(0, "end")
            self.entry.focus_set()
        elif kind == "error":
            self._print(str(item[1]), "err")
            self.busy = False

    # ---------------- input ----------------
    def _on_enter(self, _ev=None):
        if self.pending_confirm:
            self._answer_confirm()
            return
        if self.busy:
            return
        raw = self.entry.get().strip()
        if not raw:
            return
        self.entry.delete(0, "end")
        if raw.startswith("/"):
            self._run_command(raw)
            return
        self._send(raw)

    def _answer_confirm(self):
        raw = self.entry.get().strip().lower()
        self.entry.delete(0, "end")
        ev = self.pending_confirm
        self.pending_confirm = None
        ev.answer = raw in ("y", "yes", "是", "1")
        ev.set()
        self.prompt.config(text=self.t("prompt"))

    def _send(self, text):
        self._print(f"{self.t('prompt')} {text}", "user")
        # auto directory recognition: dirs the user names are allowed now
        for d in self._auto_recognize(text):
            self._print("已自动识别并放行目录: " + d, "acc")
        self.busy = True
        self.turn_start = time.time()
        self.turn_tokens = 0
        self._set_status("working")
        self.prompt.config(text="…")
        self.entry.config(state="disabled")

        def work():
            try:
                self.agent.run_turn(text, sink=lambda kind, **kw: self.ev.put((kind, *kw.values())))
                self._save_turn(text)  # conversation records (local)
            except Exception as e:
                self.ev.put(("error", str(e)))
                self.ev.put(("done",))

        threading.Thread(target=work, daemon=True).start()

    # ---------------- auto directory recognition + conversation records ----------------
    def _auto_recognize(self, text: str):
        """Add directories the user mentions to the sandbox allowed roots (persisted)."""
        added = []
        seen = set()
        for m in _ABS_PATH_RE.findall(text):
            p = m.rstrip("\\/.").strip("\"'")
            if not p or p in seen:
                continue
            seen.add(p)
            try:
                rp = os.path.realpath(p)
                if os.path.isdir(rp):
                    target = rp
                elif os.path.isfile(rp):
                    target = os.path.dirname(rp)
                else:
                    continue
                if target and self.agent.add_root(target):
                    added.append(target)
            except Exception:
                continue
        return added

    def _save_turn(self, user_text: str):
        try:
            self.log.append("user", user_text)
            if self.agent.history and self.agent.history[-1]["role"] == "assistant":
                self.log.append("assistant", self.agent.history[-1]["content"])
        except Exception:
            pass

    # ---------------- commands ----------------
    def _run_command(self, raw):
        parts = raw.split()
        cmd = parts[0].lower()
        if cmd in ("/help", "/h"):
            self._print(self.t("cmd_help"), "dim")
        elif cmd == "/clear":
            self._do_clear()
        elif cmd == "/lang":
            if len(parts) < 2:
                self._print(self.t("err_lang"), "err")
            else:
                self.lang = parts[1].lower()
                if self.lang not in i18n.L:
                    self.lang = "zh"
                self._apply_lang()
                self._print(self.t("lang") + ": " + self.lang, "dim")
        elif cmd == "/workspace":
            if len(parts) < 2:
                self._print(self.t("err_workspace"), "err")
            else:
                p = " ".join(parts[1:])
                if os.path.isdir(p):
                    self.workspace = os.path.realpath(p)
                    self.agent.set_workspace(self.workspace)
                    self.log = SessionLog(self.workspace)
                    self.log.new()
                    self.mon["ws"].config(text=self.workspace)
                    self._print(self.t("workspace_set") + self.workspace, "dim")
                    ctx, src = self.agent.get_context()
                    self._print("已自动加载项目上下文: " + src if ctx
                                else "（未发现项目上下文文件：README.md / nai_context.txt）", "dim")
                else:
                    self._print(self.t("err_notdir") + p, "err")
        elif cmd == "/context":
            body = raw[len("/context"):].strip()
            if not body:
                ctx, src = self.agent.get_context()
                if ctx:
                    self._print(f"项目上下文（{src}）:", "dim")
                    self._print(ctx[:400] + ("..." if len(ctx) > 400 else ""), "dim")
                else:
                    self._print("（当前无项目上下文；/context auto 重新扫描，/context clear 关闭）", "dim")
            elif body.lower() in ("auto", "on", "扫描", "重新"):
                self.agent.context_disabled = False
                self.agent._discover_context()
                ctx, src = self.agent.get_context()
                self._print("已重新扫描项目上下文: " + src if ctx
                            else "（未发现项目上下文文件：README.md / nai_context.txt）",
                            "acc" if ctx else "dim")
            elif body.lower() in ("clear", "off", "关", "清除"):
                self.agent.clear_context()
                self._print("项目上下文已关闭（/context auto 重新开启）", "dim")
            else:
                if self.agent.set_context(body):
                    self._print("已使用上下文文件: " + os.path.realpath(body), "acc")
                else:
                    self._print("不是有效文件: " + body, "err")
        elif cmd in ("/resume", "/load"):
            body = raw[len(cmd):].strip()
            sessions = self.log.list_sessions()
            if not sessions:
                self._print("（没有历史会话可载入）", "dim")
                return
            idx = 0
            if body:
                if body.isdigit():
                    idx = int(body) - 1
                else:
                    hit = [s for s in sessions if body.lower() in os.path.basename(s["path"]).lower()]
                    if hit:
                        idx = sessions.index(hit[0])
            if not (0 <= idx < len(sessions)):
                self._print("索引无效（/sessions 查看列表）", "err")
                return
            s = sessions[idx]
            msgs = self.log.load(s["path"])
            if not msgs:
                self._print("该会话为空", "err")
                return
            self.agent.history = list(msgs)
            self.log.path = s["path"]  # keep appending into the resumed session
            self._print(f"已载入会话 {os.path.basename(s['path'])} · "
                        f"{len(msgs) // 2} 轮对话（{len(msgs)} 条消息）", "acc")
            self._print("（继续输入即可接着聊；/new 开新会话）", "dim")
        elif cmd == "/sessions":
            sessions = self.log.list_sessions()
            if not sessions:
                self._print("（暂无历史会话；对话会自动保存到 nai_history/）", "dim")
            for i, s in enumerate(sessions, 1):
                cur = "  ← 当前" if s["path"] == self.log.path else ""
                first = s["first"] or "(空会话)"
                self._print(f"  {i}. {os.path.basename(s['path'])} · "
                            f"{s['turns']} 轮 · {first}{cur}", "dim")
        elif cmd == "/history":
            n = int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else 10
            self._print(self.log.history_text(n), "dim")
        elif cmd == "/new":
            self.agent.history = []
            p = self.log.new()
            self._print(f"新会话已开始: {os.path.basename(p)}（旧会话仍保存在本地）", "acc")
        elif cmd == "/allow":
            if len(parts) < 2:
                self._print(self.t("err_workspace"), "err")
            else:
                p = " ".join(parts[1:])
                if os.path.isdir(p) and self.agent.add_root(p):
                    self._print(self.t("allow_add") + os.path.realpath(p), "dim")
                else:
                    self._print(self.t("err_notdir") + p, "err")
        elif cmd in ("/dirs", "/sandbox"):
            roots = self.agent.tools.allowed_roots()
            msg = self.t("sandbox_show").format(ws=self.workspace) + "\n" + "\n".join("  " + r for r in roots)
            self._print(msg, "dim")
        elif cmd == "/autoshell":
            if len(parts) < 2:
                self._print(self.t("err_autoshell"), "err")
            else:
                self.autoshell = parts[1].lower() in ("on", "1", "true")
                self.agent.autoshell = self.autoshell
                self._print(self.t("autoshell_on" if self.autoshell else "autoshell_off"), "dim")
        elif cmd == "/isolation":
            body = raw[len("/isolation"):].strip()
            head = body.split()[0].lower() if body.split() else ""
            if not body or head in ("status", "list", "查看", "?"):
                m, label = self.agent.get_isolation()
                self._print(f"当前隔离模式: {label} ({m})", "dim")
            else:
                m, label = self.agent.set_isolation(body)
                self._print(f"隔离模式已设为: {label} ({m})", "acc")
        elif cmd == "/autostart":
            from . import autostart as AS
            sub = parts[1].lower() if len(parts) > 1 else "status"
            if sub in ("on", "enable", "开", "启用"):
                self._print(AS.register(), "acc")
            elif sub in ("off", "disable", "关", "停用", "取消"):
                self._print(AS.unregister(), "dim")
            elif sub in ("status", "查看", "state"):
                self._print(AS.status(), "dim")
            else:
                self._print("用法: /autostart on|off|status", "err")
        elif cmd == "/subagents":
            body = raw[len("/subagents"):].strip()
            if not body:
                self._print("用法: /subagents 任务1 | 任务2 | 任务3（并行派生子智能体）", "err")
            else:
                tasks = [t.strip() for t in body.split("|") if t.strip()]
                from . import subagent as SA
                res = SA.spawn_subagents(self.model, tasks, self.workspace,
                                         max_workers=len(tasks),
                                         confirm_hook=self._ask_confirm)
                self._print(SA.fmt_results(res), "tres")
        elif cmd == "/supervisor":
            if len(parts) < 2:
                self._print(self.t("err_supervisor"), "err")
            else:
                on = parts[1].lower() in ("on", "1", "true")
                if on:
                    # turning on supervisor = the user confirms takeover
                    if self._ask_confirm("enable supervisor mode (NAI may control this PC after each confirmed action)"):
                        self.agent.tools.supervisor_enabled = True
                        self._print(self.t("supervisor_on"), "acc")
                    else:
                        self._print(self.t("supervisor_off"), "dim")
                else:
                    self.agent.tools.supervisor_enabled = False
                    self._print(self.t("supervisor_off"), "dim")
        elif cmd in ("/stats", "/model"):
            info = self.model.info()
            info["max_tokens"] = self.agent.max_tokens
            self._print(json.dumps(info, ensure_ascii=False), "dim")
        elif cmd == "/goal":
            rest = raw[len("/goal"):].strip()
            head = rest.split()[0].lower() if rest.split() else ""
            if not rest or head in ("status", "list", "查看"):
                g = self.agent.get_goal()
                self._print(f"当前目标: {g}" if g else "（当前无目标）", "dim")
            elif head in ("clear", "done", "完成", "达成", "结束", "清空", "清除"):
                self.agent.clear_goal()
                self._print("目标已清除（任务结束）", "acc")
            else:
                self.agent.set_goal(rest)
                self._print(f"目标已设置（达成前 NAI 不会结束对话）: {rest}", "acc")
        elif cmd == "/env":
            self._print(self.agent.tools.system_info(), "dim")
        elif cmd == "/maxtokens":
            if len(parts) < 2:
                self._print(f"当前输出上限: {self.agent.max_tokens} tokens（用法: /maxtokens 2048）", "dim")
            else:
                try:
                    n = min(max(int(parts[1]), 128), 12000)
                    self.agent.max_tokens = n
                    self._print(f"输出上限已设为 {n} tokens", "acc")
                except ValueError:
                    self._print("数字无效", "err")
        elif cmd == "/readlimit":
            if len(parts) < 2:
                cur = self.agent.tools.read_limit or "不限(0,不截断)"
                self._print(f"当前 read_file 读取上限: {cur} bytes"
                            "（用法: /readlimit 字节 或 0=不限）", "dim")
            else:
                try:
                    msg = self.agent.tools.set_read_limit(parts[1])
                    self._print(msg, "acc")
                except Exception as e:
                    self._print(f"设置失败: {e}", "err")
        elif cmd in ("/rule", "/rules"):
            if cmd == "/rule":
                body = raw[len(cmd):].strip()
                if not body:
                    self._print("用法: /rule <规则文本>  (/rules 查看；/rule clear 清空)", "err")
                elif body.lower() in ("clear", "清空", "重置"):
                    self.agent.clear_rules()
                    self._print("规则已清空", "dim")
                else:
                    self.agent.add_rule(body)
                    self._print("已添加规则: " + body, "acc")
            rules = self.agent.get_rules()
            if rules:
                self._print("当前规则:", "dim")
                for i, r in enumerate(rules, 1):
                    self._print(f"  {i}. {r}", "dim")
            else:
                self._print("（暂无自定义规则）", "dim")
        elif cmd == "/mcp":
            sub = parts[1] if len(parts) > 1 else "list"
            if sub in ("list", "ls"):
                self._print(self.agent.tools.mcp_list(), "dim")
            elif sub in ("reload", "re"):
                cfg = " ".join(parts[2:]) if len(parts) > 2 else None
                self._print(self.agent.tools.mcp_reload(cfg), "dim")
            else:
                self._print("用法: /mcp list | reload [配置路径]", "err")
        elif cmd == "/tools":
            names = self.agent.tools.tool_names()
            self._print(f"已注册工具: {len(names)}", "dim")
            self._print("  " + ", ".join(names), "dim")
        elif cmd == "/exit":
            self._on_close()
        else:
            self._print(self.t("err_cmd") + cmd, "err")

    def _apply_lang(self):
        self.t = lambda k: i18n.L[self.lang][k]
        self.root.title(self.t("app_title"))
        self._print(self.t("welcome"), "dim")

    def _do_clear(self):
        self.text.config(state="normal")
        self.text.delete("1.0", "end")
        self.text.config(state="disabled")

    # ---------------- output ----------------
    def _print(self, s, tag="mono"):
        self.text.config(state="normal")
        self.text.insert("end", s + "\n", (tag,))
        self.text.see("end")
        self.text.config(state="disabled")

    def _stream(self, s):
        self.text.config(state="normal")
        for seg, is_cjk in cjk_runs(s):
            tags = ("asst", "cjk") if is_cjk else ("asst", "mono")
            self.text.insert("end", seg, tags)
        self.text.see("end")
        self.text.config(state="disabled")

    # ---------------- monitor ----------------
    def _tick_monitor(self):
        try:
            import psutil
            rss = psutil.Process().memory_info().rss / 1e6
            self.mon["mem"].config(text=f"{rss:.0f} {self.t('mem_mb')}")
        except Exception:
            pass
        up = int(time.time() - self.uptime_start)
        self.mon["uptime"].config(text=f"{up} {self.t('sec')}")
        self.mon["lang"].config(text=self.lang)
        self.mon["ws"].config(text=self.workspace)
        self.mon["status"].config(text=self.status.cget("text"))
        self.mon["tokens"].config(text=str(self.turn_tokens))
        if self.speed_history:
            self.mon["speed"].config(text=f"{self.speed_history[-1]:.1f} {self.t('tok_s')}")
            self.mon["ctx"].config(text=f"{self.turn_tokens} / {self.model.n_ctx}")
        self._draw_sparkline()
        self.root.after(1000, self._tick_monitor)

    def _draw_sparkline(self):
        self.canvas.delete("all")
        w = self.canvas.winfo_width()
        h = self.canvas.winfo_height()
        if w < 2 or h < 2:
            return
        data = self.speed_history[-60:]
        if not data:
            return
        mx = max(data) or 1.0
        n = len(data)
        pts = []
        for i, v in enumerate(data):
            x = 2 + (w - 4) * i / max(n - 1, 1)
            y = h - 2 - (h - 6) * (v / mx)
            pts.append((x, y))
        for i in range(1, len(pts)):
            self.canvas.create_line(pts[i - 1][0], pts[i - 1][1],
                                    pts[i][0], pts[i][1], fill=ACCENT, width=1.5)

    def _dot_color(self, color):
        self.dot.delete("all")
        self.dot.create_oval(2, 2, 10, 10, fill=color, outline="")

    def _set_status(self, key):
        text = {
            "ready": self.t("status_ready"),
            "working": self.t("status_working"),
            "loading": "…",
            "error": "ERR",
            "wait_confirm": self.t("status_wait_confirm"),
        }.get(key, key)
        color = {"ready": GREEN, "working": ACCENT, "error": RED,
                 "wait_confirm": YELLOW}.get(key, MUTED)
        if hasattr(self, "status"):
            self.status.config(text=text, fg=color)
        self._dot_color(color)

    def _on_close(self):
        self.root.destroy()


def main():
    try:
        root = tk.Tk()
        NAIApp(root)
        root.mainloop()
    except Exception:
        import traceback
        log = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "NAI_log.txt")
        log = os.path.abspath(log)
        try:
            with open(log, "w", encoding="utf-8") as f:
                f.write(traceback.format_exc())
        except Exception:
            pass
        raise


if __name__ == "__main__":
    main()
