---
name: graph-7fe49de7
description: >-
  最大割 / 图算法-最大割 / MAX-CUT——贪 / 贪心二分使跨割边最多。用户提到这些词时使用本技能。
  场景：对照：MAX-CUT——贪心二分最大跨割边（近似）。
  【不适用】Not for 以下场景：条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）
license: MIT
compatibility: >-
  adj 为无向图邻接表（顶点可哈希）
allowed-tools: Read Write Bash
metadata:
  version: "1.0"
  skill-author: 灵枢（AEIS）
  last-reviewed: "2026-08-29"
  kccs:
    trigger_words: ["最大割", "图算法-最大割", "MAX-CUT——贪", "贪心二分使跨割边最多"]
    when: "adj 为无向图邻接表（顶点可哈希）"
    sub: ["① 交替着色分侧 ② 统计跨侧边数"]
    execute: "逐顶点按首个邻居反向着色，u<v 且异侧计数"
    not_applicable: ["条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）"]
  calibration: "对照：MAX-CUT——贪心二分最大跨割边（近似）"
---

# 图算法-最大割（graph-7fe49de7）

## When to use

任务「最大割」；对照：MAX-CUT——贪心二分最大跨割边（近似）。

## 克制条款（不适用条件）

条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）

## How to execute

逐顶点按首个邻居反向着色，u<v 且异侧计数

## Verification

- 单元样例 3 条（cases 断言）
- 物理基底：按 calibration 对照（编译/运行/断言裁决）

## References

- 单元库：compiler_code_units.py「图算法-最大割」
