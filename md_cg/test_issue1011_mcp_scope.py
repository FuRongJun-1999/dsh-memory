# -*- coding: utf-8 -*-
"""issue #1011 第 2 节守卫：请求级身份必须线程隔离，工单必须绑定提交者。

跑法：python -X utf8 -m md_cg.test_issue1011_mcp_scope
"""
import os
import sys
import tempfile
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# 本机 shell 里 DSH_SESSION_ID 通常已设 ⇒ `_declared_session` 会按「环境即权威」忽略请求声明，
# 那样测不到请求级会话隔离。测试内清掉，改由请求声明会话（单进程多会话载体形态）。
os.environ.pop("DSH_SESSION_ID", None)
os.environ.pop("MDCG_SESSION", None)

from md_cg import mcp_server as M
from md_cg.mdcos import MdCGSecure
from md_cg.security import Principal

_ok = 0
_bad = 0


def ok(cond, label, detail=""):
    global _ok, _bad
    if cond:
        _ok += 1
        print("  [PASS] %s" % label)
    else:
        _bad += 1
        print("  [FAIL] %s  %s" % (label, detail))


def _fresh(tag):
    root = tempfile.mkdtemp(prefix="i1011b_%s_" % tag)
    cg = MdCGSecure(root, principal=Principal(actor="designer", role="designer"))
    return cg


def s1_threads_do_not_clobber():
    """两线程各带不同 as_unit 走 call_tool：彼此不得看见对方的作用域。"""
    cg = _fresh("s1")
    seen = {}
    gate = threading.Barrier(2, timeout=10)
    _orig = M._dispatch

    def _probe(cg_, name, a):
        gate.wait()                     # 两线程同时进入，放大交错窗口
        time.sleep(0.02)
        return {"unit": getattr(cg_.principal, "unit", None),
                "session": getattr(cg_, "session", None)}

    M._dispatch = _probe

    def work(tag, unit, sess):
        seen[tag] = M.call_tool(cg, "mdcg_search",
                                {"query": "x", "as_unit": unit, "session": sess})

    try:
        ts = [threading.Thread(target=work, args=("A", "record", "sess_a")),
              threading.Thread(target=work, args=("B", "verify", "sess_b"))]
        [t.start() for t in ts]
        [t.join() for t in ts]
    finally:
        M._dispatch = _orig
    ok(seen.get("A", {}).get("unit") == "record",
       "S1a 线程 A 的 as_unit 不被线程 B 覆盖", repr(seen.get("A")))
    ok(seen.get("B", {}).get("unit") == "verify",
       "S1b 线程 B 的 as_unit 不被线程 A 覆盖", repr(seen.get("B")))
    _sa, _sb = M._declared_session("sess_a"), M._declared_session("sess_b")
    ok(seen.get("A", {}).get("session") == _sa
       and seen.get("B", {}).get("session") == _sb and _sa != _sb,
       "S1c 会话互不串台", "%r vs 期望 %r/%r" % (seen, _sa, _sb))
    ok(getattr(cg.principal, "unit", None) not in ("record", "verify"),
       "S1d 实例基身份未被线程改写", repr(getattr(cg.principal, "unit", None)))


def s2_job_id_unguessable():
    """工单 id 必须是 128 位随机，不再是「毫秒+4 位随机数」。"""
    cg = _fresh("s2")
    out = M._search_job_submit(cg, {"query": "q", "defer_s": 30}, 30)
    jid = out.get("job_id") or ""
    tail = jid[5:] if jid.startswith("sjob_") else ""
    ok(jid.startswith("sjob_") and len(tail) == 32
       and all(c in "0123456789abcdef" for c in tail),
       "S2a 工单 id = sjob_ + 32 位十六进制（128 位随机）", jid)
    ok("9999" not in jid or len(tail) == 32,
       "S2b 不再是 0..9999 的 4 位随机尾", jid)


def s3_job_result_bound_to_owner():
    """非提交者取结果必须被拒；提交者自己取得到。"""
    cg = _fresh("s3")
    out = M._search_job_submit(cg, {"query": "q", "defer_s": 30}, 30)
    jid = out.get("job_id")
    for _ in range(100):
        r = M._search_job_result(jid, cg)
        if r.get("status") in ("done", "error"):
            break
        time.sleep(0.05)
    ok(M._search_job_result(jid, cg).get("status") in ("done", "error", "pending"),
       "S3a 提交者自己取得到工单", repr(M._search_job_result(jid, cg))[:80])
    other = _fresh("s3b")            # 同 role 但不同 actor/session ⇒ 身份指纹不同
    other.principal = Principal(actor="someone_else", role="designer")
    denied = M._search_job_result(jid, other)
    ok(denied.get("status") == "forbidden" and denied.get("ok") is False,
       "S3b 非提交者取结果被拒（forbidden）", repr(denied)[:110])


def s4_background_job_runs_as_submitter():
    """后台线程必须按提交者身份跑（不能落到进程基身份）。"""
    cg = _fresh("s4")
    seen = {}
    _orig = M._dispatch

    def _probe(cg_, name, a):
        seen["unit"] = getattr(cg_.principal, "unit", None)
        seen["session"] = getattr(cg_, "session", None)
        return {"results": [], "meta": {}}

    M._dispatch = _probe
    try:
        out = M.call_tool(cg, "mdcg_search",
                          {"query": "q", "defer_s": 1, "as_unit": "verify",
                           "session": "sess_bg"})
        jid = out.get("job_id")
        for _ in range(100):
            if seen:
                break
            time.sleep(0.05)
    finally:
        M._dispatch = _orig
    ok(seen.get("unit") == "verify"
       and seen.get("session") == M._declared_session("sess_bg"),
       "S4 后台线程按提交者身份作用域执行",
       "%r vs 期望 session=%r" % (seen, M._declared_session("sess_bg")))


def main():
    print("issue #1011 第 2 节守卫：身份线程隔离 + 工单绑定")
    s1_threads_do_not_clobber()
    s2_job_id_unguessable()
    s3_job_result_bound_to_owner()
    s4_background_job_runs_as_submitter()
    print("守卫结果：%d 通过 / %d 失败" % (_ok, _bad))
    return 1 if _bad else 0


if __name__ == "__main__":
    sys.exit(main())