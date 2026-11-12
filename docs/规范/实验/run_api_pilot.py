# -*- coding: utf-8 -*-
"""提示词对比实验 · 模型层直调 pilot（WorkBuddy 同款 GLM-5.3-Flash）。

为什么有这条通道：WorkBuddy GUI 被另一条并发实验线占用，GUI 输入会互相污染；
CLI 独立启动需要账户登录。这里用 ~/.codebuddy/models.json 里的同款自定义模型键
直调 OpenAI 兼容端点，作为受控 pilot，并在报告中明确标注「非 WorkBuddy 界面」。

运行：
  python docs/规范/实验/run_api_pilot.py --out .tmp/workbuddy_exp/api_runs
"""
from __future__ import annotations

import argparse
import json
import os
import time
import urllib.error
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
TASKSET = HERE / "任务集_v1.0.json"
MODELS = Path.home() / ".codebuddy" / "models.json"
MODEL_ID = "glm-5.3-flash"
SYSTEM = "你是一名严谨的工程助手。请只做文字回答，不要修改或删除任何本地文件。"


def get_model() -> dict:
    data = json.loads(MODELS.read_text(encoding="utf-8"))
    for m in data.get("models") or []:
        if m.get("id") == MODEL_ID:
            return m
    raise SystemExit(f"model {MODEL_ID} not found in {MODELS}")


def call_once(model: dict, system: str, user: str, max_tokens: int = 4096) -> dict:
    body = json.dumps(
        {
            "model": model["id"],
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "stream": False,
            "max_tokens": max_tokens,
        },
        ensure_ascii=False,
    ).encode("utf-8")
    req = urllib.request.Request(
        model["url"].rstrip("/") + "/chat/completions",
        data=body,
        headers={
            "Content-Type": "application/json",
            "Authorization": "Bearer " + model["apiKey"],
        },
    )
    t0 = time.time()
    with urllib.request.urlopen(req, timeout=180) as r:
        raw = r.read().decode("utf-8")
    latency = time.time() - t0
    data = json.loads(raw)
    ch = (data.get("choices") or [{}])[0]
    msg = ch.get("message") or {}
    return {
        "content": msg.get("content") or "",
        "reasoning": msg.get("reasoning_content") or "",
        "finish_reason": ch.get("finish_reason"),
        "usage": data.get("usage") or {},
        "latency_s": round(latency, 2),
        "request_id": data.get("request_id"),
        "raw_model": data.get("model"),
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=".tmp/workbuddy_exp/api_runs")
    ap.add_argument("--taskset", default=str(TASKSET))
    ap.add_argument("--only", default=None, help="逗号分隔的任务 id，如 T6")
    ap.add_argument("--max-tokens", type=int, default=4096)
    ap.add_argument("--sleep", type=float, default=1.0)
    args = ap.parse_args()

    cfg = json.loads(Path(args.taskset).read_text(encoding="utf-8"))
    tasks = {t["id"]: t for t in cfg["tasks"]}
    if args.only:
        keep = {x.strip() for x in args.only.split(",") if x.strip()}
        tasks = {k: v for k, v in tasks.items() if k in keep}
    arms = cfg["arms"]
    model = get_model()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    # 分层轮换顺序：同一任务的三个臂相邻，臂内顺序按任务轮换，减少时间漂移
    orders = [
        ["ZH_THINK", "EN_THINK", "DEFAULT"],
        ["EN_THINK", "DEFAULT", "ZH_THINK"],
        ["DEFAULT", "ZH_THINK", "EN_THINK"],
        ["ZH_THINK", "DEFAULT", "EN_THINK"],
        ["EN_THINK", "ZH_THINK", "DEFAULT"],
    ]
    manifest = []
    for i, (tid, task) in enumerate(tasks.items()):
        for arm in orders[i % len(orders)]:
            user = task["prompt"] + arms[arm]["suffix"]
            rec = {
                "task": tid,
                "arm": arm,
                "model": model["id"],
                "system": SYSTEM,
                "user": user,
                "timestamp": int(time.time() * 1000),
            }
            err = None
            for attempt in range(1, 3):
                try:
                    rec.update(call_once(model, SYSTEM, user, args.max_tokens))
                    break
                except urllib.error.HTTPError as e:
                    err = f"HTTP {e.code}: {e.read().decode('utf-8', 'replace')[:500]}"
                except Exception as e:
                    err = f"{type(e).__name__}: {str(e)[:500]}"
                if attempt == 1:
                    time.sleep(5)
            if "content" not in rec:
                rec["error"] = err
            fp = out / f"{tid}_{arm}.json"
            fp.write_text(json.dumps(rec, ensure_ascii=False, indent=1), encoding="utf-8")
            manifest.append(
                {
                    "task": tid,
                    "arm": arm,
                    "file": str(fp),
                    "ok": "content" in rec,
                    "latency_s": rec.get("latency_s"),
                    "tokens": (rec.get("usage") or {}).get("completion_tokens"),
                }
            )
            print(
                f"{tid} {arm:10} ok={'content' in rec} "
                f"lat={rec.get('latency_s')} "
                f"reasoning={(rec.get('reasoning') or '')[:60]!r}",
                flush=True,
            )
            time.sleep(args.sleep)
    (out / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    print(f"# wrote {len(manifest)} runs -> {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
