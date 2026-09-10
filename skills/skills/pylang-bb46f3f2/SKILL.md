---
name: pylang-bb46f3f2
description: >-
  跳表 / 数据结构-跳表 / 跳表——有序键插入 / 查找 / put 插。用户提到这些词时使用本技能。
  场景：对照：跳表——有序键插入/查找（多层索引加速语义）。
  【不适用】Not for 以下场景：op 非 {get, levels, put} 时
license: MIT
compatibility: >-
  op ∈ {get, levels, put}
allowed-tools: Read Write Bash
metadata:
  version: "1.0"
  skill-author: 灵枢（AEIS）
  last-reviewed: "2026-08-29"
  kccs:
    trigger_words: ["跳表", "数据结构-跳表", "跳表——有序键插入", "查找", "put 插"]
    when: "op ∈ {get, levels, put}"
    sub: ["① op 分支处理"]
    execute: "按 op 分派；顺序调用"
    not_applicable: ["op 非 {get, levels, put} 时"]
  calibration: "对照：跳表——有序键插入/查找（多层索引加速语义）"
---

# 数据结构-跳表（pylang-bb46f3f2）

## When to use

任务「跳表」；对照：跳表——有序键插入/查找（多层索引加速语义）。

## 克制条款（不适用条件）

op 非 {get, levels, put} 时

## How to execute

按 op 分派；顺序调用

## Verification

- 单元样例 4 条（cases 断言）
- 物理基底：按 calibration 对照（编译/运行/断言裁决）

## References

- 单元库：compiler_code_units.py「数据结构-跳表」
