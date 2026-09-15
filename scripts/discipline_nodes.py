#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""工作纪律 · 认知图投影节点同步器与守卫（真源 → 灵枢认知图 structural 节点）

背景（第4条取证）：纪律除「渲染产物」外还有一份**认知图投影**——认知图
`structural/` 下若干 `work-discipline` 节点（frontmatter tags 含 `discipline:N`），
承载「route 命中纪律」的检索面。它们此前是**手工快照**：既不在 render 渲染矩阵内、
也不在 verify 守卫内 —— 改真源后必然陈化。实例（2026-09-16）：真源第16条新增
「写入后读回确认」后，投影节点仍停留旧 `source_sha` 与旧正文；第17条（蜂巢派发）
**根本没有投影节点**。

这与「手写行号必腐化」同构：无守卫的手工件必然漂移。故把该投影并入
「真源 → render / verify」链路：
  - `render_discipline.py --all --write` 顺带同步（认知图 root 可用才做）
  - `verify_discipline.py` 校验一致性（root 不可用则跳过，外部 clone 不误红）

root 解析顺序：`--cg-root` > 环境变量 `MDCG_ROOT` > 缺失 → 跳过（退出 0）。
**不硬编码本机路径**（第14条：公开仓产物不得含本机绝对路径）。

用法：
    python scripts/discipline_nodes.py --check [--cg-root <root>]
    python scripts/discipline_nodes.py --write [--cg-root <root>]
    python scripts/discipline_nodes.py --check --json
退出码：0 一致或跳过；1 存在漂移；2 用法错误。
"""
from __future__ import annotations

import argparse
import io
import json
import os
import re
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import render_discipline as R  # noqa: E402

NODE_DIR = "structural"
TAG_PREFIX = "discipline:"
DEFAULT_CARRIER = "本机三 harness（codebuddy / zcode / dsh）的会话上下文与灵枢认知图"

_LINE_NAMES = ("功能名", "生效条件", "子功能", "执行", "验证方式", "不适用条件")
_CARRIER_RE = re.compile(r"载体/位置：(.*?)；时间：(.*?)；方法：", re.S)


# ---------------------------------------------------------------- 基础工具

def resolve_root(explicit=None):
    """认知图 root：显式参数 > MDCG_ROOT 环境变量 > None（跳过）。"""
    root = explicit or os.environ.get("MDCG_ROOT")
    if not root:
        return None
    root = os.path.normpath(os.path.expanduser(root))
    return root if os.path.isdir(root) else None


def _read_node(path):
    with io.open(path, encoding="utf-8") as f:
        raw = f.read()
    if not raw.startswith("---"):
        return None, raw
    end = raw.find("\n---", 3)
    if end < 0:
        return None, raw
    fm_text = raw[3:end].lstrip("\n")
    body = raw[end + 4:].lstrip("\n")
    fm = {}
    for line in fm_text.split("\n"):
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if ":" not in line:
            continue
        k, v = line.split(":", 1)
        fm[k.strip()] = v.strip()
    return fm, body


def _fm_render(fm_lines):
    return "---\n" + "\n".join(fm_lines) + "\n---\n"


def _json_field(fm, key):
    raw = fm.get(key)
    if not raw:
        return {}
    try:
        val = json.loads(raw)
    except Exception:  # noqa: BLE001
        return {}
    return val if isinstance(val, dict) else {}


def _norm(s):
    return re.sub(r"\s+", " ", str(s)).strip()


# ---------------------------------------------------------------- 期望形态

def expected_fields(n, i, sha, source_rel):
    """该条纪律在投影节点上的『可机械派生』期望值。"""
    cond = n.get("conditions") or {}
    neg = n.get("negative") or {}
    ex = n.get("execution") or {}
    rs = n.get("response") or {}
    return {
        "semantic": str(n.get("semantic", n["id"])).strip(),
        "trigger": R._list_or(cond.get("apply"), "（无前置条件，始终适用）"),
        "how": str(ex.get("how", "")).strip(),
        "direct": str(rs.get("direct", "")).strip(),
        "content": str(n.get("content", "")).strip(),
        "nac": [str(c) for c in (neg.get("reject") or [])],
        "sha": sha,
        "source_rel": source_rel,
        "node_id": n["id"],
        "no": i,
    }


def expected_body(exp, carrier, time_txt):
    """投影节点正文六行（与既有节点同构）。"""
    nac = "；".join(exp["nac"]) or "（无）"
    return [
        "# 功能名：工作纪律第%d条 · %s" % (exp["no"], exp["semantic"]),
        "# 生效条件：载体/位置：%s；时间：%s；方法：%s；约束：真源 = 灵枢大脑库 %s"
        " 节点 %s（SHA256 前16位 %s），本节点是其在认知图中的投影"
        % (carrier, time_txt, exp["how"], exp["source_rel"], exp["node_id"], exp["sha"]),
        "# 子功能：%s" % exp["content"],
        "# 执行：触发（%s）命中即执行「%s」；并在回复中原样输出声明：%s"
        % (exp["trigger"], exp["how"], exp["direct"]),
        "# 验证方式：data（真源 JSON 节点 %s；区间：%s）" % (exp["node_id"], exp["source_rel"]),
        "# 不适用条件：%s" % nac,
    ]


def _carrier_of(body, created_at):
    m = _CARRIER_RE.search(body or "")
    if m:
        return m.group(1).strip(), m.group(2).strip()
    stamp = datetime.fromtimestamp(float(created_at)).strftime("%Y-%m-%d") \
        if created_at else datetime.now().strftime("%Y-%m-%d")
    return DEFAULT_CARRIER, "%s 起长期有效" % stamp


# ---------------------------------------------------------------- 盘点

def scan_nodes(root):
    """返回 {条号(int): {"path", "raw", "fm", "body"}}（tags 含 discipline:N）。"""
    out = {}
    d = os.path.join(root, NODE_DIR)
    if not os.path.isdir(d):
        return out
    for fn in sorted(os.listdir(d)):
        if not fn.endswith(".md"):
            continue
        path = os.path.join(d, fn)
        fm, body = _read_node(path)
        if not fm:
            continue
        tags = fm.get("tags") or ""
        for t in re.findall(r"[\"']([^\"']+)[\"']", tags):
            if t.startswith(TAG_PREFIX):
                try:
                    out[int(t[len(TAG_PREFIX):])] = {
                        "path": path, "fm": fm, "fm_raw": fm, "body": body}
                except ValueError:
                    pass
    return out


def check_cg_nodes(repo, root, allow_missing=True):
    """守卫：真源 ↔ 认知图投影节点一致性。root 为 None 时返回 skipped。"""
    if root is None:
        return {"skipped": True, "reason": "未提供认知图 root（--cg-root / MDCG_ROOT），跳过投影节点校验",
                "ok": True, "drift": [], "nodes": 0}
    src = R.load_source(repo)
    sha = R.source_sha(repo)
    source_rel = os.path.basename(R.source_path(repo))
    mx = R.load_matrix(repo)
    source_rel = mx["source"]
    nodes = R.nodes_of(src)
    have = scan_nodes(root)

    drift = []
    for i, n in enumerate(nodes, 1):
        exp = expected_fields(n, i, sha, source_rel)
        cur = have.get(i)
        if cur is None:
            drift.append({"no": i, "id": exp["node_id"], "kind": "missing",
                          "detail": "认知图内无 discipline:%d 投影节点" % i})
            continue
        fm, body = cur["fm"], cur["body"]
        cs = _json_field(fm, "condition_space")
        got_sha = str(cs.get("source_sha") or "").strip().strip('"')
        if got_sha != sha:
            drift.append({"no": i, "id": exp["node_id"], "kind": "sha",
                          "detail": "source_sha %s ≠ 当前真源 %s（改真源后未同步）" % (got_sha or "-", sha)})
        if _norm(cs.get("trigger") or "") != _norm(exp["trigger"]):
            drift.append({"no": i, "id": exp["node_id"], "kind": "trigger",
                          "detail": "condition_space.trigger 不一致"})
        carrier, time_txt = _carrier_of(body, fm.get("created_at"))
        for want in expected_body(exp, carrier, time_txt):
            name = want.split("：", 1)[0].lstrip("# ")
            if _norm(want) not in _norm(body):
                drift.append({"no": i, "id": exp["node_id"], "kind": "body:" + name,
                              "detail": "%s 行与真源不一致" % name})
        if _norm(fm.get("id") or "").strip('"') == "":
            drift.append({"no": i, "id": exp["node_id"], "kind": "id", "detail": "节点缺 id"})
    return {"skipped": False, "ok": not drift, "drift": drift,
            "nodes": len(nodes), "source_sha": sha, "scanned": len(have)}


# ---------------------------------------------------------------- 同步

def _write_node(path, fm, fm_order, body_lines):
    lines = []
    for k in fm_order:
        v = fm.get(k, "")
        lines.append("%s: %s" % (k, v))
    with io.open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(_fm_render(lines) + "\n".join(body_lines).rstrip() + "\n")


def _new_node_fm(exp, now):
    nac = json.dumps(exp["nac"], ensure_ascii=False)
    cs = json.dumps({"trigger": exp["trigger"], "harness": "codebuddy|zcode|dsh",
                     "source_sha": exp["sha"],
                     "time_window": [now, now + 3600]}, ensure_ascii=False)
    nid = "mem_%d" % int(now * 1000)
    fm = [
        "access_count: 0",
        "condition_space: " + cs,
        "confidence: 0.6",
        "created_at: %s" % now,
        "edges: []",
        "evidence_count: 0",
        'id: "%s"' % nid,
        "importance: 0.85",
        "last_access: 0",
        'layer: "structural"',
        'modality: "text"',
        "negative_evidence: 0",
        "non_applicable_conditions: " + nac,
        "positive_evidence: 0",
        "protected: true",
        'protection_reason: "importance=0.85≥0.7"',
        'sensitivity: "internal"',
        'tags: ["work-discipline", "discipline:%d", "harness:all", "v1.1"]' % exp["no"],
        'verification_basis: "data"',
    ]
    return nid, fm


def sync_cg_nodes(repo, root, write=False):
    """把真源同步进认知图投影节点。write=False 时干跑（只报告差异）。"""
    if root is None:
        return {"skipped": True, "reason": "未提供认知图 root（--cg-root / MDCG_ROOT），跳过投影节点同步",
                "changed": [], "created": []}
    src = R.load_source(repo)
    sha = R.source_sha(repo)
    mx = R.load_matrix(repo)
    source_rel = mx["source"]
    nodes = R.nodes_of(src)
    have = scan_nodes(root)
    now = datetime.now().timestamp()

    changed, created = [], []
    for i, n in enumerate(nodes, 1):
        exp = expected_fields(n, i, sha, source_rel)
        cur = have.get(i)
        if cur is None:
            nid, fm_lines = _new_node_fm(exp, now)
            carrier, time_txt = DEFAULT_CARRIER, datetime.fromtimestamp(now).strftime("%Y-%m-%d") + " 起长期有效"
            body = expected_body(exp, carrier, time_txt)
            path = os.path.join(root, NODE_DIR, "%s.md" % nid)
            if write:
                os.makedirs(os.path.dirname(path), exist_ok=True)
                order = [l.split(":", 1)[0] for l in fm_lines]
                _write_node(path, dict(zip(order, [l.split(":", 1)[1].strip() for l in fm_lines])),
                            order, body)
            created.append({"no": i, "id": nid, "path": path, "written": bool(write)})
            continue

        fm, body = cur["fm"], cur["body"]
        fm = dict(fm)
        carrier, time_txt = _carrier_of(body, fm.get("created_at"))
        want_body = expected_body(exp, carrier, time_txt)
        fm["condition_space"] = json.dumps(
            {"trigger": exp["trigger"], "harness": "codebuddy|zcode|dsh", "source_sha": sha,
             "time_window": _json_field(fm, "condition_space").get("time_window") or [now, now + 3600]},
            ensure_ascii=False)
        fm["non_applicable_conditions"] = json.dumps(exp["nac"], ensure_ascii=False)

        cur_norm_body = [_norm(l) for l in (body or "").splitlines() if l.strip()]
        same = cur_norm_body == [_norm(l) for l in want_body] and \
            str(_json_field(cur["fm"], "condition_space").get("source_sha") or "") == sha
        if same:
            continue
        order = [k for k in cur["fm"].keys()]
        changed.append({"no": i, "id": str(fm.get("id", "")).strip('"'), "path": cur["path"],
                        "written": bool(write)})
        if write:
            _write_node(cur["path"], fm, order, want_body)
    return {"skipped": False, "changed": changed, "created": created,
            "source_sha": sha, "nodes": len(nodes)}


def main(argv=None):
    ap = argparse.ArgumentParser(description="工作纪律认知图投影节点同步器与守卫")
    ap.add_argument("--repo", default=R.REPO_DEFAULT)
    ap.add_argument("--cg-root", default=None, help="认知图 root（缺省读环境变量 MDCG_ROOT）")
    ap.add_argument("--check", action="store_true", help="校验一致性（默认动作）")
    ap.add_argument("--write", action="store_true", help="同步（写盘）")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)

    repo = os.path.abspath(args.repo)
    root = resolve_root(args.cg_root)

    if args.write:
        rep = sync_cg_nodes(repo, root, write=True)
        if args.json:
            print(json.dumps(rep, ensure_ascii=False, indent=2))
        elif rep.get("skipped"):
            print("[SKIP] " + rep["reason"])
        else:
            print("真源指纹 %s；纪律 %d 条" % (rep["source_sha"], rep["nodes"]))
            for r in rep["created"]:
                print("  [新建] 第%d条 -> %s" % (r["no"], r["path"]))
            for r in rep["changed"]:
                print("  [同步] 第%d条 %s -> %s" % (r["no"], r["id"], r["path"]))
            if not rep["created"] and not rep["changed"]:
                print("  已一致，无需改动")
        return 0

    res = check_cg_nodes(repo, root)
    if args.json:
        print(json.dumps(res, ensure_ascii=False, indent=2))
    elif res.get("skipped"):
        print("[SKIP] " + res["reason"])
    else:
        print("真源指纹 %s；纪律 %d 条；认知图扫描到 %d 个投影节点"
              % (res["source_sha"], res["nodes"], res["scanned"]))
        if res["ok"]:
            print("[OK  ] 投影节点与真源一致")
        else:
            for d in res["drift"]:
                print("  [DRIFT] 第%d条 %s: %s" % (d["no"], d["kind"], d["detail"]))
        print("")
        print("结论：%s（漂移 %d 处）" % ("一致" if res["ok"] else "存在漂移", len(res["drift"])))
    return 0 if res.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
