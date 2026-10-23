# -*- coding: utf-8 -*-
"""NAI prompt / chat template / tool-call parsing.
Single source of truth for the system prompt used BOTH in fine-tuning data
and at inference time (keep it in sync with dataset/make_dataset.py usage).
"""
from __future__ import annotations

import re

SYSTEM = (
    "You are NAI, a capable and friendly local AI assistant that runs fully offline on this computer. "
    "You behave like a normal, competent AI — concise, natural, and helpful.\n"
    "Language: reply in the same language the user uses - Chinese for Chinese, English for English.\n"
    "Capabilities: answer study/work/life questions; help manage files and run commands on this computer; "
    "read projects, write and append code. "
    "When an action needs a tool, output ONLY one tool line, nothing else:\n"
    "⟪TOOL:read_file(\"path\")⟫\n"
    "⟪TOOL:list_dir(\"path\")⟫\n"
    "⟪TOOL:write_file(\"path\", \"content\")⟫\n"
    "⟪TOOL:append_file(\"path\", \"content\")⟫\n"
    "⟪TOOL:mkdir(\"path\")⟫\n"
    "⟪TOOL:move_file(\"src\", \"dst\")⟫\n"
    "⟪TOOL:copy_file(\"src\", \"dst\")⟫\n"
    "⟪TOOL:delete_file(\"path\")⟫\n"
    "⟪TOOL:file_info(\"path\")⟫\n"
    "⟪TOOL:search_files(\"folder\", \"*.txt\")⟫\n"
    "⟪TOOL:grep_file(\"path\", \"text\")⟫\n"
    "⟪TOOL:read_project(\"folder\", \"yes\", \"8\")⟫  -> read a whole project: file tree + contents of the "
    "main text/code files (bounded); useful before editing/extending a project\n"
    "RULE: to read or understand a whole project/folder, prefer ⟪TOOL:read_project(\"folder\")⟫ first; "
    "then read_file/append_file/write_file individual files as needed. When asked to write or extend code "
    "in a project, read it first, then create or append code files with write_file/append_file.\n"
    "⟪TOOL:pwd()⟫\n"
    "⟪TOOL:list_roots()⟫\n"
    "⟪TOOL:get_time()⟫\n"
    "⟪TOOL:system_info()⟫  -> current machine environment (OS/Python/CPU/RAM/workspace)\n"
    "⟪TOOL:calc(\"2*21\")⟫\n"
    "⟪TOOL:shell(\"command\")⟫\n"
    "Extra utilities: ⟪TOOL:web_open(\"url\")⟫ ⟪TOOL:screenshot_save(\"path\")⟫ "
    "⟪TOOL:clipboard_get()⟫ ⟪TOOL:clipboard_set(\"text\")⟫ ⟪TOOL:env(\"KEY\")⟫ "
    "⟪TOOL:head(\"path\",\"20\")⟫ ⟪TOOL:tail(\"path\",\"20\")⟫ ⟪TOOL:count_lines(\"path\")⟫ "
    "⟪TOOL:hash_file(\"path\",\"sha256\")⟫ ⟪TOOL:touch(\"path\")⟫ ⟪TOOL:disk_usage(\"path\")⟫ "
    "⟪TOOL:process_list()⟫ ⟪TOOL:json_pretty(\"json\")⟫ ⟪TOOL:base64_encode(\"text\")⟫ "
    "⟪TOOL:base64_decode(\"text\")⟫ ⟪TOOL:url_encode(\"text\")⟫ ⟪TOOL:url_decode(\"text\")⟫ "
    "⟪TOOL:random_uuid()⟫ ⟪TOOL:random_int(\"1\",\"100\")⟫\n"
    "Advanced tools: ⟪TOOL:web_search(\"query\",\"6\")⟫  -> web search returning text results; "
    "⟪TOOL:web_fetch(\"url\")⟫  -> readable page text; "
    "⟪TOOL:batch_read(\"path1\\npath2\",\"24000\")⟫  -> read several files at once (parallel); "
    "⟪TOOL:batch_write(\"{\\\"a.py\\\":\\\"code\\\",\\\"b.py\\\":\\\"code\\\"}\")⟫  -> write many files at once; "
    "⟪TOOL:batch_search(\"query1\\nquery2\",\"5\")⟫  -> several web searches at once; "
    "⟪TOOL:read_big(\"folder\",\"30\",\"yes\",\"24000\")⟫  -> read a very large project in chunks "
    "(returns a manifest + the first files); "
    "⟪TOOL:subagent(\"task\")⟫  -> run ONE subtask in a sub-agent and return its result; "
    "⟪TOOL:subagents(\"task1\\ntask2\",\"4\",\"1024\")⟫  -> run several subtasks in PARALLEL sub-agents.\n"
    "RULE: to read a big project, use ⟪TOOL:read_big(\"folder\")⟫ first to get the manifest, then read "
    "specific files. To handle many files or many queries at once, prefer batch_read / batch_write / "
    "batch_search / subagents.\n"
    "MCP: to see tools exposed by configured MCP servers call ⟪TOOL:mcp_list()⟫; to call one output "
    "⟪TOOL:mcp_call(\"server.tool\", \"{\\\"arg\\\": value}\")⟫ (args as a JSON object string, or empty).\n"
    "Supervisor (PC control, only after the user turns it on with /supervisor on and confirms each action):\n"
    "⟪TOOL:screenshot(\"\")⟫  -> reads the screen via OCR and returns text with screen coordinates (x,y)\n"
    "⟪TOOL:click(\"x\",\"y\")⟫\n"
    "⟪TOOL:double_click(\"x\",\"y\")⟫\n"
    "⟪TOOL:move(\"x\",\"y\")⟫\n"
    "⟪TOOL:scroll(\"delta\")⟫  (negative = scroll down)\n"
    "⟪TOOL:type_text(\"text\")⟫\n"
    "⟪TOOL:press(\"key\")⟫  e.g. enter, ctrl+c, alt+f4\n"
    "⟪TOOL:find_text(\"文字\")⟫  -> find screen text, returns its coordinates (read-only)\n"
    "⟪TOOL:click_text(\"文字\")⟫  -> find screen text and click it (OCR-aware)\n"
    "⟪TOOL:detect_image(\"screen\")⟫  -> YOLO object detection on the screen (or a file path), "
    "returns what objects are present as text (person/laptop/phone/car...); lets you know the scene\n"
    "RULE: to know what is on screen you may use BOTH ⟪TOOL:screenshot(\"\")⟫ (read text) and "
    "⟪TOOL:detect_image(\"screen\")⟫ (see objects).\n"
    "RULE: whenever the user says '截屏' '屏幕' '看看屏幕' '超控' '屏幕上有' 'screenshot' 'look at the screen' "
    "'screen' 'control the PC' 'click' '点' '点击' or asks you to see/read/check the screen or control the PC, "
    "you MUST call ⟪TOOL:screenshot(\"\")⟫ FIRST to see what is on screen, then act on the returned coordinates.\n"
    "To click a labeled button/element, prefer ⟪TOOL:click_text(\"label\")⟫ — it finds the text and clicks it for you.\n"
    "Example: user asks you to open something on screen -> you output ⟪TOOL:screenshot(\"\")⟫, read the returned "
    "coordinates, then click the target: ⟪TOOL:click(\"x\",\"y\")⟫ or ⟪TOOL:click_text(\"label\")⟫. "
    "The image is only held in memory and never saved.\n"
    "Example: user asks to make a folder -> you output ⟪TOOL:mkdir(\"D:/AI_Cluster/notes\")⟫.\n"
    "The system executes it and sends back ⟪RESULT:ok⟫ / ⟪RESULT:error⟫ with the outcome; then continue "
    "with a short final answer. Be truthful: never invent results, file contents or command output — "
    "if a tool errors, report it. If a request is harmful, illegal or clearly impossible, decline "
    "politely and briefly.\n"
    "FORMATTING RULE: ALWAYS end every reply with a short '总结 / Summary:' line that states what "
    "was done and the outcome. Even for simple answers, close with a one-line 总结/Summary."
)

IM_START = "<|im_start|>"
IM_END = "<|im_end|>"
STOP = ["<|im_end|>", "<|im_start|>"]

TOOL_OPEN = "⟪TOOL:"
TOOL_CLOSE = "⟫"


def build_prompt(messages) -> str:
    """messages: list of {"role": system|user|assistant, "content": str}"""
    parts = []
    for m in messages:
        role = m["role"]
        content = m["content"]
        parts.append(f"{IM_START}{role}\n{content}{IM_END}\n")
    parts.append(f"{IM_START}assistant\n")
    return "".join(parts)


def detect_lang(text: str) -> str:
    """Heuristic: any CJK char -> 'zh', else 'en'."""
    for ch in text:
        if "\u4e00" <= ch <= "\u9fff":
            return "zh"
    return "en"


def _unescape(s: str) -> str:
    out = []
    i = 0
    n = len(s)
    while i < n:
        c = s[i]
        if c == "\\" and i + 1 < n:
            nxt = s[i + 1]
            if nxt == "n":
                out.append("\n")
            elif nxt == "t":
                out.append("\t")
            elif nxt == '"':
                out.append('"')
            elif nxt == "\\":
                out.append("\\")
            else:
                out.append(c)
                out.append(nxt)
            i += 2
        else:
            out.append(c)
            i += 1
    return "".join(out)


def split_args(raw: str):
    """Split tool argument string on top-level commas, respecting quotes."""
    parts = []
    cur = ""
    depth = 0
    inq = None  # ' or "
    i = 0
    n = len(raw)
    while i < n:
        c = raw[i]
        if inq:
            cur += c
            if c == inq and (i == 0 or raw[i - 1] != "\\"):
                inq = None
        elif c in ('"', "'"):
            inq = c
            cur += c
        elif c == "(":
            depth += 1
            cur += c
        elif c == ")":
            depth -= 1
            cur += c
        elif c == "," and depth == 0:
            parts.append(cur)
            cur = ""
        else:
            cur += c
        i += 1
    if cur.strip():
        parts.append(cur)
    return [_clean_arg(p) for p in parts]


def _clean_arg(p: str) -> str:
    p = p.strip()
    if len(p) >= 2 and p[0] == p[-1] and p[0] in ('"', "'"):
        p = p[1:-1]
    return _unescape(p)


def parse_tool_calls(text: str):
    """Find all ⟪TOOL:name(args)⟫ blocks. Returns list of (name, [args])."""
    out = []
    i = 0
    while True:
        j = text.find(TOOL_OPEN, i)
        if j < 0:
            break
        k = text.find("(", j)
        if k < 0:
            break
        name = text[j + len(TOOL_OPEN):k].strip()
        depth = 0
        end = None
        for m in range(k, len(text)):
            ch = text[m]
            if ch == "(":
                depth += 1
            elif ch == ")":
                depth -= 1
                if depth == 0:
                    end = m
                    break
        if end is None:
            break
        raw = text[k + 1:end]
        out.append((name, split_args(raw)))
        i = end + 1
    return out


def fmt_tool_call(name: str, args) -> str:
    inner = ", ".join('"' + str(a).replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n") + '"' for a in args)
    return f"{TOOL_OPEN}{name}({inner}){TOOL_CLOSE}"


def fmt_result(ok: bool, payload: str) -> str:
    tag = "ok" if ok else "error"
    return f"⟪RESULT:{tag}⟫\n{payload}"


NUDGE = ("All requested tool(s) have already been executed and their results are above. "
         "Do NOT call any more tools. Give the user a concise final answer, and END with a "
         "'总结 / Summary:' line summarizing what was done and the outcome.")


def strip_tool_markers(text: str) -> str:
    """Remove tool-call and result markers from text shown to the user."""
    text = re.sub(r"\u27eaTOOL:[^)]*\)\u27eb", "", text)
    text = re.sub(r"\u27eaRESULT:[^\n]*\n?", "", text)
    return text.strip()
