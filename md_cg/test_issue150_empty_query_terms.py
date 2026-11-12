# -*- coding: utf-8 -*-
r"""#150 跨侧守卫：空查询词项 / 空 tag **不得**使 LIKE 与 tag_bonus 恒真。

缺陷（本件修复，2026-10-11）
--------------------------
全标点/空白 query 经 \`normalize_en\` 归一后为 \`""\`，\`expand_query_terms\` 仍把它
当词项返回 ⇒ 下游 \`t in body_l\` 因 \`"" in s\` **恒真** ⇒ LIKE 预筛恒真、全库入池
（实测 q="???" 命中全库 6/6）。同族四处：\`expand_query_terms\` / \`_like\` /
\`tag_bonus\`（空 tag 与空 q 各一侧）/ 负覆盖判据；写入侧 \`add()\` 的空 tag 同源。
**Rust 侧同款两处**（\`retrieval.rs::like\` 与 \`tag_bonus\`）——修前 Rust 注释
**显式保留**该行为以对齐 Python（「不做空串过滤」），故必须两侧同步。

本守卫三层
----------
  [A] Python 面：五处过滤逐一断言（空词项不出现在 terms；\`_like\`/负覆盖不再恒真；
      \`tag_bonus\` 空 tag/空 q 为 0；\`add()\` 落库前滤掉空 tag）
  [B] **跨侧面**：同一语料「含空 tag」vs「不含空 tag」，**两侧都必须不翻转**，
      且两档读数**逐位一致**（Python \`search_rrf\` vs Rust \`mdcg-eval --serve\`）
  [C] 定点变异：白名单式回退（把过滤拆掉）必须让判据转红

运行：python -X utf8 -m md_cg.test_issue150_empty_query_terms
      python -X utf8 -m md_cg.test_issue150_empty_query_terms --mutate
退出码：0 全绿 / 1 有失败
（Rust 二进制缺失时**fail-closed 退出 1**——与既有 \`test_rank_parity_score_mode.py\`
 同款：不把「没测到」记成绿。构建命令见下方打印。）
"""
from __future__ import annotations

import argparse
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile

from . import mdcg as M
from .mdcos import MdCGOS

PASS = FAIL = 0
FAILS = []
_SANDBOXES = []
#: 变异自证用：_SILENT 为真时 check() 只把**失败项**记进 _VIOL，不计入 PASS/FAIL、
#: 不打印——否则变异引起的红会污染套件读数（本守卫首版即踩此坑）。
_SILENT = False
_VIOL = []

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
#: Rust 对拍二进制路径。**后缀按平台取**——`mdcg-eval` 在 unix 上无 `.exe`（cargo 只在
#: Windows 追加后缀）。本守卫首版硬编码 `mdcg-eval.exe`，于是 Linux CI 上 B0 恒报
#: 「二进制缺失」⇒ 整件 rc=1，跨侧面 [B] 组一条都跑不到。平台差不是被测缺陷，是**量具
#: 缺陷**（本仓既有口径：`scripts/rank_parity.py` / `md_cg/test_unify_default_off.py`
#: 同款按 `os.name` 取后缀）。
_EXE = os.path.join(_REPO, "rust", "target", "release",
                    "mdcg-eval.exe" if os.name == "nt" else "mdcg-eval")
_Q = "蜂群调度器 workers 领取任务"
_BODY = ("# 功能名：比对样本" + chr(10) + "# 正文：蜂群调度器按 workers 上限领取任务。")


def check(name, cond, detail=""):
    global PASS, FAIL
    if _SILENT:
        if not cond:
            _VIOL.append(name)
        return bool(cond)
    if cond:
        PASS += 1
        print("  [PASS] %s%s" % (name, ("  · " + str(detail)) if detail else ""))
    else:
        FAIL += 1
        FAILS.append(name)
        print("  [FAIL] %s  · %s" % (name, detail))
    return bool(cond)


# 生效条件：tags 为节点标签列表；在 tempfile 沙箱建两节点同正文库（探针节点带
# 指定 tags、对照节点带干净标签），返回 (root, graph_dir)。
def _mk(tags):
    t = tempfile.mkdtemp(prefix="i150g_")
    _SANDBOXES.append(t)
    g = os.path.join(t, "graph")
    os.makedirs(g, exist_ok=True)
    os.environ.update(MDCG_ROOT=g, MDCG_NODE_ID="node-guard",
                      MDCG_MASTER_KEY=os.urandom(32).hex())
    cg = MdCGOS(g)
    cg.add("probe_node", _BODY, layer="knowledge", tags=list(tags))
    cg.add("other_node", _BODY, layer="knowledge", tags=["标签Z"])
    cg.flush()
    cg.close()
    return t, g


# 生效条件：无入参；返回 Python 侧 (probe 分数, other 分数) —— 经 search_rrf 融合面。
def _py_pair(g):
    cg = MdCGOS(g)
    rows, _m = cg.search_rrf(_Q, k=10)
    out = {r[0]["id"]: round(r[1], 6) for r in rows}
    cg.close()
    return out.get("probe_node"), out.get("other_node")


# 生效条件：无入参；拉起 Rust serve（每个请求独立进程，规避管道 EOF），返回同样两值。
def _rust_pair(g):
    env = dict(os.environ)
    env["MDCG_EN_ZH_MAP"] = os.path.join(_REPO, "md_cg", "semantic", "en_zh_map.json")
    env.pop("MDCG_TOKEN", None)
    p = subprocess.Popen([_EXE, "--root", g, "--serve", "--score", "jaccard"],
                         stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                         stderr=subprocess.PIPE, text=True, encoding="utf-8", env=env)
    try:
        p.stdin.write(json.dumps({"op": "search", "query": _Q, "k": 10}) + "\n")
        p.stdin.flush()
        line = p.stdout.readline()
        resp = json.loads(line) if line else {}
    finally:
        try:
            p.stdin.close()
        except Exception:                                  # noqa: BLE001
            pass
        try:
            p.wait(timeout=10)
        except Exception:                                  # noqa: BLE001
            p.kill()
    hits = {h.get("id"): h.get("score") for h in (resp.get("hits") or [])}
    return hits.get("probe_node"), hits.get("other_node")


def _python_face():
    """[A] Python 五处过滤。"""
    check("A1 全标点 query 不再产出空词项",
          "" not in M.expand_query_terms("???"), M.expand_query_terms("???"))
    check("A1b 纯空白 query 不再产出空词项",
          "" not in M.expand_query_terms("   "), M.expand_query_terms("   "))
    check("A1c 正常 query 词项不变（零误伤）",
          M.expand_query_terms("跨节点证据")[:1] == ["跨节点证据"],
          M.expand_query_terms("跨节点证据")[:3])
    check("A2 _like 对空词项不再恒真",
          M.MdCG._like("任意正文内容", {"tags": []}, [""]) is False)
    check("A2b _like 空词项混入非空词项仍不恒真",
          M.MdCG._like("无关正文", {"tags": []}, ["", "证据"]) is False)
    check("A2c _like 正常词项仍命中（零误伤）",
          M.MdCG._like("跨节点证据交换", {"tags": []}, ["证据"]) is True)
    t, g = _mk(["", "标签A"])
    try:
        cg = MdCGOS(g)
        fm = cg.index["nodes"]["probe_node"]
        tags = list(fm.get("tags") or [])
        check("A5 add() 入口滤掉空 tag（落库 tags 无空串）",
              "" not in tags, tags)
        cg.close()
    finally:
        pass
    return t, g


def _tag_bonus_face():
    """[A3/A4] tag_bonus 与负覆盖。"""
    fm_empty = {"tags": ["", "标签A"], "id": "x", "importance": 0.5}
    docs = [(None, fm_empty, _BODY)]
    cg = None
    try:
        t, g = _mk(["标签A"])
        cg = MdCGOS(g)
        # 直接构造 _score 的入参三元组（entry 必须带 path —— readcache 取 bigram 用）
        # 索引条目**不带 id 键**（index["nodes"] 以 node_id 为键）——必须按键取，
        # 首版按 e.get("id") 过滤 ⇒ 空列表 ⇒ IndexError（本守卫自身缺陷，已修）。
        e0 = cg.index["nodes"]["probe_node"]
        # 不读盘：_score 只需要 entry（取 path 算 bigram）+ fm（取 tags）+ content 文本，
        # 三者都可直接构造 —— 这样 A3 只随 tags 变化（隔离 P3 语义）。
        fm0 = {"id": "probe_node", "tags": ["标签A"]}
        c0 = _BODY
        q = "完全无关的ZQX问句"
        qb = M.bigrams(M.normalize_en(q))
        raw_clean = M.MdCG._score(cg, [(e0, dict(fm0), c0)], q, qb)[0][1]
        fm_bad = dict(fm0)
        fm_bad["tags"] = ["", "标签A"]
        raw_bad = M.MdCG._score(cg, [(e0, fm_bad, c0)], q, qb)[0][1]
        check("A3 无关问句下：空 tag 与干净 tag 原始分相同（空 tag 不再白拿 0.05）",
              raw_clean is not None and raw_bad == raw_clean,
              "干净=%s 空tag=%s" % (raw_clean, raw_bad))
        # 负覆盖：空词项不得使全部负层节点算作覆盖
        # 建一个 rejected 层节点作负记忆；空词项修前会让它被算作「覆盖本查询」。
        cg.add("neg_probe", "# 功能名：负记忆样本" + chr(10) + "# 正文：被否决的旧结论ZZQ。",
               layer="rejected", override=True)
        cg.flush()
        cg.close()
        cg = MdCGOS(g)
        _rows, meta_bad = cg.search("???", k=5, include_neg=True)
        _rows2, meta_ok = cg.search("被否决的旧结论ZZQ", k=5, include_neg=True)
        cov_bad = list(meta_bad.get("covered_neg") or [])
        cov_ok = list(meta_ok.get("covered_neg") or [])
        check("A4 空词项/全标点 query 不再把负记忆算作「覆盖本查询」",
              not cov_bad, "covered_neg=%s" % cov_bad)
        check("A4b 正向对照：真正命中负记忆的问句仍照旧覆盖（零误伤）",
              bool(cov_ok), "covered_neg=%s" % cov_ok)
    finally:
        if cg is not None:
            cg.close()


def _cross_face():
    """[B] 跨侧面：含空 tag vs 不含空 tag，两侧都必须不翻转且逐位一致。"""
    if not os.path.isfile(_EXE):
        check("B0 Rust 二进制在位（缺失即 fail-closed）", False,
              "缺 %s —— 请先 `cargo build --release --manifest-path rust/Cargo.toml`"
              "（在 <仓根> 内；CI 的 python-tests 已有该步，见 .github/workflows/"
              "python-tests.yml）" % _EXE)
        return
    ta, ga = _mk(["", "标签A"])
    tb, gb = _mk(["标签A"])
    pa, oa = _py_pair(ga)
    pb, ob = _py_pair(gb)
    ra, r2a = _rust_pair(ga)
    rb, r2b = _rust_pair(gb)
    check("B1 Python：空 tag 不改变排名（两档读数一致）",
          (pa, oa) == (pb, ob), "A=%s B=%s" % ((pa, oa), (pb, ob)))
    check("B2 Rust：空 tag 不改变排名（两档读数一致）",
          (ra, r2a) == (rb, r2b), "A=%s B=%s" % ((ra, r2a), (rb, r2b)))
    check("B3 两侧逐位一致（含空 tag 档）",
          (pa, oa) == (ra, r2a), "py=%s rust=%s" % ((pa, oa), (ra, r2a)))
    check("B4 两侧逐位一致（干净 tag 档）",
          (pb, ob) == (rb, r2b), "py=%s rust=%s" % ((pb, ob), (rb, r2b)))


def _run_all():
    print("[A] Python 五处过滤")
    try:
        _python_face()
    except Exception as exc:                              # noqa: BLE001
        check("A 组异常", False, "%s: %s" % (type(exc).__name__, exc))
    print("[A3/A4] tag_bonus 与负覆盖")
    try:
        _tag_bonus_face()
    except Exception as exc:                              # noqa: BLE001
        check("A3/A4 组异常", False, "%s: %s" % (type(exc).__name__, exc))
    print("[B] 跨侧面")
    try:
        _cross_face()
    except Exception as exc:                              # noqa: BLE001
        check("B 组异常", False, "%s: %s" % (type(exc).__name__, exc))


# 生效条件：无入参；把五处过滤逐一拆掉，断言 [A] 判据转红；返回失败条数。
def _run_mutations():
    print(chr(10) + "=== 定点变异自证（变异前 → 变异后）===")
    keep = (M.expand_query_terms, M.MdCG._like, M.MdCG._score)

    def mut_expand():
        M.expand_query_terms = lambda q: ["", "证据"]

    def mut_like():
        def fake(content, fm, terms, index_keys=None, entry=None,
                 positive_body=None, body_lower=None):
            # 拆掉空词项守卫：不对 t 判空（复现修前语义）
            body = (body_lower(entry, content) if body_lower is not None
                    else content.lower())
            tags = " ".join(str(t) for t in (fm.get("tags") or [])).lower()
            return any(t in body or t.lower() in tags for t in terms)
        M.MdCG._like = staticmethod(fake)

    def mut_score():
        # 定点：只把 P3 的**空 tag 守卫**拆掉（其余逐位保留），复现「空 tag 白拿加成」
        orig = M.MdCG._score

        def fake_score(self, docs, q, qb, pools=None, mode=None):
            out = orig(self, docs, q, qb, pools=pools, mode=mode)
            fixed = []
            for d, s in out:
                if any(not str(t).strip() for t in (d[1].get("tags") or [])):
                    s = min(1.0, s + 0.05)
                fixed.append((d, s))
            return fixed

        M.MdCG._score = fake_score

    cases = (
        ("M1 expand_query_terms 重放空词项（拆掉 P1 过滤）", mut_expand),
        ("M2 _like 去掉空词项守卫（拆掉 P2）", mut_like),
        ("M3 _score 恒发加成（拆掉 P3 语义）", mut_score),
    )
    bad = 0
    for label, inject in cases:
        global _SILENT, _VIOL
        try:
            inject()
            _SILENT = True
            del _VIOL[:]
            try:
                _run_all()
                reds = list(_VIOL)
            except Exception as exc:                      # noqa: BLE001
                reds = ["变异后异常：%s" % type(exc).__name__]
        finally:
            _SILENT = False
            (M.expand_query_terms, M.MdCG._like, M.MdCG._score) = keep
        hit = bool(reds)
        if not check(label, hit, "变异后判据仍全绿 ⇒ 判据无判别力"):
            bad += 1
        print("        变异前：失败项=[] ｜ 变异后：失败项=%d 项 %s ⇒ %s"
              % (len(reds), reds[:2], "命中" if hit else "未命中"))
    print("  变异自证结论：%s" % ("全部按预期转红" if bad == 0
                              else "存在 %d 条未按预期" % bad))
    return bad


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(description="#150 空查询词项跨侧守卫")
    ap.add_argument("--mutate", action="store_true", help="定点变异自证")
    a = ap.parse_args()
    global PASS, FAIL
    PASS = FAIL = 0
    del FAILS[:]
    _run_all()
    base_bad = list(FAILS)
    rc = 1 if base_bad else 0
    if a.mutate:
        rc = 1 if (_run_mutations() or base_bad) else 0
    print(chr(10) + "SUMMARY: #150 空查询词项跨侧守卫：%d 通过，%d 失败%s"
          % (PASS, FAIL, ("；失败项=" + "; ".join(FAILS)) if FAILS else ""))
    for d in _SANDBOXES:
        shutil.rmtree(d, ignore_errors=True)
    return rc


if __name__ == "__main__":
    sys.exit(main())
