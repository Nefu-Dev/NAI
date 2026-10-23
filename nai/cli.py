# -*- coding: utf-8 -*-
"""NAI command-line terminal (Rich).

Launchable from the console:  python run_nai_cli.py   (or NAI_cli.bat)

A beautiful, live terminal that lets you WATCH the AI:
  • streaming generation (the AI "thinking" / writing the draft)
  • every tool call it makes, with the action + result (what it did)
  • its final answer.
Reuses the exact same agent/model/tools as the GUI version (files, shell,
supervisor/OCR, YOLO vision, bilingual, identity override, sandbox).
"""
from __future__ import annotations

import os
import re
import sys
import time

from rich.console import Console
from rich.panel import Panel
from rich.text import Text
from rich import box

from . import prompt as P
from .agent import NaiAgent
from .history import SessionLog
from .worker import NaiModel
from .paths import resolve_model_path, default_workspace

C_USER = "bold #82aaff"
C_ASST = "#7ee787"
C_TOOL = "bold #ffb86c"
C_RESULT = "#7ee787"
C_DENY = "bold #ff5555"
C_DIM = "italic #5c6370"
C_ACC = "bold #ffd866"
C_ERR = "bold #ff5555"
C_CODE = "bold #ffd866"

# Absolute Windows paths (D:\... or D:/...) mentioned in user input — these are
# auto-recognized and added to the sandbox allowed roots.
_ABS_PATH_RE = re.compile(r"[A-Za-z]:[\\/][^\s\"',;()（）【】<>]*")

# How much of a tool result the terminal prints before noting truncation.
# read_file / read_project results are shown almost in full so the user can
# actually see what the model sees (no more silent 200-char cut-off).
RESULT_DISPLAY_LIMIT = 30000


class _CodeFence:
    """Toggle between plain and code styles as ``` fences open/close in the
    live token stream, so long code streams visibly with code coloring."""

    def __init__(self, emit_plain, emit_code):
        self.buf = ""
        self.in_code = False
        self.emit_plain = emit_plain
        self.emit_code = emit_code

    def feed(self, chunk):
        self.buf += chunk
        while True:
            i = self.buf.find("```")
            if i < 0:
                if self.buf:
                    (self.emit_code if self.in_code else self.emit_plain)(self.buf)
                    self.buf = ""
                return
            if i:
                (self.emit_code if self.in_code else self.emit_plain)(self.buf[:i])
            self.buf = self.buf[i + 3:]
            self.in_code = not self.in_code


class _MarkerStripper:
    """Drops ⟪TOOL:…⟫ / ⟪RESULT:…⟫ markers from a live token stream so the
    draft reads as flowing thought while tool actions render as panels."""

    def __init__(self, emit):
        self.buf = ""
        self.emit = emit

    def feed(self, chunk):
        self.buf += chunk
        while True:
            i = self.buf.find("⟪")
            if i < 0:
                self.emit(self.buf)
                self.buf = ""
                return
            if i:
                self.emit(self.buf[:i])
                self.buf = self.buf[i:]
            j = self.buf.find("⟫")
            if j < 0:
                return  # incomplete marker: wait for more
            self.buf = self.buf[j + 1:]  # drop the whole marker


class NaiCli:
    def __init__(self, model_path=None, workspace=None):
        self.console = Console(highlight=False)
        self.model = NaiModel(model_path or resolve_model_path(), n_ctx=None)
        self.workspace = workspace or default_workspace()
        self.agent = NaiAgent(self.model, workspace=self.workspace,
                              confirm_hook=self._confirm)
        # Local conversation records: every turn is appended; /resume /sessions
        # /history /new can cut back into any saved session at any time.
        self.log = SessionLog(self.workspace)
        self.log.new()
        self.autoshell = True
        self.turn_tokens = 0
        self.turn_start = 0.0
        self.speed_hist = []

    # ---------- confirm (from agent thread = this thread) ----------
    def _confirm(self, desc: str) -> bool:
        if desc.startswith("run command") and not self.autoshell:
            return False
        self.console.print(Panel(desc, title="[bold]确认 / confirm[/]",
                                 border_style=C_ACC, box=box.ROUNDED))
        ans = input("  允许？y=是 n=拒绝 > ").strip().lower()
        return ans in ("y", "yes", "是", "1")

    # ---------- rendering ----------
    def _sink(self, kind, **kw):
        if kind == "token":
            self.turn_tokens += 1
        elif kind == "tool":
            name = kw.get("name", "?")
            args = kw.get("args", [])
            args_s = ", ".join(repr(a) for a in args[:3])
            self.console.print("")
            self.console.print(f"[{C_TOOL}]⟪ 调用工具: {name}({args_s}) ⟫[/]",
                               markup=True)
        elif kind == "tool_result":
            res = str(kw.get("result", ""))
            if len(res) > RESULT_DISPLAY_LIMIT:
                res = res[:RESULT_DISPLAY_LIMIT] + "\n...(结果过长已省略，前 %d 字符)" % RESULT_DISPLAY_LIMIT
            self.console.print(f"[{C_RESULT}]⟪ 结果: {res}[/]", markup=True)
            for d in getattr(self.agent.tools, "last_auto_added", []) or []:
                self.console.print(f"[{C_ACC}]已自动识别并放行目录: {d}[/]", markup=True)
        elif kind == "tool_denied":
            self.console.print(f"[{C_DENY}]⟪ 已拒绝该操作 ⟫[/]", markup=True)

    # ---------- auto directory recognition + conversation records ----------
    def _auto_recognize(self, text: str):
        """Find absolute paths the user mentioned and add them to the sandbox
        allowed roots automatically (persisted to nai_allowed.txt)."""
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

    def run_turn(self, text: str):
        self.console.print(f"[{C_USER}]你:[/] {text}", markup=True)
        # Auto directory recognition: directories the user names are allowed now.
        for d in self._auto_recognize(text):
            self.console.print(f"[{C_ACC}]已自动识别并放行目录: {d}[/]", markup=True)
        self.console.print(f"[bold #ff79c6]NAI 思考/生成中…[/]", markup=True)
        self.turn_tokens = 0
        self.turn_start = time.time()
        fence = _CodeFence(
            lambda t: self.console.print(t, end="", style=C_DIM, markup=False),
            lambda t: self.console.print(t, end="", style=C_CODE, markup=False),
        )
        draft = _MarkerStripper(fence.feed)
        last_tok = [0.0]

        def sink(kind, **kw):
            if kind == "token":
                self.turn_tokens += 1
                draft.feed(kw.get("text", ""))
                last_tok[0] = time.time()
            self._sink(kind, **kw)

        self.agent.run_turn(text, sink=sink)
        self._save_turn(text)  # conversation records (local)
        dt = max(time.time() - self.turn_start, 1e-6)
        tok_s = self.turn_tokens / dt
        if tok_s:
            self.speed_hist.append(tok_s)
        self.console.print("")
        self.console.print(f"[bold #d0d0d0]── {self.turn_tokens} tokens · {tok_s:.1f} tok/s ──[/]",
                           markup=True)

    # ---------- commands ----------
    def _run_command(self, raw: str):
        parts = raw.split()
        cmd = parts[0].lower()
        if cmd in ("/help", "/h"):
            self.console.print(self._help_text(), style=C_DIM)
        elif cmd == "/clear":
            os.system("cls" if os.name == "nt" else "clear")
        elif cmd == "/model":
            info = self.model.info()
            self.console.print(f"model: {info.get('model_path','?')} · n_ctx {info.get('n_ctx')} · "
                               f"n_embd {info.get('n_embd')}", style=C_DIM)
        elif cmd == "/stats":
            avg = sum(self.speed_hist) / len(self.speed_hist) if self.speed_hist else 0
            self.console.print(f"平均 {avg:.1f} tok/s · {len(self.speed_hist)} 轮 · 输出上限 {self.agent.max_tokens}",
                               style=C_DIM)
        elif cmd == "/goal":
            rest = raw[len("/goal"):].strip()
            head = rest.split()[0].lower() if rest.split() else ""
            if not rest or head in ("status", "list", "查看"):
                g = self.agent.get_goal()
                self.console.print(f"当前目标: {g}" if g else "（当前无目标）", style=C_DIM)
            elif head in ("clear", "done", "完成", "达成", "结束", "清空", "清除"):
                self.agent.clear_goal()
                self.console.print("目标已清除（任务结束）", style=C_ACC)
            else:
                self.agent.set_goal(rest)
                self.console.print(f"目标已设置（达成前 NAI 不会结束对话）: {rest}", style=C_ACC)
        elif cmd == "/env":
            self.console.print(self.agent.tools.system_info(), style=C_DIM)
        elif cmd == "/maxtokens":
            if len(parts) < 2:
                self.console.print(f"当前输出上限: {self.agent.max_tokens} tokens（用法: /maxtokens 2048）",
                                   style=C_DIM)
            else:
                try:
                    n = int(parts[1])
                    n = min(max(n, 128), 12000)
                    self.agent.max_tokens = n
                    self.console.print(f"输出上限已设为 {n} tokens", style=C_ACC)
                except ValueError:
                    self.console.print("数字无效", style=C_ERR)
        elif cmd == "/readlimit":
            if len(parts) < 2:
                cur = self.agent.tools.read_limit or "不限(0,不截断)"
                self.console.print(f"当前 read_file 读取上限: {cur} bytes"
                                   "（用法: /readlimit 字节 或 0=不限）", style=C_DIM)
            else:
                try:
                    msg = self.agent.tools.set_read_limit(parts[1])
                    self.console.print(msg, style=C_ACC)
                except Exception as e:
                    self.console.print(f"设置失败: {e}", style=C_ERR)
        elif cmd == "/workspace":
            if len(parts) < 2:
                self.console.print("用法: /workspace <目录>", style=C_ERR)
            else:
                p = " ".join(parts[1:])
                if os.path.isdir(p):
                    self.workspace = os.path.realpath(p)
                    self.agent.set_workspace(self.workspace)
                    # fresh session log in the new workspace
                    self.log = SessionLog(self.workspace)
                    self.log.new()
                    self.console.print(f"工作目录已设为: {self.workspace}", style=C_DIM)
                    ctx, src = self.agent.get_context()
                    if ctx:
                        self.console.print(f"已自动加载项目上下文: {src}", style=C_DIM)
                    else:
                        self.console.print("（未发现项目上下文文件：README.md / nai_context.txt）",
                                           style=C_DIM)
                else:
                    self.console.print(f"不是有效目录: {p}", style=C_ERR)
        elif cmd == "/allow":
            if len(parts) < 2:
                self.console.print("用法: /allow <目录>", style=C_ERR)
            else:
                p = " ".join(parts[1:])
                if os.path.isdir(p) and self.agent.add_root(p):
                    self.console.print(f"已放行目录: {os.path.realpath(p)}", style=C_DIM)
                else:
                    self.console.print(f"不是有效目录: {p}", style=C_ERR)
        elif cmd in ("/dirs", "/sandbox"):
            roots = self.agent.tools.allowed_roots()
            self.console.print("沙盒（工作目录+允许目录，自动识别目录持久化于 nai_allowed.txt）:",
                               style=C_DIM)
            for r in roots:
                self.console.print("  " + r, style=C_DIM)
        elif cmd in ("/resume", "/load"):
            body = raw[len(cmd):].strip()
            sessions = self.log.list_sessions()
            if not sessions:
                self.console.print("（没有历史会话可载入）", style=C_DIM)
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
                self.console.print("索引无效（/sessions 查看列表）", style=C_ERR)
                return
            s = sessions[idx]
            msgs = self.log.load(s["path"])
            if not msgs:
                self.console.print("该会话为空", style=C_ERR)
                return
            self.agent.history = list(msgs)
            self.log.path = s["path"]  # keep appending into the resumed session
            self.console.print(f"已载入会话 {os.path.basename(s['path'])} · "
                               f"{len(msgs) // 2} 轮对话（{len(msgs)} 条消息）", style=C_ACC)
            self.console.print("（继续输入即可接着聊；/new 开新会话）", style=C_DIM)
        elif cmd == "/sessions":
            sessions = self.log.list_sessions()
            if not sessions:
                self.console.print("（暂无历史会话；对话会自动保存到 nai_history/）", style=C_DIM)
            for i, s in enumerate(sessions, 1):
                cur = "  ← 当前" if s["path"] == self.log.path else ""
                first = s["first"] or "(空会话)"
                self.console.print(f"  {i}. {os.path.basename(s['path'])} · "
                                   f"{s['turns']} 轮 · {first}{cur}", style=C_DIM)
        elif cmd == "/history":
            n = int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else 10
            self.console.print(self.log.history_text(n), style=C_DIM)
        elif cmd == "/new":
            self.agent.history = []
            p = self.log.new()
            self.console.print(f"新会话已开始: {os.path.basename(p)}（旧会话仍保存在本地）",
                               style=C_ACC)
        elif cmd == "/context":
            body = raw[len("/context"):].strip()
            if not body:
                ctx, src = self.agent.get_context()
                if ctx:
                    self.console.print(f"项目上下文（{src}）:", style=C_DIM)
                    self.console.print(ctx[:400] + ("..." if len(ctx) > 400 else ""),
                                       style=C_DIM)
                else:
                    self.console.print("（当前无项目上下文；/context auto 重新扫描，"
                                       "/context clear 关闭）", style=C_DIM)
            elif body.lower() in ("auto", "on", "扫描", "重新"):
                self.agent.context_disabled = False
                self.agent._discover_context()
                ctx, src = self.agent.get_context()
                if ctx:
                    self.console.print(f"已重新扫描项目上下文: {src}", style=C_ACC)
                else:
                    self.console.print("（未发现项目上下文文件：README.md / nai_context.txt）",
                                       style=C_DIM)
            elif body.lower() in ("clear", "off", "关", "清除"):
                self.agent.clear_context()
                self.console.print("项目上下文已关闭（/context auto 重新开启）", style=C_DIM)
            else:
                p = body
                if self.agent.set_context(p):
                    self.console.print(f"已使用上下文文件: {os.path.realpath(p)}", style=C_ACC)
                else:
                    self.console.print(f"不是有效文件: {p}", style=C_ERR)
        elif cmd == "/supervisor":
            if len(parts) < 2:
                self.console.print("用法: /supervisor on|off", style=C_ERR)
            else:
                on = parts[1].lower() in ("on", "1", "true")
                if on:
                    if self._confirm("开启超控模式（NAI 可在每次确认后控制本机：截屏OCR/点击/输入/YOLO）"):
                        self.agent.tools.supervisor_enabled = True
                        self.console.print("超控已开启", style=C_ACC)
                    else:
                        self.console.print("已取消", style=C_DIM)
                else:
                    self.agent.tools.supervisor_enabled = False
                    self.console.print("超控已关闭", style=C_DIM)
        elif cmd == "/autoshell":
            if len(parts) < 2:
                self.console.print("用法: /autoshell on|off", style=C_ERR)
            else:
                self.autoshell = parts[1].lower() in ("on", "1", "true")
                self.console.print("命令确认: " + ("开" if self.autoshell else "关（注意风险）"),
                                   style=C_DIM)
        elif cmd == "/isolation":
            body = raw[len("/isolation"):].strip()
            head = body.split()[0].lower() if body.split() else ""
            if not body or head in ("status", "list", "查看", "?"):
                m, label = self.agent.get_isolation()
                self.console.print(f"当前隔离模式: {label} ({m})", style=C_DIM)
            else:
                m, label = self.agent.set_isolation(body)
                self.console.print(f"隔离模式已设为: {label} ({m})", style=C_ACC)
        elif cmd == "/autostart":
            from . import autostart as AS
            sub = parts[1].lower() if len(parts) > 1 else "status"
            if sub in ("on", "enable", "开", "启用"):
                self.console.print(AS.register(), style=C_ACC)
            elif sub in ("off", "disable", "关", "停用", "取消"):
                self.console.print(AS.unregister(), style=C_DIM)
            elif sub in ("status", "查看", "state"):
                self.console.print(AS.status(), style=C_DIM)
            else:
                self.console.print("用法: /autostart on|off|status", style=C_ERR)
        elif cmd == "/subagents":
            body = raw[len("/subagents"):].strip()
            if not body:
                self.console.print("用法: /subagents 任务1 | 任务2 | 任务3（并行派生子智能体）",
                                   style=C_ERR)
            else:
                tasks = [t.strip() for t in body.split("|") if t.strip()]
                from . import subagent as SA
                res = SA.spawn_subagents(self.model, tasks, self.workspace,
                                         max_workers=len(tasks),
                                         confirm_hook=self._confirm)
                self.console.print(SA.fmt_results(res), style=C_RESULT)
        elif cmd in ("/rule", "/rules"):
            if cmd == "/rule":
                body = raw[len(cmd):].strip()
                if not body:
                    self.console.print("用法: /rule <规则文本>（例如：/rule 回答尽量简短）",
                                       style=C_ERR)
                elif body.lower() in ("clear", "清空", "重置"):
                    self.agent.clear_rules()
                    self.console.print("规则已清空", style=C_DIM)
                else:
                    self.agent.add_rule(body)
                    self.console.print(f"已添加规则: {body}", style=C_ACC)
            rules = self.agent.get_rules()
            if rules:
                self.console.print("当前规则:", style=C_DIM)
                for i, r in enumerate(rules, 1):
                    self.console.print(f"  {i}. {r}", style=C_DIM)
            else:
                self.console.print("（暂无自定义规则）", style=C_DIM)
        elif cmd == "/mcp":
            sub = parts[1] if len(parts) > 1 else "list"
            if sub in ("list", "ls"):
                self.console.print(self.agent.tools.mcp_list(), style=C_DIM)
            elif sub in ("reload", "re"):
                cfg = " ".join(parts[2:]) if len(parts) > 2 else None
                self.console.print(self.agent.tools.mcp_reload(cfg), style=C_DIM)
            else:
                self.console.print("用法: /mcp list | reload [配置路径]", style=C_ERR)
        elif cmd == "/tools":
            names = self.agent.tools.tool_names()
            self.console.print(f"已注册工具: {len(names)}", style=C_DIM)
            self.console.print("  " + ", ".join(names), style=C_DIM)
        elif cmd == "/exit":
            self.console.print("再见", style=C_DIM)
            raise SystemExit(0)
        else:
            self.console.print(f"未知命令: {cmd}（/help 查看）", style=C_ERR)

    def _help_text(self):
        return (
            "命令:\n"
            "  /help            帮助\n"
            "  /clear           清屏\n"
            "  /workspace <dir> 切换工作目录（沙盒根，自动重载该目录的上下文与允许目录）\n"
            "  /allow <dir>     额外放行目录\n"
            "  /dirs /sandbox   查看沙盒范围\n"
            "  /context [auto|clear|<文件>]  项目上下文：查看/重扫/关闭/指定文件（默认自动读 README.md）\n"
            "  /resume [索引|片段] 载入历史会话继续对话（随时切入）；/load 同义\n"
            "  /sessions        列出本地保存的会话（自动存于 <工作目录>/nai_history/）\n"
            "  /history [n]     查看当前会话最近 n 轮\n"
            "  /new             开新会话（旧会话保留在本地）\n"
            "  /supervisor on|off 超控（截屏OCR/点击/输入/YOLO，需确认）\n"
            "  /autoshell on|off 命令确认\n"
            "  /isolation full|partial|ai|none  切换隔离模式（默认 full=全部隔离）\n"
            "  /autostart on|off|status  注册/注销开机自启（存到系统，关机后重启恢复）\n"
            "  /subagents 任务1 | 任务2    并行派生子智能体分别完成任务\n"
            "  /rule <文本>     添加自定义规则（/rules 查看；/rule clear 清空）\n"
            "  /env             查看本机环境（OS/Python/CPU/内存/工作目录）\n"
            "  /goal <文本>     设置目标（达成前 NAI 持续用工具推进、不结束对话）；status 查看；clear/done 结束\n"
            "  /maxtokens <n>   设置单次输出上限（长代码可调大，默认1024，上限4000）\n"
            "  /mcp list|reload [配置]  MCP 工具列表 / 重载\n"
            "  /tools           列出已注册工具\n"
            "  /model /stats    模型信息 / 推理统计\n"
            "  /exit            退出\n"
            "其他输入直接发给 NAI。\n"
            "提示：要求写代码/长文时 NAI 会自动放宽输出上限（最长4096），并以代码配色实时显示。\n"
            "提示：对话提到或模型访问到的目录会自动识别放行（持久化到 nai_allowed.txt）；"
            "对话自动保存到 nai_history/，可用 /resume 随时载入。"
        )

    # ---------- main loop ----------
    def start(self):
        self.console.print(Panel(
            "[bold #7ee787]NAI[/] · Qwen2.5-1.5B 微调 · 离线\n"
            "输入任意内容与 NAI 对话；/help 查看命令。",
            title="[bold]NAI CLI[/]", border_style="#7ee787", box=box.DOUBLE))
        ctx, src = self.agent.get_context()
        if ctx:
            self.console.print(f"[{C_DIM}]已自动加载项目上下文: {src}[/]", markup=True)
        sessions = self.log.list_sessions()
        if sessions:
            s = sessions[0]
            self.console.print(f"[{C_DIM}]上次会话: {os.path.basename(s['path'])} · "
                               f"{s['turns']} 轮 · /resume 载入 · /sessions 查看[/]", markup=True)
        while True:
            try:
                raw = input("你: ").strip()
            except (EOFError, KeyboardInterrupt):
                self.console.print("\n再见", style=C_DIM)
                return
            if not raw:
                continue
            if raw.startswith("/"):
                self._run_command(raw)
                continue
            self.run_turn(raw)


def main(model_path=None, workspace=None):
    _ensure_utf8()
    NaiCli(model_path, workspace).start()


def _ensure_utf8():
    """Force the Windows console + Python streams to UTF-8 so Chinese displays
    correctly (chcp 65001 + stream reconfiguration). No-op on other systems."""
    if os.name == "nt":
        try:
            os.system("chcp 65001 >nul")
        except Exception:
            pass
    os.environ.setdefault("PYTHONIOENCODING", "utf-8")
    for s in (sys.stdout, sys.stderr):
        try:
            s.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
