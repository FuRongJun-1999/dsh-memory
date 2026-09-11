---
name: compiler-63eae588
description: >-
  布尔字面量 / 语法-布尔字面量 / 词法——布尔字面量。用户提到这些词时使用本技能。
  场景：对照：词法——布尔字面量（真/假→True/False）。
  【不适用】Not for 以下场景：token 非 {假, 真} 时
license: MIT
compatibility: >-
  token ∈ {假, 真}
allowed-tools: Read Write Bash
metadata:
  version: "1.0"
  skill-author: 灵枢（AEIS）
  last-reviewed: "2026-08-29"
  kccs:
    trigger_words: ["布尔字面量", "语法-布尔字面量", "词法——布尔字面量"]
    when: "token ∈ {假, 真}"
    sub: ["1 token 分支处理"]
    execute: "按 op 分派"
    not_applicable: ["token 非 {假, 真} 时"]
  calibration: "对照：词法——布尔字面量（真/假→True/False）"
---

# 语法-布尔字面量（compiler-63eae588）

## When to use

任务「布尔字面量」；对照：词法——布尔字面量（真/假→True/False）。

## 克制条款（不适用条件）

token 非 {假, 真} 时

## How to execute

按 op 分派

## Verification

- 单元样例 3 条（cases 断言）
- 物理基底：按 calibration 对照（编译/运行/断言裁决）

## References

- 单元库：compiler_code_units.py「语法-布尔字面量」
