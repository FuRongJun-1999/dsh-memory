---
name: os-5192621b
description: >-
  能力系统 / 安全-能力系统 / OS 安 / 能力 / 特权令牌。用户提到这些词时使用本技能。
  场景：对照：OS 安全——能力系统（特权令牌授予/检查/撤销，最小权限）。
  【不适用】Not for 以下场景：op 非 {check, grant, revoke} 时
license: MIT
compatibility: >-
  op ∈ {check, grant, revoke}；caps.discard 可用
allowed-tools: Read Write Bash
metadata:
  version: "1.0"
  skill-author: 灵枢（AEIS）
  last-reviewed: "2026-08-29"
  kccs:
    trigger_words: ["能力系统", "安全-能力系统", "OS 安", "能力", "特权令牌"]
    when: "op ∈ {check, grant, revoke}；caps.discard 可用"
    sub: ["① op 分支处理"]
    execute: "按 op 分派"
    not_applicable: ["op 非 {check, grant, revoke} 时"]
  calibration: "对照：OS 安全——能力系统（特权令牌授予/检查/撤销，最小权限）"
---

# 安全-能力系统（os-5192621b）

## When to use

任务「能力系统」；对照：OS 安全——能力系统（特权令牌授予/检查/撤销，最小权限）。

## 克制条款（不适用条件）

op 非 {check, grant, revoke} 时

## How to execute

按 op 分派

## Verification

- 单元样例 4 条（cases 断言）
- 物理基底：按 calibration 对照（编译/运行/断言裁决）

## References

- 单元库：compiler_code_units.py「安全-能力系统」
