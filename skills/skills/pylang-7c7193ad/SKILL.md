---
name: pylang-7c7193ad
description: >-
  对象组合 / 面向对象-组合 / Python 组 / 组合 / 对象含对象。用户提到这些词时使用本技能。
  场景：对照：Python 组合——has-a 关系（对象含对象，方法委托转发）。
  【不适用】Not for 以下场景：op 非 {add, call} 时
license: MIT
compatibility: >-
  op ∈ {add, call}；add 时 name/part 提供，call 时 name/method 提供
allowed-tools: Read Write Bash
metadata:
  version: "1.0"
  skill-author: 灵枢（AEIS）
  last-reviewed: "2026-08-29"
  kccs:
    trigger_words: ["对象组合", "面向对象-组合", "Python 组", "组合", "对象含对象"]
    when: "op ∈ {add, call}；add 时 name/part 提供，call 时 name/method 提供"
    sub: ["① add 添加部件 ② call 转发部件方法"]
    execute: "按 op 分派字典/方法调用"
    not_applicable: ["op 非 {add, call} 时"]
  calibration: "对照：Python 组合——has-a 关系（对象含对象，方法委托转发）"
---

# 面向对象-组合（pylang-7c7193ad）

## When to use

任务「对象组合」；对照：Python 组合——has-a 关系（对象含对象，方法委托转发）。

## 克制条款（不适用条件）

op 非 {add, call} 时

## How to execute

按 op 分派字典/方法调用

## Verification

- 单元样例 3 条（cases 断言）
- 物理基底：按 calibration 对照（编译/运行/断言裁决）

## References

- 单元库：compiler_code_units.py「面向对象-组合」
