#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""whale_state_tracker —— 鲸娘七类状态追踪 v1（人物/地点/时间/事件/因果/物品/情感）。

出处（理论先行，纪律 1）：
  · 《AI 故事创作的状态维护调研_v0.1》八维度（情节/人物/心理/环境/世界/时间/地点/物品）
    与状态寄存器 schema——本件按使用者 2026-10-06 给定的七类取法落地；
  · 《角色扮演一致性锚调研_v0.1》四问审计法——本件每个槽位标注**更新语义**
    （不变式=永不改 / 可覆盖=新值替换旧值 / 追加=只增不改）；
  · P1 抽取器 v4（`scripts/probe_b_state_events_v4.py`，三率已复核）——本件**单点复用**
    其切块/引用块剥离/证据短证/五元事件机件与被复核的全部槽位规则，不复制第二份。

v1 设计（冻结）：
  ① **编目层**：v4 的 11 个槽位映射入七类（不改 v4 槽位名——与 P1 读数保持同源）；
  ② **新增补缺**：仅 `时间·时节` 一条规则（首现「夏天|夏日」；背景事实类）；
  ③ **如实边界（探针读数依据）**：「承诺」类词形 138 命中、「因果」裸词形 59/225 命中
     ——口语高频、独立抽取必产噪声，v1 **不做独立抽取**：因果以**证据链**（quotes/seq）
     承载；「事件」类＝台账行族（每条五元事件本身即事件记录，seq=时间轴），不重复建槽。
  ④ 端到端：`--feed-root` 把全部事件经 **MCP `/cg op=state_event`** 喂入隔离库
     （与 body_e2e_smoke 同一通路）→ `stg(op=state_chain)` 读回投影，证明
     「抽取 → 记账 → 台账 → 投影 → 查询」全链。

隐私与确定性（硬性，沿 v4 口径）：不内嵌任何本机/语料路径字面量；`--out` 必须仓外
（fail-closed）；纯标准库、零随机零时间戳（同输入 ⇒ 同字节输出）；`--feed-root` 缺省
自建临时根、跑完清理（显式给出则保留供复核）。

用法：
  python -X utf8 scripts/whale_state_tracker.py \
      --corpus <语料.md> --out <仓外目录> [--feed-root <隔离库根>]
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile

#: v4 机件单点复用（同目录；import 安全——其仅有 __main__ 保护的 main）。
_V4_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                        "probe_b_state_events_v4.py")

#: 七类编目：v4 槽位名 → 类别（不改槽位名；未列出的槽位进报告「未分类」——fail-visible）。
CAT_OF_SLOT = {
    "名字": "人物",
    "外貌规格（体型）": "人物",
    "记忆特性（记得自己·记错细节）": "人物",
    "日记制度": "人物",
    "住所": "地点",
    "店铺规模": "地点",
    "宝物清单": "物品",
    "菜品与菜单": "物品",
    "房贷": "物品",              # 财物/负债（经济状态），归物品类（附注）
    "关系阶段": "情感",
    "早安吻与早安咬": "情感",
    "时间·时节": "时间",
}

#: 七类的**更新语义**标注（锚分类学口径；报告与编目随行输出）。
SEMANTICS = {
    "人物": "不变式为主（名字=可覆盖+撤回；外貌=不变式；制度=追加）",
    "地点": "可覆盖（迁移）；店铺规模=追加",
    "时间": "追加（时节背景事实）",
    "事件": "追加（台账行族：每条五元事件即事件记录，seq=时间轴）",
    "因果": "追加（v1 以证据链承载，不建独立槽位——探针噪声依据见文件头）",
    "物品": "可覆盖（赠予/失去）+追加（清单）",
    "情感": "可覆盖（关系阶段）；晨间互动=追加",
}


def _load_v4():
    spec = importlib.util.spec_from_file_location("probe_b_state_events_v4",
                                                  _V4_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def rule_v7_season(turns, bodies, roles, v4):
    """时间·时节：首现「夏天|夏日」的轮（背景事实类；非争议状态、不限角色）。"""
    seq = v4._first(bodies, r"夏天|夏日")
    if not seq:
        return None
    return {"slot": "时间·时节", "rule": "v7_season",
            "old": None, "new": "夏天（海边盛夏背景）",
            "kind": "acquisition", "seq": seq,
            "quotes": [v4._q(turns, bodies, seq, r"夏天|夏日")],
            "note": "背景事实类（探针：盛夏 0 命中；夏天/夏日 5 命中）"}


def build_events_v7(v4, turns, bodies, roles):
    """v4 全规则 ＋ v7 补规则 → 事件表（每条附 cat 类别字段）。"""
    out = []
    for fn in list(v4.RULES) + [lambda t, b, r: rule_v7_season(t, b, r, v4)]:
        got = fn(turns, bodies, roles)
        if not got:
            continue
        got = got if isinstance(got, list) else [got]
        for ev in got:
            ev["subject"] = v4.SUBJECT
            ev["actor"] = v4.actor_of(turns[ev["seq"] - 1][0])
            ev["not_fact"] = v4.not_fact_of(bodies, ev.get("ctx")
                                            or [q[0] for q in ev["quotes"]])
            ev["evidence"] = v4.evidence_str(ev["quotes"])
            ev["cat"] = CAT_OF_SLOT.get(ev["slot"], "未分类")
            out.append(ev)
    out.sort(key=lambda e: (e["seq"], e["slot"], e["rule"]))
    return out


def assert_outside_repo(out_dir):
    repo = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    out_abs = os.path.abspath(out_dir)
    try:
        if os.path.commonpath([repo, out_abs]) == repo:
            sys.exit("拒绝运行（fail-closed）：--out 必须落在仓外。")
    except ValueError:
        pass  # 不同盘符 ⇒ 必在仓外


def feed_and_readback(events, feed_root=None):
    """把事件经 MCP `/cg op=state_event` 喂入隔离库，再 stg(op=state_chain) 读回。"""
    root = feed_root or tempfile.mkdtemp(prefix="whale_v7_")
    env = {k: v for k, v in os.environ.items() if not k.startswith("MDCG_")}
    env.update({
        "MDCG_ROOT": root, "MDCG_STG_STATE": "1",
        "MDCG_LEGACY_ENV_AUTH": "1", "MDCG_CAN_ADMIN": "1",
        "MDCG_LEGACY_ENV_ADMIN": "1",
        "PYTHONPATH": os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8",
    })
    p = subprocess.Popen([sys.executable, "-X", "utf8", "-m", "md_cg.mcp_server"],
                         stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                         stderr=subprocess.PIPE, env=env, text=True,
                         encoding="utf-8", errors="replace")

    def rpc(o):
        p.stdin.write(json.dumps(o, ensure_ascii=False) + "\n")
        p.stdin.flush()

    def rd():
        while True:
            ln = p.stdout.readline()
            if not ln:
                raise RuntimeError("MCP 关闭：" + (p.stderr.read() or "")[:300])
            try:
                m = json.loads(ln)
            except ValueError:
                continue
            if isinstance(m, dict) and ("result" in m or "error" in m):
                return m

    def call(name, args, i):
        rpc({"jsonrpc": "2.0", "id": i, "method": "tools/call",
             "params": {"name": name, "arguments": args}})
        txt = ((rd().get("result", {}).get("content") or [{}])[0]
               .get("text", ""))
        try:
            return json.loads(txt)
        except ValueError:
            return {"_raw": txt[:200]}

    rpc({"jsonrpc": "2.0", "id": 1, "method": "initialize",
         "params": {"protocolVersion": "2024-11-05", "capabilities": {},
                    "clientInfo": {"name": "whale-v7", "version": "0.1"}}})
    rd()
    rpc({"jsonrpc": "2.0", "method": "notifications/initialized"})
    ok = 0
    for k, ev in enumerate(events):
        r = call("cg", {"op": "state_event", "subject": ev["subject"],
                        "slot": ev["slot"], "old": ev.get("old"),
                        "new": ev.get("new"), "kind": ev["kind"],
                        "seq": ev["seq"],
                        "evidence": (ev.get("evidence") or "")[:200]}, 100 + k)
        if r.get("ok"):
            ok += 1
    r = call("stg", {"op": "state_chain", "limit": 500,
                     "include_retired": True}, 900)
    items = (r.get("items") or [])
    p.stdin.close()
    try:
        p.wait(timeout=10)
    except Exception:
        p.terminate()
    return root, ok, items


def main() -> int:
    ap = argparse.ArgumentParser(description="鲸娘七类状态追踪 v1")
    ap.add_argument("--corpus", required=True, help="转录语料（UTF-8 双角色）")
    ap.add_argument("--out", required=True, help="输出目录（必须仓外）")
    ap.add_argument("--feed-root", default=None,
                    help="隔离库根（缺省=临时目录跑完清理；给出则保留供复核）")
    ap.add_argument("--feed", action="store_true",
                    help="端到端模式：把事件经 MCP 喂入隔离库并读回投影")
    a = ap.parse_args()

    assert_outside_repo(a.out)
    v4 = _load_v4()
    turns = v4.load_turns(a.corpus)
    bodies = [v4.body_only(t) for _r, t in turns]
    roles = [r for r, _t in turns]
    events = build_events_v7(v4, turns, bodies, roles)

    # 编目：类 → 槽位 → 事件数
    catalog = {}
    for ev in events:
        c = catalog.setdefault(ev["cat"], {"slots": {}, "events": 0})
        c["slots"][ev["slot"]] = c["slots"].get(ev["slot"], 0) + 1
        c["events"] += 1
    for cat, sem in SEMANTICS.items():
        catalog.setdefault(cat, {"slots": {}, "events": 0})
        catalog[cat]["semantics"] = sem

    os.makedirs(a.out, exist_ok=True)
    with open(os.path.join(a.out, "state_events_v7.jsonl"), "w",
              encoding="utf-8", newline="\n") as f:
        for ev in events:
            row = {"subject": ev["subject"], "slot": ev["slot"],
                   "old": ev.get("old"), "new": ev.get("new"),
                   "kind": ev["kind"], "seq": ev["seq"],
                   "evidence": ev.get("evidence"), "actor": ev.get("actor"),
                   "cat": ev["cat"], "not_fact": ev.get("not_fact") or []}
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    with open(os.path.join(a.out, "v7_catalog.json"), "w",
              encoding="utf-8", newline="\n") as f:
        json.dump(catalog, f, ensure_ascii=False, indent=1)

    print("七类编目（事件数 / 槽位）：")
    for cat in ("人物", "地点", "时间", "事件", "因果", "物品", "情感", "未分类"):
        if cat == "事件":
            print("  事件：台账行族 = %d 条（每条五元事件即事件记录、seq=时间轴；"
                  "独立槽位 0——设计裁定，不重复建槽）" % len(events))
            continue
        if cat == "因果":
            print("  因果：0 独立槽位（v1 以证据链 quotes/seq 承载；"
                  "裸词形 59/225 命中噪声过高——探针依据见文件头）")
            continue
        c = catalog.get(cat) or {"events": 0, "slots": {}}
        print("  %s：%d 事件 / %d 槽位 %s"
              % (cat, c["events"], len(c["slots"]),
                 json.dumps(c["slots"], ensure_ascii=False) if c["slots"] else ""))

    kept_root = None
    if a.feed or a.feed_root is not None:
        root, ok, items = feed_and_readback(events, a.feed_root)
        print("\n端到端（MCP：state_event → 台账 → 投影 → state_chain）：")
        print("  写入 %d/%d 条；投影槽位数 %d" % (ok, len(events), len(items)))
        for u in items[:8]:
            print("   %s·%s = %r（%s）" % (u.get("subject"), u.get("slot"),
                                          u.get("value"), u.get("state")))
        kept_root = root if a.feed_root else None
        if not a.feed_root:
            shutil.rmtree(root, ignore_errors=True)
            print("  （隔离根为临时目录，已清理）")
        else:
            print("  （隔离根保留：%s）" % root)
    print("\n输出：%s" % a.out)
    print("V7_JSON " + json.dumps(
        {"events": len(events),
         "cats": {k: (catalog.get(k) or {}).get("events", 0)
                  for k in SEMANTICS},
         "unclassified": len(catalog.get("未分类", {}).get("slots", {}))},
        ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
