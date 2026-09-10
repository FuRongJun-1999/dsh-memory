---
name: graph-fd02d934
description: >-
  读写分离 / 运维-读写分离 / 数据库读写分离——主库写 / 从库读 / 写→主库并同步从库 / 。用户提到这些词时使用本技能。
  场景：对照：数据库读写分离——主库写+同步从库，从库读（负载分散）。
  【不适用】Not for 以下场景：op 非 {read, write} 时
license: MIT
compatibility: >-
  op ∈ {read, write}
allowed-tools: Read Write Bash
metadata:
  version: "1.0"
  skill-author: 灵枢（AEIS）
  last-reviewed: "2026-08-29"
  kccs:
    trigger_words: ["读写分离", "运维-读写分离", "数据库读写分离——主库写", "从库读", "写→主库并同步从库 / "]
    when: "op ∈ {read, write}"
    sub: ["① op 分支处理"]
    execute: "按 op 分派；循环迭代；顺序调用"
    not_applicable: ["op 非 {read, write} 时"]
  calibration: "对照：数据库读写分离——主库写+同步从库，从库读（负载分散）"
---

# 运维-读写分离（graph-fd02d934）

## When to use

任务「读写分离」；对照：数据库读写分离——主库写+同步从库，从库读（负载分散）。

## 克制条款（不适用条件）

op 非 {read, write} 时

## How to execute

按 op 分派；循环迭代；顺序调用

## Verification

- 单元样例 3 条（cases 断言）
- 物理基底：按 calibration 对照（编译/运行/断言裁决）

## References

- 单元库：compiler_code_units.py「运维-读写分离」
