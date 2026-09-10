# -*- coding: utf-8 -*-
"""令牌与角色权职分离端到端测试（P21）。

验证目标：
  ① fail-closed：无令牌只读、坏令牌拒绝启动
  ② 设计者载体：签发 → 全权（管理 + 保护层 + 核心私有内容）
  ③ 派生收窄：子令牌权限只能更小（层/op/密级/管理权）
  ④ 核心私有内容：非设计者角色写 private 密级 / anchor·self 层被拒
  ⑤ 委派链：子令牌不可再派生；父吊销级联子令牌
  ⑥ op 作用域：只读角色执行 write/review 被拒

运行：python -m md_cg.test_p21_tokens
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import time

from . import tokens
from .mdcos import MdCGSecure
from .security import AccessDenied

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


def denied(fn, *a, **kw):
    """执行 fn，返回 (是否被拒, 错误文本)。"""
    try:
        fn(*a, **kw)
        return False, ""
    except AccessDenied as e:
        return True, str(e)
    except tokens.TokenError as e:
        return True, str(e)


class _Mcp:
    """最小 MCP stdio 客户端（测试用）。"""

    def __init__(self, env):
        self.p = subprocess.Popen(
            [sys.executable, "-m", "md_cg.mcp_server"],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, encoding="utf-8", env=env,
            cwd=os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        self.i = 0
        self.send("initialize", {"protocolVersion": "2024-11-05", "capabilities": {},
                                 "clientInfo": {"name": "p21", "version": "1"}})
        self.send("notifications/initialized", {}, notify=True)

    def send(self, method, params=None, notify=False):
        msg = {"jsonrpc": "2.0", "method": method}
        if params is not None:
            msg["params"] = params
        if not notify:
            self.i += 1
            msg["id"] = self.i
        self.p.stdin.write(json.dumps(msg, ensure_ascii=False) + "\n")
        self.p.stdin.flush()
        if notify:
            return None
        line = self.p.stdout.readline()
        if not line:
            raise RuntimeError("MCP 无响应：" + (self.p.stderr.read() or "")[:400])
        return json.loads(line)

    def call(self, name, args):
        r = self.send("tools/call", {"name": name, "arguments": args})
        if "error" in r:
            return {"error": str(r["error"])}
        return json.loads(r["result"]["content"][0]["text"])

    def __enter__(self):
        return self

    def __exit__(self, *a):
        try:
            self.send("shutdown")
            self.p.wait(timeout=10)
        except Exception:                     # noqa: BLE001
            self.p.kill()


def main():
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    root = tempfile.mkdtemp(prefix="mdcg_p21_")
    tf = os.path.join(root, "_tokens.json")
    kek = os.urandom(32)
    try:
        # ---------------- ① 设计者载体 ----------------
        print("\n[1] 设计者权限载体（外部用户指定）")
        d = tokens.issue("designer", actor="codebuddy-designer",
                         label="设计者载体", path=tf)
        check("签发设计者令牌", d["ok"] and d["token"].startswith("mdcg1.designer."),
              d["token"][:24] + "…")
        dp = tokens.verify_token(d["token"], path=tf)
        check("设计者身份可校验", dp.role == "designer" and dp.can_admin is True,
              f"role={dp.role} admin={dp.can_admin} clearance={dp.clearance}")
        cg = MdCGSecure(os.path.join(root, "cg"), principal=dp, master_key=kek)
        check("设计者可写 anchor 保护层",
              bool(cg.add("n_anchor", "身份锚点：设计者载体", layer="anchor",
                          sensitivity="private")))
        check("设计者可写核心私有内容",
              bool(cg.add("n_priv", "私有核心内容", layer="knowledge",
                          sensitivity="secret")))

        # ---------------- ② 派生收窄 ----------------
        print("\n[2] 派生受限子令牌（子代理权职分离）")
        v = tokens.derive(d["token"], "verifier", actor="codebuddy-verifier",
                          label="验证单元", path=tf)
        check("派生 verifier 子令牌", v["ok"] and v["parent"] == d["token_id"],
              f"parent={v.get('parent')} clamped={v.get('clamped')}")
        vp = tokens.verify_token(v["token"], path=tf)
        check("子令牌权限已收窄",
              vp.can_admin is False and vp.clearance == "internal"
              and set(vp.layers_allow or []) <= {"rejected", "contextual"},
              f"layers={vp.layers_allow} clearance={vp.clearance}")
        vcg = MdCGSecure(os.path.join(root, "cg"), principal=vp, master_key=kek)

        ok, why = denied(vcg.add, "n_bad", "越权写事实层", layer="knowledge")
        check("验证单元写 knowledge 层被拒", ok, why[:70])
        ok, why = denied(vcg.add, "n_self", "越权写自我层", layer="self")
        check("验证单元写 self 层被拒", ok, why[:70])
        ok, why = denied(vcg.add, "n_p", "越权私有", layer="rejected",
                         sensitivity="private")
        check("验证单元写 private 密级被拒（核心私有内容）", ok, why[:70])
        check("验证单元可写 rejected 层（职责内）",
              bool(vcg.add_rejected("假设X", "被实测证伪", sensitivity="internal")))
        ok, why = denied(vcg.review_decide, "prop_x", "accept", reason="自证")
        check("验证单元无审核裁决权", ok, why[:70])

        ok, why = denied(tokens.derive, v["token"], "recorder", path=tf)
        check("子令牌不可再派生（委派链封口）", ok, why[:70])
        ok, why = denied(tokens.verify_token, d["token"][:-4] + "dead", path=tf)
        check("篡改令牌密钥被拒", ok, why[:70])

        # ---------------- ③ 其他角色职责 ----------------
        print("\n[3] 各单元职责边界")
        r = tokens.issue("recorder", actor="recorder", path=tf)
        rp = tokens.verify_token(r["token"], path=tf)
        rcg = MdCGSecure(os.path.join(root, "cg"), principal=rp, master_key=kek)
        check("记录单元可写 knowledge 层",
              bool(rcg.add("n_k", "事实条目", layer="knowledge")))
        ok, why = denied(rcg.add, "n_a", "越权", layer="anchor")
        check("记录单元写 anchor 层被拒", ok, why[:70])

        o = tokens.issue("output", actor="viewer", path=tf)
        op_ = tokens.verify_token(o["token"], path=tf)
        ocg = MdCGSecure(os.path.join(root, "cg"), principal=op_, master_key=kek)
        ok, why = denied(ocg.add, "n_o", "只读角色写入")
        check("输出单元写入被拒", ok, why[:70])
        ok, why = denied(op_.require_op, "write")
        check("输出单元执行 write op 被拒", ok, why[:70])
        check("输出单元可读", ocg.get("n_k") is not None)

        g = tokens.issue("guest", actor="anon", path=tf)
        gp = tokens.verify_token(g["token"], path=tf)
        check("访客只读且不可管理",
              gp.can_write is False and gp.can_admin is False
              and gp.clearance == "internal")

        # ---------------- ④ 过期 / 吊销 / 级联 ----------------
        print("\n[4] 生命周期")
        e = tokens.issue("recorder", actor="tmp", ttl=0.05, path=tf)
        time.sleep(0.12)
        ok, why = denied(tokens.verify_token, e["token"], path=tf)
        check("过期令牌被拒", ok, why[:70])

        tokens.revoke(d["token_id"], path=tf)
        ok1, _ = denied(tokens.verify_token, d["token"], path=tf)
        ok2, _ = denied(tokens.verify_token, v["token"], path=tf)
        check("吊销父令牌级联失效子令牌", ok1 and ok2,
              "父与子均不可用")
        check("清单默认不含已吊销",
              all(t["token_id"] != d["token_id"] for t in tokens.list_tokens(path=tf)))

        # ---------------- ⑤ 与 identity 五大单元同源（防漂移） ----------------
        print("\n[5] 与 identity.POSITIONS 同源校验")
        from .identity import POSITIONS
        drift = []
        for pos, meta in POSITIONS.items():
            spec = tokens.ROLE_SPECS.get(pos)
            if not spec:
                drift.append(f"缺角色 {pos}")
            elif spec["unit"] != meta["unit"] or meta["duty"] not in spec["duty"]:
                drift.append(f"{pos}: unit/duty 与 identity 不一致")
        check("五大单元命名与职责与 identity 同源", not drift,
              "；".join(drift) or "/".join(tokens.POSITION_ROLES))
        check("别名解析可用",
              tokens.role_spec("verifier")["label"] == "验证单元"
              and tokens.role_spec("recorder")["unit"] == "记录单元"
              and tokens.role_spec("reflection")["effect"] == "新")

        # ---------------- ⑥ MCP 进程层：fail-closed 与作用域闸门 ----------------
        print("\n[6] MCP 进程层（令牌优先 / fail-closed）")
        env = dict(os.environ)
        env.update({"MDCG_ROOT": os.path.join(root, "mcp"), "MDCG_TOKEN_FILE": tf,
                    "MDCG_SUSTAIN": "0", "PYTHONIOENCODING": "utf-8"})
        for k in ("MDCG_TOKEN", "MDCG_LEGACY_ENV_AUTH", "MDCG_CAN_ADMIN",
                  "MDCG_CAN_WRITE", "MDCG_CLEARANCE", "MDCG_ACTOR"):
            env.pop(k, None)

        bad = dict(env)
        bad["MDCG_TOKEN"] = "mdcg1.designer.tk_zzzzzz.bad-secret"
        rc = subprocess.run([sys.executable, "-m", "md_cg.mcp_server"], env=bad,
                            capture_output=True, text=True, encoding="utf-8",
                            timeout=90)
        check("坏令牌拒绝启动（fail-closed，退出码 3）", rc.returncode == 3,
              ((rc.stderr or "").strip().splitlines() or [""])[0][:80])

        d2 = tokens.issue("designer", actor="mcp-designer", path=tf)
        v2 = tokens.derive(d2["token"], "verifier", actor="mcp-verify", path=tf)
        venv = dict(env)
        venv["MDCG_TOKEN"] = v2["token"]
        with _Mcp(venv) as m:
            who = m.call("cg", {"op": "info"}).get("whoami", {}).get("principal", {})
            check("令牌身份注入进程", who.get("role") == "verify"
                  and who.get("auth_mode") == "token",
                  f"role={who.get('role')} admin={who.get('can_admin')}")
            r = m.call("cg", {"op": "write", "node_id": "mcp_k", "content": "越权事实",
                              "layer": "knowledge"})
            check("验证单元经 MCP 写事实层被拒", "error" in r, str(r.get("error"))[:70])
            r = m.call("cg", {"op": "review", "action": "list"})
            check("验证单元经 MCP 调用 review op 被拒", "error" in r,
                  str(r.get("error"))[:70])
            r = m.call("cg", {"op": "write", "node_id": "mcp_rej", "content": "证伪记录",
                              "layer": "rejected"})
            check("验证单元经 MCP 写 rejected 层放行", r.get("ok") is True
                  or r.get("id"), str(r)[:70])

        aenv = dict(env)
        aenv["MDCG_TOKEN"] = d2["token"]
        with _Mcp(aenv) as m:
            who = m.call("cg", {"op": "info"}).get("whoami", {}).get("principal", {})
            check("设计者令牌经 MCP 获得管理权",
                  who.get("role") == "designer" and who.get("can_admin") is True,
                  f"role={who.get('role')} admin={who.get('can_admin')}")
            r = m.call("cg", {"op": "write", "node_id": "mcp_priv",
                              "content": "核心私有内容", "layer": "knowledge",
                              "sensitivity": "secret"})
            check("设计者可经 MCP 写核心私有内容", r.get("ok") is True or r.get("id"),
                  str(r)[:70])
    finally:
        shutil.rmtree(root, ignore_errors=True)

    print(f"\n通过 {PASS} / 失败 {FAIL}")
    if FAILS:
        print("失败项：" + "，".join(FAILS))
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
