---
name: net-509b8001
description: >-
  流分类 / 网络-流分类 / 流量识别——按端口分类 / classify 分。用户提到这些词时使用本技能。
  场景：对照：流量识别——按端口分类（web/mail/other）。
  【不适用】Not for 以下场景：op 非 {classify, reset, stats} 时
license: MIT
compatibility: >-
  op ∈ {classify, reset, stats}
allowed-tools: Read Write Bash
metadata:
  version: "1.0"
  skill-author: 灵枢（AEIS）
  last-reviewed: "2026-08-29"
  kccs:
    trigger_words: ["流分类", "网络-流分类", "流量识别——按端口分类", "classify 分"]
    when: "op ∈ {classify, reset, stats}"
    sub: ["① op 分支处理"]
    execute: "按 op 分派；顺序调用"
    not_applicable: ["op 非 {classify, reset, stats} 时"]
  calibration: "对照：流量识别——按端口分类（web/mail/other）"
---

# 网络-流分类（net-509b8001）

## When to use

任务「流分类」；对照：流量识别——按端口分类（web/mail/other）。

## 克制条款（不适用条件）

op 非 {classify, reset, stats} 时

## How to execute

按 op 分派；顺序调用

## Verification

- 单元样例 4 条（cases 断言）
- 物理基底：按 calibration 对照（编译/运行/断言裁决）

## References

- 单元库：compiler_code_units.py「网络-流分类」
