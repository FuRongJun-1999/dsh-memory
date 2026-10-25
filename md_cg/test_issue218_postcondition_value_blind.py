# -*- coding: utf-8 -*-
"""issue #218 守卫：postcondition_terms 两条出口的回传面（判据一字未动）。

# 功能名：index_key_hits 的 post/reject 分支回传面结构化（post_source/reject_source）
# 生效条件：改动 md_cg/mdcg.py 的 index_key_hits、或改动 nodefile.CCG_CONTRACT_ROLES
#           旁的 #218 登记注释之后必跑
# 子功能：① 判据未变（hit/post/reject/why 逐位不变，只新增字段）② 生产同源词项下的
#         真值表被如实钉住 ③ **更正报告 §1.2**（compiler 确实走 term 分支）④ declared
#         分支值盲（5 个不同取值 -> 1 种输出）⑤ post_source 使分支机器可读 ⑥ 判别力
# 执行：python -X utf8 -m md_cg.test_issue218_postcondition_value_blind
# 验证方式：末行「通过 N / 失败 M」；红基线：撤掉 post_source 新增 ⇒ ②③⑤⑥ 转红
# 不适用条件：本守卫**不主张** declared 分支应被取消或收紧——那是行为变更，属设计
#             裁定（issue #218 自己倾向选项 (a)「零行为变更 + 诚实归类」）；不改阈值；
#             不测生产语料上「验证方式」取值的实际分布

## 缺陷现场（issue #218）
    post = e.get(POSTCONDITION_TERMS_KEY) or []
    if post:
        if any(t in " ".join(post) for t in (terms or [])):   # 出口 1：term
            hits["post"] = True; hits["why"].append("postcondition_terms:term")
        elif is_postcondition_query(q):                        # 出口 2：declared
            hits["post"] = True; hits["why"].append("postcondition_terms:declared")

## 复核结论（与报告一处重要不同，本守卫按实测钉）
报告 §1.1 表中「查询 A = compiler 是怎么实现的」一行报 post=False，并据此在 §1.2
**更正上游 #181**（#181 称「仅 compiler 走 term 分支」）。本件实测**不可复现该更正**：

  · 生产同源词项 = expand_query_terms(查询)（mdcg.search :4042 即此调用），
    它对查询 A 返回 ['compiler 是怎么实现的', 'compiler', '是怎么实现的', ...]
    —— **裸词 compiler 在其中**；
  · 节点侧 postcondition_terms = ['compiler']，" ".join(post) = 'compiler'；
  · 故 'compiler' in 'compiler' 为真 ⇒ 走 term 分支。
  · 同一代码在报告所称分支 origin/level0000x（5e9c313e）上**逐字相同**（已核对），
    故该读数在作者自身分支上亦不可复现——应源于探针取的 terms 非生产口径。

⇒ **#181 的读数是对的**；报告 §1.2 的「更正」不成立。
报告真正成立的是：declared 出口**值盲**——但那是**刻意设计**（见下）。

## 两条出口的真实语义
  · term     —— **值敏感**，但可达性取决于**查询**是否含该值（不是值的质量）；
  · declared —— **值盲**：验证方式问句 + 该行切分后非空即命中，任意非空取值同输出。
    代码 docstring 明写这是设计（「声明了验证方式即召回」），与 rejection_terms 的
    边界问句同构。故它不是缺陷，而是**未在回传面登记的语义**。
"""
from __future__ import annotations

import io
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(_HERE))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from md_cg import nodefile                                    # noqa: E402
from md_cg.mdcg import (expand_query_terms, is_postcondition_query,  # noqa: E402
                        index_key_hits)

_PASS, _FAIL = [], []
QA = "compiler 是怎么实现的"          # 普通问句（is_postcondition_query=False）
QB = "这个结论是怎么验证的"           # 验证方式问句（=True）
VALS = ["measurement", "compiler", "textbook", "任意乱写的值", "zzz", "x", "无"]


def ok(cond, msg, extra=''):
    (_PASS if cond else _FAIL).append(msg)
    print(('  PASS ' if cond else '  FAIL ') + msg
          + (('  <- ' + str(extra)) if (extra and not cond) else ''))


def _entry(v):
    return {nodefile.POSTCONDITION_TERMS_KEY:
            nodefile.ccg_element_terms("# 验证方式：%s\n" % v,
                                       nodefile.POSTCONDITION_FIELD)}


def _hit(v, q):
    return index_key_hits(_entry(v), expand_query_terms(q), q)


def j0_judgement_unchanged():
    ok(is_postcondition_query(QA) is False, 'J0a 查询 A 非验证方式问句')
    ok(is_postcondition_query(QB) is True, 'J0b 查询 B 是验证方式问句')
    ok(nodefile.ELEMENT_TERM_MIN == 2, 'J0c ELEMENT_TERM_MIN 仍为 2',
       nodefile.ELEMENT_TERM_MIN)
    src = io.open(os.path.join(_HERE, "mdcg.py"), encoding="utf-8").read()
    # issue #652：term 出口加了折叠（terms 与 post 两侧同口径），判据原文随之更新；
    # 断言的是「仍是同一处单点门控」，不是逐字不变。
    ok('if any(t and fold_accents(t) in _post_folded for t in (terms or [])):' in src,
       'J0d term 出口判据原文未变（含 #652 折叠臂）')
    ok("elif is_postcondition_query(q):" in src,
       'J0e declared 出口判据原文未变（本件未取消它）')


def j1_truth_table():
    """生产同源词项下的真值表——本守卫的核心事实表。"""
    seen_a, seen_b = {}, {}
    for v in VALS:
        a, b = _hit(v, QA), _hit(v, QB)
        seen_a.setdefault((a["post"], a["post_source"]), []).append(v)
        seen_b.setdefault((b["post"], b["post_source"]), []).append(v)
        print('  DATA J1 %-12s A: post=%-5s src=%-9s | B: post=%-5s src=%s'
              % (v, a["post"], a["post_source"], b["post"], b["post_source"]))
    # A（普通问句）上取值可分：>=2 种输出。
    ok(len(seen_a) >= 2,
       'J1z 普通问句 A 上取值可分（>=2 种可观测输出）', len(seen_a))
    # B（验证方式问句）上：除「切分后为空/过短」（x / 无）这一桶外，
    # 其余**全部**取值落进同一个桶 ⇒ 值盲。
    empty_bucket = [k for k, v in seen_b.items() if k == (False, None)]
    ok(len(seen_b) == 2 and len(empty_bucket) == 1,
       'J1za B 上只有两桶：一个 declared 桶 + 一个「切分后为空」桶',
       sorted(seen_b))
    ok(len(seen_b[(True, "declared")]) == 5,
       'J1zb B 上 5 个不同取值全落进同一个 declared 桶（值盲）',
       seen_b.get((True, "declared")))


def j2_term_reachable_on_ordinary_query():
    """**更正报告 §1.2**：compiler 在普通问句 A 上确实走 term 分支（#181 是对的）。"""
    h = _hit("compiler", QA)
    ok(h["post"] is True,
       'J2a compiler + 普通问句 A ⇒ post=True（报告报 False，实测为 True）', h)
    ok(h["post_source"] == "term",
       'J2b 其出口是 term（值命中）——即 #181「仅 compiler 走 term 分支」成立',
       h["post_source"])
    ok("compiler" in expand_query_terms(QA),
       'J2c 机制：生产同源词项 expand_query_terms(A) 含裸词 compiler',
       expand_query_terms(QA))
    ok(_hit("measurement", QA)["post"] is False,
       'J2d 对照：查询 A 不含 measurement ⇒ 该值不命中（A 上是值敏感的）')
    ok(_hit("textbook", QA)["post"] is False,
       'J2e 对照：查询 A 不含 textbook ⇒ 不命中')


def j3_declared_is_value_blind():
    """declared 出口值盲（**刻意设计**，本守卫如实钉住、不主张取消）。"""
    blind = [v for v in VALS if _hit(v, QB)["post_source"] == "declared"]
    ok(len(blind) >= 4,
       'J3a 验证方式问句 B 上多个不同取值同走 declared', blind)
    outs = {( _hit(v, QB)["post"], _hit(v, QB)["post_source"]) for v in blind}
    ok(len(outs) == 1,
       'J3b 这些取值在 B 上产生**同一**可观测输出（值盲）', outs)
    ok(_hit("任意乱写的值", QB)["post"] is True
       and _hit("textbook", QB)["post"] is True,
       'J3c 乱写的值与 textbook 在 B 上不可区分（报告的 §1.1 核心主张，成立）')
    ok(_hit("x", QB)["post"] is False,
       'J3d 例外：切分后词长 < ELEMENT_TERM_MIN 的取值不命中（"x" 被剔）')
    ok(_hit("无", QB)["post"] is False,
       'J3e 例外：哨兵值「无」切分后为空，同样不命中')


def j4_source_field_is_the_new_observable():
    """post_source 使「是哪一条出口」机器可读——本件真正修的那一半。"""
    a = _hit("compiler", QA)
    b = _hit("任意乱写的值", QB)
    ok(a["post_source"] == "term", 'J4a 值命中 ⇒ post_source="term"', a["post_source"])
    ok(b["post_source"] == "declared",
       'J4b 仅声明命中 ⇒ post_source="declared"', b["post_source"])
    ok(a["post"] == b["post"] is True,
       'J4c 两者 post 都是 True —— 修复前**仅凭 post 无法区分**（本字段的存在理由）')
    ok("post_source" in a and "reject_source" in a,
       'J4d 两字段都在回传体上（含未命中时）', sorted(a))
    ent = {nodefile.REJECTION_TERMS_KEY: ["其它会话"]}
    r = index_key_hits(ent, ["其它会话"], "何时不适用")
    ok(r["reject_source"] == "declared", 'J4e reject 出口同样有结构化来源', r)
    r2 = index_key_hits({}, ["x"], "普通问句")
    ok(r2["post_source"] is None and r2["reject_source"] is None,
       'J4f 未命中时来源为 None（不谎报出口）', r2)


def j5_existing_vocabulary():
    """报告选项 (c) 建议「设词表校验」——**词表已有真源**，不需新造。"""
    ok(isinstance(nodefile.VERIFICATION_BASIS, tuple)
       and "measurement" in nodefile.VERIFICATION_BASIS
       and "textbook" in nodefile.VERIFICATION_BASIS,
       'J5a VERIFICATION_BASIS 已是「验证方式」取值的受控词集',
       nodefile.VERIFICATION_BASIS)
    ok("compiler" in nodefile.VERIFICATION_BASIS,
       'J5b 其中含 compiler（与 #181 所述 term 分支的示例值同源）')
    src = io.open(os.path.join(_HERE, "nodefile.py"), encoding="utf-8").read()
    ok("# ---- issue #218" in src,
       'J5c CCG_CONTRACT_ROLES 旁已登记召回面语义（选项 (a) 的落地形态）')
    ok("post_source" in src, 'J5d 登记注释指向 post_source 字段')


def j6_discriminator():
    """判别力对照：只读 post 的消费者无法区分两条出口。"""
    a, b = _hit("compiler", QA), _hit("任意乱写的值", QB)
    legacy = {k: (a[k], b[k]) for k in ("hit", "post", "reject")}
    ok(legacy["post"] == (True, True) and legacy["reject"] == (False, False),
       'J6a 只看 hit/post/reject：两个语义不同的命中**完全相同**', legacy)
    ok(a["why"] != b["why"],
       'J6b why 其实已带分支信息——但它只被守卫消费（检索/裁决面读不到）',
       (a["why"], b["why"]))
    ok(a["post_source"] != b["post_source"],
       'J6c post_source 是第一个**结构化**且可被消费者读取的分支读数')


_CASES = (j0_judgement_unchanged, j1_truth_table,
          j2_term_reachable_on_ordinary_query, j3_declared_is_value_blind,
          j4_source_field_is_the_new_observable, j5_existing_vocabulary,
          j6_discriminator)


def _run_all():
    del _PASS[:], _FAIL[:]
    for fn in _CASES:
        print(chr(10) + '== %s' % fn.__name__)
        try:
            fn()
        except Exception as exc:            # noqa: BLE001
            import traceback
            _FAIL.append('%s 抛异常' % fn.__name__)
            print('  FAIL %s 抛异常：%s: %s' % (fn.__name__, type(exc).__name__, exc))
            traceback.print_exc()
    print(chr(10) + '通过 %d / 失败 %d' % (len(_PASS), len(_FAIL)))
    for m in _FAIL:
        print('  - ' + m)
    return 1 if _FAIL else 0


if __name__ == '__main__':
    raise SystemExit(_run_all())
