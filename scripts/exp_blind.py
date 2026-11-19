"""实验台 · 盲评包：把 60 份输出去标识，生成 S001..S060 + 独立映射表（映射不给评分者）。

用法：python -X utf8 scripts/exp_blind.py --dir artifacts/persona_v1 --out experiments/handoff/blind
"""
import argparse
import glob
import io
import json
import os
import random


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--spec", default="experiments/specs/persona_v1.json")
    ap.add_argument("--seed", type=int, default=20261119)
    a = ap.parse_args(argv)
    with io.open(a.spec, encoding="utf-8") as f:
        spec = json.load(f)
    tasks = {t["id"]: t for t in spec["tasks"]}
    rows = []
    for p in sorted(glob.glob(os.path.join(a.dir, "*.json"))):
        if p.endswith("index.jsonl"):
            continue
        with io.open(p, encoding="utf-8") as f:
            d = json.load(f)
        if not d.get("text"):
            continue
        rows.append(d)
    random.Random(a.seed).shuffle(rows)
    os.makedirs(a.out, exist_ok=True)
    mapping = []
    for i, d in enumerate(rows, 1):
        sid = "S%03d" % i
        task = tasks.get(d.get("task")) or {}
        body = [
            "# " + sid,
            "",
            "## 题面（所有样本同一题面；输出由不同条件产生，评分时不必关心条件）",
            "",
            task.get("prompt", "（缺题面）"),
            "",
            "## 输出",
            "",
            d.get("text", ""),
            "",
        ]
        with io.open(os.path.join(a.out, sid + ".md"), "w", encoding="utf-8", newline="\n") as f:
            f.write(chr(10).join(body))
        mapping.append({"sid": sid, "arm": d.get("arm"), "task": d.get("task"), "repeat": d.get("repeat"), "chars": len(d.get("text") or "")})
    with io.open(os.path.join(a.out, "_MAP_DO_NOT_SHARE.csv"), "w", encoding="utf-8", newline="\n") as f:
        f.write("sid,arm,task,repeat,chars\n")
        for m in mapping:
            f.write("%s,%s,%s,%s,%s\n" % (m["sid"], m["arm"], m["task"], m["repeat"], m["chars"]))
    sheet = ["sid,J2_取舍说明(0-2),J4_可用度(0-2),一句理由"]
    for m in mapping:
        sheet.append("%s,,," % m["sid"])
    with io.open(os.path.join(a.out, "_SCORE_SHEET.csv"), "w", encoding="utf-8", newline="\n") as f:
        f.write(chr(10).join(sheet) + chr(10))
    print("盲评包已生成：%d 份 → %s" % (len(mapping), a.out))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())