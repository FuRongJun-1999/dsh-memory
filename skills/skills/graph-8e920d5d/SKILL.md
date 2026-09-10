---
name: graph-8e920d5d
description: >-
  邻居查询 / 图查询-邻居查询 / 图查询——一跳 / 多跳邻居 / direct 一。用户提到这些词时使用本技能。
  场景：对照：图查询——一跳/多跳邻居（BFS 扩展）。
  【不适用】Not for 以下场景：op 非 {direct, multi} 时
license: MIT
compatibility: >-
  op ∈ {direct, multi}；seen.discard 可用
allowed-tools: Read Write Bash
metadata:
  version: "1.0"
  skill-author: 灵枢（AEIS）
  last-reviewed: "2026-08-29"
  kccs:
    trigger_words: ["邻居查询", "图查询-邻居查询", "图查询——一跳", "多跳邻居", "direct 一"]
    when: "op ∈ {direct, multi}；seen.discard 可用"
    sub: ["① op 分支处理"]
    execute: "按 op 分派；循环迭代；顺序调用"
    not_applicable: ["op 非 {direct, multi} 时"]
  calibration: "对照：图查询——一跳/多跳邻居（BFS 扩展）"
---

# 图查询-邻居查询（graph-8e920d5d）

## When to use

任务「邻居查询」；对照：图查询——一跳/多跳邻居（BFS 扩展）。

## 克制条款（不适用条件）

op 非 {direct, multi} 时

## How to execute

按 op 分派；循环迭代；顺序调用

## Verification

- 单元样例 3 条（cases 断言）
- 物理基底：按 calibration 对照（编译/运行/断言裁决）

## References

- 单元库：compiler_code_units.py「图查询-邻居查询」
