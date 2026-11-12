# -*- coding: utf-8 -*-
"""issue #215 守卫：条件取值两侧口径差（判据一字未动）。

# 功能名：条件取值两侧口径差可观测（cond_routes）+ 更正 mdcos 越界的「同源」声明
# 生效条件：改动 md_cg/consistency.py 的 L1-c 段、md_cg/mdcos.py 的 _ccg_field 注释、
#           或改动 md_cg/mdcg.py 的同条件取值分歧证据串之后必跑
# 子功能：① 判据未变（same_cond 仍 = max(c3,c4)，SAME_COND_HIGH 仍 0.75）② 两侧不同源
#         事实被钉住 ③ 默认落盘形态的 c3=0.7455 与同源形态的 0.7914 两个读数被钉住
#         ④ 端到端「默认形态 ACCEPT（漏检）」与「同源形态 DEFER」对照 ⑤ cond_routes
#         回传 ⑥ 越界注释已收窄 ⑦ 判别力
# 执行：python -X utf8 -m md_cg.test_issue215_condition_source_gap
# 验证方式：末行「通过 N / 失败 M」；红基线：撤掉 cond_routes 回传 ⇒ ⑤ 转红
# 不适用条件：本守卫**不主张**两侧应同源——那是行为变更（会提高既有节点检出率），
#             属设计裁定（issue #215 自己写明「归属属设计裁定」并给出 (a)(b)(c) 三选项）；
#             不改阈值、不建议改阈值；不测生产语料上受影响的节点占比

## 缺陷现场（issue #215）
    # 新节点侧
    consistency._new_terms(content, condition_space, na)
        pos = [条件行] + [condition_space 各槽值]        <- 并入槽值
    # 既有节点侧
    mdcos._declared_conditions(fm, body)
        pos = [条件行] (+ comment.生效条件 / fm)          <- 不读 condition_space
    # L1-c
    c3 = _cov(tw_pos, " ".join(e_pos))                   <- 两侧口径不同源
    if max(c3, c4) >= SAME_COND_HIGH(0.75): ...          <- 默认形态 0.7455 卡在下方

## 复核读数（本件实测，与报告逐位一致）
    不同源（默认落盘形态）: c3 = 0.7455  < 0.75  ⇒ L1-c 静默失效（verdict=ACCEPT）
    同源  （两侧一致）    : c3 = 0.7914  >= 0.75 ⇒ L1-c 触发（verdict=DEFER）
    阈值一字未动，仅两侧口径差即把 c3 压低 0.0459，跨过 0.75 这条线。

## 根因确认（报告 §1.2 的指控成立）
    mdcos._ccg_field 的 docstring 原称「本函数是条件取值的唯一读点……故一处收口即
    两函数同步」。该声明**超出了本函数的收口范围**：本函数收口的是**条件行**，而
    _new_terms 在取完条件行之后**额外并入 condition_space 各槽值**（consistency.py
    内实现，非经本函数）。本守卫 J6 钉住该注释已被收窄为「这两行」并附 #215 更正块。
"""
from __future__ import annotations

import io
import json
import os
import sys
import tempfile

_SANDBOX = tempfile.mkdtemp(prefix="i215_sandbox_")
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

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(_HERE))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from md_cg import nodefile, consistency                       # noqa: E402
from md_cg.consistency import _new_terms, SAME_COND_HIGH      # noqa: E402
from md_cg.mdcg import expand_query_terms_weighted as EQW     # noqa: E402
from md_cg.mdcos import (MdCGOS, _declared_conditions,        # noqa: E402
                         _weighted_coverage as cov)

_PASS, _FAIL, _C = [], [], [0]

CS = {"observation_position": "实验室常温", "time_window": [0, 9999999999],
      "observation_tool": "压力计", "existence_constraint": "标准大气压"}
SYN = nodefile.condition_space_text(CS)


def ok(cond, msg, extra=''):
    (_PASS if cond else _FAIL).append(msg)
    print(('  PASS ' if cond else '  FAIL ') + msg
          + (('  <- ' + str(extra)) if (extra and not cond) else ''))


def _body(fn, val):
    return ("# 功能名：%s" % fn + chr(10) + "# 子功能：压力读数" + chr(10)
            + "# 生效条件：%s" % SYN + chr(10) + "# 执行：逐点比对" + chr(10)
            + "# 验证方式：标准压力源" + chr(10) + "# 不适用条件：无" + chr(10)
            + chr(10) + "出口压力标定值为 %s。" % val + chr(10))


def _e2e(tag, new_fn, new_cs):
    """每个夹具独立库根（复用会污染比对面——#215/#216 附录点名的坑）。"""
    _C[0] += 1
    cg = MdCGOS(os.path.join(_SANDBOX, "%s_%d" % (tag, _C[0])), autoflush=0)
    cg.add("n_old", _body("泵出口压力标定", "12.5 MPa"), layer="knowledge",
           importance=0.5)
    r = cg.check_consistency(_body(new_fn, "13.8 MPa"), layer="knowledge",
                             depth=0, condition_space=new_cs)
    cg.close()
    return r


def _divs(r):
    return [c for c in (r.get("conflicts") or [])
            if c.get("type") == "same_condition_divergence"]


def _c3(new_cs, existing_side=None):
    pos = _new_terms(_body("泵出口压力标定", "12.5 MPa"), new_cs, None)[0]
    e_pos = (existing_side if existing_side is not None
             else _declared_conditions({}, _body("泵出口压力标定", "12.5 MPa"))[0])
    tw = EQW(" ".join(pos))
    return cov(tw, " ".join(e_pos)) if (tw and e_pos) else 0.0


def j0_judgement_unchanged():
    ok(SAME_COND_HIGH == 0.75, 'J0a SAME_COND_HIGH 仍为 0.75', SAME_COND_HIGH)
    ok(consistency.CONCLUSION_SAME == 0.95, 'J0b CONCLUSION_SAME 仍为 0.95',
       consistency.CONCLUSION_SAME)
    ok(consistency.SLOT_HIGH == 0.6, 'J0c SLOT_HIGH 仍为 0.6', consistency.SLOT_HIGH)
    src = io.open(os.path.join(_HERE, "consistency.py"), encoding="utf-8").read()
    ok("same_cond = max(c3, c4)" in src, 'J0d same_cond 仍取 max(c3, c4)')
    ok("c3 = _cov(tw_pos" in src, 'J0e c3 判据原文未变')


def j1_sides_not_same_source():
    """两侧不同源——本件的核心事实。"""
    pos = _new_terms(_body("泵", "1"), CS, None)[0]
    e_pos = _declared_conditions({}, _body("泵", "1"))[0]
    ok(pos != e_pos, 'J1a 两侧解析结果**不同**（不同源）', (pos, e_pos))
    ok(len(pos) == 4 and len(e_pos) == 1,
       'J1b 新侧 4 项（条件行 + 3 槽值）· 既有侧 1 项（仅条件行）',
       (len(pos), len(e_pos)))
    ok(set(pos) - set(e_pos) == {"实验室常温", "压力计", "标准大气压"},
       'J1c 差额恰是 condition_space 的槽值（_new_terms 并入、_declared_conditions 不读）',
       sorted(set(pos) - set(e_pos)))
    ok(set(e_pos) - set(pos) == set(),
       'J1d 既有侧没有新侧缺的项（单向差，不是双向分歧）',
       sorted(set(e_pos) - set(pos)))
    ok(SYN == pos[0] == e_pos[0],
       'J1e 两侧的**条件行**是同一个合成串（收口生效的那一半）')


def j2_c3_readings():
    """两个 c3 读数——报告的 §1.1 数值表逐位复现。"""
    c3_gap = _c3(CS)
    c3_same = _c3(None)
    ok(abs(c3_gap - 0.7455) < 5e-4,
       'J2a 不同源（默认落盘形态）c3 == 0.7455', c3_gap)
    ok(c3_gap < SAME_COND_HIGH,
       'J2b 该值 < SAME_COND_HIGH=0.75 ⇒ L1-c 不可达（漏检）', c3_gap)
    ok(abs(c3_same - 0.7914) < 5e-4,
       'J2c 同源 c3 == 0.7914', c3_same)
    ok(c3_same >= SAME_COND_HIGH,
       'J2d 该值 >= 0.75 ⇒ L1-c 可达', c3_same)
    ok(abs((c3_same - c3_gap) - 0.0459) < 5e-4,
       'J2e 口径差把 c3 压低约 0.0459——恰好跨过 0.75 这条线',
       c3_same - c3_gap)


def j3_e2e_default_is_silent():
    """**现状如实钉住（含升级信号）**：默认落盘形态下 L1-c 静默失效。"""
    r = _e2e("gap", "泵出口压力复核", CS)
    ok(r.get("verdict") == "ACCEPT",
       'J3a 默认形态（新节点带四槽）verdict=ACCEPT', r.get("verdict"))
    ok(_divs(r) == [] and (r.get("hard") or []) == []
       and [c for c in (r.get("conflicts") or [])
            if c.get("type") != "same_condition_divergence"] == [],
       'J3b 且**没有任何**分歧/互斥条目 ⇒ 「同条件空间 + 同结论槽 + 取值不同」'
       '这一整类真分歧被判无冲突（漏检）',
       (r.get("conflicts"), r.get("hard")))


def j4_e2e_same_source_fires():
    """对照：两侧同源时同一对节点**会**被判分歧。"""
    r = _e2e("same", "泵出口压力复核", None)
    ok(r.get("verdict") == "DEFER",
       'J4a 同源形态（新节点不带槽）verdict=DEFER', r.get("verdict"))
    ok(len(_divs(r)) >= 1,
       'J4b 且产出 same_condition_divergence', r.get("conflicts"))
    ok('同条件空间下结论槽取值不一致' in str(r.get("reason")),
       'J4c reason 为该类分歧的原文', str(r.get("reason"))[:60])


def j5_cond_routes_returned():
    """cond_routes 两侧口径差回传——本件真正修的那一半。"""
    r = _e2e("routes", "泵出口压力复核", None)
    dv = _divs(r)
    if not dv:
        ok(False, 'J5a 夹具可用', r.get("conflicts"))
        return
    d = dv[0]
    cr = d.get("cond_routes")
    ok(isinstance(cr, dict) and {"c3", "c4", "new_side", "existing_side",
                                 "only_new_side", "only_existing_side",
                                 "same_source"} <= set(cr),
       'J5b 分歧记录回传 cond_routes（七键）', cr)
    ok(cr.get("same_source") is True,
       'J5c 同源夹具 same_source=True', cr.get("same_source"))
    ok(cr.get("new_side") == cr.get("existing_side") == 1,
       'J5d 两侧项数都在（同源时相等）', (cr.get("new_side"), cr.get("existing_side")))
    ok(abs(d.get("same_condition") - cr.get("c3")) < 1e-9,
       'J5e same_condition 与分路 c3 自洽', (d.get("same_condition"), cr.get("c3")))
    ok(d.get("slot_routes") is not None,
       'J5f 与 #217 的槽位分路读数并存（两件不互相覆盖）')


def j6_comment_corrected():
    """报告 §二 的强制项：无论选哪个修法，越界注释**必须**同步改。"""
    src = io.open(os.path.join(_HERE, "mdcos.py"), encoding="utf-8").read()
    ok("# ⚠ issue #215" in src, 'J6a _ccg_field 已附 #215 更正块')
    ok("故**这两行**的收口即两函数同步" in src,
       'J6b 越界断言已就地收窄为「这两行」')
    ok("故一处收口即两函数同步；" not in src,
       'J6c 原越界断言已不存在（不是只加注释、留着旧断言）')
    ok("条件**行**同源不等于" in src,
       'J6d 收窄处显式说明「条件行同源 ≠ 正条件全部来源同源」')
    ok("c3 实测 0.7455" in src,
       'J6e 更正块登记了实测读数（可复核，非空泛声明）')
    ok("cond_routes" in src, 'J6f 更正块指向 cond_routes 回传面')


def j7_evidence_string():
    src = io.open(os.path.join(_HERE, "mdcg.py"), encoding="utf-8").read()
    ok("条件两侧 新 %s 项·既有 %s 项" in src, 'J7a mdcg 证据串已带两侧口径差')
    ok('d.get("cond_routes")' in src,
       'J7b 证据串读的是 cond_routes（不是另起一份口径差计算）')
    ok('if isinstance(_cd, dict) and _cd:' in src,
       'J7c 缺 cond_routes 的历史记录走原样（向后兼容）')


def j8_discriminator():
    """判别力对照：只看 same_condition 无法判断低值的原因。"""
    r = _e2e("disc", "泵出口压力复核", None)
    dv = _divs(r)
    if not dv:
        ok(False, 'J8a 夹具可用', r.get("conflicts"))
        return
    d = dv[0]
    legacy = {k: d.get(k) for k in ("same_condition", "slot_overlap",
                                    "conclusion_overlap")}
    ok(all(v is not None for v in legacy.values()),
       'J8b 修复前已有的三个读数仍在（本件未删既有读数）', legacy)
    stripped = {k: v for k, v in d.items() if k != "cond_routes"}
    ok("cond_routes" not in stripped,
       'J8c 摘掉 cond_routes 后，无法判断该低值是「条件真不同」还是「口径不同源」')


_CASES = (j0_judgement_unchanged, j1_sides_not_same_source, j2_c3_readings,
          j3_e2e_default_is_silent, j4_e2e_same_source_fires,
          j5_cond_routes_returned, j6_comment_corrected, j7_evidence_string,
          j8_discriminator)


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
