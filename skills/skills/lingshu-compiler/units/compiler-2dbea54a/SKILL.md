---
name: compiler-2dbea54a
description: >-
  循环检测 / 分析-循环检测 / DFS 三 / 深度优先 / 标记灰后探邻接。用户提到这些词时使用本技能。
  场景：对照：图分析——DFS 三色循环检测（回灰边即环）。
  【不适用】Not for 以下场景：条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）
license: MIT
compatibility: >-
  参数 adj 合法
allowed-tools: Read Write Bash
metadata:
  version: "1.0"
  skill-author: 灵枢（AEIS）
  last-reviewed: "2026-08-29"
  kccs:
    trigger_words: ["循环检测", "分析-循环检测", "DFS 三", "深度优先", "标记灰后探邻接"]
    when: "参数 adj 合法"
    sub: ["① 调用 dfs"]
    execute: "循环迭代；顺序调用"
    not_applicable: ["条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）"]
  calibration: "对照：图分析——DFS 三色循环检测（回灰边即环）"
---

# 分析-循环检测（compiler-2dbea54a）

## When to use

任务「循环检测」；对照：图分析——DFS 三色循环检测（回灰边即环）。

## 克制条款（不适用条件）

条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）

## How to execute

循环迭代；顺序调用

## Verification

- 单元样例 3 条（cases 断言）
- 物理基底：按 calibration 对照（编译/运行/断言裁决）

## References

- 单元库：compiler_code_units.py「分析-循环检测」
