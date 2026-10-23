# -*- coding: utf-8 -*-
"""Convert the merged HF model to the quantized GGUF shipped with NAI.

Offline pipeline: runs convert_nai.py which writes models/nai.gguf (Q4_0,
344 MB) directly from the merged safetensors via the `gguf` package — no
llama.cpp source download or external quantize.exe needed. The CLI terminal
loads exactly this file.

Why Q4_0 and not Q4_K_M: Qwen2.5's embedding is 151936x896; 896 (and 151936)
are not divisible by 256, so K-quants fall back to q8_0/q5_0 and give almost
no size win. Q4_0 (block 32) quantizes everything to ~344 MB with good quality.
"""
from __future__ import annotations

import os
import shutil
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(ROOT, "models", "nai-1.5b.gguf")
FINAL = os.path.join(ROOT, "models", "nai.gguf")


def main():
    if not os.path.exists(os.path.join(ROOT, "models", "NAI-finetuned-1.5B")):
        sys.exit("models/NAI-finetuned-1.5B missing — run train.py first.")
    # convert_nai.py writes models/nai-1.5b.gguf directly (Q4_0) from env/defaults
    sys.path.insert(0, ROOT)
    import convert_nai
    convert_nai.main()
    if not os.path.exists(SRC):
        sys.exit("conversion produced no nai-1.5b.gguf")
    shutil.copy(SRC, FINAL)
    print(f"[gguf] packaged model ready: {FINAL} ({os.path.getsize(FINAL)/1e6:.0f} MB)")


if __name__ == "__main__":
    main()

