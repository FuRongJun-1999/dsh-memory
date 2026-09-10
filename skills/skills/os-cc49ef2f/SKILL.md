---
name: os-cc49ef2f
description: >-
  存储池 / 存储-存储池 / 存储池——容量池分配 / 回收 / create 建。用户提到这些词时使用本技能。
  场景：对照：存储池——容量池分配/回收（超限拒绝）。
  【不适用】Not for 以下场景：op 非 {alloc, create, free, status} 时
license: MIT
compatibility: >-
  op ∈ {alloc, create, free, status}
allowed-tools: Read Write Bash
metadata:
  version: "1.0"
  skill-author: 灵枢（AEIS）
  last-reviewed: "2026-08-29"
  kccs:
    trigger_words: ["存储池", "存储-存储池", "存储池——容量池分配", "回收", "create 建"]
    when: "op ∈ {alloc, create, free, status}"
    sub: ["① op 分支处理"]
    execute: "按 op 分派；顺序调用"
    not_applicable: ["op 非 {alloc, create, free, status} 时"]
  calibration: "对照：存储池——容量池分配/回收（超限拒绝）"
---

# 存储-存储池（os-cc49ef2f）

## When to use

任务「存储池」；对照：存储池——容量池分配/回收（超限拒绝）。

## 克制条款（不适用条件）

op 非 {alloc, create, free, status} 时

## How to execute

按 op 分派；顺序调用

## Verification

- 单元样例 5 条（cases 断言）
- 物理基底：按 calibration 对照（编译/运行/断言裁决）

## References

- 单元库：compiler_code_units.py「存储-存储池」
