# -*- coding: utf-8 -*-
"""NAI inference engine over llama.cpp (GGUF). Streaming token generation + stats."""
from __future__ import annotations

import os
import threading
import time

from . import prompt as P


def default_threads():
    try:
        return max(2, os.cpu_count() - 2)
    except Exception:
        return 4


class NaiModel:
    def __init__(self, model_path: str, n_ctx: int = None, n_threads: int = None,
                 n_batch: int = 256, seed: int = -1):
        import llama_cpp
        # context window: default 16384, override with env NAI_CTX (e.g. 8192/12288/16384)
        if not n_ctx:
            try:
                n_ctx = int(os.environ.get("NAI_CTX", "16384"))
            except (TypeError, ValueError):
                n_ctx = 16384
        self.n_ctx = n_ctx
        # Generation lock: the single llama.cpp context is NOT thread-safe. The
        # main agent and any sub-agents share this model, so every generate()
        # call serializes here — real parallelism happens in I/O (batch tools).
        self._lock = threading.Lock()
        self._llm = llama_cpp.Llama(
            model_path=model_path,
            n_ctx=n_ctx,
            n_threads=n_threads if n_threads else default_threads(),
            n_batch=n_batch,
            use_mmap=True,
            use_mlock=False,
            verbose=False,
            seed=seed,
            logits_all=True,
        )
        self.model_path = model_path
        self.started = time.time()

    def info(self):
        m = self._llm

        def _g(name, default=None):
            v = getattr(m, name, default)
            if callable(v):
                try:
                    v = v()
                except Exception:
                    v = default
            return v

        return {
            "n_ctx": _g("n_ctx", self.n_ctx),
            "n_threads": _g("n_threads"),
            "n_embd": _g("n_embd"),
            "n_vocab": _g("n_vocab"),
            "model_size": os.path.getsize(self.model_path) / 1e6,
        }

    def generate(self, messages, max_tokens=512, temperature=0.7, top_p=0.9,
                 repeat_penalty=1.05, stream_cb=None):
        """Stream a completion for a message list. Returns (text, stats)."""
        with self._lock:
            return self._generate_locked(
                messages, max_tokens, temperature, top_p, repeat_penalty, stream_cb)

    def _generate_locked(self, messages, max_tokens, temperature, top_p,
                         repeat_penalty, stream_cb):
        prompt = P.build_prompt(messages)
        t0 = time.time()
        n_tokens = 0
        buf = []
        for chunk in self._llm.create_completion(
                prompt,
                max_tokens=max_tokens,
                temperature=temperature,
                top_p=top_p,
                repeat_penalty=repeat_penalty,
                stop=P.STOP,
                stream=True,
                echo=False,
        ):
            delta = chunk["choices"][0].get("text", "")
            if delta:
                buf.append(delta)
                n_tokens += 1
                if stream_cb:
                    stream_cb(delta)
        text = "".join(buf).strip()
        # strip a trailing im_end token if the model emitted it
        if text.endswith("<|im_end|>"):
            text = text[: -len("<|im_end|>")].rstrip()
        elapsed = max(time.time() - t0, 1e-6)
        try:
            timings = self._llm.get_timings()
            per_s = getattr(timings, "predicted_per_second", n_tokens / elapsed)
        except Exception:
            per_s = n_tokens / elapsed
        stats = {
            "tokens": n_tokens,
            "seconds": round(elapsed, 2),
            "tok_s": round(per_s, 1),
            "ctx_prompt": len(self._llm.tokenize(prompt.encode("utf-8"), add_bos=False)),
        }
        return text, stats
