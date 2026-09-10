---
name: pylang-8404bbde
description: >-
  数学函数 / 工具-数学函数 / pow / sqrt / abs 绝。用户提到这些词时使用本技能。
  场景：对照：Python math——abs/pow/sqrt（数学函数族）。
  【不适用】Not for 以下场景：op 非 {abs, pow, sqrt} 时
license: MIT
compatibility: >-
  op ∈ {abs, pow, sqrt}；math.sqrt 可用
allowed-tools: Read Write Bash
metadata:
  version: "1.0"
  skill-author: 灵枢（AEIS）
  last-reviewed: "2026-08-29"
  kccs:
    trigger_words: ["数学函数", "工具-数学函数", "pow", "sqrt", "abs 绝"]
    when: "op ∈ {abs, pow, sqrt}；math.sqrt 可用"
    sub: ["① op 分支处理"]
    execute: "按 op 分派；顺序调用"
    not_applicable: ["op 非 {abs, pow, sqrt} 时"]
  calibration: "对照：Python math——abs/pow/sqrt（数学函数族）"
---

# 工具-数学函数（pylang-8404bbde）

## When to use

任务「数学函数」；对照：Python math——abs/pow/sqrt（数学函数族）。

## 克制条款（不适用条件）

op 非 {abs, pow, sqrt} 时

## How to execute

按 op 分派；顺序调用

## Verification

- 单元样例 3 条（cases 断言）
- 物理基底：按 calibration 对照（编译/运行/断言裁决）

## References

- 单元库：compiler_code_units.py「工具-数学函数」
