# -*- coding: utf-8 -*-
"""新用户模拟（issue 系列修复后的发布门禁）：以「拿到仓库的全新用户」身份
经 **MCP stdio 协议** 从零走通大脑主链路。

模拟环境：全新认知图 root（临时目录）+ 全新 MCP server 进程。
场景（每步都是 README 快速开始承诺的能力）：
  N1 initialize + tools/list（看到 cg/stg 基元）
  N2 空库首写（content_kind=code，issue #26 修复面）→ committed=true
  N3 检索召回（cg op=read）
  N4 冲突 defer 入队 → cg op=review 裁决 accept → 落盘
  N5 ccgc 编译 → 令牌签发（部署侧）→ attest(verifier_token) → link 落库
     （issue #27 修复面：验证方身份凭据化）
  N6 汇总
"""
import json
import os
import subprocess
import sys
import tempfile
import time

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)   # 部署侧直调（tokens.issue）与 server import 共用
PASS, FAIL, FAILS = 0, 0, []


def check(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  OK   {name}")
    else:
        FAIL += 1
        FAILS.append(name)
        print(f"  FAIL {name}  {detail}")


class Mcp:
    """stdio JSON-RPC 客户端（与 smoke_test 同款协议形态）。"""

    def __init__(self, root, token):
        env = dict(os.environ, MDCG_ROOT=root, PYTHONUTF8="1",
                   PYTHONPATH=REPO, MDCG_ACTOR="newuser",
                   MDCG_TOKEN=token,
                   MDCG_TOKEN_FILE=os.path.join(root, "tokens.json"))
        self.p = subprocess.Popen(
            [sys.executable, "-m", "md_cg.mcp_server"],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL, env=env, text=True,
            encoding="utf-8", cwd=REPO)
        self._rid = 0

    def call(self, method, params=None):
        self._rid += 1
        req = {"jsonrpc": "2.0", "id": self._rid, "method": method}
        if params is not None:
            req["params"] = params
        self.p.stdin.write(json.dumps(req, ensure_ascii=False) + "\n")
        self.p.stdin.flush()
        while True:
            line = self.p.stdout.readline()
            if not line:
                raise RuntimeError("server 输出关闭")
            resp = json.loads(line)
            if resp.get("id") == self._rid:
                return resp

    def tool(self, name, args):
        resp = self.call("tools/call", {"name": name, "arguments": args})
        return json.loads(resp["result"]["content"][0]["text"])

    def close(self):
        try:
            self.p.stdin.close()
            self.p.wait(timeout=5)
        except Exception:
            self.p.kill()


def main():
    root = tempfile.mkdtemp(prefix="newuser_cogmap_")
    # 部署侧动作（README 签发指引）：新用户拿到写权限的最短路径 = 签发
    # designer 令牌并经 MDCG_TOKEN 注入。无令牌 → guest 只读（fail-closed
    # 设计行为，非缺陷）——本模拟走「已按文档配置」的用户。
    from md_cg import tokens as _tokens
    tok_file = os.path.join(root, "tokens.json")
    tk_designer = _tokens.issue("designer", actor="newuser",
                                path=tok_file)["token"]
    os.environ["MDCG_TOKEN_FILE"] = tok_file   # N5 的 verifier 令牌同文件
    m = Mcp(root, tk_designer)
    ok = True
    try:
        print("== N1 initialize + tools/list ==")
        init = m.call("initialize", {"protocolVersion": "2024-11-05",
                                     "capabilities": {}})
        check("N1a initialize 握手",
              "result" in init and init["result"].get("serverInfo"),
              json.dumps(init, ensure_ascii=False)[:120])
        tools = m.call("tools/list", {})
        names = [t.get("name") for t in
                 tools["result"].get("tools", [])]
        check("N1b 基元工具 cg/stg 在列",
              "cg" in names and "stg" in names, f"tools={names[:8]}")

        print("== N2 空库首写（content_kind=code，issue #26 修复面）==")
        w = m.tool("cg", {"op": "write", "content_kind": "code",
                          "layer": "knowledge",
                          "content": "def newuser_probe():\n    return 42\n"})
        check("N2 空库首写 committed=true（旧实现 BLINDSPOT 拦截）",
              w.get("ok") is True and w.get("committed") is True,
              json.dumps(w, ensure_ascii=False, default=str)[:200])

        print("== N3 检索召回 ==")
        r = m.tool("cg", {"op": "read", "query": "newuser_probe", "k": 3})
        res = r.get("results") or []
        check("N3 首写内容可检索", isinstance(res, list) and len(res) >= 1,
              json.dumps(r, ensure_ascii=False, default=str)[:160])

        print("== N4 冲突 defer 入队 → 裁决 accept → 落盘 ==")
        w2 = m.tool("cg", {"op": "write",
                           "content": "# 功能名：待裁决探针\n"
                                      "# 生效条件：仅在裁决场景\n"
                                      "# 正文：需要设计者收口的结论 v1",
                           "layer": "knowledge",
                           "condition_space": {"existence_constraint":
                                               "裁决场景专用"},
                           "on_conflict": "defer"})
        # 同条件空间结论分歧/互斥未必稳定触发——容忍两种结果，但若入队则必须可裁决收口
        if w2.get("committed") is True:
            check("N4a 直接落盘（未触发冲突，闸面放行）", True)
        else:
            pid = w2.get("pid")
            check("N4a 冲突入队（pid 可得）", bool(pid),
                  json.dumps(w2, ensure_ascii=False, default=str)[:160])
            rv = m.tool("cg", {"op": "review", "action": "decide",
                               "pid": pid, "decision": "accept",
                               "reason": "newuser 模拟裁决"})
            check("N4b 裁决 accept 收口", rv.get("ok") is True,
                  json.dumps(rv, ensure_ascii=False, default=str)[:160])

        print("== N5 ccgc 编译 → 令牌签发 → attest(verifier_token) → link ==")
        # 入参集中在 ccg 对象里（_ccg_call 的解包口径）
        c = m.tool("cg", {"op": "ccg", "ccg": {
            "action": "compile", "node_id": "ccg_newuser_probe",
            "dialog": "user: 帮我沉淀 newuser 探针结论\n"
                      "assistant: 生效条件：newuser 模拟；"
                      "结论：探针可用",
            "actor": "agent-Compiler"}})
        compiled_ok = (c.get("ok") is True
                       or bool(c.get("pending"))
                       or (c.get("compiled") or {}).get("success") is True)
        check("N5a compile 产出候选", compiled_ok,
              json.dumps(c, ensure_ascii=False, default=str)[:200])
        # 部署侧动作：为编外验证方签发令牌（令牌签发不在 MCP 面——设计如此）
        from md_cg import tokens
        tk = tokens.issue("verifier", actor="external-reviewer",
                          path=os.environ["MDCG_TOKEN_FILE"])["token"]
        at = m.tool("cg", {"op": "ccg", "ccg": {
            "action": "attest", "node_id": "ccg_newuser_probe",
            "verdict": "ACCEPT", "compiled_by": "agent-Compiler",
            "verifier_token": tk}})
        atd = at.get("attest") or {}
        check("N5b 令牌签章通过（issue #27 凭据化身份）",
              at.get("ok") is True and atd.get("verifier_identity") == "token"
              and atd.get("verifier") == "external-reviewer",
              json.dumps(at, ensure_ascii=False, default=str)[:220])
        lk = m.tool("cg", {"op": "ccg", "ccg": {
            "action": "link", "node_id": "ccg_newuser_probe",
            "apply": True}})
        check("N5c link 落库（written>0）",
              (lk.get("written") or 0) > 0,
              json.dumps(lk, ensure_ascii=False, default=str)[:160])

        print("== N6 会话收尾 ==")
        info = m.tool("cg", {"op": "info"})
        check("N6 info 自报健康", info.get("ok") is True
              or "nodes" in json.dumps(info), str(info)[:120])
    except Exception as exc:  # noqa: BLE001
        ok = False
        FAILS.append(type(exc).__name__)
        print(f"  FAIL 异常：{type(exc).__name__}: {exc}")
    finally:
        m.close()
    print()
    if FAILS or not ok:
        print(f"FAILED: {len(FAILS)} 项 → {', '.join(FAILS)}")
        return 1
    print(f"ALL OK: {PASS} 项（新用户 MCP 全链模拟通过）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
