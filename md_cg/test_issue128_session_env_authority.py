# -*- coding: utf-8 -*-
"""md_cg · issue #128 守卫：读侧 env 会话权威（写进去能查出来 · 第二处不对称）

缺陷（2026-10-12 隔离沙箱实测，非推断）
----------------------------------------
写侧 `mcp_server._declared_session` 有 docstring 声明的**环境权威**契约：部署侧
env（`MDCG_SESSION` 优先，退回 `DSH_SESSION_ID`）在场时，请求里的 `session`
声明一律被丢弃——「环境即权威，客户端不得改写归属」。`_apply_attribution` 随即把
`Principal.session` 设为 env 归一值，故落盘归属 = **env 值**。

读侧 `stg._view_session` 此前**只过 `_normalize_session`**，不看 env——于是
DSH 进程里客户端按自己声明的 sid 读本会话记忆时，过滤值是「归一后的声明值」，
与落盘的 env 值不等 ⇒ **本会话视图恒 0 条**（自动召回块「从未注入成功」）。
`src/hooks.ts` 的空 catch 把这次失败吞成「无痕」，与「本会话确实没有记忆」
不可分辨。

修法
----
1. 读侧 `_view_session` 同用写侧那套 env 权威判定（`_env_session_authority`，
   与 `_declared_session` 的 env 分支同源同形）——env 在场时把请求 `session`
   归到 env 值。**不放开任何授权面**（session 只是归因/视图维度）。
2. `src/hooks.ts` 两处空 catch 改显式回报（`ctx.logger.warn`，仍不抛）。
3. 若声明确被丢弃，返回体带 `session_declaration_ignored: true`（**只做回报，
   不改语义**），消除「接受参数、静默替换」的假装成功形态。

覆盖
----
A env 权威在场：写侧落 env 值 ⇒ 读侧用**请求声明值**读回命中（修复前 count=0）
B 无 env 权威：请求声明被采信、读回命中（既有行为不回归，count=1）
C 回报面：声明确被丢弃 ⇒ 返回体带 `session_declaration_ignored=True`；
  声明与 env 一致时不报（防噪声）；三态（None/""/"*"）不报
D 定点变异（抽掉 `_env_session_authority` 的 env 分支 ⇒ A 必红）

运行：python -X utf8 -m md_cg.test_issue128_session_env_authority
      python -X utf8 -m md_cg.test_issue128_session_env_authority --mutate
"""
from __future__ import annotations

import contextlib
import io
import os
import shutil
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from md_cg.mdcos import MdCGSecure
from md_cg.security import DEFAULT_SENSITIVITY, Principal
from md_cg import mcp_server as ms
from md_cg import stg

PASS, FAIL = 0, 0

_ENV_KEYS = ("MDCG_SESSION", "DSH_SESSION_ID")
_ENV_SESS = "env-sess-128"          # 非 DSH 形态 → 归一恒等，读数干净
_REQ_SESS = "sess_req_128"          # 客户端自己声明的（与 env 不同）


def check(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print("  [OK] " + name)
    else:
        FAIL += 1
        print("  [FAIL] " + name + ("  · " + str(detail) if detail else ""))


def _p(actor, session):
    return Principal(actor=actor, clearance=DEFAULT_SENSITIVITY,
                     can_write=True, can_admin=True, role="designer",
                     session=session, harness="test-harness")


def _remember(cg, text, session):
    return ms.call_tool(cg, "mdcg_remember", {
        "content": text, "layer": "contextual", "session": session,
        "gated": True, "importance": 0.6})


def _timeline(cg, session):
    return ms.call_tool(cg, "stg", {"op": "timeline", "limit": 20,
                                    "session": session})


@contextlib.contextmanager
def _env(**kw):
    saved = {k: os.environ.get(k) for k in kw}
    try:
        for k, v in kw.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        yield
    finally:
        for k, v in saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


def _cg(root, session):
    """构造实例并**显式走写侧归因注入**（与 mcp_server.main 同一条路：
    env 在场时 Principal.session 被设成 env 归一值）。"""
    p = _p("alice", session)
    ms._apply_attribution(p)         # env 在场即覆盖 p.session = env 归一值
    return MdCGSecure(root, principal=p)


# ---------------------------------------------------------------- A env 权威
def g_a(root):
    print("== A env 权威在场：写侧落 env 值，读侧用请求声明读回命中 ==")
    with _env(MDCG_SESSION=_ENV_SESS, DSH_SESSION_ID=None):
        cg = _cg(os.path.join(root, "a"), "sess_initial")
        check("A0 前置：env 归一后 = env 值",
              ms._normalize_session(_ENV_SESS) == _ENV_SESS
              and ms._declared_session(_REQ_SESS) is None,
              (ms._normalize_session(_ENV_SESS),
               ms._declared_session(_REQ_SESS)))
        res = _remember(cg, "阿尔法 env 权威读侧守卫样本", _REQ_SESS)
        nid = res.get("written") or res.get("node_id")
        fm = (cg.get(nid) or {}).get("frontmatter") or {}
        check("A1 落盘 session = env 值（写侧环境权威）",
              fm.get("session") == _ENV_SESS, fm.get("session"))
        tl = _timeline(cg, _REQ_SESS)
        check("A2 ★ 用请求声明值读回命中（修复前 count=0）",
              tl.get("count") == 1
              and [i["id"] for i in tl.get("items", [])] == [nid],
              (tl.get("count"), [i["id"] for i in tl.get("items", [])[:3]]))
        check("A3 返回体 session = env 值（生效值诚实回带）",
              tl.get("session") == _ENV_SESS, tl.get("session"))
        tl2 = _timeline(cg, _ENV_SESS)
        check("A4 用 env 值读回亦命中（两值同指一桶）",
              tl2.get("count") == 1, tl2.get("count"))


# ---------------------------------------------------------------- B 无 env
def g_b(root):
    print("== B 无 env 权威：请求声明被采信、读回命中（既有行为不回归） ==")
    with _env(MDCG_SESSION=None, DSH_SESSION_ID=None):
        cg = _cg(os.path.join(root, "b"), "sess_initial")
        res = _remember(cg, "贝塔 无 env 声明采信样本", _REQ_SESS)
        nid = res.get("written") or res.get("node_id")
        fm = (cg.get(nid) or {}).get("frontmatter") or {}
        check("B1 落盘 session = 请求声明值（无 env 即声明生效）",
              fm.get("session") == _REQ_SESS, fm.get("session"))
        tl = _timeline(cg, _REQ_SESS)
        check("B2 ★ 读回命中 count=1（H2 既有行为不回归）",
              tl.get("count") == 1, tl.get("count"))
        check("B3 未声明值不命中（不因 env 缺失而放行）",
              _timeline(cg, "sess_other").get("count") == 0,
              _timeline(cg, "sess_other").get("count"))


# ---------------------------------------------------------------- C 回报面
def g_c(root):
    print("== C 回报面：session_declaration_ignored（只回报，不改语义） ==")
    with _env(MDCG_SESSION=_ENV_SESS, DSH_SESSION_ID=None):
        cg = _cg(os.path.join(root, "c"), "sess_initial")
        _remember(cg, "伽马 声明丢弃回报样本", _REQ_SESS)
        tl = _timeline(cg, _REQ_SESS)
        check("C1 声明被丢弃 ⇒ 返回体带 session_declaration_ignored=True",
              tl.get("session_declaration_ignored") is True,
              tl.get("session_declaration_ignored"))
        tl_same = _timeline(cg, _ENV_SESS)
        check("C2 声明与 env 一致 ⇒ 不报（防噪声）",
              "session_declaration_ignored" not in tl_same,
              sorted(tl_same))
        for label, val in (("None", None), ("空串", ""), ("星号", "*")):
            out = _timeline(cg, val)
            check(f"C3 {label}（跨会话三态）不报声明丢弃",
                  "session_declaration_ignored" not in out, sorted(out))
    with _env(MDCG_SESSION=None, DSH_SESSION_ID=None):
        cg2 = _cg(os.path.join(root, "c2"), "sess_initial")
        _remember(cg2, "伽马 无 env 回报样本", _REQ_SESS)
        tl2 = _timeline(cg2, _REQ_SESS)
        check("C4 无 env 权威 ⇒ 不报（声明未被丢弃）",
              "session_declaration_ignored" not in tl2, sorted(tl2))


_GROUPS = (g_a, g_b, g_c)


def _run_all(root):
    global PASS, FAIL
    PASS, FAIL = 0, 0
    for g in _GROUPS:
        g(root)
    return FAIL


# ---------------------------------------------------------------- D 定点变异
def _mutate_mode():
    """抽掉读侧 env 权威（`_env_session_authority` 恒 None）⇒ A 组必红。"""
    saved = stg._env_session_authority
    tmp = tempfile.mkdtemp(prefix="i128_mut_")
    try:
        with contextlib.redirect_stdout(io.StringIO()):
            clean = _run_all(os.path.join(tmp, "clean"))
        stg._env_session_authority = lambda: None       # 还原缺陷形态
        try:
            with contextlib.redirect_stdout(io.StringIO()):
                red = _run_all(os.path.join(tmp, "red"))
        finally:
            stg._env_session_authority = saved
        with contextlib.redirect_stdout(io.StringIO()):
            after = _run_all(os.path.join(tmp, "after"))
        ok = (clean == 0 and red > 0 and after == 0)
        print(f"  未变异基线：红项={clean}（应 0）")
        print(f"  变异「读侧 env 权威抽掉」→ 红项={red}（应 > 0）")
        print(f"  还原后：红项={after}（应 0）")
        print("\n定点变异自证：" + ("PASS" if ok else "FAIL"))
        return 0 if ok else 1
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def main():
    if "--mutate" in sys.argv:
        print("!! 定点变异模式：抽掉读侧 env 权威，A 组应转红\n")
        return _mutate_mode()
    saved_env = {k: os.environ.get(k) for k in _ENV_KEYS}
    for k in _ENV_KEYS:
        os.environ.pop(k, None)
    root = tempfile.mkdtemp(prefix="i128_")
    try:
        fails = _run_all(root)
    finally:
        shutil.rmtree(root, ignore_errors=True)
        for k, v in saved_env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
    print(f"\n通过 {PASS} / 失败 {FAIL}")
    return 0 if fails == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
