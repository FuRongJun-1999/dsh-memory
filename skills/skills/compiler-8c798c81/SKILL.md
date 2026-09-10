---
name: compiler-8c798c81
description: >-
  转义序列 / 词法-转义序列 / 词法——转义序列。用户提到这些词时使用本技能。
  场景：对照：词法——转义序列（反斜杠n反斜杠t反斜杠引号 解码）。
  【不适用】Not for 以下场景：nxt 非 {n, t} 时
license: MIT
compatibility: >-
  nxt ∈ {n, t}
allowed-tools: Read Write Bash
metadata:
  version: "1.0"
  skill-author: 灵枢（AEIS）
  last-reviewed: "2026-08-29"
  kccs:
    trigger_words: ["转义序列", "词法-转义序列", "词法——转义序列"]
    when: "nxt ∈ {n, t}"
    sub: ["1 nxt 分支处理"]
    execute: "按 op 分派；循环迭代；顺序调用"
    not_applicable: ["nxt 非 {n, t} 时"]
  calibration: "对照：词法——转义序列（反斜杠n反斜杠t反斜杠引号 解码）"
---

# 词法-转义序列（compiler-8c798c81）

## When to use

任务「转义序列」；对照：词法——转义序列（反斜杠n反斜杠t反斜杠引号 解码）。

## 克制条款（不适用条件）

nxt 非 {n, t} 时

## How to execute

按 op 分派；循环迭代；顺序调用

## Verification

- 单元样例 3 条（cases 断言）
- 物理基底：按 calibration 对照（编译/运行/断言裁决）

## References

- 单元库：compiler_code_units.py「词法-转义序列」
