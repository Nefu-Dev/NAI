# -*- coding: utf-8 -*-
"""Safe local tools for NAI: read_file / list_dir / write_file / shell.
All paths are resolved and confined to allowed roots (workspace + extra).
Shell commands go through a blocklist and a confirmation hook.
"""
from __future__ import annotations

import os
import re
import subprocess
import time

MAX_READ = 200 * 1024
MAX_OUTPUT = 12000
MAX_ENTRIES = 300
# read_project delivers up to this many chars of file contents to the model.
# Raised from 8000 to 16000 to match the 16384-token context so it truncates
# far less when the user asks to "introduce / understand this project".
MAX_PROJECT_OUT = 16000

TOOL_NAMES = [
    "read_file", "list_dir", "write_file", "append_file", "mkdir", "move_file",
    "copy_file", "delete_file", "file_info", "search_files", "grep_file",
    "read_project", "pwd", "list_roots", "get_time", "system_info", "calc", "shell",
    "mcp_call", "mcp_list", "mcp_reload",
    "web_open", "screenshot_save", "clipboard_get", "clipboard_set", "env",
    "head", "tail", "count_lines", "hash_file", "touch", "disk_usage",
    "process_list", "json_pretty", "base64_encode", "base64_decode",
    "url_encode", "url_decode", "random_uuid", "random_int",
    "screenshot", "detect_image", "click", "double_click", "right_click",
    "move", "scroll", "type_text", "press", "find_text", "click_text",
    # --- added: isolation / batch / web / sub-agents / large-project ---
    "web_search", "web_fetch", "batch_read", "batch_write", "batch_search",
    "read_big", "subagent", "subagents",
]

TEXT_EXTS = {
    ".py", ".js", ".ts", ".tsx", ".jsx", ".c", ".cpp", ".cc", ".h", ".hpp",
    ".cs", ".java", ".go", ".rs", ".rb", ".php", ".sh", ".bat", ".ps1",
    ".sql", ".json", ".yaml", ".yml", ".toml", ".ini", ".md", ".txt",
    ".html", ".css", ".xml", ".cfg", ".conf", ".log", ".csv", ".tsv",
}

# Substrings that make a shell command suspicious -> refused outright.
BLOCKLIST = [
    "rm -rf", "rmdir /s", "del /f /s", "rd /s", "format ", "mkfs", "diskpart",
    "shutdown", "taskkill", "wmic", "reg delete", "bcdedit", "sc delete",
    "net user", "net localgroup", "netsh", "attrib +h", "takeown", "icacls",
    "powershell -enc", "powershell -e ", "-EncodedCommand", "-enc ", "certutil",
    "bitsadmin", "mshta", "regsvr32", "curl http", "wget http", "iwr ",
    "invoke-webrequest", "invoke-expression", "start-process", "> nul",
    ">nul", "&& del", "del /q /f", "erase /f", "cipher /w", "debug ",
]


class ToolError(Exception):
    pass


class SafeTools:
    def __init__(self, workspace: str):
        self.workspace = os.path.realpath(workspace)
        self.extra_roots = []
        # Auto directory recognition: when a tool targets a real path outside the
        # sandbox, resolve() adds its nearest existing directory to the allowed
        # roots automatically (persisted to nai_allowed.txt) instead of failing.
        self.auto_allow = True
        self.last_auto_added = []      # dirs auto-added by the last tool call
        self.confirm_hook = None  # callable(desc:str) -> bool
        self.supervisor_enabled = False  # master switch for PC-control tools
        self.mcp = None  # MCPRegistry (lazy)
        # --- isolation (user-selectable safety mode) ---
        from .isolation import IsolationPolicy
        self.isolation = IsolationPolicy("full")  # full = current strict default
        self.sandbox_enabled = True               # False only in "none" mode
        # --- output limits (user-tunable; no truncation by default) ---
        self.read_limit = 0            # bytes cap for read_file; 0/None = unlimited
        self.shell_output_limit = 24000  # cap for command output (characters)
        self._load_allowed()           # restore auto-/manually allowed dirs

    # ---------- isolation gating ----------
    def set_isolation(self, mode: str):
        """Switch the isolation mode (full/partial/ai/none) and sync sandbox."""
        from .isolation import normalize_mode, K_CONTROL
        self.isolation.mode = normalize_mode(mode)
        self.sandbox_enabled = self.isolation.mode != "none"
        # AI mode needs the model judge — SafeTools exposes a hook the agent fills.
        return self.isolation.mode, self.isolation.label()

    def get_isolation(self):
        return self.isolation.mode, self.isolation.label()

    def set_read_limit(self, spec: str):
        """Set the read_file byte cap (0/off/none = unlimited, no truncation)."""
        s = (spec or "").strip().lower()
        if s in ("0", "off", "none", "unlimited", "无限", "无", "不限"):
            self.read_limit = 0
        else:
            try:
                n = int(s)
                self.read_limit = n if n > 0 else 0
            except ValueError:
                raise ToolError(f"readlimit needs bytes or 0 (got {spec!r})")
        return ("read_limit = unlimited (0)" if self.read_limit == 0
                else f"read_limit = {self.read_limit} bytes")

    def _confirm_if_needed(self, desc: str):
        if self.confirm_hook and not self.confirm_hook(desc):
            raise ToolError("user denied the action")

    def _gate(self, kind, desc: str, base_ask: bool = True):
        """Apply the current isolation policy to an operation.
        `kind` is a risk kind (isolation.K_*); `base_ask` is whether the
        original full-mode behaviour would confirm this operation.
        Returns without effect when the policy auto-runs the op."""
        from .isolation import K_CONTROL
        mode = self.isolation.mode
        if mode == "none":
            return
        if mode == "partial":
            # only dangerous instructions stay confirmed
            if kind == K_CONTROL:
                self._confirm_if_needed(desc)
            return
        if mode == "ai":
            # model judges; PC control always asks
            if kind == K_CONTROL:
                self._confirm_if_needed(desc)
                return
            judge = self.isolation.judge
            decision = 1
            if judge is not None:
                try:
                    decision = int(judge(desc))
                except Exception:
                    decision = 1
            if decision >= 2:
                raise ToolError(f"blocked by AI risk judgment: {desc}")
            if decision == 1:
                self._confirm_if_needed(desc)
            return
        # full: base behaviour
        if base_ask:
            self._confirm_if_needed(desc)

    # ---------- helpers ----------
    def allowed_roots(self):
        return [self.workspace] + self.extra_roots

    def tool_names(self):
        names = list(TOOL_NAMES)
        try:
            names.extend(k for k in self._mcp_reg().tools if k not in names)
        except Exception:
            pass
        return names

    def resolve(self, path: str) -> str:
        if not path:
            raise ToolError("empty path")
        if not os.path.isabs(path):
            path = os.path.join(self.workspace, path)
        p = os.path.realpath(os.path.abspath(os.path.expanduser(path)))
        if not self.sandbox_enabled:
            return p  # "none" isolation: no sandbox confinement
        np = os.path.normcase(p)
        for root in self.allowed_roots():
            r = os.path.normcase(os.path.realpath(root))
            if np == r or np.startswith(r + os.sep):
                return p
        if self.auto_allow:
            # Auto directory recognition: if the target is a real existing path
            # outside the sandbox, recognize its nearest existing directory and
            # allow it (persisted), instead of refusing the whole call.
            auto = self._auto_find_root(p)
            if auto:
                self.add_root(auto)
                self.last_auto_added.append(auto)
                return p
        raise ToolError(f"path outside allowed directories: {path}")

    @staticmethod
    def _auto_find_root(p: str):
        """Deepest existing directory for a target path (the path itself when it
        is a folder, else its nearest existing ancestor). None if nothing exists."""
        cur = p
        if os.path.isfile(cur):
            cur = os.path.dirname(cur)
        while cur:
            if os.path.isdir(cur):
                return cur
            parent = os.path.dirname(cur)
            if parent == cur:
                return None
            cur = parent
        return None

    # ---------- allowed roots persistence (nai_allowed.txt in the workspace) ----------
    @property
    def allowed_file(self) -> str:
        return os.path.join(self.workspace, "nai_allowed.txt")

    def _load_allowed(self):
        self.extra_roots = []
        try:
            if os.path.isfile(self.allowed_file):
                with open(self.allowed_file, "r", encoding="utf-8") as f:
                    for line in f:
                        p = line.strip()
                        if p and os.path.isdir(p):
                            rp = os.path.realpath(p)
                            if rp not in self.extra_roots:
                                self.extra_roots.append(rp)
        except OSError:
            pass

    def _save_allowed(self):
        try:
            with open(self.allowed_file, "w", encoding="utf-8") as f:
                f.write("\n".join(self.extra_roots))
        except OSError:
            pass

    def reload_allowed(self):
        """Re-read allowed dirs after the workspace changes (/workspace)."""
        self._load_allowed()

    def add_root(self, path: str) -> bool:
        p = os.path.realpath(path)
        if not os.path.isdir(p):
            return False
        if p not in self.extra_roots:
            self.extra_roots.append(p)
            self._save_allowed()
        return True

    def _confirm_if_outside(self, p: str, desc: str):
        """Ask the user before mutating anything outside the workspace
        (subject to the current isolation mode)."""
        from .isolation import K_FILE
        in_workspace = os.path.normcase(p).startswith(os.path.normcase(self.workspace) + os.sep)
        if not in_workspace:
            self._gate(K_FILE, desc, base_ask=True)

    # ---------- tools ----------
    def read_file(self, path: str):
        p = self.resolve(path)
        if not os.path.isfile(p):
            raise ToolError(f"file not found: {path}")
        size = os.path.getsize(p)
        if self.read_limit and size > self.read_limit:
            raise ToolError(f"file too large ({size} bytes > read_limit {self.read_limit}); "
                            f"raise it with /readlimit <bytes> (0 = unlimited)")
        with open(p, "rb") as f:
            data = f.read()
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError:
            return f"(binary file, {size} bytes) {p}"
        return text if text.strip() else f"(empty file) {p}"

    def list_dir(self, path: str):
        p = self.resolve(path)
        if not os.path.isdir(p):
            raise ToolError(f"folder not found: {path}")
        try:
            items = sorted(os.scandir(p), key=lambda e: (not e.is_dir(), e.name.lower()))
        except OSError as e:
            raise ToolError(f"cannot list folder: {e}")
        rows = []
        for e in items[:MAX_ENTRIES]:
            try:
                is_dir = e.is_dir()
            except OSError:
                is_dir = False
            if is_dir:
                rows.append(f"[DIR]  {e.name}/")
            else:
                try:
                    sz = e.stat().st_size
                except OSError:
                    sz = 0
                rows.append(f"[FILE] {e.name} ({sz} B)")
        more = "" if len(items) <= MAX_ENTRIES else f"\n... {len(items) - MAX_ENTRIES} more entries"
        return "\n".join(rows) + more if rows else "(empty folder)"

    def write_file(self, path: str, content: str):
        p = self.resolve(path)
        self._confirm_if_outside(p, f"write file {p}")
        parent = os.path.dirname(p)
        try:
            os.makedirs(parent, exist_ok=True)
            with open(p, "w", encoding="utf-8") as f:
                f.write(content)
        except OSError as e:
            raise ToolError(f"cannot write file: {e}")
        return f"written {len(content.encode('utf-8'))} bytes to {p}"

    def append_file(self, path: str, content: str):
        """Append text to a file (creates it if missing)."""
        p = self.resolve(path)
        self._confirm_if_outside(p, f"append file {p}")
        parent = os.path.dirname(p)
        try:
            os.makedirs(parent, exist_ok=True)
            with open(p, "a", encoding="utf-8") as f:
                f.write(content if content.endswith("\n") else content + "\n")
        except OSError as e:
            raise ToolError(f"cannot append file: {e}")
        return f"appended to {p}"

    def mkdir(self, path: str):
        p = self.resolve(path)
        self._confirm_if_outside(p, f"create folder {p}")
        try:
            os.makedirs(p, exist_ok=True)
        except OSError as e:
            raise ToolError(f"cannot create folder: {e}")
        return f"folder ready: {p}"

    def move_file(self, src: str, dst: str):
        sp = self.resolve(src)
        dp = self.resolve(dst)
        self._confirm_if_outside(sp, f"move {sp} -> {dp}")
        if not os.path.exists(sp):
            raise ToolError(f"source not found: {src}")
        try:
            os.makedirs(os.path.dirname(dp), exist_ok=True)
            os.replace(sp, dp)
        except OSError as e:
            raise ToolError(f"cannot move file: {e}")
        return f"moved {src} -> {dst}"

    def copy_file(self, src: str, dst: str):
        sp = self.resolve(src)
        dp = self.resolve(dst)
        self._confirm_if_outside(sp, f"copy {sp} -> {dp}")
        if not os.path.exists(sp):
            raise ToolError(f"source not found: {src}")
        try:
            os.makedirs(os.path.dirname(dp), exist_ok=True)
            import shutil
            shutil.copy2(sp, dp)
        except OSError as e:
            raise ToolError(f"cannot copy file: {e}")
        return f"copied {src} -> {dst}"

    def delete_file(self, path: str):
        p = self.resolve(path)
        self._confirm_if_outside(p, f"delete {p}")
        if not os.path.exists(p):
            raise ToolError(f"file not found: {path}")
        try:
            if os.path.isdir(p):
                if len(os.listdir(p)) > 0:
                    raise ToolError("folder not empty — delete its files first")
                os.rmdir(p)
                return f"removed empty folder {p}"
            os.remove(p)
            return f"deleted {p}"
        except OSError as e:
            raise ToolError(f"cannot delete: {e}")

    def file_info(self, path: str):
        p = self.resolve(path)
        if not os.path.exists(p):
            raise ToolError(f"not found: {path}")
        st = os.stat(p)
        kind = "folder" if os.path.isdir(p) else "file"
        return (f"path: {p}\nkind: {kind}\nsize: {st.st_size} bytes\n"
                f"modified: {time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(st.st_mtime))}")

    def search_files(self, path: str, pattern: str):
        """Find files/folders whose name matches a glob pattern (e.g. *.txt)."""
        p = self.resolve(path)
        if not os.path.isdir(p):
            raise ToolError(f"folder not found: {path}")
        import fnmatch
        hits = []
        for root, dirs, files in os.walk(p):
            dirs[:] = [d for d in dirs if not d.startswith(".")]
            for fn in files + dirs:
                if fnmatch.fnmatch(fn, pattern):
                    hits.append(os.path.join(root, fn))
                    if len(hits) >= MAX_ENTRIES:
                        break
            if len(hits) >= MAX_ENTRIES:
                break
        if not hits:
            return f"(no matches for {pattern!r} under {p})"
        return "\n".join(hits[:MAX_ENTRIES])

    def read_project(self, path: str, include_content: str = "yes", max_files: str = "8"):
        """Read a whole project/folder: a tree of its files + the contents of the
        main text/code files, so you can understand and extend a project in one step.
        Output is bounded (MAX_PROJECT_OUT) so it fits the model context."""
        p = self.resolve(path)
        if not os.path.isdir(p):
            raise ToolError(f"folder not found: {path}")
        try:
            mf = int(max_files)
        except (TypeError, ValueError):
            mf = 8
        mf = min(max(mf, 1), 30)
        show = str(include_content).strip().lower() in ("yes", "true", "1", "content", "内容")
        lines = [f"project: {p}"]
        contents = []
        budget = [MAX_PROJECT_OUT]
        entries = [0]

        def walk(dirp, prefix, depth):
            if depth > 6 or entries[0] >= MAX_ENTRIES or budget[0] <= 0:
                return
            try:
                items = sorted(os.scandir(dirp),
                               key=lambda e: (not e.is_dir(), e.name.lower()))
            except OSError:
                return
            for e in items:
                if e.name.startswith(".") or entries[0] >= MAX_ENTRIES:
                    continue
                entries[0] += 1
                try:
                    is_dir = e.is_dir()
                    sz = "" if is_dir else f" ({e.stat().st_size} B)"
                except OSError:
                    is_dir, sz = False, ""
                line = f"{prefix}{'[DIR] ' if is_dir else '[FILE] '}{e.name}{sz}"
                lines.append(line)
                if is_dir:
                    walk(e.path, prefix + "    ", depth + 1)
                elif show:
                    ext = os.path.splitext(e.name)[1].lower()
                    if ext in TEXT_EXTS and not is_dir:
                        try:
                            if e.stat().st_size > MAX_READ:
                                continue
                            data = open(e.path, "r", encoding="utf-8", errors="replace").read()
                            if data and len(data) <= MAX_PROJECT_OUT:
                                block = f"===== {e.path} =====\n{data}"
                                budget[0] -= len(block)
                                contents.append(block)
                                if budget[0] <= 0:
                                    break
                        except OSError:
                            continue
            return

        walk(p, "", 0)
        head = "\n".join(lines)
        out = head
        if contents:
            out += f"\n\n--- contents ({len(contents)} files) ---\n" + "\n".join(contents)
        if budget[0] <= 0:
            out += "\n...(output truncated; use read_file for any single file)"
        return out

    def grep_file(self, path: str, text: str):
        """Search a file (or all files in a folder) for lines containing text."""
        matches = []
        targets = []
        if os.path.isdir(p):
            for root, dirs, files in os.walk(p):
                dirs[:] = [d for d in dirs if not d.startswith(".")]
                for fn in files:
                    targets.append(os.path.join(root, fn))
        else:
            targets = [p]
        for fp in targets:
            if os.path.getsize(fp) > MAX_READ:
                continue
            try:
                with open(fp, "r", encoding="utf-8", errors="ignore") as f:
                    for i, line in enumerate(f, 1):
                        if text in line:
                            matches.append(f"{fp}:{i}: {line.rstrip()[:200]}")
                            if len(matches) >= MAX_ENTRIES:
                                break
            except OSError:
                continue
            if len(matches) >= MAX_ENTRIES:
                break
        if not matches:
            return f"(no match for {text!r})"
        return "\n".join(matches[:MAX_ENTRIES])

    def pwd(self):
        return self.workspace

    def list_roots(self):
        return "\n".join(self.allowed_roots())

    def get_time(self):
        return time.strftime("%Y-%m-%d %H:%M:%S %A")

    def system_info(self):
        from . import environment
        return environment.environment_summary(self.workspace)

    def calc(self, expr: str):
        """Evaluate a safe arithmetic expression (numbers and + - * / % ** only)."""
        import ast
        expr = expr.strip()
        try:
            tree = ast.parse(expr, mode="eval")
            allowed = (ast.Expression, ast.BinOp, ast.UnaryOp, ast.Constant,
                       ast.Add, ast.Sub, ast.Mult, ast.Div, ast.FloorDiv,
                       ast.Mod, ast.Pow, ast.USub, ast.UAdd)
            for node in ast.walk(tree):
                if not isinstance(node, allowed):
                    raise ToolError("calc only supports numbers and + - * / % **")
                if isinstance(node, ast.Constant) and not isinstance(node.value, (int, float)):
                    raise ToolError("calc only supports numbers")
            val = eval(compile(tree, "<calc>", "eval"), {"__builtins__": {}}, {})
            return str(val)
        except ToolError:
            raise
        except Exception as e:
            raise ToolError(f"cannot compute: {e}")

    def shell(self, cmd: str):
        cmd = cmd.strip()
        if not cmd:
            raise ToolError("empty command")
        low = cmd.lower()
        # Absolute safety floor — always blocked, even in "none" mode.
        from .isolation import HARD_BLOCK, K_SHELL
        for bad in HARD_BLOCK:
            if bad in low:
                raise ToolError(f"command blocked (irreversible/destructive: {bad!r})")
        # The wider blocklist is disabled only in "none" mode.
        if self.isolation.mode != "none":
            for bad in BLOCKLIST:
                if bad in low:
                    raise ToolError(f"command blocked (dangerous pattern: {bad!r})")
        self._gate(K_SHELL, f"run command: {cmd}", base_ask=True)
        try:
            env = dict(os.environ)
            env["PYTHONIOENCODING"] = "utf-8"
            proc = subprocess.run(
                cmd, shell=True, cwd=self.workspace, capture_output=True,
                timeout=60, env=env,
            )
            out = (proc.stdout or b"") + (proc.stderr or b"")
            text = out.decode("utf-8", errors="replace").strip()
            if not text:
                text = f"(exit code {proc.returncode}, no output)"
            if self.shell_output_limit and len(text) > self.shell_output_limit:
                text = text[:self.shell_output_limit] + "\n... (output truncated)"
            return f"exit {proc.returncode}\n{text}"
        except subprocess.TimeoutExpired:
            raise ToolError("command timed out after 60s")
        except OSError as e:
            raise ToolError(f"cannot run command: {e}")

    # ---------- MCP bridge ----------
    def _mcp_reg(self):
        if self.mcp is None:
            from .mcp import MCPRegistry
            default = os.path.join(
                os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "mcp.json")
            self.mcp = MCPRegistry(default if os.path.isfile(default) else None)
        return self.mcp

    def mcp_list(self):
        return self._mcp_reg().list_tools()

    def mcp_reload(self, config_path=None):
        self._mcp_reg().reload(config_path)
        return self._mcp_reg().list_tools()

    def mcp_call(self, full_name: str, args=None):
        from .isolation import K_MCP
        self._gate(K_MCP, f"MCP call: {full_name}", base_ask=True)
        img_dir = os.path.join(self.workspace, "nai_shots")
        return self._mcp_reg().call(full_name, args or {}, image_dir=img_dir)

    # ---------- extra utilities ----------
    def web_open(self, url: str):
        from .isolation import K_WEB
        self._gate(K_WEB, f"open in browser: {url}", base_ask=True)
        import webbrowser
        webbrowser.open(url)
        return f"opened {url} in the default browser"

    def screenshot_save(self, path: str):
        p = self.resolve(path)
        self._confirm_if_outside(p, f"save screenshot to {p}")
        from PIL import ImageGrab
        img = ImageGrab.grab()
        img.save(p)
        return f"screenshot saved to {p}"

    def clipboard_get(self):
        try:
            import tkinter as tk
            r = tk.Tk(); r.withdraw(); r.update()
            v = r.clipboard_get(); r.destroy()
            return v
        except Exception as e:
            raise ToolError(f"clipboard: {e}")

    def clipboard_set(self, text: str):
        from .isolation import K_CLIPBOARD
        self._gate(K_CLIPBOARD,
                   f"set clipboard to: {text[:40]}{'...' if len(text) > 40 else ''}",
                   base_ask=True)
        import tkinter as tk
        r = tk.Tk(); r.withdraw(); r.update()
        r.clipboard_clear(); r.clipboard_append(text); r.update(); r.destroy()
        return "clipboard set"

    def env(self, key: str):
        v = os.environ.get(key)
        return v if v is not None else f"(env var {key!r} not set)"

    def head(self, path: str, n: str = "20"):
        p = self.resolve(path)
        if not os.path.isfile(p):
            raise ToolError(f"file not found: {path}")
        try:
            nn = int(n)
        except Exception:
            nn = 20
        with open(p, "r", encoding="utf-8", errors="replace") as f:
            lines = f.readlines()
        return "\n".join(x.rstrip() for x in lines[:nn]) or "(empty file)"

    def tail(self, path: str, n: str = "20"):
        p = self.resolve(path)
        if not os.path.isfile(p):
            raise ToolError(f"file not found: {path}")
        try:
            nn = int(n)
        except Exception:
            nn = 20
        with open(p, "r", encoding="utf-8", errors="replace") as f:
            lines = f.readlines()
        return "\n".join(x.rstrip() for x in lines[-nn:]) or "(empty file)"

    def count_lines(self, path: str):
        p = self.resolve(path)
        if not os.path.isfile(p):
            raise ToolError(f"file not found: {path}")
        with open(p, "r", encoding="utf-8", errors="replace") as f:
            return f"lines: {sum(1 for _ in f)}"

    def hash_file(self, path: str, algo: str = "sha256"):
        import hashlib
        p = self.resolve(path)
        if not os.path.isfile(p):
            raise ToolError(f"file not found: {path}")
        if algo not in ("md5", "sha1", "sha256"):
            raise ToolError("algo must be md5 / sha1 / sha256")
        h = hashlib.new(algo)
        with open(p, "rb") as f:
            for chunk in iter(lambda: f.read(65536), b""):
                h.update(chunk)
        return f"{algo}: {h.hexdigest()}"

    def touch(self, path: str):
        p = self.resolve(path)
        self._confirm_if_outside(p, f"create empty file {p}")
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "a", encoding="utf-8"):
            pass
        return f"touched {p}"

    def disk_usage(self, path: str = ""):
        import shutil
        p = self.resolve(path) if path else self.workspace
        if not os.path.isdir(p):
            raise ToolError(f"folder not found: {path}")
        t, u, f = shutil.disk_usage(p)
        return (f"path: {p}\ntotal: {t // 2**20} MB\nused: {u // 2**20} MB\n"
                f"free: {f // 2**20} MB")

    def process_list(self):
        import psutil
        rows = []
        for pr in psutil.process_iter(["pid", "name"]):
            try:
                rows.append(f"{pr.info['pid']} {pr.info['name']}")
            except Exception:
                pass
        return "\n".join(rows[:200]) or "(no processes)"

    def json_pretty(self, text: str):
        import json as _j
        try:
            return _j.dumps(_j.loads(text), ensure_ascii=False, indent=2)
        except Exception as e:
            raise ToolError(f"invalid JSON: {e}")

    def base64_encode(self, text: str):
        import base64
        return base64.b64encode(text.encode("utf-8")).decode()

    def base64_decode(self, text: str):
        import base64
        try:
            return base64.b64decode(text.encode()).decode("utf-8", "replace")
        except Exception as e:
            raise ToolError(str(e))

    def url_encode(self, text: str):
        import urllib.parse
        return urllib.parse.quote(text)

    def url_decode(self, text: str):
        import urllib.parse
        return urllib.parse.unquote(text)

    def random_uuid(self):
        import uuid
        return str(uuid.uuid4())

    def random_int(self, a: str, b: str):
        import random
        try:
            return str(random.randint(int(a), int(b)))
        except Exception as e:
            raise ToolError(str(e))

    def execute(self, name: str, args):
        """Dispatch a parsed tool call. Returns result string or raises ToolError."""
        self.last_auto_added = []  # fresh per tool call, read by the UI after
        one = lambda i: (args[i] if len(args) > i else "") or ""
        if name == "read_file":
            return self.read_file(one(0))
        if name == "list_dir":
            return self.list_dir(one(0))
        if name == "write_file":
            if len(args) < 2:
                raise ToolError("write_file needs path and content")
            return self.write_file(args[0], args[1])
        if name == "append_file":
            if len(args) < 2:
                raise ToolError("append_file needs path and content")
            return self.append_file(args[0], args[1])
        if name == "mkdir":
            return self.mkdir(one(0))
        if name == "move_file":
            if len(args) < 2:
                raise ToolError("move_file needs src and dst")
            return self.move_file(args[0], args[1])
        if name == "copy_file":
            if len(args) < 2:
                raise ToolError("copy_file needs src and dst")
            return self.copy_file(args[0], args[1])
        if name == "delete_file":
            return self.delete_file(one(0))
        if name == "file_info":
            return self.file_info(one(0))
        if name == "search_files":
            if len(args) < 2:
                raise ToolError("search_files needs folder and pattern")
            return self.search_files(args[0], args[1])
        if name == "grep_file":
            if len(args) < 2:
                raise ToolError("grep_file needs path and text")
            return self.grep_file(args[0], args[1])
        if name == "read_project":
            if len(args) < 1:
                raise ToolError("read_project needs a folder")
            return self.read_project(args[0], one(1) or "yes", one(2) or "8")
        if name == "pwd":
            return self.pwd()
        if name == "list_roots":
            return self.list_roots()
        if name == "get_time":
            return self.get_time()
        if name == "system_info":
            return self.system_info()
        if name == "calc":
            return self.calc(one(0))
        if name == "shell":
            return self.shell(one(0))
        # ---- MCP bridge ----
        if name == "mcp_call":
            if len(args) < 1:
                raise ToolError("mcp_call needs 'server.tool' and optional JSON args")
            return self.mcp_call(args[0], one(1) if len(args) > 1 else None)
        if name == "mcp_list":
            return self.mcp_list()
        if name == "mcp_reload":
            return self.mcp_reload(one(0) or None)
        # ---- extra utilities ----
        if name == "web_open":
            if len(args) < 1:
                raise ToolError("web_open needs a url")
            return self.web_open(args[0])
        if name == "screenshot_save":
            if len(args) < 1:
                raise ToolError("screenshot_save needs a path")
            return self.screenshot_save(args[0])
        if name == "clipboard_get":
            return self.clipboard_get()
        if name == "clipboard_set":
            if len(args) < 1:
                raise ToolError("clipboard_set needs text")
            return self.clipboard_set(args[0])
        if name == "env":
            return self.env(one(0))
        if name == "head":
            return self.head(one(0), one(1) or "20")
        if name == "tail":
            return self.tail(one(0), one(1) or "20")
        if name == "count_lines":
            return self.count_lines(one(0))
        if name == "hash_file":
            return self.hash_file(one(0), one(1) or "sha256")
        if name == "touch":
            return self.touch(one(0))
        if name == "disk_usage":
            return self.disk_usage(one(0))
        if name == "process_list":
            return self.process_list()
        if name == "json_pretty":
            return self.json_pretty(one(0))
        if name == "base64_encode":
            return self.base64_encode(one(0))
        if name == "base64_decode":
            return self.base64_decode(one(0))
        if name == "url_encode":
            return self.url_encode(one(0))
        if name == "url_decode":
            return self.url_decode(one(0))
        if name == "random_uuid":
            return self.random_uuid()
        if name == "random_int":
            if len(args) < 2:
                raise ToolError("random_int needs min and max")
            return self.random_int(args[0], args[1])
        # ---- web / batch / large-project / sub-agent tools ----
        if name == "web_search":
            if len(args) < 1:
                raise ToolError("web_search needs a query")
            return self.web_search(args[0], one(1) or "6")
        if name == "web_fetch":
            if len(args) < 1:
                raise ToolError("web_fetch needs a url")
            return self.web_fetch(args[0])
        if name == "batch_read":
            if len(args) < 1:
                raise ToolError("batch_read needs a list of file paths")
            return self.batch_read(args[0], one(1))
        if name == "batch_write":
            if len(args) < 1:
                raise ToolError("batch_write needs a JSON object of {path: content}")
            return self.batch_write(args[0])
        if name == "batch_search":
            if len(args) < 1:
                raise ToolError("batch_search needs a list of queries")
            return self.batch_search(args[0], one(1) or "5")
        if name == "read_big":
            if len(args) < 1:
                raise ToolError("read_big needs a folder")
            return self.read_big(args[0], one(1) or "30", one(2) or "yes", one(3))
        if name == "subagent":
            if len(args) < 1:
                raise ToolError("subagent needs a task")
            return self.subagent(args[0], one(1) or "1024")
        if name == "subagents":
            if len(args) < 1:
                raise ToolError("subagents needs a list of tasks")
            return self.subagents(args[0], one(1) or "4", one(2) or "1024")
        # ---- supervisor (PC control) tools ----
        if name == "screenshot":
            region = None
            if one(0):
                try:
                    vals = [int(v.strip()) for v in one(0).split(",")]
                    if len(vals) == 4:
                        region = tuple(vals)
                except (ValueError, TypeError):
                    region = None  # model passed junk -> full screen
            return self.screenshot(region)
        if name == "detect_image":
            return self.detect_image(one(0))
        if name in ("click", "double_click", "right_click", "move", "scroll",
                    "type_text", "press", "click_text", "find_text"):
            return self._supervisor_ctrl(name, args)
        raise ToolError(f"unknown tool: {name}")

    # ---------- supervisor tools ----------
    def _require_supervisor(self, name):
        if not self.supervisor_enabled:
            raise ToolError(
                f"{name} requires supervisor mode — enable it first with /supervisor on")

    def _supervisor_ctrl(self, name, args):
        self._require_supervisor(name)
        from . import supervisor as SV
        def num(i):
            try:
                return float(args[i])
            except Exception:
                raise ToolError(f"{name} needs numeric args")
        try:
            return self._supervisor_dispatch(name, args, SV, num)
        except ValueError as e:
            raise ToolError(str(e))

    def _supervisor_dispatch(self, name, args, SV, num):
        if name == "click":
            if len(args) < 2:
                raise ToolError("click needs x and y")
            self._confirm_ctrl(f"click at ({num(0)},{num(1)})")
            SV._mouse_click("left", 1, num(0), num(1))
            return f"clicked ({num(0)},{num(1)})"
        if name == "double_click":
            if len(args) < 2:
                raise ToolError("double_click needs x and y")
            self._confirm_ctrl(f"double-click at ({num(0)},{num(1)})")
            SV._mouse_click("left", 2, num(0), num(1))
            return f"double-clicked ({num(0)},{num(1)})"
        if name == "right_click":
            if len(args) < 2:
                raise ToolError("right_click needs x and y")
            self._confirm_ctrl(f"right-click at ({num(0)},{num(1)})")
            SV._mouse_click("right", 1, num(0), num(1))
            return f"right-clicked ({num(0)},{num(1)})"
        if name == "move":
            if len(args) < 2:
                raise ToolError("move needs x and y")
            SV._move(num(0), num(1))
            return f"mouse moved to ({num(0)},{num(1)})"
        if name == "scroll":
            if not args:
                raise ToolError("scroll needs a delta (negative = down)")
            self._confirm_ctrl(f"scroll by {num(0)}")
            SV._scroll(num(0))
            return f"scrolled by {num(0)}"
        if name == "type_text":
            if not args:
                raise ToolError("type_text needs text")
            t = args[0]
            self._confirm_ctrl(f"type text: {t[:40]}{'...' if len(t) > 40 else ''}")
            SV.type_text(t)
            return f"typed {len(t)} chars"
        if name == "press":
            if not args:
                raise ToolError("press needs a key, e.g. enter or ctrl+c")
            self._confirm_ctrl(f"press key: {args[0]}")
            SV.press(args[0])
            return f"pressed {args[0]}"
        if name == "find_text":
            if not args:
                raise ToolError("find_text needs a target string")
            return SV.find_text(args[0], int(args[1]) if len(args) > 1 else 0)
        if name == "click_text":
            if not args:
                raise ToolError("click_text needs a target string")
            self._confirm_ctrl(f"click screen text: {args[0]}")
            return SV.click_text(args[0], int(args[1]) if len(args) > 1 else 0)
        raise ToolError(f"unknown supervisor tool: {name}")

    def _confirm_ctrl(self, desc):
        from .isolation import K_CONTROL
        self._gate(K_CONTROL, desc, base_ask=True)

    def screenshot(self, region=None):
        from . import supervisor as SV
        return SV.screenshot_ocr(region)

    def detect_image(self, source: str):
        """YOLO object detection -> text description of an image.
        source = 'screen' (live screenshot, in memory) or a file path (inside sandbox)."""
        from . import vision
        if not source or source.strip().lower() in ("screen", "屏幕"):
            from PIL import ImageGrab
            img = ImageGrab.grab()
        else:
            p = self.resolve(source)  # sandbox-checked path
            from PIL import Image
            img = Image.open(p)
        return vision.describe_objects(img)

    # ---------- web / batch / large-project / sub-agent tools ----------
    def web_search(self, query: str, n: str = "6"):
        from .isolation import K_WEB
        self._gate(K_WEB, f"web search: {query[:60]}", base_ask=True)
        from . import webutil
        return webutil.web_search(query, n)

    def web_fetch(self, url: str):
        from .isolation import K_WEB
        self._gate(K_WEB, f"fetch page: {url[:60]}", base_ask=True)
        from . import webutil
        return webutil.web_fetch(url)

    def batch_read(self, paths: str, budget: str = ""):
        from .isolation import K_FILE
        self._gate(K_FILE, "batch_read files", base_ask=False)  # read-only: never asks
        from . import batch
        return batch.batch_read_files(self, paths,
                                      budget=int(budget) if budget.isdigit() else batch.DEFAULT_BUDGET)

    def batch_write(self, payload: str):
        from .isolation import K_FILE
        self._gate(K_FILE, "batch_write files", base_ask=True)
        from . import batch
        return batch.batch_write_files(self, payload)

    def batch_search(self, queries: str, n: str = "5"):
        from .isolation import K_WEB
        self._gate(K_WEB, "batch web search", base_ask=True)
        from . import batch
        try:
            nn = max(1, min(int(n), 10))
        except (TypeError, ValueError):
            nn = 5
        return batch.batch_search_queries(queries, nn)

    def read_big(self, path: str, max_files: str = "30", include: str = "yes",
                 budget: str = ""):
        from .isolation import K_FILE
        self._gate(K_FILE, "read big project", base_ask=False)  # read-only: never asks
        from . import batch
        return batch.read_big_project(self, path, max_files, include,
                                      budget or str(batch.DEFAULT_BUDGET))

    def subagent(self, task: str, max_tokens: str = "1024"):
        """Run ONE subtask in a sub-agent and return its result."""
        from .isolation import K_FILE
        self._gate(K_FILE, "spawn sub-agent (runs tools)", base_ask=True)
        from . import subagent
        from .agent import _current_model
        model = _current_model()
        if model is None:
            raise ToolError("sub-agent needs the active model (only available from the agent)")
        try:
            mt = int(max_tokens)
        except (TypeError, ValueError):
            mt = 1024
        results = subagent.spawn_subagents(model, [task], self.workspace,
                                           confirm_hook=self.confirm_hook,
                                           max_tokens=mt)
        return subagent.fmt_results(results)

    def subagents(self, tasks: str, max_workers: str = "4", max_tokens: str = "1024"):
        """Run several subtasks in PARALLEL sub-agents. tasks = newline/JSON list."""
        from .isolation import K_FILE
        self._gate(K_FILE, "spawn parallel sub-agents (run tools)", base_ask=True)
        from . import subagent, batch
        from .agent import _current_model
        model = _current_model()
        if model is None:
            raise ToolError("sub-agents need the active model (only available from the agent)")
        task_list = batch.parse_list(tasks)
        if not task_list:
            raise ToolError("subagents needs a list of tasks (newline or JSON array)")
        try:
            mw = max(1, min(int(max_workers), 8))
        except (TypeError, ValueError):
            mw = 4
        try:
            mt = int(max_tokens)
        except (TypeError, ValueError):
            mt = 1024
        results = subagent.spawn_subagents(model, task_list, self.workspace,
                                           max_workers=mw, confirm_hook=self.confirm_hook,
                                           max_tokens=mt)
        return subagent.fmt_results(results)

    # ---------- shell blocklist check exposed for tests ----------
    @staticmethod
    def is_blocked(cmd: str) -> bool:
        low = cmd.lower()
        return any(b in low for b in BLOCKLIST)
