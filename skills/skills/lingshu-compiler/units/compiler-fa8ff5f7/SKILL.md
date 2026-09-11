---
name: compiler-fa8ff5f7
description: >-
  内联缓存 / 编译-内联缓存 / learn 学。用户提到这些词时使用本技能。
  场景：对照：多态内联缓存——类→方法学习/命中/未命中。
  【不适用】Not for 以下场景：op 非 {learn, lookup, miss} 时
license: MIT
compatibility: >-
  op ∈ {learn, lookup, miss}
allowed-tools: Read Write Bash
metadata:
  version: "1.0"
  skill-author: 灵枢（AEIS）
  last-reviewed: "2026-08-29"
  kccs:
    trigger_words: ["内联缓存", "编译-内联缓存", "learn 学"]
    when: "op ∈ {learn, lookup, miss}"
    sub: ["① op 分支处理"]
    execute: "按 op 分派"
    not_applicable: ["op 非 {learn, lookup, miss} 时"]
  calibration: "对照：多态内联缓存——类→方法学习/命中/未命中"
---

# 编译-内联缓存（compiler-fa8ff5f7）

## When to use

任务「内联缓存」；对照：多态内联缓存——类→方法学习/命中/未命中。

## 克制条款（不适用条件）

op 非 {learn, lookup, miss} 时

## How to execute

按 op 分派

## Verification

- 单元样例 4 条（cases 断言）
- 物理基底：按 calibration 对照（编译/运行/断言裁决）

## References

- 单元库：compiler_code_units.py「编译-内联缓存」
