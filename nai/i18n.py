# -*- coding: utf-8 -*-
"""NAI terminal UI strings (Chinese / English)."""
from __future__ import annotations

L = {
    "zh": {
        "app_title": "NAI — 本地 AI 终端",
        "header_badge": "NAI · 本地 AI",
        "header_model": "本地模型",
        "status_ready": "就绪",
        "status_working": "推理中…",
        "status_tool": "执行工具…",
        "status_wait_confirm": "等待确认",
        "prompt": "❯",
        "monitor_title": "推理监控",
        "mon_model": "模型",
        "mon_ctx": "上下文",
        "mon_tokens": "本轮 tokens",
        "mon_speed": "速度",
        "mon_mem": "内存",
        "mon_uptime": "运行时长",
        "mon_status": "状态",
        "workspace": "工作目录",
        "lang": "语言",
        "cmd_help": (
            "可用命令：\n"
            "  /help            显示本帮助\n"
            "  /clear           清空终端\n"
            "  /lang zh|en      切换界面语言\n"
            "  /workspace <dir> 设置工作目录（模型可读写的根目录；自动重载该目录的上下文与允许目录）\n"
            "  /allow <dir>     额外允许模型访问的目录\n"
            "  /dirs /sandbox    显示当前沙盒（工作目录+允许目录）\n"
            "  /context [auto|clear|<文件>]  项目上下文：查看/重扫/关闭/指定文件（默认自动读 README.md）\n"
            "  /resume [索引|片段] 载入历史会话继续对话（随时切入）；/load 同义\n"
            "  /sessions        列出本地保存的会话（自动存于 <工作目录>/nai_history/）\n"
            "  /history [n]     查看当前会话最近 n 轮\n"
            "  /new             开新会话（旧会话保留在本地）\n"
            "  /autoshell on|off 执行命令前是否需要确认（默认 on）\n"
            "  /isolation full|partial|ai|none 切换隔离模式（默认 full=全部隔离）\n"
            "  /autostart on|off|status 注册/注销开机自启（存到系统，关机后重启恢复）\n"
            "  /subagents 任务1 | 任务2 并行派生子智能体分别完成任务\n"
            "  /readlimit <字节|0> 设置 read_file 读取上限（0=不限，不截断；默认不限）\n"
            "  /supervisor on|off 开启超控（截屏OCR识别屏幕+点击/滚动/输入，开启需确认）\n"
            "  /stats           显示推理统计\n"
            "  /model           显示模型信息\n"
            "  /exit            退出\n"
            "其他输入会发给 NAI。模型可直接读取/写入文件，执行命令、超控操作需你确认。"
        ),
        "err_cmd": "未知命令：",
        "err_lang": "用法：/lang zh 或 /lang en",
        "err_workspace": "用法：/workspace <绝对路径>",
        "err_notdir": "不是有效目录：",
        "err_autoshell": "用法：/autoshell on|off",
        "err_supervisor": "用法：/supervisor on|off",
        "supervisor_on": "超控已开启：NAI 可截屏识别屏幕并按你的确认点击/滚动/输入（截图仅内存、不落盘）。",
        "supervisor_off": "超控已关闭。",
        "workspace_set": "工作目录已设为：",
        "allow_add": "已允许目录：",
        "autoshell_on": "执行命令前将询问确认。",
        "autoshell_off": "已关闭命令确认（注意风险）。",
        "sandbox_show": "沙盒（工作目录 + 允许目录）：\n  工作目录: {ws}\n  允许目录:",
        "confirm_shell": "NAI 想执行命令：\n  {cmd}\n输入 y 允许，n 拒绝。",
        "confirm_write": "NAI 想写入工作目录外的文件：\n  {path}\n输入 y 允许，n 拒绝。",
        "tool_run": "⟪ 工具 {name}: {desc}",
        "tool_ok": "⟪ 结果: {desc}",
        "tool_err": "⟪ 错误: {desc}",
        "tool_denied": "⟪ 已拒绝: {desc}",
        "done": "完成",
        "welcome": "NAI 已就绪 · 本地离线 · 支持中/英双语\n输入 /help 查看命令，直接输入内容与我对话。",
        "mem_mb": "MB",
        "tok_s": "tok/s",
        "sec": "s",
    },
    "en": {
        "app_title": "NAI — Local AI Terminal",
        "header_badge": "NAI · Local AI",
        "header_model": "local model",
        "status_ready": "ready",
        "status_working": "thinking…",
        "status_tool": "running tool…",
        "status_wait_confirm": "awaiting confirm",
        "prompt": "❯",
        "monitor_title": "INFERENCE MONITOR",
        "mon_model": "model",
        "mon_ctx": "context",
        "mon_tokens": "tokens",
        "mon_speed": "speed",
        "mon_mem": "memory",
        "mon_uptime": "uptime",
        "mon_status": "status",
        "workspace": "workspace",
        "lang": "lang",
        "cmd_help": (
            "Commands:\n"
            "  /help            show this help\n"
            "  /clear           clear the terminal\n"
            "  /lang zh|en      switch UI language\n"
            "  /workspace <dir> set the workspace root the model may read/write (auto-reloads context & allowed dirs)\n"
            "  /allow <dir>     allow one more directory for the model\n"
            "  /dirs /sandbox    show the current sandbox (workspace + allowed dirs)\n"
            "  /context [auto|clear|<file>]  project context: view/rescan/disable/set a file (auto reads README.md)\n"
            "  /resume [idx|substr] resume a saved conversation (cut back in anytime); /load same\n"
            "  /sessions        list locally saved sessions (auto stored under <workspace>/nai_history/)\n"
            "  /history [n]     show the last n turns of the current session\n"
            "  /new             start a new session (old ones stay on disk)\n"
            "  /autoshell on|off ask before running commands (default on)\n"
            "  /isolation full|partial|ai|none switch isolation mode (default full)\n"
            "  /autostart on|off|status register/unregister autostart (stored in the system)\n"
            "  /subagents task1 | task2 run parallel sub-agents\n"
            "  /readlimit <bytes|0> set the read_file cap (0=unlimited, no truncation; default unlimited)\n"
            "  /supervisor on|off enable screen control (OCR the screen + click/scroll/type; needs confirm)\n"
            "  /stats           show inference statistics\n"
            "  /model           show model info\n"
            "  /exit            quit\n"
            "Anything else is sent to NAI. It can read/write files directly; "
            "running commands and control actions ask for your confirmation."
        ),
        "err_cmd": "unknown command: ",
        "err_lang": "usage: /lang zh or /lang en",
        "err_workspace": "usage: /workspace <absolute path>",
        "err_notdir": "not a valid directory: ",
        "err_autoshell": "usage: /autoshell on|off",
        "err_supervisor": "usage: /supervisor on|off",
        "supervisor_on": "supervisor ON: NAI can OCR the screen and click/scroll/type after each confirmation (screenshots stay in memory, never saved).",
        "supervisor_off": "supervisor OFF.",
        "workspace_set": "workspace set to: ",
        "allow_add": "allowed directory: ",
        "autoshell_on": "commands will ask for confirmation.",
        "autoshell_off": "command confirmation disabled (risky).",
        "sandbox_show": "sandbox (workspace + allowed dirs):\n  workspace: {ws}\n  allowed:",
        "confirm_shell": "NAI wants to run:\n  {cmd}\nType y to allow, n to deny.",
        "confirm_write": "NAI wants to write outside the workspace:\n  {path}\nType y to allow, n to deny.",
        "tool_run": "⟪ tool {name}: {desc}",
        "tool_ok": "⟪ result: {desc}",
        "tool_err": "⟪ error: {desc}",
        "tool_denied": "⟪ denied: {desc}",
        "done": "done",
        "welcome": "NAI ready · fully offline · Chinese/English\nType /help for commands, or just talk to me.",
        "mem_mb": "MB",
        "tok_s": "tok/s",
        "sec": "s",
    },
}
