---
name: pylang-e1aa3818
description: >-
  数值舍入 / 工具-数值舍入 / floor / ceil / round 四。用户提到这些词时使用本技能。
  场景：对照：Python round/floor/ceil（数值舍入）。
  【不适用】Not for 以下场景：op 非 {ceil, floor, round} 时
license: MIT
compatibility: >-
  op ∈ {ceil, floor, round}；math.floor 可用；math.ceil 可用
allowed-tools: Read Write Bash
metadata:
  version: "1.0"
  skill-author: 灵枢（AEIS）
  last-reviewed: "2026-08-29"
  kccs:
    trigger_words: ["数值舍入", "工具-数值舍入", "floor", "ceil", "round 四"]
    when: "op ∈ {ceil, floor, round}；math.floor 可用；math.ceil 可用"
    sub: ["① op 分支处理"]
    execute: "按 op 分派；顺序调用"
    not_applicable: ["op 非 {ceil, floor, round} 时"]
  calibration: "对照：Python round/floor/ceil（数值舍入）"
---

# 工具-数值舍入（pylang-e1aa3818）

## When to use

任务「数值舍入」；对照：Python round/floor/ceil（数值舍入）。

## 克制条款（不适用条件）

op 非 {ceil, floor, round} 时

## How to execute

按 op 分派；顺序调用

## Verification

- 单元样例 4 条（cases 断言）
- 物理基底：按 calibration 对照（编译/运行/断言裁决）

## References

- 单元库：compiler_code_units.py「工具-数值舍入」
