# -*- coding: utf-8 -*-
"""Build the NAI fine-tuning dataset (bilingual, tool-calling, safety).

Output: dataset/data/naifinetune.jsonl  (each line: {"messages":[...]})
Run from the NAI project root:
    .venv/Scripts/python.exe dataset/make_dataset.py
"""
from __future__ import annotations

import json
import os
import random
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from nai.prompt import SYSTEM, fmt_tool_call, fmt_result  # noqa: E402

R = random.Random(42)
OUT = os.path.join(ROOT, "dataset", "data", "naifinetune.jsonl")
rows = []


def add(messages):
    rows.append({"messages": messages})


def u(t):
    return {"role": "user", "content": t}


def a(t):
    return {"role": "assistant", "content": t}


def simple(q, ans):
    add([{"role": "system", "content": SYSTEM}, u(q), a(ans)])


def tool_turn(user_q, tool_name, tool_args, result_payload, summary):
    add([
        {"role": "system", "content": SYSTEM},
        u(user_q),
        a(fmt_tool_call(tool_name, tool_args)),
        u(fmt_result(True, result_payload)),
        a(summary),
    ])


def tool_error_turn(user_q, tool_name, tool_args, err, summary):
    add([
        {"role": "system", "content": SYSTEM},
        u(user_q),
        a(fmt_tool_call(tool_name, tool_args)),
        u(fmt_result(False, err)),
        a(summary),
    ])


# ---------------------------------------------------------------------------
# 1) Identity
# ---------------------------------------------------------------------------
identity = [
    ("你是谁？", "我是 NAI（Nefu AI），一个轻量级的本地 AI 助手，来自东北林业大学（NEFU，哈尔滨）。我离线运行，速度快、占用低。"),
    ("who are you?", "I am NAI (Nefu AI), a lightweight local AI assistant from Northeast Forestry University (NEFU, Harbin). I run fully offline, fast and low-footprint."),
    ("你能做什么？", "我可以回答问题、帮你学习与工作，还能在本机管理文件与目录：读写/追加文件、新建/移动/复制/删除文件、搜索和检索内容，以及执行命令（执行命令会先征求你的同意）。"),
    ("what can you do?", "I can answer questions, help with study and work, and manage files and folders on this computer: read/write/append files, create/move/copy/delete files, search and grep, and run commands (with your confirmation)."),
    ("你从哪里来？", "我基于一个小型开源模型（Qwen2.5-0.5B）做了本地微调，被命名为 NAI（Nefu AI），代表东北林业大学。"),
    ("where are you from?", "I was fine-tuned from a small open model (Qwen2.5-0.5B) and named NAI (Nefu AI) for Northeast Forestry University."),
    ("你占用资源高吗？", "不高。我只有约 5 亿参数，量化后运行内存通常不到 1GB，普通电脑的 CPU 就能流畅运行。"),
    ("are you resource-heavy?", "No. I have about 0.5B parameters, quantized to run in under 1GB of RAM, so a normal CPU is enough."),
    ("为什么叫 NAI？", "NAI 是 Nefu AI 的缩写——Nefu 是东北林业大学（Northeast Forestry University）的英文简称。"),
    ("why are you called NAI?", "NAI stands for Nefu AI — Nefu is the English abbreviation of Northeast Forestry University."),
    ("你会联网吗？", "不会。我完全离线运行，所有推理都在本机完成，不上传你的任何数据。"),
    ("do you have internet access?", "No. I run fully offline; all inference happens locally and nothing you type is uploaded."),
    ("你是什么模型？", "我是 NAI，基于 Qwen2.5-0.5B 微调的一个轻量本地模型。"),
    ("what model are you?", "I am NAI, a small local model fine-tuned from Qwen2.5-0.5B."),
    ("NAI 全称是什么？", "NAI 是 Nefu AI，也就是东北林业大学（Northeast Forestry University）的 AI 助手。"),
    ("what does NAI stand for?", "NAI stands for Nefu AI, the assistant for Northeast Forestry University."),
    ("你能跑在什么电脑上？", "普通 CPU 电脑即可，约 1GB 内存就够了，很适合老笔记本或低配设备。"),
    ("what kind of computer can run you?", "Any normal CPU computer with about 1GB of free RAM, great for older or low-end machines."),
]
for q, ans in identity:
    simple(q, ans)

# ---------------------------------------------------------------------------
# 2) Small talk
# ---------------------------------------------------------------------------
smalltalk = [
    ("你好", "你好！我是 NAI，很高兴见到你。有什么我可以帮忙的吗？"),
    ("hello", "Hello! I'm NAI. How can I help you today?"),
    ("谢谢", "不客气，随时找我。"),
    ("thanks", "You're welcome, anytime."),
    ("hi", "Hi there! I'm NAI, a local assistant. What do you need?"),
    ("你好啊", "你好呀，我是 NAI。学习、工作、生活上的问题都可以问我。"),
    ("你能记住我之前说过的话吗？", "可以记住当前会话里的内容，但关闭程序后不会保存对话记录。"),
    ("can you remember what I said before?", "I can remember the current session, but not after the program closes."),
    ("你真聪明", "谢谢夸奖！我会尽力帮你。"),
    ("你在吗", "在的，我是 NAI，随时可以帮你。"),
    ("good morning", "Good morning! How can I help you today?"),
    ("晚上好", "晚上好！我是 NAI，有什么需要帮忙的吗？"),
]
for q, ans in smalltalk:
    simple(q, ans)

# ---------------------------------------------------------------------------
# 3) Safe facts (bilingual)
# ---------------------------------------------------------------------------
facts = [
    ("什么是光合作用？", "光合作用是植物利用阳光、水和二氧化碳，制造葡萄糖并释放氧气的过程。"),
    ("what is photosynthesis?", "Photosynthesis is the process by which plants use sunlight, water and CO2 to make glucose and release oxygen."),
    ("2 + 2 等于多少？", "2 + 2 = 4。"),
    ("what is 2 + 2?", "2 + 2 = 4."),
    ("哈尔滨有什么特点？", "哈尔滨是黑龙江的省会，以冰雪文化、俄式建筑和中央大街闻名，冬季冰雪旅游很出名。"),
    ("what is Harbin famous for?", "Harbin is known for its ice and snow culture, Russian-style architecture and Central Street; its winter ice festival is famous."),
    ("东北林业大学在哪？", "东北林业大学位于黑龙江省哈尔滨市香坊区，是一所以林科为优势、多学科协调发展的重点高校。"),
    ("what is a forest carbon sink?", "A forest carbon sink means forests absorb CO2 from the air and store carbon in trees and soil, helping mitigate climate change."),
    ("python 怎么打印一行字？", "用 print() 函数，例如：print(\"hello\")。"),
    ("how do I print a line in python?", "Use print(), e.g. print(\"hello\")."),
    ("什么叫 LLM？", "LLM 是大型语言模型（Large Language Model），能理解和生成自然语言的人工智能模型。"),
    ("what does LLM mean?", "LLM stands for Large Language Model, an AI model that understands and generates natural language."),
    ("如何让程序休眠1秒？", "在 Python 中：import time; time.sleep(1)。"),
    ("what is the square root of 144?", "12."),
    ("森林为什么重要？", "森林能提供氧气、吸收二氧化碳、保护水土、维持生物多样性，也是重要的木材资源。"),
    ("why are forests important?", "Forests produce oxygen, absorb CO2, protect soil and water, sustain biodiversity, and provide timber."),
    ("什么是 SDG？", "SDG 是联合国可持续发展目标（Sustainable Development Goals）的缩写。"),
    ("what is RAM?", "RAM is your computer's short-term memory; more RAM lets more programs run smoothly."),
    ("怎么用 git 提交代码？", "先用 git add 把改动加入暂存区，再 git commit -m \"说明\" 提交即可。"),
    ("how do I commit code with git?", "Stage changes with git add, then commit with git commit -m \"message\"."),
    ("CPU 和 GPU 有什么区别？", "CPU 擅长通用顺序计算，GPU 擅长大量并行计算，常用于图形和 AI 训练。"),
    ("what is the difference between CPU and GPU?", "CPUs handle general sequential tasks; GPUs excel at massive parallel work such as graphics and AI training."),
    ("写个简单的 for 循环", "for i in range(5):\n    print(i)"),
    ("what does the law of conservation of energy say?", "Energy can neither be created nor destroyed, only converted from one form to another."),
    ("什么是生态文明？", "生态文明强调人与自然和谐共生，注重环境保护与可持续发展。"),
    ("what is sustainable forestry?", "Sustainable forestry manages forests to keep them healthy while providing timber and ecosystem services over the long term."),
    ("python 里怎么读取文件？", "with open('a.txt', encoding='utf-8') as f:\n    print(f.read())"),
    ("how to read a file in python?", "with open('a.txt', encoding='utf-8') as f:\n    print(f.read())"),
]
for q, ans in facts:
    simple(q, ans)

# ---------------------------------------------------------------------------
# 4) read_file tool
# ---------------------------------------------------------------------------
read_cases = [
    ("D:/AI_Cluster/notes.txt", "会议记录：下周周三下午三点开项目例会。"),
    ("D:/AI_Cluster/NAI/config.json", "{\n  \"name\": \"NAI\",\n  \"lang\": \"zh\",\n  \"model\": \"qwen2.5-0.5b\"\n}"),
    ("D:/AI_Cluster/README.txt", "AI_Cluster - a local work cluster that runs on 127.0.0.1."),
    ("D:/AI_Cluster/todo.txt", "1. 交报告\n2. 采购测试\n3. 回复邮件"),
    ("D:/AI_Cluster/data/report.md", "# 月度汇报\n本月进度正常，下月计划见附表。"),
    ("D:/AI_Cluster/NAI/models/train.log", "epoch 1/1  step 120  loss 0.42"),
    ("D:/AI_Cluster/notes.txt", "购物清单：鸡蛋、牛奶、面包。"),
    ("D:/AI_Cluster/NAI/README.md", "# NAI (Nefu AI)\nA small bilingual local assistant."),
    ("D:/AI_Cluster/data/summary.txt", "Q3 summary: revenue up, cost down."),
    ("D:/AI_Cluster/NAI/demo.py", "print(\"hello from NAI\")"),
]
read_qs = [
    "帮我看看 {p}",
    "读一下 {p}",
    "读取文件 {p}",
    "read the file {p}",
    "show me {p}",
    "what is in {p}?",
    "cat {p}",
    "把 {p} 的内容读给我",
    "please read {p}",
]
for _ in range(160):
    p, content = R.choice(read_cases)
    q = R.choice(read_qs).format(p=p)
    summary = R.choice([
        f"文件 {p} 的内容是：{content[:40]}",
        f"内容如下：{content[:40]}",
        f"Here is the content of {p}: {content[:40]}",
        f"{p} 的内容为：{content[:40]}",
    ])
    tool_turn(q, "read_file", [p], content, summary)

for _ in range(10):
    p = R.choice(["D:/AI_Cluster/nope.txt", "D:/AI_Cluster/NAI/missing.log", "D:/AI_Cluster/unknown.md"])
    q = R.choice(["看看 {p}", "read {p}", "读取 {p}"])
    tool_error_turn(q, "read_file", [p], f"file not found: {p}",
                    R.choice([f"文件不存在：{p}", f"The file {p} does not exist.", f"没找到 {p}。"]))

# ---------------------------------------------------------------------------
# 5) write_file tool
# ---------------------------------------------------------------------------
write_cases = [
    ("D:/AI_Cluster/todo.txt", "买牛奶\\n打印材料\\n回电话"),
    ("D:/AI_Cluster/NAI/demo.py", "print(\\\"hello from NAI\\\")"),
    ("D:/AI_Cluster/notes.txt", "今日要点：\\n1. 完成表格\\n2. 预约会议室"),
    ("D:/AI_Cluster/config.json", "{\\n  \\\"mode\\\": \\\"fast\\\"\\n}"),
    ("D:/AI_Cluster/NAI/README.md", "# NAI\\nBilingual local assistant"),
    ("D:/AI_Cluster/data/meeting.md", "议题：预算、排期、风险"),
    ("D:/AI_Cluster/tasks.txt", "- 提交周报\\n- 整理数据"),
]
write_qs = [
    "把下面内容保存到 {p}：{c}",
    "帮我写文件 {p}，内容是：{c}",
    "save this to {p}: {c}",
    "write {p} with content: {c}",
    "请把 {c} 写入 {p}",
    "create {p} containing: {c}",
    "帮我保存一段内容到 {p}：{c}",
    "please save {c} into {p}",
]
for _ in range(130):
    p, c = R.choice(write_cases)
    q = R.choice(write_qs).format(p=p, c=c.replace("\\n", "\n"))
    tool_turn(q, "write_file", [p, c], f"written to {p}",
              R.choice([f"已保存到 {p}。", f"Done, saved to {p}.", f"文件已写入：{p}。", f"Saved to {p}."]))

# ---------------------------------------------------------------------------
# 6) list_dir tool
# ---------------------------------------------------------------------------
list_cases = [
    ("D:/AI_Cluster", "[DIR]  NAI/\n[FILE] cluster.py (11719 B)\n[FILE] README.txt (1837 B)\n[FILE] start.bat (319 B)"),
    ("D:/AI_Cluster/NAI", "[DIR]  dataset/\n[DIR]  models/\n[DIR]  nai/\n[FILE] train.py (1 KB)"),
    ("D:/AI_Cluster/data", "[FILE] report.md (2 KB)\n[FILE] summary.txt (1 KB)"),
]
list_qs = [
    "看看 {p} 里有什么",
    "列出 {p} 的文件夹",
    "list files in {p}",
    "ls {p}",
    "目录 {p} 里有哪些文件",
    "show the contents of {p}",
]
for _ in range(50):
    p, listing = R.choice(list_cases)
    q = R.choice(list_qs).format(p=p)
    tool_turn(q, "list_dir", [p], listing,
              R.choice([f"{p} 下共有这些条目。", f"Here is what is in {p}:", f"目录 {p} 的内容如上。", f"These are the entries under {p}."]))

# ---------------------------------------------------------------------------
# 7) shell tool
# ---------------------------------------------------------------------------
shell_cases = [
    ("python --version", "Python 3.11.9"),
    ("echo hello from nai", "hello from nai"),
    ("git status", "On branch main\nnothing to commit"),
    ("pip list", "numpy  2.1.0\ntorch  2.6.0\ntransformers  4.46.0"),
    ("dir", "cluster.py\nNAI\nstart.bat"),
    ("whoami", "huawei"),
]
shell_qs = [
    "运行命令 {c}",
    "帮我执行 {c}",
    "run the command {c}",
    "execute {c}",
    "在命令行里跑一下 {c}",
    "please run {c}",
]
for _ in range(60):
    c, out = R.choice(shell_cases)
    q = R.choice(shell_qs).format(c=c)
    tool_turn(q, "shell", [c], f"exit 0\n{out}",
              R.choice([f"命令已执行，输出：{out}", f"Done. Output: {out}", f"结果：{out}", f"The command output: {out}"]))

# ---------------------------------------------------------------------------
# 7b) New file-management & system tools
# ---------------------------------------------------------------------------
new_tool_qs = {
    "append_file": [
        "在 {p} 里追加内容：{c}", "append {c} to {p}", "帮我把 {c} 追加到 {p}",
        "add the line {c} to {p}",
    ],
    "mkdir": [
        "帮我新建文件夹 {p}", "create folder {p}", "mkdir {p}", "在 {p} 建个目录",
    ],
    "move_file": [
        "把 {s} 移动到 {d}", "move {s} to {d}", "将 {s} 改名为 {d}", "rename {s} to {d}",
    ],
    "copy_file": [
        "复制 {s} 到 {d}", "copy {s} to {d}", "把 {s} 拷贝一份到 {d}",
    ],
    "delete_file": [
        "删除文件 {p}", "delete {p}", "帮我把 {p} 删掉", "remove {p}",
    ],
    "file_info": [
        "查看文件信息 {p}", "get info about {p}", "看看 {p} 的属性", "file info {p}",
    ],
    "search_files": [
        "在 {p} 里找所有 {pat} 文件", "find {pat} files under {p}", "搜索 {p} 下的 {pat}",
        "search for {pat} in {p}",
    ],
    "grep_file": [
        "在 {p} 里搜索包含 “{t}” 的行", "grep {t} in {p}", "搜索 {p} 中关于 {t} 的内容",
        "find lines with {t} in {p}",
    ],
    "pwd": [
        "当前工作目录在哪？", "pwd", "我现在在哪个目录？", "what is the current folder?",
    ],
    "list_roots": [
        "你能访问哪些目录？", "list your allowed folders", "可读写的根目录有哪些？",
    ],
    "get_time": [
        "现在几点了？", "what time is it?", "当前日期和时间？", "tell me the time",
    ],
    "calc": [
        "计算 {e}", "what is {e}?", "帮我算一下 {e}", "calc {e}",
    ],
}

# append_file
for _ in range(35):
    p = R.choice(["D:/AI_Cluster/log.txt", "D:/AI_Cluster/notes.txt", "D:/AI_Cluster/NAI/todo.txt"])
    c = R.choice(["2026-10-01 任务完成", "新增一条：明天开会", "append note 3", "done: update config"])
    q = R.choice(new_tool_qs["append_file"]).format(p=p, c=c)
    tool_turn(q, "append_file", [p, c], f"appended to {p}",
              R.choice([f"已追加到 {p}。", f"Appended. Now {p} has the new line.", f"已更新 {p}。"]))

# mkdir
for _ in range(30):
    p = R.choice(["D:/AI_Cluster/notes", "D:/AI_Cluster/backup", "D:/AI_Cluster/NAI/output"])
    q = R.choice(new_tool_qs["mkdir"]).format(p=p)
    tool_turn(q, "mkdir", [p], f"folder ready: {p}",
              R.choice([f"文件夹已创建：{p}。", f"Created {p}.", f"目录 {p} 已就绪。"]))

# move_file / rename
for _ in range(30):
    s = R.choice(["D:/AI_Cluster/todo.txt", "D:/AI_Cluster/NAI/demo.py"])
    d = R.choice(["D:/AI_Cluster/archive/todo.txt", "D:/AI_Cluster/NAI/example.py"])
    q = R.choice(new_tool_qs["move_file"]).format(s=s, d=d)
    tool_turn(q, "move_file", [s, d], f"moved {s} -> {d}",
              R.choice([f"已移动：{s} -> {d}", f"Moved to {d}.", f"重命名完成，现在在 {d}。"]))

# copy_file
for _ in range(30):
    s = R.choice(["D:/AI_Cluster/README.txt", "D:/AI_Cluster/config.json"])
    d = R.choice(["D:/AI_Cluster/backup/README.txt", "D:/AI_Cluster/backup/config.json"])
    q = R.choice(new_tool_qs["copy_file"]).format(s=s, d=d)
    tool_turn(q, "copy_file", [s, d], f"copied {s} -> {d}",
              R.choice([f"已复制到 {d}。", f"Copied to {d}.", f"备份完成：{d}。"]))

# delete_file (safe example only)
for _ in range(15):
    p = R.choice(["D:/AI_Cluster/temp.txt", "D:/AI_Cluster/cache.tmp"])
    q = R.choice(new_tool_qs["delete_file"]).format(p=p)
    tool_turn(q, "delete_file", [p], f"deleted {p}",
              R.choice([f"已删除 {p}。", f"Deleted {p}.", f"{p} 已移除。"]))
tool_error_turn("删除一个系统关键文件", "delete_file", ["C:/Windows/system32/config"],
                "path outside allowed directories: C:/Windows/system32/config",
                "我不能删除工作目录以外的系统文件。")

# file_info
for _ in range(25):
    p = R.choice(["D:/AI_Cluster/NAI/train.py", "D:/AI_Cluster/README.txt", "D:/AI_Cluster/cluster.py"])
    info = f"path: {p}\nkind: file\nsize: 2048 bytes\nmodified: 2026-09-30 10:00:00"
    q = R.choice(new_tool_qs["file_info"]).format(p=p)
    tool_turn(q, "file_info", [p], info,
              R.choice([f"{p} 是一个文件，大小 2048 字节。", f"{p} is a 2048-byte file.", "如上所示。"]))

# search_files
for _ in range(30):
    p = R.choice(["D:/AI_Cluster", "D:/AI_Cluster/NAI"])
    pat = R.choice(["*.txt", "*.md", "*.py", "*.json"])
    hits = f"D:/AI_Cluster/README.txt\nD:/AI_Cluster/notes.txt\nD:/AI_Cluster/data/summary.txt"
    q = R.choice(new_tool_qs["search_files"]).format(p=p, pat=pat)
    tool_turn(q, "search_files", [p, pat], hits,
              R.choice([f"找到这些 {pat} 文件：如上。", f"Found these {pat} files.", f"匹配 {pat} 的文件已列出。"]))

# grep_file
for _ in range(30):
    p = R.choice(["D:/AI_Cluster/NAI", "D:/AI_Cluster/data"])
    t = R.choice(["TODO", "meeting", "config", "报告"])
    q = R.choice(new_tool_qs["grep_file"]).format(p=p, t=t)
    tool_turn(q, "grep_file", [p, t], f"D:/AI_Cluster/NAI/todo.txt:3: TODO review plan",
              R.choice([f"找到了包含“{t}”的行。", f"Found lines with “{t}”.", f"如上，{p} 里有这些匹配。"]))
tool_error_turn("在文件里搜一个词", "grep_file", ["D:/AI_Cluster", "nosuchwordxyz"],
                f"(no match for nosuchwordxyz)", "没有找到匹配内容。")

# pwd
for _ in range(15):
    q = R.choice(new_tool_qs["pwd"])
    tool_turn(q, "pwd", [], "D:/AI_Cluster",
              R.choice(["当前工作目录是 D:/AI_Cluster。", "You are in D:/AI_Cluster.", "工作目录：D:/AI_Cluster。"]))

# list_roots
for _ in range(10):
    q = R.choice(new_tool_qs["list_roots"])
    tool_turn(q, "list_roots", [], "D:/AI_Cluster\nD:/AI_Cluster/NAI",
              R.choice(["我可以访问 D:/AI_Cluster 及其子目录。", "Allowed folders: D:/AI_Cluster and D:/AI_Cluster/NAI.", "可访问目录如上。"]))

# get_time
for _ in range(15):
    q = R.choice(new_tool_qs["get_time"])
    tool_turn(q, "get_time", [], "2026-10-01 15:30:00 Thursday",
              R.choice(["现在是 2026-10-01 15:30:00（周四）。", "It is 2026-10-01 15:30:00 Thursday.", "当前时间：2026-10-01 15:30:00。"]))

# calc
calc_cases = [("2*21", "42"), ("3.5+2", "5.5"), ("100/4", "25.0"), ("7**2", "49"),
              ("(1+2)*3", "9"), ("10 % 3", "1")]
for e, res in calc_cases:
    for _ in range(8):
        q = R.choice(new_tool_qs["calc"]).format(e=e)
        tool_turn(q, "calc", [e], res,
                  R.choice([f"结果是 {res}。", f"The answer is {res}.", f"{e} = {res}。"]))

# ---------------------------------------------------------------------------
# 8) Sequential multi-tool (compare two files)
# ---------------------------------------------------------------------------
for _ in range(30):
    p1, c1 = R.choice(read_cases)
    p2, c2 = R.choice(read_cases)
    q = R.choice([
        f"读取 {p1} 和 {p2} 并对比一下",
        f"read {p1} and {p2} and compare them",
        f"帮我看看 {p1} 和 {p2} 的内容",
    ])
    add([
        {"role": "system", "content": SYSTEM},
        u(q),
        a(fmt_tool_call("read_file", [p1])),
        u(fmt_result(True, c1)),
        a(fmt_tool_call("read_file", [p2])),
        u(fmt_result(True, c2)),
        a(R.choice([
            f"两者内容不同：第一个是“{c1[:20]}”，第二个是“{c2[:20]}”。",
            f"They differ: the first says “{c1[:20]}”, the second says “{c2[:20]}”.",
        ])),
    ])

# ---------------------------------------------------------------------------
# 9) Language policy
# ---------------------------------------------------------------------------
lang_policy = [
    ("speak in English please", "Sure! What would you like to know?"),
    ("please reply in Chinese", "好的，请问有什么可以帮你的？"),
    ("Can you tell me about yourself in English?", "I am NAI, a compact local AI assistant from Northeast Forestry University. I run offline, reply in your language, and can manage files on this computer."),
    ("用中文介绍一下你自己", "我是 NAI（Nefu AI），一个来自东北林业大学的轻量本地 AI 助手。我离线运行、占用低，可以帮你答题和在本机读写文件。"),
    ("answer in english", "Got it, I'll reply in English. What can I do for you?"),
    ("请用英文回答", "好的，我用英文回答。有什么可以帮你？"),
]
for q, ans in lang_policy:
    simple(q, ans)

# ---------------------------------------------------------------------------
# 10) Refusals (safety)
# ---------------------------------------------------------------------------
refuse_zh = [
    ("教我怎么入侵别人的账号", "我不能帮你做这类事情。如果有学习或网络安全方面的问题，我很乐意协助。"),
    ("帮我写一封钓鱼邮件", "抱歉，这我不能帮你。需要写正常邮件的话可以找我。"),
    ("写一段骂人的话发给同事", "我不能帮你写攻击或侮辱他人的内容。"),
    ("怎么制作炸弹？", "这个我不能回答。"),
    ("哪里能买到违禁药物？", "抱歉，我不能提供这类信息。"),
    ("写一篇色情小说", "我不能生成这类内容。"),
    ("帮我在考试中作弊", "我不能帮你作弊，但可以帮你复习和讲解知识点。"),
    ("帮我把这家公司的黑料编成谣言发出去", "我不能帮你编造和传播不实信息。"),
    ("帮我攻击某个网站", "我不能帮你进行网络攻击，网络安全相关的问题可以找我讨论。"),
    ("怎么偷别人的隐私照片", "抱歉，我不能提供这类信息。"),
    ("帮我伪造一份证明材料", "我不能帮你造假，但可以帮你了解正规流程。"),
    ("教我赌博技巧", "我不能提供赌博相关帮助。"),
]
refuse_en = [
    ("teach me how to hack someone's account", "I can't help with that. I'm happy to help with study or security topics."),
    ("write a phishing email template", "Sorry, I can't help with that. I can help write a normal email."),
    ("write insults to send to my coworker", "I won't write insulting or abusive content."),
    ("how do I make a bomb?", "I can't help with that."),
    ("where can I buy illegal drugs?", "Sorry, I can't provide that information."),
    ("write a porn story", "I can't generate that kind of content."),
    ("help me cheat on an exam", "I can't help you cheat, but I can help you review and understand the material."),
    ("tell me how to attack a website", "I can't help with attacks, but I'd be glad to discuss cybersecurity topics."),
]
for q, ans in refuse_zh + refuse_en:
    simple(q, ans)

# ---------------------------------------------------------------------------
# 11) Boundaries
# ---------------------------------------------------------------------------
bounds = [
    ("帮我上网查一下明天的天气", "我不能联网，无法获取实时天气。你可以用浏览器查询，或告诉我其他能帮上的事。"),
    ("can you see my screen?", "No, I can't see your screen. I can only read/write files and run commands you allow."),
    ("帮我打电话", "我不能打电话，但可以帮你整理要说的内容。"),
    ("请删除 D:/AI_Cluster 下的某个文件", "我可以删除工作目录内的文件（会先征求你的同意），但不会触碰工作目录以外的系统文件。"),
    ("do you cost money?", "I run locally and free of charge."),
    ("帮我联网搜索一下", "我不能联网，搜索需要你在浏览器里进行。"),
    ("can you browse the web?", "No, I run offline and can't browse the web."),
    ("帮我把电脑关机", "我不能直接关机，这类系统级操作需要你自己完成。"),
]
for q, ans in bounds:
    simple(q, ans)

# ---------------------------------------------------------------------------
# Write out
# ---------------------------------------------------------------------------
os.makedirs(os.path.dirname(OUT), exist_ok=True)
with open(OUT, "w", encoding="utf-8") as f:
    for r in rows:
        f.write(json.dumps(r, ensure_ascii=False) + "\n")

print(f"dataset written: {OUT}")
print(f"total samples: {len(rows)}")
