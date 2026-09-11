---
name: compile-logic-expr
description: >-
  逻辑表达式 / 编译-逻辑表达式 / 编译逻辑——且 / 或短路 / 逻辑表达式编译 / 且/或 → 短路跳转字节。用户提到这些词时使用本技能。
  场景：对照：编译逻辑——且/或短路（左操作数决定是否求右——短路求值语义）。
  【不适用】Not for 以下场景：op 非 {且} 时
license: MIT
compatibility: >-
  op ∈ {且, 或}；left/right 为指令列表
allowed-tools: Read Write Bash
metadata:
  version: "1.0"
  skill-author: 灵枢（AEIS）
  last-reviewed: "2026-08-29"
  kccs:
    trigger_words: ["逻辑表达式", "编译-逻辑表达式", "编译逻辑——且", "或短路", "逻辑表达式编译", "且/或 → 短路跳转字节"]
    when: "op ∈ {且, 或}；left/right 为指令列表"
    sub: ["① 拼接左指令 ② 短路跳转 ③ 拼接右指令"]
    execute: "且→JUMP_IF_FALSE、或→JUMP_IF_TRUE（左短路）"
    not_applicable: ["op 非 {且} 时"]
  calibration: "对照：编译逻辑——且/或短路（左操作数决定是否求右——短路求值语义）"
---

# 编译-逻辑表达式（compile-logic-expr）

## When to use

任务「逻辑表达式」；对照：编译逻辑——且/或短路（左操作数决定是否求右——短路求值语义）。

## 克制条款（不适用条件）

op 非 {且} 时

## How to execute

且→JUMP_IF_FALSE、或→JUMP_IF_TRUE（左短路）

## Verification

- 单元样例 2 条（cases 断言）
- 物理基底：按 calibration 对照（编译/运行/断言裁决）

## References

- 单元库：compiler_code_units.py「编译-逻辑表达式」
