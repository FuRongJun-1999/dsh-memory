# -*- coding: utf-8 -*-
"""守卫 · issue #1033：结构标签不得被当成断言键（scrub 误判 demote 的根因）。

病灶：`_kv_pairs()` 用 `partition("：")` 从正文抽「键：值」对，把 Markdown 小节标题、
编号列表、口语短句也切成了「键」。于是任意两篇无关文档的「任务：xxx」天然取值不同，
`_contradiction` 判「同键不同值」→ weaken + demote + 跨层移动（用户实测 16 节点受害）。

本守卫钉住：
  1. 结构标签（小节词/编号前缀/口语量词）不产生键；
  2. 带空白、引号、路径符、`@` 的键不产生键；
  3. URL 值（`//`）不产生键；
  4. **真字段仍能抽出**（判据宁窄勿宽，不许把「端口：8080」也拦掉）。
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from md_cg.scrub import _kv_pairs  # noqa: E402

PASSED, FAILED = [], []


def ok(cond, name, detail=""):
    print(("  PASS " if cond else "  FAIL ") + name + ("" if cond else "  " + str(detail)[:160]))
    (PASSED if cond else FAILED).append(name)
    return bool(cond)


def main():
    # —— 结构标签：一律不产生键 ——
    ok(_kv_pairs("# 计划\n任务：让 scrub 只抓真矛盾\n") == {},
       "S1 Markdown 小节标题（任务：）不产生键")
    ok(_kv_pairs("1. 连通性探测：node index.js\n") == {},
       "S2 编号列表（1. xxx：）不产生键")
    ok(_kv_pairs("（2）补充说明：先做\n") == {},
       "S3 括号编号（（2）xxx：）不产生键")
    ok(_kv_pairs("三、结论：先上线\n") == {},
       "S4 中文序号（三、）不产生键")
    ok(_kv_pairs("任务就一条：别改排序\n") == {},
       "S5 口语量词（一条/一句）不产生键")
    ok(_kv_pairs("https://example.com/a\n") == {},
       "S6 URL（https 被切成键 + // 值）不产生键")
    ok(_kv_pairs("- 提案：x\n") == {},
       "S7 列表项前缀行不产生键（既有 #665 判据仍生效）")

    # —— 真字段：必须仍抽得出（防过度过滤）——
    got = _kv_pairs("端口：8080\n数据根：D:/mem\n")
    ok(got == {"端口": "8080", "数据根": "D:/mem"},
       "S8 真字段（端口/数据根）照常抽出，不误伤", got)
    got2 = _kv_pairs("不适用条件：windows\n")
    ok(got2 == {},
       "S9 CCG 六要素行仍被 is_ccg_mark 拦（既有判据不变）", got2)

    # —— issue #1033 后续：whitebox_kb 代码节点的定位/索引元数据（全库扫描 99.8% 误伤源）——
    ok(_kv_pairs("位置：whitebox_kb/wisdom/x.py:684\n") == {},
       "S11 「位置」（源码行号）不产生键——2563 个 demoted 节点 100% 由它引起")
    ok(_kv_pairs("索引元条件：载体/位置：本地源码仓；时间：全时窗\n") == {},
       "S12 「索引元条件」不产生键")
    ok(_kv_pairs("子节：一、投影声明；二、核心声明\n") == {},
       "S13 「子节」（小节目录）不产生键")

    # —— 回归：两篇无关文档不再「同键不同值」——
    a = _kv_pairs("# 计划\n任务：让 scrub 只抓真矛盾\n\n1. 连通性探测：node index.js\n")
    b = _kv_pairs("# 复盘\n任务：修好本轮的误报\n\n1. 连通性探测：curl api.github.com\n")
    shared = set(a) & set(b)
    ok(not shared, "S10 两篇无关文档的键集不再相交（issue 给的原复现）", shared)

    print()
    print("结构标签判据：%d 通过 / %d 失败" % (len(PASSED), len(FAILED)))
    return 0 if not FAILED else 1


if __name__ == "__main__":
    sys.exit(main())