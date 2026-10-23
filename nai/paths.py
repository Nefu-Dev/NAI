# -*- coding: utf-8 -*-
"""Path resolution helpers (works both in dev and inside the PyInstaller EXE)."""
from __future__ import annotations

import os
import sys


def resource_dir() -> str:
    """Directory containing packaged data (sys._MEIPASS when frozen)."""
    if getattr(sys, "frozen", False):
        return sys._MEIPASS
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def resolve_model_path() -> str:
    p = os.environ.get("NAI_MODEL")
    if p and os.path.exists(p):
        return p
    base = resource_dir()
    for cand in (
        os.path.join(base, "nai_models", "nai.gguf"),
        os.path.join(base, "models", "nai.gguf"),
    ):
        if os.path.exists(cand):
            return cand
    raise FileNotFoundError(
        "nai.gguf not found. Set NAI_MODEL or place the model at nai_models/nai.gguf."
    )


def resolve_yolo_path() -> str:
    """Path to the YOLO ONNX detector (bundled with the EXE or in models/)."""
    p = os.environ.get("NAI_YOLO")
    if p and os.path.exists(p):
        return p
    base = resource_dir()
    for cand in (
        os.path.join(base, "nai_models", "yolov8n.onnx"),
        os.path.join(base, "models", "yolov8n.onnx"),
    ):
        if os.path.exists(cand):
            return cand
    raise FileNotFoundError(
        "yolov8n.onnx not found. Set NAI_YOLO or place it at nai_models/yolov8n.onnx."
    )


def default_workspace() -> str:
    d = "D:/AI_Cluster"
    return d if os.path.isdir(d) else os.getcwd()
