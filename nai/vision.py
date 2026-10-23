# -*- coding: utf-8 -*-
"""Lightweight YOLO object detection -> text, so the text-only NAI model can
"see" what is in an image. Uses onnxruntime (CPU) + yolov8n.onnx — no torch/cv2
at runtime, keeping the EXE small. Detection runs on demand.
"""
from __future__ import annotations

import numpy as np

from . import paths

COCO_NAMES = [
    "person", "bicycle", "car", "motorcycle", "airplane", "bus", "train", "truck",
    "boat", "traffic light", "fire hydrant", "stop sign", "parking meter", "bench",
    "bird", "cat", "dog", "horse", "sheep", "cow", "elephant", "bear", "zebra",
    "giraffe", "backpack", "umbrella", "handbag", "tie", "suitcase", "frisbee",
    "skis", "snowboard", "sports ball", "kite", "baseball bat", "baseball glove",
    "skateboard", "surfboard", "tennis racket", "bottle", "wine glass", "cup",
    "fork", "knife", "spoon", "bowl", "banana", "apple", "sandwich", "orange",
    "broccoli", "carrot", "hot dog", "pizza", "donut", "cake", "chair", "couch",
    "potted plant", "bed", "dining table", "toilet", "tv", "laptop", "mouse",
    "remote", "keyboard", "cell phone", "microwave", "oven", "toaster", "sink",
    "refrigerator", "book", "clock", "vase", "scissors", "teddy bear", "hair drier",
    "toothbrush",
]

IMGSZ = 640
CONF = 0.30
IOU = 0.45

_session = None


def _get_session():
    global _session
    if _session is None:
        import onnxruntime as ort
        _session = ort.InferenceSession(paths.resolve_yolo_path(),
                                        providers=["CPUExecutionProvider"])
    return _session


def _letterbox(img, size=IMGSZ):
    h, w = img.shape[:2]
    r = min(size / h, size / w)
    nw, nh = int(round(w * r)), int(round(h * r))
    from PIL import Image
    im = Image.fromarray(img).resize((nw, nh), Image.BILINEAR)
    canvas = np.full((size, size, 3), 114, dtype=np.uint8)
    canvas[:nh, :nw] = np.asarray(im)
    return canvas, r


def _nms(boxes, scores, iou_thr=IOU):
    # boxes: Nx4 (x1,y1,x2,y2); scores: N. Greedy NMS.
    order = scores.argsort()[::-1]
    keep = []
    x1, y1, x2, y2 = boxes[:, 0], boxes[:, 1], boxes[:, 2], boxes[:, 3]
    areas = (x2 - x1) * (y2 - y1)
    while order.size:
        i = order[0]
        keep.append(int(i))
        if order.size == 1:
            break
        xx1 = np.maximum(x1[i], x1[order[1:]])
        yy1 = np.maximum(y1[i], y1[order[1:]])
        xx2 = np.minimum(x2[i], x2[order[1:]])
        yy2 = np.minimum(y2[i], y2[order[1:]])
        inter = np.maximum(0, xx2 - xx1) * np.maximum(0, yy2 - yy1)
        iou = inter / (areas[i] + areas[order[1:]] - inter + 1e-9)
        order = order[1:][iou <= iou_thr]
    return keep


def detect_objects(img, conf=CONF):
    """Run YOLO on a PIL image, return list of (label, score, x1, y1, x2, y2)
    in the original image coordinate space."""
    arr = np.asarray(img.convert("RGB"))
    canvas, ratio = _letterbox(arr)
    # RGB -> float CHW /255
    blob = np.ascontiguousarray(canvas.transpose(2, 0, 1)).astype(np.float32) / 255.0
    blob = blob[None]
    sess = _get_session()
    out = sess.run(None, {sess.get_inputs()[0].name: blob})[0]  # (1, 84, 8400)
    out = out[0]  # (84, 8400)
    boxes = out[:4].T  # (8400,4) cx,cy,w,h
    scores = out[4:].T  # (8400,80)
    cls_ids = scores.argmax(1)
    cls_scores = scores[np.arange(scores.shape[0]), cls_ids]
    mask = cls_scores > conf
    boxes, cls_ids, cls_scores = boxes[mask], cls_ids[mask], cls_scores[mask]
    if boxes.shape[0] == 0:
        return []
    cx, cy, w, h = boxes[:, 0], boxes[:, 1], boxes[:, 2], boxes[:, 3]
    x1 = (cx - w / 2) / ratio
    y1 = (cy - h / 2) / ratio
    x2 = (cx + w / 2) / ratio
    y2 = (cy + h / 2) / ratio
    det_boxes = np.stack([x1, y1, x2, y2], 1)
    keep = _nms(det_boxes, cls_scores, IOU)
    results = []
    for i in keep:
        label = COCO_NAMES[cls_ids[i]] if cls_ids[i] < len(COCO_NAMES) else f"obj{cls_ids[i]}"
        results.append((label, float(cls_scores[i]),
                        int(round(x1[i])), int(round(y1[i])),
                        int(round(x2[i])), int(round(y2[i]))))
    return results


def describe_objects(img, conf=CONF, max_items=12):
    """YOLO -> a short text description of what is in the image (for NAI)."""
    dets = detect_objects(img, conf)
    if not dets:
        return "(yolo: no recognizable objects)"
    lines = []
    for label, score, x1, y1, x2, y2 in dets[:max_items]:
        cx = (x1 + x2) // 2
        cy = (y1 + y2) // 2
        lines.append(f"{label} {score:.2f} at ({cx},{cy}) size {x2-x1}x{y2-y1}")
    return "\n".join(lines)
