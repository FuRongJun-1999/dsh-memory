# -*- coding: utf-8 -*-
"""test_t31a_whykept —— why_kept 判断理由字段：写入侧接线 + 测试（E-T31a t1）。

在 T18 判定面（默认**关闭**；`MDCG_JUDGMENT=1|true|on|yes|enable` 显式开启）之上：
每次写入（add / remember_event）自动生成并落一条**非空** why_kept 判断理由
（AI 自判、不靠用户标注）——理由来源于判定 verdict 的命中规则/evidence
（如「J6 能长期成立的事实（证据：长期）」），KEEP 与 KEEP_LIFE 均带；
开关关闭（MDCG_JUDGMENT 未设 / 显式 0）时不落该字段，写入行为与接线前
逐字节一致（契约真源 judgment_rules.py is_enabled() 默认关）。

三段（口径真源 md_cg/judgment_rules.py，接线真源 md_cg/mdcg.py 的
MdCG.add / MdCG.remember_event 前置短路）：

  [A] 单元：why_kept_of(verdict)——KEEP 各判据（J1–J6）与 KEEP_LIFE（J11）
      返回含判据名 + 证据的非空串；DROP / 坏形状返回空串；不抄录正文。
  [B] 接线（MDCG_JUDGMENT=1 显式开启）：真实对话样本写入后，remember_event 的
      meta 与 add 的 frontmatter 均带非空 why_kept 且可回溯到判定
      （== jr.why_kept_of(同输入 verdict)）；每态至少一个样本；
      DROP 拒写无节点可附。
  [C] 关闭回归（MDCG_JUDGMENT 未设 = 默认关，再显式 0 各跑一遍）：
      写入行为与接线前逐字节一致——记录体 / frontmatter 均不出现 why_kept
      （与任一判定字段）。

运行：python -X utf8 -m md_cg.test_t31a_whykept
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
    return MdCGOS(tempfile.mkdtemp(prefix="mdcg_t31a_"))


# ---------------------------------------------------------------------------
# [A] 单元：why_kept_of(verdict)
# ---------------------------------------------------------------------------

def test_a_unit():
    print("[A] 单元 why_kept_of：留/留但定寿非空且可回溯，丢/坏形状空串")

    # ---- KEEP（J1–J6 各一真实对话样本）----
    v = jr.judge_event({"role": "user",
                        "text": "我讨厌你先讲道理，先接住我的情绪再说"})
    w = jr.why_kept_of(v)
    check("KEEP/J1：非空 + 含判据名 + 含证据",
          v["state"] == jr.KEEP and bool(w) and "J1" in w
          and any(e in w for e in v["evidence"]), repr(w))

    v = jr.judge_event({"role": "user",
                        "text": "你的性格要沉淀下来：先接住情绪，再讲道理"})
    w = jr.why_kept_of(v)
    check("KEEP/J2：非空 + 含判据名", bool(w) and "J2" in w, repr(w))

    v = jr.judge_event({"role": "user",
                        "text": "我们俩以后就按这个分工来，不再互相抢活"})
    check("KEEP/J3：非空 + 含判据名",
          jr.why_kept_of(v) and "J3" in jr.why_kept_of(v),
          jr.why_kept_of(v))

    v = jr.judge_event({"role": "assistant",
                        "text": "报错原文是 KeyError，根因是 md_cg/run_tests.py:24 的管道"})
    w = jr.why_kept_of(v)
    check("KEEP/J4：理由含技术结论证据",
          v["state"] == jr.KEEP and bool(w) and "J4" in w
          and "run_tests.py:24" in w, repr(w))

    v = jr.judge_event({"role": "user",
                        "text": "诊断脚本在 D:\\tools\\probe.ps1，跑法见 README。"})
    w = jr.why_kept_of(v)
    check("KEEP/J5：理由含路径证据",
          bool(w) and "J5" in w and any(e in w for e in v["evidence"]), repr(w))

    v = jr.judge_event({"role": "user",
                        "text": "这台机器上 Python 默认必须走 UTF-8，长期如此"})
    w = jr.why_kept_of(v)
    check("KEEP/J6（长期成立事实）：非空 + 含判据名 + 含证据",
          v["state"] == jr.KEEP and v["judge"] == "J6" and bool(w)
          and "J6" in w and "长期" in w, repr(w))

    # ---- 兜底 J6（无命中）也带理由 ----
    v = jr.judge_event({"role": "user", "text": "嗯，这个数值是 42。"})
    w = jr.why_kept_of(v)
    check("KEEP/J6 兜底：非空 + 含 fallback 证据",
          v["state"] == jr.KEEP and v["judge"] == "J6" and bool(w)
          and "fallback" in w, repr(w))

    # ---- KEEP_LIFE（J11）----
    v = jr.judge_event({"role": "user", "text": "这份光谱对照表以后可能有用，先留着。",
                        "ref_signals": {"ref_count": 0}})
    w = jr.why_kept_of(v)
    check("KEEP_LIFE/J11：非空 + 含判据名 + 含证据（ref_count 或寿命词）",
          v["state"] == jr.KEEP_LIFE and bool(w) and "J11" in w
          and ("留着" in w or "ref_count" in w), repr(w))

    v = jr.judge_event({"role": "user", "text": "这份光谱对照表以后可能有用，先留着。",
                        "ref_signals": {"ref_count": 3, "cited": True}})
    w = jr.why_kept_of(v)
    check("KEEP_LIFE/J11（ref_count>0）：理由含引用计数信号",
          bool(w) and "J11" in w and "ref_count" in w, repr(w))

    # ---- DROP / 坏形状：空串 ----
    v = jr.judge_event({"role": "tool-output",
                        "text": "python check.py\nPASS 3/3\n[exit code: 0]"})
    check("DROP/J9：why_kept 空串（拒写无节点可附）",
          v["state"] == jr.DROP and jr.why_kept_of(v) == "", jr.explain(v))

    v = jr.judge_event({"role": "user", "text": "今天把 report.pdf 生成一下"})
    check("DROP/J7：why_kept 空串",
          v["state"] == jr.DROP and jr.why_kept_of(v) == "", jr.explain(v))

    check("坏形状（None/非 dict/缺 state）：why_kept 空串",
          jr.why_kept_of(None) == "" and jr.why_kept_of("x") == ""
          and jr.why_kept_of({}) == "")

    # ---- 不抄录正文：理由只含判据名 + 证据片段，不含正文全文 ----
    body = "我讨厌你先讲道理，先接住我的情绪再说"
    v = jr.judge_event({"role": "user", "text": body})
    w = jr.why_kept_of(v)
    check("不抄录正文：why_kept 不含正文全文",
          bool(w) and body not in w, repr(w))


# ---------------------------------------------------------------------------
# [B] 接线（MDCG_JUDGMENT=1）：remember_event / add 落非空 why_kept
# ---------------------------------------------------------------------------

def test_b_wiring():
    print("[B] 接线：写入路径落 why_kept（MDCG_JUDGMENT=1，每态至少一样本）")
    _env_prev = os.environ.get(_ENV_KEY)
    os.environ[_ENV_KEY] = "1"
    kg = _mk_cg()
    try:
        # ---- remember_event：KEEP / KEEP_LIFE 带 why_kept，DROP 拒写 ----
        k = kg.remember_event("user",
                              "这台机器上 Python 默认必须走 UTF-8，长期如此")
        wk = k["event"]["meta"].get(jr.WHY_KEPT_FIELD, "")
        check("remember_event KEEP/J6：meta.why_kept 非空且可回溯到判定",
              k["event"] is not None
              and k["event"]["meta"].get(jr.STATE_FIELD) == jr.KEEP
              and bool(wk) and "J6" in wk and "长期" in wk
              and wk == jr.why_kept_of(k["verdict"]), repr(wk))

        k1 = kg.remember_event("user", "我讨厌你先讲道理，先接住我的情绪再说")
        wk1 = k1["event"]["meta"].get(jr.WHY_KEPT_FIELD, "")
        check("remember_event KEEP/J1：也带非空 why_kept",
              bool(wk1) and "J1" in wk1
              and wk1 == jr.why_kept_of(k1["verdict"]), repr(wk1))

        l1 = kg.remember_event("user",
                               "这份光谱对照表以后可能有用，先留着。",
                               meta={"ref_count": 3})
        wk2 = l1["event"]["meta"].get(jr.WHY_KEPT_FIELD, "")
        check("remember_event KEEP_LIFE/J11：why_kept 非空 + 寿命标记并存",
              l1["event"]["meta"].get(jr.STATE_FIELD) == jr.KEEP_LIFE
              and bool(wk2) and "J11" in wk2
              and l1["event"]["meta"].get(jr.LIFETIME_FIELD,
                                          {}).get("policy") == "ref_count_positive"
              and wk2 == jr.why_kept_of(l1["verdict"]), repr(wk2))

        d = kg.remember_event("command", "python check.py\nPASS 3/3")
        check("remember_event DROP/J9：拒写无节点、无 why_kept 可附",
              d["event"] is None and d["verdict"]["state"] == jr.DROP
              and _recent_texts(kg) == ["这份光谱对照表以后可能有用，先留着。",
                                        "我讨厌你先讲道理，先接住我的情绪再说",
                                        "这台机器上 Python 默认必须走 UTF-8，长期如此"],
              str(d))

        # ---- add：KEEP / KEEP_LIFE 落 fm.why_kept，DROP 返回 None ----
        k3 = kg.add("t31a_keep_j6",
                    "这台机器上 Python 默认必须走 UTF-8，长期如此",
                    layer="self")
        fm3 = _fm_of(kg, k3)
        wk3 = fm3.get(jr.WHY_KEPT_FIELD, "") if fm3 else ""
        check("add KEEP/J6：fm.why_kept 非空且可回溯到判定",
              k3 == "t31a_keep_j6" and fm3.get(jr.STATE_FIELD) == jr.KEEP
              and bool(wk3) and "J6" in wk3
              and "长期" in wk3
              and wk3 == jr.why_kept_of(
                  jr.judge_event({"role": None, "text": "这台机器上 Python 默认必须走 UTF-8，长期如此"})),
              repr(wk3))

        k4 = kg.add("t31a_keep_j4",
                    "根因是 md_cg/run_tests.py:24 的管道读取用了 cp936",
                    layer="knowledge")
        fm4 = _fm_of(kg, k4)
        wk4 = fm4.get(jr.WHY_KEPT_FIELD, "") if fm4 else ""
        check("add KEEP/J4：理由含技术结论证据片段",
              k4 == "t31a_keep_j4" and bool(wk4) and "J4" in wk4
              and "run_tests.py:24" in wk4, repr(wk4))

        l2 = kg.add("t31a_life_j11",
                    "这份光谱对照表以后可能有用，先留着。",
                    layer="knowledge", ref_signals={"ref_count": 0})
        fm5 = _fm_of(kg, l2)
        wk5 = fm5.get(jr.WHY_KEPT_FIELD, "") if fm5 else ""
        check("add KEEP_LIFE/J11：fm.why_kept 非空 + 寿命标记并存",
              l2 == "t31a_life_j11"
              and fm5.get(jr.STATE_FIELD) == jr.KEEP_LIFE
              and fm5.get(jr.LIFETIME_FIELD, {}).get("policy") == "ref_count_zero"
              and bool(wk5) and "J11" in wk5, repr(wk5))

        d2 = kg.add("t31a_drop_j7", "今天把 report.pdf 生成一下")
        check("add DROP/J7：返回 None、节点缺席、无 why_kept 字段",
              d2 is None and _fm_of(kg, "t31a_drop_j7") is None, repr(d2))
    finally:
        shutil.rmtree(kg.root, ignore_errors=True)
        if _env_prev is None:
            os.environ.pop(_ENV_KEY, None)
        else:
            os.environ[_ENV_KEY] = _env_prev


# ---------------------------------------------------------------------------
# [C] 关闭回归（默认关=未设，与显式 0 各跑一遍）：不落 why_kept，逐字节一致
# ---------------------------------------------------------------------------

def _assert_closed_behavior(label):
    cg = _mk_cg()
    try:
        r = cg.remember_event("command", "pytest -k login")
        check(label + " role=command 事件照常进窗（无 verdict / why_kept 键夹带）",
              r["event"] is not None and r["event"]["text"] == "pytest -k login"
              and "verdict" not in r
              and set(r["event"].keys()) == {"t", "role", "text", "tags", "meta"}
              and jr.WHY_KEPT_FIELD not in r["event"]["meta"], str(r))

        r2 = cg.remember_event("user", "开始重构登录模块")
        check(label + " 正常事件返回体形状不变（仅 event/dropped 两键）",
              set(r2.keys()) == {"event", "dropped"}
              and jr.WHY_KEPT_FIELD not in r2["event"]["meta"], str(r2))

        nid = cg.add("t31a_off", "今天把 report.pdf 生成一下")
        fm = _fm_of(cg, nid)
        check(label + " add 不拦（J7 类正文照常成节点；无判定字段）",
              nid == "t31a_off"
              and jr.STATE_FIELD not in fm
              and jr.WHY_KEPT_FIELD not in fm, repr(fm))

        nid2 = cg.add("t31a_off2", "缓存策略是临时的")
        fm2 = _fm_of(cg, nid2)
        check(label + " add J10 类正文照常写入（无 why_kept）",
              nid2 == "t31a_off2" and jr.WHY_KEPT_FIELD not in fm2, repr(fm2))
    finally:
        shutil.rmtree(cg.root, ignore_errors=True)


def test_c_closed():
    print("[C] 关闭回归：默认关（未设）+ 显式 0，均不落 why_kept、行为与接线前一致")
    # 场景 1：开关未设（本模块 import 时已 pop 自管）= 默认关
    _env_prev = os.environ.pop(_ENV_KEY, None)
    try:
        _assert_closed_behavior("关闭/未设")
    finally:
        if _env_prev is not None:
            os.environ[_ENV_KEY] = _env_prev
    # 场景 2：显式 MDCG_JUDGMENT=0 关闭
    prev2 = os.environ.get(_ENV_KEY)
    os.environ[_ENV_KEY] = "0"
    try:
        _assert_closed_behavior("关闭/=0")
    finally:
        if prev2 is None:
            os.environ.pop(_ENV_KEY, None)
        else:
            os.environ[_ENV_KEY] = prev2


def main():
    print("===== md_cg.test_t31a_whykept（why_kept 判断理由字段：接线 + 测试） =====")
    test_a_unit()
    test_b_wiring()
    test_c_closed()
    print("\n===== t31a 判定：%d 通过，%d 失败 =====" % (passed, failed))
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()