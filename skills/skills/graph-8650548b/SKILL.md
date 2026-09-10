---
name: graph-8650548b
description: >-
  审计记录 / 图安全-审计日志 / 图安全——审计日志 / 审计日志 / record 记。用户提到这些词时使用本技能。
  场景：对照：图安全——审计日志（操作记录/用户过滤）。
  【不适用】Not for 以下场景：op 非 {count, filter, record} 时
license: MIT
compatibility: >-
  op ∈ {count, filter, record}
allowed-tools: Read Write Bash
metadata:
  version: "1.0"
  skill-author: 灵枢（AEIS）
  last-reviewed: "2026-08-29"
  kccs:
    trigger_words: ["审计记录", "图安全-审计日志", "图安全——审计日志", "审计日志", "record 记"]
    when: "op ∈ {count, filter, record}"
    sub: ["① op 分支处理"]
    execute: "按 op 分派；顺序调用"
    not_applicable: ["op 非 {count, filter, record} 时"]
  calibration: "对照：图安全——审计日志（操作记录/用户过滤）"
---

# 图安全-审计日志（graph-8650548b）

## When to use

任务「审计记录」；对照：图安全——审计日志（操作记录/用户过滤）。

## 克制条款（不适用条件）

op 非 {count, filter, record} 时

## How to execute

按 op 分派；顺序调用

## Verification

- 单元样例 3 条（cases 断言）
- 物理基底：按 calibration 对照（编译/运行/断言裁决）

## References

- 单元库：compiler_code_units.py「图安全-审计日志」
