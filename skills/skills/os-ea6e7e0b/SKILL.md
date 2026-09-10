---
name: os-ea6e7e0b
description: >-
  性能分析 / 性能-性能分析 / OS 性 / profiling / 函数耗时统计。用户提到这些词时使用本技能。
  场景：对照：OS 性能——profiling（函数耗时统计，热点定位）。
  【不适用】Not for 以下场景：times 为空/非法时
license: MIT
compatibility: >-
  参数 times 合法
allowed-tools: Read Write Bash
metadata:
  version: "1.0"
  skill-author: 灵枢（AEIS）
  last-reviewed: "2026-08-29"
  kccs:
    trigger_words: ["性能分析", "性能-性能分析", "OS 性", "profiling", "函数耗时统计"]
    when: "参数 times 合法"
    sub: ["① 调用 sum；② 调用 round；③ 调用 len"]
    execute: "顺序调用"
    not_applicable: ["times 为空/非法时"]
  calibration: "对照：OS 性能——profiling（函数耗时统计，热点定位）"
---

# 性能-性能分析（os-ea6e7e0b）

## When to use

任务「性能分析」；对照：OS 性能——profiling（函数耗时统计，热点定位）。

## 克制条款（不适用条件）

times 为空/非法时

## How to execute

顺序调用

## Verification

- 单元样例 2 条（cases 断言）
- 物理基底：按 calibration 对照（编译/运行/断言裁决）

## References

- 单元库：compiler_code_units.py「性能-性能分析」
