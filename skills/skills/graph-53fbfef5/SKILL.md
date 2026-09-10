---
name: graph-53fbfef5
description: >-
  最短路径 / 图遍历-最短路径 / BFS 逐。用户提到这些词时使用本技能。
  场景：对照：条件链最短路径——BFS 最少跳数（两链中取最短；反向无路返回 None）。
  【不适用】Not for 以下场景：条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）
license: MIT
compatibility: >-
  graph 提供 neighbors 接口；start/end 为图中节点
allowed-tools: Read Write Bash
metadata:
  version: "1.0"
  skill-author: 灵枢（AEIS）
  last-reviewed: "2026-08-29"
  kccs:
    trigger_words: ["最短路径", "图遍历-最短路径", "BFS 逐"]
    when: "graph 提供 neighbors 接口；start/end 为图中节点"
    sub: ["① BFS 逐层扩散 ② 记录前驱 ③ 终点回溯还原路径"]
    execute: "队列扩散 + prev 链回溯"
    not_applicable: ["条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）"]
  calibration: "对照：条件链最短路径——BFS 最少跳数（两链中取最短；反向无路返回 None）"
---

# 图遍历-最短路径（graph-53fbfef5）

## When to use

任务「最短路径」；对照：条件链最短路径——BFS 最少跳数（两链中取最短；反向无路返回 None）。

## 克制条款（不适用条件）

条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）

## How to execute

队列扩散 + prev 链回溯

## Verification

- 单元样例 2 条（cases 断言）
- 物理基底：按 calibration 对照（编译/运行/断言裁决）

## References

- 单元库：compiler_code_units.py「图遍历-最短路径」
