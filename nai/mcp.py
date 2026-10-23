# -*- coding: utf-8 -*-
"""Minimal MCP (Model Context Protocol) client bridge for NAI.

Lets NAI call tools exposed by MCP servers (e.g. a browser MCP, filesystem MCP...).
Config: a JSON file with a top-level "mcpServers" map:
    {
      "mcpServers": {
        "browser": {"type": "stdio", "command": "npx", "args": ["-y", "@playwright/mcp@latest"]},
        "math":    {"type": "http",  "url": "http://127.0.0.1:8000/mcp"}
      }
    }
Transports: "stdio" (line-delimited JSON-RPC 2.0 over stdin/stdout) and "http"
(single JSON-RPC POST request/response). Both implement the core MCP handshake.
"""
from __future__ import annotations

import json
import os
import subprocess
import threading
import urllib.request

MCP_VERSION = "2025-03-26"


class MCPError(Exception):
    pass


class MCPServer:
    """A single configured MCP server (stdio or http)."""

    def __init__(self, name: str, conf: dict):
        self.name = name
        self.conf = conf
        self.transport = conf.get("type", "stdio")
        self._proc = None
        self._lock = threading.Lock()
        self._next_id = [0]
        self._initialized = False

    # ---- low-level rpc ----
    def _request(self, method, params=None, timeout=30):
        if self.transport == "http":
            return self._http(method, params, timeout)
        return self._stdio(method, params, timeout)

    def _http(self, method, params, timeout):
        url = self.conf.get("url")
        if not url:
            raise MCPError(f"server {self.name}: missing url for http transport")
        self._next_id[0] += 1
        payload = {"jsonrpc": "2.0", "id": self._next_id[0],
                   "method": method, "params": params or {}}
        req = urllib.request.Request(
            url, data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            data = json.loads(r.read().decode("utf-8", "replace"))
        return self._unwrap(data)

    def _stdio(self, method, params, timeout):
        self._ensure_stdio()
        with self._lock:
            if not self._initialized:
                self._handshake()
            self._next_id[0] += 1
            rid = self._next_id[0]
            self._proc.stdin.write(
                (json.dumps({"jsonrpc": "2.0", "id": rid, "method": method,
                             "params": params or {}}) + "\n").encode("utf-8"))
            self._proc.stdin.flush()
            return self._read_response(rid, timeout)

    def _ensure_stdio(self):
        if self._proc is not None and self._proc.poll() is None:
            return
        cmd = self.conf.get("command")
        if not cmd:
            raise MCPError(f"server {self.name}: missing command for stdio transport")
        args = self.conf.get("args", [])
        env = dict(self.conf.get("env", {}))
        kwargs = {"env": env or None}
        if os.name == "nt":
            kwargs["creationflags"] = 0x08000000  # CREATE_NO_WINDOW (hide console)
        self._proc = subprocess.Popen(
            [cmd] + list(args), stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, **kwargs)
        self._initialized = False

    def _handshake(self):
        self._next_id[0] += 1
        self._proc.stdin.write((json.dumps({
            "jsonrpc": "2.0", "id": self._next_id[0],
            "method": "initialize",
            "params": {"protocolVersion": MCP_VERSION,
                       "capabilities": {}, "clientInfo": {"name": "nai", "version": "1.0"}},
        }) + "\n").encode("utf-8"))
        self._proc.stdin.flush()
        self._read_response(self._next_id[0])
        self._proc.stdin.write((json.dumps({
            "jsonrpc": "2.0", "method": "notifications/initialized", "params": {}}) + "\n").encode("utf-8"))
        self._proc.stdin.flush()
        self._initialized = True

    def _read_response(self, rid, timeout=30):
        # read line-delimited frames until we get our id (or an error)
        import queue
        deadline = threading.Event()
        q = queue.Queue()

        def pump():
            try:
                while True:
                    line = self._proc.stdout.readline()
                    if not line:
                        q.put(("__eof__", None))
                        return
                    try:
                        msg = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if msg.get("id") == rid:
                        q.put(("ok", msg))
                        return
            except Exception as e:
                q.put(("err", e))

        t = threading.Thread(target=pump, daemon=True)
        t.start()
        try:
            kind, msg = q.get(timeout=timeout)
        except queue.Empty:
            raise MCPError(f"server {self.name}: timeout waiting for response")
        if kind == "__eof__":
            raise MCPError(f"server {self.name}: process exited")
        if kind == "err":
            raise MCPError(str(msg))
        return self._unwrap(msg)

    @staticmethod
    def _unwrap(data):
        if "error" in data and data["error"]:
            raise MCPError(str(data["error"]))
        return data.get("result", {})

    # ---- high-level ----
    def list_tools(self):
        res = self._request("tools/list")
        return res.get("tools", [])

    def call_tool(self, name, args=None, image_dir=None):
        res = self._request("tools/call", {"name": name, "arguments": args or {}})
        content = res.get("content", [])
        parts = []
        for c in content:
            if c.get("type") == "text":
                parts.append(c.get("text", ""))
            elif c.get("type") == "image":
                # save returned images (e.g. browser screenshots) to disk so the
                # GUI/CLI can visualize them; return the local path.
                p = self._save_image(c, image_dir)
                parts.append(f"[image saved: {p}]" if p else f"[image:{c.get('mimeType','')}]")
        return "\n".join(parts) if parts else json.dumps(res)[:500]

    @staticmethod
    def _save_image(c, image_dir=None):
        data = c.get("data") or c.get("image") or ""
        if not data:
            return None
        mime = c.get("mimeType", "image/png")
        ext = {"image/png": "png", "image/jpeg": "jpg", "image/webp": "webp"}.get(mime, "png")
        try:
            raw = data.encode("utf-8", "replace")
            import base64
            try:
                raw = base64.b64decode(data, validate=True)
            except Exception:
                pass
        except Exception:
            return None
        d = image_dir or os.path.join(os.getcwd(), "nai_shots")
        os.makedirs(d, exist_ok=True)
        from time import time
        path = os.path.join(d, f"mcp_{int(time()*1000)}.{ext}")
        try:
            with open(path, "wb") as f:
                f.write(raw)
            return path
        except Exception:
            return None

    def close(self):
        if self._proc is not None and self._proc.poll() is None:
            try:
                self._proc.terminate()
            except Exception:
                pass


class MCPRegistry:
    """Loads mcp.json, manages servers, exposes a flat tool namespace."""

    def __init__(self, config_path=None):
        self.config_path = config_path
        self.servers = {}
        self.tools = {}
        self.reload(config_path)

    def reload(self, config_path=None):
        if config_path:
            self.config_path = config_path
        for s in self.servers.values():
            try:
                s.close()
            except Exception:
                pass
        self.servers = {}
        self.tools = {}
        if not self.config_path or not os.path.isfile(self.config_path):
            return 0
        with open(self.config_path, "r", encoding="utf-8") as f:
            cfg = json.load(f)
        m = cfg.get("mcpServers", {})
        for name, conf in m.items():
            self.servers[name] = MCPServer(name, conf)
            try:
                for tl in self.servers[name].list_tools():
                    tname = tl.get("name")
                    self.tools[f"{name}.{tname}"] = tl.get("description", "")
            except MCPError as e:
                self.tools[f"{name}.!error"] = str(e)
        return len(self.tools)

    def list_tools(self):
        rows = [f"{k}  -  {v}" for k, v in self.tools.items()]
        return "\n".join(rows) if rows else "(no MCP servers configured)"

    def call(self, full_name, args=None, image_dir=None):
        if "." not in full_name:
            raise MCPError(f"mcp tool must be 'server.tool', got {full_name!r}")
        srv, tool = full_name.split(".", 1)
        if srv not in self.servers:
            raise MCPError(f"unknown MCP server {srv!r}")
        if isinstance(args, str):
            try:
                args = json.loads(args) if args.strip() else {}
            except json.JSONDecodeError:
                raise MCPError("mcp args must be a JSON object string")
        return self.servers[srv].call_tool(tool, args or {}, image_dir=image_dir)

    def close(self):
        for s in self.servers.values():
            try:
                s.close()
            except Exception:
                pass
        self.servers = {}

