---
name: net-0f2850e0
description: >-
  API限流 / 网络-API限流 / API 网 / API 限 / use 消。用户提到这些词时使用本技能。
  场景：对照：API 网关——每用户配额限流（超额拒绝）。
  【不适用】Not for 以下场景：op 非 {check, use} 时
license: MIT
compatibility: >-
  op ∈ {check, use}
allowed-tools: Read Write Bash
metadata:
  version: "1.0"
  skill-author: 灵枢（AEIS）
  last-reviewed: "2026-08-29"
  kccs:
    trigger_words: ["API限流", "网络-API限流", "API 网", "API 限", "use 消"]
    when: "op ∈ {check, use}"
    sub: ["① op 分支处理"]
    execute: "按 op 分派"
    not_applicable: ["op 非 {check, use} 时"]
  calibration: "对照：API 网关——每用户配额限流（超额拒绝）"
---

# 网络-API限流（net-0f2850e0）

## When to use

任务「API限流」；对照：API 网关——每用户配额限流（超额拒绝）。

## 克制条款（不适用条件）

op 非 {check, use} 时

## How to execute

按 op 分派

## Verification

- 单元样例 4 条（cases 断言）
- 物理基底：按 calibration 对照（编译/运行/断言裁决）

## References

- 单元库：compiler_code_units.py「网络-API限流」
