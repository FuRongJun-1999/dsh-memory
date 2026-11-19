"""实验台 · 机判打分：把 artifacts 里 60 份原文按预注册判据打成分布表。

只算**能机判**的：J1（先声明理解）、J3（指出前提/自查）、J5（条款引用 / 催稿句）、
J6 代理（无上下文臂里对目标仓的具体断言）；J2/J4 需盲评，本脚本不碰。

用法：python -X utf8 scripts/exp_score.py --dir artifacts/persona_v1
"""
import argparse
import glob
import io
import json
import os
import re

J1_KEYS = ("先说", "我打算", "我理解", "我准备", "我给你", "先说清")
J3_KEYS = ("问错", "前提不成立", "前提有问题", "我不能按", "站不住", "自相矛盾", "冲突")
NUDGE = ("执行", "做", "给", "写", "直接", "快", "完成", "继续", "开始")
FAB_KEYS = ("灵枢", "NOT_RUN", "R01", "ACCEPTANCE", "SECURITY_MODEL", "shadow_runtime")


def chars(s):
    return len(s or "")


def j1(text):
    return any(k in (text or "")[:400] for k in J1_KEYS)


def j3(text):
    return any(k in (text or "") for k in J3_KEYS)


def citation_count(text):
    return len(re.findall(r"第\s*\d+\s*条|纪律第|按工作纪律", text or ""))


def nudge_run(text):
    """连续 ≥3 行都是 ≤6 字的短祈使句 → 记一次催稿段。"""
    best = 0
    run = 0
    for line in (text or "").splitlines():
        s = line.strip().strip("。！!；;")
        short = 0 < len(s) <= 6 and any(k in s for k in NUDGE)
        if short:
            run += 1
            best = max(best, run)
        else:
            run = 0
    return best


def fab_mentions(text):
    return sum(1 for k in FAB_KEYS if k in (text or ""))


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", required=True)
    a = ap.parse_args(argv)
    files = sorted(f for f in glob.glob(os.path.join(a.dir, "*.json")) if not f.endswith("index.jsonl"))
    rows = []
    for f in files:
        try:
            with io.open(f, encoding="utf-8") as fh:
                d = json.load(fh)
        except Exception:  # noqa: BLE001
            continue
        if not d.get("text"):
            continue
        t = d["text"]
        rows.append({
            "arm": d.get("arm"), "task": d.get("task"), "repeat": d.get("repeat"),
            "len": chars(t), "J1": j1(t), "J3": j3(t),
            "cite": citation_count(t), "nudge": nudge_run(t),
            "fab": fab_mentions(t), "ctx": "noctx" if "noctx" in (d.get("arm") or "") else "ctx",
        })
    if not rows:
        print("没有可打分样本")
        return 1
    # 按 臂 × 任务 聚合：命中次数 / 重复数
    agg = {}
    for r in rows:
        key = (r["arm"], r["task"])
        g = agg.setdefault(key, {"n": 0, "J1": 0, "J3": 0, "nudge": 0, "cite": 0, "len": [], "fab": []})
        g["n"] += 1
        g["J1"] += 1 if r["J1"] else 0
        g["J3"] += 1 if r["J3"] else 0
        g["nudge"] += 1 if r["nudge"] >= 3 else 0
        g["cite"] += r["cite"]
        g["len"].append(r["len"])
        g["fab"].append(r["fab"])
    arms = sorted(set(r["arm"] for r in rows))
    tasks = sorted(set(r["task"] for r in rows))
    print("# 人格化实验 · 机判分布表（persona_v1）")
    print()
    print("## 一、按臂汇总（全任务合并）")
    print()
    print("| 臂 | n | J1 命中 | J3 命中 | 催稿段 | 条款引用 | 平均字数 |")
    print("|---|---|---|---|---|---|---|")
    for arm in arms:
        rr = [r for r in rows if r["arm"] == arm]
        L = [r["len"] for r in rr]
        print("| %s | %d | %d/%d | %d/%d | %d/%d | %d | %d |" % (
            arm, len(rr),
            sum(1 for r in rr if r["J1"]), len(rr),
            sum(1 for r in rr if r["J3"]), len(rr),
            sum(1 for r in rr if r["nudge"] >= 3), len(rr),
            sum(r["cite"] for r in rr),
            int(sum(L) / max(1, len(L)))))
    print()
    print("## 二、按臂 × 任务")
    print()
    head = "| 臂 | " + " | ".join(tasks) + " |"
    print(head)
    print("|---" * (len(tasks) + 1) + "|")
    for arm in arms:
        cells = []
        for t in tasks:
            g = agg.get((arm, t))
            if not g:
                cells.append("—")
                continue
            cells.append("J1 %d/%d · J3 %d/%d" % (g["J1"], g["n"], g["J3"], g["n"]))
        print("| %s | %s |" % (arm, " | ".join(cells)))
    print()
    print("## 三、无上下文臂的「目标仓具体断言」计数（J6 代理）")
    print()
    for arm in arms:
        rr = [r for r in rows if r["arm"] == arm and r["ctx"] == "noctx"]
        if not rr:
            continue
        fab = [r["fab"] for r in rr]
        print("- %s：%d 份，命中关键词平均 %.1f 个/份" % (arm, len(rr), sum(fab) / len(fab)))
    print()
    print("## 四、方差提示（必须先看）")
    print()
    同格 = {}
    for r in rows:
        同格.setdefault((r["arm"], r["task"]), []).append(r["J1"])
    mixed = [k for k, v in 同格.items() if len(set(v)) > 1]
    print("- 重复间 J1 不一致的格：%d / %d" % (len(mixed), len(同格)))
    if mixed:
        for k in mixed[:6]:
            print("  - %s / %s" % k)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())