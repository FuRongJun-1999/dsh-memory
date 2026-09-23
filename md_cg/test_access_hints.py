# -*- coding: utf-8 -*-
"""test_access_hints —— AccessDenied 可操作指引专项（issue #34）

背景：新用户三步接入后必然撞上的第一条失败是 guest 只读写入被拒，而该错误
无任何 hint（与本仓 md_cg/*.py 70 处 hint 标准不一致）——issue #34 判定为
「同一仓内标准不一致，且恰落在最影响首次体验的位置」。

覆盖：
- guest op 拒绝：hint 含为什么（MDCG_TOKEN 未配置）+ 怎么办（tokens issue /
  setx / 重启 / README 指针）+ 安抚（不是故障）+ help 指引
- 有令牌但白名单缺 op：hint 指「换角色 / --ops-allow 补授权重签」（不误导成配凭据）
- 令牌过期：hint 指重新签发
- guest require_write：hint 同步到位（同口径）
- MCP stdio 端到端（issue 复现路径）：干净库 + 无 MDCG_TOKEN → cg(op=write)
  的 error JSON 结构化携带 hint

运行：python -X utf8 -m md_cg.test_access_hints
"""
import json
import os
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from md_cg.security import AccessDenied, Principal  # noqa: E402

passed = failed = 0


def check(name, cond, detail=""):
    global passed, failed
    if cond:
        passed += 1
        print("  [PASS] " + name)
    else:
        failed += 1
        print("  [FAIL] " + name + "  " + str(detail)[:200])


def _denied(fn):
    try:
        fn()
        return None
    except AccessDenied as e:
        return e


GUEST_OPS = ("info", "route", "read", "recent", "whitebox", "status", "edges")


def main():
    print("[1] guest op 拒绝（issue #34 主场景）")
    guest = Principal(actor="world", role="guest", ops_allow=GUEST_OPS,
                      can_write=False)
    e = _denied(lambda: guest.require_op("write"))
    check("guest op=write 抛 AccessDenied", e is not None)
    h = (e.hint if e else "") or ""
    for kw, label in [("MDCG_TOKEN", "点明凭据来源"),
                      ("tokens issue", "给签发命令"),
                      ("setx", "给配置动作"),
                      ("README", "给文档指针"),
                      ("不是故障", "安抚语气"),
                      ('cg(op="help"', "help 指引"),
                      ("重启", "重启生效提示")]:
        check(f"hint {label}（{kw}）", kw in h, h[:120])
    check("hint 非空且 error 消息保留原口径",
          bool(h) and "无权执行 op=write" in str(e))

    print("[2] 有令牌但白名单缺 op（不误导成配凭据）")
    rec = Principal(actor="demo", role="recorder",
                    ops_allow=("read", "write", "recent"), can_write=True)
    e2 = _denied(lambda: rec.require_op("forget"))
    check("recorder op=forget 抛 AccessDenied", e2 is not None)
    h2 = (e2.hint if e2 else "") or ""
    check("hint 指补授权/换角色（--ops-allow / 重新签发）",
          "--ops-allow" in h2 and "重新签发" in h2, h2[:120])
    check("hint 不误指 guest 成因（不含 MDCG_TOKEN 未配置口径）",
          "未检测到写入凭据" not in h2, h2[:120])

    print("[3] 令牌过期")
    exp = Principal(actor="demo", role="designer",
                    expires_at=1, can_write=True)
    e3 = _denied(lambda: exp.require_op("read"))
    check("过期抛 AccessDenied 且 hint 指重新签发",
          e3 is not None and "重新签发" in (e3.hint or ""), e3.hint)

    print("[4] guest require_write 同口径")
    e4 = _denied(lambda: guest.require_write("internal"))
    check("guest 写拒绝带 hint（含 MDCG_TOKEN）",
          e4 is not None and "MDCG_TOKEN" in (e4.hint or ""), e4.hint)

    print("[5] MCP stdio 端到端（issue 复现路径：干净库 + 无令牌）")
    root = tempfile.mkdtemp(prefix="acc_hint_")
    env = dict(os.environ)
    env.pop("MDCG_TOKEN", None)
    env["MDCG_ROOT"] = root
    env["PYTHONUTF8"] = "1"
    py = sys.executable
    proc = subprocess.Popen(
        [py, "-X", "utf8", "-m", "md_cg.mcp_server"],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
        env=env, cwd=os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        text=True, encoding="utf-8")

    def rpc(id_, method, params=None):
        req = {"jsonrpc": "2.0", "id": id_, "method": method,
               "params": params or {}}
        proc.stdin.write(json.dumps(req) + "\n")
        proc.stdin.flush()
        line = proc.stdout.readline()
        return json.loads(line) if line.strip() else {}

    try:
        rpc(1, "initialize", {"protocolVersion": "2024-11-05",
                              "capabilities": {}, "clientInfo": {"name": "t"}})
        # 通知无应答：直写不等（带 id 等通知应答会错位/阻塞）
        proc.stdin.write(json.dumps(
            {"jsonrpc": "2.0", "method": "notifications/initialized"}) + "\n")
        proc.stdin.flush()
        r = rpc(3, "tools/call", {"name": "cg", "arguments": {
            "op": "write", "content": "测试写入", "content_kind": "code"}})
        proc.stdin.close()
        body = ((r.get("result") or {}).get("content") or [{}])[0].get("text", "")
        obj = json.loads(body) if body.startswith("{") else {}
        check("stdio error JSON 含 AccessDenied", "AccessDenied" in obj.get("error", ""),
              body[:160])
        check("stdio error JSON 结构化携带 hint（含 MDCG_TOKEN 与签发命令）",
              "MDCG_TOKEN" in (obj.get("hint") or "")
              and "tokens issue" in (obj.get("hint") or ""),
              (obj.get("hint") or "")[:160])
        check("isError=True 形态", bool((r.get("result") or {}).get("isError")))
    finally:
        try:
            proc.wait(timeout=10)
        except Exception:                                  # noqa: BLE001
            proc.kill()
        import shutil
        shutil.rmtree(root, ignore_errors=True)

    print(f"\naccess_hints: {passed} 通过 / {failed} 失败")
    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(main())
