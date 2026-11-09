# -*- coding: utf-8 -*-
"""test_consolidate_kind —— consolidate 固化字段时补 kind 与功能名（P0-c）

判什么（真落盘，临时根；不调模型，直接驱动 `_apply_node`）：
  A0 前提：knowledge 层写入时不传 kind → 落库后 kind 仍为空
  A1 knowledge 层节点没有 kind → 固化后 kind = text
  A2 contextual 层节点没有 kind → 固化后 kind = work_log
  A3 已有 kind 一字不动（knowledge 上显式写 work_log，固化后仍是 work_log）
  A4 正文没有 `# 功能名` → 固化后首行是派生标题，且 fm.title_basis = derived
  A5 正文已有 `# 功能名` → 原样保留、不写 title_basis
  A6 落库后 ccg_scope 认得出豁免（contextual/work_log → exempt）
  A7 补出来的字段真的进了正文（`# 生效条件：…` 可 grep 到）

为什么这样判：20 条批次里 ACCEPT 10 条全落 contextual 层、补了 5 个要素却
仍 `content_kind=None` ⇒ 资格裁决按 text 要六要素 ⇒ 差「功能名」恒
incomplete。A1/A2 都是「补 kind」的正题：库面 859/859 为 None 的历史节点都在索引里、且
写闸对 kind 缺失一律 BLINDSPOT 进 review_queue，所以只能绕过写闸用 `cg.add` 造
出与历史同形的节点。

负控：删掉 `_apply_node` 里那段 kind 赋值 → A1 / A2 / A6 三条变红
（`/tmp/sv16n` 实测：8 条断言里 3 条红）。
"""
import sys
import tempfile

from . import ccg_scope, consolidate, writepipe

N = 0
BAD = []

BODY = ("检索流水：mn_gw_0021d1d4aa9d 于 2026-11-06T03:30:00 记「检索低分的根因是"
        "语料脏，不是排序」。\n")

SEM6 = ("# 功能名：语义卡六要素齐全\n# 生效条件：需要给结论时\n# 子功能：给结论\n"
        "# 执行：读 index 后重算\n# 验证方式：判据实测\n# 不适用条件：无\n正文。\n")


def ck(name, cond, detail=""):
    global N
    N += 1
    if cond:
        print("  ok   %s" % name)
    else:
        BAD.append(name)
        print("  FAIL %s  %s" % (name, detail))


def _cg(root):
    from .mdcos import MdCGSecure
    from .security import Principal
    return MdCGSecure(root, principal=Principal(
        actor="dsh-memory", role="designer", tenant="default",
        clearance="private", can_write=True, can_admin=True), autoflush=8)


def _node(cg, nid, content, layer, kind=None, tags=()):
    """直接 cg.add 落库（**绕过写闸**）——这正是不带 kind 的历史节点的形态：
    P0 之前 writepipe 从不转发 content_kind，库面 859/859 全为 None。
    走 writepipe 的话缺 kind 会被判 BLINDSPOT 进 review_queue，根本进不了索引，
    也就测不到  的补 kind 逻辑。"""
    kw = {"tags": list(tags), "importance": 0.5}
    if kind:
        kw["content_kind"] = kind
    cg.add(nid, content, layer=layer, **kw)
    return {"ok": True}


def _entry(cg, nid):
    # 索引以 nid 为键，条目里**没有** id 字段（只有 path/layer/tags/…），
    # 所以按键取、再把 id 补进去——`_apply_node` 依赖 e["id"] 或 e["path"]。
    e = cg.index["nodes"].get(nid)
    if e is None:
        return None
    e = dict(e)
    e["id"] = nid
    return e


def _apply(cg, nid, fields):
    e = _entry(cg, nid)
    r = cg.get(nid, probe=True) or {}
    fm = dict(r.get("frontmatter") or {})   # 索引条目不带 frontmatter，只能从节点读
    fm.setdefault("id", nid)
    content = r.get("content") or ""
    consolidate._apply_node(cg, e, fm, content, fields,
                            {"at": 0, "verdict": "ACCEPT"}, "实测", "other")


def _read(cg, nid):
    r = cg.get(nid, probe=True) or {}
    return (r.get("frontmatter") or {}), (r.get("content") or "")


def main():
    root = tempfile.mkdtemp(prefix="mdcg-p0c-")
    cg = _cg(root)

    # A0/A1：knowledge 层、写入时不传 kind → kind 缺失只能靠 _apply_node 补
    _node(cg, "kn_nokind", SEM6, "knowledge")
    fm0, _c0 = _read(cg, "kn_nokind")
    ck("A0 前提：knowledge 写入后 kind 仍为空", not (fm0.get("content_kind") or ""),
       str(fm0.get("content_kind")))
    _apply(cg, "kn_nokind", {"执行": ["读 index 后重算"]})
    fm1, _c1 = _read(cg, "kn_nokind")
    ck("A1 knowledge → text", fm1.get("content_kind") == "text", str(fm1.get("content_kind")))

    # A2 + A4 + A6 + A7：contextual 流水卡（写入时 kind 缺失，由 _fill_kind 补）
    _node(cg, "ctx_flow_1", BODY, "contextual")
    _apply(cg, "ctx_flow_1", {"生效条件": ["需要判断检索为什么 0 命中时"]})
    fm2, c2 = _read(cg, "ctx_flow_1")
    ck("A2 contextual → work_log", fm2.get("content_kind") == "work_log",
       str(fm2.get("content_kind")))
    ck("A4 补出派生功能名", c2.startswith("# 功能名：") and fm2.get("title_basis") == "derived",
       c2[:40].replace("\n", "|"))
    ck("A7 字段进了正文", "# 生效条件：" in c2, c2[:200].replace("\n", "|"))
    ck("A6 豁免口径认得出", ccg_scope.is_exempt(fm2) is True,
       str(ccg_scope.completeness(c2, fm2)))

    # A5：已有标题不动
    titled = "# 功能名：手工确认过的标题\n" + BODY
    _node(cg, "ctx_titled", titled, "contextual")
    _apply(cg, "ctx_titled", {"不适用条件": ["无观测窗语义对照"]})
    fm3, c3 = _read(cg, "ctx_titled")
    ck("A5 已有标题不动", c3.count("# 功能名：") == 1 and fm3.get("title_basis") is None,
       str(fm3.get("title_basis")))

    # A3：显式 kind 必被保留
    _node(cg, "kn_forced", BODY, "knowledge", "work_log")
    _apply(cg, "kn_forced", {"子功能": ["给出一条可复算的结论"]})
    fm4, _c4 = _read(cg, "kn_forced")
    ck("A3 已有 kind 不动", fm4.get("content_kind") == "work_log",
       str(fm4.get("content_kind")))

    print("\n%d 条断言 · 失败 %d" % (N, len(BAD)))
    if BAD:
        print("失败项：" + ", ".join(BAD))
    return 0 if not BAD else 1


if __name__ == "__main__":
    sys.exit(main())
