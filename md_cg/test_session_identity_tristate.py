# -*- coding: utf-8 -*-
"""md_cg · 会话身份三态（env → 请求声明 → unattributed）与 P1 回归守卫

背景
----
设计者 2026-10-07 裁定「会话身份三态」工程（P1 = 交接单 mem_1790416361175，
2026-09-26）：cg(op=write, session=sess_3a55e8c9651c) 落盘 session 变随机
sess_0804baa32949；三次 accept 三个随机会话 id；inbox 入队即丢声明值。

2026-10-07 本端复现核验（改动前一手读数，见守卫 A1）：当前 HEAD 上请求声明
通道（MCP 请求面）**已通**——`_declared_session('sess_3a55e8c9651c')` 干净
env 下返回声明值自身（P1 描述的「直调返回 None」不复现；当时的 None 系进程
env 命中否决或旧实现）。真存量洞是**第三态缺位**：无 env 且无声明时写入归属
全部落 `security.py:117` 的进程自动随机 `sess_<hex12>`（MCP 直连无声明写入 /
库层直调 / review_cli 缺省 / inbox 入队 / 事件 / 会话要点）——归因不可辨认、
跨进程对不上（幽灵索引 sess_5ae9a5874cfd 现象的机理）。

三态契约（解析单点 = `MdCGSecure._attributed_session`）
------------------------------------------------------
  态① env（MDCG_SESSION / DSH_SESSION_ID）→ 原值（三态收口不改写 env）；
  态② 请求声明（call_tool 请求级覆盖 / 库层显式构造 session）→ 原值；
  态③ 两者皆无（Principal 构造时的进程自动随机，session_auto=True 且未被
      覆盖）→ `UNATTRIBUTED_SESSION = 'unattributed'`（显式、可辨认、跨进程
      一致；不再产生新的随机 sess_hex）。
  **例外（钉死的既有语义）**：sens 达到 private 档时保持进程随机——绑定档的
  落盘值参与读回判据（`_readable`：`nsess == principal.session`），改写成
  unattributed 会让写者读不回自己刚写的 private/secret 节点（D 组钉死）。

覆盖
----
  A P1 回归：请求声明通道（直调解析 + MCP 端到端落盘一致 + 调用后复原）
  B env 优先不变：env 否决请求声明（解析层 + 端到端落 env 值 + _apply_attribution
    清自动标记 + main() 注入点源级断言）
  C 无声明 → unattributed：MCP 请求面 / 事件 / 库层直调 / 入队 rec / 会话要点；
    全库扫描无任何进程随机 sess_<hex12> 落盘
  D 显式 session 行为不变 + 绑定档豁免：显式值照落；private 无声明保持进程
    随机且同进程读回 OK
  E 来源标记传导与容错：narrowed_principal（as_unit 收窄）传导 session_auto；
    无标记对象保守默认（不放行收口、不炸）

运行：python -m md_cg.test_session_identity_tristate              # 正常跑
      python -m md_cg.test_session_identity_tristate --self-proof  # 变异自证
退出码：0 全绿 ｜ 1 断言失败 ｜ 2 ANCHOR-MISS（锚点漂移，fail-closed）

变异自证的基线源 = **运行中的实现源码**（`inspect.getsource` 就地变异、就地
复原），**不读 git**（与 test_p45 同款纪律：把基线绑到某个提交，下一次改动
即失效）。
"""
from __future__ import annotations

import contextlib
import inspect
import io
import json
import os
import re
import sys
import tempfile
import textwrap
import types

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from md_cg import mcp_server as ms
from md_cg import tokens as _tk
from md_cg import mdcos as _mdcos
from md_cg.mdcos import MdCGSecure, UNATTRIBUTED_SESSION
from md_cg.security import Principal

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
        print(f"  [FAIL] {name}  · {str(detail)[:240]}")


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


def _cg_no_decl(root):
    """无声明进程形态：自动随机会话的 principal（session=None）。"""
    return MdCGSecure(root, principal=Principal(
        actor="tristate", clearance="secret", can_write=True, can_admin=True,
        role="designer"), autoflush=1)


def _inbox_last(root):
    """隔离库 inbox.jsonl 的最后一条记录（无则 {}）。"""
    path = os.path.join(root, "hippocampus", "inbox.jsonl")
    last = {}
    if os.path.exists(path):
        with open(path, encoding="utf-8") as fh:
            for line in fh:
                if line.strip():
                    last = json.loads(line)
    return last


def _scan_sessions(root):
    """扫描隔离库全部节点 fm.session 与 inbox rec.session（去重集合）。"""
    from md_cg import nodefile
    vals = set()
    for dirpath, _dirs, files in os.walk(root):
        for f in files:
            if not f.endswith(".md"):
                continue
            try:
                with open(os.path.join(dirpath, f), encoding="utf-8") as fh:
                    fm, _c = nodefile.loads(fh.read())
            except Exception:            # noqa: BLE001 —— 非节点 md（如审计 md）
                continue
            if isinstance(fm, dict) and fm.get("session"):
                vals.add(str(fm.get("session")))
    rec = _inbox_last(root)
    if rec.get("session"):
        vals.add(str(rec["session"]))
    return vals


# ----------------------------------------------------------------------
# 组
# ----------------------------------------------------------------------

def _group_a():
    print("\n[A] P1 回归：请求声明通道（直调解析 + MCP 端到端）")
    check("A1 干净 env 直调 _declared_session('sess_3a55e8c9651c') == 声明值"
          "（P1 描述的 None 不复现）",
          ms._declared_session("sess_3a55e8c9651c") == "sess_3a55e8c9651c",
          repr(ms._declared_session("sess_3a55e8c9651c")))
    root = tempfile.mkdtemp(prefix="mdcg_tristate_a_")
    cg = _cg_no_decl(root)
    saved = cg.session
    out = ms.call_tool(cg, "mdcg_remember", {
        "node_id": "a_decl", "content": "A 组：请求声明写入",
        "layer": "contextual", "session": "sess_3a55e8c9651c"})
    fm = (cg.get("a_decl") or {}).get("frontmatter") or {}
    check("A2 端到端：请求声明值落盘一致（fm.session == 声明值）",
          bool(out.get("ok")) and fm.get("session") == "sess_3a55e8c9651c",
          repr(fm.get("session")))
    check("A3 调用后 cg.session 复原（不污染共享身份）",
          cg.session == saved, (cg.session, saved))


def _group_b():
    print("\n[B] env 优先不变（env 否决请求声明）")
    old = _setenv(MDCG_SESSION="env-sess", DSH_SESSION_ID=None)
    try:
        check("B1 env 存在 → 直调解析返回 None（请求声明被否决）",
              ms._declared_session("sess_req") is None,
              repr(ms._declared_session("sess_req")))
        p = Principal(actor="tristate", clearance="secret", can_write=True,
                      can_admin=True, role="designer")
        ms._apply_attribution(p)        # 模拟 _build_principal 的 env 注入
        check("B3 _apply_attribution：env 值注入且清进程自动标记",
              p.session == "env-sess"
              and getattr(p, "session_auto", None) is False,
              (p.session, getattr(p, "session_auto", None)))
        root = tempfile.mkdtemp(prefix="mdcg_tristate_b_")
        cg = MdCGSecure(root, principal=p, autoflush=1)
        ms.call_tool(cg, "mdcg_remember", {
            "node_id": "b_decl", "content": "B 组：env 下请求声明被否决",
            "layer": "contextual", "session": "sess_req"})
        fm = (cg.get("b_decl") or {}).get("frontmatter") or {}
        check("B2 端到端：env 下请求声明被否决，落 env 值",
              fm.get("session") == "env-sess", repr(fm.get("session")))
    finally:
        _restore(old)
    src = inspect.getsource(ms.main)
    check("B4 main() 的 MDCG_SESSION 注入点维护自动标记（源级断言）",
          "principal.session = _p_session" in src
          and "principal.session_auto = False" in src)
    old = _setenv(MDCG_SESSION=None, DSH_SESSION_ID="dsh-env")
    try:
        check("B5 DSH_SESSION_ID 同样否决请求声明",
              ms._declared_session("sess_req") is None)
    finally:
        _restore(old)


def _group_c():
    print("\n[C] 无声明 → unattributed（不再产生进程随机 sess_hex）")
    root = tempfile.mkdtemp(prefix="mdcg_tristate_c_")
    cg = _cg_no_decl(root)
    ms.call_tool(cg, "mdcg_remember", {
        "node_id": "c_mcp", "content": "C 组：MCP 请求面无声明",
        "layer": "contextual"})
    fm1 = (cg.get("c_mcp") or {}).get("frontmatter") or {}
    check("C1 MCP 请求面无声明 → unattributed",
          fm1.get("session") == UNATTRIBUTED_SESSION, repr(fm1.get("session")))
    cg.remember_event("user", "C 组：无声明事件")
    evs = cg.recent_events(limit=5)
    last = evs[0] if evs else {}
    check("C2 事件 meta.session → unattributed",
          (last.get("meta") or {}).get("session") == UNATTRIBUTED_SESSION,
          repr((last.get("meta") or {}).get("session")))
    cg2 = _cg_no_decl(root)            # 新实例 = 新自动随机（库层直调形态）
    cg2.add("c_cli", "C 组：库层直调无声明", layer="contextual")
    fm2 = (cg2.get("c_cli") or {}).get("frontmatter") or {}
    check("C3 库层直调 add → unattributed",
          fm2.get("session") == UNATTRIBUTED_SESSION, repr(fm2.get("session")))
    cg2.propose("c_prop", "C 组：无声明入队", sensitivity="internal")
    rec = _inbox_last(root)
    check("C4 入队 rec.session → unattributed（P1 inbox 现场收口）",
          bool(rec) and rec.get("session") == UNATTRIBUTED_SESSION,
          repr(rec.get("session")))
    vals = _scan_sessions(root)
    rand = sorted(v for v in vals if re.fullmatch(r"sess_[0-9a-f]{12}", v))
    check("C5 全库扫描：无任何进程随机 sess_<hex12> 落盘",
          not rand, str(rand))
    n = cg2.session_note("C 组：无声明会话要点")
    node = (cg2.get(n.get("id")) or {}).get("frontmatter") or {}
    tags = node.get("tags") or []
    check("C6 会话要点兜底 → unattributed（返回体与标签一致）",
          n.get("session") == UNATTRIBUTED_SESSION
          and f"session:{UNATTRIBUTED_SESSION}" in tags,
          (n.get("session"), tags))


def _group_d():
    print("\n[D] 显式 session 行为不变 + 绑定档豁免（既有语义钉死）")
    root = tempfile.mkdtemp(prefix="mdcg_tristate_d_")
    cg = MdCGSecure(root, principal=Principal(
        actor="tristate", clearance="secret", can_write=True, can_admin=True,
        role="designer", session="sess_explicit"), autoflush=1)
    cg.add("d_expl", "D 组：显式会话共享档", layer="contextual")
    fm = (cg.get("d_expl") or {}).get("frontmatter") or {}
    check("D1 显式 session → 原值（共享档）",
          fm.get("session") == "sess_explicit", repr(fm.get("session")))
    # D2 用非 admin 身份：读回判据必须走会话绑定分支（admin 豁免会掩盖口径）
    p2 = Principal(actor="tristate2", clearance="secret", can_write=True,
                   can_admin=False, role="recorder")
    cg2 = MdCGSecure(root, principal=p2, autoflush=1)
    cg2.add("d_priv", "D 组：私档无声明", layer="contextual",
            sensitivity="private")
    fm2 = (cg2.get("d_priv") or {}).get("frontmatter") or {}
    check("D2a 私档 + 无声明 → 保持进程随机（授权绑定档豁免）",
          bool(p2.session) and fm2.get("session") == p2.session
          and str(fm2.get("session", "")).startswith("sess_"),
          repr(fm2.get("session")))
    check("D2b 私档同进程读回 OK（豁免的根据：读回判据锚 principal.session）",
          cg2.get("d_priv") is not None)
    cg3 = MdCGSecure(root, principal=Principal(
        actor="tristate", clearance="secret", can_write=True, can_admin=True,
        role="designer", session="sess_priv"), autoflush=1)
    cg3.add("d_priv2", "D 组：私档显式会话", layer="contextual",
            sensitivity="private")
    fm3 = (cg3.get("d_priv2") or {}).get("frontmatter") or {}
    check("D3 私档 + 显式 session → 原值",
          fm3.get("session") == "sess_priv", repr(fm3.get("session")))


def _group_e():
    print("\n[E] 来源标记传导与容错")
    p = Principal(actor="tristate")
    q = _tk.narrowed_principal(p, "record")
    check("E1a 自动随机来源经 narrowed_principal 传导（auto 保持 True）",
          getattr(q, "session_auto", None) is True,
          getattr(q, "session_auto", None))
    p2 = Principal(actor="tristate", session="sess_x")
    q2 = _tk.narrowed_principal(p2, "record")
    check("E1b 显式声明的来源传导（auto 保持 False）",
          getattr(q2, "session_auto", None) is False
          and q2.session == "sess_x")
    root = tempfile.mkdtemp(prefix="mdcg_tristate_e_")
    cg = MdCGSecure(root, principal=Principal(actor="tristate",
                                              session="sess_e"), autoflush=1)
    cg.principal = types.SimpleNamespace(session="sess_e")  # 无 session_auto
    check("E2 无标记对象容错（保守默认：不放行收口、不改写）",
          cg._attributed_session() == "sess_e")


# ----------------------------------------------------------------------
# 定点变异自证（锚点 = 去缩进后的运行中源码；命中 ≠1 → ANCHOR-MISS）
# ----------------------------------------------------------------------

def _src_of(fn):
    return textwrap.dedent(inspect.getsource(fn))


_ANCHORS = (
    (lambda: _src_of(MdCGSecure._attributed_session),
     "return UNATTRIBUTED_SESSION"),
    (lambda: _src_of(MdCGSecure._attributed_session),
     "    if bound:\n        return sess                  # 授权绑定档：保持随机（读回判据锚定它）"),
    (lambda: _src_of(ms._declared_session),
     'if (os.environ.get("MDCG_SESSION")\n'
     '            or os.environ.get("DSH_SESSION_ID") or "").strip():\n'
     '        return None                  # 环境已固定会话：客户端不得改写归属'),
    (lambda: _src_of(ms.call_tool),
     'sess = _declared_session(a.get("session"))'),
    (lambda: _src_of(_tk.narrowed_principal),
     'q.session_auto = getattr(p, "session_auto", False)'),
)


def _anchor_preflight():
    """锚点自检：任一锚点在去缩进源码里命中次数 ≠1 → ANCHOR-MISS + 退出码 2。"""
    bad = []
    for get_src, anchor in _ANCHORS:
        n = get_src().count(anchor)
        if n != 1:
            bad.append((anchor, n))
    if not bad:
        return 0
    for anchor, n in bad:
        print("  ANCHOR-MISS 锚点漂移（命中 %d 次，期望恰好 1）：%r"
              % (n, anchor[:70]))
    print("  => 实现已漂移，变异表失效：退出码 2（fail-closed；请同步 _MUTATIONS 锚点）")
    return 2


def _run_all():
    """跑全部组，返回（转红断言项集合, 通过数, 失败数）。"""
    global PASS, FAIL
    PASS = FAIL = 0
    del FAILS[:]
    old = _setenv(MDCG_SESSION=None, DSH_SESSION_ID=None)
    try:
        _group_a()
        _group_b()
        _group_c()
        _group_d()
        _group_e()
    finally:
        _restore(old)
    return ({n.split(" ", 1)[0] for n in FAILS}, PASS, FAIL)


# 变异表：(名, 目标模块命名空间, 宿主函数, old, new, 期望红项集合)
_MUTATIONS = (
    ("①撤 unattributed 分支（自动随机放行）",
     _mdcos, MdCGSecure._attributed_session,
     "return UNATTRIBUTED_SESSION", "return sess",
     {"C1", "C2", "C3", "C4", "C5", "C6"}),
    ("②删 env 否决（请求声明盖过 env）",
     ms, ms._declared_session,
     'if (os.environ.get("MDCG_SESSION")\n'
     '            or os.environ.get("DSH_SESSION_ID") or "").strip():\n'
     '        return None                  # 环境已固定会话：客户端不得改写归属',
     "", {"B1", "B2", "B5"}),
    ("③吞请求声明（call_tool 不解声明）",
     ms, ms.call_tool,
     'sess = _declared_session(a.get("session"))', 'sess = None',
     {"A2"}),
    ("④撤私档豁免（绑定档也改 unattributed）",
     _mdcos, MdCGSecure._attributed_session,
     "    if bound:\n        return sess                  # 授权绑定档：保持随机（读回判据锚定它）",
     "", {"D2a", "D2b"}),
    ("⑤撤来源标记传导（narrowed copy 丢失 auto）",
     _tk, _tk.narrowed_principal,
     'q.session_auto = getattr(p, "session_auto", False)', "",
     {"E1a"}),
)


def _mutate_and_run(ns_mod, host_fn, old, new):
    """就地变异 host_fn（exec 到宿主模块命名空间），跑全套，finally 复原。"""
    src = _src_of(host_fn)
    mutated = src.replace(old, new)
    qn = getattr(host_fn, "__qualname__", host_fn.__name__)
    ns = dict(vars(ns_mod))
    exec(compile(mutated, "<tristate-mutated>", "exec"), ns)
    short = qn.split(".")[-1]
    if "." in qn:                        # 类方法：替换类属性后复原
        cls = ns_mod.__dict__[qn.split(".")[0]]
        orig = cls.__dict__[short]
        setattr(cls, short, ns[short])
        try:
            with contextlib.redirect_stdout(io.StringIO()):
                red, _, _ = _run_all()
            return red
        finally:
            setattr(cls, short, orig)
    orig = getattr(ns_mod, short)
    setattr(ns_mod, short, ns[short])
    try:
        with contextlib.redirect_stdout(io.StringIO()):
            red, _, _ = _run_all()
        return red
    finally:
        setattr(ns_mod, short, orig)


def _self_proof():
    rc = _anchor_preflight()
    if rc:
        return rc
    print("!! 定点变异自证：就地变异运行中的实现源码（不读 git），"
          "逐条要求**恰好**命中期望红项\n")
    with contextlib.redirect_stdout(io.StringIO()):
        base_red, _, _ = _run_all()
    print("  未变异基线：红项 %d %s" % (len(base_red),
                                        "（应为 0）" if base_red else ""))
    bad = []
    if base_red:
        bad.append("未变异基线即转红：%s" % sorted(base_red))
    marks = "①②③④⑤"
    for i, (name, ns_mod, host_fn, old, new, expect) in enumerate(_MUTATIONS):
        try:
            red = _mutate_and_run(ns_mod, host_fn, old, new)
        except Exception as exc:                       # noqa: BLE001
            red = {"<变异体运行异常:%s>" % type(exc).__name__}
        hit = red == expect
        if not hit:
            bad.append("变异%s %s：红项 %s ≠ 期望 %s"
                       % (marks[i], name, sorted(red), sorted(expect)))
        print("  变异%s %-34s 红项 %d（期望 %d）%s"
              % (marks[i], name, len(red), len(expect),
                 "PASS" if hit else "**FAIL** 实=%s 期=%s" % (sorted(red),
                                                              sorted(expect))))
    argv_bak = list(sys.argv)
    sys.argv[:] = [a for a in argv_bak if a != "--self-proof"]
    _buf = io.StringIO()
    try:
        with contextlib.redirect_stdout(_buf):
            full_rc = main()
    finally:
        sys.argv[:] = argv_bak
    print("  复原后重跑全套（A–E）：退出码 %d %s"
          % (full_rc, "（全绿）" if full_rc == 0 else "**非全绿**"))
    if full_rc:
        for _ln in _buf.getvalue().splitlines():
            if "[FAIL]" in _ln:
                print("    复原重跑红：%s" % _ln.strip()[:120])
        bad.append("复原后全套非全绿（rc=%d）" % full_rc)
    print("\n变异自证：%s"
          % ("PASS（五条腿逐条恰好命中期望红项；复原后全绿）" if not bad
             else "FAIL —— " + "；".join(bad)))
    return 0 if not bad else 1


def main():
    global PASS, FAIL
    if "--self-proof" in sys.argv:
        return _self_proof()
    _rc = _anchor_preflight()
    if _rc:
        return _rc
    PASS = FAIL = 0
    del FAILS[:]
    old = _setenv(MDCG_SESSION=None, DSH_SESSION_ID=None)
    try:
        _group_a()
        _group_b()
        _group_c()
        _group_d()
        _group_e()
    finally:
        _restore(old)
    print("\n" + "=" * 68)
    print(f"通过 {PASS} / 失败 {FAIL}")
    if FAILS:
        print("失败项：" + "，".join(FAILS))
    print("=" * 68)
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    _rc = main()
    sys.exit(_rc if _rc in (0, 2) else 1)
