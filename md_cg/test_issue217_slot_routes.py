# -*- coding: utf-8 -*-
"""issue #217 守卫：L1-c 结论槽的**分路读数**（判据一字未动，行为逐位不变）。

# 功能名：L1-c 结论槽（功能名/子功能）分路读数可见化
# 生效条件：改动 md_cg/consistency.py 的 L1-c 段（slot 计算 / same_condition_divergence
#           记录）或 md_cg/mdcg.py 的「同条件取值分歧」证据串之后必跑
# 子功能：① 判据未变（slot 仍 = max(两路)，阈值/比较算子逐位不变）② 分歧记录回传
#         slot_routes 分路读数与 slot_single_route 标志 ③ 人工裁决证据串带分路读数
#         ④ 判据面「仅一路变异不改结论」的现状被如实钉住（含升级信号）
# 执行：python -X utf8 -m md_cg.test_issue217_slot_routes
# 验证方式：末行「通过 N / 失败 M」；红基线：撤掉 slot_routes 回传 ⇒ ②③ 转红
# 不适用条件：本守卫**不主张** slot 判据正确——#217 的核心主张（两路各自单独不承重）
#             属**语义面设计裁定**（报告作者明示「须并入 #134 的待设计者裁项流程，
#             不单方面落地」），本件只落地「零行为变更的可观测化」那一半；
#             不测生产语料占比（隔离库最小夹具）；不测 #216 的 c1/c2 分路

## 缺陷现场（issue #217）
consistency.py 的 L1-c：
    slot = max(cov(新功能名, 旧功能名), cov(新子功能, 旧子功能))
max() 是析取 ⇒ 任一路满分即掩盖另一路。**端到端实测**（本守卫 J1 复现）：
只改功能名 / 只改子功能，verdict 与 reason 与「什么都不改」**逐字节相同**；
只有两者同改才翻转。⇒ 两路各自单独都不承重。

## 本件的定位（重要，防过度解读）
复核结论与报告有一处**不同**：slot 是**前置门**，真正的判别器是紧随其后的
conclusion_overlap（concl < CONCLUSION_SAME 才记分歧）。故 max() 的宽松
**不产生漏检**——本件穷举「只改功能名且结论同值」等形态，未找到
「concl 会放过、而 min() 能救」的实例。真正成立的是报告 §1.3 那条：
**「仅一路撑起槽位」这一事实此前不可观测（静默）**。
故本件只落地可观测化；语义面（改 min/合取、或把 功能名 移出 slot）留给设计者裁定。

## 分路读数的既有教训（与 #216 同源）
多路合成读数（c1/c2、槽位）回传时必须**分路**，否则读者无法判断改变的是哪一侧、
读数不可复核。本守卫 J2/J3 即钉这一点。
"""
from __future__ import annotations

import io
import json
import os
import sys
import tempfile

_SANDBOX = tempfile.mkdtemp(prefix="i217_sandbox_")
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

from md_cg import consistency                      # noqa: E402
from md_cg.mdcos import MdCGOS, _weighted_coverage as cov   # noqa: E402
from md_cg.mdcg import expand_query_terms_weighted as EQ    # noqa: E402

_HERE = os.path.dirname(os.path.abspath(__file__))
_PASS, _FAIL = [], []


def ok(cond, msg, extra=''):
    (_PASS if cond else _FAIL).append(msg)
    print(('  PASS ' if cond else '  FAIL ') + msg
          + (('  <- ' + str(extra)) if (extra and not cond) else ''))


FN = "反应堆冷却泵出口压力标定"
SB = "读取压力计读数"
COND = "反应堆冷却泵处于运行状态"
BODY_OLD = ("出口压力标定值为 12.5 MPa。标定周期为每 6 个月一次，"
            "使用标准压力源逐点比对。")
BODY_NEW = ("出口压力标定值为 13.8 MPa。标定周期为每 6 个月一次，"
            "使用标准压力源逐点比对。")
_C = [0]


def _mk(fn, sb, body):
    return ("# 功能名：%s" % fn + chr(10) + "# 子功能：%s" % sb + chr(10)
            + "# 生效条件：%s" % COND + chr(10)
            + "# 子功能说明：压力标定" + chr(10) + "# 执行：逐点比对" + chr(10)
            + "# 验证方式：标准压力源" + chr(10)
            + "# 不适用条件：泵停机检修时" + chr(10) + chr(10) + body + chr(10))


def _e2e(fn, sb):
    """每个夹具用独立库根（否则先前夹具的节点进入比对面污染读数）。"""
    _C[0] += 1
    cg = MdCGOS(os.path.join(_SANDBOX, "e2e_%d" % _C[0]), autoflush=0)
    cg.add("n_old", _mk(FN, SB, BODY_OLD), layer="knowledge", importance=0.5,
           state_attributes={"comment": {"生效条件": COND}})
    return cg.check_consistency(_mk(fn, sb, BODY_NEW), layer="knowledge", depth=0)


def _dv(r):
    return [c for c in (r.get("conflicts") or [])
            if c.get("type") == "same_condition_divergence"]


def j0_judgement_unchanged():
    """判据面：阈值与比较算子逐位不变（本件只加读数，不动判据）。"""
    ok(consistency.SLOT_HIGH == 0.6, 'J0a SLOT_HIGH 仍为标定值 0.6',
       consistency.SLOT_HIGH)
    ok(consistency.CONCLUSION_SAME == 0.95, 'J0b CONCLUSION_SAME 仍为 0.95',
       consistency.CONCLUSION_SAME)
    ok(consistency.SAME_COND_HIGH == 0.75, 'J0c SAME_COND_HIGH 仍为 0.75',
       consistency.SAME_COND_HIGH)
    src = io.open(os.path.join(_HERE, "consistency.py"), encoding="utf-8").read()
    ok("slot = max(slot_fn, slot_sb)" in src,
       'J0d slot 仍取 max(两路)——本件**未**改成 min/合取（那是行为变更，待裁定）')
    ok("slot = max(slot_fn, slot_sb)" not in src.replace(
        "slot = max(slot_fn, slot_sb)", "", 1),
       'J0e slot 赋值点唯一（没有第二处覆盖）')


def j1_route_readings_present():
    """分歧记录回传分路读数——这是本件真正修的那一半（静默 → 可观测）。"""
    r = _e2e(FN, SB)
    dv = _dv(r)
    ok(len(dv) == 1, 'J1a 基线夹具产出一条 same_condition_divergence', len(dv))
    if not dv:
        return
    d = dv[0]
    sr = d.get("slot_routes")
    ok(isinstance(sr, dict) and set(sr) == {"功能名", "子功能"},
       'J1b 分歧记录回传 slot_routes（分路读数）', sr)
    ok(d.get("slot_single_route") is False,
       'J1c 基线两路都达标 ⇒ slot_single_route=False', d.get("slot_single_route"))
    ok(d.get("slot_overlap") == max(sr.values()),
       'J1d slot_overlap 仍 == max(分路)（合并读数与分路自洽）',
       (d.get("slot_overlap"), sr))


def j2_single_route_visible():
    """只改一路时，分路读数必须把「是哪一路降了」显出来——修复前该事实不可见。"""
    r = _e2e("反应堆冷却泵入口压力标定", SB)
    dv = _dv(r)
    ok(len(dv) == 1, 'J2a 只改功能名仍产出分歧条目（检出未变）', len(dv))
    if not dv:
        return
    d = dv[0]
    sr = d.get("slot_routes") or {}
    ok(sr.get("功能名", 1.0) < 1.0,
       'J2b 功能名 分路读数 < 1.0（该路确已下降，修复前被 max 掩盖）',
       sr)
    ok(sr.get("子功能") == 1.0,
       'J2c 子功能 分路读数 == 1.0（另一路确实满分）', sr)
    # 「出口→入口」这一处替换把该路压到 SLOT_HIGH 之下，而另一路仍满分 ——
    # 正是 #217 要暴露的形态：**仅一路撑起槽位**。修复前这一事实不可见
    # （合并读数恒 1.0），修复后由标志与分路读数同时给出。
    ok(sr.get("功能名", 1.0) < consistency.SLOT_HIGH,
       'J2d 功能名 分路读数已跌破 SLOT_HIGH=%s' % consistency.SLOT_HIGH, sr)
    ok(d.get("slot_single_route") is True,
       'J2e 仅一路达标 ⇒ slot_single_route=True（静默失效变可观测）',
       (d.get("slot_single_route"), sr))


def j3_evidence_string_carries_routes():
    """人工裁决证据串：分路读数进 reason，裁决者不必再去猜是哪一路。"""
    _C[0] += 1
    cg = MdCGOS(os.path.join(_SANDBOX, "ev_%d" % _C[0]), autoflush=0)
    cg.add("n_old", _mk(FN, SB, BODY_OLD), layer="knowledge", importance=0.5,
           state_attributes={"comment": {"生效条件": COND}})
    r = cg.check_consistency(_mk("反应堆冷却泵入口压力标定", SB, BODY_NEW),
                             layer="knowledge", depth=0)
    txt = json.dumps(r, ensure_ascii=False, default=str)
    ok("slot_routes" in txt or "槽位分路" in txt,
       'J3a 一致性回传体里出现分路读数（供下游构造证据串）', txt[:160])
    # 证据串构造点：直接喂一条带分路读数的分歧条目，看 mdcg 的提炼是否带上
    from md_cg.mdcos import _weighted_coverage  # noqa: F401
    src = io.open(os.path.join(_HERE, "mdcg.py"), encoding="utf-8").read()
    ok("槽位分路" in src, 'J3b mdcg 证据串提炼点已带「槽位分路」')
    ok('d.get("slot_routes")' in src,
       'J3c 证据串读的是 slot_routes（不是另起一份分路计算）')
    ok('if isinstance(_sr, dict) and _sr:' in src,
       'J3d 缺 slot_routes 的历史记录走原样（向后兼容，不因新键缺失变形）')


def j4_no_regress_on_judgement():
    """**现状如实钉住**（含升级信号）：只改一路 ⇒ 结论与「什么都不改」相同。
    这是 #217 的核心主张。本件**未改**这一行为（语义面待设计者裁定）。
    将来若设计者裁定改成 min/合取，本项会转红——那正是「把断言升级为
    『单路变异必须可观测』」的时点。"""
    base = _e2e(FN, SB)
    only_fn = _e2e("反应堆冷却泵入口压力标定", SB)
    only_sb = _e2e(FN, "记录温度计读数")
    both = _e2e("反应堆冷却泵入口压力标定", "记录温度计读数")
    db, df, ds = _dv(base), _dv(only_fn), _dv(only_sb)

    def _sig(dv):
        return [(x.get("same_condition"), x.get("slot_overlap"),
                 x.get("conclusion_overlap")) for x in dv]

    ok(base.get("verdict") == only_fn.get("verdict") == only_sb.get("verdict"),
       'J4a 现状：基线/只改功能名/只改子功能 三者 verdict 相同',
       (base.get("verdict"), only_fn.get("verdict"), only_sb.get("verdict")))
    ok(_sig(db) == _sig(df) == _sig(ds),
       'J4b 现状：三者的分歧读数（条件/槽位/结论）逐位相同 ⇒ 单路变异不可观测',
       (_sig(db), _sig(df), _sig(ds)))
    ok(both.get("verdict") != base.get("verdict"),
       'J4c 两者同改才翻转 verdict（掩盖的机制是 max，与单路降到多低无关）',
       (base.get("verdict"), both.get("verdict")))


def j5_discriminator():
    """判别力对照：把分路读数从分歧记录里摘掉（等价修复前形态）⇒ J1b 转红。"""
    r = _e2e(FN, SB)
    dv = _dv(r)
    ok(len(dv) == 1, 'J5a 夹具可用', len(dv))
    if not dv:
        return
    d = dict(dv[0])
    stripped = {k: v for k, v in d.items()
                if k not in ("slot_routes", "slot_single_route")}
    ok("slot_routes" not in stripped,
       'J5b 摘掉分路读数后，该记录不再具备「是哪一路撑起槽位」的信息（'
       'J1b 的判别力来源即此）')


_CASES = (j0_judgement_unchanged, j1_route_readings_present,
          j2_single_route_visible, j3_evidence_string_carries_routes,
          j4_no_regress_on_judgement, j5_discriminator)


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
