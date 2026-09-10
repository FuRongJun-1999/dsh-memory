---
name: pylang-f5b34833
description: >-
  列表分块 / 工具-列表分块 / 分块——按大小分批 / 按固定大小切块。用户提到这些词时使用本技能。
  场景：对照：分块——按大小分批（chunking）。
  【不适用】Not for 以下场景：size 越界（LtE）时（隐式盲区：返回默认值 [] = 未知行为——不适用）
license: MIT
compatibility: >-
  参数 items/size 合法
allowed-tools: Read Write Bash
metadata:
  version: "1.0"
  skill-author: 灵枢（AEIS）
  last-reviewed: "2026-08-29"
  kccs:
    trigger_words: ["列表分块", "工具-列表分块", "分块——按大小分批", "按固定大小切块"]
    when: "参数 items/size 合法"
    sub: ["① 调用 range；② 调用 len"]
    execute: "顺序调用"
    not_applicable: ["size 越界（LtE）时（隐式盲区：返回默认值 [] = 未知行为——不适用）"]
  calibration: "对照：分块——按大小分批（chunking）"
---

# 工具-列表分块（pylang-f5b34833）

## When to use

任务「列表分块」；对照：分块——按大小分批（chunking）。

## 克制条款（不适用条件）

size 越界（LtE）时（隐式盲区：返回默认值 [] = 未知行为——不适用）

## How to execute

顺序调用

## Verification

- 单元样例 4 条（cases 断言）
- 物理基底：按 calibration 对照（编译/运行/断言裁决）

## References

- 单元库：compiler_code_units.py「工具-列表分块」
