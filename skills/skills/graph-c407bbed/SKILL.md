---
name: graph-c407bbed
description: >-
  增量更新 / 图算法-增量更新 / 动态图——增量边增删 / 动态图增量 / 边增删（增量维护。用户提到这些词时使用本技能。
  场景：对照：动态图——增量边增删（增量维护语义）。
  【不适用】Not for 以下场景：op 非 {add, remove} 时
license: MIT
compatibility: >-
  op ∈ {add, remove}；graph.add_edge 可用；graph.remove_edge 可用
allowed-tools: Read Write Bash
metadata:
  version: "1.0"
  skill-author: 灵枢（AEIS）
  last-reviewed: "2026-08-29"
  kccs:
    trigger_words: ["增量更新", "图算法-增量更新", "动态图——增量边增删", "动态图增量", "边增删（增量维护"]
    when: "op ∈ {add, remove}；graph.add_edge 可用；graph.remove_edge 可用"
    sub: ["① op 分支处理"]
    execute: "按 op 分派"
    not_applicable: ["op 非 {add, remove} 时"]
  calibration: "对照：动态图——增量边增删（增量维护语义）"
---

# 图算法-增量更新（graph-c407bbed）

## When to use

任务「增量更新」；对照：动态图——增量边增删（增量维护语义）。

## 克制条款（不适用条件）

op 非 {add, remove} 时

## How to execute

按 op 分派

## Verification

- 单元样例 1 条（cases 断言）
- 物理基底：按 calibration 对照（编译/运行/断言裁决）

## References

- 单元库：compiler_code_units.py「图算法-增量更新」
