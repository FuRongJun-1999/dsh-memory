---
name: pylang-01b23f80
description: >-
  有序字典 / 数据结构-有序字典 / collections. / put 按。用户提到这些词时使用本技能。
  场景：对照：collections.OrderedDict——插入序保持（键序）。
  【不适用】Not for 以下场景：op 非 {get, order, put} 时
license: MIT
compatibility: >-
  op ∈ {get, order, put}
allowed-tools: Read Write Bash
metadata:
  version: "1.0"
  skill-author: 灵枢（AEIS）
  last-reviewed: "2026-08-29"
  kccs:
    trigger_words: ["有序字典", "数据结构-有序字典", "collections.", "put 按"]
    when: "op ∈ {get, order, put}"
    sub: ["① op 分支处理"]
    execute: "按 op 分派；顺序调用"
    not_applicable: ["op 非 {get, order, put} 时"]
  calibration: "对照：collections.OrderedDict——插入序保持（键序）"
---

# 数据结构-有序字典（pylang-01b23f80）

## When to use

任务「有序字典」；对照：collections.OrderedDict——插入序保持（键序）。

## 克制条款（不适用条件）

op 非 {get, order, put} 时

## How to execute

按 op 分派；顺序调用

## Verification

- 单元样例 4 条（cases 断言）
- 物理基底：按 calibration 对照（编译/运行/断言裁决）

## References

- 单元库：compiler_code_units.py「数据结构-有序字典」
