---
name: pylang-85d8617b
description: >-
  集合运算 / 数据结构-集合运算 / Python set—— / union 并。用户提到这些词时使用本技能。
  场景：对照：Python set——并/交/差（集合代数运算）。
  【不适用】Not for 以下场景：op 非 {diff, intersect, union} 时
license: MIT
compatibility: >-
  op ∈ {diff, intersect, union}
allowed-tools: Read Write Bash
metadata:
  version: "1.0"
  skill-author: 灵枢（AEIS）
  last-reviewed: "2026-08-29"
  kccs:
    trigger_words: ["集合运算", "数据结构-集合运算", "Python set——", "union 并"]
    when: "op ∈ {diff, intersect, union}"
    sub: ["① op 分支处理"]
    execute: "按 op 分派；顺序调用"
    not_applicable: ["op 非 {diff, intersect, union} 时"]
  calibration: "对照：Python set——并/交/差（集合代数运算）"
---

# 数据结构-集合运算（pylang-85d8617b）

## When to use

任务「集合运算」；对照：Python set——并/交/差（集合代数运算）。

## 克制条款（不适用条件）

op 非 {diff, intersect, union} 时

## How to execute

按 op 分派；顺序调用

## Verification

- 单元样例 3 条（cases 断言）
- 物理基底：按 calibration 对照（编译/运行/断言裁决）

## References

- 单元库：compiler_code_units.py「数据结构-集合运算」
