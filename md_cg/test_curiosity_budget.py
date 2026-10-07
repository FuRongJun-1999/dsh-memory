# -*- coding: utf-8 -*-
"""v1.2 组1 好奇线（§2.9.3.1 非任务探索）生产路径守卫：C1–C6。

契约：`docs/eval/好奇线_通电设计_v0.1.md` 文末「设计者位置 · 2026-10-07」九条 ＋ 守卫 C1–C6。
病灶（两处缺口，同 #25/#28 的「机制在位、生产路径不可达」）：
  缺口 a：`autonomy.explore(..., bypass_gain=True)` 机制在位，但生产入口
          `insight act="explore"`（`mdcos.MdCGOS.insight`）不传该参数 ⇒ 不可达。
  缺口 b：探索预算无显式声明位（真源 §2.9.3.1 要求「预算上限须显式声明并可审计」）。

修复：① `autonomy.budget_gate`（env `MDCG_EXPLORE_BUDGET_MAX`/`_WINDOW`，**缺省关**：
未设 env 即不豁免，请求未获准**回落任务定价**，非硬拒绝）；② 生产入口透传 `bypass_gain`；
③ MCP 面 schema ＋ 分发同步；④ 台账/返回体新增 `budget` 字段（只增）。

断言（每条可红）：
  C1 默认零变更（未设 env、不传 bypass_gain ⇒ 既有键面/行为逐位一致；能红「无条件开启」）；
  C2 开关生效（预算内 bypass_gain=True 冷却中照常探索 + 留痕；能红「旧实现/卸下挂载」）；
  C3 预算耗尽即回落任务定价（降级非硬拒绝；能红「无预算」）；
  C4 台账 `budget` 字段齐（可审计）；
  C5 豁免不改资格（score）与终排、不碰 import 面；
  C6 结构防悬空（生产入口真走到预算门 + MCP 面透传；注入「卸下挂载」必红）。

运行：
  python -X utf8 -m md_cg.test_curiosity_budget              # 正向 C1–C6
  python -X utf8 -m md_cg.test_curiosity_budget --self-proof # 定点变异自证

退出码：0 全绿；1 有断言失败/变异未按预期转红/基线非 0 红；
        2 **ANCHOR-MISS**（变异锚点在实现源码里找不到唯一命中——实现漂移硬失败）。
"""
from __future__ import annotations

import inspect
import json
import os
import re
import shutil
import tempfile
import textwrap
import time

from . import autonomy, metacognition
from .fsutil import append_jsonl
from .mdcos import MdCGOS

PASS = FAIL = 0
FAILS = []

QUERY = "反应堆冷却方案"
BID = metacognition._key(QUERY)

#: 既有（改动前）台账键集合——C1 要求默认路径**不新增**任何键（逐位一致的键面）。
EXPECTED_REC_KEYS = {"type", "t", "actor", "apply", "n_proposals", "bids",
                     "outcomes", "bypass_gain", "meta_outcomes",
                     "gain_deferred", "proposals"}
#: 既有（改动前）返回体键集合。
EXPECTED_OUT_KEYS = {"ok", "action", "apply", "proposals", "steps",
                     "n_signals", "deferred", "note"}

_BUDGET_ENVS = ("MDCG_EXPLORE_BUDGET_MAX", "MDCG_EXPLORE_BUDGET_WINDOW")


def ok(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  [PASS] {name}" + (f"  · {detail}" if detail else ""))
    else:
        FAIL += 1
        FAILS.append(name)
        print(f"  [FAIL] {name}  · {detail}")


class _Env:
    """预算 env 隔离：进入先清两个预算变量，按需置值；退出再清（不泄漏到邻检查）。"""

    def __init__(self, **kv):
        self.kv = kv

    def __enter__(self):
        for k in _BUDGET_ENVS:
            os.environ.pop(k, None)
        for k, v in self.kv.items():
            os.environ[k] = str(v)
        return self

    def __exit__(self, *a):
        for k in _BUDGET_ENVS:
            os.environ.pop(k, None)
        return False


# ---------------------------------------------------------------- 沙箱构造
def _root():
    return tempfile.mkdtemp(prefix="mdcg_curiosity_")


def _lib(root_sub):
    """临时库：含冷却盲区（σ=0）——豁免与回落两态在 steps 上可直接分辨。"""
    os.makedirs(root_sub, exist_ok=True)
    cg = MdCGOS(root_sub)
    cg.add("k1", "# 功能名：反应堆冷却知识\n"
                 "# 生效条件：问反应堆冷却方案\n"
                 "# 子功能：知识片段\n"
                 "# 执行：陈述知识\n"
                 "# 验证方式：test\n"
                 "# 不适用条件：无\n"
                 "反应堆冷却方案概述。\n",
           layer="knowledge", verification_basis="test")
    # 信息差信号（BLINDSPOT×2）→ 提案有资格（score>0）
    append_jsonl(cg.reflection_log,
                 {"t": 1.0, "query": QUERY, "d_prev": 1.0, "d_curr": 1.0,
                  "d_delta": 0.0, "d2": 0.9, "states": {"BLINDSPOT": 2},
                  "n_results": 3, "feedback": None})
    # 连续 2 次停滞终态 → σ(Gain)=0（冷却中）：豁免才放行，任务定价则拦
    t0 = time.time() - 10.0
    for i, tml in enumerate(["carried", "carried"]):
        append_jsonl(autonomy._explore_log_path(cg),
                     {"type": "explore", "t": t0 + i * 5.0, "actor": "test",
                      "outcomes": {BID: tml}, "bids": [BID]})
    return cg


def _last_rec(cg):
    with open(autonomy._explore_log_path(cg), encoding="utf-8") as f:
        recs = [json.loads(x) for x in f if x.strip()]
    return recs[-1]


# ====================================================================== C1–C6
def _group(root):
    # 每次运行取独立子目录 —— 变异自证会在同一 root 上反复重跑，
    # 复用同名子目录会让 _explore.jsonl 跨轮累积（used 漂移 ⇒ 假红）。
    root = tempfile.mkdtemp(dir=root, prefix="run_")
    # ---------------- C1 默认零变更（未设 env、不传 bypass_gain） ----------------
    with _Env():
        cg = _lib(os.path.join(root, "c1"))
        ref = autonomy.proposals(cg, window=200, limit=3, enforce_gain=True)
        out = autonomy.explore(cg, actor="test")
        rec = _last_rec(cg)
        ok("C1a 默认台账键面逐位一致（无 budget 键、bypass_gain=False）",
           set(rec) == EXPECTED_REC_KEYS and "budget" not in rec
           and rec["bypass_gain"] is False,
           f"keys={sorted(set(rec) ^ EXPECTED_REC_KEYS)}")
        ok("C1b 默认返回体键面逐位一致（无 budget 键、note 未追加预算段）",
           set(out) == EXPECTED_OUT_KEYS and "budget" not in out
           and "好奇线预算门" not in out["note"],
           f"keys={sorted(set(out) ^ EXPECTED_OUT_KEYS)}")
        # C1c：默认路径根本不咨询预算门（结构上不可能改行为）
        orig_bg = autonomy.budget_gate

        def _boom(*a, **k):
            raise AssertionError("默认路径不应咨询 budget_gate")

        autonomy.budget_gate = _boom
        try:
            ok("C1c 默认路径不咨询 budget_gate（零变更的结构证据）",
               autonomy.explore(cg, actor="test")["ok"] is True)
        except AssertionError as exc:
            ok("C1c 默认路径不咨询 budget_gate（零变更的结构证据）", False,
               str(exc))
        finally:
            autonomy.budget_gate = orig_bg
        # C1d【反向腿】默认仍走 σ 筛选（冷却盲区被拦）——能红「无条件开启」
        ok("C1d 默认仍走 σ(Gain) 筛选：冷却盲区被拦（steps 空、deferred 非空）",
           out["steps"] == [] and len(out["deferred"]) == 1,
           f"steps={len(out['steps'])} deferred={len(out['deferred'])}")
        # C1e【反向腿】默认 proposals/steps 与 enforce_gain=True 参考逐位一致
        ok("C1e 默认 proposals/n_signals/deferred 与参考（enforce_gain=True）逐位一致",
           out["proposals"] == ref["proposals"]
           and out["n_signals"] == ref["n_signals"]
           and out["deferred"] == ref["deferred"])

    # ---------------- C2 开关生效（预算内照常探索 + 留痕） ----------------
    with _Env(MDCG_EXPLORE_BUDGET_MAX=30):
        cg2 = _lib(os.path.join(root, "c2"))
        ex = autonomy.explore(cg2, actor="test", bypass_gain=True)
        rec2 = _last_rec(cg2)
        ok("C2a 预算内 bypass_gain=True：冷却盲区仍产生 steps（旧实现必红）",
           bool(ex["steps"]) and ex["steps"][0]["blindspot_id"] == BID,
           f"steps={len(ex['steps'])}")
        ok("C2b 豁免台账留痕 bypass_gain is True（可审计）",
           rec2.get("bypass_gain") is True)

    # ---------------- C3 预算耗尽即回落任务定价（降级非硬拒绝） ----------------
    with _Env(MDCG_EXPLORE_BUDGET_MAX=2):
        cg3 = _lib(os.path.join(root, "c3"))
        for i in range(2):                       # 窗口内已用 2 条 = 上限 → 耗尽
            append_jsonl(autonomy._explore_log_path(cg3),
                         {"type": "explore", "t": time.time(), "actor": "test",
                          "bypass_gain": True, "n_proposals": 1,
                          "bids": ["zzz"], "outcomes": {"zzz": "carried"}})
        got = autonomy.budget_gate(cg3)
        ex3 = autonomy.explore(cg3, actor="test", bypass_gain=True)
        ok("C3a 耗尽即回落任务定价（σ 仍拦：steps 空、deferred 非空；非硬拒绝）",
           got["exhausted"] is True and ex3["ok"] is True
           and ex3["steps"] == [] and len(ex3["deferred"]) == 1,
           f"used={got['used']} exhausted={got['exhausted']} "
           f"steps={len(ex3['steps'])}")
        b3 = ex3.get("budget") or {}
        ok("C3b 耗尽可审计：返回体 budget.exhausted=True 且 granted=False",
           b3.get("exhausted") is True and b3.get("granted") is False,
           json.dumps(b3, ensure_ascii=False))

    # ---------------- C4 台账字段齐（可审计） ----------------
    with _Env(MDCG_EXPLORE_BUDGET_MAX=30):
        cg4 = _lib(os.path.join(root, "c4"))
        autonomy.explore(cg4, actor="test", bypass_gain=True)
        rec4 = _last_rec(cg4)
        ok("C4a 豁免台账含 bypass_gain / actor / budget（三面可审计）",
           {"bypass_gain", "actor", "budget"} <= set(rec4))
        b4 = rec4.get("budget") or {}
        ok("C4b budget 含 window/max/used/exhausted（＋declared/granted），类型与取值正确",
           {"window", "max", "used", "exhausted", "declared", "granted"}
           <= set(b4) and b4["max"] == 30 and b4["used"] == 0
           and b4["window"] == autonomy.BUDGET_WINDOW_DEFAULT
           and b4["declared"] is True,
           json.dumps(b4, ensure_ascii=False))
    with _Env():                                  # 缺省关：未设 env 仍请求
        cg4b = _lib(os.path.join(root, "c4b"))
        autonomy.explore(cg4b, actor="test", bypass_gain=True)
        b4b = (_last_rec(cg4b).get("budget") or {})
        ok("C4c 缺省关可审计：未声明 env 时 budget.declared/granted/exhausted 全 False",
           b4b.get("declared") is False and b4b.get("granted") is False
           and b4b.get("exhausted") is False and b4b.get("max") == 0,
           json.dumps(b4b, ensure_ascii=False))

    # ---------------- C5 豁免不改资格（score）与终排、不碰 import 面 ----------------
    cg5 = _lib(os.path.join(root, "c5"))
    append_jsonl(cg5.reflection_log,
                 {"t": 2.0, "query": "次信号查询", "d_prev": 1.0, "d_curr": 1.0,
                  "d_delta": 0.0, "d2": -0.4, "states": {},
                  "n_results": 2, "feedback": None})
    append_jsonl(cg5.reflection_log,
                 {"t": 3.0, "query": "零信号查询", "d_prev": 1.0, "d_curr": 1.0,
                  "d_delta": 0.0, "d2": 0.0, "states": {},
                  "n_results": 1, "feedback": None})
    p_on = autonomy.proposals(cg5, enforce_gain=False)    # 豁免态
    p_off = autonomy.proposals(cg5, enforce_gain=True)    # 任务定价态
    # 对拍面 = 提案 ∪ 被拦（score 是定价器：两态都应保留同一份 ΔD 定价）
    sc = lambda pr: {p["query"]: p["score"]                       # noqa: E731
                     for p in pr["proposals"] + pr["deferred"]}
    ok("C5a 两态 score（ΔD 定价器）逐条相等——豁免不改定价",
       sc(p_on) == sc(p_off) and sc(p_off).get(QUERY, 0) > 0,
       f"on={sc(p_on)} off={sc(p_off)}")
    ok("C5b 零信号查询两态均无提案；n_signals 相等——豁免不造资格",
       "零信号查询" not in sc(p_on) and "零信号查询" not in sc(p_off)
       and p_on["n_signals"] == p_off["n_signals"],
       f"n={p_on['n_signals']}/{p_off['n_signals']}")
    ok("C5c 豁免路径未执行 σ 分支（out 无 gain_gate 键、deferred 为空）",
       all("gain_gate" not in p for p in p_on["proposals"])
       and p_on["deferred"] == [])
    src = inspect.getsource(autonomy)
    mods = set()
    for m in re.finditer(r"^\s*from \. import ([a-z_,\s]+)$", src, re.M):
        mods |= {x.strip() for x in m.group(1).split(",") if x.strip()}
    _DENY = {"judge", "trust", "weights", "writepipe", "propose", "advice"}
    ok("C5d 结构：autonomy 相对 import 面不含 judge/trust/写入闸",
       not (mods & _DENY) and {"d_meta", "metacognition", "predict"} <= mods,
       f"imports={sorted(mods)}")

    # ---------------- C6 结构防悬空（生产入口真走到预算门） ----------------
    with _Env(MDCG_EXPLORE_BUDGET_MAX=30):
        cg6 = _lib(os.path.join(root, "c6"))
        seen = {}
        orig_ex = autonomy.explore

        def _spy(c, **kw):
            seen.update(kw)
            return {"ok": True, "action": "explore", "apply": False,
                    "proposals": [], "steps": [], "n_signals": 0,
                    "deferred": [], "note": "spy"}

        autonomy.explore = _spy
        try:
            _ENTRY_FN()(cg6, action="explore", bypass_gain=True)
        finally:
            autonomy.explore = orig_ex
        ok("C6a 生产入口真透传：经 insight(action=explore) 到达 explore 时 bypass_gain=True",
           seen.get("bypass_gain") is True and "bypass_gain" in seen,
           f"captured={sorted(seen)}")
        ok("C6b 入口源码引用 bypass_gain 透传（防第二个不含豁免的入口）",
           _A_ENTRY in _ENTRY_SRC())
        props = _cg_schema_props()
        ok("C6c MCP 面同步：_insight_call 透传 + cg 工具 schema 声明 bypass_gain",
           _A_MCP in _MCP_SRC() and "bypass_gain" in props)


# ===================== 生产面取样（自证时可被变异替身顶替） =====================
_ENTRY_SRC = lambda: inspect.getsource(MdCGOS.insight)        # noqa: E731
_MCP_SRC = lambda: inspect.getsource(_mcp_insight_call())     # noqa: E731


def _mcp_insight_call():
    from .mcp_server import _insight_call
    return _insight_call


def _ENTRY_FN():
    return MdCGOS.insight


def _cg_schema_props():
    from .mcp_server import KERNEL_TOOLS
    tool = next(t for t in KERNEL_TOOLS if t["name"] == "cg")
    return set((tool.get("inputSchema") or {}).get("properties") or {})


def _degraded_entry(cg, action="explore", **kw):
    """「卸下挂载」替身：入口不透传 bypass_gain（模拟缺口 a 复发）。"""
    return autonomy.explore(cg)


# 变异锚点（须在对应源码里**恰好**出现 1 次，否则 ANCHOR-MISS 退出码 2）
_A_ENFORCE = "enforce_gain=not granted"
_A_GRANT = ('granted = bool(req and bgate["declared"] '
            'and not bgate["exhausted"])')
_A_LEDGER = 'rec["budget"] = brec'
_A_ENTRY = 'bypass_gain=bool(kw.get("bypass_gain"))'
_A_MCP = 'bypass_gain=a.get("bypass_gain")'

#: (名, 期望红项前缀集合, apply(还原)) —— 注入退化 → **恰好**打中预期红项数。
_MUTATIONS = (
    ("①无条件开启（force-exempt）→ 默认也绕过 σ(Gain)",
     {"C1d", "C1e", "C3a"}, "explore", _A_ENFORCE, "enforce_gain=False"),
    ("②卸下豁免（never-exempt）→ 请求恒不实授（缺口 a 复发）",
     {"C2a", "C2b"}, "explore", _A_GRANT, "granted = False"),
    ("③忽略窗口耗尽（只看声明）→ 预算形同虚设",
     {"C3a", "C3b"}, "explore", _A_GRANT,
     'granted = bool(req and bgate["declared"])'),
    ("④丢台账预算字段 → 不可审计",
     {"C4a", "C4b", "C4c"}, "explore", _A_LEDGER, 'rec["_budget"] = brec'),
)


def _anchor_preflight():
    src = textwrap.dedent(inspect.getsource(autonomy.explore))
    bad = []
    for a in (_A_ENFORCE, _A_GRANT, _A_LEDGER):
        if src.count(a) != 1:
            bad.append((a, src.count(a)))
    for a, s in ((_A_ENTRY, _ENTRY_SRC()), (_A_MCP, _MCP_SRC())):
        if s.count(a) != 1:
            bad.append((a, s.count(a)))
    if not bad:
        return 0
    for a, n in bad:
        print("  ANCHOR-MISS 锚点漂移（命中 %d 次，期望恰好 1）：%r" % (n, a[:70]))
    print("  => 实现已漂移，变异表失效：退出码 2（fail-closed；请同步 _MUTATIONS 锚点）")
    return 2


def _run_group(root):
    global PASS, FAIL
    PASS = FAIL = 0
    del FAILS[:]
    _group(root)
    return ({n.split(" ", 1)[0] for n in FAILS}, PASS, FAIL)


def _self_proof():
    rc = _anchor_preflight()
    if rc:
        return rc
    print("!! 定点变异自证：就地变异运行中的实现（不读 git），逐条要求**恰好**命中期望红项\n")
    global _ENTRY_SRC, _MCP_SRC
    orig_src = (_ENTRY_SRC, _MCP_SRC)
    orig_ex = autonomy.explore
    root = _root()
    bad = []
    try:
        with _Env():
            red0, _, _ = _run_group(root)
        print("  未变异基线：红项 %d %s"
              % (len(red0), "（应为 0）" if red0 else ""))
        if red0:
            bad.append("未变异基线即转红：%s" % sorted(red0))
        src = textwrap.dedent(inspect.getsource(autonomy.explore))
        marks = "①②③④"
        for i, (name, expect, fn, old, new) in enumerate(_MUTATIONS):
            ns = dict(vars(autonomy))
            exec(compile(src.replace(old, new), "<curiosity-mut-%d>" % i, "exec"),
                 ns)
            autonomy.explore = ns["explore"]
            try:
                red, _, _ = _run_group(root)
            except Exception as exc:                       # noqa: BLE001
                red = {"<变异体运行异常:%s>" % type(exc).__name__}
            finally:
                autonomy.explore = orig_ex
            hit = red == expect
            if not hit:
                bad.append("变异%s %s：红项 %s ≠ 期望 %s"
                           % (marks[i], name, sorted(red), sorted(expect)))
            print("  变异%s %-40s 红项 %d（期望 %d）%s"
                  % (marks[i], name, len(red), len(expect),
                     "PASS" if hit else "**FAIL** 实=%s 期=%s"
                     % (sorted(red), sorted(expect))))
        # ⑤「卸下挂载」= 入口不透传（源码 + 行为双面）
        _ENTRY_SRC = lambda: orig_src[0]().replace(_A_ENTRY, "bypass_gain=None")
        ent_src = orig_src[0]()
        red = {"C6b"} if _A_ENTRY not in _ENTRY_SRC() else set()
        hit = red == {"C6b"}
        if not hit:
            bad.append("变异⑤ 源码谓词判别力失效：红项 %s ≠ {C6b}" % sorted(red))
        print("  变异⑤ %-40s 红项 %d（期望 1）%s"
              % ("卸下挂载·入口源码不再透传", len(red),
                 "PASS" if hit else "**FAIL**"))
        real_fn = _ENTRY_FN
        globals()["_ENTRY_FN"] = lambda: _degraded_entry
        try:
            seen = {}
            oex = autonomy.explore

            def _spy(c, **kw):
                seen.update(kw)
                return {"ok": True}
            autonomy.explore = _spy
            try:
                _ENTRY_FN()(None, action="explore", bypass_gain=True)
            finally:
                autonomy.explore = oex
            redb = set() if seen.get("bypass_gain") is True else {"C6a"}
        finally:
            globals()["_ENTRY_FN"] = real_fn
        hitb = redb == {"C6a"}
        if not hitb:
            bad.append("变异⑤b 行为判别力失效：红项 %s ≠ {C6a}" % sorted(redb))
        print("  变异⑤b %-39s 红项 %d（期望 1）%s"
              % ("卸下挂载·入口行为不再透传", len(redb),
                 "PASS" if hitb else "**FAIL**"))
        # ⑥ MCP 面卸下
        _MCP_SRC = lambda: orig_src[1]().replace(_A_MCP, "bypass_gain=None")
        redm = {"C6c"} if _A_MCP not in _MCP_SRC() else set()
        hitm = redm == {"C6c"}
        if not hitm:
            bad.append("变异⑥ MCP 面判别力失效：红项 %s ≠ {C6c}" % sorted(redm))
        print("  变异⑥ %-40s 红项 %d（期望 1）%s"
              % ("MCP 面卸下透传", len(redm), "PASS" if hitm else "**FAIL**"))
    finally:
        _ENTRY_SRC, _MCP_SRC = orig_src
        autonomy.explore = orig_ex
        shutil.rmtree(root, ignore_errors=True)
    print("\n变异自证：%s"
          % ("PASS（四处核心接线 ＋ 两处入口/MCP 面逐条恰好命中期望红项）"
             if not bad else "FAIL —— " + "；".join(bad)))
    return 0 if not bad else 1


def main():
    print("v1.2 组1 好奇线（§2.9.3.1 非任务探索）生产路径守卫 C1–C6")
    print("=" * 70)
    root = _root()
    print("root =", root)
    try:
        _group(root)
    finally:
        shutil.rmtree(root, ignore_errors=True)
    print()
    if FAILS:
        print(f"FAILED: {len(FAILS)} 项 → {', '.join(FAILS)}")
        return 1
    print(f"ALL OK: {PASS} 项（好奇线预算门守卫全绿）")
    return 0


if __name__ == "__main__":
    if "--self-proof" in os.sys.argv:
        os.sys.exit(_self_proof())
    os.sys.exit(main())
