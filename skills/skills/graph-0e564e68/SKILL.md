---
name: graph-0e564e68
description: >-
  图遍历 / 图遍历-BFS / 条件链组合——从条件出发 / BFS 遍 / 从起点出发可达的所有节点。用户提到这些词时使用本技能。
  场景：对照：条件链组合——从条件出发传播可达的规律（灵枢因果传播同构）。
  【不适用】Not for 以下场景：条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）
license: MIT
compatibility: >-
  graph 提供 neighbors 接口；start 为图中已存在节点
allowed-tools: Read Write Bash
metadata:
  version: "1.0"
  skill-author: 灵枢（AEIS）
  last-reviewed: "2026-08-29"
  kccs:
    trigger_words: ["图遍历", "图遍历-BFS", "条件链组合——从条件出发", "BFS 遍", "从起点出发可达的所有节点"]
    when: "graph 提供 neighbors 接口；start 为图中已存在节点"
    sub: ["① 起点入队并标记 ② 出队访问并入队未访问邻接"]
    execute: "队列 + 已访问集合，逐层扩展直至队空"
    not_applicable: ["条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）"]
  calibration: "对照：条件链组合——从条件出发传播可达的规律（灵枢因果传播同构）"
---

# 图遍历-BFS（graph-0e564e68）

## When to use

任务「图遍历」；对照：条件链组合——从条件出发传播可达的规律（灵枢因果传播同构）。

## 克制条款（不适用条件）

条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）

## How to execute

队列 + 已访问集合，逐层扩展直至队空

## Verification

- 单元样例 1 条（cases 断言）
- 物理基底：按 calibration 对照（编译/运行/断言裁决）

## References

- 单元库：compiler_code_units.py「图遍历-BFS」
