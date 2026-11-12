# -*- coding: utf-8 -*-
"""守卫 · issue #789 B6 的假红形态（端口字面量与时间戳尾数撞车）。

病史：B6 用四位端口字面量对**整份留痕文本**做子串判断（`PORT_B not in raw_log`）。
留痕每行含时间戳浮点 `t` 与毫秒级 trace_id ⇒ 四位数字串会**偶发**出现在这些与内容
无关的字段里 ⇒ 假红（实测 2000 次独立沙箱命中 1 次）。

现行判据（`_log_plaintext_leaked`）：只在**承载正文的字段**里查端口，或整份留痕里查
**正文全文**（长文本，无撞车可能）。本守卫把**两侧**都钉住——
  ① 撞车形态绝不能再假红（旧判据会红、新判据必须绿）；
  ② 真泄漏仍必须被抓（不许因为改判据而放松）。
"""
from __future__ import annotations

import json
import os
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from md_cg.test_b3_merge_keeps_content import _log_plaintext_leaked  # noqa: E402

FAILS = []
PORT = "8080"
BODY = "新值：内网网关改到 7001，回滚窗口 30 分钟（长正文，不会与数字撞车）"


def ok(cond, name, detail=""):
    if cond:
        print("  PASS " + name)
    else:
        print("  FAIL " + name + "  " + str(detail)[:170])
        FAILS.append(name)


def main():
    print("=" * 70)
    print("issue #789：B6 端口撞车假红")
    print("=" * 70)

    # 撞车现场：端口只出现在时间戳/毫秒 id 里，正文与承载字段都不含端口
    row = {"t": 1793965510.8080123, "trace_id": "tr-8080-9f2c",
           "dropped_content": "[redacted sha1=ab12 len=48]"}
    raw = json.dumps([row], ensure_ascii=False)
    ok(PORT in raw, "C1 构造成功：旧判据（整份留痕扫端口）确会假红", PORT)
    ok(_log_plaintext_leaked(raw, [row], BODY, PORT) is False,
       "C2 新判据不再假红（端口只在时间戳/ id 里）", "leaked=True")

    # 真泄漏 ①：正文全文落进留痕（承载字段）
    row_leak = dict(row, dropped_content=BODY)
    ok(_log_plaintext_leaked(json.dumps([row_leak], ensure_ascii=False),
                             [row_leak], BODY, PORT) is True,
       "C3 真泄漏（承载字段含正文）必须被抓")

    # 真泄漏 ②：正文全文出现在整份留痕任意位置
    ok(_log_plaintext_leaked(json.dumps([row], ensure_ascii=False) + BODY,
                             [row], BODY, PORT) is True,
       "C4 真泄漏（正文全文出现在留痕别处）必须被抓")

    # 真泄漏 ③：端口落在承载字段里（最短信号仍有效）
    row_port = dict(row, dropped_content="gateway=%s" % PORT)
    ok(_log_plaintext_leaked(json.dumps([row_port], ensure_ascii=False),
                             [row_port], BODY, PORT) is True,
       "C5 端口出现在承载字段 ⇒ 判泄漏（判据未放松）")

    # 稳定性：2000 个不同时间戳（尾数随机）不得出现一次假红
    bad = 0
    for i in range(2000):
        ts = 1793965510.0 + i * 0.0137
        r2 = {"t": ts, "trace_id": "tr-%d" % (8080000 + i),
              "dropped_content": "[redacted sha1=%04x len=48]" % i}
        if _log_plaintext_leaked(json.dumps([r2], ensure_ascii=False), [r2], BODY, PORT):
            bad += 1
    ok(bad == 0, "C6 2000 个不同时间戳零假红（旧判据命中率约 0.05%）", bad)

    print()
    print("全部通过" if not FAILS else "失败 %d 项" % len(FAILS))
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())