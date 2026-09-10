---
name: graph-de00894f
description: >-
  聚类系数 / 图算法-聚类系数 / 局部聚类系数——邻居间实 / 可能边 / 邻居间实际边数 / 可能。用户提到这些词时使用本技能。
  场景：对照：局部聚类系数——邻居间实际边/可能边（闭合度）。
  【不适用】Not for 以下场景：k 越界（Lt）时
license: MIT
compatibility: >-
  参数 adj/u 合法
allowed-tools: Read Write Bash
metadata:
  version: "1.0"
  skill-author: 灵枢（AEIS）
  last-reviewed: "2026-08-29"
  kccs:
    trigger_words: ["聚类系数", "图算法-聚类系数", "局部聚类系数——邻居间实", "可能边", "邻居间实际边数 / 可能"]
    when: "参数 adj/u 合法"
    sub: ["① 调用 set；② 调用 len；③ 调用 sum"]
    execute: "顺序调用"
    not_applicable: ["k 越界（Lt）时"]
  calibration: "对照：局部聚类系数——邻居间实际边/可能边（闭合度）"
---

# 图算法-聚类系数（graph-de00894f）

## When to use

任务「聚类系数」；对照：局部聚类系数——邻居间实际边/可能边（闭合度）。

## 克制条款（不适用条件）

k 越界（Lt）时

## How to execute

顺序调用

## Verification

- 单元样例 3 条（cases 断言）
- 物理基底：按 calibration 对照（编译/运行/断言裁决）

## References

- 单元库：compiler_code_units.py「图算法-聚类系数」
