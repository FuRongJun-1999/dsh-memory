# -*- coding: utf-8 -*-
"""#789 守卫：留痕明文探针不许被时间戳尾数撞出假红。

缺陷（修复前，实测于 main 3619402b）
------------------------------------
`md_cg/test_b3_merge_keeps_content.py` 的 B6 断言：
    `PORT_B not in raw_log`            # PORT_B = "9595"（四位端口字面量）
raw_log 是**整份** `_forgetting.jsonl` 文本，其每行都带时间戳浮点
`"t":1793965510.1209595` 与毫秒级 trace_id ⇒ 四位数字串会偶发出现在**与内容无关**
的字段里，把「加密级 DROP 明文不落留痕」这条正确行为判成红。

复现读数（本机，2026-11-06，main 3619402b，2000 次独立沙箱）：
    HIT run=1401 verdict=DROP kept=False
      {"t":1793965510.1209595,...}     ← 命中字段是 t，不是任何正文
    SUMMARY runs=2000 hits=1 rate=0.050%
CI 里全量套件跑久了必然碰上（issue #789 的 CI red）。

修法（不是放宽）
----------------
明文判据改为 `_log_plaintext_leaked(raw, rows, body, port)`：
  ① 只看**承载正文的字段**（dropped_content / content / text / preview）里是否出现端口或正文；
  ② 整份留痕里查**正文全文**（长文本，无撞车可能）。
端口号仍然查，只是不再拿它去扫时间戳——判据比原来**更准**，不是更松。

本守卫的判别力
--------------
· `t1` 复刻 CI 撞车行（t 尾数含 9595、dropped_content=null）⇒ 新判据必须判「未泄露」；
· `t2` 同一条用**旧判据**（`port in raw_log`）⇒ 必须判「泄露」（证明旧判据假红）；
· `t3` 真泄露（dropped_content 里带端口）⇒ 新判据必须判「泄露」（没被修宽）；
· `t4` 整份留痕泄漏正文全文、但行字段已清空 ⇒ 仍判「泄露」（旁路也堵）。

运行：python -X utf8 -m md_cg.test_issue789_log_plaintext_probe
"""
from __future__ import annotations

import json
import sys

from .test_b3_merge_keeps_content import _log_plaintext_leaked

PASS = 0
FAIL = 0
FAILS = []

PORT = "9595"
BODY = ("部署说明：生产库端口 9595，回滚窗口 30 分钟；灰度先放 5% 流量，"
        "观察 P99 与错误率。")


def ok(cond, label):
    global PASS, FAIL
    if cond:
        PASS += 1
        print("  ok   %s" % label)
    else:
        FAIL += 1
        FAILS.append(label)
        print("  FAIL %s" % label)


def _raw(row):
    return json.dumps(row, ensure_ascii=False) + "\n"


def main():
    # t1：复刻 CI 撞车（t 的尾数含 9595，正文已脱敏）
    collide = {"t": 1793965510.1209595, "node_id": "s_second", "verdict": "DROP",
               "trace_id": "drop-s_second-1793965510921", "content_chars": 27,
               "dropped_content": None, "content_kept": False}
    raw = _raw(collide)
    ok(not _log_plaintext_leaked(raw, [collide], BODY, PORT),
       "t1时间戳尾数含 %r 但正文已脱敏 ⇒ 判「未泄露」（旧写法在这里假红）" % PORT)

    # t2：同一条用旧判据必须假红（判别力证据）
    ok(PORT in raw,
       "t2旧判据 `port in raw_log` 对同一条判「泄露」＝假红（本守卫要拦的正是它）")

    # t3：真泄露（承载字段里带端口）⇒ 必须判泄露
    leaked_row = dict(collide, dropped_content="端口 " + PORT + " 全文落盘")
    ok(_log_plaintext_leaked(_raw(leaked_row), [leaked_row], BODY, PORT),
       "t3承载字段里带 %r ⇒ 判「泄露」（修法没把断言改宽）" % PORT)

    # t4：行字段已清空、但整份留痕别处含正文全文 ⇒ 仍判泄露（旁路也堵）
    other = {"t": 1.0, "note": BODY}
    ok(_log_plaintext_leaked(_raw(other), [collide], BODY, PORT),
       "t4整份留痕别处含正文全文 ⇒ 仍判「泄露」（旁路未被放过）")

    print("\nPASS=%d FAIL=%d" % (PASS, FAIL))
    if FAIL:
        print("FAILS:\n  " + "\n  ".join(FAILS))
    return 1 if FAIL else 0


def test_issue789_log_plaintext_probe():
    rc = main()
    assert rc == 0, "%d 条断言失败" % FAIL


if __name__ == "__main__":
    sys.exit(main())
