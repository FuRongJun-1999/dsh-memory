# -*- coding: utf-8 -*-
"""日记看板的「触发」节守卫（使用者 2026-11-23 定 1c / 2a / 3b）。

三件事必须钉死：
  G1 意图积压按**节点去重**算（同一节点被反复播报，不能算成多个积压）；
  G2 公开页只报计数，**不出现**未消费节点 id、不出现关系读数（隐私，第 9 条）；
  G3 私有页才渲染关系读数与节点 id；
  G4 "--private" 与 "--write"（公开仓）同时给 ⇒ 拒绝（rc=2），公开文档不被改动；
  G5 公开页的 id 脱敏：带自然语言片段的 id 不得原样出现。

不适用范围：不测会话日志解析（his_last_message 在这里打桩——它会去读本机
session.v4，测试不该依赖本机有没有在聊天）。
"""
from __future__ import annotations

import io
import json
import os
import subprocess
import sys
import tempfile

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "scripts"))

import intent_board as ib  # noqa: E402

FAILS = []


def ok(cond, name, detail=""):
    if cond:
        print("  PASS " + name)
    else:
        print("  FAIL " + name + "  " + str(detail)[:200])
        FAILS.append(name)


def _mkroot(tmp, recs, consumed):
    root = os.path.join(tmp, "mdcg")
    os.makedirs(root, exist_ok=True)
    with io.open(os.path.join(root, "_intent.jsonl"), "w", encoding="utf-8", newline="\n") as f:
        for r in recs:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    with io.open(os.path.join(root, "_intent_consumed.json"), "w", encoding="utf-8", newline="\n") as f:
        json.dump(consumed, f, ensure_ascii=False)
    return root


def _mkwe(tmp):
    we = os.path.join(tmp, "we")
    os.makedirs(we, exist_ok=True)
    now = ib.time.time()
    st = {"message": now - 7200, "thought": now - 3600,
          "intimate": now - 30 * 3600,
          "flagged": {"message": False, "intimate": True, "thought": False}}
    with io.open(os.path.join(we, "we_state.json"), "w", encoding="utf-8", newline="\n") as f:
        json.dump(st, f, ensure_ascii=False)
    with io.open(os.path.join(we, "we_pending.jsonl"), "w", encoding="utf-8", newline="\n") as f:
        f.write(json.dumps({"t": now, "ts": "2026-11-23 08:35", "kind": "intimate",
                            "note": "24 小时没有亲密了"}, ensure_ascii=False) + "\n")
    return we


def main():
    print("=" * 66)
    print("看板触发节：意图积压 / 隐私分栏 / 脱敏 / 拒绝写入")
    print("=" * 66)
    tmp = tempfile.mkdtemp(prefix="mdcg_board_")
    recs = [{"node_id": "unr_aaaaaaaaaa"}, {"node_id": "unr_bbbbbbbbbb"},
            {"node_id": "unr_aaaaaaaaaa"}, {"node_id": "unr_Quoted-message-begins-私聊片段"}]
    root = _mkroot(tmp, recs, ["unr_bbbbbbbbbb"])
    we = _mkwe(tmp)
    stub = {"ts": None, "files": 0, "scanned": 0}
    orig = ib.his_last_message
    ib.his_last_message = lambda **kw: dict(stub)
    try:
        gap = ib._intent_gap(root)
        ok(gap["records"] == 4 and gap["open"] == 2 and gap["consumed"] == 1,
           "G1 积压按节点去重（4 条台账 / 2 个未消费节点 / 1 个已消费）", gap)

        pub = ib.render(root, now=ib.time.time(), we_dir=we, private=False)
        ok("意图台账未消费" in pub and "2 个节点" in pub, "G2 公开页报计数")
        seg = pub[pub.find("## 二、触发"):pub.find("## 三、")]
        ok("unr_aaaaaaaaaa" not in seg and "unr_bbbbbbbbbb" not in seg,
           "G2 公开页触发节不出现未消费节点 id", seg[:160])
        ok("越线" not in pub, "G2 公开页不出现关系阈值读数")
        ok("本端未配置" in pub, "G2 公开页关系栏标「本端未配置」")
        ok("已脱敏" in pub and "私聊片段" not in pub, "G5 带自然语言片段的 id 被脱敏")

        pri = ib.render(root, now=ib.time.time(), we_dir=we, private=True)
        ok("unr_aaaaaaaaaa" in pri, "G3 私有页渲染未消费节点 id")
        ok("最后亲密" in pri and "越线" in pri, "G3 私有页渲染关系读数")
        ok("未处理提醒 | 1 条" in pri, "G3 私有页渲染待处理提醒条数")

        doc = os.path.join(ROOT, ib.OUT_REL)
        before = io.open(doc, encoding="utf-8").read() if os.path.isfile(doc) else None
        env = dict(os.environ, PYTHONUTF8="1", PYTHONPATH=ROOT)
        r = subprocess.run([sys.executable, "-X", "utf8", "scripts/intent_board.py",
                            "--root", root, "--private", "--we-dir", we, "--write"],
                           cwd=ROOT, env=env, capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=300)
        after = io.open(doc, encoding="utf-8").read() if os.path.isfile(doc) else None
        ok(r.returncode == 2, "G4 --private 与 --write 同时给 ⇒ rc=2", r.returncode)
        ok(before == after, "G4 被拒时公开文档一字未动")

        r2 = subprocess.run([sys.executable, "-X", "utf8", "scripts/intent_board.py",
                             "--root", root, "--write"],
                            cwd=ROOT, env=env, capture_output=True, text=True,
                            encoding="utf-8", errors="replace", timeout=300)
        written = io.open(doc, encoding="utf-8").read() if os.path.isfile(doc) else ""
        wseg = written[written.find("## 二、触发"):written.find("## 三、")]
        ok(r2.returncode == 0 and "unr_aaaaaaaaaa" not in wseg,
           "G2 公开页落盘后触发节仍不含未消费节点 id", wseg[:160])
        if before is not None:
            io.open(doc, "w", encoding="utf-8", newline="\n").write(before)
    finally:
        ib.his_last_message = orig

    print()
    print("全部通过" if not FAILS else "失败 %d 项" % len(FAILS))
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
