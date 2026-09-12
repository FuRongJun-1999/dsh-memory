#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""工作纪律 · 漂移守卫（双向比对：真源 ↔ 各 harness 产物）

正向（真源 → 产物）：每条纪律的 semantic / 动作 / 声明 必须出现在产物中。
反向（产物 → 真源）：产物里出现的每一条「按工作纪律第 N 条」声明，必须能在真源里找到；
                     出现真源没有的声明即判为孤儿（手抄残留 / 旧版本）。

用法：
    python scripts/verify_discipline.py                 # 默认校验 enabled 目标
    python scripts/verify_discipline.py --target codebuddy --allow-missing   # 干跑比对（产物未生成时不报错）
    python scripts/verify_discipline.py --json
退出码：0 全部一致；1 存在漂移或缺失；2 用法错误。
"""
from __future__ import annotations

import argparse
import io
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import render_discipline as R  # noqa: E402

DECL_RE = re.compile(r"按工作纪律第\s*(\d+)\s*条")


def norm(s):
    return re.sub(r"\s+", " ", str(s)).strip()


def extract(target, repo):
    """返回 (text, source_desc) 或 (None, 说明)"""
    if target.get("transport") == "file":
        path = R.expand(target["path"], repo)
        if not os.path.isfile(path):
            return None, "未生成：" + path
        with io.open(path, encoding="utf-8") as f:
            return f.read(), path
    text, _eol = R.read_config_key(target, repo)
    if text is None:
        return None, "未找到受管块：" + R.expand(target["path"], repo)
    return text, R.expand(target["path"], repo)


def check(target, src, repo, allow_missing):
    nodes = R.nodes_of(src)
    text, where = extract(target, repo)
    res = {"target": target.get("_name"), "variant": target.get("variant"),
           "transport": target.get("transport"), "artifact": where,
           "missing": [], "orphans": [], "ok": True, "skipped": False}
    if text is None:
        res["skipped"] = True
        res["ok"] = bool(allow_missing)
        return res

    body = norm(text)
    for i, n in enumerate(nodes, 1):
        ex = (n.get("execution", {}) or {}).get("how", "")
        rs = (n.get("response", {}) or {}).get("direct", "")
        for label, val in (("动作", ex), ("声明", rs)):
            if val and norm(val) not in body:
                res["missing"].append({"no": i, "field": label, "id": n["id"], "text": norm(val)[:80]})

    known = set()
    for n in nodes:
        d = norm((n.get("response", {}) or {}).get("direct", ""))
        m = DECL_RE.search(d)
        if m:
            known.add(int(m.group(1)))
    found = set(int(m.group(1)) for m in DECL_RE.finditer(body))
    unknown = sorted(found - known)
    if unknown:
        res["orphans"] = unknown
        for no in unknown:
            snippet = ""
            for line in text.splitlines():
                if DECL_RE.search(line) and ("第 %d 条" % no) in line or ("第%d条" % no) in line:
                    snippet = line.strip()[:100]
                    break
            res["orphans"] = res.get("orphans")
        res["orphan_detail"] = [{"no": no} for no in unknown]

    # 陈化检查：产物内嵌的真源指纹 vs 当前真源指纹（改真源未重渲染）
    m = re.search(r"前16位[）：:]*\s*([0-9a-f]{16})", text)
    res["artifact_sha"] = m.group(1) if m else None
    res["source_sha"] = R.source_sha(repo)
    res["stale"] = bool(m) and res["artifact_sha"] != res["source_sha"]

    res["ok"] = not res["missing"] and not res["orphans"]
    return res


def main(argv=None):
    ap = argparse.ArgumentParser(description="工作纪律漂移守卫")
    ap.add_argument("--repo", default=R.REPO_DEFAULT)
    ap.add_argument("--target", action="append", default=[])
    ap.add_argument("--all-targets", action="store_true", help="含 enabled=false 的目标（干跑比对）")
    ap.add_argument("--allow-missing", action="store_true", help="产物不存在时不计为失败")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)

    repo = os.path.abspath(args.repo)
    mx = R.load_matrix(repo)
    src = R.load_source(repo)
    targets = mx.get("targets", {})
    names = args.target or [n for n, t in targets.items() if t.get("enabled") or args.all_targets]

    results = []
    for name in names:
        t = dict(targets.get(name) or {})
        t["_name"] = name
        results.append(check(t, src, repo, args.allow_missing))

    bad = [r for r in results if not r["ok"]]
    if args.json:
        print(json.dumps({"ok": not bad, "results": results}, ensure_ascii=False, indent=2))
    else:
        for r in results:
            mark = "SKIP" if r["skipped"] else ("OK  " if r["ok"] else "DRIFT")
            print("[%s] %-10s variant=%-7s -> %s" % (mark, r["target"], str(r["variant"]), r["artifact"]))
            for m in r["missing"]:
                print("        缺失 第%d条 %s: %s" % (m["no"], m["field"], m["text"]))
            if r["orphans"]:
                print("        孤儿声明（真源无此条）：第 %s 条" % ", ".join(str(x) for x in r["orphans"]))
            if r.get("stale"):
                print("        陈化：产物指纹 %s ≠ 当前真源 %s（改真源后未重渲染）"
                      % (r.get("artifact_sha"), r.get("source_sha")))
        print("")
        print("结论：%d/%d 目标一致%s" % (len(results) - len(bad), len(results),
                                        "" if not bad else "；漂移目标：" + ", ".join(r["target"] for r in bad)))
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
