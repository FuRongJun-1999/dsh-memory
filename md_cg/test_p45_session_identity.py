# -*- coding: utf-8 -*-
"""md_cg · 第 45 篇：嵌套身份归因与会话切片（(harness, session) 不参与授权）

设计口径（设计者，2026-09-11）：
  · 唯一设计者 = 外部用户；被授权端 codebuddy / dsh / zcode 是本机三个进程，
    权限域一致（同一最高权限），区别只在单元分工（工程内容）；
  · 身份靠 (harness, session) 归因，而不是靠多令牌/多实例提权；
  · 会话产物落薄卡（单例）的 session 维度切片 + 富索引指针，卡本身仍是单例。

覆盖：
  A Principal 归因字段（harness/unit/session；与授权正交）
  B _normalize_session：DSH 形态 + 目录存在 → 采用；不存在 → anonymous；
    非 DSH 形态 → 采用；根可配置（MDCG_DSH_SESSIONS_ROOT）
  C _apply_attribution：MDCG_SESSION / DSH_SESSION_ID / MDCG_HARNESS / MDCG_UNIT
  D self_state 会话切片：refresh(session=) 登记维度 / summary(session=) 回报 /
    单例卡语义不变 / 不覆盖显式维度
  E 会话要点：session_note 缺省用 Principal.session；recall 带回会话自我切片
  F 审计归因：_audit.jsonl 条目带 harness/unit
  G MCP 入口：_self_state_call 缺省会话透传 + index 快捷反查
  R65 issue #65：session_recall ③ 近期事件段的**会话隔离**（外部报告 by ducc239，
      对 v0.7.5 实测；本 workflow 修前复现）——假会话 id 空窗口 / A 只回 A /
      B 只回 B / "*" 与 None 退回全局 / 缺 meta.session 者被丢弃 / compact 回归 /
      MCP 入口端到端 / 文档口径在位；外加**定点变异自证**模式。

运行：python -m md_cg.test_p45_session_identity                 # 正常跑
      python -m md_cg.test_p45_session_identity --self-proof     # 变异自证
退出码：0 全绿 ｜ 1 断言失败 ｜ 2 ANCHOR-MISS（锚点漂移，fail-closed）

变异自证的基线源 = **运行中的实现源码**（`inspect.getsource` 就地变异、就地复原），
**不读 git**——把基线绑到某个提交，下一次改动即失效（本仓已有两次教训）。
"""
from __future__ import annotations

import contextlib
import inspect
import io
import json
import os
import sys
import tempfile
import textwrap

from .mdcos import MdCGOS, MdCGSecure
from . import mdcos as _mdcos
from .security import Principal
from . import self_state as ss
from . import mcp_server as ms

PASS = FAIL = 0
FAILS = []


def check(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  [PASS] {name}" + (f"  · {detail}" if detail else ""))
    else:
        FAIL += 1
        FAILS.append(name)
        print(f"  [FAIL] {name}  · {detail}")


def _setenv(**kw):
    old = {k: os.environ.get(k) for k in kw}
    for k, v in kw.items():
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v
    return old


def _restore(old):
    for k, v in old.items():
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v


def main():
    global PASS, FAIL
    if "--self-proof" in sys.argv:
        return _r65_self_proof()
    _rc = _r65_anchor_preflight()           # 锚点漂移 → ANCHOR-MISS + 退出码 2
    if _rc:
        return _rc
    PASS = FAIL = 0                         # 计数器复位：变异自证模式内会复用本函数重跑
    del FAILS[:]
    # ---------- A. Principal 归因字段 ----------
    print("\n[A] Principal 归因字段（与授权正交）")
    p0 = Principal(actor="a0")
    check("A1 默认会话是进程随机 id", (p0.session or "").startswith("sess_"),
          p0.session)
    check("A2 harness/unit 默认为 None", p0.harness is None and p0.unit is None)
    p1 = Principal(actor="a1", session="session-x", harness="dsh", unit="record",
                   ops_allow=("read",))
    d = p1.as_dict()
    check("A3 as_dict 暴露 harness/unit/session",
          d.get("harness") == "dsh" and d.get("unit") == "record"
          and d.get("session") == "session-x")
    check("A4 归因不影响授权（ops 仍按记录）",
          p1.allows_op("read") and not p1.allows_op("write"))

    # ---------- B. _normalize_session ----------
    print("\n[B] 会话 id 归一与轻校验")
    sdir = tempfile.mkdtemp(prefix="mdcg_p45_sess_")
    # 人造 id：不得使用任何真实 DSH 会话 id，否则断言会依赖运行机器的磁盘现状
    # （若该 id 恰好在 ~/.dsh/sessions 下存在，B5 的 fail-soft 断言会被偶然满足）。
    sid = "session-deadbeef-6abc-4a71-a1f2-b658712be0fb"
    os.makedirs(os.path.join(sdir, "--ws--", sid))
    # 形态自检：id 若不满足 DSH 五段形态，B1/B5 会退化成「非 DSH 形态原样采用」
    # 而仍然通过——断言落空且看不出来，故先钉死前提。
    check("B0 测试用 id 满足 DSH 形态（防断言落空）", ms._is_dsh_session(sid))
    old = _setenv(MDCG_DSH_SESSIONS_ROOT=sdir)
    try:
        check("B1 DSH 形态 + 目录存在 → 采用",
              ms._normalize_session(sid) == sid)
        check("B2 DSH 形态 + 目录不存在 → anonymous",
              ms._normalize_session(
                  "session-00000000-0000-0000-0000-000000000000") == "anonymous")
        check("B3 非 DSH 形态 → 原样采用",
              ms._normalize_session("dsl-web-main") == "dsl-web-main")
        check("B4 空值 → anonymous", ms._normalize_session("") == "anonymous")
    finally:
        _restore(old)
    # 必须显式指向「不存在的根」：若沿用默认根，在装了 DSH 的机器上根目录存在，
    # 会落到「根可读但无该会话 → anonymous」分支，测不到 fail-soft（易假 PASS）。
    old = _setenv(MDCG_DSH_SESSIONS_ROOT=os.path.join(sdir, "_no_such_root_"))
    try:
        check("B5 根不存在/不可读 → fail-soft（保留标记，不丢会话）",
              ms._normalize_session(sid) == sid, "根不存在时不因环境差异丢弃会话标记")
    finally:
        _restore(old)

    # ---------- C. _apply_attribution ----------
    print("\n[C] 归因注入（MDCG_SESSION / DSH_SESSION_ID / HARNESS / UNIT）")
    old = _setenv(MDCG_SESSION="dsl-web-main", DSH_SESSION_ID=None,
                  MDCG_HARNESS="dsh", MDCG_UNIT="record")
    try:
        p = Principal(actor="a2")
        ms._apply_attribution(p)
        check("C1 MDCG_SESSION 优先", p.session == "dsl-web-main", p.session)
        check("C2 harness/unit 注入",
              p.harness == "dsh" and p.unit == "record")
        # 原实现此处复述了 C1（测的仍是 MDCG_SESSION），未覆盖「后备不越权覆盖」。
        old_dsh = _setenv(DSH_SESSION_ID="session-abc")
        try:
            pm = Principal(actor="a2b")
            ms._apply_attribution(pm)
            check("C3 两者并存时 MDCG_SESSION 优先（后备不覆盖）",
                  pm.session == "dsl-web-main", pm.session)
        finally:
            _restore(old_dsh)
    finally:
        _restore(old)
    old = _setenv(MDCG_SESSION=None, DSH_SESSION_ID="session-abc",
                  MDCG_HARNESS=None, MDCG_UNIT=None)
    try:
        p = Principal(actor="a3")
        ms._apply_attribution(p)
        check("C4 无 MDCG_SESSION 时用 DSH_SESSION_ID",
              p.session == "session-abc", p.session)
        check("C5 无归因环境时保留进程随机 id",
              (p := Principal()).session.startswith("sess_"))
    finally:
        _restore(old)

    # ---------- D. self_state 会话切片 ----------
    print("\n[D] 薄卡 + 会话维度切片（单例语义不变）")
    root = tempfile.mkdtemp(prefix="mdcg_p45_")
    SESS = ms._normalize_session("dsl-web-main")
    cg = MdCGSecure(root, principal=Principal(
        actor="dsh", session=SESS, harness="dsh", unit="record"))
    r = cg.self_state_refresh(ss.DEFAULT_SUBJECT)
    check("D1 refresh 缺省带会话维度",
          bool(r.get("ok")) and SESS in (
              (r.get("state") or {}).get("dimensions") or {}).get("session", []),
          str(r.get("changed")))
    card = cg.self_state_snapshot(ss.DEFAULT_SUBJECT)
    check("D2 单例卡 id 未因会话改变",
          card.get("node_id") == ss.state_node_id(ss.DEFAULT_SUBJECT))
    summ = cg.self_state_summary(ss.DEFAULT_SUBJECT, session=SESS)
    check("D3 summary 回报本会话已登记",
          summ.get("session_registered") is True and summ.get("session") == SESS)
    other = cg.self_state_summary(ss.DEFAULT_SUBJECT, session="session-other")
    check("D4 其它会话未登记且指针为空",
          other.get("session_registered") is False
          and (other.get("session_refs") or {}).get("count") == 0)
    r2 = cg.self_state_refresh(ss.DEFAULT_SUBJECT,
                               dimensions={"session": ["manual-x"]})
    dims = ((r2.get("state") or {}).get("dimensions") or {}).get("session", [])
    check("D5 会话并入而不覆盖显式维度",
          "manual-x" in dims and SESS in dims, str(dims))
    check("D6 窄刷新仍以单例卡为准（同 subject 一张卡）",
          cg.self_state_snapshot(ss.DEFAULT_SUBJECT).get("node_id")
          == ss.state_node_id(ss.DEFAULT_SUBJECT))

    # ---------- E. 会话要点 ----------
    print("\n[E] 会话要点：缺省会话 = Principal.session")
    n = cg.session_note("P45 会话要点：嵌套身份归因联调")
    check("E1 session_note 缺省采用进程会话", n.get("session") == SESS,
          str(n.get("session")))
    rec = cg.session_recall(session=SESS, include_state=True)
    check("E2 recall 命中本会话要点",
          any(x.get("id") == n.get("id") for x in rec.get("notes") or []))
    check("E3 recall 的自我状态带会话切片",
          (rec.get("self_state") or {}).get("session") == SESS)

    # ---------- F. 审计归因 ----------
    print("\n[F] 审计归因（harness/unit 只入审计）")
    with open(os.path.join(root, "_audit.jsonl"), encoding="utf-8") as f:
        rows = [json.loads(x) for x in f if x.strip()]
    last = rows[-1] if rows else {}
    check("F1 审计条目带 harness", last.get("harness") == "dsh", str(last.get("op")))
    check("F2 审计条目带 unit", last.get("unit") == "record")
    check("F3 审计条目带会话", bool(last.get("session")))

    # ---------- G. MCP 入口 ----------
    print("\n[G] MCP 分发：会话缺省透传")
    out = ms._self_state_call(cg, {"action": "summary"})
    check("G1 summary 缺省取 Principal 会话",
          out.get("session") == SESS and out.get("session_registered") is True)
    idx = ms._self_state_call(cg, {"action": "index"})
    check("G2 index 不传 dim → 按当前会话反查",
          idx.get("dimension") == "session" and idx.get("value") == SESS,
          str(idx.get("count")))
    out2 = ms._self_state_call(cg, {"action": "refresh"})
    check("G3 refresh 经 MCP 缺省登记会话",
          bool(out2.get("ok")))

    # ---------- R65. 近期事件段的会话隔离（issue #65） ----------
    print("\n[R65] session_recall ③ 近期事件：按会话隔离（issue #65；修前=全进程窗口）")
    _r65_group()

    print("\n" + "=" * 68)
    print(f"通过 {PASS} / 失败 {FAIL}")
    if FAILS:
        print("失败项：" + "，".join(FAILS))
    print("=" * 68)
    return FAIL


# ======================================================================
# R65（issue #65）：session_recall ③ 近期事件段的会话隔离
# ======================================================================
# 缺陷（外部报告 by ducc239，对 v0.7.5 实测；本 workflow 修前复现）：③ 段取
# `self.recent_events(limit=…)` 时**不传会话**，而 `MdCGSecure.recent_events`
# 无 session 形参（只有 private/secret 档判会话归属，默认档全放行）⇒ recent 恒为
# 全进程窗口：多窗口/多会话并发时 A 的续接包里混入 B 的报文（宿主把它当用户输入
# 处理，可被压缩检查点记入——静默污染）。同族既有正确形态（旁证）：`session_compact`
# 的 `if session: evs = [...]`、`_session_notes` 的 `session:{sid}` tag 过滤、
# MCP `_session_call` 已传 `session=`——缺口只在 session_recall ③ 段一处。
R65_A = "session-AAA-0000"
R65_B = "session-BBBB-0000"
R65_AX = R65_A + "-long"           # A 的**前缀延伸**会话：钉「严格相等」判据
R65_FAKE = "session-zzzz-nope-0000"
R65_BARE = "N0 无会话归属的裸事件"
R65_GLOBAL = ("A1", "A2", "AX", "B1", "N0")   # 全局窗口（不过滤）读数

# 五条事件：A×2 / B×1 / 裸×1（缺 meta.session）/ A 前缀延伸×1。
# 裸事件经**基类** remember_event 直写注入——安全档写入会把 meta.session
# setdefault 成本进程会话（mdcos.py:5087），测不到「缺 meta.session」形态；而读侧
# 对无归属事件的丢弃正是本 issue 的契约要求（存量数据 / 非安全档写入形态）。
R65_EVENTS = (
    ("user", "A1 会话A的第一句话", {"session": R65_A}),
    ("assistant", "A2 会话A的第二句话", {"session": R65_A}),
    ("user", "B1 会话B的第一句话", {"session": R65_B}),
    ("user", R65_BARE, {}),
    ("user", "AX 会话A前缀延伸会话", {"session": R65_AX}),
)

# 真源文件快照（导入时取一次）：变异自证把 `MdCGOS.session_recall` 换成 exec 出来的
# 临时函数，那种函数**没有源文件**（`getsource` 会抛 OSError）——故注释行检查必须锚在
# 导入时记下的真源路径上；docstring 检查则走 `__doc__`（变异体也带，M6 才能转红）。
_R65_FILE = inspect.getsourcefile(MdCGOS.session_recall)


def _r65_lib():
    """隔离库（系统临时目录合成库；不留仓内件）。"""
    cg = MdCGOS(tempfile.mkdtemp(prefix="mdcg_p45_r65_"))
    for role, text, meta in R65_EVENTS:
        cg.remember_event(role, text, meta=meta)
    return cg


def _r65_recent(cg, session):
    """续接包 recent 段的事件短标签（前 2 字），排序后返回（顺序不参与判据）。"""
    pack = cg.session_recall(session=session, recent_limit=20,
                             budget_tokens=4000, include_state=False)
    return sorted((r.get("text") or "")[:2] for r in (pack.get("recent") or []))


def _r65_cond_line():
    """`def session_recall` 上方紧邻的「生效条件：」注释行（本仓惯例：改函数须同步）。"""
    lines = io.open(_R65_FILE, encoding="utf-8").read().splitlines()
    for i, ln in enumerate(lines):
        if ln.strip().startswith("def session_recall("):
            j = i - 1
            while j >= 0 and not lines[j].strip():
                j -= 1
            return lines[j] if j >= 0 else ""
    return ""


def _r65_group():
    """R65 组断言（变异自证模式复用同一组，故不依赖模块级实例）。"""
    cg = _r65_lib()
    check("R65.1 假会话 id → recent 空窗口（修前=全库五条；杜绝错块）",
          _r65_recent(cg, R65_FAKE) == [], _r65_recent(cg, R65_FAKE))
    check("R65.2 会话 A → recent 恰为 A 的两条（严格相等：不含 B／裸事件／A 的前缀延伸会话）",
          _r65_recent(cg, R65_A) == ["A1", "A2"], _r65_recent(cg, R65_A))
    check("R65.3 会话 B → recent 恰为 B 的一条",
          _r65_recent(cg, R65_B) == ["B1"], _r65_recent(cg, R65_B))
    check('R65.4a session="*" → 不过滤（跨会话汇总合法用法）',
          _r65_recent(cg, "*") == list(R65_GLOBAL), _r65_recent(cg, "*"))
    check('R65.4b session=" * "（空白包裹）→ 仍按汇总处理（strip 判据）',
          _r65_recent(cg, " * ") == list(R65_GLOBAL), _r65_recent(cg, " * "))
    check("R65.5a session=None → 全局窗口（退回旧行为）",
          _r65_recent(cg, None) == list(R65_GLOBAL), _r65_recent(cg, None))
    check('R65.5b session=""（falsy）→ 全局窗口',
          _r65_recent(cg, "") == list(R65_GLOBAL), _r65_recent(cg, ""))
    check("R65.6a 指定会话下缺 meta.session 的事件被丢弃（不许漏；最坏空窗口）",
          "N0" not in _r65_recent(cg, R65_A), _r65_recent(cg, R65_A))
    check("R65.6b 不指定会话（None）时缺 meta.session 的事件照旧可见",
          "N0" in _r65_recent(cg, None), _r65_recent(cg, None))
    check("R65.7 回归：session_compact(session=A) 仍只压 A、compact(None) 照旧全局",
          cg.session_compact(session=R65_A, limit=50)["events"] == 2
          and cg.session_compact(session=None, limit=50)["events"] == len(R65_EVENTS),
          (cg.session_compact(session=R65_A, limit=50)["events"],
           cg.session_compact(session=None, limit=50)["events"]))
    _doc = inspect.getdoc(MdCGOS.session_recall) or ""
    check("R65.8 文档口径在位：docstring 声明「段跟会话走」＝recent 跟会话（含『跨会话汇总』"
          "例外口径）＋ 紧邻「生效条件：」注释含过滤条款",
          ("段跟会话走" in _doc and "跨会话汇总" in _doc
           and "recent 段按会话过滤" in _r65_cond_line()),
          _r65_cond_line()[:48])
    _mcp = MdCGSecure(tempfile.mkdtemp(prefix="mdcg_p45_r65_mcp_"),
                      principal=Principal(actor="r65_mcp", session=R65_A))
    _mcp.remember_event("user", "A1 生产形态：本会话事件", meta={"session": R65_A})
    _mcp.remember_event("user", "B1 生产形态：他会话事件", meta={"session": R65_B})
    _hit = ms._session_call(_mcp, {"action": "recall", "session": R65_A,
                                   "recent_limit": 20, "budget_tokens": 4000,
                                   "include_state": False})
    _none = ms._session_call(_mcp, {"action": "recall", "session": R65_FAKE,
                                    "recent_limit": 20, "budget_tokens": 4000,
                                    "include_state": False})
    check("R65.9 MCP 入口（_session_call recall）端到端：本会话只回本会话、假 id 空窗口",
          sorted((r.get("text") or "")[:2] for r in _hit.get("recent") or []) == ["A1"]
          and (_none.get("recent") or []) == [],
          (_hit.get("recent"), _none.get("recent")))


# ---------------------------------------------------------------- 定点变异自证
# 锚点在**去缩进后的实现源码**上定位（方法体在类体内缩进 4 格，编译前统一 dedent）。
# 每条变异声明**期望转红的断言项**；实跑红项与期望必须**恰好相等**——多红=断言语义
# 纠缠，少红=该判据空转（本仓教训：test_neg_condition_hits 的「整条命中档」曾 31 条
# 断言全绿而分支已删）。锚点漂移（命中次数 ≠1）→ ANCHOR-MISS + 退出码 2（fail-closed）。
_R65_A_BLOCK = (
    '        if session and str(session).strip() != "*":\n'
    '            evs = [r for r in evs if (r.get("meta") or {}).get("session") == session]\n')
_R65_A_COND = 'if session and str(session).strip() != "*":'
_R65_A_STRIP = 'str(session).strip() != "*"'
_R65_A_FILTER = ('evs = [r for r in evs '
                 'if (r.get("meta") or {}).get("session") == session]')
_R65_A_DOC = "段跟会话走"
_R65_ANCHORS = (_R65_A_BLOCK, _R65_A_COND, _R65_A_STRIP, _R65_A_FILTER, _R65_A_DOC)

_R65_MUTATIONS = (
    ("①删整段会话过滤（recent 回到全进程窗口）", _R65_A_BLOCK, "",
     {"R65.1", "R65.2", "R65.3", "R65.6a", "R65.9"}),
    ("②删 \"*\" 例外（星号也过滤）", _R65_A_COND, "if session:",
     {"R65.4a", "R65.4b"}),
    ("③去 strip（\" * \" 不再按汇总处理）", _R65_A_STRIP, 'str(session) != "*"',
     {"R65.4b"}),
    ("④缺 meta.session 改 fail-open（放行）", _R65_A_FILTER,
     ('evs = [r for r in evs if not (r.get("meta") or {}).get("session") '
      'or (r.get("meta") or {}).get("session") == session]'),
     # 签名：放行无归属事件 ⇒ 三个「按会话」腿任一都混入裸事件（R65.1/2/3 与 R65.6a
     # 同红）；R65.9 的库内无裸事件，故它**不**红——与变异① 的签名差恰在这一项。
     {"R65.1", "R65.2", "R65.3", "R65.6a"}),
    ("⑤去 falsy 守卫（None/\"\" 也过滤）", _R65_A_COND,
     'if str(session).strip() != "*":', {"R65.5a", "R65.5b"}),
    ("⑥文档口径回退（docstring 反转）", _R65_A_DOC, "段不跟会话走", {"R65.8"}),
)


def _r65_anchor_preflight():
    """锚点自检：任一锚点在实现源码里命中次数 ≠1 → ANCHOR-MISS + 退出码 2（fail-closed）。"""
    src = textwrap.dedent(inspect.getsource(MdCGOS.session_recall))
    bad = [(a, src.count(a)) for a in _R65_ANCHORS if src.count(a) != 1]
    if not bad:
        return 0
    for a, n in bad:
        print("  ANCHOR-MISS 锚点漂移（命中 %d 次，期望恰好 1）：%r" % (n, a[:70]))
    print("  => 实现已漂移，变异表失效：退出码 2（fail-closed；请同步 _R65_MUTATIONS 锚点）")
    return 2


def _r65_run():
    """跑 R65 组，返回（转红断言项集合, 通过数, 失败数）。"""
    global PASS, FAIL
    PASS = FAIL = 0
    del FAILS[:]
    _r65_group()
    return ({n.split(" ", 1)[0] for n in FAILS}, PASS, FAIL)


def _r65_self_proof():
    """逐条变异 → 要求恰好命中期望红项；复原后重跑全套应当全绿。"""
    rc = _r65_anchor_preflight()
    if rc:
        return rc
    print("!! 定点变异自证：就地变异运行中的实现源码（不读 git），逐条要求**恰好**命中期望红项\n")
    src = textwrap.dedent(inspect.getsource(MdCGOS.session_recall))
    orig = MdCGOS.session_recall
    bad = []
    with contextlib.redirect_stdout(io.StringIO()):
        base_red, _, _ = _r65_run()
    print("  未变异基线：红项 %d %s" % (len(base_red),
                                        "（应为 0）" if base_red else ""))
    if base_red:
        bad.append("未变异基线即转红：%s" % sorted(base_red))
    marks = "①②③④⑤⑥"
    for i, (name, old, new, expect) in enumerate(_R65_MUTATIONS):
        ns = dict(vars(_mdcos))
        exec(compile(src.replace(old, new), "<r65-mutated-%d>" % i, "exec"), ns)
        MdCGOS.session_recall = ns["session_recall"]
        try:
            with contextlib.redirect_stdout(io.StringIO()):
                red, _, _ = _r65_run()
        except Exception as exc:                       # noqa: BLE001
            red = {"<变异体运行异常:%s>" % type(exc).__name__}
        finally:
            MdCGOS.session_recall = orig
        hit = red == expect
        if not hit:
            bad.append("变异%s %s：红项 %s ≠ 期望 %s"
                       % (marks[i], name, sorted(red), sorted(expect)))
        print("  变异%s %-32s 红项 %d（期望 %d）%s"
              % (marks[i], name, len(red), len(expect),
                 "PASS" if hit else "**FAIL** 实=%s 期=%s" % (sorted(red), sorted(expect))))
    argv_bak = list(sys.argv)
    sys.argv[:] = [a for a in argv_bak if a != "--self-proof"]
    _buf = io.StringIO()
    try:
        with contextlib.redirect_stdout(_buf):
            full_rc = main()
    finally:
        sys.argv[:] = argv_bak
    print("  复原后重跑全套（A–G + R65）：退出码 %d %s"
          % (full_rc, "（全绿）" if full_rc == 0 else "**非全绿**"))
    if full_rc:
        for _ln in _buf.getvalue().splitlines():
            if "[FAIL]" in _ln:
                print("    复原重跑红：%s" % _ln.strip()[:120])
        bad.append("复原后全套非全绿（rc=%d）" % full_rc)
    print("\n变异自证：%s"
          % ("PASS（六条腿逐条恰好命中期望红项；复原后全绿）" if not bad
             else "FAIL —— " + "；".join(bad)))
    return 0 if not bad else 1


if __name__ == "__main__":
    _rc = main()
    sys.exit(_rc if _rc in (0, 2) else 1)