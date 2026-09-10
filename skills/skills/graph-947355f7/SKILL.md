---
name: graph-947355f7
description: >-
  时间窗口 / 图时序-时间窗口 / 时序图查询——时间窗口内 / window 窗。用户提到这些词时使用本技能。
  场景：对照：时序图查询——时间窗口内事件（滑窗过滤）。
  【不适用】Not for 以下场景：op 非 {count, window} 时
license: MIT
compatibility: >-
  op ∈ {count, window}
allowed-tools: Read Write Bash
metadata:
  version: "1.0"
  skill-author: 灵枢（AEIS）
  last-reviewed: "2026-08-29"
  kccs:
    trigger_words: ["时间窗口", "图时序-时间窗口", "时序图查询——时间窗口内", "window 窗"]
    when: "op ∈ {count, window}"
    sub: ["① op 分支处理"]
    execute: "按 op 分派；顺序调用"
    not_applicable: ["op 非 {count, window} 时"]
  calibration: "对照：时序图查询——时间窗口内事件（滑窗过滤）"
---

# 图时序-时间窗口（graph-947355f7）

## When to use

任务「时间窗口」；对照：时序图查询——时间窗口内事件（滑窗过滤）。

## 克制条款（不适用条件）

op 非 {count, window} 时

## How to execute

按 op 分派；顺序调用

## Verification

- 单元样例 3 条（cases 断言）
- 物理基底：按 calibration 对照（编译/运行/断言裁决）

## References

- 单元库：compiler_code_units.py「图时序-时间窗口」
