# -*- coding: utf-8 -*-
"""NAI batch operations — read / write / search many items in parallel
(multi-threaded + asyncio), and read very large projects in chunks.

Why threads + async: file I/O and network I/O are what "batch" spends time on,
and those are perfectly parallel. The shared local GGUF model is single-threaded
and stays serialized (see worker.NaiModel._lock), so LLM *generation* does not
parallelize — but reading hundreds of files or searching many queries at once
does. That is the honest win this module delivers.

Public helpers (used by SafeTools methods):
  batch_read_files(tools, paths, budget)
  batch_write_files(tools, payload)
  batch_search_queries(queries, n)
  read_big_project(tools, path, max_files, include, budget)
"""
from __future__ import annotations

import asyncio
import concurrent.futures
import json
import os

from .tools import SafeTools, ToolError

DEFAULT_BUDGET = 24000
MAX_WORKERS = 12
MAX_QUERY = 10


# ---------- helpers to parse a list from model args (JSON array | newline | comma) ----------
def parse_list(raw: str):
    raw = (raw or "").strip()
    if not raw:
        return []
    if raw.startswith("["):
        try:
            v = json.loads(raw)
            return [str(x) for x in v] if isinstance(v, list) else []
        except Exception:
            pass
    items = [x.strip() for x in re_split(raw)]
    return [x for x in items if x]


def re_split(raw: str):
    import re
    if "\n" in raw:
        return raw.splitlines()
    return re.split(r"\s*,\s*|\s*\|\s*", raw)


# ---------- asyncio version (async I/O) ----------
async def _gather(coros, limit=None):
    if limit:
        sem = asyncio.Semaphore(limit)
        async def _wrap(c):
            async with sem:
                return await c
        coros = [_wrap(c) for c in coros]
    return await asyncio.gather(*coros, return_exceptions=True)


def run_async(coro):
    try:
        return asyncio.run(coro)
    except RuntimeError:
        loop = asyncio.new_event_loop()
        try:
            return loop.run_until_complete(coro)
        finally:
            loop.close()


# ---------- batch read ----------
def batch_read_files(tools: SafeTools, paths, budget: int = DEFAULT_BUDGET):
    paths = parse_list(paths) if isinstance(paths, str) else list(paths)
    if not paths:
        raise ToolError("batch_read needs a list of file paths")

    def one(p):
        try:
            return ("ok", p, tools.read_file(p))
        except ToolError as e:
            return ("error", p, str(e))

    with concurrent.futures.ThreadPoolExecutor(
            max_workers=min(MAX_WORKERS, len(paths))) as ex:
        futs = [ex.submit(one, p) for p in paths]
        results = [f.result() for f in futs]

    parts = []
    total = 0
    errors = 0
    for st, p, r in results:
        if st != "ok":
            errors += 1
        block = f"===== {p} =====\n{r}"
        total += len(block)
        if total > budget and parts:
            parts.append(block[:max(0, budget - sum(len(x) for x in parts))] +
                         "\n...(batch_read budget hit; read the rest with read_file)")
            break
        parts.append(block)
    head = f"batch_read: {len(results)} files, {errors} errors"
    return head + "\n\n" + "\n".join(parts)


# ---------- batch write (many files at once) ----------
def batch_write_files(tools: SafeTools, payload: str):
    # payload: JSON object {"path": "content", ...}  (paths resolved inside sandbox)
    try:
        data = json.loads(payload)
        if not isinstance(data, dict):
            raise ValueError("not an object")
    except Exception as e:
        raise ToolError(f"batch_write needs a JSON object of {{path: content}}: {e}")
    items = list(data.items())
    if not items:
        raise ToolError("batch_write got an empty object")

    def one(kv):
        path, content = kv
        try:
            return ("ok", path, tools.write_file(str(path), str(content)))
        except ToolError as e:
            return ("error", path, str(e))

    with concurrent.futures.ThreadPoolExecutor(
            max_workers=min(MAX_WORKERS, len(items))) as ex:
        futs = [ex.submit(one, kv) for kv in items]
        results = [f.result() for f in futs]
    rows = []
    for st, path, r in results:
        rows.append(f"[{st.upper()}] {path}: {r}")
    return "batch_write:\n" + "\n".join(rows)


# ---------- batch search (parallel web queries) ----------
def batch_search_queries(queries, n: int = 5):
    queries = parse_list(queries) if isinstance(queries, str) else list(queries)
    queries = queries[:MAX_QUERY]
    if not queries:
        raise ToolError("batch_search needs a list of queries")
    from . import webutil

    def one(q):
        try:
            return ("ok", q, webutil.web_search(q, str(n)))
        except ToolError as e:
            return ("error", q, str(e))

    with concurrent.futures.ThreadPoolExecutor(
            max_workers=min(MAX_WORKERS, len(queries))) as ex:
        futs = [ex.submit(one, q) for q in queries]
        results = [f.result() for f in futs]
    blocks = []
    for st, q, r in results:
        blocks.append(f"##### query: {q} #####\n{r}")
    return "\n\n".join(blocks)


# ---------- read a very large project (parallel walk + chunked budget) ----------
def _text_files(root: str, limit: int):
    files = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if not d.startswith(".")]
        for fn in filenames:
            if len(files) >= limit:
                break
            p = os.path.join(dirpath, fn)
            ext = os.path.splitext(fn)[1].lower()
            if ext in SafeTools.TEXT_EXTS:
                files.append(p)
        if len(files) >= limit:
            break
    return files


def read_big_project(tools: SafeTools, path: str, max_files: str = "30",
                     include: str = "yes", budget: str = str(DEFAULT_BUDGET)):
    """Parallel read of up to N text files of a (possibly huge) project.

    Returns: a manifest of ALL text files (paths, size, line count) + the
    contents of the first batch of files up to `budget` chars. If the project
    has more files than fit the budget, it returns the manifest and tells the
    model which specific files to read next with read_file / batch_read — so a
    huge project is read across steps instead of overflowing context.
    """
    p = tools.resolve(path)
    if not os.path.isdir(p):
        raise ToolError(f"folder not found: {path}")
    try:
        mf = int(max_files)
    except (TypeError, ValueError):
        mf = 30
    mf = min(max(mf, 1), 300)
    try:
        bb = int(budget)
    except (TypeError, ValueError):
        bb = DEFAULT_BUDGET
    bb = min(max(bb, 2000), 60000)
    show = str(include).strip().lower() in ("yes", "true", "1", "content", "内容")

    files = _text_files(p, mf)
    if not files:
        return f"(no text/code files found under {p})"

    # manifest: all text files with size + line count (parallel stat)
    def stat_one(f):
        try:
            sz = os.path.getsize(f)
            with open(f, "r", encoding="utf-8", errors="replace") as fh:
                nlines = sum(1 for _ in fh)
            return (f, sz, nlines)
        except OSError:
            return (f, -1, -1)

    with concurrent.futures.ThreadPoolExecutor(
            max_workers=min(MAX_WORKERS, len(files))) as ex:
        manifest = [x.result() for x in [ex.submit(stat_one, f) for f in files]]

    manifest_lines = [f"project: {p} — {len(files)} text files (manifest of the first {mf})"]
    for f, sz, nl in manifest:
        manifest_lines.append(f"  {f}  ({sz} B, {nl} lines)")

    if not show:
        return "\n".join(manifest_lines)

    # read contents in parallel until budget
    def read_one(f):
        try:
            if os.path.getsize(f) > 200 * 1024:
                return ("skip", f, f"(>200KB, skip; use head/read_file)")
            data = open(f, "r", encoding="utf-8", errors="replace").read()
            return ("ok", f, data)
        except OSError as e:
            return ("error", f, str(e))

    contents = []
    total = 0
    with concurrent.futures.ThreadPoolExecutor(
            max_workers=min(MAX_WORKERS, len(files))) as ex:
        futs = [ex.submit(read_one, f) for f in files]
        for fut in futs:
            st, f, data = fut.result()
            if st == "ok" and data:
                block = f"===== {f} =====\n{data}"
                if total + len(block) > bb and contents:
                    break
                total += len(block)
                contents.append(block)
            elif st == "error":
                contents.append(f"===== {f} =====\n(error: {data})")

    out = "\n".join(manifest_lines)
    if contents:
        out += "\n\n--- contents ---\n" + "\n".join(contents)
    remaining = len(files) - len(contents)
    if remaining > 0:
        out += (f"\n...(budget reached: {len(contents)} files shown, {remaining} more "
                f"text files in manifest above). Read them with read_file/batch_read "
                f"using the manifest paths.")
    return out
