---
name: net-99076a29
description: >-
  跳频 / 网络-跳频 / FHSS——跳 / hop 下。用户提到这些词时使用本技能。
  场景：对照：FHSS——跳频序列（抗干扰/保密）。
  【不适用】Not for 以下场景：op 非 {current, hop, pattern} 时
license: MIT
compatibility: >-
  op ∈ {current, hop, pattern}
allowed-tools: Read Write Bash
metadata:
  version: "1.0"
  skill-author: 灵枢（AEIS）
  last-reviewed: "2026-08-29"
  kccs:
    trigger_words: ["跳频", "网络-跳频", "FHSS——跳", "hop 下"]
    when: "op ∈ {current, hop, pattern}"
    sub: ["① op 分支处理"]
    execute: "按 op 分派；顺序调用"
    not_applicable: ["op 非 {current, hop, pattern} 时"]
  calibration: "对照：FHSS——跳频序列（抗干扰/保密）"
---

# 网络-跳频（net-99076a29）

## When to use

任务「跳频」；对照：FHSS——跳频序列（抗干扰/保密）。

## 克制条款（不适用条件）

op 非 {current, hop, pattern} 时

## How to execute

按 op 分派；顺序调用

## Verification

- 单元样例 4 条（cases 断言）
- 物理基底：按 calibration 对照（编译/运行/断言裁决）

## References

- 单元库：compiler_code_units.py「网络-跳频」
