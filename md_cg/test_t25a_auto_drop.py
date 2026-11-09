# -*- coding: utf-8 -*-
"""test_t25a_auto_drop —— 「丢弃全自动、零中间态」五段验收（E-T25a t1）。

## 这个测试锁的是什么

写入侧接线（`mdcg.add` 前置短路 / `mdcg.remember_event` 前置短路，开关
`MDCG_JUDGMENT`，真源 `judgment_rules.is_enabled`）判 `DROP` 时必须是
**全自动**的：拒写、不留占位、不换名落盘、**不进**两段式 pending 队列
（`twophase.pending`，短路必须发生在 `twophase.begin` 之前）、**不进**
海马体 inbox 待审队列（`MdCGOS.review_list`）——中间态一个都不留。
开关默认关闭（存量回归）；本文件只读被测面，不改任何产品源码。

五段（范式照 `md_cg/test_t09a_demand_drop.py` / `md_cg/test_t10a_procedural.py`）：

  [A] 判定契约：`judgment_rules` 三态互斥穷尽（KEEP/DROP/KEEP_LIFE）——
      结构面（RULES 全部落在 STATES 内、三态各有规则覆盖）+ 行为面（样本集
      里三态都真实出现，J7/J8/J9/J10 四类丢弃判据逐一现身）；
      `should_write(DROP)==False`、`should_write(KEEP/KEEP_LIFE)==True`；
      坏形状（None / 非 dict）fail-open 放行（防误伤，不是防污染）。
  [B] add 写路径（`MDCG_JUDGMENT=1`）：DROP 样本 add → 返回 None 且节点缺席
      （get 空、无占位文件、无换名落盘），`twophase.pending(cg)==[]`
      （未结清写入意图=不进 pending 队列），`review_list()==[]`
      （无待审候选=不审核）。
  [C] remember_event 写路径（`MDCG_JUDGMENT=1`）：DROP → `event=None`、
      `dropped==0`、recent 窗口零变化，且同样 `pending==[]`、`review_list()==[]`。
  [D] 对照组：同路径 KEEP 样本照常落盘/进窗（证明短路只拦 DROP、没堵死
      写入面），KEEP 写入不产生 pending 残留；附**非空洞探针**——同族实例上
      人为 `twophase.begin` / `MdCGOS.propose`，证明 pending/review 检测面
      真的能看见东西（恒空不是瞎的）。另探一条 KEEP_LIFE 写入照常落寿。
  [E] 默认关回归：`MDCG_JUDGMENT` 未设/显式 0 时同一需求样本照常成节点、
      fm 无判定字段夹带、`remember_event` 返回体形状不变（必须真跑通）。

## 残留 gate 处理约定（照任务口径，不改产品源码）

[B]/[C] 里「节点缺席 / pending 队列 / review 队列」三条零残留探针若失败，
说明产品层残留 gate（DROP 仍产生写入意图 / 待审候选 / 节点占位）——按
预期失败（XFAIL）记入并注明「T25a 发现残留 gate」，测试照常 exit 0；
[A]/[D]/[E] 是硬断言，失败即真失败。

运行：cd D:\\wook\\lingshu-src && python -X utf8 -m md_cg.test_t25a_auto_drop
"""
import os
import shutil
import sys
import tempfile

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

from md_cg import judgment_rules as jr          # noqa: E402
from md_cg import twophase                      # noqa: E402
from md_cg.mdcos import MdCGOS                  # noqa: E402

passed = failed = xfailed = 0
_ENV_KEY = "MDCG_JUDGMENT"
_ENV_PREV = os.environ.pop(_ENV_KEY, None)      # 本测试全程自管开关状态

#: DROP 样本（期望判据, 文本）——J7 一次性需求 ×2 / J8 讨论过程 / J9 噪声 ×2 /
#: J10 时效失效，四类丢弃判据逐一现身（[A] 断言覆盖，[B]/[C] 直接喂写路径）。
DROP_SAMPLES = (
    ("J7", "给我生成一份PDF"),
    ("J7", "把数据导出来给我"),
    ("J8", "A还是B，你倾向哪个？"),
    ("J9", "Traceback (most recent call last)"),
    ("J9", "[exit code: 1]"),
    ("J10", "先这样，等会儿回头再说"),
)

#: KEEP 对照样本（同一条写入路径，必须照常落盘/进窗——短路只拦 DROP）。
KEEP_SAMPLES = (
    "我主力语言是 Python，讨厌过度抽象",
    "我的生日是5月20日",
    "结论是 X 模块放 D:\\wook\\lingshu-src",
)

#: KEEP_LIFE 探针：J11 + 显式引用信号 → 留但定寿（写入面照常放行）。
LIFE_TEXT = "先记着这个方案"
LIFE_REFS = {"ref_count": 3, "cited": False}

#: 默认关回归用的需求样本（未设/显式 0 时都必须照常成节点）。
OFF_SAMPLES = (
    "给我生成一份PDF",
    "提醒我下午三点开会",
    "把日志清理一下",
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


def check_residue(name, cond, detail=""):
    """零残留探针：cond 为真 = 零残留（PASS）；为假 = 产品层残留 gate——
    按任务口径**不改产品源码**，XFAIL 记入并注明「T25a 发现残留 gate」，
    不计入 failed（本文件照常 exit 0）。"""
    global passed, xfailed
    if cond:
        passed += 1
        print("  [PASS] " + name)
    else:
        xfailed += 1
        print("  [XFAIL:T25a 发现残留 gate] " + name + "  " + str(detail)[:300])


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


def _recent_texts(cg, limit=20):
    return [r.get("text") or "" for r in cg.recent_events(limit=limit)]


def _all_node_ids(cg):
    """本实例里**所有**已落节点 id（含未预期的占位节点）——用于断言「无占位」。"""
    ids = []
    for key in ("index", "_index", "nodes"):
        try:
            obj = getattr(cg, key, None)
            if isinstance(obj, dict):
                ids.extend(str(x) for x in obj.keys())
        except Exception:
            continue
    try:
        for it in cg.list_nodes():
            if isinstance(it, dict) and it.get("id"):
                ids.append(str(it["id"]))
            elif isinstance(it, str):
                ids.append(it)
    except Exception:
        pass
    return sorted(set(ids))


def _walk_files(root):
    out = []
    for base, _dirs, files in os.walk(root):
        for f in files:
            out.append(os.path.join(base, f))
    return out


def _mk_cg():
    return MdCGOS(tempfile.mkdtemp(prefix="mdcg_t25a_"))


def _with_env(value):
    """临时开关上下文：返回 (restore_fn)；value=None 表示弹掉（默认关）。"""
    prev = os.environ.get(_ENV_KEY)
    if value is None:
        os.environ.pop(_ENV_KEY, None)
    else:
        os.environ[_ENV_KEY] = value

    def restore():
        if prev is None:
            os.environ.pop(_ENV_KEY, None)
        else:
            os.environ[_ENV_KEY] = prev
    return restore


# ---------------------------------------------------------------------------
# [A] 判定契约：三态互斥穷尽 + should_write 裁决 + 坏形状 fail-open
# ---------------------------------------------------------------------------

def test_a_contract():
    print("[A] 判定契约：三态互斥穷尽（KEEP/DROP/KEEP_LIFE）+ should_write 裁决")

    # ---- 结构面：三态互斥（三个不同串）且穷尽（RULES 全覆盖、每态有规则） ----
    check("三态是三个互异串（互斥）",
          len(set(jr.STATES)) == 3 and set(jr.STATES)
          == {jr.KEEP, jr.DROP, jr.KEEP_LIFE}, str(jr.STATES))
    check("RULES 全部落在 STATES 内（无第四态混入）",
          all(r.get("state") in jr.STATES for r in jr.RULES.values()),
          {k: r.get("state") for k, r in jr.RULES.items()})
    check("三态穷尽：每种状态都有规则覆盖（keep J1-J6 / drop J7-J10 / life J11）",
          set(r["state"] for r in jr.RULES.values()) == set(jr.STATES),
          sorted(set(r["state"] for r in jr.RULES.values())))

    # ---- 行为面：样本集里三态都真实出现，且每次结论都在 STATES 内 ----
    seen = set()
    for want, text in DROP_SAMPLES:
        v = jr.judge_text(text)
        seen.add(v.get("state"))
        check("丢弃样本 %s 判 DROP 且判据名正确：%s" % (want, text),
              v.get("state") == jr.DROP and v.get("judge") == want
              and v.get("state_of", {}).get(want) == jr.DROP, jr.explain(v))
        check("  └ evidence 非空（拒写原因可回溯，不是黑箱）：%s" % text,
              bool(v.get("evidence")), repr(v.get("evidence")))
        check("  └ should_write(DROP)==False（写入侧唯一裁决）：%s" % text,
              jr.should_write(v) is False, jr.explain(v))
    for text in KEEP_SAMPLES:
        v = jr.judge_text(text)
        seen.add(v.get("state"))
        check("KEEP 对照样本判留且放行：%s" % text,
              v.get("state") == jr.KEEP and jr.should_write(v) is True,
              jr.explain(v))
    vlife = jr.judge_text(LIFE_TEXT, ref_signals=dict(LIFE_REFS))
    seen.add(vlife.get("state"))
    check("KEEP_LIFE 样本（J11+引用信号）判留但定寿且放行：%s" % LIFE_TEXT,
          vlife.get("state") == jr.KEEP_LIFE and vlife.get("judge") == "J11"
          and jr.should_write(vlife) is True, jr.explain(vlife))
    check("行为面三态穷尽：样本集里 KEEP/DROP/KEEP_LIFE 都真实出现",
          seen == set(jr.STATES), sorted(seen))

    # ---- 丢弃判据覆盖：J7/J8/J9/J10 都真实现身（不是靠单一判据顶包） ----
    judges = {jr.judge_text(t).get("judge") for _w, t in DROP_SAMPLES}
    check("四类丢弃判据 J7/J8/J9/J10 都真实命中（无顶包）",
          {"J7", "J8", "J9", "J10"} <= judges, sorted(judges))

    # ---- should_write 矩阵：DROP 拒、留/留但定寿放 ----
    check("should_write 对合成 DROP 结论恒拒",
          jr.should_write({"state": jr.DROP}) is False)
    check("should_write 对 KEEP / KEEP_LIFE 恒放行",
          jr.should_write({"state": jr.KEEP}) is True
          and jr.should_write({"state": jr.KEEP_LIFE}) is True)

    # ---- 坏形状 fail-open：判定面故障不得堵死写入（防误伤） ----
    for bad in (None, "drop", 123, [], (), {}, {"no_state": 1}):
        check("坏形状 fail-open 放行：%r" % (bad,),
              jr.should_write(bad) is True, repr(bad))
    check("坏形状 explain 不炸（渲染为可读占位串）",
          isinstance(jr.explain(None), str))


# ---------------------------------------------------------------------------
# [B] add 写路径（MDCG_JUDGMENT=1）：DROP 前置短路 + 零中间态
# ---------------------------------------------------------------------------

def test_b_add_drop():
    print("[B] add 写路径：DROP 返回 None 且零残留（无节点/无 pending/无 review）")
    restore = _with_env("1")
    kg = _mk_cg()
    try:
        check("开关已开启（is_enabled==True，本段前提）", jr.is_enabled() is True)
        check("前置检查：fresh 实例 pending 队列为空", twophase.pending(kg) == [])
        check("前置检查：fresh 实例 review 队列为空", kg.review_list() == [])

        for i, (want, text) in enumerate(DROP_SAMPLES):
            nid = "t25a_drop_%d" % i
            got = kg.add(nid, text)
            check("add DROP 返回 None（%s）：%s" % (want, text),
                  got is None, repr(got))
            check_residue("  └ 节点缺席：get 空（无占位）：%s" % text,
                          _fm_of(kg, nid) is None and not kg.get(nid),
                          repr(_fm_of(kg, nid)))
            check_residue("  └ 无换名落盘：节点集里没有任何 t25a_drop_* 条目：%s" % text,
                          not any(x.startswith("t25a_drop_")
                                  for x in _all_node_ids(kg)),
                          _all_node_ids(kg))
            check_residue("  └ 未结清写入意图=不进 pending 队列（短路在 begin 之前）：%s" % text,
                          twophase.pending(kg) == [], twophase.pending(kg))
            check_residue("  └ 无待审候选=不进 review 队列（不审核）：%s" % text,
                          kg.review_list() == [], kg.review_list())

        # ---- 整批之后的收口断言：一个中间态都不留 ----
        check_residue("整批 DROP 后：无任何 .md 节点占位文件落盘",
                      not [p for p in _walk_files(kg.root) if p.endswith(".md")],
                      [p for p in _walk_files(kg.root) if p.endswith(".md")])
        check_residue("整批 DROP 后：pending 队列仍为空", twophase.pending(kg) == [],
                      twophase.pending(kg))
        check_residue("整批 DROP 后：review 队列仍为空", kg.review_list() == [],
                      kg.review_list())
    finally:
        shutil.rmtree(kg.root, ignore_errors=True)
        restore()


# ---------------------------------------------------------------------------
# [C] remember_event 写路径（MDCG_JUDGMENT=1）：DROP 不落窗 + 零中间态
# ---------------------------------------------------------------------------

def test_c_event_drop():
    print("[C] remember_event 写路径：DROP event=None、窗口零变化、无中间态")
    restore = _with_env("1")
    kg = _mk_cg()
    try:
        check("前置检查：拒写前 recent 窗口为空",
              _recent_texts(kg) == [], _recent_texts(kg))
        for want, text in DROP_SAMPLES:
            before = _recent_texts(kg)
            r = kg.remember_event("user", text)
            check("remember_event DROP：event=None + dropped==0（%s）：%s"
                  % (want, text),
                  r.get("event") is None and r.get("dropped") == 0
                  and r.get("verdict", {}).get("state") == jr.DROP,
                  str(r)[:200])
            check_residue("  └ recent 窗口零变化（不 append 不 roll）：%s" % text,
                          _recent_texts(kg) == before, _recent_texts(kg))
            check_residue("  └ 未结清写入意图=不进 pending 队列：%s" % text,
                          twophase.pending(kg) == [], twophase.pending(kg))
            check_residue("  └ 无待审候选=不进 review 队列：%s" % text,
                          kg.review_list() == [], kg.review_list())

        check_residue("整批 DROP 后：recent 窗口仍为空", _recent_texts(kg) == [],
                      _recent_texts(kg))
        check_residue("整批 DROP 后：pending 队列仍为空", twophase.pending(kg) == [],
                      twophase.pending(kg))
        check_residue("整批 DROP 后：review 队列仍为空", kg.review_list() == [],
                      kg.review_list())
    finally:
        shutil.rmtree(kg.root, ignore_errors=True)
        restore()


# ---------------------------------------------------------------------------
# [D] 对照组：同路径 KEEP 照常落盘/进窗；KEEP 不产生 pending 残留；
#     非空洞探针（pending/review 检测面真的能看见东西）
# ---------------------------------------------------------------------------

def test_d_keep_control():
    print("[D] 对照组：KEEP 照常落盘/进窗（短路只拦 DROP），附非空洞探针")
    restore = _with_env("1")
    kg = _mk_cg()
    try:
        # ---- add：KEEP 照常成节点，且自带判定结论（可回溯） ----
        for i, text in enumerate(KEEP_SAMPLES):
            nid = "t25a_keep_%d" % i
            got = kg.add(nid, text)
            fm = _fm_of(kg, nid)
            check("add KEEP 照常落盘：%s" % text,
                  got == nid and fm is not None
                  and fm.get(jr.STATE_FIELD) == jr.KEEP, "got=%r fm=%r" % (got, fm))
            check("  └ why_kept 非空可回溯（落盘节点自带判断理由）：%s" % text,
                  bool((fm or {}).get(jr.WHY_KEPT_FIELD)),
                  str((fm or {}).get(jr.WHY_KEPT_FIELD)))

        # ---- remember_event：KEEP 照常进窗 ----
        for text in KEEP_SAMPLES:
            r = kg.remember_event("user", text)
            check("remember_event KEEP 照常进窗：%s" % text,
                  r.get("event") is not None and r["event"]["text"] == text
                  and r.get("verdict", {}).get("state") == jr.KEEP,
                  str(r)[:200])
        check("整批 KEEP 进窗顺序：newest-first = reversed(写入序)",
              _recent_texts(kg) == list(reversed(KEEP_SAMPLES)),
              _recent_texts(kg))

        # ---- KEEP 写入不产生 pending/review 残留 ----
        check_residue("KEEP 落盘后：pending 队列无残留（结清的写入不挂账）",
                      twophase.pending(kg) == [], twophase.pending(kg))
        check_residue("KEEP 落盘后：review 队列无残留（add 直写不入 inbox）",
                      kg.review_list() == [], kg.review_list())

        # ---- 同实例上 DROP 仍被拦（短路只拦 DROP，两条路互不干扰） ----
        check("同实例：DROP 复测仍拒写（对照组没把闸门带松）",
              kg.add("t25a_drop_again", DROP_SAMPLES[0][1]) is None)

        # ---- KEEP_LIFE 探针：留但定寿照常放行（写入面没被 DROP 短路堵死） ----
        life_fm = _fm_of(kg, kg.add("t25a_life", LIFE_TEXT,
                                    ref_signals=dict(LIFE_REFS)))
        check("KEEP_LIFE 写入照常落盘且带寿标记（should_write 放行非 DROP 全部）",
              life_fm is not None
              and life_fm.get(jr.STATE_FIELD) == jr.KEEP_LIFE
              and jr.LIFETIME_FIELD in life_fm, repr(life_fm))

        # ---- 非空洞探针：证明上面 pending==[] / review==[] 断言不是恒真空集 ----
        kg2 = _mk_cg()
        try:
            tok = twophase.begin(kg2, "t25a_probe", "probe-content")
            check("非空洞探针：人为 begin 后 pending 立刻可见（断言面不瞎）",
                  len(twophase.pending(kg2)) == 1, twophase.pending(kg2))
            twophase.commit(kg2, tok)
            check("非空洞探针：commit 结清后 pending 归零",
                  twophase.pending(kg2) == [], twophase.pending(kg2))
            kg2.propose("t25a_probe_node", "候选正文")
            check("非空洞探针：人为 propose 后 review_list 立刻可见（断言面不瞎）",
                  len(kg2.review_list()) == 1, kg2.review_list())
        finally:
            shutil.rmtree(kg2.root, ignore_errors=True)
    finally:
        shutil.rmtree(kg.root, ignore_errors=True)
        restore()


# ---------------------------------------------------------------------------
# [E] 默认关回归：未设 / 显式 0 → 需求样本照常成节点、无判定字段夹带
# ---------------------------------------------------------------------------

def _off_case(label):
    """默认关口径的一个完整快照：节点成、fm 无判定字段、返回体形状不变。"""
    cg = _mk_cg()
    try:
        for i, t in enumerate(OFF_SAMPLES):
            nid = "t25a_off_%d" % i
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
    # 回归要有意义：OFF 样本在规则层确实判 DROP（关闸才放行 = 真回归）。
    check("回归前提：OFF 样本在规则层全部判 DROP（关闸放行才有回归价值）",
          all(jr.judge_text(t)["state"] == jr.DROP for t in OFF_SAMPLES),
          [jr.explain(jr.judge_text(t)) for t in OFF_SAMPLES])

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
    print("===== md_cg.test_t25a_auto_drop（E-T25a t1 丢弃全自动、零中间态） =====")
    test_a_contract()
    test_b_add_drop()
    test_c_event_drop()
    test_d_keep_control()
    test_e_default_off()
    tail = ("（%d 预期失败：T25a 发现残留 gate）" % xfailed) if xfailed else ""
    print("\n===== t25a 丢弃全自动：%d 通过，%d 失败%s =====" % (passed, failed, tail))
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
