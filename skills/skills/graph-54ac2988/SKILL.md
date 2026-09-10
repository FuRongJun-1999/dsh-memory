---
name: graph-54ac2988
description: >-
  PageRank / 图算法-PageRank / 权重迭代传播（出链均分。用户提到这些词时使用本技能。
  场景：对照：图算法——PageRank（权重迭代传播，入链多者排名高）。
  【不适用】Not for 以下场景：out 为空/非法时
license: MIT
compatibility: >-
  graph.neighbors 可用
allowed-tools: Read Write Bash
metadata:
  version: "1.0"
  skill-author: 灵枢（AEIS）
  last-reviewed: "2026-08-29"
  kccs:
    trigger_words: ["PageRank", "图算法-PageRank", "权重迭代传播（出链均分"]
    when: "graph.neighbors 可用"
    sub: ["① 调用 sorted；② 调用 len；③ 调用 range"]
    execute: "循环迭代；顺序调用"
    not_applicable: ["out 为空/非法时"]
  calibration: "对照：图算法——PageRank（权重迭代传播，入链多者排名高）"
---

# 图算法-PageRank（graph-54ac2988）

## When to use

任务「PageRank」；对照：图算法——PageRank（权重迭代传播，入链多者排名高）。

## 克制条款（不适用条件）

out 为空/非法时

## How to execute

循环迭代；顺序调用

## Verification

- 单元样例 1 条（cases 断言）
- 物理基底：按 calibration 对照（编译/运行/断言裁决）

## References

- 单元库：compiler_code_units.py「图算法-PageRank」
