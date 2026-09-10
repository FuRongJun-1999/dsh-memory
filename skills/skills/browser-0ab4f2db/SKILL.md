---
name: browser-0ab4f2db
description: >-
  网络记录 / 浏览器-网络记录 / 开发者工具 / record 记。用户提到这些词时使用本技能。
  场景：对照：开发者工具网络面板——请求记录/过滤/汇总。
  【不适用】Not for 以下场景：op 非 {filter, record, stats} 时
license: MIT
compatibility: >-
  op ∈ {filter, record, stats}
allowed-tools: Read Write Bash
metadata:
  version: "1.0"
  skill-author: 灵枢（AEIS）
  last-reviewed: "2026-08-29"
  kccs:
    trigger_words: ["网络记录", "浏览器-网络记录", "开发者工具", "record 记"]
    when: "op ∈ {filter, record, stats}"
    sub: ["① op 分支处理"]
    execute: "按 op 分派；顺序调用"
    not_applicable: ["op 非 {filter, record, stats} 时"]
  calibration: "对照：开发者工具网络面板——请求记录/过滤/汇总"
---

# 浏览器-网络记录（browser-0ab4f2db）

## When to use

任务「网络记录」；对照：开发者工具网络面板——请求记录/过滤/汇总。

## 克制条款（不适用条件）

op 非 {filter, record, stats} 时

## How to execute

按 op 分派；顺序调用

## Verification

- 单元样例 3 条（cases 断言）
- 物理基底：按 calibration 对照（编译/运行/断言裁决）

## References

- 单元库：compiler_code_units.py「浏览器-网络记录」
