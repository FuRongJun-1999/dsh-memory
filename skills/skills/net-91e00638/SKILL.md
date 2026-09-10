---
name: net-91e00638
description: >-
  序列号回绕 / 网络-序列号回绕 / TCP 序 / 回绕比较 / next 推。用户提到这些词时使用本技能。
  场景：对照：TCP 序列号——回绕推进/回绕比较（2^32 空间）。
  【不适用】Not for 以下场景：op 非 {compare, next, wrap} 时
license: MIT
compatibility: >-
  op ∈ {compare, next, wrap}
allowed-tools: Read Write Bash
metadata:
  version: "1.0"
  skill-author: 灵枢（AEIS）
  last-reviewed: "2026-08-29"
  kccs:
    trigger_words: ["序列号回绕", "网络-序列号回绕", "TCP 序", "回绕比较", "next 推"]
    when: "op ∈ {compare, next, wrap}"
    sub: ["① op 分支处理"]
    execute: "按 op 分派"
    not_applicable: ["op 非 {compare, next, wrap} 时"]
  calibration: "对照：TCP 序列号——回绕推进/回绕比较（2^32 空间）"
---

# 网络-序列号回绕（net-91e00638）

## When to use

任务「序列号回绕」；对照：TCP 序列号——回绕推进/回绕比较（2^32 空间）。

## 克制条款（不适用条件）

op 非 {compare, next, wrap} 时

## How to execute

按 op 分派

## Verification

- 单元样例 5 条（cases 断言）
- 物理基底：按 calibration 对照（编译/运行/断言裁决）

## References

- 单元库：compiler_code_units.py「网络-序列号回绕」
