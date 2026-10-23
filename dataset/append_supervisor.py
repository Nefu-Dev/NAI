# -*- coding: utf-8 -*-
import json, os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from nai import prompt as P

path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "naifinetune.jsonl")
sys = P.SYSTEM  # includes supervisor tools

examples = [
    ("截屏，看看屏幕上有什么",
     '⟪TOOL:screenshot("")⟫\n'
     '屏幕上检测到这些文字：\n(120,50) 新建对话\n(89,287) 手机 遥 控 电 脑\n(77,321) API 服务\n'
     '我读到了屏幕上的内容。'),
    ("点击屏幕上的'新 对 话'按钮",
     '⟪TOOL:screenshot("")⟫\n'
     '⟪TOOL:click("82","151")⟫\n'
     '我已点击“新 对 话”。'),
    ("用键盘输入 hello，然后按回车",
     '⟪TOOL:type_text("hello")⟫\n⟪TOOL:press("enter")⟫\n'
     '已输入 hello 并回车。'),
    ("帮我向下滚动一屏",
     '⟪TOOL:scroll("-6")⟫\n'
     '已向下滚动。'),
    ("双击坐标 400,300 处的文件",
     '⟪TOOL:double_click("400","300")⟫\n'
     '已双击该文件。'),
]

added = 0
with open(path, "a", encoding="utf-8") as f:
    for user, asst in examples:
        rec = {"messages": [
            {"role": "system", "content": sys},
            {"role": "user", "content": user},
            {"role": "assistant", "content": asst},
        ]}
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        added += 1
print("appended", added)
with open(path, encoding="utf-8") as f:
    print("total lines:", sum(1 for _ in f))
