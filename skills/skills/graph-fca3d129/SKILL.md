---
name: graph-fca3d129
description: >-
  图事务 / 图存储-事务 / commit 生 / rollback 回 / 图数据库事务 / begin 快。用户提到这些词时使用本技能。
  场景：对照：图数据库事务——begin 快照/commit 生效/rollback 回滚（ACID 原子性语义）。
  【不适用】Not for 以下场景：op 非 {begin, commit, rollback} 时（隐式盲区：返回默认值 idle = 未知行为——不适用）
license: MIT
compatibility: >-
  state 为图存储状态；op ∈ {begin, commit, rollback}
allowed-tools: Read Write Bash
metadata:
  version: "1.0"
  skill-author: 灵枢（AEIS）
  last-reviewed: "2026-08-29"
  kccs:
    trigger_words: ["图事务", "图存储-事务", "commit 生", "rollback 回", "图数据库事务", "begin 快"]
    when: "state 为图存储状态；op ∈ {begin, commit, rollback}"
    sub: ["① begin 深拷贝快照 ② commit 清除快照 ③ rollback 恢复快照"]
    execute: "快照字典深拷贝 + 按 op 分派"
    not_applicable: ["op 非 {begin, commit, rollback} 时（隐式盲区：返回默认值 idle = 未知行为——不适用）"]
  calibration: "对照：图数据库事务——begin 快照/commit 生效/rollback 回滚（ACID 原子性语义）"
---

# 图存储-事务（graph-fca3d129）

## When to use

任务「图事务」；对照：图数据库事务——begin 快照/commit 生效/rollback 回滚（ACID 原子性语义）。

## 克制条款（不适用条件）

op 非 {begin, commit, rollback} 时（隐式盲区：返回默认值 idle = 未知行为——不适用）

## How to execute

快照字典深拷贝 + 按 op 分派

## Verification

- 单元样例 3 条（cases 断言）
- 物理基底：按 calibration 对照（编译/运行/断言裁决）

## References

- 单元库：compiler_code_units.py「图存储-事务」
