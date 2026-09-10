---
name: graph-3d255ed4
description: >-
  条件链查询 / 图查询-条件链 / 从条件出发沿边收集完整链 / 递归走链 / 无后继时记录完整条件链。用户提到这些词时使用本技能。
  场景：对照：图查询语言——变长路径 MATCH (a)-[*]->(b)：从条件出发的完整条件链集合。
  【不适用】Not for 以下场景：succ 为空/非法时
license: MIT
compatibility: >-
  graph 提供 neighbors 接口；condition 为起始条件节点
allowed-tools: Read Write Bash
metadata:
  version: "1.0"
  skill-author: 灵枢（AEIS）
  last-reviewed: "2026-08-29"
  kccs:
    trigger_words: ["条件链查询", "图查询-条件链", "从条件出发沿边收集完整链", "递归走链", "无后继时记录完整条件链"]
    when: "graph 提供 neighbors 接口；condition 为起始条件节点"
    sub: ["① 递归沿边走链 ② 无后继记录完整链 ③ 超长截断"]
    execute: "DFS 回溯 + max_len 剪枝，收集全部条件链"
    not_applicable: ["succ 为空/非法时"]
  calibration: "对照：图查询语言——变长路径 MATCH (a)-[*]->(b)：从条件出发的完整条件链集合"
---

# 图查询-条件链（graph-3d255ed4）

## When to use

任务「条件链查询」；对照：图查询语言——变长路径 MATCH (a)-[*]->(b)：从条件出发的完整条件链集合。

## 克制条款（不适用条件）

succ 为空/非法时

## How to execute

DFS 回溯 + max_len 剪枝，收集全部条件链

## Verification

- 单元样例 1 条（cases 断言）
- 物理基底：按 calibration 对照（编译/运行/断言裁决）

## References

- 单元库：compiler_code_units.py「图查询-条件链」
