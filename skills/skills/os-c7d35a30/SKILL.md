---
name: os-c7d35a30
description: >-
  内存热插拔 / 内存-内存热插拔 / 内存热插拔——节点上线 / 下线 / online 上。用户提到这些词时使用本技能。
  场景：对照：内存热插拔——节点上线/下线（热添加内存）。
  【不适用】Not for 以下场景：op 非 {nodes, offline, online} 时
license: MIT
compatibility: >-
  op ∈ {nodes, offline, online}
allowed-tools: Read Write Bash
metadata:
  version: "1.0"
  skill-author: 灵枢（AEIS）
  last-reviewed: "2026-08-29"
  kccs:
    trigger_words: ["内存热插拔", "内存-内存热插拔", "内存热插拔——节点上线", "下线", "online 上"]
    when: "op ∈ {nodes, offline, online}"
    sub: ["① op 分支处理"]
    execute: "按 op 分派；顺序调用"
    not_applicable: ["op 非 {nodes, offline, online} 时"]
  calibration: "对照：内存热插拔——节点上线/下线（热添加内存）"
---

# 内存-内存热插拔（os-c7d35a30）

## When to use

任务「内存热插拔」；对照：内存热插拔——节点上线/下线（热添加内存）。

## 克制条款（不适用条件）

op 非 {nodes, offline, online} 时

## How to execute

按 op 分派；顺序调用

## Verification

- 单元样例 4 条（cases 断言）
- 物理基底：按 calibration 对照（编译/运行/断言裁决）

## References

- 单元库：compiler_code_units.py「内存-内存热插拔」
