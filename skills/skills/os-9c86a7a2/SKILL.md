---
name: os-9c86a7a2
description: >-
  内存池 / 内存-内存池 / 内存池——固定块分配 / 释放 / 统计 / alloc 分。用户提到这些词时使用本技能。
  场景：对照：内存池——固定块分配/释放/统计（池化分配）。
  【不适用】Not for 以下场景：op 非 {alloc, free, stats} 时
license: MIT
compatibility: >-
  op ∈ {alloc, free, stats}
allowed-tools: Read Write Bash
metadata:
  version: "1.0"
  skill-author: 灵枢（AEIS）
  last-reviewed: "2026-08-29"
  kccs:
    trigger_words: ["内存池", "内存-内存池", "内存池——固定块分配", "释放", "统计", "alloc 分"]
    when: "op ∈ {alloc, free, stats}"
    sub: ["① op 分支处理"]
    execute: "按 op 分派；顺序调用"
    not_applicable: ["op 非 {alloc, free, stats} 时"]
  calibration: "对照：内存池——固定块分配/释放/统计（池化分配）"
---

# 内存-内存池（os-9c86a7a2）

## When to use

任务「内存池」；对照：内存池——固定块分配/释放/统计（池化分配）。

## 克制条款（不适用条件）

op 非 {alloc, free, stats} 时

## How to execute

按 op 分派；顺序调用

## Verification

- 单元样例 4 条（cases 断言）
- 物理基底：按 calibration 对照（编译/运行/断言裁决）

## References

- 单元库：compiler_code_units.py「内存-内存池」
