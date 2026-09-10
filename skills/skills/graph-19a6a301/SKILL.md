---
name: graph-19a6a301
description: >-
  快照版本 / 图存储-快照版本 / 图数据库版本管理——快照 / 回溯 / 图版本快照 / 保存/回溯。用户提到这些词时使用本技能。
  场景：对照：图数据库版本管理——快照保存/回溯（时间点恢复）。
  【不适用】Not for 以下场景：op 非 {list, restore, save} 时
license: MIT
compatibility: >-
  op ∈ {list, restore, save}
allowed-tools: Read Write Bash
metadata:
  version: "1.0"
  skill-author: 灵枢（AEIS）
  last-reviewed: "2026-08-29"
  kccs:
    trigger_words: ["快照版本", "图存储-快照版本", "图数据库版本管理——快照", "回溯", "图版本快照", "保存/回溯"]
    when: "op ∈ {list, restore, save}"
    sub: ["① op 分支处理"]
    execute: "按 op 分派；顺序调用"
    not_applicable: ["op 非 {list, restore, save} 时"]
  calibration: "对照：图数据库版本管理——快照保存/回溯（时间点恢复）"
---

# 图存储-快照版本（graph-19a6a301）

## When to use

任务「快照版本」；对照：图数据库版本管理——快照保存/回溯（时间点恢复）。

## 克制条款（不适用条件）

op 非 {list, restore, save} 时

## How to execute

按 op 分派；顺序调用

## Verification

- 单元样例 3 条（cases 断言）
- 物理基底：按 calibration 对照（编译/运行/断言裁决）

## References

- 单元库：compiler_code_units.py「图存储-快照版本」
