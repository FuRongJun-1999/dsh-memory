# -*- coding: utf-8 -*-
"""守卫 · 会话身份五元组形态（s5，2026-10-09 DSH 端落地）。

形态（设计者定稿，已确认）：s5.<harness>.<unit>.<workspace>.<epoch>.<digest12>
三决定：①形态字符串如上 ②起点消息=首条 user 消息原文截断 1024 字符取 sha1 前 12
③起点时间=会话创建时间（unix 秒）。

判据：
  G1 形态：make_session5 产出符合正则，且与设计者示例前缀 s5.dsh.agent.D_4_ai. 对齐
  G2 slug：D:\\4_ai 与 D-4_ai 归一为同一 D_4_ai（跨端一致的前提）
  G3 可复算：verify_session5 对正确起点消息为真、对篡改消息为假
  G4 归一化接线：_normalize_session 原样保留 s5（不降级 anonymous）；
     且不误判 uuid4 形态与 sess_ 回落桶
  G5 截断确定性：超过 1024 字符的差异不影响 digest
运行：python -m md_cg.test_session5_identity   退出码 0 全绿 1 失败
"""
from __future__ import annotations

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
if REPO not in sys.path:
    sys.path.insert(0, REPO)

PASS = 0
FAIL = 0
FAILS = []


def check(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print("[PASS] %s%s" % (name, ("  · " + detail) if detail else ""))
    else:
        FAIL += 1
        FAILS.append(name)
        print("[FAIL] %s  · %s" % (name, detail))


def main():
    from md_cg import session5 as s5

    msg = "你好，这是本会话的第一条消息"
    sid = s5.make_session5("dsh", "agent", r"D:\4_ai", 1791340000, msg)
    check("G1a 形态符合正则", s5.is_session5(sid), sid)
    check("G1b 与设计者示例前缀对齐", sid.startswith("s5.dsh.agent.D_4_ai.1791340000."), sid)
    parsed = s5.parse_session5(sid) or {}
    check("G1c 字段可拆解", parsed.get("harness") == "dsh" and parsed.get("unit") == "agent"
          and parsed.get("workspace") == "D_4_ai" and parsed.get("start_epoch") == 1791340000,
          str(parsed))

    check("G2a 原生路径归一", s5.slug_workspace(r"D:\4_ai") == "D_4_ai", s5.slug_workspace(r"D:\4_ai"))
    check("G2b 目录名形态归一（与 a 同结果）", s5.slug_workspace("D-4_ai") == "D_4_ai",
          s5.slug_workspace("D-4_ai"))
    check("G2c 跨端一致：两种输入生成同一 id",
          s5.make_session5("dsh", "agent", r"D:\4_ai", 1791340000, msg)
          == s5.make_session5("dsh", "agent", "D-4_ai", 1791340000, msg), "")

    check("G3a 正确起点消息 → 校验通过", s5.verify_session5(sid, msg) is True, "")
    check("G3b 篡改起点消息 → 校验不通过", s5.verify_session5(sid, "伪造的首条消息") is False, "")

    check("G5 截断确定性（>1024 的差异不进 digest）",
          s5.digest_message("A" * 1024) == s5.digest_message("A" * 1024 + "B" * 500), "")

    try:
        from md_cg.mcp_server import _normalize_session, _is_session5_like
    except Exception as exc:
        check("G4 归一化接线（import mcp_server）", False, "%s: %s" % (type(exc).__name__, str(exc)[:80]))
    else:
        check("G4a _is_session5_like 认出 s5", _is_session5_like(sid) is True, "")
        check("G4b _normalize_session 原样保留 s5（不降级 anonymous）",
              _normalize_session(sid) == sid, _normalize_session(sid))
        check("G4c 不误判 uuid4 形态",
              _is_session5_like("session-c2da54e4-e22d-4228-878c-05801c85408b") is False, "")
        check("G4d sess_ 回落桶仍原样保留",
              _normalize_session("sess_ff792996a426") == "sess_ff792996a426", "")
        check("G4e 空值仍归 anonymous", _normalize_session("") == "anonymous", "")

    print("")
    print("=" * 64)
    print("通过 %d ／ 失败 %d" % (PASS, FAIL))
    if FAILS:
        print("失败项：" + "，".join(FAILS))
    print("=" * 64)
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
