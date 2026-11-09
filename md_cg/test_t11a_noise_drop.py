# -*- coding: utf-8 -*-
"""test_t11a_noise_drop —— J9「噪声（工具日志、重复、系统上下文）」门槛收紧的验收
（E-T11a / 目标 T11，run t11a-20261012 t1）。

被测面：`md_cg/judgment_rules.py` 的 **J9 规则定义**（只扩了 terms/patterns，
未删旧词、未动 `_PRIORITY`、未动其它 J 判据）与 `judge_text` 的**一个新增
J9 噪声来源**——`_dup_noise_of` 重复句/CJK 立即重复计数（hard requirement：
不改变 `_PRIORITY` 与既有规则判定）。本文件只读被测面，不改它。

五段（范式照 `md_cg/test_t09a_demand_drop.py` / `md_cg/test_t18a_judgment.py`）：

  [A] 规则层：工具日志 / 系统上下文 / 重复三类噪声样本（各 ≥3 条）逐条判
      `state==drop` 且 `judge=="J9"`（判据名也要对——只判三态会让「被 J7/J8
      顺手抢走」也蒙混过关），evidence 恒非空、should_write 一致拒写。
  [B] 优先级：噪声与 keep 词**同现**的混合句仍判 drop/J9（J9 在 _PRIORITY
      首位，丢胜过留）；4 条对照保留样本仍判 keep（噪声规则不得误伤）。
  [C] 写路径不留占位：`MDCG_JUDGMENT=1` 时 `kg.add(噪声样本)` 返回 None 且
      `_fm_of` 为 None、`kg.remember_event` 返回 `event=None` 且 recent 窗口
      零变化（拒写必须是**前置短路**，不是写进去再删）；KEEP 对照照常落盘
      带 `judgment_state=keep`。
  [D] 事实钉存边界：4 条钉存/个性样本仍 KEEP 落盘（add 带 fm、remember_event
      进窗带 verdict），一条不误丢。
  [E] 默认关回归：`MDCG_JUDGMENT` 未设 / 显式 0 时同一噪声样本照常成节点、
      fm 无判定字段夹带（与接线前逐字节一致）。

运行：cd D:\\wook\\lingshu-src && python -X utf8 -m md_cg.test_t11a_noise_drop
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

#: ① 工具日志形态（npm/python/管道捕获/框架注入标记，含 E-T11a 原文样本）。
TOOL_LOGS = (
    "npm error code ELIFECYCLE",
    "npm error code ENOENT: No such file or directory",
    "Traceback (most recent call last):",
    "Collecting xyz",
    "Downloading xyz-1.0.tar.gz",
    "added 123 packages",
    "[stderr] npm WARN deprecated foo@1.0.0",
    "[stdout] ✓ probe finished",
    "[exit code: 1]",
    "[sandbox: file access denied under workspace-write mode]",
    "[Compressed 测试通过]",
    "<acp tokens=1024 type=text>",
)

#: ② 系统上下文块（标签块 / AGENTS.md 引用块）。
SYS_CTX = (
    "<system-reminder>hello there</system-reminder>",
    "<system-reminder>请按当前会话的清单执行</system-reminder>",
    "Instructions from: AGENTS.md",
    "Instructions from: ~/.dsh/AGENTS.md",
)

#: ③ 重复（同句/同词立即重复 + 同文本内同类句 ≥2 次 → judge_text 的
#: _dup_noise_of 计数判 J9）。
REPEATS = (
    "收到收到",
    "好的好的 好的好的",
    "明白明白 明白明白",
    "这个项目是 wook。这个项目是 wook。",
    "我主力语言是 Python。我主力语言是 Python。",
)

#: 三类噪声样本全集（[A] 逐条断言用）。
NOISES = TOOL_LOGS + SYS_CTX + REPEATS

#: 混合样本：同一段文本里噪声与 keep 词/事实句**同现** → 仍判 drop/J9
#: （J9 在 _PRIORITY 首位，丢胜过留）。
MIXED = (
    "我主力语言是 Python，npm error code ELIFECYCLE",
    "我的生日是5月20日，Traceback (most recent call last):",
    "帮我记住我的邮箱是 a@b.com。<system-reminder>hello</system-reminder>",
)

#: 对照保留样本（**必须不误伤**——噪声规则不得吞掉真实陈述/钉存）。
PINS = (
    "我主力语言是 Python，讨厌过度抽象",
    "我的生日是5月20日",
    "项目名是 wook",
    "帮我记住我的邮箱是 a@b.com",
)

#: 默认关回归用的噪声样本（未设/显式 0 时都必须照常成节点）。
OFF_SAMPLES = (
    "npm error code ELIFECYCLE",
    "Instructions from: AGENTS.md",
    "收到收到",
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
    return MdCGOS(tempfile.mkdtemp(prefix="mdcg_t11a_"))


# ---------------------------------------------------------------------------
# [A] 规则层：工具日志 / 系统上下文 / 重复 三类噪声样本，全部 drop/J9
# ---------------------------------------------------------------------------

def test_a_rules():
    print("[A] 规则层：三类噪声样本判 drop（且判据名就是 J9）")
    for label, group in (("工具日志", TOOL_LOGS), ("系统上下文", SYS_CTX),
                         ("重复", REPEATS)):
        check("组内样本数 ≥3：%s（%d 条）" % (label, len(group)),
              len(group) >= 3)
        for t in group:
            v = jr.judge_text(t)
            check("噪声样本 drop/J9：%s：%s" % (label, t),
                  v["state"] == jr.DROP and v["judge"] == "J9"
                  and v["state_of"].get("J9") == jr.DROP,
                  jr.explain(v))
    check("全部噪声样本的 evidence 恒非空（拒写原因可回溯，不是黑箱）",
          all(jr.judge_text(t)["evidence"] for t in NOISES))
    check("should_write 对全部噪声样本一致拒写（写入侧唯一裁决）",
          not any(jr.should_write(jr.judge_text(t)) for t in NOISES))
    check("对比先例：J7 需求样本仍归 J7（噪声收紧不吞其它丢判据）",
          jr.judge_text("今天把 report.pdf 生成一下")["judge"] == "J7"
          and jr.judge_text("A还是B，你倾向哪个？")["judge"] == "J8")


# ---------------------------------------------------------------------------
# [B] 优先级：噪声+keep 混合句丢胜过留；对照保留样本不误伤
# ---------------------------------------------------------------------------

def test_b_priority():
    print("[B] 优先级：混合句仍丢/J9；对照保留样本仍 keep")
    for t in MIXED:
        v = jr.judge_text(t)
        check("混合句仍判 drop/J9：%s" % t,
              v["state"] == jr.DROP and v["judge"] == "J9", jr.explain(v))
    check("J9 在 _PRIORITY 里先于全部留类判据（次序即口径，本任务不得改它）",
          jr._PRIORITY.index("J9") < jr._PRIORITY.index("J1")
          and jr._PRIORITY.index("J9") < jr._PRIORITY.index("J6"))
    for t in PINS:
        v = jr.judge_text(t)
        check("对照保留样本仍 keep（不误伤）：%s" % t,
              v["state"] == jr.KEEP and jr.should_write(v), jr.explain(v))


# ---------------------------------------------------------------------------
# [C] 写路径不留占位（MDCG_JUDGMENT=1）：拒写是前置短路，不是写进去再删
# ---------------------------------------------------------------------------

def test_c_writepath():
    print("[C] 写路径：DROP 前置短路（add 返回 None / remember_event 不落窗）")
    _env_prev = os.environ.get(_ENV_KEY)
    os.environ[_ENV_KEY] = "1"
    kg = _mk_cg()
    # 跨三类各取两条，覆盖 [C] 的写路径至少 6 个噪声样本。
    drop_writes = (TOOL_LOGS[0], TOOL_LOGS[8], SYS_CTX[0], SYS_CTX[2],
                   REPEATS[0], REPEATS[3])
    try:
        # ---- add：返回 None，且节点真不出现在存储里 ----
        for i, t in enumerate(drop_writes):
            nid = "t11a_drop_%d" % i
            got = kg.add(nid, t)
            fm = _fm_of(kg, nid)
            check("add DROP 返回 None 且节点缺席：%s" % t,
                  got is None and fm is None, "got=%r fm=%r" % (got, fm))
            stored = kg.get(nid)
            check("  └ 存储按 id 复查仍为空（无占位/无换名落盘）：%s" % t,
                  not stored, repr(stored))

        # ---- remember_event：event=None，且 recent 窗口零变化 ----
        check("前置检查：拒写前 recent 窗口为空",
              _recent_texts(kg) == [], str(_recent_texts(kg)))
        for t in drop_writes:
            r = kg.remember_event("user", t)
            check("remember_event DROP：event=None + 窗口零变化：%s" % t,
                  r["event"] is None and r.get("dropped") == 0
                  and r["verdict"]["state"] == jr.DROP
                  and _recent_texts(kg) == [], str(r)[:200])

        # ---- 对照组：同一条路径上 KEEP 的照常落盘（证明短路没把写入整条堵死）----
        k = kg.remember_event("user", "我的生日是5月20日")
        check("对照组：KEEP 事件照常落窗且带 verdict（短路只拦 DROP）",
              k["event"] is not None
              and k["event"]["meta"].get(jr.STATE_FIELD) == jr.KEEP
              and _recent_texts(kg) == ["我的生日是5月20日"], str(k)[:200])
        check("对照组：KEEP 节点照常落盘",
              kg.add("t11a_keep_probe", "我的生日是5月20日") == "t11a_keep_probe")
    finally:
        shutil.rmtree(kg.root, ignore_errors=True)
        if _env_prev is None:
            os.environ.pop(_ENV_KEY, None)
        else:
            os.environ[_ENV_KEY] = _env_prev


# ---------------------------------------------------------------------------
# [D] 事实钉存边界：开关开启时 4 条钉存/个性样本仍 KEEP 落盘（一条不误丢）
# ---------------------------------------------------------------------------

def test_d_pin_keep():
    print("[D] 钉存边界：4 条钉存/个性样本照常 KEEP 落盘（开关开启时）")
    _env_prev = os.environ.get(_ENV_KEY)
    os.environ[_ENV_KEY] = "1"
    kg = _mk_cg()
    try:
        for i, t in enumerate(PINS):
            nid = "t11a_pin_%d" % i
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
# [E] 默认关回归：未设 / 显式 0 → 噪声样本照常成节点且无判定字段夹带
# ---------------------------------------------------------------------------

def _off_case(label):
    """默认关口径的一个完整快照：节点成、fm 无判定字段、返回体形状不变。"""
    cg = _mk_cg()
    try:
        for i, t in enumerate(OFF_SAMPLES):
            nid = "t11a_off_%d" % i
            got = cg.add(nid, t)
            fm = _fm_of(cg, nid)
            check("%s add 噪声样本照常成节点：%s" % (label, t),
                  got == nid and fm is not None, "got=%r fm=%r" % (got, fm))
            leaked = [f for f in _JUDGMENT_FIELDS if f in (fm or {})]
            check("  └ fm 无判定字段夹带（逐字节一致）：%s" % t,
                  not leaked, "leaked=%s" % leaked)
        r = cg.remember_event("user", OFF_SAMPLES[0])
        check("%s remember_event 返回体形状不变（仅 event/dropped 两键）" % label,
              set(r.keys()) == {"event", "dropped"}, str(sorted(r.keys())))
        check("%s remember_event 正文原样进窗（未被判定面改写）" % label,
              r["event"] is not None and r["event"]["text"] == OFF_SAMPLES[0]
              and _recent_texts(cg) == [OFF_SAMPLES[0]], str(r)[:200])
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
    print("===== md_cg.test_t11a_noise_drop（E-T11a t1 J9 噪声门槛收紧验收） =====")
    test_a_rules()
    test_b_priority()
    test_c_writepath()
    test_d_pin_keep()
    test_e_default_off()
    print("\n===== t11a 噪声丢弃：%d 通过，%d 失败 =====" % (passed, failed))
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()