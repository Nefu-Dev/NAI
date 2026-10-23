# -*- coding: utf-8 -*-
"""Headless self-test: load the GGUF, run bilingual chat + a file tool turn,
then write selftest_result.json (used to verify NAI.exe without a GUI)."""
from __future__ import annotations

import json
import os
import sys
import time
import traceback

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def resolve_model():
    from nai.paths import resolve_model_path
    return resolve_model_path()


def run():
    result = {"ok": False, "steps": []}
    try:
        from nai.worker import NaiModel
        from nai.agent import NaiAgent

        model_path = resolve_model()
        result["model"] = model_path
        import psutil
        base_rss = psutil.Process().memory_info().rss / 1e6

        model = NaiModel(model_path, n_ctx=None)
        agent = NaiAgent(model, workspace=ROOT, autoshell=False)
        info = model.info()
        result["info"] = info

        def step(name, prompt, max_tokens=200):
            events = []
            t0 = time.time()
            agent.run_turn(prompt, sink=lambda kind, **kw: events.append((kind, kw)))
            dt = time.time() - t0
            tokens = sum(1 for k, _ in events if k == "token")
            tools = [e for e in events if e[0] == "tool"]
            result["steps"].append({
                "name": name, "prompt": prompt,
                "tokens": tokens, "seconds": round(dt, 2),
                "tok_s": round(tokens / max(dt, 1e-6), 1),
                "tool_calls": [(e[1].get("name"), e[1].get("args")) for e in tools],
            })
            return tokens

        step("zh_greet", "你好，简单介绍一下你自己", max_tokens=160)
        step("en_hello", "hello, what can you do?", max_tokens=160)
        # persistent rules
        try:
            agent.clear_rules()
            agent.add_rule("回答尽量简短")
            got = agent.get_rules()
            result["rules_ok"] = "简短" in "".join(got)
            agent.clear_rules()
        except Exception as e:
            result["rules_ok"] = False
            result["rules_err"] = str(e)
        # read_project (whole-project reader) works inside the EXE
        try:
            rp = agent.tools.execute("read_project", [os.path.join(ROOT, "nai"), "no"])
            result["read_project_ok"] = "project:" in str(rp) and "read_project" in rp.lower() or "tools" in str(rp).lower()
            result["read_project_sample"] = str(rp)[:160]
        except Exception as e:
            result["read_project_ok"] = False
            result["read_project_err"] = str(e)
        # utility tools smoke
        try:
            result["util_ok"] = (str(agent.tools.execute("json_pretty", ['{"a":1}'])) == '{\n  "a": 1\n}' and
                                 len(str(agent.tools.execute("random_uuid", []))) == 36)
        except Exception as e:
            result["util_ok"] = False
            result["util_err"] = str(e)
        # MCP registry (no servers configured by default -> graceful)
        try:
            result["mcp_list"] = str(agent.tools.execute("mcp_list", []))[:120]
            result["mcp_ok"] = True
        except Exception as e:
            result["mcp_ok"] = False
            result["mcp_err"] = str(e)
        # file tool roundtrip
        agent.add_root(ROOT)
        agent.tools.autoshell = True
        step("tool_write", "帮我写一个文件 demo.txt，内容是 hello nai", max_tokens=120)
        # supervisor: screenshot OCR (read-only) inside the EXE
        try:
            agent.tools.supervisor_enabled = True
            ocr_out = agent.tools.execute("screenshot", [])
            result["supervisor_ocr"] = str(ocr_out)[:300]
            result["supervisor_ocr_ok"] = True
        except Exception as e:
            result["supervisor_ocr_ok"] = False
            result["supervisor_ocr_err"] = str(e)
        # YOLO object detection on the live screen (in memory)
        try:
            yolo_out = agent.tools.execute("detect_image", ["screen"])
            result["yolo_detect"] = str(yolo_out)[:300]
            result["yolo_ok"] = True
        except Exception as e:
            result["yolo_ok"] = False
            result["yolo_err"] = str(e)
        # ---- new modules: isolation / batch / self-heal / autostart / sub-agent ----
        # isolation mode switch (persisted)
        try:
            m, _label = agent.set_isolation("partial")
            m2, _l2 = agent.get_isolation()
            result["isolation_switch_ok"] = (m == "partial" and m2 == "partial")
            agent.set_isolation("full")
            result["isolation_full"] = agent.get_isolation()[0] == "full"
        except Exception as e:
            result["isolation_switch_ok"] = False
            result["isolation_err"] = str(e)
        # batch read + write (parallel, no model needed)
        try:
            agent.tools.isolation.mode = "none"
            agent.tools.sandbox_enabled = False
            from nai import batch
            wr = batch.batch_write_files(agent.tools,
                                         '{"_selftest_a.txt":"one","_selftest_b.txt":"two"}')
            rd = batch.batch_read_files(agent.tools, ["_selftest_a.txt", "_selftest_b.txt"])
            result["batch_ok"] = ("[OK] _selftest_a.txt" in wr and "one" in rd and "two" in rd)
            agent.set_isolation("full")
        except Exception as e:
            result["batch_ok"] = False
            result["batch_err"] = str(e)
        # self-heal hint logic (pure)
        try:
            from nai.selfheal import SelfHeal
            h = SelfHeal(max_consecutive=2)
            _g, hint1 = h.hint("read_file", ["x"], "file not found")
            _g, hint2 = h.hint("read_file", ["x"], "file not found")
            result["selfheal_ok"] = ("not exist" in hint1.lower() or "STOP" in hint2)
        except Exception as e:
            result["selfheal_ok"] = False
            result["selfheal_err"] = str(e)
        # autostart status (read-only, must not crash)
        try:
            from nai import autostart as AS
            result["autostart_status"] = AS.status()
            result["autostart_ok"] = result["autostart_status"].startswith("autostart:")
        except Exception as e:
            result["autostart_ok"] = False
            result["autostart_err"] = str(e)
        # sub-agent: one small subtask (bounded; real model call, serialized by lock)
        try:
            from nai import subagent as SA
            sa_res = SA.spawn_subagents(model, ["一句话：你好"], ROOT,
                                        max_workers=1, max_tokens=60)
            result["subagent_ok"] = sa_res and sa_res[0].get("ok") is True
            result["subagent_sample"] = (sa_res[0].get("text") or "")[:80]
        except Exception as e:
            result["subagent_ok"] = False
            result["subagent_err"] = str(e)
        rss = psutil.Process().memory_info().rss / 1e6
        result["rss_mb"] = round(rss, 1)
        result["rss_delta_mb"] = round(rss - base_rss, 1)
        result["ok"] = True
    except Exception:
        result["error"] = traceback.format_exc()
    out = os.path.join(os.getcwd(), "selftest_result.json")
    with open(out, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    print("selftest result ->", out)
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    sys.exit(run())
