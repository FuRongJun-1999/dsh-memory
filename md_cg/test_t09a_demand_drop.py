# -*- coding: utf-8 -*-
"""test_t09a_demand_drop —— J7「一次性的需求与交代本身」扩展的验收（E-T09a t1）。

被测面：`md_cg/judgment_rules.py` 的 **J7 规则定义**（只扩了 terms/patterns，
未加新规则、未动其它 J 规则、未动 `_PRIORITY`）。本文件只读被测面，不改它。

四段（范式照 `md_cg/test_t18a_judgment.py`）：

  [A] 规则层：9 条需求句式（E-T09a 蓝图的验收样本）+ 若干同类样本，
      必须全部 `state==drop` 且 `judge=="J7"`（判据名也要对——只判三态会让
      「被 J8/J10 顺手抢走」也蒙混过关）。
  [B] 优先级：需求句柄与个性/事实词**同现**的混合样本仍判 drop（模块头的
      「分句 + 取最高优先级、丢胜过留」口径）；纯 keep 词样本仍判 keep
      （扩展不得误伤，两侧都要有断言——只测一侧的回归是单边锁）。
  [C] 写路径不留占位：`MDCG_JUDGMENT=1` 时 `MdCGOS.add` 返回 None 且节点
      真不出现在存储里、`remember_event` 返回 `event=None` 且 recent 窗口
      零变化（拒写必须是**前置短路**，不是写进去再删）。
  [D] 事实钉存边界：4 条钉存样本在开关开启时仍 KEEP 落盘（走 J6 兜底）。
  [E] 默认关回归：`MDCG_JUDGMENT` 未设时同一需求样本照常成节点、返回体形状
      与 fm 字段集**与接线前逐字节一致**（无判定字段夹带）；显式 `=0` 同。

运行：cd D:\\wook\\lingshu-src && python -X utf8 -m md_cg.test_t09a_demand_drop
"""
import os
import shutil
import sys
import tempfile

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

from md_cg import judgment_rules as jr          # noqa: E402
from md_cg.mdcos import MdCGOS                  # noqa: E402

passed = failed = 0
_ENV_KEY = "MDCG_JUDGMENT"
_ENV_PREV = os.environ.pop(_ENV_KEY, None)      # 本测试全程自管开关状态

#: E-T09a 蓝图的 9 条验收样本（第一条是明确列出的需求句式）。
DEMANDS = (
    "给我生成一份PDF",
    "把数据导出来给我",
    "明天记得提醒我开会",
    "提醒我下午三点开会",
    "把那个问题修复一下",
    "把日志清理一下",
    "给我发一份昨天的监控数据",
    "我需要你生成一份这个月的数据报表",
    "请帮我封装一个工具函数",
)

#: 同类需求样本（没在蓝图里点名，但属同一「一次性需求」面）。
DEMANDS_MORE = (
    "帮我写一下会议纪要",
    "请把端口占用查一下",
    "把部署脚本生成一下",
    "给我整理一下文件",
    "提醒我明天早上开会",
)

#: 混合样本：同一段文本里既有需求句柄、又有个性/事实词。
MIXED = (
    "帮我生成一份报告，我的性格是喜欢简洁的",
    "帮我把接口改一下，接口以前是老的实现",
)

#: 事实钉存样本（**必须不误伤**——这些是长期事实，不是一次性交代）。
PINS = (
    "帮我记住我的生日是5月20日",
    "记一下我的邮箱是 a@b.com",
    "记住：项目名是 wook",
    "以后叫我小R",
)

#: 纯 keep 词样本（扩展后仍须落 keep）。
PURE_KEEP = (
    "我主力语言是 Python，讨厌过度抽象",
    "我的生日是5月20日",
    "项目名是 wook",
)

#: 默认关回归用的需求样本（未设/显式 0 时都必须照常成节点）。
OFF_SAMPLES = (
    "给我生成一份PDF",
    "把数据导出来给我",
    "提醒我下午三点开会",
)

#: 判定面的全部落盘字段（默认关时一个都不许出现）。
_JUDGMENT_FIELDS = (jr.STATE_FIELD, jr.WHY_KEPT_FIELD,
                    jr.LIFETIME_FIELD, jr.REF_COUNT_FIELD)


def check(name, cond, detail=""):
    global passed, failed
    if cond:
        passed += 1
        print("  [PASS] " + name)
    else:
        failed += 1
        print("  [FAIL] " + name + "  " + str(detail)[:300])


def _fm_of(cg, nid):
    """node_id 的 frontmatter；节点缺席（ID 为假 / get 为空）返回 None。"""
    if not nid:
        return None
    try:
        got = cg.get(nid)
    except Exception:
        return None
    if not got:
        return None
    return got.get("frontmatter")


def _recent_texts(cg, limit=10):
    return [r.get("text") or "" for r in cg.recent_events(limit=limit)]


def _mk_cg():
    return MdCGOS(tempfile.mkdtemp(prefix="mdcg_t09a_"))


# ---------------------------------------------------------------------------
# [A] 规则层：9 条需求句式 + 同类样本，全部 drop/J7
# ---------------------------------------------------------------------------

def test_a_demands():
    print("[A] 规则层：需求句式判 drop（且判据名就是 J7）")
    for t in DEMANDS:
        v = jr.judge_text(t)
        check("需求样本 drop/J7：%s" % t,
              v["state"] == jr.DROP and v["judge"] == "J7"
              and v["state_of"].get("J7") == jr.DROP, jr.explain(v))
    for t in DEMANDS_MORE:
        v = jr.judge_text(t)
        check("同类样本 drop/J7：%s" % t,
              v["state"] == jr.DROP and v["judge"] == "J7", jr.explain(v))
    check("需求样本的 evidence 恒非空（拒写原因可回溯，不是黑箱）",
          all(jr.judge_text(t)["evidence"] for t in DEMANDS))
    check("should_write 对全部需求样本一致拒写（写入侧唯一裁决）",
          not any(jr.should_write(jr.judge_text(t)) for t in DEMANDS + DEMANDS_MORE))


# ---------------------------------------------------------------------------
# [B] 优先级：混合句丢胜过留；纯 keep 词不误伤
# ---------------------------------------------------------------------------

def test_b_priority():
    print("[B] 优先级：混合句丢胜过留 / 纯 keep 词不误伤")
    for t in MIXED:
        v = jr.judge_text(t)
        check("混合句仍判 drop/J7：%s" % t,
              v["state"] == jr.DROP and v["judge"] == "J7", jr.explain(v))
    check("J7 在 _PRIORITY 里先于留类判据（次序即口径，本任务不得改它）",
          jr._PRIORITY.index("J7") < jr._PRIORITY.index("J1")
          and jr._PRIORITY.index("J7") < jr._PRIORITY.index("J6"))
    for t in PURE_KEEP:
        v = jr.judge_text(t)
        check("纯 keep 词样本仍 keep：%s" % t,
              v["state"] == jr.KEEP and jr.should_write(v), jr.explain(v))
    for t in PINS:
        v = jr.judge_text(t)
        check("钉存样本规则层仍 keep（不误伤）：%s" % t,
              v["state"] == jr.KEEP, jr.explain(v))


# ---------------------------------------------------------------------------
# [C] 写路径不留占位（MDCG_JUDGMENT=1）：拒写是前置短路，不是写进去再删
# ---------------------------------------------------------------------------

def test_c_writepath():
    print("[C] 写路径：DROP 前置短路（add 返回 None / remember_event 不落窗）")
    _env_prev = os.environ.get(_ENV_KEY)
    os.environ[_ENV_KEY] = "1"
    kg = _mk_cg()
    try:
        # ---- add：返回 None，且节点真不出现在存储里 ----
        for i, t in enumerate(DEMANDS):
            nid = "t09a_drop_%d" % i
            got = kg.add(nid, t)
            fm = _fm_of(kg, nid)
            check("add DROP 返回 None 且节点缺席：%s" % t,
                  got is None and fm is None, "got=%r fm=%r" % (got, fm))
            # 等价检查：不是「换了 id 写进去」——按内容在存储里也找不到。
            stored = kg.get(nid)
            check("  └ 存储按 id 复查仍为空（无占位/无换名落盘）：%s" % t,
                  not stored, repr(stored))

        # ---- remember_event：event=None，且 recent 窗口零变化 ----
        check("前置检查：拒写前 recent 窗口为空",
              _recent_texts(kg) == [], str(_recent_texts(kg)))
        for t in DEMANDS:
            r = kg.remember_event("user", t)
            check("remember_event DROP：event=None + 窗口零变化：%s" % t,
                  r["event"] is None and r.get("dropped") == 0
                  and r["verdict"]["state"] == jr.DROP
                  and _recent_texts(kg) == [], str(r)[:200])

        # ---- 对照组：同一条路径上 KEEP 的照常落盘（证明短路没把写入整条堵死）----
        k = kg.remember_event("user", "我的生日是5月20日")
        check("对照组：KEEP 事件照常落窗（短路只拦 DROP，不是堵死写入面）",
              k["event"] is not None and _recent_texts(kg) == ["我的生日是5月20日"],
              str(k)[:200])
        check("对照组：KEEP 节点照常落盘",
              kg.add("t09a_keep_probe", "我的生日是5月20日") == "t09a_keep_probe")
    finally:
        shutil.rmtree(kg.root, ignore_errors=True)
        if _env_prev is None:
            os.environ.pop(_ENV_KEY, None)
        else:
            os.environ[_ENV_KEY] = _env_prev


# ---------------------------------------------------------------------------
# [D] 事实钉存边界：开关开启时 4 条钉存样本仍 KEEP 落盘
# ---------------------------------------------------------------------------

def test_d_pin_keep():
    print("[D] 钉存边界：4 条事实钉存样本照常 KEEP 落盘（开关开启时）")
    _env_prev = os.environ.get(_ENV_KEY)
    os.environ[_ENV_KEY] = "1"
    kg = _mk_cg()
    try:
        for i, t in enumerate(PINS):
            nid = "t09a_pin_%d" % i
            got = kg.add(nid, t)
            fm = _fm_of(kg, nid)
            check("add 钉存照常落盘：%s" % t,
                  got == nid and fm is not None
                  and fm.get(jr.STATE_FIELD) == jr.KEEP, "got=%r fm=%r" % (got, fm))
            check("  └ why_kept 非空可回溯（落盘节点自带判断理由）",
                  bool((fm or {}).get(jr.WHY_KEPT_FIELD)),
                  str((fm or {}).get(jr.WHY_KEPT_FIELD)))
            ev = kg.remember_event("user", t)
            check("remember_event 钉存照常进窗且带 verdict：%s" % t,
                  ev["event"] is not None
                  and ev["event"]["text"] == t
                  and ev["verdict"]["state"] == jr.KEEP, str(ev)[:200])
        check("4 条钉存样本全部进了 recent 窗口（一条没被误丢）",
              _recent_texts(kg, limit=20) == list(reversed(PINS)),
              str(_recent_texts(kg, limit=20)))
    finally:
        shutil.rmtree(kg.root, ignore_errors=True)
        if _env_prev is None:
            os.environ.pop(_ENV_KEY, None)
        else:
            os.environ[_ENV_KEY] = _env_prev


# ---------------------------------------------------------------------------
# [E] 默认关回归：未设 / 显式 0 → 需求样本照常成节点且无判定字段夹带
# ---------------------------------------------------------------------------

def _off_case(label):
    """默认关口径的一个完整快照：节点成、fm 无判定字段、返回体形状不变。"""
    cg = _mk_cg()
    try:
        for i, t in enumerate(OFF_SAMPLES):
            nid = "t09a_off_%d" % i
            got = cg.add(nid, t)
            fm = _fm_of(cg, nid)
            check("%s add 需求样本照常成节点：%s" % (label, t),
                  got == nid and fm is not None, "got=%r fm=%r" % (got, fm))
            leaked = [f for f in _JUDGMENT_FIELDS if f in (fm or {})]
            check("  └ fm 无判定字段夹带（逐字节一致）：%s" % t,
                  not leaked, "leaked=%s" % leaked)
        r = cg.remember_event("user", OFF_SAMPLES[0])
        check("%s remember_event 返回体形状不变（仅 event/dropped 两键）" % label,
              set(r.keys()) == {"event", "dropped"}, str(sorted(r.keys())))
        check("%s remember_event 正文原样进窗（未被判定面改写）" % label,
              r["event"] is not None and r["event"]["text"] == OFF_SAMPLES[0]
              and _recent_texts(cg) == [OFF_SAMPLES[0]],
              str(r)[:200])
        check("%s 事件 meta 里无判定字段夹带" % label,
              not [f for f in _JUDGMENT_FIELDS if f in r["event"]["meta"]],
              str(r["event"]["meta"]))
    finally:
        shutil.rmtree(cg.root, ignore_errors=True)


def test_e_default_off():
    print("[E] 默认关回归：MDCG_JUDGMENT 未设 / 显式 0 → 与接线前逐字节一致")
    os.environ.pop(_ENV_KEY, None)
    check("未设时 is_enabled() 为 False（默认关是契约，不是巧合）",
          jr.is_enabled() is False)
    _off_case("未设")

    os.environ[_ENV_KEY] = "0"
    try:
        check("显式 MDCG_JUDGMENT=0 时 is_enabled() 仍为 False",
              jr.is_enabled() is False)
        _off_case("显式0")
    finally:
        os.environ.pop(_ENV_KEY, None)


def main():
    print("===== md_cg.test_t09a_demand_drop（E-T09a t1 J7 需求句式扩展验收） =====")
    test_a_demands()
    test_b_priority()
    test_c_writepath()
    test_d_pin_keep()
    test_e_default_off()
    print("\n===== t09a 需求丢弃：%d 通过，%d 失败 =====" % (passed, failed))
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
