---
name: graph-d40691ca
description: >-
  信息差收敛 / 条件路由图-信息差收敛 / 条件路由图——信息差收敛 / 沿路径逐节点缩小信息差。用户提到这些词时使用本技能。
  场景：对照：条件路由图——信息差收敛（逐节点减半，路由推进决策）。
  【不适用】Not for 以下场景：nxt 为空/非法时
license: MIT
compatibility: >-
  参数 graph/start/end/gap 合法
allowed-tools: Read Write Bash
metadata:
  version: "1.0"
  skill-author: 灵枢（AEIS）
  last-reviewed: "2026-08-29"
  kccs:
    trigger_words: ["信息差收敛", "条件路由图-信息差收敛", "条件路由图——信息差收敛", "沿路径逐节点缩小信息差"]
    when: "参数 graph/start/end/gap 合法"
    sub: ["① 调用 round；② 调用 len"]
    execute: "循环迭代；顺序调用"
    not_applicable: ["nxt 为空/非法时"]
  calibration: "对照：条件路由图——信息差收敛（逐节点减半，路由推进决策）"
---

# 条件路由图-信息差收敛（graph-d40691ca）

## When to use

任务「信息差收敛」；对照：条件路由图——信息差收敛（逐节点减半，路由推进决策）。

## 克制条款（不适用条件）

nxt 为空/非法时

## How to execute

循环迭代；顺序调用

## Verification

- 单元样例 3 条（cases 断言）
- 物理基底：按 calibration 对照（编译/运行/断言裁决）

## References

- 单元库：compiler_code_units.py「条件路由图-信息差收敛」
