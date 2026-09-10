---
name: graph-a125d282
description: >-
  可达性判定 / 图查询-可达性判定 / BFS 可 / BFS 从。用户提到这些词时使用本技能。
  场景：对照：BFS 可达性——条件链传导判定（起点→目标能否到达）。
  【不适用】Not for 以下场景：条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）
license: MIT
compatibility: >-
  参数 graph/start/target 合法
allowed-tools: Read Write Bash
metadata:
  version: "1.0"
  skill-author: 灵枢（AEIS）
  last-reviewed: "2026-08-29"
  kccs:
    trigger_words: ["可达性判定", "图查询-可达性判定", "BFS 可", "BFS 从"]
    when: "参数 graph/start/target 合法"
    sub: ["① 条件判定 ② 结果处理"]
    execute: "循环迭代"
    not_applicable: ["条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）"]
  calibration: "对照：BFS 可达性——条件链传导判定（起点→目标能否到达）"
---

# 图查询-可达性判定（graph-a125d282）

## When to use

任务「可达性判定」；对照：BFS 可达性——条件链传导判定（起点→目标能否到达）。

## 克制条款（不适用条件）

条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）

## How to execute

循环迭代

## Verification

- 单元样例 4 条（cases 断言）
- 物理基底：按 calibration 对照（编译/运行/断言裁决）

## References

- 单元库：compiler_code_units.py「图查询-可达性判定」
