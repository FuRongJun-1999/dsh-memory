---
name: graph-37a45d4b
description: >-
  最大流 / 图算法-最大流 / 图算法——最大流 / BFS 增。用户提到这些词时使用本技能。
  场景：对照：图算法——最大流（Ford-Fulkerson 增广路径推送）。
  【不适用】Not for 以下场景：found 为空/非法时
license: MIT
compatibility: >-
  graph 为容量网络（含容量边）；source/sink 为源/汇节点
allowed-tools: Read Write Bash
metadata:
  version: "1.0"
  skill-author: 灵枢（AEIS）
  last-reviewed: "2026-08-29"
  kccs:
    trigger_words: ["最大流", "图算法-最大流", "图算法——最大流", "BFS 增"]
    when: "graph 为容量网络（含容量边）；source/sink 为源/汇节点"
    sub: ["① BFS 找增广路 ② 沿路推送最小剩余容量 ③ 更新残留网络"]
    execute: "反复增广直至无路，累加推送流量"
    not_applicable: ["found 为空/非法时"]
  calibration: "对照：图算法——最大流（Ford-Fulkerson 增广路径推送）"
---

# 图算法-最大流（graph-37a45d4b）

## When to use

任务「最大流」；对照：图算法——最大流（Ford-Fulkerson 增广路径推送）。

## 克制条款（不适用条件）

found 为空/非法时

## How to execute

反复增广直至无路，累加推送流量

## Verification

- 单元样例 3 条（cases 断言）
- 物理基底：按 calibration 对照（编译/运行/断言裁决）

## References

- 单元库：compiler_code_units.py「图算法-最大流」
