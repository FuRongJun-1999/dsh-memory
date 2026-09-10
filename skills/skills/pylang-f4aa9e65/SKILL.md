---
name: pylang-f4aa9e65
description: >-
  分位数 / 工具-分位数 / quantiles——百 / 排序后按百分位取位置。用户提到这些词时使用本技能。
  场景：对照：quantiles——百分位插值（分位数）。
  【不适用】Not for 以下场景：data 为空/非法时
license: MIT
compatibility: >-
  参数 data/p 合法
allowed-tools: Read Write Bash
metadata:
  version: "1.0"
  skill-author: 灵枢（AEIS）
  last-reviewed: "2026-08-29"
  kccs:
    trigger_words: ["分位数", "工具-分位数", "quantiles——百", "排序后按百分位取位置"]
    when: "参数 data/p 合法"
    sub: ["① 调用 sorted；② 调用 int；③ 调用 min"]
    execute: "顺序调用"
    not_applicable: ["data 为空/非法时"]
  calibration: "对照：quantiles——百分位插值（分位数）"
---

# 工具-分位数（pylang-f4aa9e65）

## When to use

任务「分位数」；对照：quantiles——百分位插值（分位数）。

## 克制条款（不适用条件）

data 为空/非法时

## How to execute

顺序调用

## Verification

- 单元样例 4 条（cases 断言）
- 物理基底：按 calibration 对照（编译/运行/断言裁决）

## References

- 单元库：compiler_code_units.py「工具-分位数」
