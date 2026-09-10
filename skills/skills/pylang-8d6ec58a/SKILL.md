---
name: pylang-8d6ec58a
description: >-
  位掩码 / 工具-位掩码 / clear / toggle / test / set 置。用户提到这些词时使用本技能。
  场景：对照：位标志——set/clear/toggle/test（位掩码）。
  【不适用】Not for 以下场景：op 非 {clear, set, test, toggle} 时
license: MIT
compatibility: >-
  op ∈ {clear, set, test, toggle}
allowed-tools: Read Write Bash
metadata:
  version: "1.0"
  skill-author: 灵枢（AEIS）
  last-reviewed: "2026-08-29"
  kccs:
    trigger_words: ["位掩码", "工具-位掩码", "clear", "toggle", "test", "set 置"]
    when: "op ∈ {clear, set, test, toggle}"
    sub: ["① op 分支处理"]
    execute: "按 op 分派；顺序调用"
    not_applicable: ["op 非 {clear, set, test, toggle} 时"]
  calibration: "对照：位标志——set/clear/toggle/test（位掩码）"
---

# 工具-位掩码（pylang-8d6ec58a）

## When to use

任务「位掩码」；对照：位标志——set/clear/toggle/test（位掩码）。

## 克制条款（不适用条件）

op 非 {clear, set, test, toggle} 时

## How to execute

按 op 分派；顺序调用

## Verification

- 单元样例 4 条（cases 断言）
- 物理基底：按 calibration 对照（编译/运行/断言裁决）

## References

- 单元库：compiler_code_units.py「工具-位掩码」
