---
name: compiler-cda9c262
description: >-
  边界检查消除 / 编译-边界检查消除 / 编译优化——边界检查消除 / prove 证。用户提到这些词时使用本技能。
  场景：对照：编译优化——边界检查消除（可证范围免检）。
  【不适用】Not for 以下场景：op 非 {eliminate, prove} 时
license: MIT
compatibility: >-
  op ∈ {eliminate, prove}
allowed-tools: Read Write Bash
metadata:
  version: "1.0"
  skill-author: 灵枢（AEIS）
  last-reviewed: "2026-08-29"
  kccs:
    trigger_words: ["边界检查消除", "编译-边界检查消除", "编译优化——边界检查消除", "prove 证"]
    when: "op ∈ {eliminate, prove}"
    sub: ["① op 分支处理"]
    execute: "按 op 分派"
    not_applicable: ["op 非 {eliminate, prove} 时"]
  calibration: "对照：编译优化——边界检查消除（可证范围免检）"
---

# 编译-边界检查消除（compiler-cda9c262）

## When to use

任务「边界检查消除」；对照：编译优化——边界检查消除（可证范围免检）。

## 克制条款（不适用条件）

op 非 {eliminate, prove} 时

## How to execute

按 op 分派

## Verification

- 单元样例 4 条（cases 断言）
- 物理基底：按 calibration 对照（编译/运行/断言裁决）

## References

- 单元库：compiler_code_units.py「编译-边界检查消除」
