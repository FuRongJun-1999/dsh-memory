---
name: graph-3aa4c941
description: >-
  拓扑排序 / 图算法-拓扑排序 / 图算法——拓扑排序 / DAG 依。用户提到这些词时使用本技能。
  场景：对照：图算法——拓扑排序（Kahn 入度归零，DAG 依赖顺序；有环返回 None）。
  【不适用】Not for 以下场景：条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）
license: MIT
compatibility: >-
  graph 为有向无环图（含 nodes/neighbors 接口）
allowed-tools: Read Write Bash
metadata:
  version: "1.0"
  skill-author: 灵枢（AEIS）
  last-reviewed: "2026-08-29"
  kccs:
    trigger_words: ["拓扑排序", "图算法-拓扑排序", "图算法——拓扑排序", "DAG 依"]
    when: "graph 为有向无环图（含 nodes/neighbors 接口）"
    sub: ["① 入度统计 ② 零入度入队 ③ 出队并减后继入度"]
    execute: "Kahn 队列反复出零入度节点（依赖顺序）"
    not_applicable: ["条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）"]
  calibration: "对照：图算法——拓扑排序（Kahn 入度归零，DAG 依赖顺序；有环返回 None）"
---

# 图算法-拓扑排序（graph-3aa4c941）

## When to use

任务「拓扑排序」；对照：图算法——拓扑排序（Kahn 入度归零，DAG 依赖顺序；有环返回 None）。

## 克制条款（不适用条件）

条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）

## How to execute

Kahn 队列反复出零入度节点（依赖顺序）

## Verification

- 单元样例 1 条（cases 断言）
- 物理基底：按 calibration 对照（编译/运行/断言裁决）

## References

- 单元库：compiler_code_units.py「图算法-拓扑排序」
