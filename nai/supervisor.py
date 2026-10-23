# -*- coding: utf-8 -*-
"""NAI supervisor: optional "take over the PC" capability.

Adds screen reading (screenshot -> Windows built-in OCR -> text+coordinates,
image held only in memory and never written to disk) and real input control
(click / double-click / move / scroll / type / press) via ctypes — no extra deps.

Everything is gated:
  * a master switch `supervisor_enabled` (turned on with /supervisor on + confirm)
  * per-action confirmation through `confirm_hook`
"""
from __future__ import annotations

import ctypes
import time
from ctypes import wintypes

user32 = ctypes.windll.user32

# ---- win32 constants ----
KEYEVENTF_KEYUP = 0x0002
KEYEVENTF_UNICODE = 0x0004
MOUSEEVENTF_LEFTDOWN = 0x0002
MOUSEEVENTF_LEFTUP = 0x0004
MOUSEEVENTF_RIGHTDOWN = 0x0008
MOUSEEVENTF_RIGHTUP = 0x0010
MOUSEEVENTF_WHEEL = 0x0800

VK = {
    "enter": 0x0D, "return": 0x0D, "tab": 0x09, "esc": 0x1B, "escape": 0x1B,
    "space": 0x20, "backspace": 0x08, "delete": 0x2E, "del": 0x2E,
    "up": 0x26, "down": 0x28, "left": 0x25, "right": 0x27,
    "home": 0x24, "end": 0x23, "pageup": 0x21, "pagedown": 0x22, "pgup": 0x21, "pgdn": 0x22,
    "ctrl": 0x11, "alt": 0x12, "shift": 0x10, "win": 0x5B, "meta": 0x5B,
    "capslock": 0x14, "caps": 0x14,
}
for i, name in enumerate(["f1", "f2", "f3", "f4", "f5", "f6", "f7", "f8", "f9", "f10", "f11", "f12"]):
    VK[name] = 0x70 + i


def screen_size():
    return user32.GetSystemMetrics(0), user32.GetSystemMetrics(1)


def _move(x, y):
    user32.SetCursorPos(int(round(x)), int(round(y)))


def _mouse_click(button="left", clicks=1, x=None, y=None, delay=0.06):
    if x is not None:
        _move(x, y)
        time.sleep(delay)
    down, up = (MOUSEEVENTF_LEFTDOWN, MOUSEEVENTF_LEFTUP) if button == "left" \
        else (MOUSEEVENTF_RIGHTDOWN, MOUSEEVENTF_RIGHTUP)
    for _ in range(clicks):
        user32.mouse_event(down, 0, 0, 0, 0)
        user32.mouse_event(up, 0, 0, 0, 0)
        if clicks > 1:
            time.sleep(0.08)


def _scroll(delta):
    # positive = up, negative = down (Windows wheel convention)
    user32.mouse_event(MOUSEEVENTF_WHEEL, 0, 0, int(delta) * 120, 0)


class _KEYBDINPUT(ctypes.Structure):
    _fields_ = [("wVk", wintypes.WORD), ("wScan", wintypes.WORD),
                ("dwFlags", wintypes.DWORD), ("time", wintypes.DWORD),
                ("dwExtraInfo", ctypes.POINTER(wintypes.ULONG))]


class _MOUSEINPUT(ctypes.Structure):
    _fields_ = [("dx", wintypes.LONG), ("dy", wintypes.LONG),
                ("mouseData", wintypes.DWORD), ("dwFlags", wintypes.DWORD),
                ("time", wintypes.DWORD), ("dwExtraInfo", ctypes.POINTER(wintypes.ULONG))]


class _HARDWAREINPUT(ctypes.Structure):
    _fields_ = [("uMsg", wintypes.DWORD), ("wParamL", wintypes.WORD), ("wParamH", wintypes.WORD)]


class _INPUTUNION(ctypes.Union):
    _fields_ = [("mi", _MOUSEINPUT), ("ki", _KEYBDINPUT), ("hi", _HARDWAREINPUT)]


class _INPUT(ctypes.Structure):
    _fields_ = [("type", wintypes.DWORD), ("u", _INPUTUNION)]


def _send_input(ki):
    inp = _INPUT()
    inp.type = 1  # INPUT_KEYBOARD
    inp.u.ki = ki
    user32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(_INPUT))


def _send_unicode(code: int):
    ki = _KEYBDINPUT(0, code, KEYEVENTF_UNICODE, 0, None)
    _send_input(ki)
    ki.dwFlags = KEYEVENTF_UNICODE | KEYEVENTF_KEYUP
    _send_input(ki)


def _press_key(vk: int, delay=0.04):
    ki = _KEYBDINPUT(vk, 0, 0, 0, None)
    _send_input(ki)
    ki.dwFlags = KEYEVENTF_KEYUP
    _send_input(ki)
    time.sleep(delay)


def type_text(s: str):
    for ch in s:
        if ch == "\n":
            _press_key(VK["enter"])
        elif ch == "\t":
            _press_key(VK["tab"])
        elif ch in ("\r",):
            _press_key(VK["enter"])
        else:
            _send_unicode(ord(ch))
            time.sleep(0.004)


def press(combo: str):
    """Press one key or a modifier combo, e.g. 'enter', 'ctrl+c', 'alt+f4'."""
    combo = combo.strip().lower().replace(" ", "")
    parts = [p for p in combo.split("+") if p]
    if not parts:
        raise ValueError("empty key")
    mods = [VK[p] for p in parts[:-1] if p in VK]
    key = parts[-1]
    if key not in VK:
        if len(key) == 1 and key.isalnum():
            key = key.upper()
        else:
            raise ValueError(f"unknown key: {key}")
    vk = VK[key] if key in VK else ord(key)
    for m in mods:
        user32.keybd_event(m, 0, 0, 0)
        time.sleep(0.02)
    user32.keybd_event(vk, 0, 0, 0)
    time.sleep(0.03)
    user32.keybd_event(vk, 0, KEYEVENTF_KEYUP, 0)
    for m in reversed(mods):
        user32.keybd_event(m, 0, KEYEVENTF_KEYUP, 0)
    time.sleep(0.04)


# ---- OCR: screenshot -> text + coordinates (in memory, never saved) ----
def _ocr_lines_raw(bbox):
    from PIL import ImageGrab
    import winocr
    img = ImageGrab.grab(bbox=bbox)
    # Windows built-in OCR (Chinese available on this machine). Image is held in
    # memory only and freed here — nothing is written to disk.
    res = winocr.recognize_pil_sync(img, "zh-CN")
    lines = res.get("lines", []) if isinstance(res, dict) else getattr(res, "lines", [])
    out = []
    for ln in lines:
        text = (ln.get("text", "") if isinstance(ln, dict) else ln.text).strip()
        words = ln.get("words", []) if isinstance(ln, dict) else getattr(ln, "words", [])
        if not text or not words:
            continue
        pts = []
        for w in words:
            br = w.get("bounding_rect", {}) if isinstance(w, dict) else getattr(w, "bounding_rect", {})
            x = br.get("x", 0); y = br.get("y", 0)
            wdt = br.get("width", 0); hgt = br.get("height", 0)
            pts.append((x + wdt / 2, y + hgt / 2))
        cx = int(round(sum(p[0] for p in pts) / len(pts) + bbox[0]))
        cy = int(round(sum(p[1] for p in pts) / len(pts) + bbox[1]))
        out.append((text, cx, cy))
    return out


def _default_bbox():
    w, h = screen_size()
    return (0, 0, w, h)


def _norm_region(region):
    if region:
        if len(region) != 4:
            raise ValueError("region must be x,y,w,h")
        return tuple(int(v) for v in region)
    return _default_bbox()


def screenshot_ocr(region=None):
    """Capture the screen (or a region), OCR it, return lines with screen coords.
    The image is never saved to disk — recognized and released in memory."""
    bbox = _norm_region(region)
    lines = _ocr_lines_raw(bbox)
    if not lines:
        return "(screen OCR: no text detected)"
    return "\n".join(f"({cx},{cy}) {text}" for text, cx, cy in lines)


def find_text(text, index=0, region=None):
    """OCR the screen and find a line whose text contains `text`.
    Returns a description with the coordinates, or raises if not found."""
    bbox = _norm_region(region)
    target = (text or "").strip()
    if not target:
        raise ValueError("find_text needs a target string")
    matches = [(t, cx, cy) for (t, cx, cy) in _ocr_lines_raw(bbox)
               if target.lower() in t.lower()]
    if not matches:
        raise ValueError(f"'{text}' not found on screen")
    idx = min(max(index, 0), len(matches) - 1)
    t, cx, cy = matches[idx]
    return f"'{t}' found at ({cx},{cy})"


def click_text(text, index=0, region=None):
    """OCR the screen, find `text`, move the mouse to it and left-click."""
    bbox = _norm_region(region)
    target = (text or "").strip()
    if not target:
        raise ValueError("click_text needs a target string")
    matches = [(t, cx, cy) for (t, cx, cy) in _ocr_lines_raw(bbox)
               if target.lower() in t.lower()]
    if not matches:
        raise ValueError(f"'{text}' not found on screen")
    idx = min(max(index, 0), len(matches) - 1)
    t, cx, cy = matches[idx]
    _mouse_click("left", 1, cx, cy)
    return f"clicked '{t}' at ({cx},{cy})"
