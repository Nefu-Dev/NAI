# -*- coding: utf-8 -*-
import json, os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from nai import prompt as P
p = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "naifinetune.jsonl")
ex = [
    ("看看屏幕上有什么东西",
     '⟪TOOL:detect_image("screen")⟫\n屏幕上检测到：laptop 0.47 at (984,580) 等。'),
    ("这个图片里有什么",
     '⟪TOOL:detect_image("D:/AI_Cluster/photo.png")⟫\n图片里有 person 0.82 at (200,300)、dog 0.71 at (500,200)。'),
]
n = 0
with open(p, "a", encoding="utf-8") as f:
    for u, a in ex:
        f.write(json.dumps({"messages": [
            {"role": "system", "content": P.SYSTEM},
            {"role": "user", "content": u},
            {"role": "assistant", "content": a},
        ]}, ensure_ascii=False) + "\n")
        n += 1
with open(p, encoding="utf-8") as f:
    print("appended", n, "total", sum(1 for _ in f))
