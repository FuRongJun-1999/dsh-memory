---
name: browser-ff94a671
description: >-
  提示词 / 浏览器-提示词 / set 设。用户提到这些词时使用本技能。
  场景：对照：Prompt API——提示词设置/读取/清除。
  【不适用】Not for 以下场景：op 非 {clear, get, set} 时
license: MIT
compatibility: >-
  op ∈ {clear, get, set}
allowed-tools: Read Write Bash
metadata:
  version: "1.0"
  skill-author: 灵枢（AEIS）
  last-reviewed: "2026-08-29"
  kccs:
    trigger_words: ["提示词", "浏览器-提示词", "set 设"]
    when: "op ∈ {clear, get, set}"
    sub: ["① op 分支处理"]
    execute: "按 op 分派"
    not_applicable: ["op 非 {clear, get, set} 时"]
  calibration: "对照：Prompt API——提示词设置/读取/清除"
---

# 浏览器-提示词（browser-ff94a671）

## When to use

任务「提示词」；对照：Prompt API——提示词设置/读取/清除。

## 克制条款（不适用条件）

op 非 {clear, get, set} 时

## How to execute

按 op 分派

## Verification

- 单元样例 4 条（cases 断言）
- 物理基底：按 calibration 对照（编译/运行/断言裁决）

## References

- 单元库：compiler_code_units.py「浏览器-提示词」
