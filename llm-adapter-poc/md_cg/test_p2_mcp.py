# -*- coding: utf-8 -*-
"""md_cg · MCP 协议验收（stdio + JSON-RPC 2.0）

运行：python -m md_cg.test_p2_mcp
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile

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


class McpClient:
    """最小 MCP stdio 客户端（逐行 JSON-RPC 2.0）。"""

    def __init__(self, root, actor="mcp-test"):
        env = dict(os.environ)
        env["MDCG_ROOT"] = root
        env["MDCG_ACTOR"] = actor
        env["PYTHONIOENCODING"] = "utf-8"
        here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        env["PYTHONPATH"] = here + os.pathsep + env.get("PYTHONPATH", "")
        self.p = subprocess.Popen(
            [sys.executable, "-m", "md_cg.mcp_server"],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            env=env, text=True, encoding="utf-8", cwd=here)
        self._id = 0

    def send(self, method, params=None, notify=False):
        msg = {"jsonrpc": "2.0", "method": method}
        if params is not None:
            msg["params"] = params
        if not notify:
            self._id += 1
            msg["id"] = self._id
        self.p.stdin.write(json.dumps(msg, ensure_ascii=False) + "\n")
        self.p.stdin.flush()
        if notify:
            return None
        line = self.p.stdout.readline()
        if not line:
            err = self.p.stderr.read()[:400]
            raise RuntimeError(f"no response; stderr={err}")
        return json.loads(line)

    def call(self, name, args=None):
        r = self.send("tools/call", {"name": name, "arguments": args or {}})
        content = r["result"]["content"][0]["text"]
        try:
            return json.loads(content)
        except ValueError:
            return content

    def close(self):
        try:
            self.send("shutdown")
        except Exception:  # noqa: BLE001
            pass
        try:
            self.p.wait(timeout=5)
        except Exception:  # noqa: BLE001
            self.p.kill()


def main():
    root = tempfile.mkdtemp(prefix="mdcg_mcp_")
    cli = None
    try:
        cli = McpClient(root)

        # 1. 握手
        print("\n【1】握手与工具发现")
        init = cli.send("initialize", {"protocolVersion": "2024-11-05",
                                       "capabilities": {},
                                       "clientInfo": {"name": "test", "version": "0"}})
        check("initialize 返回协议版本",
              init.get("result", {}).get("protocolVersion") == "2024-11-05", str(init)[:100])
        cli.send("notifications/initialized", {}, notify=True)
        tl = cli.send("tools/list")
        tools = tl.get("result", {}).get("tools", [])
        names = {t["name"] for t in tools}
        check("tools/list 返回工具面", len(tools) >= 15, f"{len(tools)} 个")
        check("工具名以 mdcg_ 前缀", all(n.startswith("mdcg_") for n in names),
              ",".join(sorted(names)[:6]) + " ...")

        # 2. 写 + 读
        print("\n【2】写 / 读")
        CCG = ("# 功能名：红按钮移动\n# 生效条件：问红按钮\n# 子功能：左移\n"
               "# 执行：红按钮控制角色左移\n# 验证方式：test\n# 不适用条件：问蓝按钮\n\n红按钮控制角色左移\n")
        r1 = cli.call("mdcg_remember", {"node_id": "n1", "content": CCG,
                                        "role": "knowledge", "verification_basis": "test",
                                        "tags": ["game"]})
        check("mdcg_remember 成功", r1.get("ok"), str(r1)[:80])
        g = cli.call("mdcg_get", {"node_id": "n1"})
        check("mdcg_get 读回内容", g and "红按钮" in (g.get("content") or ""), str(g)[:80])

        # 3. 检索 / 召回
        print("\n【3】检索 / 召回")
        s = cli.call("mdcg_search", {"query": "红按钮", "k": 5})
        check("mdcg_search 有结果", len(s.get("results", [])) > 0,
              f"{len(s.get('results', []))} 条")
        check("search 自报 tier", "tier" in s.get("meta", {}), str(s.get("meta", {}))[:80])
        rec = cli.call("mdcg_recall", {"query": "红按钮", "budget_tokens": 500})
        check("mdcg_recall 返回记忆包", "pack" in rec and rec["tokens_used"] <= rec["budget"],
              f"used={rec.get('tokens_used')}/{rec.get('budget')}")

        # 4. 负记忆 / 未解 / 飞轮 / 反思
        print("\n【4】负记忆 / 未解 / 飞轮 / 反思")
        rj = cli.call("mdcg_rejected", {"hypothesis": "红按钮开门", "reason": "按了3次没反应"})
        check("mdcg_rejected 写入负记忆", rj.get("id", "").startswith("rej_"), str(rj))
        un = cli.call("mdcg_unresolved", {"question": "绿按钮干嘛的", "known_clues": "按了没反应"})
        check("mdcg_unresolved 写入未解", un.get("id", "").startswith("unr_"), str(un))
        fw = cli.call("mdcg_flywheel", {"error_report": {"query": "红按钮", "expected_state": "ACCEPT",
                                                        "actual_state": "BLINDSPOT", "missing": "缺条件"}})
        check("mdcg_flywheel 产出 unresolved", fw.get("unresolved_id", "").startswith("unr_"), str(fw)[:80])
        rf = cli.call("mdcg_reflect", {"query": "红按钮"})
        check("mdcg_reflect 记录信息差 D", "d_curr" in rf, str({k: rf.get(k) for k in ("d_curr", "d2")}))

        # 5. 审核队列
        print("\n【5】审核队列")
        pr = cli.call("mdcg_propose", {"node_id": "p1", "content": CCG})
        check("mdcg_propose 入队", pr.get("pid", "").startswith("prop_"), str(pr))
        rl = cli.call("mdcg_review_list")
        check("mdcg_review_list 列出待审", any(x["pid"] == pr["pid"] for x in rl.get("pending", [])),
              f"{len(rl.get('pending', []))} 条")
        rd = cli.call("mdcg_review_decide", {"pid": pr["pid"], "decision": "accept"})
        check("mdcg_review_decide accept", rd.get("ok"), str(rd))

        # 6. tombstone / 恢复
        print("\n【6】tombstone / 恢复")
        fg = cli.call("mdcg_forget", {"node_id": "n1", "reason": "mcp 测试"})
        check("mdcg_forget 软删除", fg.get("ok"), str(fg))
        rs = cli.call("mdcg_restore", {"node_id": "n1"})
        check("mdcg_restore 被删除检查拦截", not rs.get("ok") and rs.get("error") == "tombstoned",
              str(rs))
        rs2 = cli.call("mdcg_restore", {"node_id": "n1", "force": True})
        check("mdcg_restore force 成功", rs2.get("ok"), str(rs2))

        # 7. fix pairs / health / service_info
        print("\n【7】fix pairs / health / service_info")
        fp = cli.call("mdcg_mine_fix_pairs", {"events": [
            {"role": "tool-output", "text": "Traceback (most recent call last):\nModuleNotFoundError: No module named 'bar'"},
            {"role": "assistant", "text": "pip install bar"}]})
        check("mdcg_mine_fix_pairs 产出修复知识", len(fp.get("knowledge_ids", [])) >= 1, str(fp)[:100])
        h = cli.call("mdcg_health")
        check("mdcg_health 返回 OS 指标", "os" in h and "roles" in h["os"], str(h.get("os"))[:100])
        si = cli.call("mdcg_service_info")
        check("mdcg_service_info 返回身份/工具数", si.get("tools") == len(tools), str(si)[:100])

        # 8. 错误处理
        print("\n【8】错误处理")
        bad = cli.call("mdcg_nonexistent_tool", {})
        check("未知工具返回 error 而非崩溃", isinstance(bad, dict) and "error" in bad, str(bad)[:80])
        again = cli.call("mdcg_get", {"node_id": "n1"})
        check("错误后服务仍可用", again is not None, str(again)[:60])

    finally:
        if cli:
            cli.close()
        shutil.rmtree(root, ignore_errors=True)

    print("\n" + "=" * 68)
    print(f"通过 {PASS} / 失败 {FAIL}")
    if FAILS:
        print("失败项：" + ", ".join(FAILS))
    print("=" * 68)
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
