---
name: os-3db42aac
description: >-
  网络接口 / 系统-网络接口 / configure 配。用户提到这些词时使用本技能。
  场景：对照：OS 网络栈——网卡接口配置/状态/启停。
  【不适用】Not for 以下场景：op 非 {configure, set_state, status} 时
license: MIT
compatibility: >-
  op ∈ {configure, set_state, status}
allowed-tools: Read Write Bash
metadata:
  version: "1.0"
  skill-author: 灵枢（AEIS）
  last-reviewed: "2026-08-29"
  kccs:
    trigger_words: ["网络接口", "系统-网络接口", "configure 配"]
    when: "op ∈ {configure, set_state, status}"
    sub: ["① op 分支处理"]
    execute: "按 op 分派"
    not_applicable: ["op 非 {configure, set_state, status} 时"]
  calibration: "对照：OS 网络栈——网卡接口配置/状态/启停"
---

# 系统-网络接口（os-3db42aac）

## When to use

任务「网络接口」；对照：OS 网络栈——网卡接口配置/状态/启停。

## 克制条款（不适用条件）

op 非 {configure, set_state, status} 时

## How to execute

按 op 分派

## Verification

- 单元样例 4 条（cases 断言）
- 物理基底：按 calibration 对照（编译/运行/断言裁决）

## References

- 单元库：compiler_code_units.py「系统-网络接口」
