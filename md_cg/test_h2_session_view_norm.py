# -*- coding: utf-8 -*-
"""md_cg · H2：会话视图的读侧归一（「写进去能查出来」）

病灶（端到端实测）：写侧落盘值 = `_normalize_session(请求声明值)`
（`MdCGSecure._attribution` 取 `cg.session`，而 `cg.session` 由 `call_tool`
→ `_declared_session` 归一）；读侧 `stg.timeline` 却拿**未归一的原值**做
等值比较 ⇒ 同一条记忆「写进去查不出」——DSH 形态的会话 id 在会话根下不
存在时写侧落 `anonymous`，读侧按 `session-…` 精确匹配得 `count=0`。

修复（一处归一，改在视图层）：`stg._view_session` 只对「具体会话值」这一态
消费 `mcp_server._normalize_session`（真源唯一，**不重写实现**），三态语义
（None / "" / "*" = 跨会话）逐位不变。

覆盖
----
A 端到端：MCP 写一条声明了 DSH 形态 session 的记忆 → 落盘值是归一值，
  再用**原始声明值**读回来必须命中（H2 的核心断言）
B 归一真源唯一：读侧消费的确实是 `mcp_server._normalize_session`
  （哨兵替换法——防后续有人在 stg 里重写一把尺，那必然造出第三种不等值）
C 三态视图不回归：None / "" / "*" 仍跨会话；具体非 DSH 值仍精确匹配
D fail-soft：会话根不可读（OSError）时读写两侧都保原值，仍能读回
E 不越界：cg 侧读路径（search）不吃请求 session（issue #35 定稿：身份不可自报）

运行：python -m md_cg.test_h2_session_view_norm
"""
from __future__ import annotations

import os
import shutil
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Windows cmd 默认 GBK：中文打印即 UnicodeEncodeError，且崩在断言之后、报告之前。
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from md_cg.mdcos import MdCGSecure
from md_cg.security import DEFAULT_SENSITIVITY, Principal
from md_cg import mcp_server as ms

PASS = 0
FAILS = []

# 合成会话 id（uuid4 形态的 DSH 会话；非真实凭据，仅形态样本）
DSH_ID = "session-11111111-2222-3333-4444-555555555555"
ENV_KEY = "MDCG_DSH_SESSIONS_ROOT"

# 环境隔离（照 md_cg/test_state_event_op.py 钉 MDCG_TOKEN_FILE 的先例，2026-10-09）：
# mcp_server 的 env 权威 `_declared_session` / `_apply_attribution`（MDCG_SESSION
# 优先、退回 DSH_SESSION_ID）会**覆盖**本测试自声明的 session——凡 harness 注入
# 这两个键之一者，A2/A3/D2/D3 转红；未注入者全绿，同一件两机读数分叉。本测试不
# 依赖任何 env 会话，故全程清掉这两个键，使测试自声明的 session 成为权威，结束复原。
# **不改实现语义**（env 权威是既有契约，本笔只做测试侧环境隔离）。
_SESSION_ENV_KEYS = ("MDCG_SESSION", "DSH_SESSION_ID")


def check(name, cond, detail=""):
    global PASS
    if cond:
        PASS += 1
        print(f"  [PASS] {name}" + (f"  · {detail}" if detail else ""))
    else:
        FAILS.append(name)
        print(f"  [FAIL] {name}  · {str(detail)[:240]}")


def _p(actor, session):
    return Principal(actor=actor, clearance=DEFAULT_SENSITIVITY,
                     can_write=True, can_admin=True, role="designer",
                     session=session, harness="test-harness")


def _remember(cg, text, session):
    """经 MCP 写入口落一条（gated 路径，与插件自动记忆同一条链）。"""
    return ms.call_tool(cg, "mdcg_remember", {
        "content": text, "layer": "contextual", "session": session,
        "gated": True, "importance": 0.6})


def _timeline(cg, session):
    return ms.call_tool(cg, "stg", {"op": "timeline", "limit": 20, "session": session})


def test_a(root, sessions_root):
    """A 写进去能查出来（核心断言）。"""
    print("\n[A] 端到端：DSH 形态声明 → 落盘归一值 → 原值读回命中")
    old = os.environ.get(ENV_KEY)
    os.environ[ENV_KEY] = sessions_root          # 根可读、但无该会话
    try:
        # 前置条件断言：本用例的环境确实触发归一，否则下面的断言是空的
        check("A0 前置：该环境下 DSH 形态归一为 anonymous",
              ms._normalize_session(DSH_ID) == "anonymous",
              ms._normalize_session(DSH_ID))
        cg = MdCGSecure(root, principal=_p("alice", "sess_A"))
        res = _remember(cg, "阿尔法 会话视图归一 端到端写入样本", DSH_ID)
        nid = res.get("written") or res.get("node_id")
        check("A1 写入落盘（ACCEPT 且有节点 id）",
              bool(nid) and res.get("verdict") == "ACCEPT",
              (res.get("verdict"), nid))
        fm = (cg.get(nid) or {}).get("frontmatter") or {}
        check("A2 落盘 session = 归一声明值（写侧口径）",
              fm.get("session") == "anonymous", fm.get("session"))
        tl = _timeline(cg, DSH_ID)
        check("A3 用**原始声明值**读回命中（H2 核心：写进去查得出）",
              tl.get("count") == 1 and [i["id"] for i in tl.get("items", [])] == [nid],
              (tl.get("count"), [i["id"] for i in tl.get("items", [])[:3]]))
        check("A4 返回体 session = 归一后的生效值（诚实回带）",
              tl.get("session") == "anonymous", tl.get("session"))
    finally:
        if old is None:
            os.environ.pop(ENV_KEY, None)
        else:
            os.environ[ENV_KEY] = old


def test_b(root, sessions_root):
    """B 归一真源唯一（哨兵法）。"""
    print("\n[B] 读侧消费 mcp_server 真源（不重写一把尺）")
    old = os.environ.get(ENV_KEY)
    os.environ[ENV_KEY] = sessions_root
    orig = ms._normalize_session
    try:
        cg = MdCGSecure(root, principal=_p("alice", "sess_A"))
        ms._normalize_session = lambda raw: "SENTINEL_" + str(raw)
        out = _timeline(cg, "probe")
        check("B1 具体值经 mcp_server._normalize_session（哨兵可见）",
              out.get("session") == "SENTINEL_probe", out.get("session"))
        star = _timeline(cg, "*")
        check("B2 \"*\" 不经归一（跨会话开关是不变量）",
              star.get("session") is None, star.get("session"))
        blank = _timeline(cg, "")
        check("B3 空串不经归一（缺省语义不变量）",
              blank.get("session") is None, blank.get("session"))
    finally:
        ms._normalize_session = orig
        if old is None:
            os.environ.pop(ENV_KEY, None)
        else:
            os.environ[ENV_KEY] = old


def test_c(root, sessions_root):
    """C 三态视图不回归 + 具体值精确匹配。"""
    print("\n[C] 视图三态与精确匹配不回归")
    old = os.environ.get(ENV_KEY)
    os.environ[ENV_KEY] = sessions_root
    try:
        cg = MdCGSecure(root, principal=_p("alice", "sess_A"))
        _remember(cg, "贝塔 属于 会话 sess_A 的知识点", "sess_A")
        a = _timeline(cg, "sess_A")
        check("C1 具体非 DSH 值精确匹配（原样采用）",
              a.get("count") == 1 and a.get("session") == "sess_A",
              (a.get("count"), a.get("session")))
        z = _timeline(cg, "sess_Z")
        check("C2 未知会话为空（不因缺省而放行）",
              z.get("count") == 0, z.get("count"))
        for label, val in (("缺省", None), ("空串", ""), ("星号", "*")):
            out = _timeline(cg, val)
            check(f"C3 {label}仍为跨会话视图（返回体 session=None 且非空）",
                  out.get("session") is None and out.get("count") >= 1,
                  (out.get("session"), out.get("count")))
    finally:
        if old is None:
            os.environ.pop(ENV_KEY, None)
        else:
            os.environ[ENV_KEY] = old


def test_d(root, tmp):
    """D fail-soft：根不可读 → 两侧都保原值。"""
    print("\n[D] 会话根不可读（OSError）时 fail-soft 读写一致")
    old = os.environ.get(ENV_KEY)
    os.environ[ENV_KEY] = os.path.join(tmp, "no_such_root_dir")
    try:
        check("D1 根不可读 → 归一保原值",
              ms._normalize_session(DSH_ID) == DSH_ID,
              ms._normalize_session(DSH_ID))
        cg = MdCGSecure(root, principal=_p("alice", "sess_A"))
        res = _remember(cg, "伽马 根不可读 场景写入样本", DSH_ID)
        nid = res.get("written") or res.get("node_id")
        fm = (cg.get(nid) or {}).get("frontmatter") or {}
        check("D2 落盘保原值（不因环境差异丢会话标记）",
              fm.get("session") == DSH_ID, fm.get("session"))
        tl = _timeline(cg, DSH_ID)
        check("D3 同环境下读回命中（读写两侧同尺）",
              tl.get("count") == 1, tl.get("count"))
    finally:
        if old is None:
            os.environ.pop(ENV_KEY, None)
        else:
            os.environ[ENV_KEY] = old


def test_e(root, sessions_root):
    """E 不越界：cg 侧读路径不吃请求 session（issue #35 定稿）。"""
    print("\n[E] 不越界：search 的 session 不构成授权/过滤豁免")
    old = os.environ.get(ENV_KEY)
    os.environ[ENV_KEY] = sessions_root
    try:
        cg = MdCGSecure(root, principal=_p("alice", "sess_A"))
        _remember(cg, "德尔塔 共享档检索样本", "sess_A")
        res_default, _ = cg.search("德尔塔", judge=False, record=False)
        res_dsh, _ = cg.search("德尔塔", session=DSH_ID, judge=False, record=False)
        ids_default = {r[0].get("id") if isinstance(r, tuple) else r.get("id")
                       for r in res_default}
        ids_dsh = {r[0].get("id") if isinstance(r, tuple) else r.get("id")
                   for r in res_dsh}
        check("E1 传 DSH 形态 session 与缺省结果一致（cg 侧不经 _view_session）",
              ids_default == ids_dsh and bool(ids_default),
              (sorted(ids_default)[:3], sorted(ids_dsh)[:3]))
    finally:
        if old is None:
            os.environ.pop(ENV_KEY, None)
        else:
            os.environ[ENV_KEY] = old


def main():
    # 先隔离宿主注入的会话 env（见 _SESSION_ENV_KEYS 注释）——保证本测试自声明的
    # session 在任何 harness 下都是权威，读数不因宿主而分叉。
    _saved_env = {k: os.environ.get(k) for k in _SESSION_ENV_KEYS}
    for _k in _SESSION_ENV_KEYS:
        os.environ.pop(_k, None)
    tmp = tempfile.mkdtemp(prefix="mdcg_h2_")
    sessions_root = os.path.join(tmp, "sessions")
    os.makedirs(sessions_root, exist_ok=True)
    try:
        test_a(os.path.join(tmp, "root_a"), sessions_root)
        test_b(os.path.join(tmp, "root_b"), sessions_root)
        test_c(os.path.join(tmp, "root_c"), sessions_root)
        test_d(os.path.join(tmp, "root_d"), tmp)
        test_e(os.path.join(tmp, "root_e"), sessions_root)

        print("\n通过 %d / 失败 %d" % (PASS, len(FAILS)))
        if FAILS:
            print("失败项：" + ", ".join(FAILS))
            return 1
        return 0
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
        for _k, _v in _saved_env.items():
            if _v is None:
                os.environ.pop(_k, None)
            else:
                os.environ[_k] = _v


if __name__ == "__main__":
    sys.exit(main())
