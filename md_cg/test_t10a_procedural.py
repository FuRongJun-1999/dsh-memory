# -*- coding: utf-8 -*-
r"""test_t10a_procedural —— 过程性内容（讨论 / 选项 / 取舍）拒写：单元判定 + 写入侧接线 + 关闭回归
（E-T10a t1）。

## 这个测试锁的是什么

「过程性内容」= 一段对话里头**来回商量的过程**本身：讨论（『要不要换个方案』）、
选项（『A 还是 B，你倾向哪个』）、取舍（『权衡一下』）。这类内容的**结论**值得留，
过程**不值得**——判据真源 `md_cg/judgment_rules.py` 的 J8「讨论过程（选项、取舍、
来回商量）」state=DROP，`_PRIORITY` 里丢在留前面（`("J9","J7","J8","J11","J10",
"J1"…)`），故混合句按「丢」处理。

本测试**不改任何规则**（`judgment_rules.py` 只读、J8 词表本轮不动），只做三件事：
把过程性内容喂给判定面、喂给写入路径、再把开关关掉看行为有没有回退。

## 三段

  [A] 单元判定：≥3 个**真实对话形态**的过程性样本（讨论 / 选项 / 取舍各一），
      `judge_event` 与 `judge_text` 对每个样本都返回 DROP（命中 J8 或更高优先级的
      drop 规则均可），`evidence` 非空，且**绝不返回 None / 空态**；同一段对话里
      混一条可复用结论（KEEP 对照），证明不是一刀切全丢。
  [B] 写入侧接线（显式 `MDCG_JUDGMENT=1`）：DROP 类样本走 `remember_event` / `add`
      的既有前置短路（`mdcg.py` 未改）→ 断言**拒写**：`add` 返回 None、节点缺位、
      recent 里查不到该文本、**无占位节点**；KEEP 对照样本断言正常落盘。
  [C] 关闭回归：`MDCG_JUDGMENT` 未设（默认关）时同一样本的写入行为与接线前
      **逐字节一致**（节点照常落盘、frontmatter 不出现 `judgment_state` 等判定
      字段）；再显式置 0 各跑一遍等价。

## 真实性发现（**未改规则**，按事实调整样本）

蓝图举例的「方案A还是方案B，你倾向哪个」**并未**被现有 J8 命中：J8 的选项式
正则只有 `(?:A|甲)\s*(?:还是|或)\s*(?:B|乙)`（要求裸 A/B 或 甲/乙）与
`(?:方案|选项)\s*(?:一|二|1|2|甲|乙)`（要求方案**一/二**这类序数，不是「方案A」），
「方案A还是方案B」两边都不沾，实测落 `keep J6 ['fallback:no-rule-hit']`。
本测试**不为过门而改 J8 词表**，改用被现有规则真实命中的同形态样本
（`A还是B，你倾向哪个` → J8 `['A还是B']`；`方案一还是方案二，你倾向哪个`
→ J8 `['方案一']`），并把原句作为「不被命中」的反例一并断言（见 `test_a_unit`
的 `_UNMATCHED_BLUEPRINT` 一节），免得这个 J8 空档被后来的改动悄悄抹平。

运行：python -X utf8 -m md_cg.test_t10a_procedural
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

#: 过程性样本（真实对话形态）：讨论 / 选项 / 取舍各一，均被现有规则真实命中 DROP。
#: 每条带 (标签, 文本, 期望判据集合)——期望判据写成集合，允许更高优先级的 drop
#: 规则抢先（J9/J7 排在 J8 前），但**必须**是 DROP，且 J8 至少在一个样本上现身。
_PROCEDURAL = (
    ("讨论", "我们要不要考虑换个方案？", ("J8",)),
    ("选项", "A还是B，你倾向哪个？", ("J8",)),
    ("选项-序数", "方案一还是方案二，你倾向哪个？", ("J8",)),
    ("取舍", "权衡一下，先跑通再优化还是先优化再跑通？", ("J8",)),
    ("取舍-商量", "两种方案各有取舍，商量一下到底用哪个", ("J8",)),
    ("讨论-泛化", "讨论一下这个设计怎么收口", ("J8",)),
)

#: KEEP 对照：同一段对话里混入的**可复用结论**（不是过程，是过程产出的东西）。
_KEEP_CONTROL = "结论是 X 模块放 D:\\wook\\lingshu-src"

#: 真实对话形态的**混合段**：过程 + 结论同段，验证不是一刀切全丢。
_MIXED = ("我们要不要考虑换个方案？"
          "结论是 X 模块放 D:\\wook\\lingshu-src")

#: 蓝图原句：**现有 J8 不命中**（真实性发现，见模块头）。作为反例锁住这个空档，
#: 不改规则——只记录事实。
_UNMATCHED_BLUEPRINT = "方案A还是方案B，你倾向哪个"


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


def _mk_cg():
    return MdCGOS(tempfile.mkdtemp(prefix="mdcg_t10a_"))


def _state_of(v):
    """判定结论的三态；坏形状（None/非 dict）返回哨兵串「<bad-shape>」。"""
    if not isinstance(v, dict):
        return "<bad-shape>"
    return v.get("state")


# ---------------------------------------------------------------------------
# [A] 单元判定：过程性内容 → DROP（J8 或更高优先级），KEEP 对照 → 留
# ---------------------------------------------------------------------------

def test_a_unit():
    print("[A] 单元判定：过程性内容（讨论/选项/取舍）判 DROP，KEEP 对照判留")

    # ---- 过程性样本逐条：judge_event 与 judge_text 都必须判 DROP ----
    for label, text, want in _PROCEDURAL:
        v = jr.judge_event({"role": "user", "text": text})
        check("过程性/%s：judge_event 判 DROP（判据 %s）" % (label, "/".join(want)),
              _state_of(v) == jr.DROP and v.get("judge") in want,
              jr.explain(v))
        check("过程性/%s：evidence 非空且绝不返回 None/空态" % label,
              isinstance(v, dict) and v.get("state") in jr.STATES
              and bool(v.get("evidence")) and v.get("state") != "",
              repr(v))

        vt = jr.judge_text(text, role="user")
        check("过程性/%s：judge_text 同判 DROP（两入口一致）" % label,
              _state_of(vt) == jr.DROP and vt.get("judge") == v.get("judge"),
              jr.explain(vt))

    # ---- J8 至少真实现身一次（不是靠 J7/J9 顶包冒充）----
    judges = {jr.judge_event({"role": "user", "text": t}).get("judge")
              for _l, t, _w in _PROCEDURAL}
    check("过程性：J8 在样本集里真实命中（非 J7/J9 顶包）",
          "J8" in judges, sorted(judges))

    # ---- 强制拒写口径：should_write 对这些样本一律 False ----
    for label, text, _w in _PROCEDURAL:
        v = jr.judge_event({"role": "user", "text": text})
        check("过程性/%s：should_write 拒写（DROP ⇒ False）" % label,
              jr.should_write(v) is False, jr.explain(v))

    # ---- KEEP 对照：可复用结论照常留，证明不是一刀切 ----
    vk = jr.judge_event({"role": "user", "text": _KEEP_CONTROL})
    check("对照/KEEP：可复用结论判留（J4 技术结论 + 路径）",
          _state_of(vk) == jr.KEEP and vk.get("judge") == "J4"
          and jr.should_write(vk) is True, jr.explain(vk))

    # ---- 混合段：过程 + 结论同段 ⇒ 取更高优先级 = 丢（有意的成本不对称）----
    vm = jr.judge_event({"role": "user", "text": _MIXED})
    check("混合段（过程+结论）：按优先级取丢（丢排在留前面）",
          _state_of(vm) == jr.DROP and jr.should_write(vm) is False,
          jr.explain(vm))
    check("混合段：结论词仍在 evidence/state_of 里可回溯（没被静默抹掉）",
          any("结论是" in str(e) or "模块" in str(e) for e in vm.get("evidence", []))
          or jr.judge_text("结论是 X 模块放 D:\\wook\\lingshu-src",
                           role="user").get("judge") == "J4",
          jr.explain(vm))

    # ---- 真实性发现：蓝图原句未被现有 J8 命中（不改规则，只锁事实）----
    vun = jr.judge_event({"role": "user", "text": _UNMATCHED_BLUEPRINT})
    check("真实性发现：『方案A还是方案B』未被现有 J8 命中（记录，不改规则）",
          _state_of(vun) != jr.DROP or vun.get("judge") != "J8",
          "实际=%s；J8 正则只认裸 A/B 或 方案一/方案二，不认「方案A」"
          % jr.explain(vun))
    check("真实性发现的反例已被改用样本覆盖（同形态的 A还是B 真命中 J8）",
          jr.judge_event({"role": "user",
                          "text": "A还是B，你倾向哪个？"}).get("judge") == "J8")


# ---------------------------------------------------------------------------
# [B] 写入侧接线（MDCG_JUDGMENT=1）：DROP 拒写 + KEEP 正常落盘
# ---------------------------------------------------------------------------

def test_b_wiring():
    print("[B] 接线：过程性内容拒写（add 返回 None / recent 查不到 / 无占位节点）")
    _env_prev = os.environ.get(_ENV_KEY)
    os.environ[_ENV_KEY] = "1"
    kg = _mk_cg()
    try:
        # ---- add：DROP 类样本逐条拒写 ----
        for i, (label, text, _w) in enumerate(_PROCEDURAL):
            nid = "t10a_drop_%d" % i
            got = kg.add(nid, text)
            check("接线 add/过程性-%s：返回 None（拒写）" % label,
                  got is None, repr(got))
            check("接线 add/过程性-%s：节点缺位（get 取不到）" % label,
                  _fm_of(kg, nid) is None, repr(_fm_of(kg, nid)))

        # ---- 无占位节点：DROP 轮次里一个节点都不该落 ----
        ids = _all_node_ids(kg)
        check("接线：拒写后无任何占位节点（节点集为空）",
              not any(x.startswith("t10a_drop_") for x in ids), ids)
        check("接线：无占位文件落盘（只有审计日志，无 .md 节点）",
              not [p for p in _walk_files(kg.root) if p.endswith(".md")],
              _walk_files(kg.root))

        # ---- remember_event：DROP 类样本不落窗 ----
        d = kg.remember_event("user", _PROCEDURAL[0][1])
        check("接线 remember_event/过程性：event=None + verdict=DROP",
              d["event"] is None and d["verdict"]["state"] == jr.DROP
              and jr.is_enabled() is True, jr.explain(d["verdict"]))
        check("接线 remember_event：recent 里查不到该过程性文本",
              _PROCEDURAL[0][1] not in _recent_texts(kg),
              _recent_texts(kg))
        check("接线 remember_event：拒写事件窗口零变化（recent 为空）",
              _recent_texts(kg) == [], _recent_texts(kg))

        # ---- KEEP 对照：正常落盘 ----
        nk = kg.add("t10a_keep", _KEEP_CONTROL)
        fmk = _fm_of(kg, nk)
        check("接线 add/KEEP 对照：正常返回 id + fm.judgment_state=keep",
              nk == "t10a_keep" and fmk.get(jr.STATE_FIELD) == jr.KEEP,
              repr((nk, fmk)))
        check("接线 add/KEEP 对照：fm 不带 why_kept 之外的污染（字段可回溯）",
              bool(fmk.get(jr.WHY_KEPT_FIELD, "")), repr(fmk))

        rk = kg.remember_event("user", _KEEP_CONTROL)
        check("接线 remember_event/KEEP 对照：正常落窗 + meta 打 judgment_state",
              rk["event"] is not None
              and rk["event"]["meta"].get(jr.STATE_FIELD) == jr.KEEP
              and _recent_texts(kg) == [_KEEP_CONTROL], str(rk))

        # ---- DROP 与 KEEP 并存：过程不进窗、结论进窗 ----
        check("接线：同实例内过程性内容与结论互不影响（拒写的没挤掉该留的）",
              _PROCEDURAL[0][1] not in _recent_texts(kg)
              and _KEEP_CONTROL in _recent_texts(kg), _recent_texts(kg))
    finally:
        shutil.rmtree(kg.root, ignore_errors=True)
        if _env_prev is None:
            os.environ.pop(_ENV_KEY, None)
        else:
            os.environ[_ENV_KEY] = _env_prev


def _walk_files(root):
    out = []
    for base, _dirs, files in os.walk(root):
        for f in files:
            out.append(os.path.join(base, f))
    return out


# ---------------------------------------------------------------------------
# [C] 关闭回归：未设（默认关）/ 显式 0 —— 与接线前逐字节一致
# ---------------------------------------------------------------------------

def _assert_closed_behavior(label):
    cg = _mk_cg()
    try:
        # 过程性样本在关闸下照常落盘（存量契约：默认关 = 不拦）
        for i, (kind, text, _w) in enumerate(_PROCEDURAL):
            nid = "t10a_off_%d" % i
            got = cg.add(nid, text)
            fm = _fm_of(cg, nid)
            check("%s add/过程性-%s：照常成节点（不拦）" % (label, kind),
                  got == nid and fm is not None, repr(got))
            check("%s add/过程性-%s：fm 不出现判定字段（无 judgment_state）"
                  % (label, kind),
                  fm is not None and jr.STATE_FIELD not in fm
                  and jr.LIFETIME_FIELD not in fm
                  and jr.REF_COUNT_FIELD not in fm
                  and jr.WHY_KEPT_FIELD not in fm, repr(fm))

        # KEEP 对照同样照常落盘且不带判定字段
        nk = cg.add("t10a_off_keep", _KEEP_CONTROL)
        fmk = _fm_of(cg, nk)
        check("%s add/KEEP 对照：照常落盘且无判定字段" % label,
              nk == "t10a_off_keep" and jr.STATE_FIELD not in fmk, repr(fmk))

        # 事件面：返回体形状与接线前一致（无 verdict 键夹带）
        r = cg.remember_event("user", _PROCEDURAL[0][1])
        check("%s remember_event：返回体形状不变（仅 event/dropped 两键）" % label,
              set(r.keys()) == {"event", "dropped"}
              and r["event"] is not None
              and "verdict" not in r, str(r))
        check("%s remember_event：过程性文本照常进窗（recent 查得到）" % label,
              _PROCEDURAL[0][1] in _recent_texts(cg), _recent_texts(cg))
        check("%s remember_event：meta 不带判定字段" % label,
              jr.STATE_FIELD not in r["event"]["meta"]
              and jr.WHY_KEPT_FIELD not in r["event"]["meta"],
              str(r["event"]["meta"]))
    finally:
        shutil.rmtree(cg.root, ignore_errors=True)


def test_c_closed():
    print("[C] 关闭回归：未设（默认关）+ 显式 0，均照常落盘、无判定字段")
    # 场景 1：开关未设（模块 import 时已 pop 自管）= 默认关
    _env_prev = os.environ.pop(_ENV_KEY, None)
    try:
        check("关闭/未设：is_enabled() 为 False", jr.is_enabled() is False)
        _assert_closed_behavior("关闭/未设")
    finally:
        if _env_prev is not None:
            os.environ[_ENV_KEY] = _env_prev
    # 场景 2：显式 MDCG_JUDGMENT=0 关闭
    prev2 = os.environ.get(_ENV_KEY)
    os.environ[_ENV_KEY] = "0"
    try:
        check("关闭/=0：is_enabled() 为 False", jr.is_enabled() is False)
        _assert_closed_behavior("关闭/=0")
    finally:
        if prev2 is None:
            os.environ.pop(_ENV_KEY, None)
        else:
            os.environ[_ENV_KEY] = prev2


def main():
    print("===== md_cg.test_t10a_procedural（E-T10a t1 过程性内容拒写） =====")
    test_a_unit()
    test_b_wiring()
    test_c_closed()
    print("\n===== t10a 过程性：%d 通过，%d 失败 =====" % (passed, failed))
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
