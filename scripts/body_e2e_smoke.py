#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""body_e2e_smoke —— 0.8.0 灵枢「身体×脑」组合冒烟（身体侧视角 · MCP 全链）。

用途
----
以**身体侧进程的视角**（逐行 JSON-RPC，等价于 lingshu 身体件将来经 MCP 连脑的
真实通路）验证世界模型端到端最小闭环：

    身体侧会话材料 → cg(op=state_event) 记账 → 台账 → 投影 → stg(op=state_chain) 查询

判据（机械）
------------
  ① 握手成功（initialize → serverInfo）；
  ② 写口：`cg(op=state_event)` 对全部输入事件返回 `"ok": true`（计数 == 输入数）；
  ③ 查询：`stg(op=state_chain)` 返回的槽位数与台账主体的预期一致（默认样本=2），
     且每个槽位的 value/state 与输入序列的期望值一致。

安全与纪律
----------
  · **零在役库写入**：root 一律为本次运行新建的临时目录（脚本内断言），跑完按需清理；
  · 事件文件路径由 `--events` 传入（不内嵌任何本机路径字面量）；缺省用**内置合成样本**（3 条）；
  · 子进程环境剔除继承的全部 `MDCG_*` 后只注入隔离 root 与显式开关；
    身份走 legacy 三开关（隔离库测试专用形态），不触任何真实令牌；
  · `MDCG_STG_STATE=1` 显式开（新面默认关纪律）；
  · 退出码 0=全过 / 1=有断言失败（stdout 逐项读数）。

用法
----
  python -X utf8 scripts/body_e2e_smoke.py                    # 内置合成样本
  python -X utf8 scripts/body_e2e_smoke.py --events <事件 jsonl>  # 真实事件序列（仓外）

事件行格式 = 状态事件台账五元（与本仓 `_state_events.jsonl` 同构）：
  {"subject","slot","old","new","kind","seq","evidence"}
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile

#: 内置合成样本（3 条：两个槽位，含迁移与启用；期望读数内嵌于 _expected）。
_SAMPLE = [
    {"subject": "访客", "slot": "位置", "old": None, "new": "门口",
     "kind": "enablement", "seq": 1, "evidence": "场景描述①"},
    {"subject": "访客", "slot": "位置", "old": "门口", "new": "客厅",
     "kind": "migration", "seq": 2, "evidence": "场景描述②"},
    {"subject": "访客", "slot": "情绪", "old": None, "new": "happy",
     "kind": "acquisition", "seq": 3, "evidence": "场景描述③"},
]

#: 内置样本的期望槽位读数（value/state 逐槽断言）。
_EXPECTED = {("访客", "位置"): ("客厅", "active"),
             ("访客", "情绪"): ("happy", "active")}


def _load_events(path):
    recs = [json.loads(l) for l in open(path, encoding="utf-8") if l.strip()]
    return recs


def main() -> int:
    ap = argparse.ArgumentParser(description="灵枢身体×脑组合冒烟（MCP 全链，隔离库）")
    ap.add_argument("--events", default=None,
                    help="事件序列 jsonl（仓外；缺省用内置合成样本）")
    ap.add_argument("--keep-root", action="store_true", help="保留隔离根（调试用）")
    a = ap.parse_args()

    repo = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    events = _load_events(a.events) if a.events else _SAMPLE
    expected = _EXPECTED if a.events is None else None   # 真实序列只断「数=槽位一致 + 全 ok」

    root = tempfile.mkdtemp(prefix="body_e2e_")
    assert root and root.startswith(tempfile.gettempdir()), "隔离根必须是临时目录（fail-closed）"

    env = {k: v for k, v in os.environ.items()}
    for k in list(env):
        if k.startswith("MDCG_"):
            env.pop(k)
    env.update({
        "MDCG_ROOT": root,
        "MDCG_STG_STATE": "1",
        "MDCG_LEGACY_ENV_AUTH": "1",     # 隔离库测试身份（三开关；非真实令牌）
        "MDCG_CAN_ADMIN": "1",
        "MDCG_LEGACY_ENV_ADMIN": "1",
        "PYTHONPATH": repo, "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8",
    })

    p = subprocess.Popen([sys.executable, "-X", "utf8", "-m", "md_cg.mcp_server"],
                         stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                         stderr=subprocess.PIPE, env=env, text=True,
                         encoding="utf-8", errors="replace")
    fails = []

    def rpc(obj):
        p.stdin.write(json.dumps(obj, ensure_ascii=False) + "\n")
        p.stdin.flush()

    def read_result():
        while True:
            line = p.stdout.readline()
            if not line:
                raise RuntimeError("MCP 进程关闭: " + (p.stderr.read() or "")[:400])
            try:
                msg = json.loads(line)
            except ValueError:
                continue
            if isinstance(msg, dict) and ("result" in msg or "error" in msg):
                return msg

    def call(name, args, rid):
        rpc({"jsonrpc": "2.0", "id": rid, "method": "tools/call",
             "params": {"name": name, "arguments": args}})
        return read_result()

    try:
        rpc({"jsonrpc": "2.0", "id": 1, "method": "initialize",
             "params": {"protocolVersion": "2024-11-05", "capabilities": {},
                        "clientInfo": {"name": "body-e2e-smoke", "version": "0.1"}}})
        init = read_result()
        si = init.get("result", {}).get("serverInfo", {})
        print("① 握手:", json.dumps(si, ensure_ascii=False))
        if not si:
            fails.append("握手无 serverInfo")
        rpc({"jsonrpc": "2.0", "method": "notifications/initialized"})

        ok = 0
        first_err = ""
        for i, ev in enumerate(events):
            r = call("cg", {"op": "state_event", "subject": ev.get("subject"),
                            "slot": ev.get("slot"), "old": ev.get("old"),
                            "new": ev.get("new"), "kind": ev.get("kind"),
                            "seq": ev.get("seq"),
                            "evidence": (ev.get("evidence") or "")[:200]}, 100 + i)
            txt = (r.get("result", {}).get("content") or [{}])[0].get("text", "")
            if '"ok": true' in txt:
                ok += 1
            elif not first_err:
                first_err = txt[:300]
        print(f"② 写口（cg(op=state_event) 经 MCP）: {ok}/{len(events)} 条入账"
              + (f"  首错: {first_err}" if first_err else ""))
        if ok != len(events):
            fails.append(f"写口 {ok}/{len(events)}")

        r = call("stg", {"op": "state_chain", "limit": 200, "include_retired": True}, 900)
        txt = (r.get("result", {}).get("content") or [{}])[0].get("text", "")
        out = json.loads(txt)
        items = out.get("items") or []
        print(f"③ 查询（stg(op=state_chain) 经 MCP）: count={out.get('count')} kept={out.get('kept')}")
        for u in items:
            print(f"   {u['subject']}·{u['slot']}: {str(u['value'])[:26]!r} "
                  f"state={u['state']} seq {u['seq_from']}→{u['seq_to']} ev={u['event_count']}")

        if expected is not None:
            got = {(u["subject"], u["slot"]): (u["value"], u["state"]) for u in items}
            if set(got) != set(expected):
                fails.append(f"槽位集合不符: {sorted(got)} != {sorted(expected)}")
            for k, want in expected.items():
                if k in got and got[k] != want:
                    fails.append(f"槽位 {k} 读数 {got[k]} != 期望 {want}")
        else:
            # 真实序列：只断「槽位（subject,slot）去重数 == 台账去重数」——机械自洽
            want_pairs = {(e.get("subject"), e.get("slot")) for e in events}
            got_pairs = {(u["subject"], u["slot"]) for u in items}
            if got_pairs != want_pairs:
                fails.append(f"槽位集合与输入不符: {len(got_pairs)} vs {len(want_pairs)}")
    except Exception as e:  # noqa: BLE001 —— 冒烟工具：异常进读数并判失败
        fails.append(f"异常: {type(e).__name__}: {e}")
    finally:
        try:
            p.stdin.close()
        except Exception:
            pass
        try:
            p.wait(timeout=10)
        except Exception:
            p.terminate()
        if not a.keep_root:
            import shutil
            shutil.rmtree(root, ignore_errors=True)

    print()
    if fails:
        print("VERDICT=FAIL")
        for f in fails:
            print("  -", f)
        return 1
    print("VERDICT=PASS（身体侧 → MCP → 记账 → 台账 → 投影 → 查询 全链贯通）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
