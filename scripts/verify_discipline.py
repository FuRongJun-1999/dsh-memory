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

# —— 工具名随端标注守卫（20260916 漂移实例的机械捕获器）——
# 纪律件里出现的 DSH 端基元注册名；宿主内建桥端（memory 以 plugin/ 开头）该名即本端正名，豁免。
TOOLNAME_DSH = ("lingshu_cg", "lingshu_stg")
MCP_CANON = "mdcg"

# —— 逐字比对字段（默认全部 strict；target 可用 verify_fields 把个别字段降为 advisory）——
# 历史缺陷（20260916 第二例）：原实现只比 动作/声明 两栏，而根注入件序言承诺的
# 「编号 / 触发 / 不适用 / 声明出口」四项中，触发与不适用两栏**完全无守卫**——
# 承诺项无守卫即等同无承诺（与「手写行号必腐化」同构）。
FIELD_LABEL = {"trigger": "触发", "action": "动作", "negative": "不适用", "declaration": "声明"}
FIELD_ORDER = ("trigger", "action", "negative", "declaration")


def field_value(n, key):
    """取该条纪律在指定字段上的『渲染口径』文本（与 render_discipline 生成产物同源）。"""
    if key == "action":
        return str((n.get("execution") or {}).get("how", ""))
    if key == "declaration":
        return str((n.get("response") or {}).get("direct", ""))
    if key == "trigger":
        return R._list_or((n.get("conditions") or {}).get("apply"), "（无前置条件，始终适用）")
    if key == "negative":
        return R._list_or((n.get("negative") or {}).get("reject"), "（无）")
    raise KeyError(key)


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


def check_tool_alignment(text, target):
    """工具名随端标注守卫：MCP 端件里出现的 DSH 端注册名，必须与 MCP 端正名同行。

    历史缺陷（20260916）：根注入件 AGENTS.md 手工维护、长期不在渲染/校验矩阵内，把 DSH 端的
    `lingshu_cg` 写死为「工具全名」并加「非 cg」的反向否决，本端 agent 因此对工具名产生疑惑。
    根因与「手写行号必腐化」同构——无守卫的手工件必然漂移。
    判据：该端 memory 声明为宿主内建桥（plugin/…）时，`lingshu_cg` 就是本端注册名，无标注义务。
    """
    if str(target.get("memory") or "").startswith("plugin/"):
        return []
    bad = []
    for ln, line in enumerate(text.splitlines(), 1):
        if any(t in line for t in TOOLNAME_DSH) and MCP_CANON not in line:
            bad.append({"line": ln, "text": line.strip()[:100]})
    return bad


def check(target, src, repo, allow_missing):
    nodes = R.nodes_of(src)
    text, where = extract(target, repo)
    res = {"target": target.get("_name"), "variant": target.get("variant"),
           "transport": target.get("transport"), "artifact": where,
           "missing": [], "advisory": [], "orphans": [], "ok": True, "skipped": False}
    if text is None:
        res["skipped"] = True
        res["ok"] = bool(allow_missing)
        return res

    # 字段级判据：默认 strict；target 的 verify_fields 可把某字段降为 advisory
    # （降级只对「清单/摘要形态的手工件」成立，且差异仍全量打印——不静默）。
    vf = target.get("verify_fields") or {}
    advisory_keys = {k for k, v in vf.items() if str(v).lower() == "advisory"}

    body = norm(text)
    for i, n in enumerate(nodes, 1):
        for key in FIELD_ORDER:
            val = field_value(n, key)
            if not val or norm(val) in body:
                continue
            rec = {"no": i, "field": FIELD_LABEL[key], "key": key,
                   "id": n["id"], "text": norm(val)[:80]}
            (res["advisory"] if key in advisory_keys else res["missing"]).append(rec)

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

    res["toolname"] = check_tool_alignment(text, target)

    res["ok"] = not res["missing"] and not res["orphans"] and not res["toolname"]
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
            if r.get("advisory"):
                print("        摘要差异 %d 处（该目标声明 verify_fields=advisory：清单形态需转义半角 "
                      "'|' 且刻意摘要化，故不判失败；差异全量列出供人工复核）"
                      % len(r["advisory"]))
                for m in r["advisory"]:
                    print("          ~ 第%d条 %s: %s" % (m["no"], m["field"], m["text"]))
            if r["orphans"]:
                print("        孤儿声明（真源无此条）：第 %s 条" % ", ".join(str(x) for x in r["orphans"]))
            for m in r.get("toolname") or []:
                print("        工具名未随端标注（DSH 端注册名未与本端正名同行）第%d行: %s"
                      % (m["line"], m["text"]))
            if r.get("stale"):
                print("        陈化：产物指纹 %s ≠ 当前真源 %s（改真源后未重渲染）"
                      % (r.get("artifact_sha"), r.get("source_sha")))
        print("")
        print("结论：%d/%d 目标一致%s" % (len(results) - len(bad), len(results),
                                        "" if not bad else "；漂移目标：" + ", ".join(r["target"] for r in bad)))
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
