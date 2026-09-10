---
name: net-74e8a576
description: >-
  尽力交付 / 网络-尽力交付 / UDP 尽 / 可丢包 / send 发。用户提到这些词时使用本技能。
  场景：对照：UDP 尽力交付——无确认/可丢包（不可靠传输语义）。
  【不适用】Not for 以下场景：op 非 {delivered, drop, send} 时
license: MIT
compatibility: >-
  op ∈ {delivered, drop, send}
allowed-tools: Read Write Bash
metadata:
  version: "1.0"
  skill-author: 灵枢（AEIS）
  last-reviewed: "2026-08-29"
  kccs:
    trigger_words: ["尽力交付", "网络-尽力交付", "UDP 尽", "可丢包", "send 发"]
    when: "op ∈ {delivered, drop, send}"
    sub: ["① op 分支处理"]
    execute: "按 op 分派；顺序调用"
    not_applicable: ["op 非 {delivered, drop, send} 时"]
  calibration: "对照：UDP 尽力交付——无确认/可丢包（不可靠传输语义）"
---

# 网络-尽力交付（net-74e8a576）

## When to use

任务「尽力交付」；对照：UDP 尽力交付——无确认/可丢包（不可靠传输语义）。

## 克制条款（不适用条件）

op 非 {delivered, drop, send} 时

## How to execute

按 op 分派；顺序调用

## Verification

- 单元样例 4 条（cases 断言）
- 物理基底：按 calibration 对照（编译/运行/断言裁决）

## References

- 单元库：compiler_code_units.py「网络-尽力交付」
