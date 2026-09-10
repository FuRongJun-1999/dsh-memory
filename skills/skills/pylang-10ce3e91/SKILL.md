---
name: pylang-10ce3e91
description: >-
  迭代工具 / 工具-迭代工具 / chain 拼。用户提到这些词时使用本技能。
  场景：对照：itertools——chain 拼接/take 截取/zip 配对。
  【不适用】Not for 以下场景：op 非 {chain, take, zip} 时
license: MIT
compatibility: >-
  op ∈ {chain, take, zip}
allowed-tools: Read Write Bash
metadata:
  version: "1.0"
  skill-author: 灵枢（AEIS）
  last-reviewed: "2026-08-29"
  kccs:
    trigger_words: ["迭代工具", "工具-迭代工具", "chain 拼"]
    when: "op ∈ {chain, take, zip}"
    sub: ["① op 分支处理"]
    execute: "按 op 分派；循环迭代；顺序调用"
    not_applicable: ["op 非 {chain, take, zip} 时"]
  calibration: "对照：itertools——chain 拼接/take 截取/zip 配对"
---

# 工具-迭代工具（pylang-10ce3e91）

## When to use

任务「迭代工具」；对照：itertools——chain 拼接/take 截取/zip 配对。

## 克制条款（不适用条件）

op 非 {chain, take, zip} 时

## How to execute

按 op 分派；循环迭代；顺序调用

## Verification

- 单元样例 3 条（cases 断言）
- 物理基底：按 calibration 对照（编译/运行/断言裁决）

## References

- 单元库：compiler_code_units.py「工具-迭代工具」
