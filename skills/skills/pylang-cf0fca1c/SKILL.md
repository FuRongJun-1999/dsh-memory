---
name: pylang-cf0fca1c
description: >-
  最长公共前缀 / 工具-最长公共前缀 / 最长公共前缀——逐词比对 / 逐字符比对所有词。用户提到这些词时使用本技能。
  场景：对照：最长公共前缀——逐词比对（LCP）。
  【不适用】Not for 以下场景：words 为空/非法时；prefix 为空/非法时（隐式盲区：返回默认值 空串 = 未知行为——不适用）
license: MIT
compatibility: >-
  w.startswith 可用
allowed-tools: Read Write Bash
metadata:
  version: "1.0"
  skill-author: 灵枢（AEIS）
  last-reviewed: "2026-08-29"
  kccs:
    trigger_words: ["最长公共前缀", "工具-最长公共前缀", "最长公共前缀——逐词比对", "逐字符比对所有词"]
    when: "w.startswith 可用"
    sub: ["① 条件判定 ② 结果处理"]
    execute: "循环迭代"
    not_applicable: ["words 为空/非法时；prefix 为空/非法时（隐式盲区：返回默认值 空串 = 未知行为——不适用）"]
  calibration: "对照：最长公共前缀——逐词比对（LCP）"
---

# 工具-最长公共前缀（pylang-cf0fca1c）

## When to use

任务「最长公共前缀」；对照：最长公共前缀——逐词比对（LCP）。

## 克制条款（不适用条件）

words 为空/非法时；prefix 为空/非法时（隐式盲区：返回默认值 空串 = 未知行为——不适用）

## How to execute

循环迭代

## Verification

- 单元样例 3 条（cases 断言）
- 物理基底：按 calibration 对照（编译/运行/断言裁决）

## References

- 单元库：compiler_code_units.py「工具-最长公共前缀」
