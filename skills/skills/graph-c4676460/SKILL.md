---
name: graph-c4676460
description: >-
  图指标 / 图监控-指标统计 / 图监控——指标统计 / 节点数/边数/密度。用户提到这些词时使用本技能。
  场景：对照：图监控——指标统计（节点/边/密度）。
  【不适用】Not for 以下场景：条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）
license: MIT
compatibility: >-
  graph.neighbors 可用
allowed-tools: Read Write Bash
metadata:
  version: "1.0"
  skill-author: 灵枢（AEIS）
  last-reviewed: "2026-08-29"
  kccs:
    trigger_words: ["图指标", "图监控-指标统计", "图监控——指标统计", "节点数/边数/密度"]
    when: "graph.neighbors 可用"
    sub: ["① 调用 len；② 调用 sum；③ 调用 round"]
    execute: "顺序调用"
    not_applicable: ["条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）"]
  calibration: "对照：图监控——指标统计（节点/边/密度）"
---

# 图监控-指标统计（graph-c4676460）

## When to use

任务「图指标」；对照：图监控——指标统计（节点/边/密度）。

## 克制条款（不适用条件）

条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）

## How to execute

顺序调用

## Verification

- 单元样例 1 条（cases 断言）
- 物理基底：按 calibration 对照（编译/运行/断言裁决）

## References

- 单元库：compiler_code_units.py「图监控-指标统计」
