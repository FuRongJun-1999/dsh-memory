---
name: graph-5ca34baa
description: >-
  社区发现 / 图算法-社区发现 / 图算法——标签传播社区发 / 标签传播。用户提到这些词时使用本技能。
  场景：对照：图算法——标签传播社区发现（LPA，邻居多数标签传播收敛）。
  【不适用】Not for 以下场景：neigh 为空/非法时
license: MIT
compatibility: >-
  graph.neighbors 可用；cnt.most_common 可用
allowed-tools: Read Write Bash
metadata:
  version: "1.0"
  skill-author: 灵枢（AEIS）
  last-reviewed: "2026-08-29"
  kccs:
    trigger_words: ["社区发现", "图算法-社区发现", "图算法——标签传播社区发", "标签传播"]
    when: "graph.neighbors 可用；cnt.most_common 可用"
    sub: ["① 调用 range；② 调用 sorted；③ 调用 Counter"]
    execute: "循环迭代；顺序调用"
    not_applicable: ["neigh 为空/非法时"]
  calibration: "对照：图算法——标签传播社区发现（LPA，邻居多数标签传播收敛）"
---

# 图算法-社区发现（graph-5ca34baa）

## When to use

任务「社区发现」；对照：图算法——标签传播社区发现（LPA，邻居多数标签传播收敛）。

## 克制条款（不适用条件）

neigh 为空/非法时

## How to execute

循环迭代；顺序调用

## Verification

- 单元样例 1 条（cases 断言）
- 物理基底：按 calibration 对照（编译/运行/断言裁决）

## References

- 单元库：compiler_code_units.py「图算法-社区发现」
