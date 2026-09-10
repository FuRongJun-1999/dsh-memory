---
name: graph-12cd830a
description: >-
  树重心 / 图算法-树重心 / 树重心——移除后最大子树 / 移除后最大子树最小 / 深度优先 / 统计子树大小并计算最大子。用户提到这些词时使用本技能。
  场景：对照：树重心——移除后最大子树最小（平衡点）。
  【不适用】Not for 以下场景：条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）
license: MIT
compatibility: >-
  adj 为树形无向图（n 个顶点连通无环）
allowed-tools: Read Write Bash
metadata:
  version: "1.0"
  skill-author: 灵枢（AEIS）
  last-reviewed: "2026-08-29"
  kccs:
    trigger_words: ["树重心", "图算法-树重心", "树重心——移除后最大子树", "移除后最大子树最小", "深度优先", "统计子树大小并计算最大子"]
    when: "adj 为树形无向图（n 个顶点连通无环）"
    sub: ["① DFS 统计子树大小 ② 计算各点最大子树 ③ 取最小者"]
    execute: "后序 DFS 收集 size，比较 max(子树, n-size) 取最小"
    not_applicable: ["条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）"]
  calibration: "对照：树重心——移除后最大子树最小（平衡点）"
---

# 图算法-树重心（graph-12cd830a）

## When to use

任务「树重心」；对照：树重心——移除后最大子树最小（平衡点）。

## 克制条款（不适用条件）

条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）

## How to execute

后序 DFS 收集 size，比较 max(子树, n-size) 取最小

## Verification

- 单元样例 3 条（cases 断言）
- 物理基底：按 calibration 对照（编译/运行/断言裁决）

## References

- 单元库：compiler_code_units.py「图算法-树重心」
