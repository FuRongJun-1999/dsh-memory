---
name: pylang-621123dd
description: >-
  众数统计 / 工具-众数统计 / statistics.m / 出现最频繁的元素。用户提到这些词时使用本技能。
  场景：对照：statistics.mode——众数（最频繁元素）。
  【不适用】Not for 以下场景：items 为空/非法时（隐式盲区：返回默认值 [] = 未知行为——不适用）
license: MIT
compatibility: >-
  参数 items 合法
allowed-tools: Read Write Bash
metadata:
  version: "1.0"
  skill-author: 灵枢（AEIS）
  last-reviewed: "2026-08-29"
  kccs:
    trigger_words: ["众数统计", "工具-众数统计", "statistics.m", "出现最频繁的元素"]
    when: "参数 items 合法"
    sub: ["① 调用 max"]
    execute: "循环迭代；顺序调用"
    not_applicable: ["items 为空/非法时（隐式盲区：返回默认值 [] = 未知行为——不适用）"]
  calibration: "对照：statistics.mode——众数（最频繁元素）"
---

# 工具-众数统计（pylang-621123dd）

## When to use

任务「众数统计」；对照：statistics.mode——众数（最频繁元素）。

## 克制条款（不适用条件）

items 为空/非法时（隐式盲区：返回默认值 [] = 未知行为——不适用）

## How to execute

循环迭代；顺序调用

## Verification

- 单元样例 3 条（cases 断言）
- 物理基底：按 calibration 对照（编译/运行/断言裁决）

## References

- 单元库：compiler_code_units.py「工具-众数统计」
