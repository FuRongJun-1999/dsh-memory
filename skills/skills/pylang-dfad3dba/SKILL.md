---
name: pylang-dfad3dba
description: >-
  字符串对齐 / 工具-字符串对齐 / ljust 左。用户提到这些词时使用本技能。
  场景：对照：str.ljust/rjust/center——填充对齐。
  【不适用】Not for 以下场景：align 非 {center, left, right} 时（隐式盲区：返回默认值 0 = 未知行为——不适用）
license: MIT
compatibility: >-
  align ∈ {center, left, right}；text.ljust 可用；text.rjust 可用
allowed-tools: Read Write Bash
metadata:
  version: "1.0"
  skill-author: 灵枢（AEIS）
  last-reviewed: "2026-08-29"
  kccs:
    trigger_words: ["字符串对齐", "工具-字符串对齐", "ljust 左"]
    when: "align ∈ {center, left, right}；text.ljust 可用；text.rjust 可用"
    sub: ["1 align 分支处理"]
    execute: "按 op 分派"
    not_applicable: ["align 非 {center, left, right} 时（隐式盲区：返回默认值 0 = 未知行为——不适用）"]
  calibration: "对照：str.ljust/rjust/center——填充对齐"
---

# 工具-字符串对齐（pylang-dfad3dba）

## When to use

任务「字符串对齐」；对照：str.ljust/rjust/center——填充对齐。

## 克制条款（不适用条件）

align 非 {center, left, right} 时（隐式盲区：返回默认值 0 = 未知行为——不适用）

## How to execute

按 op 分派

## Verification

- 单元样例 4 条（cases 断言）
- 物理基底：按 calibration 对照（编译/运行/断言裁决）

## References

- 单元库：compiler_code_units.py「工具-字符串对齐」
