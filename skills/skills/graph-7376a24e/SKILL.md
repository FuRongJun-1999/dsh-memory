---
name: graph-7376a24e
description: >-
  加权最短路径 / 图遍历-加权最短 / Dijkstra 贪。用户提到这些词时使用本技能。
  场景：对照：条件链加权最短——Dijkstra 选代价最小链（缺氧路径代价 1+2=3 < 沸点降路径 2+2=4）。
  【不适用】Not for 以下场景：条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）
license: MIT
compatibility: >-
  heapq.heappop 可用；graph.neighbors 可用
allowed-tools: Read Write Bash
metadata:
  version: "1.0"
  skill-author: 灵枢（AEIS）
  last-reviewed: "2026-08-29"
  kccs:
    trigger_words: ["加权最短路径", "图遍历-加权最短", "Dijkstra 贪"]
    when: "heapq.heappop 可用；graph.neighbors 可用"
    sub: ["① 调用 float"]
    execute: "循环迭代；顺序调用"
    not_applicable: ["条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）"]
  calibration: "对照：条件链加权最短——Dijkstra 选代价最小链（缺氧路径代价 1+2=3 < 沸点降路径 2+2=4）"
---

# 图遍历-加权最短（graph-7376a24e）

## When to use

任务「加权最短路径」；对照：条件链加权最短——Dijkstra 选代价最小链（缺氧路径代价 1+2=3 < 沸点降路径 2+2=4）。

## 克制条款（不适用条件）

条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）

## How to execute

循环迭代；顺序调用

## Verification

- 单元样例 1 条（cases 断言）
- 物理基底：按 calibration 对照（编译/运行/断言裁决）

## References

- 单元库：compiler_code_units.py「图遍历-加权最短」
