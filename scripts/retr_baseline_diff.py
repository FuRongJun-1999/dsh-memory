# -*- coding: utf-8 -*-
"""检索基线固化与漂移比对（阶段二 批 0 · B）。

查询集 = S-A ∪ S-B（显式白名单，不做全仓启发式扫描）：
  S-A  s_a_bench6_zh / s_a_bench6_en   data/benchmarks/bench6-100-zh-en/questions.jsonl
       s_a_locomo_zh_500               data/external/locomo_zh/questions500.jsonl
       s_a_locomo_en_raw               data/external/locomo_zh/raw_questions.jsonl
       s_a_blind_comp                  md_cg/bench_blind_comp.py 的静态题面常量（ast 提取，禁止 import）
       s_a_test_retr_s1..s7            取证结论：无查询集常量（脚本式测试，import 会执行并 sys.exit）→ 恒 0
  S-B  s_b_reflection                 <root>/_reflection.jsonl 的 query 字段
S-C（审计日志）明确排除：那是运维记录不是检索查询。

比对硬纪律（--diff）：
  ① 自证 OLD vs OLD 必须零差异，失败即红灯退出（防工具坏了报绿）
  ② baseline meta.repo_commit 与当前 HEAD 不一致即报错退出（区分「不可比」与「不一致」）
  ③ cases 一致性（条数 + q 序列逐位）
  ④ root 与节点数一致性
  ⑤ 断言 len(Q) > 0（空集红灯，不是「无数据可测」）
  ⑥ 逐位比对 id 与 score 序列，差异逐位列出

用法：
  python scripts/retr_baseline_diff.py --build [--max-per-source 40] [--seed 42]
  python scripts/retr_baseline_diff.py --cases
  python scripts/retr_baseline_diff.py --diff --baseline <file> [--new <file>] [--allow-commit-mismatch]
"""
import argparse
import ast
import datetime as _dt
import json
import os
import random
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
if REPO not in sys.path:
    sys.path.insert(0, REPO)

from md_cg.mdcg import LAYERS   # noqa: E402

RESULTS_DIR = os.path.join(REPO, "data", "external", "eval_results")

# 现役默认检索参数（与 MCP 面 / 默认链路逐位一致；record=False 仅为不写运维日志）
SEARCH_PARAMS = {
    "k": 20,
    "min_results": 1,
    "layer": None,
    "context": None,
    "record": False,
}

ENV_KEYS = [
    "MDCG_SEMANTIC", "MDCG_EN_ATOMS", "MDCG_RETRIEVAL_PIPELINE",
    "MDCG_GATE_S1B", "MDCG_GATE_S2", "MDCG_GATE_S3", "MDCG_GATE_S4",
    "MDCG_REACH", "MDCG_POOLING",
]

# 文件型 S-A 源白名单：(source, 相对路径, 题面字段)
FILE_SOURCES = [
    ("s_a_bench6_zh", "data/benchmarks/bench6-100-zh-en/questions.jsonl", "question_zh"),
    ("s_a_bench6_en", "data/benchmarks/bench6-100-zh-en/questions.jsonl", "question_en"),
    ("s_a_locomo_zh_500", "data/external/locomo_zh/questions500.jsonl", "question"),
    ("s_a_locomo_en_raw", "data/external/locomo_zh/raw_questions.jsonl", "question"),
]

# 取证结论：这些脚本式测试里不存在可用作查询集的常量，恒记 0（不假造）
TEST_SET_SOURCES = ["s_a_test_retr_s1", "s_a_test_retr_s2", "s_a_test_retr_s3",
                    "s_a_test_retr_s4", "s_a_test_retr_s5", "s_a_test_retr_s6",
                    "s_a_test_retr_s7"]


# 生效条件：cwd 为仓库目录且 git 可用时返回 HEAD 短哈希，失败返回 "unknown"。
def _git_commit():
    try:
        r = subprocess.run(["git", "rev-parse", "HEAD"], cwd=REPO,
                           capture_output=True, text=True,
                           encoding="utf-8", errors="replace", shell=False)
        return r.stdout.strip() if r.returncode == 0 else "unknown"
    except Exception:
        return "unknown"


# 生效条件：md_cg 目录存在时返回其下 *.py 的最大 mtime（ISO 字符串），否则 None。
def _md_cg_mtime_max():
    d = os.path.join(REPO, "md_cg")
    latest = None
    for dirpath, _dirnames, files in os.walk(d):
        for fn in files:
            if not fn.endswith(".py"):
                continue
            try:
                m = os.path.getmtime(os.path.join(dirpath, fn))
            except OSError:
                continue
            if latest is None or m > latest:
                latest = m
    if latest is None:
        return None
    return _dt.datetime.fromtimestamp(latest).astimezone().isoformat(timespec="seconds")


# 生效条件：返回 ENV_KEYS 当前取值快照，未设置的键值为 None（不伪造默认值）。
def _env_snapshot():
    return {k: os.environ.get(k) or None for k in ENV_KEYS}


# 生效条件：md_cg.codeindex 可导入且暴露 RENDER_VERSION 时返回其值，否则 None。
def _render_version():
    try:
        from md_cg import codeindex
        return getattr(codeindex, "RENDER_VERSION", None)
    except Exception:
        return None


# 生效条件：root 为目录时返回其 LAYERS 八层内递归 *.md 数（与覆盖率脚本同口径）。
def _count_layer_nodes(root):
    total = 0
    for layer in LAYERS:
        layer_dir = os.path.join(root, layer)
        if not os.path.isdir(layer_dir):
            continue
        for _dirpath, _dirnames, files in os.walk(layer_dir):
            total += sum(1 for fn in files if fn.endswith(".md"))
    return total


# 生效条件：path 存在且为 jsonl 时返回 (rows, parse_errors)，rows 为 (行号, dict) 列表，
# 非 dict 行与解析失败行计入 parse_errors 并跳过；文件不存在返回 ([], 0)。
def _read_jsonl(path):
    rows, errors = [], 0
    if not os.path.isfile(path):
        return rows, errors
    with open(path, "r", encoding="utf-8", errors="replace") as fh:
        for i, line in enumerate(fh, 1):
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except Exception:
                errors += 1
                continue
            if not isinstance(obj, dict):
                errors += 1
                continue
            rows.append((i, obj))
    return rows, errors


# 生效条件：node 为 ast 常量节点时返回其 str 取值（无取值返回 None）。
def _const_str(node):
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return None


# 生效条件：node 为 list/tuple/set 字面量时递归收集其中的字符串常量（非字面量忽略）。
def _literals_from_node(node):
    out = []
    if isinstance(node, (ast.List, ast.Tuple, ast.Set)):
        for elt in node.elts:
            out.extend(_literals_from_node(elt))
    elif isinstance(node, ast.Dict):
        for elt in node.values:
            out.extend(_literals_from_node(elt))
    else:
        s = _const_str(node)
        if s is not None:
            out.append(s)
    return out


# 生效条件：bench_blind_comp.py 存在且含 UNSEEN / COMP_EN / COMP_L3 模块级赋值时，
# 返回 (题面列表, 备注)；禁止 import 该模块（import 即构造语料并跑评测）。
def _extract_blind_comp():
    path = os.path.join(REPO, "md_cg", "bench_blind_comp.py")
    if not os.path.isfile(path):
        return [], "bench_blind_comp.py 不存在"
    with open(path, "r", encoding="utf-8", errors="replace") as fh:
        tree = ast.parse(fh.read())
    wanted = ("UNSEEN", "COMP_EN", "COMP_L3")
    items, found = [], []
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        for tgt in node.targets:
            if isinstance(tgt, ast.Name) and tgt.id in wanted:
                found.append(tgt.id)
                items.extend(_literals_from_node(node.value))
    note = "ast 提取静态题面常量：%s" % (",".join(found) if found else "未找到")
    return items, note


# 生效条件：path 为 jsonl 文件时按 field 取非空字符串题面，返回 (题面列表, 解析失败数)；
# field 缺失或取值非字符串的行跳过并计入失败数。
def _extract_jsonl_question(path, field):
    rows, errors = _read_jsonl(path)
    out = []
    for _lineno, obj in rows:
        v = obj.get(field)
        if isinstance(v, str) and v.strip():
            out.append(v.strip())
        else:
            errors += 1
    return out, errors


# 生效条件：items 为序列且 limit>0 时用固定 seed 确定性抽样并返回 (子序列, True)；
# limit<=0 或 len(items)<=limit 时返回 (全量副本, False)。
def _sample_items(items, limit, seed):
    if limit and limit > 0 and len(items) > limit:
        rnd = random.Random(seed)
        idx = sorted(rnd.sample(range(len(items)), limit))
        return [items[i] for i in idx], True
    return list(items), False


# 生效条件：root 为认知图库目录时收集 S-A ∪ S-B 全部候选题面（去重、保序），
# 返回 (cases, source_stats)；cases 元素为 {"source","q"}。
def _collect_candidates(root, limit, seed):
    cases, stats = [], {}

    for source, rel, field in FILE_SOURCES:
        path = os.path.join(REPO, rel.replace("/", os.sep))
        items, errors = _extract_jsonl_question(path, field)
        picked, sampled = _sample_items(items, limit, seed + len(source))
        stats[source] = {"path": rel, "field": field, "available": len(items),
                         "used": len(picked), "sampled": sampled, "parse_errors": errors}
        cases.extend({"source": source, "q": q} for q in picked)

    items, note = _extract_blind_comp()
    picked, sampled = _sample_items(items, limit, seed + 1)
    stats["s_a_blind_comp"] = {"path": "md_cg/bench_blind_comp.py", "field": "(静态常量)",
                               "available": len(items), "used": len(picked),
                               "sampled": sampled, "note": note}
    cases.extend({"source": "s_a_blind_comp", "q": q} for q in picked)

    for source in TEST_SET_SOURCES:
        stats[source] = {"path": "md_cg/%s.py" % source.replace("s_a_", ""), "field": "(无)",
                         "available": 0, "used": 0, "sampled": False,
                         "note": "取证结论：脚本式测试、无查询集常量（import 会执行并 sys.exit）"}
        # 不做提取，如实计 0

    refl = os.path.join(root, "_reflection.jsonl") if root else ""
    rows, errors = _read_jsonl(refl) if refl else ([], 0)
    items = [obj.get("query").strip() for _ln, obj in rows
             if isinstance(obj.get("query"), str) and obj.get("query").strip()]
    stats["s_b_reflection"] = {"path": "_reflection.jsonl", "field": "query",
                               "available": len(items), "used": len(items),
                               "sampled": False, "parse_errors": errors}
    cases.extend({"source": "s_b_reflection", "q": q} for q in items)

    dedup, seen = [], set()
    for c in cases:
        if c["q"] in seen:
            continue
        seen.add(c["q"])
        dedup.append(c)
    return dedup, stats


# 生效条件：root 为目录时构造只读 MdCGSecure 实例（与 MCP 面同一入口与 autoflush 口径）。
def _build_instance(root):
    from md_cg.mdcos import MdCGSecure
    from md_cg.security import Principal
    principal = Principal(actor="cli-baseline", clearance="secret", can_write=False,
                          can_admin=False, role="designer", auth_mode="local-cli")
    return MdCGSecure(root, principal=principal, autoflush=1)


# 生效条件：results 为 search 返回的 (node, score, qualification) 序列时，
# 返回 (ids, scores) 两个平行列表；结构不符的元素按 None id / 0.0 score 占位。
def _extract_result_items(results):
    ids, scores = [], []
    for row in results or []:
        node, score = None, 0.0
        if isinstance(row, (tuple, list)):
            if row:
                node = row[0]
            if len(row) > 1:
                score = row[1]
        elif isinstance(row, dict):
            node, score = row, row.get("score", 0.0)
        nid = None
        if isinstance(node, dict):
            nid = node.get("id") or node.get("node_id")
        ids.append(nid)
        try:
            scores.append(float(score))
        except (TypeError, ValueError):
            scores.append(None)
    return ids, scores


# 生效条件：cases 为 {"source","q"} 列表且 root 可构造检索实例时，按现役默认参数采样，
# 返回 (cases_with_hits, meta)；每次检索只读（record=False），不改数据面。
def _run_search(cases, root):
    cg = _build_instance(root)
    out = []
    try:
        for c in cases:
            try:
                results, _meta = cg.search(c["q"], k=SEARCH_PARAMS["k"],
                                           min_results=SEARCH_PARAMS["min_results"],
                                           layer=SEARCH_PARAMS["layer"],
                                           context=SEARCH_PARAMS["context"],
                                           record=SEARCH_PARAMS["record"])
                ids, scores = _extract_result_items(results)
                err = None
            except Exception as exc:
                ids, scores, err = [], [], "%s: %s" % (type(exc).__name__, exc)
            out.append({"source": c["source"], "q": c["q"], "k": SEARCH_PARAMS["k"],
                        "min_results": SEARCH_PARAMS["min_results"],
                        "layer": SEARCH_PARAMS["layer"], "context": SEARCH_PARAMS["context"],
                        "ids": ids, "scores": scores, "error": err})
    finally:
        try:
            cg.close()
        except Exception:
            pass
    return out


# 生效条件：root 为目录时采集完整基线 dict（含 meta 环境快照与逐 case 命中序列）。
def _build_baseline(root, limit, seed):
    candidates, stats = _collect_candidates(root, limit, seed)
    cases = _run_search(candidates, root)
    errors = sum(1 for c in cases if c.get("error"))
    return {
        "meta": {
            "at": _dt.datetime.now().astimezone().isoformat(timespec="seconds"),
            "root": root,
            "node_count": _count_layer_nodes(root),
            "layers": list(LAYERS),
            "repo_commit": _git_commit(),
            "md_cg_mtime_max": _md_cg_mtime_max(),
            "python": sys.version.split()[0],
            "render_version": _render_version(),
            "env": _env_snapshot(),
            "search_params": dict(SEARCH_PARAMS),
            "search_params_note": "record=False 仅避免写运维日志，不参与排序口径",
            "entry": "MdCGSecure(root, principal=只读 designer, autoflush=1).search",
            "sample": {"max_per_source": limit, "seed": seed, "dedup": True},
            "sources": stats,
            "n_cases": len(cases),
            "n_cases_error": errors,
        },
        "cases": cases,
    }


# 生效条件：old/new 为基线 dict 时做六项校验与逐位比对，返回 (ok, messages)；
# ok=False 表示差异或红灯（消息逐条说明，不吞并）。
def _compare(old, new, allow_commit_mismatch=False, check_commit=True):
    msgs = []

    old_cases, new_cases = old.get("cases") or [], new.get("cases") or []
    if len(old_cases) == 0 or len(new_cases) == 0:
        return False, ["红灯⑤：查询集为空（len(cases)==0），不构成可比基线"]

    om, nm = old.get("meta") or {}, new.get("meta") or {}
    if check_commit:
        head = _git_commit()
        for label, m in (("baseline", om), ("new", nm)):
            if m.get("repo_commit") not in (head,):
                if not allow_commit_mismatch:
                    msgs.append("红灯②：%s 的 repo_commit=%s 与当前 HEAD=%s 不一致（不可比）"
                                % (label, m.get("repo_commit"), head))
        if msgs:
            return False, msgs

    if len(old_cases) != len(new_cases):
        msgs.append("红灯③：case 数不一致 old=%d new=%d" % (len(old_cases), len(new_cases)))
    else:
        for i, (a, b) in enumerate(zip(old_cases, new_cases)):
            if a.get("q") != b.get("q"):
                msgs.append("红灯③：第 %d 条 q 不一致 old=%r new=%r" % (i, a.get("q"), b.get("q")))
                break

    if om.get("root") != nm.get("root"):
        msgs.append("红灯④：root 不一致 old=%s new=%s" % (om.get("root"), nm.get("root")))
    if om.get("node_count") != nm.get("node_count"):
        msgs.append("红灯④：节点数不一致 old=%s new=%s"
                    % (om.get("node_count"), nm.get("node_count")))
    if msgs:
        return False, msgs

    diffs = 0
    for i, (a, b) in enumerate(zip(old_cases, new_cases)):
        if a.get("ids") != b.get("ids"):
            diffs += 1
            if diffs <= 20:
                msgs.append("差异⑥[%d] %r：id 序列不同\n  old=%s\n  new=%s"
                            % (i, a.get("q")[:40], a.get("ids"), b.get("ids")))
        elif a.get("scores") != b.get("scores"):
            diffs += 1
            if diffs <= 20:
                msgs.append("差异⑥[%d] %r：score 序列不同\n  old=%s\n  new=%s"
                            % (i, a.get("q")[:40], a.get("scores"), b.get("scores")))
    if diffs:
        msgs.append("总计 %d/%d 条 case 存在漂移" % (diffs, len(old_cases)))
        return False, msgs
    msgs.append("零漂移：%d 条 case 的 id 与 score 序列逐位一致" % len(old_cases))
    return True, msgs


# 生效条件：argv 为 None 或参数序列时按模式执行；--build/--cases 需 root，
# 退出码 0 通过 / 1 差异或红灯 / 2 用法或环境错误。
def main(argv=None):
    p = argparse.ArgumentParser(description="检索基线固化与漂移比对")
    p.add_argument("--build", action="store_true")
    p.add_argument("--diff", action="store_true")
    p.add_argument("--cases", action="store_true")
    p.add_argument("--baseline", default="")
    p.add_argument("--new", default="")
    p.add_argument("--out", default="")
    p.add_argument("--root", default=(os.environ.get("MDCG_ROOT") or "").strip())
    p.add_argument("--max-per-source", type=int, default=40)
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--allow-commit-mismatch", action="store_true")
    args = p.parse_args(argv)

    if not (args.build or args.diff or args.cases):
        p.print_help()
        return 2

    root = os.path.abspath(os.path.expanduser(args.root)) if args.root else ""
    if not root or not os.path.isdir(root):
        print("错误：未提供可用认知图库根：设 MDCG_ROOT 或传 --root DIR", file=sys.stderr)
        return 2

    if args.cases:
        candidates, stats = _collect_candidates(root, args.max_per_source, args.seed)
        print(json.dumps({"n": len(candidates), "sources": stats,
                          "q": [c["q"] for c in candidates]}, ensure_ascii=False, indent=2))
        return 0 if candidates else 1

    if args.build:
        baseline = _build_baseline(root, args.max_per_source, args.seed)
        date = _dt.date.today().strftime("%Y%m%d")
        out = args.out or os.path.join(RESULTS_DIR, "retr_baseline_%s.json" % date)
        os.makedirs(os.path.dirname(out), exist_ok=True)
        with open(out, "w", encoding="utf-8") as fh:
            json.dump(baseline, fh, ensure_ascii=False, indent=2)
        print(json.dumps({"out": out, "meta": baseline["meta"]}, ensure_ascii=False, indent=2))
        return 0

    if not args.baseline:
        print("错误：--diff 需要 --baseline FILE", file=sys.stderr)
        return 2

    with open(args.baseline, "r", encoding="utf-8") as fh:
        old = json.load(fh)

    ok_self, self_msgs = _compare(old, old, allow_commit_mismatch=True, check_commit=False)
    if not ok_self:
        print("红灯①：自证失败（OLD vs OLD 存在差异），比对工具不可信：", file=sys.stderr)
        for m in self_msgs:
            print("  " + m, file=sys.stderr)
        return 1

    if args.new:
        with open(args.new, "r", encoding="utf-8") as fh:
            new = json.load(fh)
        new_label = args.new
    else:
        new = _build_baseline(root, args.max_per_source, args.seed)
        new_label = "(现采)"
        stamp = _dt.datetime.now().strftime("%Y%m%d_%H%M%S")
        dump = os.path.join(RESULTS_DIR, "retr_baseline_rerun_%s.json" % stamp)
        os.makedirs(os.path.dirname(dump), exist_ok=True)
        with open(dump, "w", encoding="utf-8") as fh:
            json.dump(new, fh, ensure_ascii=False, indent=2)

    ok, msgs = _compare(old, new, allow_commit_mismatch=args.allow_commit_mismatch)
    print("[OK] 自证①：OLD vs OLD 零差异")
    print("比对：%s vs %s" % (args.baseline, new_label))
    for m in msgs:
        print(("  " if ok else "  [DIFF] ") + m)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
