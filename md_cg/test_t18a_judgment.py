# -*- coding: utf-8 -*-
"""test_t18a_judgment —— 判据规则表 J1–J11 单元判定 + mdcg 写入侧接线（E-T18a t1）。

三段（口径真源 md_cg/judgment_rules.py，接线真源 md_cg/mdcg.py 的
MdCG.add / MdCG.remember_event 前置短路）：

  [A] 单元判定：每条判据（J1–J11）至少一个**真实对话**样本，外加结构信号
      （role=tool-output 判 J9、空文本判 J9、无命中兜底 J6）与三态 API
      （should_write / lifetime_mark_of / explain / is_enabled 默认关）。
  [B] 接线（显式 MDCG_JUDGMENT=1 开启）：remember_event 的三态
      （DROP 拒写不落盘 / KEEP 原样落盘+meta 打 judgment_state / KEEP_LIFE 打
      judgment_lifetime + judgment_ref_count）与 add 的三态（DROP 返回 None
      节点缺席 / KEEP 落节点+fm.judgment_state / KEEP_LIFE 落 fm 寿命标记）。
  [C] 回归：默认**关闭**（MDCG_JUDGMENT 未设）→ 写入行为与接线前**逐字节
      一致**——role=command 事件照常进窗且返回体不夹带 verdict、J7/J10 类
      正文节点照常可写、fm 不带判定字段；（E-T31a 关闭回归同锁此契约）；
      显式开启（MDCG_JUDGMENT=1）时 role=command 事件按**正文**判（裸命令
      无命中 → 照常进窗且带 verdict，test_p7_goals_recent.py:106 同款用例）
      且 add 拦 DROP 类正文。

运行：python -X utf8 -m md_cg.test_t18a_judgment
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
    return MdCGOS(tempfile.mkdtemp(prefix="mdcg_t18a_"))


# ---------------------------------------------------------------------------
# [A] 单元判定（真实对话样本，逐判据）
# ---------------------------------------------------------------------------

def test_a_unit():
    print("[A] 单元判定 judge_event：留 / 丢 / 留但定寿")

    # ---- 留（J1–J6）----
    v = jr.judge_event({"role": "user",
                        "text": "我讨厌你先讲道理，先接住我的情绪再说"})
    check("J1 留：用户语气习惯（真实对话）",
          v["state"] == jr.KEEP and v["judge"] == "J1" and v["lifetime"] is None,
          jr.explain(v))

    v = jr.judge_event({"role": "user",
                        "text": "你的性格要沉淀下来：先接住情绪，再讲道理"})
    check("J2 留：助手正在长成的性格",
          v["state"] == jr.KEEP and v["judge"] == "J2", jr.explain(v))

    v = jr.judge_event({"role": "user",
                        "text": "我们俩以后就按这个分工来，不再互相抢活"})
    check("J3 留：两人的相处方式", v["state"] == jr.KEEP and v["judge"] == "J3",
          jr.explain(v))

    v = jr.judge_event({"role": "assistant",
                        "text": "报错原文是 KeyError，根因是 md_cg/run_tests.py:24 的管道"})
    check("J4 留：技术结论+踩坑（含 文件:行号 指纹）",
          v["state"] == jr.KEEP and v["judge"] == "J4", jr.explain(v))

    v = jr.judge_event({"role": "user",
                        "text": "诊断脚本在 D:\\tools\\probe.ps1，跑法见 README。"})
    check("J5 留：可复用的脚本/跑法", v["state"] == jr.KEEP and v["judge"] == "J5",
          jr.explain(v))

    v = jr.judge_event({"role": "user",
                        "text": "这台机器上 Python 默认必须走 UTF-8，长期如此"})
    check("J6 留：能长期成立的环境事实",
          v["state"] == jr.KEEP and v["judge"] == "J6", jr.explain(v))

    # ---- 丢（J7–J10）----
    v = jr.judge_event({"role": "user", "text": "今天把 report.pdf 生成一下"})
    check("J7 丢：一次性的需求与交代本身",
          v["state"] == jr.DROP and v["judge"] == "J7", jr.explain(v))

    v = jr.judge_event({"role": "user",
                        "text": "方案一和方案二各有取舍，要不要再商量一下？"})
    check("J8 丢：讨论过程（选项/取舍）",
          v["state"] == jr.DROP and v["judge"] == "J8", jr.explain(v))

    v = jr.judge_event({"role": "tool-output",
                        "text": "python check.py\nPASS 3/3\n[exit code: 0]"})
    check("J9 丢：role=tool-output 结构性判噪声（role 是比正文更硬的信号）",
          v["state"] == jr.DROP and v["judge"] == "J9"
          and v["evidence"] == ["role:tool-output"], jr.explain(v))

    v = jr.judge_event({"role": "assistant",
                        "text": 'File "run_tests.py", line 24: module-level import error'})
    check("J9 丢：正文级工具日志噪声（栈帧 File \"…\", line N）",
          v["state"] == jr.DROP and v["judge"] == "J9", jr.explain(v))

    v = jr.judge_event({"role": "user",
                        "text": "这个方案是临时的，先这样凑合，回头再说"})
    check("J10 丢：临时设计（且 J10 优先于 J11 同现词）",
          v["state"] == jr.DROP and v["judge"] == "J10", jr.explain(v))

    # ---- 留但定寿（J11）----
    v = jr.judge_event({"role": "user", "text": "这份光谱对照表以后可能有用，先留着。",
                        "ref_signals": {"ref_count": 0}})
    check("J11 留但定寿：ref_count=0 → 沉底起点",
          v["state"] == jr.KEEP_LIFE and v["judge"] == "J11"
          and v["lifetime"]["policy"] == "ref_count_zero"
          and v["lifetime"]["ref_count"] == 0, jr.explain(v))

    v = jr.judge_event({"role": "user", "text": "这份光谱对照表以后可能有用，先留着。",
                        "ref_signals": {"ref_count": 3, "cited": True}})
    check("J11 留但定寿：ref_count>0 → 被反复提起，留住并继续计数",
          v["state"] == jr.KEEP_LIFE and v["judge"] == "J11"
          and v["lifetime"]["policy"] == "ref_count_positive"
          and v["lifetime"]["ref_count"] == 3
          and jr.lifetime_mark_of(v) is v["lifetime"], jr.explain(v))

    v = jr.judge_event({"role": "user", "text": "这份光谱对照表以后可能有用，先留着。"})
    check("J11 无引用信号 → 回落普通留（寿命是事后属性，不凭空定寿）",
          v["state"] == jr.KEEP and v["lifetime"] is None
          and v.get("state_of", {}).get("J11") == jr.KEEP, jr.explain(v))

    # ---- 结构信号与兜底 ----
    v = jr.judge_event({"role": "user", "text": ""})
    check("空文本 → J9 丢（should_write 拿到它必拒写）",
          v["state"] == jr.DROP and not jr.should_write(v), jr.explain(v))

    v = jr.judge_event({"role": "user", "text": "嗯，这个数值是 42。"})
    check("无命中兜底判 J6 留（过滤器不是门禁；evidence 恒非空）",
          v["state"] == jr.KEEP and v["judge"] == "J6"
          and v["evidence"] == ["fallback:no-rule-hit"], jr.explain(v))

    check("should_write 对坏形状放行（fail-open：判定面故障不堵写入）",
          jr.should_write(None) is True and jr.should_write("x") is True)
    check("should_write 只拒 DROP",
          jr.should_write({"state": jr.DROP}) is False
          and jr.should_write({"state": jr.KEEP}) is True
          and jr.should_write({"state": jr.KEEP_LIFE}) is True)
    check("判据次序可回溯：state_of 映射落点 + explain 可读串",
          jr.judge_event({"role": "user", "text": "帮我跑一下"})
          .get("state_of", {}).get("J7") == jr.DROP
          and isinstance(jr.explain(None), str))
    check("is_enabled 默认关闭（MDCG_JUDGMENT 未设=与接线前逐字节一致）",
          jr.is_enabled() is False)
    os.environ[_ENV_KEY] = "1"
    try:
        check("is_enabled 显式开启（MDCG_JUDGMENT=1）",
              jr.is_enabled() is True)
    finally:
        os.environ.pop(_ENV_KEY, None)


# ---------------------------------------------------------------------------
# [B] 接线（MDCG_JUDGMENT=1）：remember_event / add 的三态写入
# ---------------------------------------------------------------------------

def test_b_wiring():
    print("[B] 接线：写入路径前置短路（显式 MDCG_JUDGMENT=1 开启）")
    _env_prev = os.environ.get(_ENV_KEY)
    os.environ[_ENV_KEY] = "1"
    kg = _mk_cg()
    try:
        # ---- remember_event 三态 ----
        d = kg.remember_event("user", "今天把 report.pdf 生成一下")
        check("接线 DROP：不落盘（event=None、窗口零变化）",
              d["event"] is None and d["verdict"]["state"] == jr.DROP
              and _recent_texts(kg) == [], jr.explain(d["verdict"]))

        k = kg.remember_event("assistant", "已定位到 token 过期逻辑")
        check("接线 KEEP：照常落盘 + meta 打 judgment_state（正文元数据不贴胶带）",
              k["event"] is not None
              and k["event"]["meta"].get(jr.STATE_FIELD) == jr.KEEP
              and _recent_texts(kg) == ["已定位到 token 过期逻辑"]
              and "dropped" in k, str(k))

        l1 = kg.remember_event("user", "这份光谱对照表以后可能有用，先留着。",
                               meta={"ref_count": 3})
        check("接线 J11 KEEP_LIFE：meta 打寿命标记（ref_count 归一自 meta）",
              l1["event"] is not None
              and l1["event"]["meta"].get(jr.STATE_FIELD) == jr.KEEP_LIFE
              and l1["event"]["meta"].get(jr.LIFETIME_FIELD,
                                          {}).get("policy") == "ref_count_positive"
              and l1["event"]["meta"].get(jr.REF_COUNT_FIELD) == 3, str(l1))

        l0 = kg.remember_event("user", "这份光谱对照表以后可能有用，先留着。",
                               meta={"ref_signals": {"ref_count": 0}})
        check("接线 J11 KEEP_LIFE：meta.ref_signals 显式优先、ref_count=0 拍沉底起点",
              l0["event"] is not None
              and l0["event"]["meta"].get(jr.LIFETIME_FIELD,
                                          {}).get("policy") == "ref_count_zero",
              str(l0))

        k2 = kg.remember_event("user", "我主力语言是 Python，讨厌过度抽象")
        check("接线 J11 词命中但无引用信号 → KEEP 落盘（不定寿）",
              k2["event"] is not None
              and k2["event"]["meta"].get(jr.STATE_FIELD) == jr.KEEP
              and jr.LIFETIME_FIELD not in k2["event"]["meta"], str(k2))

        # ---- add 三态 ----
        d2 = kg.add("t18a_drop", "今天把 report.pdf 生成一下")
        check("接线 add DROP：返回 None（defer 同形状）、节点缺席",
              d2 is None and _fm_of(kg, "t18a_drop") is None, repr(d2))

        k3 = kg.add("t18a_keep", "我讨厌你先讲道理，先接住我的情绪再说",
                    layer="self")
        check("接线 add KEEP：正常返回 id + fm.judgment_state=keep",
              k3 == "t18a_keep"
              and _fm_of(kg, k3).get(jr.STATE_FIELD) == jr.KEEP, repr(k3))

        l2 = kg.add("t18a_life", "这份光谱对照表以后可能有用，先留着。",
                    ref_signals={"ref_count": 0})
        fm = _fm_of(kg, l2)
        check("接线 add J11 KEEP_LIFE：fm 打寿命标记且接线条不进其余字段",
              l2 == "t18a_life"
              and fm.get(jr.STATE_FIELD) == jr.KEEP_LIFE
              and fm.get(jr.LIFETIME_FIELD, {}).get("policy") == "ref_count_zero"
              and fm.get(jr.REF_COUNT_FIELD) == 0, str(fm))

        k4 = kg.add("t18a_lifetimeless",
                    "这份光谱对照表以后可能有用，先留着。")
        fm4 = _fm_of(kg, k4)
        check("接线 add J11 词命中但无引用信号 → KEEP（fm 不打寿命令）",
              k4 is not None and fm4.get(jr.STATE_FIELD) == jr.KEEP
              and jr.LIFETIME_FIELD not in fm4, str(fm4))
    finally:
        shutil.rmtree(kg.root, ignore_errors=True)
        if _env_prev is None:
            os.environ.pop(_ENV_KEY, None)
        else:
            os.environ[_ENV_KEY] = _env_prev


# ---------------------------------------------------------------------------
# [C] 回归：默认关（未设=与接线前逐字节一致，E-T31a 同锁此契约）vs 显式开
#     （MDCG_JUDGMENT=1：按正文判、command 事件照常进窗且带 verdict）。
# ---------------------------------------------------------------------------

def test_c_regression():
    print("[C] 回归：默认关闭（逐字节一致） + 显式开启（按正文判）")

    # ---- 默认关闭（未设）：写入行为与接线前逐字节一致 ----
    cg = _mk_cg()
    try:
        r = cg.remember_event("command", "pytest -k login")
        check("默认关 role=command 事件照常进窗（无 verdict 键夹带）",
              r["event"] is not None and r["event"]["text"] == "pytest -k login"
              and "verdict" not in r
              and set(r["event"].keys()) == {"t", "role", "text", "tags", "meta"},
              str(r))
        check("默认关 recent 读取含该 command 事件",
              _recent_texts(cg) == ["pytest -k login"], str(_recent_texts(cg)))
        r2 = cg.remember_event("user", "开始重构登录模块")
        check("默认关正常事件返回体形状不变（仅 event/dropped 两键）",
              set(r2.keys()) == {"event", "dropped"}, str(r2))

        nid = cg.add("t18a_off", "今天把 report.pdf 生成一下")
        check("默认关 add 不拦（J7 类正文照常成节点；无判定字段）",
              nid == "t18a_off"
              and jr.STATE_FIELD not in _fm_of(cg, nid), repr(nid))
        nid2 = cg.add("t18a_off2", "缓存策略是临时的")
        check("默认关 add J10 类正文照常写入",
              nid2 == "t18a_off2"
              and jr.STATE_FIELD not in _fm_of(cg, nid2), repr(nid2))
    finally:
        shutil.rmtree(cg.root, ignore_errors=True)

    # ---- 显式开启：MDCG_JUDGMENT=1 → 按正文判，command 事件仍照常进窗 ----
    _env_prev = os.environ.get(_ENV_KEY)
    os.environ[_ENV_KEY] = "1"
    cgo = _mk_cg()
    try:
        r = cgo.remember_event("command", "pytest -k login")
        check("开启 role=command 裸命令按正文判 → KEEP 进窗（p7:106 同款用例）",
              r["event"] is not None and r["event"]["text"] == "pytest -k login"
              and r["verdict"]["state"] == jr.KEEP
              and r["event"]["meta"].get(jr.STATE_FIELD) == jr.KEEP, str(r))
        check("开启 recent 读取含该 command 事件",
              _recent_texts(cgo) == ["pytest -k login"], str(_recent_texts(cgo)))

        d = cgo.add("t18a_drop_default", "今天把 report.pdf 生成一下")
        check("开启 add 拦 DROP 类正文（J7 一次性需求拒写）",
              d is None and _fm_of(cgo, "t18a_drop_default") is None, repr(d))
        k = cgo.add("t18a_keep_default", "缓存策略是临时的")
        check("开启 add 正常正文照常写入且带判定字段",
              k == "t18a_keep_default"
              and _fm_of(cgo, k).get(jr.STATE_FIELD) == jr.KEEP, repr(k))
    finally:
        shutil.rmtree(cgo.root, ignore_errors=True)
        if _env_prev is None:
            os.environ.pop(_ENV_KEY, None)
        else:
            os.environ[_ENV_KEY] = _env_prev


def main():
    print("===== md_cg.test_t18a_judgment（E-T18a t1 判据规则表 + 接线） =====")
    test_a_unit()
    test_b_wiring()
    test_c_regression()
    print("\n===== t18a 判定：%d 通过，%d 失败 =====" % (passed, failed))
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
