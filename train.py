# -*- coding: utf-8 -*-
"""LoRA fine-tune a tiny bilingual base model (Qwen2.5-0.5B-Instruct) into NAI.
CPU only. Output: models/NAI-finetuned (merged, fp16).

Usage (from project root, venv python):
    python train.py
"""
from __future__ import annotations

import json
import os
import random
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))
os.environ.setdefault("HF_HOME", os.path.join(ROOT, ".cache", "hf"))
os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")
os.environ["TOKENIZERS_PARALLELISM"] = "false"

import torch  # noqa: E402
from torch.nn.utils.rnn import pad_sequence  # noqa: E402
from transformers import (  # noqa: E402
    AutoModelForCausalLM,
    AutoTokenizer,
    Trainer,
    TrainingArguments,
)
from peft import LoraConfig, get_peft_model, PeftModel  # noqa: E402

BASE = os.environ.get("NAI_BASE", "Qwen/Qwen2.5-1.5B-Instruct")
DATA = os.path.join(ROOT, "dataset", "data", "naifinetune.jsonl")
OUT_DIR = os.path.join(ROOT, "models", "NAI-finetuned-1.5B")
ADAPTER_DIR = os.path.join(ROOT, "models", "NAI-lora-1.5B")
MAX_SEQ = 256
BATCH = 2
GRAD_ACC = 2
MAX_STEPS = int(os.environ.get("NAI_STEPS", "100"))
LR = 2e-4


def load_data(path):
    samples = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            obj = json.loads(line)
            samples.append(obj["messages"])
    return samples


def tokenize(tokenizer, conversations, max_seq):
    encs = []
    for conv in conversations:
        text = tokenizer.apply_chat_template(
            conv, tokenize=False, add_generation_prompt=False
        )
        ids = tokenizer(text, add_special_tokens=False, truncation=True,
                        max_length=max_seq).input_ids
        encs.append(ids)
    return encs


class CompletionCollator:
    """Pads a batch and masks all tokens except the assistant turns in labels."""

    def __init__(self, tokenizer, response_template="<|im_start|>assistant"):
        self.tokenizer = tokenizer
        self.rt = tokenizer(response_template, add_special_tokens=False).input_ids

    def __call__(self, features):
        ids = [torch.tensor(f["input_ids"], dtype=torch.long) for f in features]
        attn = [torch.tensor(f["attention_mask"], dtype=torch.long) for f in features]
        ids_p = pad_sequence(ids, batch_first=True, padding_value=self.tokenizer.pad_token_id)
        attn_p = pad_sequence(attn, batch_first=True, padding_value=0)
        labels = ids_p.clone()
        labels[labels == self.tokenizer.pad_token_id] = -100
        rtl = len(self.rt)
        for i, orig in enumerate(ids):
            n = len(orig)
            pos = -1
            for j in range(n - rtl, -1, -1):
                if orig[j:j + rtl].tolist() == self.rt:
                    pos = j
                    break
            if pos >= 0:
                labels[i, :pos] = -100
        return {"input_ids": ids_p, "attention_mask": attn_p, "labels": labels}


def main():
    random.seed(42)
    torch.manual_seed(42)

    print(f"[train] loading base model {BASE} (CPU, fp32) ...")
    tokenizer = AutoTokenizer.from_pretrained(BASE, trust_remote_code=True)
    if tokenizer.pad_token is None:
        tokenizer.pad_token = tokenizer.eos_token
    model = AutoModelForCausalLM.from_pretrained(
        BASE, dtype=torch.float32, device_map=None,
        trust_remote_code=True,
    )

    conversations = load_data(DATA)
    random.shuffle(conversations)
    split = int(len(conversations) * 0.95)
    train_conv = conversations[:split]
    eval_conv = conversations[split:]

    def to_dataset(conv_list):
        encs = tokenize(tokenizer, conv_list, MAX_SEQ)
        # wrap into dicts for HF
        return [{"input_ids": ids, "attention_mask": [1] * len(ids)} for ids in encs]

    train_ds = to_dataset(train_conv)
    eval_ds = to_dataset(eval_conv)
    print(f"[train] train={len(train_ds)} eval={len(eval_ds)}")

    lora = LoraConfig(
        r=16, lora_alpha=32, lora_dropout=0.05, bias="none",
        target_modules=["q_proj", "k_proj", "v_proj", "o_proj",
                        "gate_proj", "up_proj", "down_proj"],
        task_type="CAUSAL_LM",
    )
    model = get_peft_model(model, lora)
    model.print_trainable_parameters()

    collator = CompletionCollator(tokenizer)

    args = TrainingArguments(
        output_dir=os.path.join(ROOT, "models", "train_out"),
        per_device_train_batch_size=BATCH,
        gradient_accumulation_steps=GRAD_ACC,
        max_steps=MAX_STEPS,
        learning_rate=LR,
        lr_scheduler_type="cosine",
        warmup_steps=6,
        logging_steps=10,
        save_strategy="no",
        eval_strategy="steps",
        eval_steps=24,
        dataloader_pin_memory=False,
        remove_unused_columns=False,
        fp16=False,
        bf16=False,
        report_to=[],
        seed=42,
    )
    trainer = Trainer(
        model=model,
        args=args,
        train_dataset=train_ds,
        eval_dataset=eval_ds,
        data_collator=collator,
    )
    trainer.train()

    os.makedirs(ADAPTER_DIR, exist_ok=True)
    model.save_pretrained(ADAPTER_DIR)
    tokenizer.save_pretrained(ADAPTER_DIR)

    # quick generation sanity before merge
    model.eval()
    with torch.no_grad():
        base = model.merge_and_unload()
    base = base.half()
    os.makedirs(OUT_DIR, exist_ok=True)
    base.save_pretrained(OUT_DIR, safe_serialization=True)
    tokenizer.save_pretrained(OUT_DIR)
    print(f"[train] merged model saved to {OUT_DIR}")


if __name__ == "__main__":
    main()
