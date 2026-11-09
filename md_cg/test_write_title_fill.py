# -*- coding: utf-8 -*-
"""test_write_title_fill —— 写入口补全标题（P4，2026-11-06）

判什么：
  A 组 · derive_title（纯函数，不落盘）
    A1 首行是附属字段（「验证方式：…」）时，标题取**最长的一行非附属字段散文**
    A2 完全没有附属字段时取最长行
    A3 全部行都是附属字段时回落首个非空行（不返回空串，也不编造）
    A4 超长标题截到 40 字符
  B 组 · 写链（真落盘，临时根）
    B1 正文缺标题 → 写入后盘上出现「# 功能名：」，fm.title_basis == "derived"
    B2 正文自带标题 → 原样保留，fm 里**没有** title_basis（不覆盖人的标题）
    B3 _meta_patch（只补元数据）→ 不补标题
    B4 空正文 → 不崩、不补（返回体仍是合法形态）
    B5 派生标题的节点能被 ccg 判成「有功能名」（读出口与写入口口径一致）

负控：把 _fill_title 换成恒等函数，B1/B1b/B1c/B5 必须变红。
"""
import sys
import tempfile

from . import writepipe

N = 0
BAD = []

# CCG 六要素齐全的正文（0.9.23 的写闸要求六行齐全，缺一条就被 REJECT）
BODY = """# 子功能：把每轮对话压成一条可检索的卡
# 生效条件：每轮结束且正文里有可检索的事实
# 执行：先跑 ingest，再 verify 一遍
# 验证方式：实测
# 不适用条件：纯寒暄没有事实
检索低分的根因是语料脏，不是排序。
"""


def ck(name, cond, detail=""):
    global N
    N += 1
    if cond:
        print("  ok   %s" % name)
    else:
        BAD.append(name)
        print("  FAIL %s  %s" % (name, detail))


def A():
    d = writepipe.derive_title
    ck("A1 跳过附属字段取散文",
       d("# 验证方式：同模型自验\n# 生效条件：需要回答检索问题时\n"
         "检索低分的根因是语料脏，不是排序。") == "检索低分的根因是语料脏，不是排序。",
       d("# 验证方式：同模型自验\n检索低分的根因是语料脏，不是排序。"))
    ck("A2 无附属字段取最长行",
       d("短句。\n这是一行明显更长也更像标题的散文。") == "这是一行明显更长也更像标题的散文。",
       d("短句。\n这是一行明显更长也更像标题的散文。"))
    ck("A3 全附属字段回落首个非空行",
       d("# 验证方式：同模型自验\n# 执行：跑一遍") == "验证方式：同模型自验",
       d("# 验证方式：同模型自验\n# 执行：跑一遍"))
    long = "标" * 60
    ck("A4 截断到 40", len(d(long)) == 40, len(d(long)))


def _cg(root):
    from .mdcos import MdCGSecure
    from .security import Principal
    return MdCGSecure(root, principal=Principal(
        actor="dsh-memory", role="designer", tenant="default",
        clearance="private", can_write=True, can_admin=True), autoflush=8)


def B():
    with tempfile.TemporaryDirectory() as td:
        cg = _cg(td)
        pipe = writepipe.default_pipeline()
        r1 = pipe.execute(cg, {"node_id": "kn_t1", "content": BODY,
                               "layer": "knowledge", "content_kind": "text",
                               "role": "assistant"})
        g1 = cg.get("kn_t1") or {}
        body1 = g1.get("content") or ""
        ck("B1 缺标题被补", body1.startswith("# 功能名："), (body1[:60] or repr(r1)[:120]))
        first = (body1.splitlines() or [""])[0]
        ck("B1b 标题取自散文", "检索低分的根因" in first, first)
        ck("B1c fm.title_basis=derived",
           (g1.get("frontmatter") or {}).get("title_basis") == "derived",
           (g1.get("frontmatter") or {}).get("title_basis"))
        ck("B1d 写入被接受", bool(r1.get("ok")) and bool(r1.get("committed")),
           (r1.get("verdict") or {}).get("evidence"))

        with_title = "# 功能名：我自己写的标题\n" + BODY
        r2 = pipe.execute(cg, {"node_id": "kn_t2", "content": with_title,
                               "layer": "knowledge", "content_kind": "text",
                               "role": "assistant"})
        g2 = cg.get("kn_t2") or {}
        body2 = g2.get("content") or ""
        ck("B2 自带标题原样保留",
           body2.count("# 功能名：") == 1 and body2.startswith("# 功能名：我自己写的标题"),
           body2[:60])
        ck("B2b 不写 title_basis",
           "title_basis" not in (g2.get("frontmatter") or {}),
           (g2.get("frontmatter") or {}).get("title_basis"))

        # B3：_meta_patch 按契约「正文由盘面取回」，调用方把**现盘正文**原样传回；
        #     已派生的标题必须原样留着、不被再补一条（幂等）
        cur = (cg.get("kn_t1") or {}).get("content") or ""
        r3 = pipe.execute(cg, {"node_id": "kn_t1", "_meta_patch": True,
                               "content": cur, "content_kind": "text",
                               "tags": ["domain:test"]})
        g3 = cg.get("kn_t1") or {}
        ck("B3 _meta_patch 不补标题（正文仍是已补版本，未再加一条）",
           (g3.get("content") or "").count("# 功能名：") == 1,
           (g3.get("content") or "")[:40])
        ck("B3b 元数据补丁被接受", bool(r3.get("ok")), r3.get("verdict"))

        # B4：空白正文不静默落成节点——写链按 CCG 六要素缺失拒收（REJECT，不进正式层）
        try:
            r4 = pipe.execute(cg, {"node_id": "kn_t4", "content": "   ",
                                   "layer": "contextual", "content_kind": "text",
                                   "role": "assistant"})
            rejected = (not r4.get("ok")) and not r4.get("committed") \
                and (r4.get("verdict") or {}).get("state") == "REJECT"
            ck("B4 空正文被拒（不落正式节点）", rejected, r4.get("verdict"))
        except ValueError as e:
            ck("B4 空正文被拒（不落正式节点）", "content 不能为空" in str(e), str(e)[:60])
        ck("B4b 空正文没落盘", (cg.get("kn_t4") or {}) == {}, cg.get("kn_t4"))

        from . import nodefile
        ck("B5 ccg 认得出功能名",
           nodefile.ccg_mark_present(body1, "功能名"), body1[:30])


def main():
    print("=== test_write_title_fill ===")
    A()
    B()
    print("=== test_write_title_fill: PASS %d / FAIL %d ===" % (N - len(BAD), len(BAD)))
    if BAD:
        print("失败项：", "、".join(BAD))
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
