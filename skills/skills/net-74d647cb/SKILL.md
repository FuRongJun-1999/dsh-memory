---
name: net-74d647cb
description: >-
  连接迁移 / 网络-连接迁移 / QUIC——连 / migrate 换。用户提到这些词时使用本技能。
  场景：对照：QUIC——连接迁移（端点切换不断连）。
  【不适用】Not for 以下场景：op 非 {count, current, migrate} 时
license: MIT
compatibility: >-
  op ∈ {count, current, migrate}
allowed-tools: Read Write Bash
metadata:
  version: "1.0"
  skill-author: 灵枢（AEIS）
  last-reviewed: "2026-08-29"
  kccs:
    trigger_words: ["连接迁移", "网络-连接迁移", "QUIC——连", "migrate 换"]
    when: "op ∈ {count, current, migrate}"
    sub: ["① op 分支处理"]
    execute: "按 op 分派"
    not_applicable: ["op 非 {count, current, migrate} 时"]
  calibration: "对照：QUIC——连接迁移（端点切换不断连）"
---

# 网络-连接迁移（net-74d647cb）

## When to use

任务「连接迁移」；对照：QUIC——连接迁移（端点切换不断连）。

## 克制条款（不适用条件）

op 非 {count, current, migrate} 时

## How to execute

按 op 分派

## Verification

- 单元样例 4 条（cases 断言）
- 物理基底：按 calibration 对照（编译/运行/断言裁决）

## References

- 单元库：compiler_code_units.py「网络-连接迁移」
