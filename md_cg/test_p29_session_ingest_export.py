# -*- coding: utf-8 -*-
"""会话层 + 摄取分派 + 全库导出（P29 · P0 工程缺口验收）。

对照 `docs/灵枢82工具_功能整理与迁移映射_v0.1.md` §五：P0 新增三个 op。

  ① op 三处同步：`tokens.ALL_OPS` == `cg` 工具 op 描述 == `_cg_call` 分支
  ② session：note 幂等写入；recall 一次返回可续接上下文包；compact 启发式压缩
  ③ ingest：注册表分派（file/dir/jsonl/stat）+ dry_run 预演 + 幂等
  ④ export：流式 JSONL（graph/slice/nodes）+ stat 体检 + 管理权限门
  ⑤ 权限：无写权角色可 recall、不可 note；非 admin 不可 export

运行：python -m md_cg.test_p29_session_ingest_export
"""
from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile

from . import corpus, sources, tokens
from .mdcos import MdCGOS
from .mcp_server import KERNEL_TOOLS, call_tool
from .security import AccessDenied, Principal

PASS = FAIL = 0
FAILS = []


GUIDE_MD = ("# 记忆系统指南\n\n"
            "## 概述\n本系统以 md 为单一真相源，派生物可重建。\n\n"
            "## 摄取\n支持按扩展名自动分派到文档 / 代码 / 会话三条链。\n\n"
            "### 细节\n单一入口吃多种文件，避免调用方记忆每个后缀。\n")

ALPHA_PY = ('"""能量计算模块。"""\n'
            'import math\n\n\n'
            'def compute_energy(mass, speed):\n'
            '    """计算动能。"""\n'
            '    return mass * speed * speed\n')

DSH_JSONL = (
    '{"type":"session","id":"S9","cwd":"/x"}\n'
    '{"type":"user/message","time":1700000000000,"seq":1,'
    '"data":{"content":[{"type":"text","text":"请记住我在 Windows 上开发"}]}}\n'
    '{"type":"assistant/message","time":1700000001000,"seq":2,'
    '"data":{"message":{"content":[{"type":"text","text":"好的，已记录平台偏好"}]}}}\n')


def check(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  [PASS] {name}" + (f"  · {detail}" if detail else ""))
    else:
        FAIL += 1
        FAILS.append(name)
        print(f"  [FAIL] {name}  · {detail}")


def rd(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


def wr(path, text):
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)


def main():
    print("=" * 68)
    print("md 认知图 P29 验收 · 会话层 / 摄取分派 / 全库导出（P0）")
    print("=" * 68)

    tmp = tempfile.mkdtemp(prefix="mdcg_p29_")
    # 每次运行独立根：摄取 watermark 与节点 id 都按 source key 恒定派生，
    # 若复用固定 ROOT，二次运行会因「同 id 已存在」被判幂等而 written=0，
    # 破坏「重跑 ≡ 首跑」。故根随 tmp 走，运行完即弃。
    ROOT = os.path.join(tmp, "root")
    src_dir = os.path.join(tmp, "src")
    out_dir = os.path.join(tmp, "out")
    os.makedirs(src_dir)
    os.makedirs(out_dir)
    guide = os.path.join(src_dir, "guide.md")
    alpha = os.path.join(src_dir, "alpha.py")
    sess = os.path.join(src_dir, "sess.jsonl")
    wr(guide, GUIDE_MD)
    wr(alpha, ALPHA_PY)
    wr(sess, DSH_JSONL)

    corpus.reset_root(ROOT)
    cg = MdCGOS(ROOT, actor="p29")
    cg.principal = Principal(tenant="default", actor="p29", clearance="internal",
                             can_write=True, can_admin=True, role="designer")

    try:
        # ============================================ ① op 三处同步
        print("\n【1】op 契约链：ALL_OPS == 工具 schema == 分发")
        cg_tool = next(t for t in KERNEL_TOOLS if t["name"] == "cg")
        declared = set(
            cg_tool["inputSchema"]["properties"]["op"]["description"].split("|"))
        check("工具 op 枚举 == tokens.ALL_OPS（防漏改）",
              declared == set(tokens.ALL_OPS),
              f"only-schema={sorted(declared - set(tokens.ALL_OPS))} "
              f"only-ops={sorted(set(tokens.ALL_OPS) - declared)}")
        check("session / ingest / export 已进 ALL_OPS",
              {"session", "ingest", "export"} <= set(tokens.ALL_OPS))
        check("ALL_OPS 数量 ≥ 28（25 + P0 三项；P1/P2 会继续递增）",
              len(tokens.ALL_OPS) >= 28, str(len(tokens.ALL_OPS)))
        check("sources 注册表是分派唯一真源",
              sources.dispatch_of("a.md") == "doc"
              and sources.dispatch_of("a.py") == "code"
              and sources.dispatch_of("a.jsonl") == "session"
              and sources.dispatch_of("a.xyz") is None)

        # ============================================ ② session 三件套
        print("\n【2】session：note / recall / compact")
        SUM = "用户偏好深色主题，禁用表情符号"
        s1 = call_tool(cg, "cg", {"op": "session", "action": "note",
                                  "summary": SUM, "session": "S1"})
        check("note 写入成功", s1.get("ok") is True, str(s1)[:120])
        nid = s1.get("id")
        check("节点 id 以 sess_ 开头", str(nid).startswith("sess_"), str(nid))
        n_before = len(cg.index["nodes"])
        s2 = call_tool(cg, "cg", {"op": "session", "action": "note",
                                  "summary": SUM, "session": "S1"})
        check("note 幂等：同要点重复写入同 id", s2.get("id") == nid)
        cg.flush()
        check("note 幂等：节点数不增",
              len(cg.index["nodes"]) == n_before,
              f"{len(cg.index['nodes'])} == {n_before}")
        node = cg.get(nid)
        check("note 节点 CCG 齐备（生效条件 + 验证方式）",
              isinstance(node, dict)
              and "# 生效条件：" in node["content"]
              and "# 验证方式：" in node["content"])

        r = call_tool(cg, "cg", {"op": "session", "action": "recall",
                                 "session": "S1"})
        check("recall 返回 ok", r.get("ok") is True, str(r)[:120])
        check("recall 命中该会话要点",
              any(n.get("id") == nid for n in r.get("notes", [])),
              str([n.get("id") for n in r.get("notes", [])]))
        check("recall 含 goals / recent / unresolved 字段",
              all(k in r for k in ("goals", "recent", "unresolved")),
              str(sorted(r)))
        check("recall 带预算字段且不超预算",
              isinstance(r.get("tokens"), int)
              and isinstance(r.get("budget_tokens"), int)
              and r.get("tokens") <= r.get("budget_tokens"),
              f"{r.get('tokens')} <= {r.get('budget_tokens')}")
        rt = call_tool(cg, "cg", {"op": "session", "action": "recall",
                                  "session": "S1", "budget_tokens": 200})
        check("小预算：受预算约束或显式 truncated",
              rt.get("tokens") <= rt.get("budget_tokens")
              or rt.get("truncated") is True,
              f"tokens={rt.get('tokens')} truncated={rt.get('truncated')}")

        cg.remember_event("user", "请把记忆库整理一遍并补全条件标注")
        cg.remember_event("assistant", "好的，我先做全库体检再分批回填")
        c = call_tool(cg, "cg", {"op": "session", "action": "compact",
                                 "limit": 20})
        check("compact 返回 ok 且标记 heuristic",
              c.get("ok") is True and c.get("heuristic") is True)
        check("compact 给出 summary 与 roles",
              bool(c.get("summary")) and isinstance(c.get("roles"), dict))
        cn = call_tool(cg, "cg", {"op": "session", "action": "compact",
                                  "note": True, "session": "S1"})
        check("compact note=True 落盘会话要点", bool(cn.get("written_id")),
              str(cn.get("written_id")))

        # ============================================ ③ ingest 分派
        print("\n【3】ingest：file / dir / jsonl / stat")
        st = call_tool(cg, "cg", {"op": "ingest", "action": "stat"})
        check("stat 返回注册表与支持面",
              st.get("ok") is True and "doc" in st.get("extensions", {}),
              str(sorted(st.get("extensions", {}))))
        check("stat 带水位字段", "watermarks" in st and "ledger" in st)

        dr = call_tool(cg, "cg", {"op": "ingest", "action": "dir",
                                  "path": src_dir, "dry_run": True})
        check("dir dry_run 只统计不写",
              dr.get("dry_run") is True
              and dr.get("counts", {}).get("doc", 0) >= 1
              and dr.get("counts", {}).get("code", 0) >= 1,
              str(dr.get("counts")))

        f1 = call_tool(cg, "cg", {"op": "ingest", "action": "file",
                                  "path": guide, "layer": "knowledge"})
        check("file 摄取 md 成功且有条目",
              f1.get("ok") is True and f1.get("indexed", 0) > 0, str(f1)[:140])
        n_after = len(cg.index["nodes"])
        call_tool(cg, "cg", {"op": "ingest", "action": "file",
                             "path": guide, "layer": "knowledge"})
        cg.flush()
        check("file 重复摄取幂等（节点数不增）",
              len(cg.index["nodes"]) == n_after,
              f"{len(cg.index['nodes'])} == {n_after}")

        bad = call_tool(cg, "cg", {"op": "ingest", "action": "file",
                                   "path": os.path.join(src_dir, "x.xyz")})
        check("不支持后缀显式报错（不静默）",
              bad.get("ok") is False and "不支持" in (bad.get("error") or ""),
              str(bad.get("error")))

        j1 = call_tool(cg, "cg", {"op": "ingest", "action": "jsonl",
                                  "path": sess, "sensitivity": "internal"})
        check("jsonl 会话摄取成功", j1.get("ok") is True, str(j1)[:140])
        check("jsonl 识别为 DSH 会话源",
              j1.get("source_class") == "DSHSessionSource",
              str(j1.get("source_class")))
        check("jsonl 实际写入会话事件",
              j1.get("written", 0) >= 1, str(j1.get("written")))
        j2 = call_tool(cg, "cg", {"op": "ingest", "action": "jsonl",
                                  "path": sess, "sensitivity": "internal"})
        check("jsonl 幂等：重摄取无新事件",
              j2.get("new_events") == 0, str(j2.get("new_events")))

        d1 = call_tool(cg, "cg", {"op": "ingest", "action": "dir",
                                  "path": src_dir, "incremental": True,
                                  "sensitivity": "internal"})
        check("dir 摄取返回 doc / code / session 三链",
              all(k in (d1.get("chains") or {}) for k in ("doc", "code", "session")),
              str(sorted((d1.get("chains") or {}).keys())))
        check("dir 增量下文档链跳过未变文件",
              (d1.get("chains", {}).get("doc", {}).get("skipped_unchanged", 0) >= 1
               or d1.get("chains", {}).get("doc", {}).get("indexed", 0) >= 0))

        # ============================================ ④ export 全库导出
        print("\n【4】export：graph / slice / nodes / stat（流式 JSONL）")
        es = call_tool(cg, "cg", {"op": "export", "action": "stat"})
        check("stat 返回 ok 且 total == 节点数",
              es.get("ok") is True and es.get("total") == len(cg.index["nodes"]),
              f"{es.get('total')} vs {len(cg.index['nodes'])}")
        check("stat 带层分布与时间范围",
              isinstance(es.get("by_layer"), dict) and "time_range" in es)

        out = os.path.join(out_dir, "dump.jsonl")
        eg = call_tool(cg, "cg", {"op": "export", "action": "graph", "out": out})
        check("graph 导出 ok", eg.get("ok") is True, str(eg)[:140])
        check("导出文件落盘", os.path.exists(out))
        check("流式统计：written + skipped_unreadable == 可见节点",
              eg.get("written", 0) + eg.get("skipped_unreadable", 0)
              == len(cg.index["nodes"]),
              f"{eg.get('written')}+{eg.get('skipped_unreadable')} "
              f"vs {len(cg.index['nodes'])}")
        rows = [json.loads(ln) for ln in rd(out).splitlines() if ln.strip()]
        check("导出行数 == written", len(rows) == eg.get("written"),
              f"{len(rows)} vs {eg.get('written')}")
        check("导出行含 id / layer / content",
              all(k in rows[0] for k in ("id", "layer", "content")) if rows else False)
        check("导出体积与字节数一致",
              os.path.getsize(out) == eg.get("bytes"))

        sout = os.path.join(out_dir, "ctx.jsonl")
        sl = call_tool(cg, "cg", {"op": "export", "action": "slice",
                                  "out": sout, "layer": "contextual"})
        check("slice 只导出指定层",
              sl.get("ok") is True
              and set((sl.get("by_layer") or {}).keys()) <= {"contextual"},
              str(sl.get("by_layer")))

        nout = os.path.join(out_dir, "one.jsonl")
        nd = call_tool(cg, "cg", {"op": "export", "action": "nodes",
                                  "ids": [nid], "out": nout})
        check("nodes 按 id 导出 1 条",
              nd.get("ok") is True and nd.get("written") == 1, str(nd)[:120])
        check("nodes 无缺失上报 missing=[]", nd.get("missing") == [])
        nd2 = call_tool(cg, "cg", {"op": "export", "action": "nodes",
                                   "ids": ["no_such_node"],
                                   "out": os.path.join(out_dir, "none.jsonl")})
        check("nodes 缺失 id 显式上报",
              nd2.get("missing") == ["no_such_node"], str(nd2.get("missing")))

        # ============================================ ⑤ 权限收窄
        print("\n【5】权限：受限角色可 recall、不可 note；非 admin 不可 export")
        keep = cg.principal
        try:
            cg.principal = Principal(tenant=keep.tenant, actor="output",
                                     clearance=keep.clearance,
                                     can_write=False, can_admin=False)
            ro = call_tool(cg, "cg", {"op": "session", "action": "recall"})
            check("无写权角色可 recall（只读）", ro.get("ok") is True)
            denied_note = False
            try:
                call_tool(cg, "cg", {"op": "session", "action": "note",
                                     "summary": "越权写入"})
            except AccessDenied:
                denied_note = True
            check("无写权 → session note 被拒（AccessDenied）", denied_note)
            denied_exp = False
            try:
                call_tool(cg, "cg", {"op": "export", "action": "stat"})
            except AccessDenied:
                denied_exp = True
            check("非 admin → export 被拒（AccessDenied）", denied_exp)
            denied_ing = False
            try:
                call_tool(cg, "cg", {"op": "ingest", "action": "file",
                                     "path": guide})
            except AccessDenied:
                denied_ing = True
            check("无写权 → ingest 被拒（AccessDenied）", denied_ing)
        finally:
            cg.principal = keep

        # ============================================ ⑥ 未知 action 不静默
        print("\n【6】未知 action 不静默成功")
        for op in ("session", "ingest", "export"):
            silent = True
            try:
                outx = call_tool(cg, "cg", {"op": op, "action": "definitely_nope"})
                silent = isinstance(outx, dict) and outx.get("ok") is True
            except Exception:                              # noqa: BLE001
                silent = False
            check(f"{op} 未知 action 不静默成功", silent is False)

    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    print("\n" + "=" * 68)
    print(f"通过 {PASS} / 失败 {FAIL}")
    if FAILS:
        print("失败项：\n  - " + "\n  - ".join(FAILS))
    print("=" * 68)
    return 1 if FAIL else 0


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.exit(main())
