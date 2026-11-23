# -*- coding: utf-8 -*-
"""日记看板的「触发」节守卫（使用者 2026-11-23 定 1c / 2a / 3b）。

钉住的东西：
  G1 意图积压按**节点去重**算，台账坏行不崩；
  G2 公开页只报计数：触发节不出现未消费 id、不出现关系读数；
  G3 私有页才渲染关系读数、待处理提醒、未消费 id；
  G4 --private 与 --write 同时给 ⇒ rc=2，目标文件一字未动；
  G5 公开页 id 脱敏：带自然语言片段的 id 不得原样出现（待办推进 / 日记目录同判据）；
  G6 --write-private 指向仓内 ⇒ rc=2（含 Windows 大小写变体）；
  G7 关系状态坏值（顶层非 dict / 行非 dict / 时间值非数值）不抛栈；
  G8 会话文件里找不到 zstd 帧头 ⇒ None（读不到），不是空列表（没有消息）；
  G9 公开页的待办推进**保留**哈希形态 id（防止过度脱敏）。

本测试**不写真实工作区**：公开页落盘走 --out 临时目录。
不测真实会话日志解析（his_last_message 打桩）。
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


def _mkwe(tmp, state=None, ts_value=None):
    we = os.path.join(tmp, "we")
    os.makedirs(we, exist_ok=True)
    now = ib.time.time()
    st = state if state is not None else {
        "message": ts_value if ts_value is not None else now - 7200,
        "thought": now - 3600, "intimate": now - 30 * 3600,
        "flagged": {"message": False, "intimate": True, "thought": False}}
    with io.open(os.path.join(we, "we_state.json"), "w", encoding="utf-8", newline="\n") as f:
        json.dump(st, f, ensure_ascii=False)
    with io.open(os.path.join(we, "we_pending.jsonl"), "w", encoding="utf-8", newline="\n") as f:
        f.write(json.dumps({"t": now, "ts": "2026-11-23 08:35", "kind": "intimate",
                            "note": "24 小时没有亲密了"}, ensure_ascii=False) + "\n")
        f.write(json.dumps("这不是 dict", ensure_ascii=False) + "\n")
    return we


def _run(args, timeout=300):
    env = dict(os.environ, PYTHONUTF8="1", PYTHONPATH=ROOT)
    return subprocess.run([sys.executable, "-X", "utf8", "scripts/intent_board.py"] + args,
                          cwd=ROOT, env=env, capture_output=True, text=True,
                          encoding="utf-8", errors="replace", timeout=timeout)


def main():
    print("=" * 66)
    print("看板触发节：意图积压 / 隐私分栏 / 脱敏 / 拒绝写入 / 坏数据")
    print("=" * 66)
    tmp = tempfile.mkdtemp(prefix="mdcg_board_")
    recs = [{"node_id": "unr_aaaaaaaaaa"}, {"node_id": "unr_bbbbbbbbbb"},
            {"node_id": "unr_aaaaaaaaaa"}, {"node_id": "unr_Quoted-message-begins-私聊片段"},
            "这不是 dict"]
    root = _mkroot(tmp, recs, ["unr_bbbbbbbbbb"])
    we = _mkwe(tmp)
    stub = {"ts": None, "files": 0, "scanned": 0}
    orig_msg, orig_diary = ib.his_last_message, ib._diary
    ib.his_last_message = lambda **kw: dict(stub)
    ib._diary = lambda root_, limit=40: [{"id": "unr_Quoted-diary-私聊片段", "date": "d", "head": "h"}]
    try:
        gap = ib._intent_gap(root)
        ok(gap["records"] == 5 and gap["open"] == 2 and gap["consumed"] == 1,
           "G1 积压按节点去重且坏行不计（5 行台账 / 2 个未消费节点 / 1 个已消费）", gap)

        pub = ib.render(root, now=ib.time.time(), we_dir=we, private=False)
        seg = pub[pub.find("## 二、触发"):pub.find("## 三、")]
        ok("意图台账未消费" in seg and "2 个节点" in seg, "G2 公开页触发节报计数")
        ok("unr_aaaaaaaaaa" not in seg and "unr_bbbbbbbbbb" not in seg,
           "G2 公开页触发节不出现未消费节点 id", seg[:120])
        ok("越线" not in pub and "未处理提醒" not in seg, "G2 公开页不出现关系读数")
        ok("本端未配置" in seg, "G2 公开页关系栏标「本端未配置」")
        ok("已脱敏" in pub and "私聊片段" not in pub,
           "G5 带自然语言片段的 id 被脱敏（待办推进 + 日记目录两处）")
        ok("unr_aaaaaaaaaa" in pub[pub.find("## 四、待办推进"):pub.find("## 五、")],
           "G9 哈希形态 id 在公开页待办推进里保留")

        pri = ib.render(root, now=ib.time.time(), we_dir=we, private=True)
        ok("unr_aaaaaaaaaa" in pri, "G3 私有页渲染未消费节点 id")
        ok("最后亲密" in pri and "越线" in pri, "G3 私有页渲染关系读数")
        ok("未处理提醒 | 1 条" in pri, "G3 私有页把非 dict 行滤掉后报 1 条")
        ok("unr_Quoted-diary-私聊片段" in pri, "G3 私有页日记 id 原样")

        bad = _mkwe(tmp + "_bad", state=["不是 dict"])
        pri2 = ib.render(root, now=ib.time.time(), we_dir=bad, private=True)
        ok("最后亲密 | 未知" in pri2, "G7 关系状态顶层非 dict 时不抛栈，报未知")

        weird = _mkwe(tmp + "_weird", state={"intimate": ["x"], "thought": {"a": 1}})
        pri3 = ib.render(root, now=ib.time.time(), we_dir=weird, private=True)
        ok("最后亲密 | 未知" in pri3, "G7 关系读数时间值非数值时不抛栈")

        junk = os.path.join(tmp, "junk.bin")
        with io.open(junk, "wb") as f:
            f.write(b"not-a-zstd-frame" * 10)
        if ib._tail_message_times.__doc__ is None:
            ok(False, "G8 会话帧头逻辑（zstandard 缺失或函数被替换）")
        else:
            try:
                import zstandard  # noqa: F401
                ok(ib._tail_message_times(junk) is None,
                   "G8 无帧头 ⇒ None（读不到，不是没有消息）")
            except ImportError:
                print("  SKIP G8 本机无 zstandard（CI 装了才有意义）")

        outdir = os.path.join(tmp, "out")
        os.makedirs(outdir, exist_ok=True)
        target = os.path.join(outdir, "board.md")
        r = _run(["--root", root, "--private", "--we-dir", we, "--write", "--out", target])
        ok(r.returncode == 2 and not os.path.isfile(target),
           "G4 --private 与 --write 同时给 ⇒ rc=2 且目标未生成", r.returncode)

        real_doc = os.path.join(ROOT, ib.OUT_REL)
        before_doc = io.open(real_doc, encoding="utf-8").read() if os.path.isfile(real_doc) else None
        r5 = _run(["--root", root, "--we-dir", we, "--write-private", real_doc])
        after_doc = io.open(real_doc, encoding="utf-8").read() if os.path.isfile(real_doc) else None
        ok(r5.returncode == 2 and after_doc == before_doc,
           "G6 --write-private 指向仓内 ⇒ rc=2 且公开文档未改", (r5.returncode, (r5.stdout or "")[:80]))
        repo_upper = os.path.join(ROOT, ib.OUT_REL).upper()
        r6 = _run(["--root", root, "--we-dir", we, "--write-private", repo_upper])
        ok(r6.returncode == 2, "G6 Windows 大小写变体同样被拒", (r6.returncode, (r6.stdout or "")[:80]))

        r2 = _run(["--root", root, "--write", "--out", target])
        written = io.open(target, encoding="utf-8").read() if os.path.isfile(target) else ""
        wseg = written[written.find("## 二、触发"):written.find("## 三、")]
        ok(r2.returncode == 0 and "unr_aaaaaaaaaa" not in wseg,
           "G2 公开页落盘后触发节仍不含未消费节点 id")
        ok("unr_aaaaaaaaaa" in written[written.find("## 四、待办推进"):written.find("## 五、")],
           "G9 落盘后待办推进仍保留哈希 id")
        doc_now = io.open(os.path.join(ROOT, ib.OUT_REL), encoding="utf-8").read() if os.path.isfile(
            os.path.join(ROOT, ib.OUT_REL)) else ""
        ok("unr_Quoted-diary-私聊片段" not in doc_now, "全流程不写真实公开文档")
    finally:
        ib.his_last_message, ib._diary = orig_msg, orig_diary

    print()
    print("全部通过" if not FAILS else "失败 %d 项" % len(FAILS))
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
