# -*- coding: utf-8 -*-
"""Offline HF-safetensors -> quantized GGUF converter using the `gguf` package.

Outputs models/nai-q8.gguf (Q8_0). Later make_gguf.py quantizes it to Q4_K_M
with llama.cpp's quantize.exe (falling back to this Q8_0 file).
Designed for Qwen2.5-0.5B-Instruct (llama-compatible "qwen2" arch).
"""
from __future__ import annotations

import json
import os
import re

import gguf
import numpy as np
from safetensors import safe_open

ROOT = os.path.dirname(os.path.abspath(__file__))
HF_DIR = os.environ.get("NAI_HF", os.path.join(ROOT, "models", "NAI-finetuned-1.5B"))
OUT = os.environ.get("NAI_GGUF", os.path.join(ROOT, "models", "nai-1.5b.gguf"))
QTYPE = gguf.GGMLQuantizationType.Q4_0

hf_name_map = {
    "model.embed_tokens.weight": "token_embd.weight",
    "model.norm.weight": "output_norm.weight",
    "lm_head.weight": "output.weight",
}


def layer_map(l):
    m = {
        "input_layernorm.weight": f"blk.{l}.attn_norm.weight",
        "post_attention_layernorm.weight": f"blk.{l}.ffn_norm.weight",
        "self_attn.q_proj.weight": f"blk.{l}.attn_q.weight",
        "self_attn.k_proj.weight": f"blk.{l}.attn_k.weight",
        "self_attn.v_proj.weight": f"blk.{l}.attn_v.weight",
        "self_attn.o_proj.weight": f"blk.{l}.attn_output.weight",
        "self_attn.q_proj.bias": f"blk.{l}.attn_q.bias",
        "self_attn.k_proj.bias": f"blk.{l}.attn_k.bias",
        "self_attn.v_proj.bias": f"blk.{l}.attn_v.bias",
        "mlp.gate_proj.weight": f"blk.{l}.ffn_gate.weight",
        "mlp.up_proj.weight": f"blk.{l}.ffn_up.weight",
        "mlp.down_proj.weight": f"blk.{l}.ffn_down.weight",
    }
    return {f"model.layers.{l}.{k}": v for k, v in m.items()}


def build_vocab(tok_path, vocab_size):
    """Build tokens/types/merges + special ids for a Qwen2 tokenizer.json."""
    t = json.load(open(tok_path, encoding="utf-8"))
    model = t["model"]
    vocab = model["vocab"]                      # token -> id (0..len-1)
    merges = [" ".join(p) if isinstance(p, list) else p for p in model["merges"]]
    added = t.get("added_tokens", []) or []     # [{id, content, special,...}]
    base_len = len(vocab)
    n_total = max(vocab_size, base_len + len(added))
    tokens = [""] * n_total
    for tok, idx in vocab.items():
        if 0 <= idx < n_total:
            tokens[idx] = tok
    added_ids = set()
    for a in added:
        i = a["id"]
        if 0 <= i < n_total and a.get("content"):
            if not tokens[i]:
                tokens[i] = a["content"]
            added_ids.add(i)
    # pad unused ids 151665.. with [PADxxxx] tokens (type 5 byte), matching official Qwen GGUF
    for i in range(n_total):
        if not tokens[i]:
            tokens[i] = f"[PAD{i}]"
    # token types: base vocab -> 1 (unknown), added/special -> 3 (user-defined), padding -> 5 (byte)
    types = [3 if i in added_ids else 5 if tokens[i].startswith("[PAD") else 1 for i in range(n_total)]
    # bos/eos/unk/pad ids (Qwen2 style)
    eos_id = None
    pad_id = None
    tc = json.load(open(os.path.join(os.path.dirname(tok_path), "tokenizer_config.json"),
                        encoding="utf-8"))
    id_by_token = {tok: i for i, tok in enumerate(tokens) if tok}
    for name, key in (("eos", "eos_token"), ("pad", "pad_token")):
        s = tc.get(key)
        if s and s in id_by_token:
            if name == "eos":
                eos_id = id_by_token[s]
            else:
                pad_id = id_by_token[s]
    if eos_id is None and "<|im_end|>" in id_by_token:
        eos_id = id_by_token["<|im_end|>"]
    if pad_id is None and "<|endoftext|>" in id_by_token:
        pad_id = id_by_token["<|endoftext|>"]
    bos_id = pad_id
    unk_id = pad_id
    return tokens, types, merges, bos_id, eos_id, unk_id, pad_id


def main():
    cfg = json.load(open(os.path.join(HF_DIR, "config.json"), encoding="utf-8"))
    hidden = cfg["hidden_size"]
    nblocks = cfg["num_hidden_layers"]
    nhead = cfg["num_attention_heads"]
    nkv = cfg.get("num_key_value_heads", nhead)
    head_dim = cfg.get("head_dim", hidden // nhead)
    inter = cfg["intermediate_size"]
    eps = cfg.get("rms_norm_eps", 1e-6)
    rope_theta = float(cfg.get("rope_theta") or 1_000_000.0)
    max_pos = cfg.get("max_position_embeddings", 32768)
    vocab_size = cfg["vocab_size"]

    print("[convert] arch qwen2, hidden", hidden, "layers", nblocks,
          "heads", nhead, "kv", nkv, "inter", inter)

    writer = gguf.GGUFWriter(OUT, arch="qwen2")
    writer.add_name("NAI")
    writer.add_context_length(max_pos)
    writer.add_embedding_length(hidden)
    writer.add_block_count(nblocks)
    writer.add_rope_dimension_count(head_dim)
    writer.add_rope_freq_base(rope_theta)
    writer.add_head_count(nhead)
    writer.add_head_count_kv(nkv)
    writer.add_feed_forward_length(inter)
    writer.add_layer_norm_rms_eps(eps)
    writer.add_vocab_size(vocab_size)
    writer.add_file_type(gguf.LlamaFileType.MOSTLY_Q4_0)
    writer.add_quantization_version(gguf.GGML_QUANT_VERSION)

    # --- vocab ---
    tokens, types, merges, bos_id, eos_id, unk_id, pad_id = build_vocab(
        os.path.join(HF_DIR, "tokenizer.json"), vocab_size)
    writer.add_tokenizer_model("gpt2")
    writer.add_tokenizer_pre("qwen2")
    writer.add_token_list(tokens)
    writer.add_token_types(types)
    writer.add_token_merges(merges)
    writer.add_bos_token_id(bos_id)
    writer.add_eos_token_id(eos_id)
    writer.add_unk_token_id(unk_id)
    writer.add_pad_token_id(pad_id)
    writer.add_add_bos_token(False)
    writer.add_add_eos_token(False)
    print(f"[convert] vocab {len(tokens)} tokens, {len(merges)} merges, "
          f"bos={bos_id} eos={eos_id} pad={pad_id}")

    # --- tensors ---
    names = {**hf_name_map}
    for l in range(nblocks):
        names.update(layer_map(l))
    seen = set()
    with safe_open(os.path.join(HF_DIR, "model.safetensors"), framework="np") as f:
        for hf_name in f.keys():
            gguf_name = names.get(hf_name)
            if gguf_name is None:
                print(f"[convert] WARNING unmapped tensor: {hf_name}")
                continue
            data = np.asarray(f.get_tensor(hf_name), dtype=np.float32)
            if data.ndim == 2:
                q = gguf.quantize(data, QTYPE)
                writer.add_tensor(gguf_name, q, raw_shape=q.shape, raw_dtype=QTYPE)
                if hf_name == "model.embed_tokens.weight":
                    writer.add_tensor("output.weight", q, raw_shape=q.shape, raw_dtype=QTYPE)
            else:
                # norms & attention biases must stay F32 for GGML ops
                writer.add_tensor(gguf_name, data, raw_dtype=gguf.GGMLQuantizationType.F32)
            seen.add(hf_name)
            if hf_name in ("model.embed_tokens.weight", "model.norm.weight"):
                print(f"[convert] {gguf_name} <- {hf_name} {data.shape}")

    missing = [n for n in names if n not in seen]
    if missing:
        print("[convert] WARNING expected but missing:", missing[:10])

    writer.write_header_to_file()
    for shard in writer.kv_data:
        for key, val in shard.items():
            try:
                writer._pack_val(val.value, val.type, add_vtype=True, sub_type=val.sub_type)
            except Exception as e:
                print("SCAN BAD:", key, repr(val.value)[:80], val.type, val.sub_type, "->", e)
    writer.write_kv_data_to_file()
    writer.write_tensors_to_file()
    writer.close()
    print(f"[convert] done -> {OUT} ({os.path.getsize(OUT)/1e6:.0f} MB)")


if __name__ == "__main__":
    main()
