---
name: pylang-49026041
description: >-
  并查集 / 数据结构-并查集 / union-find—— / 查找 / 连通 / find 根 / 根查找 / 路径压缩。用户提到这些词时使用本技能。
  场景：对照：union-find——不相交集合并/查找/连通（路径压缩）。
  【不适用】Not for 以下场景：op 非 {connected, find, union} 时
license: MIT
compatibility: >-
  op ∈ {connected, find, union}
allowed-tools: Read Write Bash
metadata:
  version: "1.0"
  skill-author: 灵枢（AEIS）
  last-reviewed: "2026-08-29"
  kccs:
    trigger_words: ["并查集", "数据结构-并查集", "union-find——", "查找", "连通", "find 根", "根查找", "路径压缩"]
    when: "op ∈ {connected, find, union}"
    sub: ["① op 分支处理"]
    execute: "按 op 分派；循环迭代；顺序调用"
    not_applicable: ["op 非 {connected, find, union} 时"]
  calibration: "对照：union-find——不相交集合并/查找/连通（路径压缩）"
---

# 数据结构-并查集（pylang-49026041）

## When to use

任务「并查集」；对照：union-find——不相交集合并/查找/连通（路径压缩）。

## 克制条款（不适用条件）

op 非 {connected, find, union} 时

## How to execute

按 op 分派；循环迭代；顺序调用

## Verification

- 单元样例 4 条（cases 断言）
- 物理基底：按 calibration 对照（编译/运行/断言裁决）

## References

- 单元库：compiler_code_units.py「数据结构-并查集」
