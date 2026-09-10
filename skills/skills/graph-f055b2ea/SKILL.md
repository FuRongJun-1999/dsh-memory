---
name: graph-f055b2ea
description: >-
  分层布局 / 图可视化-分层布局 / 图可视化——分层布局。用户提到这些词时使用本技能。
  场景：对照：图可视化——分层布局（BFS 深度分层坐标）。
  【不适用】Not for 以下场景：starts 为空/非法时
license: MIT
compatibility: >-
  q.popleft 可用；graph.neighbors 可用
allowed-tools: Read Write Bash
metadata:
  version: "1.0"
  skill-author: 灵枢（AEIS）
  last-reviewed: "2026-08-29"
  kccs:
    trigger_words: ["分层布局", "图可视化-分层布局", "图可视化——分层布局"]
    when: "q.popleft 可用；graph.neighbors 可用"
    sub: ["① 调用 deque；② 调用 min；③ 调用 any"]
    execute: "循环迭代；顺序调用"
    not_applicable: ["starts 为空/非法时"]
  calibration: "对照：图可视化——分层布局（BFS 深度分层坐标）"
---

# 图可视化-分层布局（graph-f055b2ea）

## When to use

任务「分层布局」；对照：图可视化——分层布局（BFS 深度分层坐标）。

## 克制条款（不适用条件）

starts 为空/非法时

## How to execute

循环迭代；顺序调用

## Verification

- 单元样例 1 条（cases 断言）
- 物理基底：按 calibration 对照（编译/运行/断言裁决）

## References

- 单元库：compiler_code_units.py「图可视化-分层布局」
