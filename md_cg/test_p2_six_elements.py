# -*- coding: utf-8 -*-
"""P2 守卫 · 六要素 6 行索引（§5.1）/ 拒绝域双语义（§5.2）/ 全进默认检索（§5.4）。

覆盖判据（每条对应契约的一项）：

  G1 **六要素那张表从 4 行长成 6 行**：`nodefile.CCG_INDEX_ROLES` 恰 6 行、
      前 4 行 == 理论 `智能论3.4.md:3053-3059` 的 4 行、后 2 行 == 新增的
      「验证方式（后置条件词）/ 不适用条件（拒绝域词）」；6 行字段名集合与
      `nodefile.CCG_MARKS` **同源**（不新造第六个要素名）。
  G2 **取要素文本走既有单点**：`ccg_element_terms` 吃的是
      `ccg_field_value` 的行语义（冒号可有可无、后接行形态），**不是**检索面
      自写的正则——三条行为断言（冒号形态 / 无冒号换行形态 / 缺行）+
      与 `ccg_field_value` 的对拍；并断言词长下限与 `mdcg.NEG_MIN_TERM` 同值。
  G3 **两个键进索引条目**（`_node_entry`，与 `time_window`/`observation_position`
      同为免读文件的扁指标量）：条目含两键且值 == nodefile 单点计算值；
      **写路径（`add`）与重建路径（`rebuild_index`）同口径**。
  G4 **重建协议四条硬约束**（§5.3）：①幂等（`_fingerprint` 对拍 + 两次重建的
      `_index.json` 字节相同）②增量优先（指纹未变时 `_maybe_reload_index`
      不换索引对象）③可回退（源面 .md 逐字节不变）④可对拍（重建前后同查询
      top-k 序列与分数**逐位不变**）。
  G5 **拒绝域双语义**（§5.2，前置必做）：**同一节点**既被边界命中、
      又**未**被资格 REJECT；`boundary_hit` 与资格 REJECT **分开计数**
      （两个独立键）；灵敏度不变（情境真的落在拒绝域 ⇒ 非边界问句照旧 REJECT）。
  G6 **全进默认检索**（§5.4）：默认 `search_rrf` 上，边界问句只召回「声明了
      拒绝域」的节点并打 `boundary_hit`；拒绝域词**不作普通问句的召回键**
      （`positive_body` 的既有立场不变）；`meta["boundary"]` 与
      `meta["judge_filtered"]` 分开呈现。
  G7 **旧库零破坏**：条目缺这两键（未重建的旧索引快照）时 `index_key_hits`
      判 False；`_like` 的三参旧签名行为与改动前一致。

运行：
    python -X utf8 -m md_cg.test_p2_six_elements                  # 正向
    python -X utf8 -m md_cg.test_p2_six_elements --mutate         # 定点变异自证
    python -X utf8 -m md_cg.test_p2_six_elements --mutate --list  # 列出变异

退出码：0 = 全绿；1 = 有断言失败 / 变异未按预期转红；2 = ANCHOR-MISS
（变异锚点在本源码里找不到——实现改了却没同步本表，硬失败不静默跳过）。

硬边界：不动任何在役数据根（库根一律 tempfile）；不 git add/commit/push。
"""
from __future__ import annotations

import hashlib
import json
import os
import sys
import tempfile

# ── 隔离前置：必须在 import md_cg 子模块之前（tokens/theory 等模块级冻 aux_root）──
_TMP0 = tempfile.mkdtemp(prefix="p2_six_")
os.environ["MDCG_AUX_ROOT"] = os.path.join(_TMP0, "auxroot")
os.environ["MDCG_MASTER_KEY"] = "ef" * 32
os.environ["MDCG_TOKEN_FILE"] = os.path.join(_TMP0, "tokens.json")
os.environ["MDCG_ROOT"] = os.path.join(_TMP0, "cgroot")
for _k in ("MDCG_TOKEN", "MDCG_TENANT", "MDCG_CLEARANCE", "MDCG_SESSION",
           "MDCG_RETRIEVAL_PIPELINE", "MDCG_POOLING", "MDCG_FRESHNESS"):
    os.environ.pop(_k, None)

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except AttributeError:
    pass

from md_cg import nodefile                                    # noqa: E402
from md_cg import mdcg as M                                   # noqa: E402
from md_cg.mdcos import MdCGOS                                # noqa: E402

PASS = 0
FAIL = 0
FAILS = []


def check(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  OK   {name}")
    else:
        FAIL += 1
        FAILS.append(name)
        print(f"  FAIL {name}  {detail}")
    return bool(cond)


BODY = ("# 功能名：{n}\n"
        "# 生效条件：无条件\n"
        "# 子功能：无\n"
        "# 执行：占位\n"
        "# 验证方式：compiler test 复现\n"
        "# 不适用条件：{neg}\n\n{t}\n")


#: 不适用条件按 `；` 分条（与写入面 ccgc 的拆分口径同源：每条=一个独立拒绝域条目）
NEG_TWO = "其它会话；无关查询"


def _mk(cg, nid, neg=NEG_TWO, tail=None, **kw):
    cg.add(nid, BODY.format(n=nid, neg=neg, t=tail or f"{nid} 正文 苹果 章节"),
           layer="knowledge", **kw)


def _tree_hash(root):
    h = hashlib.sha256()
    for dirpath, dirs, files in os.walk(root):
        # 派生物/运行态（_index.json / _index_log/ / _access.log …）不入源面对拍
        dirs[:] = sorted(d for d in dirs if not d.startswith("_"))
        for fn in sorted(files):
            if fn.startswith("_"):
                continue
            p = os.path.join(dirpath, fn)
            h.update(os.path.relpath(p, root).replace("\\", "/").encode())
            with open(p, "rb") as f:
                h.update(f.read())
    return h.hexdigest()[:16]


def _corpus(nd=2):
    root = tempfile.mkdtemp(prefix="p2_six_lib_")
    cg = MdCGOS(root)
    if nd >= 1:
        _mk(cg, "k_decl")
    if nd >= 2:
        _mk(cg, "k_nodecl", neg="无")
    cg.flush()
    return root, cg


def g1_table_six_rows():
    print("== G1 六要素表：4 行 → 6 行 ==")
    roles = tuple(nodefile.CCG_INDEX_ROLES)
    check("表恰 6 行", len(roles) == 6, str(len(roles)))
    check("前 4 行 == 理论 4 行",
          [r[0] for r in roles[:4]] == ["功能名", "生效条件", "子功能", "执行"],
          str([r[0] for r in roles[:4]]))
    check("后 2 行 == 新增两要素（验证方式 / 不适用条件）",
          [r[0] for r in roles[4:]] == [nodefile.POSTCONDITION_FIELD,
                                        nodefile.REJECTION_FIELD],
          str([r[0] for r in roles[4:]]))
    check("后 2 行的索引键名 == 条目里的键（单一真源）",
          nodefile.INDEX_TERMS_KEYS == (nodefile.POSTCONDITION_TERMS_KEY,
                                        nodefile.REJECTION_TERMS_KEY),
          str(nodefile.INDEX_TERMS_KEYS))
    check("6 行字段名集合与 CCG_MARKS 同源",
          {r[0] for r in roles} == set(nodefile.CCG_MARKS),
          str({r[0] for r in roles} ^ set(nodefile.CCG_MARKS)))
    check("每行的索引键列非空", all(str(r[1]).strip() for r in roles))


def g2_single_parse_point():
    print("== G2 取要素文本：走既有单点（非检索面自写正则）==")
    colon = "# 功能名：x\n# 验证方式：compiler test 复现\n# 不适用条件：其它会话 无关查询\n"
    nocolon = "# 功能名：x\n# 验证方式\ncompiler 复现\n# 不适用条件\n其它会话\n"
    missing = "# 功能名：x\n# 执行：无\n"
    check("冒号形态取值",
          nodefile.ccg_element_terms(colon, "验证方式") == ["compiler", "test", "复现"],
          str(nodefile.ccg_element_terms(colon, "验证方式")))
    check("无冒号换行形态取值（行语义与 ccg_field_value 一致）",
          nodefile.ccg_element_terms(nocolon, "验证方式") == ["compiler", "复现"],
          str(nodefile.ccg_element_terms(nocolon, "验证方式")))
    check("缺行 → 空表（不猜测）",
          nodefile.ccg_element_terms(missing, "验证方式") == [])
    # 与单点对拍：terms 必须 == element_terms_from_text(ccg_field_value(...))
    ok = all(nodefile.ccg_element_terms(c, f)
             == nodefile.element_terms_from_text(nodefile.ccg_field_value(c, f))
             for c in (colon, nocolon, missing)
             for f in ("验证方式", "不适用条件"))
    check("与 ccg_field_value 逐例对拍一致（取值单点未旁路）", ok)
    check("词长下限与 mdcg.NEG_MIN_TERM 同值（同口径）",
          nodefile.ELEMENT_TERM_MIN == M.NEG_MIN_TERM,
          f"{nodefile.ELEMENT_TERM_MIN} vs {M.NEG_MIN_TERM}")
    check("空值语义哨兵不入键（不适用条件：无 → 空表）",
          nodefile.ccg_element_terms(colon.replace("其它会话 无关查询", "无"),
                                     "不适用条件") == [],
          str(nodefile.ccg_element_terms(
              colon.replace("其它会话 无关查询", "无"), "不适用条件")))


def g3_entry_keys():
    print("== G3 两键进索引条目（写路径 / 重建路径同口径）==")
    root, cg = _corpus()
    try:
        e = cg.index["nodes"]["k_decl"]
        check("条目含后置条件词键",
              nodefile.POSTCONDITION_TERMS_KEY in e and
              e[nodefile.POSTCONDITION_TERMS_KEY] == ["compiler", "test", "复现"],
              str(e.get(nodefile.POSTCONDITION_TERMS_KEY)))
        check("条目含拒绝域词键",
              e.get(nodefile.REJECTION_TERMS_KEY) == ["其它会话", "无关查询"],
              str(e.get(nodefile.REJECTION_TERMS_KEY)))
        check("不声明拒绝域的节点该键为空",
              (cg.index["nodes"]["k_nodecl"].get(
                  nodefile.REJECTION_TERMS_KEY) or []) == [],
              str(cg.index["nodes"]["k_nodecl"].get(
                  nodefile.REJECTION_TERMS_KEY)))
        # 两键是**扁指标量**：与 time_window/observation_position 同为条目直读标量
        check("两键为 list（扁指标量，非嵌套对象）",
              isinstance(e[nodefile.POSTCONDITION_TERMS_KEY], list)
              and isinstance(e[nodefile.REJECTION_TERMS_KEY], list))
        # 写路径 vs 重建路径：重建后再取，两键逐位相同
        before = {k: e.get(k) for k in nodefile.INDEX_TERMS_KEYS}
        cg.rebuild_index()
        after = {k: cg.index["nodes"]["k_decl"].get(k)
                 for k in nodefile.INDEX_TERMS_KEYS}
        check("写路径 == 重建路径（两键逐位相同）", before == after,
              f"{before} vs {after}")
    finally:
        cg.close()


def g4_rebuild_protocol():
    print("== G4 重建协议四条硬约束（§5.3）==")
    root, cg = _corpus()
    try:
        seq_a = [(r[0]["id"], round(float(r[1]), 6))
                 for r in cg.search_rrf("苹果 章节", k=5, record=False)[0]]
        src_a = _tree_hash(root)
        idx_path = cg.index_path
        cg.rebuild_index()              # 第一次：写快照（幂等对拍的左值）
        fp_a = cg.index.get("_fingerprint")
        with open(idx_path, "rb") as f:
            bytes_a = f.read()
        cg.rebuild_index()              # 第二次：同源重建（对拍右值）
        fp_b = cg.index.get("_fingerprint")
        with open(idx_path, "rb") as f:
            bytes_b = f.read()
        src_b = _tree_hash(root)
        seq_b = [(r[0]["id"], round(float(r[1]), 6))
                 for r in cg.search_rrf("苹果 章节", k=5, record=False)[0]]
        check("① 幂等：同源重建 _fingerprint 对拍相等", fp_a == fp_b,
              f"{fp_a} vs {fp_b}")
        check("① 幂等：两次重建的 _index.json 字节相同", bytes_a == bytes_b)
        check("③ 可回退：重建只覆盖派生物，源面逐字节不变",
              src_a == src_b, f"{src_a} vs {src_b}")
        check("④ 可对拍：重建前后合法次序逐位不变", seq_a == seq_b,
              f"{seq_a} vs {seq_b}")
        # ② 增量优先：指纹未变时 _maybe_reload_index 不换索引对象（不重扫）
        obj_a = cg.index
        cg._maybe_reload_index()
        check("② 增量优先：指纹未变则不重建（索引对象不变）",
              cg.index is obj_a)
    finally:
        cg.close()


def g5_dual_semantics():
    print("== G5 拒绝域双语义：同一节点既边界命中、又未被资格 REJECT ==")
    root, cg = _corpus()
    try:
        nd = cg.get("k_decl")
        # ① 边界问句 + 查询自带拒绝域词面 → 边界命中 ∧ 非 REJECT
        q1 = "什么条件下不适用 其它会话"
        jb = M.MdCG.judge_with_boundary(nd, q1, None)
        check("边界命中为真", jb["boundary"]["hit"] is True,
              str(jb["boundary"]))
        check("同一节点未被资格 REJECT（自否定 = 0）",
              jb["qualification"]["state"] != M.STATE_REJECT,
              str(jb["qualification"]))
        check("可召回可展示", jb["recallable"] is True)
        check("分开计数：boundary_hit 与 reject 是两个独立键",
              jb["counts"]["boundary_hit"] == 1 and jb["counts"]["reject"] == 0,
              str(jb["counts"]))
        # ② 灵敏度不变：非边界问句 + 情境真的落在拒绝域 → 照旧 REJECT
        jb2 = M.MdCG.judge_with_boundary(nd, "刚才在干什么", {"scene": "其它会话"})
        check("非边界问句下情境落在拒绝域仍判 REJECT（灵敏度不变）",
              jb2["qualification"]["state"] == M.STATE_REJECT,
              str(jb2["qualification"]))
        check("该情形同样分开计数（reject=1 / boundary_hit=1）",
              jb2["counts"]["reject"] == 1 and jb2["counts"]["boundary_hit"] == 1,
              str(jb2["counts"]))
        # ③ 边界标记单点：两条来源（情境落在拒绝域 / 边界问句且已声明）
        b1 = M.boundary_mark(nd, "什么条件下不适用", None)
        b2 = M.boundary_mark(nd, "刚才在干什么", {"scene": "无关查询"})
        check("边界问句且已声明拒绝域 → 命中",
              b1["hit"] and b1["why"] == ["boundary_query_and_declared"],
              str(b1))
        check("情境落在拒绝域 → 命中（复用 P0-4 判据）",
              b2["hit"] and "scene_in_rejection_domain" in b2["why"], str(b2))
        check("marker 恒为 boundary_hit（展示标记，不是资格结论）",
              b1["marker"] == M.BOUNDARY_MARKER)
    finally:
        cg.close()


def g6_default_recall():
    print("== G6 六要素后两行全进默认检索（§5.4）==")
    root, cg = _corpus()
    try:
        # 「何时不适用」：不撞 CCG 样板词面（生效条件/验证方式…），故若无索引键
        # 则一个都召不回——正是「索引键驱动召回」的判别用例。
        r, meta = cg.search_rrf("何时不适用", k=5, record=False)
        ids = [x[0]["id"] for x in r]
        check("边界问句召回「声明了拒绝域」的节点",
              ids == ["k_decl"], str(ids))
        check("该节点带 boundary_hit 标记",
              bool(r) and r[0][0].get("boundary_hit") is True,
              str([x[0].get("boundary_hit") for x in r]))
        check("未声明拒绝域的节点不被召回", "k_nodecl" not in ids, str(ids))
        check("meta 分开呈现边界读数（独立键）",
              (meta.get("boundary") or {}).get("hit") == 1
              and "boundary" in meta and "judge_filtered" in meta,
              str(meta.get("boundary")))
        check("默认路集仍为六路（不缺路）",
              set((meta.get("paths") or {}).keys()) == {
                  "lexical", "bucket", "entity", "graph", "chain",
                  "temporal"}, str(sorted((meta.get("paths") or {}).keys())))
        # 验证方式（第 5 行）：按验证手段检索
        r2, _ = cg.search_rrf("compiler", k=5, record=False)
        check("按验证手段可召回（后置条件词索引键）",
              "k_decl" in [x[0]["id"] for x in r2],
              str([x[0]["id"] for x in r2]))
        # 拒绝域**不作普通问句的召回键**（positive_body 的既有立场不变）
        ent = cg.index["nodes"]["k_decl"]
        terms_norm = M.expand_query_terms("其它会话")
        check("普通问句：拒绝域键不参与召回",
              M.index_key_hits(ent, terms_norm, "其它会话")["hit"] is False,
              str(M.index_key_hits(ent, terms_norm, "其它会话")))
        check("边界问句：拒绝域键参与召回",
              M.index_key_hits(ent, terms_norm, "何时不适用")["reject"] is True,
              str(M.index_key_hits(ent, terms_norm, "何时不适用")))
    finally:
        cg.close()


def g7_legacy_zero_break():
    print("== G7 旧库零破坏（条目缺键 / 旧签名）==")
    root, cg = _corpus()
    try:
        old = {"path": "knowledge/k_old.md", "tags": [], "importance": 0.5}
        hits = M.index_key_hits(old, ["其它会话"], "何时不适用")
        check("条目缺两键 → 判 False（未重建的旧快照退回旧行为）",
              hits == {"hit": False, "post": False, "reject": False, "why": []},
              str(hits))
        # `_like` 三参旧签名（旧调用方）行为与改动前一致
        body = BODY.format(n="x", neg="其它会话", t="苹果 章节")
        check("_like 三参旧签名：按 positive_body 命中",
              M.MdCG._like(body, {}, ["苹果"]) is True)
        check("_like 三参旧签名：不适用条件行仍不作召回键",
              M.MdCG._like(body, {}, ["其它会话"]) is False,
              "positive_body 立场被破坏")
    finally:
        cg.close()


# --------------------------------------------------------------------------
# 定点变异（自证断言有判别力；只改本进程内存对象，绝不改仓库文件）
# --------------------------------------------------------------------------

def _mut_mark_min():
    return _patch(nodefile, "ELEMENT_TERM_MIN", 1)


def _mut_roles_4rows():
    return _patch(nodefile, "CCG_INDEX_ROLES",
                  tuple(nodefile.CCG_INDEX_ROLES[:4]))


def _mut_boundary_markers():
    return _patch(M, "BOUNDARY_QUERY_MARKERS", ())


def _mut_index_key_hits_off():
    orig = M.index_key_hits
    M.index_key_hits = lambda entry, terms, query: {
        "hit": False, "post": False, "reject": False, "why": []}

    def restore():
        M.index_key_hits = orig
    return restore


def _mut_boundary_no_strip():
    orig = M.MdCG.judge_with_boundary

    def shrunk(node_dict, query, context=None):
        qual = dict(M.MdCG.judge_qualification(node_dict, query, context))
        st = str(qual.get("state") or "")
        counts = {k: int(st == v) for k, v in
                  (("accept", M.STATE_ACCEPT), ("reject", M.STATE_REJECT),
                   ("defer", M.STATE_DEFER), ("blindspot", M.STATE_BLINDSPOT))}
        counts["boundary_hit"] = 0
        return {"qualification": qual, "boundary": {"hit": False, "terms": [],
                                                    "marker": None},
                "counts": counts,
                "recallable": st not in (M.STATE_REJECT, M.STATE_BLINDSPOT)}

    M.MdCG.judge_with_boundary = staticmethod(shrunk)

    def restore():
        M.MdCG.judge_with_boundary = orig
    return restore


def _patch(mod, name, value):
    orig = getattr(mod, name)

    def restore():
        setattr(mod, name, orig)
    setattr(mod, name, value)
    return restore


_MUTATIONS = [
    ("roles_4rows", "把六要素表退回 4 行", _mut_roles_4rows),
    ("term_min_1", "索引词长下限改成 1（与 NEG_MIN_TERM 分叉）", _mut_mark_min),
    ("no_boundary_markers", "边界问句标记表清空", _mut_boundary_markers),
    ("index_keys_off", "索引键召回判据恒 False", _mut_index_key_hits_off),
    ("no_boundary_strip", "边界问句不再摘词面（自否定回归）",
     _mut_boundary_no_strip),
]


def _collect():
    """跑全部断言组，返回失败清单（变异自证用同一批断言）。"""
    global PASS, FAIL, FAILS
    PASS, FAIL, FAILS = 0, 0, []
    g1_table_six_rows()
    g2_single_parse_point()
    g3_entry_keys()
    g4_rebuild_protocol()
    g5_dual_semantics()
    g6_default_recall()
    g7_legacy_zero_break()
    return list(FAILS)


def main(argv):
    if "--mutate" in argv:
        if "--list" in argv:
            for name, desc, _fn in _MUTATIONS:
                print(f"  {name:24s} {desc}")
            return 0
        base = _collect()
        if base:
            print(f"\n!! 基线不绿（{len(base)} 条失败）——变异自证无意义：{base}")
            return 1
        bad = []
        for name, desc, fn in _MUTATIONS:
            for anchor in ():
                pass
            try:
                restore = fn()
            except AttributeError as exc:      # 锚点漂移：硬失败
                print(f"  ANCHOR-MISS {name}: {exc}")
                return 2
            got = _collect()
            restore()
            if got:
                print(f"  MUTATE-OK {name}（{desc}）→ 转红 {len(got)} 条：{got[:3]}")
            else:
                bad.append(name)
                print(f"  MUTATE-FAIL {name}（{desc}）→ 仍全绿（断言无判别力）")
        print(f"\ntest_p2_six_elements --mutate: "
              f"{len(_MUTATIONS) - len(bad)}/{len(_MUTATIONS)} 变异按预期转红")
        return 0 if not bad else 1
    fails = _collect()
    print(f"\ntest_p2_six_elements: {PASS} 通过 / {FAIL} 失败")
    return 0 if not fails else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
