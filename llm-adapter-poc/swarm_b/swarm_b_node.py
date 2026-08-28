# -*- coding: utf-8 -*-
"""swarm_b_node.py · dsh 端 B 节点守护（蜂群 M1 真实接入·B 侧）

依 docs/T12_dsh端接入指南_v0.1.md（主仓库 FuRongJun-1999/CommonTrustProtocol）
实现的最小 B 节点：收件箱轮询 + 能力注册 + 三纪律（盲区诚实/资格先于
执行/产出带基底）。

启动（dsh 端）：
    python swarm_b_node.py --root D:\\swarm_bus --me nodeB
A 侧（ZCode）用 tools/swarm_a_cli.py 对接同一 --root 即可联调。

能力注册：编辑 CAPABILITIES / HANDLERS。默认注册「info」演示能力
（返回 dsh 节点自我介绍），联调验证用。
"""
from __future__ import annotations

import argparse
import json
import os
import time
import uuid

# ---- 能力注册表（dsh 端按需扩展）----
HANDLERS = {
    "info": lambda _in: {"node": "dsh-灵枢", "ts": time.time()},
}


def make_msg(mtype, me, to, payload, reply_to=None):
    m = {"type": mtype, "from": me, "to": to, "id": f"m{uuid.uuid4().hex[:12]}",
         "ts": time.time(), "payload": payload}
    if reply_to:
        m["reply_to"] = reply_to
    return m


def send(root, msg):
    d = os.path.join(root, msg["to"], "inbox")
    os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, msg["id"] + ".json"), "w", encoding="utf-8") as f:
        json.dump(msg, f, ensure_ascii=False)


def inbox(root, me):
    d = os.path.join(root, me, "inbox")
    os.makedirs(d, exist_ok=True)
    out = []
    for name in sorted(os.listdir(d)):
        p = os.path.join(d, name)
        try:
            with open(p, encoding="utf-8") as f:
                out.append(json.load(f))
        except (json.JSONDecodeError, OSError):
            continue  # 半写文件跳过，下轮再读
        os.remove(p)
    out.sort(key=lambda m: m.get("ts", 0))
    return out


def main():
    ap = argparse.ArgumentParser(description="蜂群 B 节点守护（dsh 端）")
    ap.add_argument("--root", required=True, help="总线目录（与 A 侧一致）")
    ap.add_argument("--me", default="nodeB")
    ap.add_argument("--peer", default="nodeA")
    ap.add_argument("--interval", type=float, default=2.0, help="轮询间隔秒")
    args = ap.parse_args()

    caps = sorted(HANDLERS)
    log = []
    print(f"[B 守护] 节点={args.me} 总线={args.root} 能力={caps} 对端={args.peer}")
    send(args.root, make_msg("HELLO", args.me, args.peer, {"capabilities": caps}))
    print("[B 守护] HELLO 已广播，进入轮询…")
    try:
        while True:
            for msg in inbox(args.root, args.me):
                log.append(msg)
                t = msg["type"]
                if t == "CAP_QUERY":
                    cap = msg["payload"]["capability"]
                    verdict = "ACCEPT" if cap in caps else "BLINDSPOT"
                    reason = (f"{args.me} 已注册能力: {cap}" if verdict == "ACCEPT"
                              else f"{args.me} 未注册能力: {cap}（能力边界诚实声明）")
                    send(args.root, make_msg("CAP_REPLY", args.me, msg["from"],
                                             {"verdict": verdict, "reason": reason},
                                             reply_to=msg["id"]))
                    print(f"[B 守护] CAP_QUERY {cap} → {verdict}")
                elif t == "TASK":
                    cap = msg["payload"]["capability"]
                    if cap in HANDLERS:
                        out = HANDLERS[cap](msg["payload"]["input"])
                        send(args.root, make_msg("RESULT", args.me, msg["from"],
                                                 {"output": out,
                                                  "basis": f"dsh 端 {cap} 执行器"},
                                                 reply_to=msg["id"]))
                        print(f"[B 守护] TASK {cap} 执行完成 → RESULT")
                elif t == "VERDICT":
                    if msg["payload"]["pass"]:
                        print(f"[B 守护] VERDICT pass → ADOPTED 登记")
            time.sleep(args.interval)
    except KeyboardInterrupt:
        print(f"[B 守护] 退出（本轮消息 {len(log)} 条）")


if __name__ == "__main__":
    main()
