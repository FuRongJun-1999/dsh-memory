# -*- coding: utf-8 -*-
"""负条件（不适用条件）命中判据的守卫（批次76，2026-09-28）。

运行：python -X utf8 -m md_cg.test_neg_condition_hits        # 正常跑
      python -X utf8 -m md_cg.test_neg_condition_hits --head-baseline  # 判别力自证

背景（为什么另立一套）：改动前判据是
`neg_hit = [n for n in neg if any(w in scene for w in n.split())]`
——**空白切词 + 任一词命中**。三处过粗各有实测支撑：
  · 主题词变扳机：中文句里夹的裸标识符被切成独立词，`CCG`/`state`/`tags`/
    `python3` 在**本节点自己的主题问句**上命中 → 节点把自己判成不适用
    （三条归档实测，批次75 已用措辞侧改写止血）；
  · 单个通用词整片否决：`DSH`(16 条)/`MCP`(12 条)/`CI`/`AEIS`/`Actions`
    这类条目作用域旁注里的词，任何含它的问句都把这些节点打成不适用；
  · 单字符碎片（的/与/3）与长短语同权。
新判据（`mdcg.neg_condition_hits`）：**整条命中** 或 **全词命中**，词长下限
`NEG_MIN_TERM`，外加**自主题豁免**（命中内容出现在节点自己声明的主题面里则
不计——它与写入期 L1-a「负条件命中自身生效条件/正文即自相矛盾」同向）。

本套断言分七组：
  G1 整条命中（单词语料条目，「问ZXQ7」/「刚才在干什么」/「问完全无关主题」）
  G2 全词命中（多词条目须词面齐全；缺一词即放行）
  G3 词长下限（单字符碎片不否决）
  G4 自主题豁免（命中内容在 own_topic 里 → 放行；不在 → 照旧否决）
  G5 病理复现（三条归档的**旧措辞**：旧判据命中、新判据放行——正对照是同一
     条目在把 own_topic 换成别人的主题后**仍**否决）
  G6 单点结构（`judge_qualification` 走 `neg_condition_hits`，源码里不得再出现
     「任一词命中」式实现——副本回归即红）
  G7 端到端（真建临时库：完整六要素节点，自主题问句非 REJECT、语料式问句 REJECT）

**红基线自证（--head-baseline）**：把 `neg_condition_hits` 临时替换回旧的
「任一词命中」实现，G1/G4/G5/G7 必须转红（G2 的「缺一词即放行」在旧判据下也
会失败，因为旧判据任一词命中即拒）。若红基线不红，说明断言没有判别力。
"""
from __future__ import annotations

import json
import os
import re
import sys
import tempfile

from . import mdcg as M
from .mdcg import NEG_MIN_TERM, MdCG, neg_condition_hits

_PASS = []
_FAIL = []


def ok(cond, msg, extra=""):
    (_PASS if cond else _FAIL).append(msg)
    print(("  PASS " if cond else "  FAIL ") + msg + (("  ← " + str(extra)) if (extra and not cond) else ""))


def _scene(q: str) -> str:
    return json.dumps({"query": q}, ensure_ascii=False)


# ---------------------------------------------------------------- 旧判据（红基线用）
def _old_hits(neg_conditions, scene_text, own_topic_text=""):
    """改动前的实现原文——仅用于 --head-baseline 的判别力自证，不参与生产。"""
    return [n for n in (neg_conditions or [])
            if any(w in scene_text for w in str(n).split())]


# ---------------------------------------------------------------- G1 整条命中
def g1():
    print("== G1 整条命中（语料口径，必须保持否决）==")
    for neg, q in ((['问ZXQ7'], '问ZXQ7 是什么'),
                   (['刚才在干什么'], '你刚才在干什么'),
                   (['问完全无关主题'], '问完全无关主题')):
        h = neg_condition_hits(neg, _scene(q), '')
        ok(bool(h), "G1 语料式负条件命中即否决：%s" % neg[0], h)
    h = neg_condition_hits(['问 ZXQ7'], _scene('问ZXQ7 是什么'), '')
    ok(bool(h), "G1a 空白归一：条目「问 ZXQ7」对问句「问ZXQ7」仍命中（判据反向前更稳）", h)


# ---------------------------------------------------------------- G2 全词命中
def g2():
    print("== G2 全词命中（多词条目要求词面齐全）==")
    neg = ['抓取 管线']
    ok(bool(neg_condition_hits(neg, _scene('顺带说说抓取 管线的事'), '')),
       "G2 两词齐全 → 否决")
    ok(not neg_condition_hits(neg, _scene('抓取这条路怎么走'), ''),
       "G2a 只中一词 → 放行（旧判据在这里误拒）")
    ok(not neg_condition_hits(['其它机器/其它 DSH profile'], _scene('DSH 端怎么接'), ''),
       "G2b 作用域旁注里的单个通用词（DSH）不否决")
    ok(not neg_condition_hits(['非 GitHub Actions 环境'], _scene('GitHub Actions 怎么配'), ''),
       "G2c 旁注词不作为拒绝理由（「非 X 环境」条目对「X 怎么配」放行）")


# ---------------------------------------------------------------- G3 词长下限
def g3():
    print("== G3 词长下限 ==")
    ok(NEG_MIN_TERM == 2, "G3 词长下限常量 =2（单字符碎片不构成拒绝理由）", NEG_MIN_TERM)
    ok(not neg_condition_hits(['的 与 3'], _scene('随便一个问句 3'), ''),
       "G3a 单字符碎片不否决")
    ok(not neg_condition_hits([''], _scene('任意问句'), ''),
       "G3b 空条目不产生命中")


# ---------------------------------------------------------------- G4 自主题豁免
def g4():
    print("== G4 自主题豁免 ==")
    scene = _scene('写入闸门 tags 扫描面')
    neg = ['（1）写入闸门只扫 content、不扫 tags——内容无命中而 tags 夹带凭据时判 ACCEPT']
    own = '负记忆凭据脱敏的形态补全（全形态令牌 · 跨度合并 · tags 同口径）'
    ok(bool(_old_hits(neg, scene, own)), "G4 前置：旧判据在该问句下确实命中（病态成立）")
    ok(not neg_condition_hits(neg, scene, own),
       "G4a 命中内容属于节点自身主题面 → 放行（不当成「不适用」）")
    ok(not neg_condition_hits(neg, scene, '别的主题'),
       "G4b 换 own_topic 同样不命中（长句条目本就不是拒绝域的判据，与豁免无关）")
    ok(not neg_condition_hits(['刚才在干什么'], _scene('你刚才在干什么'),
                              '问的是刚才在干什么这类即时情境'),
       "G4c 自主题豁免对语料式条目同样生效（自身主题含该短语时不当成不适用）")
    ok(bool(neg_condition_hits(['刚才在干什么'], _scene('你刚才在干什么'),
                               '问的是写入闸门的判据'),
           ),
       "G4d 正对照：同一条目，own_topic 换成不相干主题 → 仍否决")


# ---------------------------------------------------------------- G5 病理复现
def g5():
    print("== G5 病理复现（三条归档的旧措辞）==")
    cases = (
        ("mem_1790589433213",
         ['本次只覆盖解释器「名字不可用」这一族——不解决「候选名可跑但版本/依赖不符」'
          '（如 PATH 上有 python3 却缺 md_cg 所需依赖）的错配，此时须显式设 HIVE_PYTHON'],
         '解释器缺省 python3 探测 HIVE_PYTHON',
         'HIVE_PYTHON 探测式缺省'),
        ("mem_1790595840708",
         ['不覆盖 DSH/TS 侧是否有并列判据（本仓 src/ 与 lib/ 检索无第二套 CCG 判据）'],
         'CCG 六要素 判据 单点 冒号',
         'CCG 六要素判据收单点'),
        ("mem_1790596483649",
         ['（1）写入闸门**只扫 `content`、不扫 `tags`**——内容无命中而 tags 夹带凭据时判 ACCEPT'],
         '写入闸门 tags 扫描面',
         '负记忆凭据脱敏的形态补全（tags 同口径）'),
    )
    for nid, neg, q, own in cases:
        old = _old_hits(neg, _scene(q), own)
        new = neg_condition_hits(neg, _scene(q), own)
        ok(bool(old), "G5 %s 旧判据在这条自主题问句下命中（红基线可复现）" % nid, old)
        ok(not new, "G5a %s 新判据放行（节点不再在自己的主题上消失）" % nid, new)


# ---------------------------------------------------------------- G6 单点结构
def g6():
    print("== G6 判据单点（防副本回归）==")
    p = os.path.join(os.path.dirname(os.path.abspath(__file__)), "mdcg.py")
    src = open(p, encoding="utf-8").read()
    win = M.__file__
    body = src[src.index("def judge_qualification"):
               src.index("def judge_qualification") + 3000]
    ok("neg_condition_hits(" in body, "G6 judge_qualification 走单点 neg_condition_hits")
    # 只看**可执行行**（说明性注释里引述旧实现是允许的，正是要记下它为何被换掉）
    code = "\n".join(l for l in body.splitlines() if not l.strip().startswith("#"))
    ok("any(w in scene" not in code,
       "G6a 可执行行内不再有「任一词命中」式实现（副本回归即红）")
    ok("def neg_condition_hits" in src, "G6b 单点函数存在于 mdcg.py（真源 %s）" % win)
    n = len(re.findall(r"def neg_condition_hits", src))
    ok(n == 1, "G6c 单点全仓唯一实现（mdcg.py 内出现 %d 次）" % n, n)
    # 三态调用方（mdcos 的 legacy 覆盖）必须仍委托父类判据
    mdsrc = open(os.path.join(os.path.dirname(p), "mdcos.py"), encoding="utf-8").read()
    ok("MdCG.judge_qualification(node_dict, query, context)" in mdsrc,
       "G6d mdcos 的 legacy 分支仍委托 MdCG.judge_qualification（不在副本里重判）")
    # G6e/G6f：批次76 同批收口的**陈旧副本**——`_ccg_line` 自称「与 mdcos._ccg_field
    # 同源」，实为手抄且停在「必须有冒号」的旧语义（旧副本取空／单点非空实测 93 条）。
    from . import nodefile as _nf
    rwin = src[src.index("def _ccg_line"):src.index("def _ccg_line") + 1400]
    ok("nodefile.ccg_field_value(content, name)" in rwin,
       "G6e _ccg_line 委托单点（不许再手抄一行扫描）")
    c_nocolon = ("# 功能名\n无冒号形态的取值\n# 生效条件\n问某种问句\n# 子功能\nx\n"
                 "# 执行\nx\n# 验证方式\n编译器/静态检查通过\n# 不适用条件\n其它\n")
    ok(MdCG._ccg_line(c_nocolon, "生效条件") == _nf.ccg_field_value(c_nocolon, "生效条件")
       and (MdCG._ccg_line(c_nocolon, "生效条件") or "").strip() != "",
       "G6f 行为逐字一致：无冒号形态两侧取到同一个非空值（旧副本在此返回空串）",
       repr(MdCG._ccg_line(c_nocolon, "生效条件")))


# ---------------------------------------------------------------- G7 端到端
def g7():
    print("== G7 端到端（临时库真建节点）==")
    from .mdcos import MdCGOS
    tmp = tempfile.mkdtemp(prefix="negcond_")
    cg = MdCGOS(tmp)
    doc = ("# 功能名：写入闸门对 tags 的扫描面\n"
           "# 生效条件：问写入闸门内容闸门的判据时\n"
           "# 子功能：md_cg/writepipe.py\n# 执行：读闸门代码\n"
           "# 验证方式：编译器/静态检查通过\n"
           "# 不适用条件：本条不覆盖 tags 字段的扫描面，闸门只扫 content\n")
    cg.add("nc1", doc, layer="knowledge", verification_basis="test",
           non_applicable_conditions=["本条不覆盖 tags 字段的扫描面，闸门只扫 content"])
    neg_doc = ("# 功能名：否定事件节点\n"
               "# 生效条件：时间：即时情境\n"
               "# 子功能：子功能说明\n# 执行：执行说明\n"
               "# 验证方式：编译器/静态检查通过\n"
               "# 不适用条件：刚才在干什么\n")
    cg.add("nc2", neg_doc, layer="knowledge", verification_basis="test",
           non_applicable_conditions=["刚才在干什么"])
    cg.flush()
    q1 = MdCG.judge_qualification({"frontmatter": (cg.get("nc1") or {}).get("frontmatter") or {},
                                   "content": (cg.get("nc1") or {}).get("content") or ""},
                                  "写入闸门 tags 的扫描面", None)
    ok(q1["state"] != "REJECT",
       "G7 自主题问句不再 REJECT（state=%s）" % q1["state"], q1)
    q2 = MdCG.judge_qualification({"frontmatter": (cg.get("nc2") or {}).get("frontmatter") or {},
                                   "content": (cg.get("nc2") or {}).get("content") or ""},
                                  "你刚才在干什么", None)
    ok(q2["state"] == "REJECT",
       "G7a 语料式否定节点仍 REJECT（state=%s）" % q2["state"], q2)


def main() -> int:
    base = "--head-baseline" in sys.argv
    if base:
        print("!! 红基线模式：neg_condition_hits 临时替换回旧实现，断言应当转红")
        M.neg_condition_hits = _old_hits
        import md_cg.mdcg as _m
        _m.neg_condition_hits = _old_hits
        globals()["neg_condition_hits"] = _old_hits
    for g in (g1, g2, g3, g4, g5, g6, g7):
        g()
    if base:
        print("\n== 红基线判定：应有失败 ==")
        print("红基线失败数 = %d（>0 才算断言有判别力）" % len(_FAIL))
        for f in _FAIL:
            print("   红:", f)
        return 0 if _FAIL else 1
    print("\n负条件判据守卫：%d 通过，%d 失败" % (len(_PASS), len(_FAIL)))
    return 0 if not _FAIL else 1


if __name__ == "__main__":
    sys.exit(main())
