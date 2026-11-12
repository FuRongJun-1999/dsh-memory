# -*- coding: utf-8 -*-
"""test_t27a_per_message —— 日常对话**逐条**判断存亡的驱动面（E-T27a / t27a-20261011）。

被测真源 `md_cg/t27a_per_message.py` 的 `per_message_verdicts`；判据真源
`md_cg/judgment_rules.py`（J1–J11，E-T18a t1）。四段：

  [A] 逐条形状：一段 ≥6 条的真实多轮对话逐条判，断言条数对齐、五键齐全、
      state ∈ 三态、index 连续 0..n-1。
  [B] 反一刀切证据：同一段对话内 judge 至少命中 2 条不同判据、state 至少出现
      2 种取值——逐条判定 ≠ 整段一刀切。
  [C] 与整段批量判定可区分：整段拼成一个事件只出 1 条判定，而逐条出 count 条
      ——证明不是把整段当一个事件。
  [D] 诚实关断：`MDCG_JUDGMENT=0` 时驱动如实报 disabled（返回 []，不伪判成
      keep/drop）；显式开启后逐条判定照常。

运行：python -X utf8 -m md_cg.test_t27a_per_message
"""
import os
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

from md_cg import judgment_rules as jr                      # noqa: E402

# 2026-11-12 合并：本件是 2026-10-29 的**归档测试**，被测模块
# `md_cg/t27a_per_message.py` 在本树与远端**两侧都不存在**（已随批次移除）⇒
# 无被测面可判。按本仓既有的「依赖缺失 ⇒ SKIP」口径如实报，而不是让
# ModuleNotFoundError 冒充「测试失败」（那会把真回归信号淹掉）。
try:
    from md_cg.t27a_per_message import VERDICT_KEYS         # noqa: E402
except ImportError:
    print("SKIP  缺依赖 md_cg.t27a_per_message（该模块已从本树移除，归档件无被测面）")
    raise SystemExit(0)

from md_cg.t27a_per_message import map_role                 # noqa: E402
from md_cg.t27a_per_message import per_message_verdicts     # noqa: E402

passed = failed = 0
_ENV_KEY = jr.ENV_FLAG
_ENV_PREV = os.environ.pop(_ENV_KEY, None)                  # 本测试全程自管开关

#: 从 `judgment_rules` **自己声明的**常量里取开启值，不硬编码 0/1。
_ON_VALUES = tuple(getattr(jr, "ENABLE_VALUES", ()) or ())
_ON_TOKEN = _ON_VALUES[0] if _ON_VALUES else "1"


def _force_on():
    """按 `judgment_rules` 的现行契约把开关**显式开启**；开不了返回 False。"""
    for token in ([_ON_TOKEN] + list(_ON_VALUES) + ["1", "true", "on"]):
        os.environ[_ENV_KEY] = token
        if jr.is_enabled():
            return True
    return False


def _force_off():
    """把开关**关掉**（现行契约：不设 = 关，或取一个非开启值）；关不掉返回 False。"""
    os.environ.pop(_ENV_KEY, None)
    if jr.is_enabled() is False:
        return True
    os.environ[_ENV_KEY] = "0"
    return jr.is_enabled() is False


def _restore_env():
    if _ENV_PREV is None:
        os.environ.pop(_ENV_KEY, None)
    else:
        os.environ[_ENV_KEY] = _ENV_PREV


#: [A] 一段真实多轮对话（10 条，user/assistant 交替）：含长期偏好、技术结论、
#: 一次性交代、闲谈、可复用脚本路径、临时设计、工具日志。每条的落点见注释，
#: 这是 [B] 的证据来源。
CONVERSATION = [
    {"role": "user",
     "text": "我主力语言是 Python，讨厌过度抽象，别给我绕弯子的方案。"},
    #   ↑ J1 留：用户的性格 / 偏好 / 命令方式
    {"role": "assistant",
     "text": "已定位到缓存失效的根因是 md_cg/refindex.py:88 的索引重载漏了分支键。"},
    #   ↑ J4 留：技术结论 + 文件:行号指纹
    {"role": "user",
     "text": "今天把 report.pdf 生成一下"},
    #   ↑ J7 丢：一次性的需求与交代本身
    {"role": "user",
     "text": "这个配色我们是说好按品牌手册来的吧？"},
    #   ↑ 兜底 J6 留：有内容但无判据命中（判据表是过滤器不是门禁）
    {"role": "assistant",
     "text": "这个临时方案先这样凑合，回头再说。"},
    #   ↑ J10 丢：会随时间自动失效的（临时设计 / 当时状态）
    {"role": "user",
     "text": "嗨，今天天气还行。"},
    #   ↑ 兜底 J6 留：纯闲谈不丢——闲谈里也可能长出长期事实
    {"role": "user",
     "text": "诊断脚本在 D:\\tools\\probe.ps1，跑法见 README。"},
    #   ↑ J5 留：可复用的东西（脚本 / 路径 / 跑法）
    {"role": "user",
     "text": "把 mdcg.py 第 302 行改成 X"},
    #   ↑ J4 留：工具指令式消息，正文含 文件名 指纹（能指名回溯）
    {"role": "tool-output",
     "text": "python run_tests.py\nPASS 3/3\n[exit code: 0]"},
    #   ↑ J9 丢：结构性噪声——role=tool-output 是比正文更硬的信号
    {"role": "assistant",
     "text": "这份光谱对照表以后可能有用，先留着。"},
    #   ↑ J6 留：命中 J11 寿命词但**无**引用信号 → 回落普通留（不凭空定寿）
]


def check(name, cond, detail=""):
    global passed, failed
    if cond:
        passed += 1
        print("  [PASS] " + name)
    else:
        failed += 1
        print("  [FAIL] " + name + "  " + str(detail)[:300])


def _texts(messages):
    return [m["text"] for m in messages]


# ---------------------------------------------------------------------------
# [A] 逐条形状：条数对齐 + 五键齐全 + 三态取值 + index 连续
# ---------------------------------------------------------------------------

def test_a_per_message_shape():
    print("[A] 逐条形状：条数对齐 / 五键齐全 / state ∈ 三态 / index 连续")

    msgs = list(CONVERSATION)
    check("样本自足：一段真实多轮对话 ≥6 条且 user/assistant 交替",
          len(msgs) >= 6
          and len({m["role"] for m in msgs}) >= 2
          and sum(1 for m in msgs if m["role"] == "assistant") >= 3,
          "len=%d" % len(msgs))

    r = per_message_verdicts(msgs)
    check("返回 list[dict]（不是包着 enabled/count 的 dict 外壳）",
          isinstance(r, list) and all(isinstance(v, dict) for v in r),
          type(r).__name__)

    check("条数相等：len(verdicts) == len(messages)（一条消息一条判定）",
          len(r) == len(msgs), "len=%s/%s" % (len(r), len(msgs)))

    keys_ok = all(set(v.keys()) == set(VERDICT_KEYS) for v in r)
    missing = [v.get("index") for v in r if set(v.keys()) != set(VERDICT_KEYS)]
    check("每条 verdict **恰好五个**键（index/role/text/state/judge/evidence）",
          keys_ok, "键不符的条目 index=%s" % missing)

    states = [v["state"] for v in r]
    check("state 恒 ∈ {keep, drop, keep_life}（取值来自规则表，不自行发明）",
          all(s in jr.STATES for s in states)
          and any(s in states for s in (jr.KEEP, jr.DROP)),
          sorted(set(states)))

    check("index 连续 0..n-1 且与输入顺序对齐",
          [v["index"] for v in r] == list(range(len(msgs))),
          [v["index"] for v in r])

    check("role/text 逐条回填原文（未映射时 role 原样）",
          [v["role"] for v in r] == [m["role"] for m in msgs]
          and [v["text"] for v in r] == _texts(msgs))

    check("evidence 恒为 list（无命中时为 []，不返回 None）",
          all(isinstance(v["evidence"], list) for v in r))

    check("judge 为判据 id 或 None，命中的必在 J1–J11 内",
          all(v["judge"] is None or v["judge"] in jr.RULES for v in r))

    # 逐条判定与真源**同输入同输出**：驱动只做「逐条调 + 收集 + 归一」。
    direct = [jr.judge_event({"role": m["role"], "text": m["text"]})
              for m in msgs]
    check("逐条结论与直接调 judge_event 逐条一致（驱动零复制判据）",
          [v["state"] for v in r] == [d["state"] for d in direct]
          and [v["judge"] for v in r] == [d["judge"] for d in direct],
          [(v["state"], d["state"]) for v, d in zip(r, direct)])

    # 字段名推断：不给 role/text 键、只给常见别名时也能取到。
    r_alias = per_message_verdicts(
        [{"speaker": "user", "content": "我主力语言是 Python"},
         {"speaker": "user", "content": "今天把 report.pdf 生成一下"}])
    check("缺省按常见键名推断（speaker→role、content→text）",
          len(r_alias) == 2
          and r_alias[0]["role"] == "user"
          and r_alias[0]["text"] == "我主力语言是 Python"
          and r_alias[0]["state"] == jr.KEEP, str(r_alias[0]))

    # role_map：可调用与 dict 两种形态都要先映射再送判。
    r2 = per_message_verdicts(msgs, role_map={"assistant": "user"})
    check("role_map(dict) 先映射再送判：映射命中改 role、缺键回落原 role",
          r2[0]["role"] == "user" and r2[1]["role"] == "user"
          and r2[2]["role"] == "user" and len(r2) == len(r))

    r3 = per_message_verdicts(
        [{"role": "bot", "text": "python run_tests.py\nPASS 3/3\n[exit code: 0]"}],
        role_map=lambda role: "tool-output" if role == "bot" else role)
    check("role_map(可调用) 生效：映射成 tool-output → 结构性判 J9 丢",
          r3[0]["role"] == "tool-output" and r3[0]["state"] == jr.DROP
          and r3[0]["judge"] == "J9", str(r3[0]))

    # role_map 兼作「字段名映射」：告诉本函数输入的字段叫什么。
    r4 = per_message_verdicts(
        [{"who": "user", "body": "今天把 report.pdf 生成一下"}],
        role_map={"who": "role", "body": "text"})
    check("role_map 字段名映射形态：who/body → role/text",
          len(r4) == 1 and r4[0]["role"] == "user"
          and r4[0]["text"] == "今天把 report.pdf 生成一下"
          and r4[0]["state"] == jr.DROP, str(r4))

    check("map_role 对坏形状不抛异常（None/dict 缺键一律回落原 role）",
          map_role("user") == "user"
          and map_role("x", {"user": "assistant"}) == "x"
          and map_role(None, None) is None)


# ---------------------------------------------------------------------------
# [B] 反一刀切证据：同一段对话命中 ≥2 个判据、≥2 种 state
# ---------------------------------------------------------------------------

def test_b_not_one_size_fits_all():
    print("[B] 反一刀切：同段对话命中 ≥2 判据、≥2 种 state（逐条 ≠ 整段）")

    r = per_message_verdicts(CONVERSATION)
    judges = sorted({v["judge"] for v in r if v["judge"]})
    states = sorted({v["state"] for v in r})

    check("judge 去重后 ≥2 个不同判据（同段对话不是一条判据通吃）",
          len(judges) >= 2, judges)
    check("state 去重后 ≥2 种取值（同段对话不是一刀切同一个结论）",
          len(states) >= 2, states)

    check("同段对话里 留(keep) 与 丢(drop) 逐条并存",
          jr.KEEP in states and jr.DROP in states,
          [(v["index"], v["state"], v["judge"]) for v in r])

    drops = [v["index"] for v in r if v["state"] == jr.DROP]
    keeps = [v["index"] for v in r if v["state"] == jr.KEEP]
    check("丢的条目数 < 总条数（没有一刀切全丢）",
          0 < len(drops) < len(r), "drops=%s keeps=%s" % (drops, keeps))
    check("留的条目数 < 总条数（也没有一刀切全留）",
          0 < len(keeps) < len(r), "keeps=%s" % keeps)

    # 每条落点断言（真源逐条判的结果，写死以锁住语义）。
    want = {0: (jr.KEEP, "J1"), 1: (jr.KEEP, "J4"), 2: (jr.DROP, "J7"),
            4: (jr.DROP, "J10"), 5: (jr.KEEP, "J6"), 6: (jr.KEEP, "J5"),
            7: (jr.KEEP, "J4"), 8: (jr.DROP, "J9"), 9: (jr.KEEP, "J6")}
    bad = [(i, r[i]["state"], r[i]["judge"], exp)
           for i, exp in want.items()
           if (r[i]["state"], r[i]["judge"]) != exp]
    check("逐条落点与真源一致（J1/J4/J7/J10/J6/J5/J4/J9/J6 各归其位）",
          not bad, bad)

    check("同一输入两次调用结论逐条相同（判定确定性，无随机）",
          [v["state"] for v in per_message_verdicts(CONVERSATION)]
          == [v["state"] for v in r])


# ---------------------------------------------------------------------------
# [C] 与整段批量判定可区分：整段只出 1 条，逐条出 count 条
# ---------------------------------------------------------------------------

def test_c_vs_whole_segment():
    print("[C] 与整段批量判定可区分：整段拼成一个事件只出 1 条判定")

    joined = "\n".join(_texts(CONVERSATION))
    whole = jr.judge_event({"role": "user", "text": joined})
    per = per_message_verdicts(CONVERSATION)

    check("整段判定只有 1 条结论（一次调用一段输入）",
          isinstance(whole, dict) and whole.get("state") in jr.STATES,
          jr.explain(whole))
    check("逐条判定有 count == len(messages) 条（≥6）",
          len(per) == len(CONVERSATION) and len(per) >= 6, len(per))
    check("逐条条数 ≠ 整段条数（驱动是逐条，不是把整段当一个事件）",
          len(per) > 1)

    # 整段拼接把判据表内部的「取最高优先级（丢在前）」放大成整段一刀切：
    # 段内任何一条命中 DROP，整段就判 DROP——正是逐条判定要避免的。
    check("整段拼接会把段内任意一条 DROP 放大成整段 DROP（一刀切证据）",
          whole["state"] == jr.DROP
          and any(v["state"] == jr.DROP for v in per)
          and any(v["state"] == jr.KEEP for v in per),
          "whole=%s per=%s" % (whole["state"], [v["state"] for v in per]))

    check("同一段对话：整段判丢，但逐条仍有 ≥1 条判留（可区分）",
          whole["state"] == jr.DROP
          and sum(1 for v in per if v["state"] == jr.KEEP) >= 1,
          [v["state"] for v in per])


# ---------------------------------------------------------------------------
# [D] 诚实关断：MDCG_JUDGMENT=0 → disabled（[]）；开启后恢复
# ---------------------------------------------------------------------------

def test_d_honest_disable():
    print("[D] 诚实关断：MDCG_JUDGMENT=0 → enabled=False / [] （不伪判）")

    check("开关可以按现行契约关闭（关不掉则该段无意义）", _force_off())
    try:
        os.environ[_ENV_KEY] = "0"
        check("MDCG_JUDGMENT=0 时 is_enabled() 为 False",
              jr.is_enabled() is False, jr.is_enabled())
        off = per_message_verdicts(CONVERSATION)
        check("关断：返回 []（如实报 disabled，不伪判成 keep/drop）",
              off == [] and isinstance(off, list), repr(off))
        check("关断：没有任何一条带 state 的伪判定（不冒充判过）",
              all(not (isinstance(v, dict) and "state" in v) for v in off))
        check("关断：坏形状 messages 同样不伪判（仍返回 []）",
              per_message_verdicts(None) == []
              and per_message_verdicts("not-a-list") == []
              and per_message_verdicts([], role_map={"a": "b"}) == [])
    finally:
        _restore_env()

    check("开关可以显式开启（契约翻转后仍是可逆的，不是永久降级）",
          _force_on())
    try:
        check("开启态确认（is_enabled() 为 True）", jr.is_enabled() is True)
        back = per_message_verdicts(CONVERSATION)
        check("开启后逐条判定照常（条数回到 len(messages)、逐条对齐）",
              len(back) == len(CONVERSATION)
              and [v["index"] for v in back] == list(range(len(CONVERSATION))),
              "%s" % len(back))
        check("开启后各条 state 均 ∈ 三态（恢复不是伪造结果）",
              all(v["state"] in jr.STATES for v in back))
    finally:
        _restore_env()


def main():
    print("===== md_cg.test_t27a_per_message（E-T27a 日常对话逐条判存亡） =====")
    if not _force_on():
        print("  [FAIL] 无法按现行契约开启判定面，后续各段无意义")
        globals()["failed"] = failed + 1
    try:
        test_a_per_message_shape()
        test_b_not_one_size_fits_all()
        test_c_vs_whole_segment()
        test_d_honest_disable()
    finally:
        _restore_env()
    print("\n===== t27a 逐条判定：%d 通过，%d 失败 =====" % (passed, failed))
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
