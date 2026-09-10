---
name: browser-77a97b43
description: >-
  存储配额 / 浏览器-存储配额 / estimate 估。用户提到这些词时使用本技能。
  场景：对照：Storage Quota——存储用量估算与占用比。
  【不适用】Not for 以下场景：op 非 {estimate, percent, usage} 时
license: MIT
compatibility: >-
  op ∈ {estimate, percent, usage}
allowed-tools: Read Write Bash
metadata:
  version: "1.0"
  skill-author: 灵枢（AEIS）
  last-reviewed: "2026-08-29"
  kccs:
    trigger_words: ["存储配额", "浏览器-存储配额", "estimate 估"]
    when: "op ∈ {estimate, percent, usage}"
    sub: ["① op 分支处理"]
    execute: "按 op 分派；顺序调用"
    not_applicable: ["op 非 {estimate, percent, usage} 时"]
  calibration: "对照：Storage Quota——存储用量估算与占用比"
---

# 浏览器-存储配额（browser-77a97b43）

## When to use

任务「存储配额」；对照：Storage Quota——存储用量估算与占用比。

## 克制条款（不适用条件）

op 非 {estimate, percent, usage} 时

## How to execute

按 op 分派；顺序调用

## Verification

- 单元样例 4 条（cases 断言）
- 物理基底：按 calibration 对照（编译/运行/断言裁决）

## References

- 单元库：compiler_code_units.py「浏览器-存储配额」
