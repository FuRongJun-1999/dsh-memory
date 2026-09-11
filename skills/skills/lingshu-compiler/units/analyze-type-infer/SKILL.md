---
name: analyze-type-infer
description: >-
  类型推断 / 分析-类型推断 / C2 语 / 从赋值推断符号类型 / 冲突赋值 → 类型标记'。用户提到这些词时使用本技能。
  场景：对照：C2 语义深化——类型推断（赋值→数值/文本/布尔，冲突→混合）+ 条件空间声明登记（目标3 分析器完整化）。
  【不适用】Not for 以下场景：kind 非 {COND, assign} 时
license: MIT
compatibility: >-
  statements 为语句列表（assign/条件空间声明）
allowed-tools: Read Write Bash
metadata:
  version: "1.0"
  skill-author: 灵枢（AEIS）
  last-reviewed: "2026-08-29"
  kccs:
    trigger_words: ["类型推断", "分析-类型推断", "C2 语", "从赋值推断符号类型", "冲突赋值 → 类型标记'"]
    when: "statements 为语句列表（assign/条件空间声明）"
    sub: ["① 赋值推导类型 ② 条件空间登记 ③ 冲突标记混合类型"]
    execute: "逐语句分派，冲突赋值 → 类型标记'混合'（编译期拦截候选）"
    not_applicable: ["kind 非 {COND, assign} 时"]
  calibration: "对照：C2 语义深化——类型推断（赋值→数值/文本/布尔，冲突→混合）+ 条件空间声明登记（目标3 分析器完整化）"
---

# 分析-类型推断（analyze-type-infer）

## When to use

任务「类型推断」；对照：C2 语义深化——类型推断（赋值→数值/文本/布尔，冲突→混合）+ 条件空间声明登记（目标3 分析器完整化）。

## 克制条款（不适用条件）

kind 非 {COND, assign} 时

## How to execute

逐语句分派，冲突赋值 → 类型标记'混合'（编译期拦截候选）

## Verification

- 单元样例 4 条（cases 断言）
- 物理基底：按 calibration 对照（编译/运行/断言裁决）

## References

- 单元库：compiler_code_units.py「分析-类型推断」
