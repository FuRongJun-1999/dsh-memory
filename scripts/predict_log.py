# -*- coding: utf-8 -*-
"""预测台账：把「我预判会怎样」写成事前可验的一条，事后对照，暴露信息差。

# 功能名：predict_log —— 事前预测 / 事后对照 / 命中率统计
# 生效条件：开始一件有可观察结果的事之前；或想暴露「我在哪类事上其实在猜」时
# 子功能：
#   ① pre()   事前写一条：判断 + 推论 + 判据（判据必须在结果出现前写死）
#   ② post()  事后对照：填实际结果，判命中与否
#   ③ stats() 命中率 + 最近一次未命中（未命中的指向 unresolved）
# 执行：python -X utf8 scripts/predict_log.py --pre/--post/--stats
#       台账落 <库根>/_predict.jsonl（单行 JSON，只追加不覆写）
# 验证方式：md_cg/test_predict_log.py（事前事后配对、缺判据拒写、命中率口径）
# 不适用条件：结果不可观察的事不写（写了也无法对照）；命中率低不等于能力差，
#             只说明该类事上信息差大

设计约束（2026-11-20 使用者与 agent 议定）：
  · 判据必须事前给定 —— 事后才补判据等于自证
  · 未命中不惩罚，但必须记一次 —— 宁可多记错，不可少预测
  · 只存最近 N 条 —— 它是当下的校准度，不是历史档案馆
"""
import argparse
import io
import json
import os
import sys
import time

LOG_NAME = "_predict.jsonl"
KEEP = 200


def _root(explicit=None):
    if explicit:
        return explicit
    try:
        from md_cg.datapath import mdcg_root
        return mdcg_root()
    except Exception:  # noqa: BLE001
        return os.environ.get("MDCG_ROOT") or "."


def _path(root):
    return os.path.join(root, LOG_NAME)


def read_all(root, limit=None):
    out = []
    try:
        with io.open(_path(root), encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    out.append(json.loads(line))
                except Exception:  # noqa: BLE001
                    continue
    except OSError:
        return []
    return out[-limit:] if limit else out


def pre(root, judgment, prediction, criterion, *, actor="dsh端"):
    if not (judgment or "").strip() or not (prediction or "").strip() or not (criterion or "").strip():
        raise ValueError("judgment / prediction / criterion 三者缺一不可——判据必须事前写死")
    rec = {"kind": "pre", "t": time.time(), "actor": actor,
           "judgment": judgment.strip(), "prediction": prediction.strip(),
           "criterion": criterion.strip(), "pid": ""}
    _append(root, rec)
    return rec


def post(root, pid, actual, hit, *, note=""):
    rec = {"kind": "post", "t": time.time(), "pid": pid,
           "actual": (actual or "").strip(), "hit": bool(hit), "note": (note or "").strip()}
    _append(root, rec)
    return rec


def _append(root, rec):
    path = _path(root)
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with io.open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    rows = read_all(root, limit=KEEP)
    with io.open(path, "w", encoding="utf-8", newline="\n") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")


def stats(root):
    rows = read_all(root)
    posts = [r for r in rows if r.get("kind") == "post"]
    hit = sum(1 for r in posts if r.get("hit"))
    last_miss = next((r for r in reversed(posts) if not r.get("hit")), None)
    return {"n": len(posts), "hit": hit,
            "rate": round(hit / float(len(posts)), 4) if posts else None,
            "last_miss": last_miss}


def cli(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=None)
    ap.add_argument("--pre", action="store_true")
    ap.add_argument("--post", action="store_true")
    ap.add_argument("--stats", action="store_true")
    ap.add_argument("--judgment", default="")
    ap.add_argument("--prediction", default="")
    ap.add_argument("--criterion", default="")
    ap.add_argument("--pid", default="")
    ap.add_argument("--actual", default="")
    ap.add_argument("--hit", default="")
    ap.add_argument("--note", default="")
    a = ap.parse_args(argv)
    root = _root(a.root)
    if a.pre:
        print(json.dumps(pre(root, a.judgment, a.prediction, a.criterion), ensure_ascii=False))
    elif a.post:
        h = str(a.hit).lower() in ("1", "true", "yes", "y")
        print(json.dumps(post(root, a.pid, a.actual, h, note=a.note), ensure_ascii=False))
    else:
        print(json.dumps(stats(root), ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(cli())
