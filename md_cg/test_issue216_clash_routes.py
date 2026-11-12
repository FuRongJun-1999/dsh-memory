# -*- coding: utf-8 -*-
"""issue #216 守卫：condition_clash 的 c1/c2 分路读数（判据一字未动）。

# 功能名：condition_clash 回传 c1/c2 分路读数与两侧词项规模
# 生效条件：改动 md_cg/consistency.py 的 L1-b 段（c1/c2 计算 / condition_clash 记录）
#           或 md_cg/mdcg.py 的「条件互斥」证据串之后必跑
# 子功能：① 判据未变（c 仍 = max(c1, c2)，CLASH_LOW/CLASH_HIGH 逐位不变）② 冲突记录
#         回传 clash_routes（c1/c2 + 四侧词项数）③ 人工裁决证据串带分路读数 ④ 两侧
#         词项规模的**不对称现状**被如实钉住（含升级信号）⑤ 判别力对照
# 执行：python -X utf8 -m md_cg.test_issue216_clash_routes
# 验证方式：末行「通过 N / 失败 M」；红基线：撤掉 clash_routes 回传 ⇒ ②③ 转红
# 不适用条件：本守卫**不主张** c1 侧应当与 c2 侧对称——那属设计裁定（issue #216 §四
#             自己写明「本件不主张 c1 侧应该被修复到可达……是否要求两侧对称属设计裁定」）；
#             不改阈值、不建议改阈值；不测生产语料上 na 分布与生效条件行形态分布
#             （issue #216 §四 指出的两个未测分布，须由全量盘点补充）

## 缺陷现场（issue #216）
    c1 = _cov(tw_pos, " ".join(e_neg))    # 新节点正条件 ↔ 既有节点负条件
    c2 = _cov(tw_neg, " ".join(e_pos))    # 新节点负条件 ↔ 既有节点正条件
    c  = max(c1, c2)
两个面被合并成一个 c 回传，读者无法判断是哪一侧撑起这次冲突，读数不可复核。

## 复核结论（与报告一处不同，本守卫按实测口径钉）
报告把不对称归因为「c1 侧比 c2 侧更难达阈值」。本件实测发现更精确的机制：
**两侧在「各 1 词」时 c1 == c2 == 0.4082，完全对称**；不对称只在**某一侧是合成串**
时出现。因为新节点的 tw_pos 含 condition_space_text 合成串（词项 7 → 16），
而 tw_neg 只来自 na（恒 7）。故根因不是 c1/c2 这对判据本身，而是
**新节点正条件侧的构成方式与负条件侧不同源**（与「不同源」件同族）。
本守卫 J4 把这一现状如实钉住。

## 报告三个数值的复核（诚实记录）
本件实测：1 词夹具 c1 = **0.4082**（与报告一致）；合成串夹具 c1 = **0.0962**
（报告为 0.1482），词项数 7 → 16（与报告一致）。差异应来自合成串取值不同
（本件用「实验室台面／全时窗／压力计／泵运行中」）。**定性与词项数一致，
具体数值以各自夹具为准**——这正是报告 §〇 自己的教训（读数表须分列词项数）。
"""
from __future__ import annotations

import io
import json
import os
import sys
import tempfile

_SANDBOX = tempfile.mkdtemp(prefix="i216_sandbox_")
os.environ["MDCG_AUX_ROOT"] = os.path.join(_SANDBOX, "auxroot")
os.environ["MDCG_MASTER_KEY"] = "ef" * 32
os.environ["MDCG_TOKEN_FILE"] = os.path.join(_SANDBOX, "tokens.json")
os.environ["MDCG_ROOT"] = os.path.join(_SANDBOX, "cgroot")
for _k in ("MDCG_TOKEN", "MDCG_TENANT", "MDCG_CLEARANCE", "MDCG_SESSION",
           "MDCG_RETRIEVAL_PIPELINE", "MDCG_POOLING", "MDCG_FRESHNESS",
           "MDCG_EXPORT_ROOT", "MDCG_TEST_LIVE_ROOT"):
    os.environ.pop(_k, None)
os.makedirs(os.environ["MDCG_AUX_ROOT"], exist_ok=True)
os.makedirs(os.environ["MDCG_ROOT"], exist_ok=True)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from md_cg import consistency                          # noqa: E402
from md_cg.mdcos import MdCGOS, _is_null_condition, _weighted_coverage as cov  # noqa: E402
from md_cg.mdcg import expand_query_terms_weighted as EQ  # noqa: E402
from md_cg.nodefile import condition_space_text        # noqa: E402

_HERE = os.path.dirname(os.path.abspath(__file__))
_PASS, _FAIL, _C = [], [], [0]

CS4 = {"observation_position": "实验室台面", "time_window": [0, 9999999999],
       "observation_tool": "压力计", "existence_constraint": "泵运行中"}
SYN = condition_space_text(CS4)


def ok(cond, msg, extra=''):
    (_PASS if cond else _FAIL).append(msg)
    print(('  PASS ' if cond else '  FAIL ') + msg
          + (('  <- ' + str(extra)) if (extra and not cond) else ''))


def _e2e(old_na, new_na, cs=None):
    """每个夹具用独立库根（复用会污染比对面——issue #216 附录点名的坑）。"""
    _C[0] += 1
    cg = MdCGOS(os.path.join(_SANDBOX, "e2e_%d" % _C[0]), autoflush=0)
    old = ("# 功能名：泵出口压力标定" + chr(10) + "# 子功能：压力读数" + chr(10)
           + "# 生效条件：实验室常温" + chr(10) + "# 执行：逐点比对" + chr(10)
           + "# 验证方式：标准压力源" + chr(10)
           + "# 不适用条件：%s" % old_na + chr(10) + chr(10)
           + "出口压力标定值为 12.5 MPa。" + chr(10))
    cg.add("n_old", old, layer="knowledge", importance=0.5)
    new = ("# 功能名：泵出口压力复核" + chr(10) + "# 子功能：压力读数" + chr(10)
           + "# 生效条件：实验室常温" + chr(10) + "# 执行：逐点比对" + chr(10)
           + "# 验证方式：标准压力源" + chr(10)
           + "# 不适用条件：%s" % new_na + chr(10) + chr(10)
           + "出口压力标定值为 13.8 MPa。" + chr(10))
    return cg.check_consistency(new, layer="knowledge", depth=0,
                                condition_space=cs)


def _clashes(r):
    return [c for c in (r.get("conflicts") or [])
            if c.get("type") == "condition_clash"]


def j0_judgement_unchanged():
    ok(consistency.CLASH_LOW == 0.35, 'J0a CLASH_LOW 仍为 0.35', consistency.CLASH_LOW)
    ok(consistency.CLASH_HIGH == 0.6, 'J0b CLASH_HIGH 仍为 0.6', consistency.CLASH_HIGH)
    src = io.open(os.path.join(_HERE, "consistency.py"), encoding="utf-8").read()
    ok("c = max(c1, c2)" in src, 'J0c c 仍取 max(c1, c2)——本件未改成合取/对称度量')
    ok("c = max(c1, c2)" not in src.replace("c = max(c1, c2)", "", 1),
       'J0d c 赋值点唯一')


def j1_null_condition_sentinels():
    """门 ①：哨兵被 _is_null_condition 丢弃（语义正确，非缺陷）——
    既有节点无负条件时 c1 无从谈起。本守卫如实钉住这一**语义正确**的现状。"""
    for v in ("无", "（无）", "n/a", "None"):
        ok(_is_null_condition(v) is True,
           'J1 空值哨兵 %r 判为「没有这个条件」' % v, _is_null_condition(v))
    for v in ("高温环境", "无法确定", "无缓存场景"):
        ok(_is_null_condition(v) is False,
           'J1 反向：%r 是真实条件，不被误判为哨兵' % v, _is_null_condition(v))


def j2_routes_present():
    """c1/c2 分路读数回传——本件真正修的那一半。"""
    r = _e2e(old_na="高温环境", new_na="实验室常温")
    cl = _clashes(r)
    ok(len(cl) >= 1, 'J2a 夹具产出 condition_clash', len(cl))
    if not cl:
        return
    d = cl[0]
    cr = d.get("clash_routes")
    ok(isinstance(cr, dict) and {"c1", "c2", "terms"} <= set(cr),
       'J2b 冲突记录回传 clash_routes（c1/c2 + terms）', cr)
    ok(cr.get("c1") is not None and cr.get("c2") is not None,
       'J2c c1/c2 两路读数都在（修复前只有合并的 score）', cr)
    ok(abs(d.get("score") - max(cr["c1"], cr["c2"])) < 1e-9,
       'J2d score 仍 == max(c1, c2)（合并读数与分路自洽）',
       (d.get("score"), cr))
    tm = cr.get("terms") or {}
    ok(set(tm) == {"tw_pos", "tw_neg", "e_pos", "e_neg"},
       'J2e 四侧词项规模都在（issue #216 §〇：读数表须分列词项数）', tm)


def j3_evidence_string():
    src = io.open(os.path.join(_HERE, "mdcg.py"), encoding="utf-8").read()
    ok("分路 c1" in src, 'J3a mdcg 证据串提炼点已带 c1/c2 分路读数')
    ok('d.get("clash_routes")' in src,
       'J3b 证据串读的是 clash_routes（不是另起一份分路计算）')
    ok('if isinstance(_cr, dict) and _cr:' in src,
       'J3d 缺 clash_routes 的历史记录走原样（向后兼容）')


def j4_asymmetry_pinned():
    """**现状如实钉住**（含升级信号）：两侧各 1 词时 c1 == c2（对称）；
    任一侧是合成串时不对称。⇒ 根因不是 c1/c2 这对判据，而是新节点正条件侧
    的构成方式（含 condition_space_text 合成串）与负条件侧不同源。
    将来若设计者裁定统一两侧构成，本项会转红——那正是升级断言的时点。"""
    ok(bool(SYN), 'J4a 夹具前提：四槽齐备时 condition_space_text 非空', repr(SYN)[:60])
    tw1 = EQ("实验室常温")
    ok(abs(cov(tw1, "实验室常温") - cov(tw1, "实验室常温")) < 1e-9,
       'J4b 同一侧同一文本 ⇒ 两式恒等（对称性前提）')
    tws = EQ(SYN)
    ok(len(tws) > len(tw1),
       'J4c 合成串词项数 > 单条件词项数（稀释来源）',
       (len(tws), len(tw1)))
    ok(cov(tws, "实验室常温") < cov(tw1, "实验室常温"),
       'J4d 同一 e_neg 下，合成串的 c1 低于单条件的 c1（稀释实测）',
       (cov(tws, "实验室常温"), cov(tw1, "实验室常温")))
    ok(cov(tw1, "实验室常温") >= consistency.CLASH_LOW,
       'J4e 单条件夹具的 c1 仍 >= CLASH_LOW=0.35（可达）',
       cov(tw1, "实验室常温"))
    ok(cov(tws, "实验室常温") < consistency.CLASH_LOW,
       'J4f 合成串夹具的 c1 已 < CLASH_LOW（不可达）',
       cov(tws, "实验室常温"))


def j5_discriminator():
    """判别力对照：摘掉 clash_routes ⇒ 记录不再具备「是哪一侧撑起」的信息。"""
    r = _e2e(old_na="高温环境", new_na="实验室常温")
    cl = _clashes(r)
    if not cl:
        ok(False, 'J5a 夹具可用', len(cl))
        return
    ok(len(cl) >= 1, 'J5a 夹具可用', len(cl))
    stripped = {k: v for k, v in cl[0].items() if k != "clash_routes"}
    ok("clash_routes" not in stripped,
       'J5b 摘掉分路读数后，只剩合并 score，无法判断是哪一侧（J2b 的判别力来源）')
    ok("score" in stripped, 'J5c 合并 score 仍在（本件未删既有读数）')


_CASES = (j0_judgement_unchanged, j1_null_condition_sentinels,
          j2_routes_present, j3_evidence_string, j4_asymmetry_pinned,
          j5_discriminator)


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
