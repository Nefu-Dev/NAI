# -*- coding: utf-8 -*-
"""Build the NAI.exe (onefile, windowed) with PyInstaller.
Only the quantized GGUF is bundled (nai_models/nai.gguf) — no HF training stack.
"""
from __future__ import annotations

import os
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))
MODEL = os.path.join(ROOT, "models", "nai.gguf")
YOLO = os.path.join(ROOT, "models", "yolov8n.onnx")
ICON = os.path.join(ROOT, "assets", "nai.ico")
SEP = ";" if os.name == "nt" else ":"


def main():
    if not os.path.exists(MODEL):
        sys.exit("models/nai.gguf missing — run make_gguf.py first.")
    # allow building to a different output name while the current NAI.exe is locked
    out_name = os.environ.get("NAI_OUT_NAME", "NAI")
    args = [
        os.path.join(ROOT, "run_nai.py"),
        "--onefile",
        "--windowed",
        "--name", out_name,
        "--icon", ICON,
        "--add-data", f"{MODEL}{SEP}nai_models",
        "--collect-all", "llama_cpp",
        "--collect-all", "psutil",
        "--hidden-import", "diskcache",
        # supervisor: Windows built-in OCR (winocr + winrt split packages)
        "--collect-all", "winocr",
        "--collect-all", "winrt",
        "--collect-all", "winrt_runtime",
        "--collect-all", "winrt.windows.foundation",
        "--collect-all", "winrt.windows.foundation.collections",
        "--collect-all", "winrt.windows.globalization",
        "--collect-all", "winrt.windows.graphics.imaging",
        "--collect-all", "winrt.windows.media.ocr",
        "--collect-all", "winrt.windows.storage.streams",
        "--hidden-import", "winrt.windows.media.ocr",
        "--hidden-import", "winrt.windows.graphics.imaging",
        "--hidden-import", "winrt.windows.storage.streams",
        "--hidden-import", "winrt.windows.foundation",
        "--hidden-import", "winrt.windows.foundation.collections",
        "--hidden-import", "winrt.windows.globalization",
        "--hidden-import", "winrt_runtime",
        "--hidden-import", "winocr",
        # YOLO vision (onnxruntime, light)
        "--collect-all", "onnxruntime",
        "--collect-all", "numpy",
        "--hidden-import", "onnxruntime",
        "--clean",
        "--noconfirm",
        "--distpath", os.path.join(ROOT, "dist"),
        "--workpath", os.path.join(ROOT, "build", "pyi"),
        "--specpath", os.path.join(ROOT, "build"),
    ]
    if os.path.exists(YOLO):
        args += ["--add-data", f"{YOLO}{SEP}nai_models"]
    import PyInstaller.__main__
    PyInstaller.__main__.run(args)
    print("OK ->", os.path.join(ROOT, "dist", out_name + ".exe"))


if __name__ == "__main__":
    main()
