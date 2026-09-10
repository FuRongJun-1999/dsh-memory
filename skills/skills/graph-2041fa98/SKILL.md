---
name: graph-2041fa98
description: >-
  一致性快照 / 图存储-一致性快照 / MVCC 快 / 版本化读写。用户提到这些词时使用本技能。
  场景：对照：MVCC 快照隔离——版本化读写（读旧版本一致视图）。
  【不适用】Not for 以下场景：kv 为空/非法时；op 非 {read, write} 时
license: MIT
compatibility: >-
  op ∈ {read, write}
allowed-tools: Read Write Bash
metadata:
  version: "1.0"
  skill-author: 灵枢（AEIS）
  last-reviewed: "2026-08-29"
  kccs:
    trigger_words: ["一致性快照", "图存储-一致性快照", "MVCC 快", "版本化读写"]
    when: "op ∈ {read, write}"
    sub: ["① op 分支处理"]
    execute: "按 op 分派；顺序调用"
    not_applicable: ["kv 为空/非法时；op 非 {read, write} 时"]
  calibration: "对照：MVCC 快照隔离——版本化读写（读旧版本一致视图）"
---

# 图存储-一致性快照（graph-2041fa98）

## When to use

任务「一致性快照」；对照：MVCC 快照隔离——版本化读写（读旧版本一致视图）。

## 克制条款（不适用条件）

kv 为空/非法时；op 非 {read, write} 时

## How to execute

按 op 分派；顺序调用

## Verification

- 单元样例 4 条（cases 断言）
- 物理基底：按 calibration 对照（编译/运行/断言裁决）

## References

- 单元库：compiler_code_units.py「图存储-一致性快照」
