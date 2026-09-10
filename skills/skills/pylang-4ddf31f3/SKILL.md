---
name: pylang-4ddf31f3
description: >-
  异步生成器 / 异步-异步生成器 / async genera / next 产。用户提到这些词时使用本技能。
  场景：对照：async generator——异步逐值产出（yield 语义模拟）。
  【不适用】Not for 以下场景：op 非 {done, feed, next} 时
license: MIT
compatibility: >-
  op ∈ {done, feed, next}
allowed-tools: Read Write Bash
metadata:
  version: "1.0"
  skill-author: 灵枢（AEIS）
  last-reviewed: "2026-08-29"
  kccs:
    trigger_words: ["异步生成器", "异步-异步生成器", "async genera", "next 产"]
    when: "op ∈ {done, feed, next}"
    sub: ["① op 分支处理"]
    execute: "按 op 分派"
    not_applicable: ["op 非 {done, feed, next} 时"]
  calibration: "对照：async generator——异步逐值产出（yield 语义模拟）"
---

# 异步-异步生成器（pylang-4ddf31f3）

## When to use

任务「异步生成器」；对照：async generator——异步逐值产出（yield 语义模拟）。

## 克制条款（不适用条件）

op 非 {done, feed, next} 时

## How to execute

按 op 分派

## Verification

- 单元样例 4 条（cases 断言）
- 物理基底：按 calibration 对照（编译/运行/断言裁决）

## References

- 单元库：compiler_code_units.py「异步-异步生成器」
