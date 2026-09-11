---
name: compile-type-check
description: >-
  类型检查 / 编译-类型检查 / C2 语 / 类型检查编译 / 先类型推断 → 未推断/ / infer_fn 注 / 分析-类型推断）。用户提到这些词时使用本技能。
  场景：对照：C2 语义深化——类型推断接入编译管线（未推断/混合类型符号使用→编译期拦截，目标3 分析器完整化）。
  【不适用】Not for 以下场景：t 非 {混合} 时
license: MIT
compatibility: >-
  t ∈ {混合}；_re.findall 可用
allowed-tools: Read Write Bash
metadata:
  version: "1.0"
  skill-author: 灵枢（AEIS）
  last-reviewed: "2026-08-29"
  kccs:
    trigger_words: ["类型检查", "编译-类型检查", "C2 语", "类型检查编译", "先类型推断 → 未推断/", "infer_fn 注", "分析-类型推断）"]
    when: "t ∈ {混合}；_re.findall 可用"
    sub: ["1 t 分支处理"]
    execute: "按 op 分派；循环迭代；顺序调用"
    not_applicable: ["t 非 {混合} 时"]
  calibration: "对照：C2 语义深化——类型推断接入编译管线（未推断/混合类型符号使用→编译期拦截，目标3 分析器完整化）"
---

# 编译-类型检查（compile-type-check）

## When to use

任务「类型检查」；对照：C2 语义深化——类型推断接入编译管线（未推断/混合类型符号使用→编译期拦截，目标3 分析器完整化）。

## 克制条款（不适用条件）

t 非 {混合} 时

## How to execute

按 op 分派；循环迭代；顺序调用

## Verification

- 单元样例 3 条（cases 断言）
- 物理基底：按 calibration 对照（编译/运行/断言裁决）

## References

- 单元库：compiler_code_units.py「编译-类型检查」
