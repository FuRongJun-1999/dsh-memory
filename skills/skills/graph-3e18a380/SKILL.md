---
name: graph-3e18a380
description: >-
  节点大小 / 图可视化-节点大小 / 图可视化——度→节点尺寸 / 按度映射尺寸。用户提到这些词时使用本技能。
  场景：对照：图可视化——度→节点尺寸映射（节点大小）。
  【不适用】Not for 以下场景：adj 为空/非法时（隐式盲区：返回默认值 {} = 未知行为——不适用）
license: MIT
compatibility: >-
  参数 adj/min_size/max_size 合法
allowed-tools: Read Write Bash
metadata:
  version: "1.0"
  skill-author: 灵枢（AEIS）
  last-reviewed: "2026-08-29"
  kccs:
    trigger_words: ["节点大小", "图可视化-节点大小", "图可视化——度→节点尺寸", "按度映射尺寸"]
    when: "参数 adj/min_size/max_size 合法"
    sub: ["① 调用 len；② 调用 max；③ 调用 min"]
    execute: "循环迭代；顺序调用"
    not_applicable: ["adj 为空/非法时（隐式盲区：返回默认值 {} = 未知行为——不适用）"]
  calibration: "对照：图可视化——度→节点尺寸映射（节点大小）"
---

# 图可视化-节点大小（graph-3e18a380）

## When to use

任务「节点大小」；对照：图可视化——度→节点尺寸映射（节点大小）。

## 克制条款（不适用条件）

adj 为空/非法时（隐式盲区：返回默认值 {} = 未知行为——不适用）

## How to execute

循环迭代；顺序调用

## Verification

- 单元样例 3 条（cases 断言）
- 物理基底：按 calibration 对照（编译/运行/断言裁决）

## References

- 单元库：compiler_code_units.py「图可视化-节点大小」
