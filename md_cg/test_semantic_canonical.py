# -*- coding: utf-8 -*-
"""标准语义归一面测试：词表真源 / OOV 审计 / 写入落盘 / 语义摘要路 / 零回归守卫。

跑法：python -m md_cg.test_semantic_canonical
"""
import os
import shutil
import sys
import tempfile

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for _p in (HERE, os.path.join(HERE, "md_cg")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from md_cg.semantic import canonical as cn          # noqa: E402
from md_cg.semantic import zh_en_atoms              # noqa: E402
from md_cg import mdcos                             # noqa: E402
from md_cg import eval_common as ec                 # noqa: E402

N = 0


def ok(cond, msg):
    global N
    assert cond, msg
    N += 1


L3_Q = "体检后医生建议我补充一些从深海鱼类里提取的油脂"
GOLD_TEXT = "今天午饭吃了鱼油，味道不错，下次还做。"
DISTRACT = "下午去市场买了鱼，价格比昨天便宜一些。"


def t_units():
    # 词表真源加载
    zh = cn.atoms_zh()
    ok(len(zh) > 800, "atoms 词表规模异常: %d" % len(zh))
    ok("鱼" in zh and "油" in zh, "组成原子缺失")
    # 容错切分：复合词形态与空格原子形态同构
    ok(cn.semantic_atoms("鱼油") == ["鱼", "油"], "复合词切分失败")
    ok(cn.semantic_atoms("鱼 油") == ["鱼", "油"], "空格原子解析失败")
    # OOV 审计：合法空 / OOV 检出（熬 不在 atoms——实测验证）
    ok(cn.oov_of("鱼 油") == [], "合法原子误报 OOV")
    ok(cn.oov_of("鱼 熬") == ["熬"], "OOV 未检出")
    # 组合窗口共现（探针实证口径）
    ok(cn.pair_hits("鱼 油", L3_Q) == 1.0, "win6 命中失败（探针口径回归）")
    ok(cn.pair_hits("鱼 油", "鱼在很远的地方才有油") == 0.0, "超窗误命中")
    ok(cn.pair_hits("鱼", L3_Q) == 0.0, "单原子摘要应诚实 0 分")
    ok(cn.pair_hits("鱼 油", "今天吃了马肉") == 0.0, "无关 query 误命中")
    # 与 zh_en_atoms 同源：serialize 出口不受影响
    ok("cow meat" == zh_en_atoms.serialize("牛肉"), "zh_en_atoms 出口漂移")
    # 英文 query 汇入统一真源（2026-09-14）：同一切分器保证两端形态同构。
    # 复合概念词（牛肉）在 ZH_EN 贪心表/atoms 真源内 → 保持整词（serialize
    # 出口既有设计）；单字语素组合（马肉）→ 展开为原子。
    ok(cn.query_atoms("I ate beef yesterday") == ("我", "吃", "牛肉", "昨天"),
       "英文归一形态漂移: %r" % (cn.query_atoms("I ate beef yesterday"),))
    ok(cn.query_atoms("horse meat") == ("马", "肉"), "英文组合词语素映射失败")
    ok(cn.query_atoms("Caroline reads books") == ("Caroline", "读", "书"),
       "英文保留词应原样占位: %r" % (cn.query_atoms("Caroline reads books"),))
    ok(cn.pair_hits("吃 牛肉", "I ate beef yesterday") == 1.0,
       "英文原题经统一真源未命中 doc 原子（复合词整词）")
    ok(cn.pair_hits("马 肉", "Did you eat horse meat today?") == 1.0,
       "英文原题经统一真源未命中 doc 原子（单字语素）")
    # 纯中文零变化守卫（英文分支不触发）
    ok(cn.query_atoms("鱼油") == ("鱼", "油"), "纯中文切分漂移")
    ok(cn.query_atoms("鱼 油") == ("鱼", "油"), "纯中文空格形态漂移")


def t_write(tmp):
    os.environ.pop("MDCG_SEMANTIC", None)
    cg = mdcos.MdCGOS(tmp, autoflush=500)
    try:
        cg.add("g1", GOLD_TEXT, layer="knowledge", semantic="鱼 油",
               verification_basis="data")
        cg.add("g2", GOLD_TEXT, layer="knowledge", semantic="鱼 熬",
               verification_basis="data")
        cg.add("g3", GOLD_TEXT, layer="knowledge", verification_basis="data")
        fm1 = cg.get("g1")["frontmatter"]
        fm2 = cg.get("g2")["frontmatter"]
        fm3 = cg.get("g3")["frontmatter"]
        ok(fm1.get("semantic") == "鱼 油", "semantic 未落 fm")
        ok("semantic_oov" not in fm1, "合法原子不应有 OOV 键")
        ok(fm2.get("semantic_oov") == ["熬"], "OOV 审计未落 fm")
        ok(fm2.get("semantic") == "鱼 熬", "OOV 时原样保留 AI 产物")
        ok("semantic" not in fm3, "未传 semantic 不应产生键")
    finally:
        cg.close()


def t_score_off_guard(tmp):
    """默认关闭零回归：直调 _score 比词法层原始分（绕开 RRF 名次拆序——
    search_rrf 并列时按名次取 1/(K+rank)，同分节点的名次分差是融合层
    固有行为，不是 semantic 侧差异）。"""
    os.environ.pop("MDCG_SEMANTIC", None)
    root = os.path.join(tmp, "off")
    cg = mdcos.MdCGOS(root, autoflush=500)
    try:
        ec.unlock_global_cap()
        ec.use_jaccard()
        cg.add("a_sem", "今天研究了鱼油的做法，记载于此。", layer="knowledge",
               semantic="鱼 油", verification_basis="data")
        cg.add("a_plain", "今天研究了鱼油的做法，记载于此。", layer="knowledge",
               verification_basis="data")
        cg.flush()
        from md_cg.mdcg import bigrams, normalize_en
        stat = {"scanned": 0}
        docs = cg._read_many(list(cg.index["nodes"].values()), stat)
        qb = bigrams(normalize_en("鱼油"))
        by_id = {s[0]["id"]: s[1] for s in cg._score(docs, "鱼油", qb)}
        ok(by_id.get("a_sem") == by_id.get("a_plain"),
           "默认关闭时 semantic 改变了词法分（零回归破坏）: %r"
           % by_id)
        # 开启后：semantic 摘要命中（鱼 油 同现）→ a_sem 被语义路抬高
        os.environ["MDCG_SEMANTIC"] = "1"
        by_id2 = {s[0]["id"]: s[1] for s in cg._score(docs, "鱼油", qb)}
        ok(by_id2["a_sem"] > by_id2["a_plain"],
           "开启后语义路未抬高 a_sem: %r" % by_id2)
        os.environ.pop("MDCG_SEMANTIC", None)
    finally:
        cg.close()


def t_e2e(tmp):
    """端到端（盲测同口径 search_rrf/lexical）：开→L3 gold top1；关→词法零交集不命中。"""
    ec.unlock_global_cap()
    ec.use_jaccard()

    def build(root, with_sem):
        shutil.rmtree(root, ignore_errors=True)
        cg = mdcos.MdCGOS(root, autoflush=500)
        kw = {"semantic": "鱼 油"} if with_sem else {}
        cg.add("gold", GOLD_TEXT, layer="knowledge",
               verification_basis="data", **kw)
        kw2 = {"semantic": "猪 油"} if with_sem else {}
        cg.add("gold_p", "妈妈熬了一罐雪白的荤油，拌饭特别香",
               layer="knowledge", verification_basis="data", **kw2)
        cg.add("d1", DISTRACT, layer="knowledge", verification_basis="data")
        cg.add("d2", "晚上用油和奶做了两道菜，都没放辣椒。", layer="knowledge",
               verification_basis="data")
        cg.flush()
        ec.install_read_cache(cg)
        return cg

    root_on = os.path.join(tmp, "e2e_on")
    cg = build(root_on, with_sem=True)
    try:
        # 开：gold top1（组合共现 1.0，干扰 0 分）
        os.environ["MDCG_SEMANTIC"] = "1"
        res, _meta = cg.search_rrf(L3_Q, k=5, paths=("lexical",),
                                   judge=False, record=False)
        ok(res and res[0][0]["id"] == "gold",
           "语义路开启未命中 top1: %r" % [r[0]["id"] for r in res[:2]])
        # 查询侧归一（设想终态）：荤油正文无「猪」字，原句式 query 无法命中，
        # AI 归一后的标准原子 query「猪 油」命中 gold_p
        res, _meta = cg.search_rrf("猪 油", k=5, paths=("lexical",),
                                   judge=False, record=False)
        ok(res and res[0][0]["id"] == "gold_p",
           "归一 query 未命中 gold_p: %r" % [r[0]["id"] for r in res[:2]])
        # 关闭后同 query：gold_p 词法分 0（「猪」不在正文），不应凭语义进 top1
        os.environ.pop("MDCG_SEMANTIC", None)
        res, _meta = cg.search_rrf("猪 油", k=5, paths=("lexical",),
                                   judge=False, record=False)
        top1 = res[0][0]["id"] if res else None
        ok(top1 != "gold_p", "关闭语义路 gold_p 仍 top1（词法零分被违反？）")
        # 关：词法零交集 → gold 不应凭语义进前排（结构性无解基线）
        os.environ.pop("MDCG_SEMANTIC", None)
        res, _meta = cg.search_rrf(L3_Q, k=5, paths=("lexical",),
                                   judge=False, record=False)
        top1 = res[0][0]["id"] if res else None
        ok(top1 != "gold", "关闭语义路 gold 仍 top1（词法零交集被违反？）")
    finally:
        os.environ.pop("MDCG_SEMANTIC", None)
        cg.close()

    # 无摘要库上开关无副作用（fm.semantic 缺失走原词法路径）
    root_off = os.path.join(tmp, "e2e_off")
    cg = build(root_off, with_sem=False)
    try:
        os.environ["MDCG_SEMANTIC"] = "1"
        res, _meta = cg.search_rrf(L3_Q, k=5, paths=("lexical",),
                                   judge=False, record=False)
        top1 = res[0][0]["id"] if res else None
        ok(top1 != "gold", "无 semantic 摘要时语义路不应凭空生效")
    finally:
        os.environ.pop("MDCG_SEMANTIC", None)
        cg.close()


def t_en_unified(tmp):
    """英文 query 汇入统一真源（端到端）：英文原题直查 fm.semantic 节点。

    归一发生在 query_atoms 内部——检索调用面零改动；同时验证语义资格层
    （fm.semantic 无条件入池）对英文 query 同样生效（英文 terms 对中文
    正文 LIKE 必不中，唯一通路就是语义资格 + 组合共现打分）。
    """
    ec.unlock_global_cap()
    ec.use_jaccard()
    root = os.path.join(tmp, "en_unified")
    shutil.rmtree(root, ignore_errors=True)
    cg = mdcos.MdCGOS(root, autoflush=500)
    try:
        cg.add("gold", "今天午饭吃了马肉，味道不错，下次还做。", layer="knowledge",
               semantic="马 肉", verification_basis="data")
        cg.add("d1", "下午去市场买了马，价格比昨天便宜一些。", layer="knowledge",
               verification_basis="data")
        cg.flush()
        ec.install_read_cache(cg)
        os.environ["MDCG_SEMANTIC"] = "1"
        res, _m = cg.search_rrf("Did you eat horse meat today?", k=5,
                                paths=("lexical",), judge=False, record=False)
        ok(res and res[0][0]["id"] == "gold",
           "英文原题未命中统一真源 gold: %r" % [r[0]["id"] for r in res[:2]])
        # 关闭语义路：英文原题对中文正文词法零交集，gold 不应凭空出现
        os.environ.pop("MDCG_SEMANTIC", None)
        res, _m = cg.search_rrf("Did you eat horse meat today?", k=5,
                                paths=("lexical",), judge=False, record=False)
        top1 = res[0][0]["id"] if res else None
        ok(top1 != "gold", "关闭语义路英文原题仍命中 gold（词法零交集被违反？）")
    finally:
        os.environ.pop("MDCG_SEMANTIC", None)
        cg.close()


def main():
    os.environ.pop("MDCG_SEMANTIC", None)
    t_units()
    tmp = tempfile.mkdtemp(prefix="lsh_sem_")
    try:
        t_write(tmp)
        t_score_off_guard(tmp)
        t_e2e(tmp)
        t_en_unified(tmp)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
        os.environ.pop("MDCG_SEMANTIC", None)
    print("[test_semantic_canonical] %d 断言全绿" % N)


if __name__ == "__main__":
    main()
