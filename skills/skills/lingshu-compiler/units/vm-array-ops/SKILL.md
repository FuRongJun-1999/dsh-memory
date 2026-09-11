---
name: vm-array-ops
description: >-
  数组操作 / VM-数组操作 / VM 数 / aget 索。用户提到这些词时使用本技能。
  场景：对照：VM 数组——索引读写与越界保护（AGET/ASET 指令）。
  【不适用】Not for 以下场景：op 非 {aget, aset, size} 时
license: MIT
compatibility: >-
  op ∈ {aget, aset, size}
allowed-tools: Read Write Bash
metadata:
  version: "1.0"
  skill-author: 灵枢（AEIS）
  last-reviewed: "2026-08-29"
  kccs:
    trigger_words: ["数组操作", "VM-数组操作", "VM 数", "aget 索"]
    when: "op ∈ {aget, aset, size}"
    sub: ["① op 分支处理"]
    execute: "按 op 分派；顺序调用"
    not_applicable: ["op 非 {aget, aset, size} 时"]
  calibration: "对照：VM 数组——索引读写与越界保护（AGET/ASET 指令）"
---

# VM-数组操作（vm-array-ops）

## When to use

任务「数组操作」；对照：VM 数组——索引读写与越界保护（AGET/ASET 指令）。

## 克制条款（不适用条件）

op 非 {aget, aset, size} 时

## How to execute

按 op 分派；顺序调用

## Verification

- 单元样例 4 条（cases 断言）
- 物理基底：按 calibration 对照（编译/运行/断言裁决）

## References

- 单元库：compiler_code_units.py「VM-数组操作」
