---
name: graph-52e6e216
description: >-
  连通分量 / 图算法-连通分量 / 图算法——连通分量 / BFS 分 / 构建无向邻接。用户提到这些词时使用本技能。
  场景：对照：图算法——连通分量（无向互达分组）。
  【不适用】Not for 以下场景：条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）
license: MIT
compatibility: >-
  graph 提供 nodes/neighbors 接口（无向图）
allowed-tools: Read Write Bash
metadata:
  version: "1.0"
  skill-author: 灵枢（AEIS）
  last-reviewed: "2026-08-29"
  kccs:
    trigger_words: ["连通分量", "图算法-连通分量", "图算法——连通分量", "BFS 分", "构建无向邻接"]
    when: "graph 提供 nodes/neighbors 接口（无向图）"
    sub: ["① 邻接双向化 ② BFS 未访问分组 ③ 收集各分量"]
    execute: "BFS 逐组标记，未访问节点开新组"
    not_applicable: ["条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）"]
  calibration: "对照：图算法——连通分量（无向互达分组）"
---

# 图算法-连通分量（graph-52e6e216）

## When to use

任务「连通分量」；对照：图算法——连通分量（无向互达分组）。

## 克制条款（不适用条件）

条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）

## How to execute

BFS 逐组标记，未访问节点开新组

## Verification

- 单元样例 1 条（cases 断言）
- 物理基底：按 calibration 对照（编译/运行/断言裁决）

## References

- 单元库：compiler_code_units.py「图算法-连通分量」
