# -*- coding: utf-8 -*-
"""P2（六要素 6 行索引 / 拒绝域双语义）+ P4（权重刷新与衰减）**可复算探针**。

同一命令在**改前树**（HEAD worktree）与**改后树**（当前工作区）上都能跑，
逐条输出读数，供「变了多少、为什么变」归因（设计稿 §5.4 / §7.2 / §〇.3-15）。

只使用**两侧都存在**的公开面（`MdCG` / `MdCGOS.search_rrf` /
`mcp_server._dispatch` / `MdCG._score` / `MdCG.judge_with_boundary` /
`nodefile.dumps`），故改后新增的 `MDCG_FRESHNESS_NOW` 等开关在改前树上被忽略
（正是要看的读数差）；本脚本**不 import 任何本批新增模块**，改前树上不炸。

用法：
    python -X utf8 scripts/p2p4_probe.py                 # 人读
    python -X utf8 scripts/p2p4_probe.py --json-out out.json   # 落盘

退出码：0 = 探针跑完（读数不判绿红——绿红由守卫判）。
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sys
import tempfile
import time

_HERE = os.path.dirname(os.path.abspath(__file__))
_REPO = os.path.dirname(_HERE)
if _REPO not in sys.path:
    sys.path.insert(0, _REPO)

# ── 隔离前置（必须在 import md_cg 子模块之前）：绝不触真实 ~/.mdcg 密钥面 ──
_TMP0 = tempfile.mkdtemp(prefix="p2p4_probe_iso_")
os.environ["MDCG_AUX_ROOT"] = os.path.join(_TMP0, "auxroot")
os.environ["MDCG_MASTER_KEY"] = "ab" * 32
os.environ["MDCG_TOKEN_FILE"] = os.path.join(_TMP0, "tokens.json")
os.environ["MDCG_ROOT"] = os.path.join(_TMP0, "cgroot")
for _k in ("MDCG_TOKEN", "MDCG_TENANT", "MDCG_CLEARANCE", "MDCG_SESSION",
           "MDCG_LEGACY_ENV_AUTH", "MDCG_LEGACY_ENV_ADMIN", "MDCG_CAN_ADMIN",
           "MDCG_CAN_WRITE", "MDCG_STATE_ROOT", "MDCG_DATA_ROOT",
           "MDCG_RETRIEVAL_PIPELINE", "MDCG_POOLING"):
    os.environ.pop(_k, None)

from md_cg import nodefile                        # noqa: E402
from md_cg.fsutil import atomic_write             # noqa: E402
from md_cg.mdcg import MdCG, bigrams, normalize_en  # noqa: E402
from md_cg.mdcos import MdCGOS                    # noqa: E402

#: 固定时间基准（不依赖 wall clock → 两侧可逐位比对）
REF = 1_800_000_000.0
DAY = 86400.0


def _body(nid, extra=""):
    return (f"# 功能名：{nid}\n"
            f"# 生效条件：无条件\n"
            f"# 子功能：无\n"
            f"# 执行：{extra or '无'}\n"
            f"# 验证方式：compiler test 复现\n"
            f"# 不适用条件：其它会话 无关查询\n\n{nid} 正文 苹果 章节\n")


#: 受控正文模板（R5：正文尾部单独给定，控制词面同构度）
_CCG = ("# 功能名：{n}\n# 生效条件：无条件\n# 子功能：无\n"
        "# 执行：占位\n# 验证方式：compiler 复现\n"
        "# 不适用条件：其它会话 无关查询\n\n{t}\n")


def _mk(root, nid, fm_extra=None, body=None, layer="knowledge"):
    fm = {"id": nid, "layer": layer, "created_at": REF,
          # 与写入面 `add()` 同口径：CCG `# 不适用条件：` 行结构化进 fm
          "non_applicable_conditions": ["其它会话", "无关查询"]}
    fm.update(fm_extra or {})
    d = os.path.join(root, layer)
    os.makedirs(d, exist_ok=True)
    atomic_write(os.path.join(d, nid + ".md"),
                 nodefile.dumps(fm, body if body is not None else _body(nid)))


def _corpus(root):
    """确定性小库：两节点六要素齐全，仅 access/created_at 不同。"""
    _mk(root, "k_new", {"access_count": 40, "last_access": REF,
                        "importance": 0.8},
        body=_body("k_new", "无"))
    _mk(root, "k_old", {"access_count": 0, "last_access": 0,
                        "importance": 0.8, "created_at": REF - 300 * DAY},
        body=_body("k_old", "无"))


def _hash_tree(root):
    h = hashlib.sha256()
    for dirpath, dirs, files in os.walk(root):
        dirs.sort()
        for fn in sorted(files):
            if fn.startswith("_") or fn.endswith(".lock"):
                continue
            p = os.path.join(dirpath, fn)
            h.update(os.path.relpath(p, root).replace("\\", "/").encode())
            with open(p, "rb") as f:
                h.update(f.read())
    return h.hexdigest()[:16]


def _entry(root, nid="k_new"):
    cg = MdCG(root)
    e = dict((cg.index.get("nodes") or {}).get(nid) or {})
    cg.close()
    return e


def probe():
    tmp = tempfile.mkdtemp(prefix="p2p4_probe_")
    out = {}
    try:
        os.environ["MDCG_FRESHNESS_NOW"] = repr(REF)   # 改前树忽略（无该读取点）
        # ── R1 索引条目：六要素后两行的索引键 / P4 两个访问计数键 ─────────
        r1 = os.path.join(tmp, "r1")
        _corpus(r1)
        e1 = _entry(r1)
        out["R1_entry_keys_新增键存在"] = {
            k: (k in e1) for k in ("postcondition_terms", "rejection_terms",
                                   "access_count", "last_access")}
        out["R1_entry_keys_值"] = {
            k: e1.get(k) for k in ("postcondition_terms", "rejection_terms",
                                   "access_count", "last_access",
                                   "created_at", "importance", "protected")}
        out["R1_entry_key_n"] = len(e1)

        # ── R2 边界问句的默认召回（六要素第 6 行进默认检索）───────────────
        cg = MdCGOS(r1)
        res2, meta2 = cg.search_rrf("什么条件下不适用", k=5, record=False)
        out["R2_boundary_query_top"] = [[r[0].get("id"), round(float(r[1]), 6),
                                        bool(r[0].get("boundary_hit"))]
                                        for r in res2]
        out["R2_meta_boundary"] = meta2.get("boundary")
        out["R2_meta_paths"] = meta2.get("paths")
        # 验证方式问句（六要素第 5 行）
        res2b, meta2b = cg.search_rrf("怎么验证的 用什么方法证明", k=5,
                                      record=False)
        out["R2b_postcond_query_top"] = [[r[0].get("id"), round(float(r[1]), 6)]
                                         for r in res2b]
        # 普通问句（负条件不得成为召回键——对照面）
        res2c, _ = cg.search_rrf("其它会话 无关查询", k=5, record=False)
        out["R2c_ordinary_query_top"] = [r[0].get("id") for r in res2c]
        cg.close()

        # ── R3 拒绝域双语义：同一节点既边界命中、又未被资格 REJECT ────────
        cg3 = MdCG(r1)
        nd = cg3.get("k_new")
        jb = MdCG.judge_with_boundary(nd, "什么条件下不适用", None)
        out["R3_dual"] = {"qualification": jb["qualification"]["state"],
                          "boundary_hit": jb["boundary"]["hit"],
                          "marker": jb["boundary"]["marker"],
                          "recallable": jb["recallable"],
                          "counts": jb["counts"]}
        # 边界问句**自身携带**拒绝域词面（自否定靶区）：应为「边界命中 ∧ 非 REJECT」
        jb_q = MdCG.judge_with_boundary(nd, "什么条件下不适用 其它会话", None)
        out["R3_dual_query_terms"] = {
            "qualification": jb_q["qualification"]["state"],
            "boundary_hit": jb_q["boundary"]["hit"],
            "recallable": jb_q["recallable"],
            "counts": jb_q["counts"]}
        # 情境**本身**落在拒绝域（非边界问句；灵敏度不得变）：应为 REJECT
        jb2 = MdCG.judge_with_boundary(nd, "刚才在干什么", {"scene": "其它会话"})
        out["R3_dual_scene"] = {"qualification": jb2["qualification"]["state"],
                                "boundary_hit": jb2["boundary"]["hit"],
                                "recallable": jb2["recallable"],
                                "counts": jb2["counts"]}
        cg3.close()

        # ── R4 重建协议：幂等 / 源面逐字节不变 / 合法次序逐位不变 ─────────
        cg4 = MdCGOS(r1)
        r4a, m4a = cg4.search_rrf("苹果 章节", k=5, record=False)
        seq_a = [(r[0].get("id"), round(float(r[1]), 6)) for r in r4a]
        fp_a = (cg4.index.get("_fingerprint"))
        src_a = _hash_tree(r1)
        cg4.rebuild_index()
        fp_b = (cg4.index.get("_fingerprint"))
        src_b = _hash_tree(r1)
        r4b, _ = cg4.search_rrf("苹果 章节", k=5, record=False)
        seq_b = [(r[0].get("id"), round(float(r[1]), 6)) for r in r4b]
        out["R4_rebuild"] = {"fp_before": fp_a, "fp_after": fp_b,
                             "fp_equal": fp_a == fp_b,
                             "src_hash_before": src_a, "src_hash_after": src_b,
                             "src_bytes_equal": src_a == src_b,
                             "seq_before": seq_a, "seq_after": seq_b,
                             "seq_equal": seq_a == seq_b}
        cg4.close()

        # ── R5 默认 recall 的融合口径（sum vs max vs 默认）────────────────
        # 语料构造成「两路共识 vs 单路更好名次」——sum 奖励共识、max 只认最好名次，
        # 两口径的 top-k 序列在此分开。
        r5 = os.path.join(tmp, "r5")
        # 受控语料：entity 路只认 m_zz/m_aa（tags）；lexical 路按同构度排
        # m_lex > m_zz > m_aa（legacy 口径：|qb∩db|/|qb|）。
        _mk(r5, "m_aa", {"tags": ["苹果"], "importance": 0.5},
            body=_CCG.format(n="m_aa", t="苹果 别的内容 章节 分离"))
        _mk(r5, "m_zz", {"tags": ["苹果"], "importance": 0.9},
            body=_CCG.format(n="m_zz", t="苹果 别的内容 章节 分离"))
        _mk(r5, "m_lex", {"tags": [], "importance": 0.5},
            body=_CCG.format(n="m_lex", t="苹果章节 同构"))
        _mk(r5, "m_other", {"tags": [], "importance": 0.5},
            body=_CCG.format(n="m_other", t="苹果 别的内容 章节 分离 更多"))
        cg5 = MdCGOS(r5)
        from md_cg import mcp_server as MS
        fuses = {}
        for tag, arg in (("default", {}), ("sum", {"fusion": "sum"}),
                         ("max", {"fusion": "max"})):
            pack = MS._dispatch(cg5, "mdcg_recall",
                                dict({"query": "苹果 章节", "k": 5}, **arg))
            meta5 = pack.get("meta") or {}
            fuses[tag] = {"top": [[it.get("id"), it.get("score")]
                                  for it in (pack.get("pack") or [])],
                          "paths": meta5.get("paths")}
        out["R5_fusion"] = fuses
        # 显式两路（lexical+entity）下的 sum/max 对照：口径差的最纯读数
        for tag, fu in (("sum", "sum"), ("max", "max")):
            r5r, m5r = cg5.search_rrf("苹果 章节", k=5, record=False,
                                      paths=("lexical", "entity"), fusion=fu)
            out[f"R5_two_paths_{tag}"] = [[x[0].get("id"), round(float(x[1]), 6)]
                                          for x in r5r]
        cg5.close()

        # ── R6 权重乘子：同内容、仅访问/时刻不同的两节点的词法分 ──────────
        cg6 = MdCG(r1)
        docs = [({"path": "knowledge/k_new.md"},
                 {"id": "k_new", "tags": [], "access_count": 40,
                  "last_access": REF, "created_at": REF, "importance": 0.8},
                 _body("k_new")),
                ({"path": "knowledge/k_old.md"},
                 {"id": "k_old", "tags": [], "access_count": 0,
                  "last_access": 0, "created_at": REF - 300 * DAY,
                  "importance": 0.8},
                 _body("k_old"))]
        scored = cg6._score(docs, "苹果 章节", bigrams(normalize_en("苹果 章节")))
        out["R6_score"] = [[d["id"], round(float(s), 9)] for d, s in scored]
        out["R6_ratio"] = (round(float(scored[0][1] / scored[1][1]), 9)
                           if scored[1][1] else None)
        # protected 节点的衰减不得穿过保护线
        docs_p = [(docs[0][0], dict(docs[0][1]), docs[0][2])]
        docs_p[0][1]["protected"] = True
        out["R6_protected_score"] = [
            [d["id"], round(float(s), 9)]
            for d, s in cg6._score(docs_p, "苹果 章节",
                                   bigrams(normalize_en("苹果 章节")))]
        cg6.close()

        # ── R8 默认召回在「新/旧同内容节点」上的排序（衰减幅度读数）────────
        r8 = os.path.join(tmp, "r8")
        for nid, age, imp in (("a_fresh", 0.0, 0.5), ("b_30d", 30.0, 0.6),
                              ("c_300d", 300.0, 0.9)):
            _mk(r8, nid, {"created_at": REF - age * DAY, "importance": imp,
                          "access_count": 0, "last_access": 0},
                body=_body(nid, "无"))
        cg8 = MdCGOS(r8)
        r8r, m8r = cg8.search_rrf("苹果 章节", k=5, record=False)
        out["R8_age_order"] = [[x[0].get("id"), round(float(x[1]), 6)]
                               for x in r8r]
        cg8.close()

        # ── R7 S3/因果路的邻接构建代价（P3 遗留 B⑥ 的代价读数）───────────
        r7 = os.path.join(tmp, "r7")
        os.makedirs(os.path.join(r7, "knowledge"), exist_ok=True)
        N = 400
        for i in range(N):
            _mk(r7, f"n{i:04d}",
                {"edges": [{"target": f"n{(i + 1) % N:04d}",
                            "relation_type": "causal"}]})
        cg7 = MdCG(r7)
        from md_cg import chain as _chain
        cg7._chain_adj = None
        t0 = time.perf_counter()
        adj = _chain.adjacency(cg7)
        t1 = time.perf_counter()
        t2 = time.perf_counter()                   # 第二次：缓存命中
        adj2 = _chain.adjacency(cg7)
        t3 = time.perf_counter()
        out["R7_chain_adj"] = {"entries": len(cg7.index.get("nodes") or {}),
                               "adj_src": len(adj),
                               "cold_s": round(t1 - t0, 6),
                               "cached_s": round(t3 - t2, 6),
                               "adj2_is_same_object": adj2 is adj}
        cg7.close()
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
        os.environ.pop("MDCG_FRESHNESS_NOW", None)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--json-out", default=None)
    a = ap.parse_args()
    out = probe()
    out["_head"] = _repo_head()
    text = json.dumps(out, ensure_ascii=False, sort_keys=True, indent=1)
    if a.json_out:
        with open(a.json_out, "w", encoding="utf-8") as f:
            f.write(text + "\n")
    print(text)
    return 0


def _repo_head():
    import subprocess
    try:
        p = subprocess.run(["git", "-C", _REPO, "rev-parse", "HEAD"],
                           capture_output=True, text=True, encoding="utf-8")
        return p.stdout.strip()
    except Exception:                       # noqa: BLE001
        return None


if __name__ == "__main__":
    sys.exit(main())
