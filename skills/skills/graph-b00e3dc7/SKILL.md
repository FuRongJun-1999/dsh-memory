---
name: graph-b00e3dc7
description: >-
  子图匹配 / 图查询-子图匹配 / 图查询——子图模式匹配 / 图查询 / 模式子图匹配, ...] / 所有边都在图中存在 → 。用户提到这些词时使用本技能。
  场景：对照：图查询——子图模式匹配（模式边全部存在=匹配；缺边=不匹配）。
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
    trigger_words: ["子图匹配", "图查询-子图匹配", "图查询——子图模式匹配", "图查询", "模式子图匹配, ...]", "所有边都在图中存在 → "]
    when: "graph.neighbors 可用"
    sub: ["① 条件判定 ② 结果处理"]
    execute: "循环迭代"
    not_applicable: ["条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）"]
  calibration: "对照：图查询——子图模式匹配（模式边全部存在=匹配；缺边=不匹配）"
---

# 图查询-子图匹配（graph-b00e3dc7）

## When to use

任务「子图匹配」；对照：图查询——子图模式匹配（模式边全部存在=匹配；缺边=不匹配）。

## 克制条款（不适用条件）

条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）

## How to execute

循环迭代

## Verification

- 单元样例 2 条（cases 断言）
- 物理基底：按 calibration 对照（编译/运行/断言裁决）

## References

- 单元库：compiler_code_units.py「图查询-子图匹配」
