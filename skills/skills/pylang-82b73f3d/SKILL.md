---
name: pylang-82b73f3d
description: >-
  字符串判断 / 工具-字符串判断 / Python 字。用户提到这些词时使用本技能。
  场景：对照：Python 字符串方法族（isdigit/startswith/isupper）。
  【不适用】Not for 以下场景：op 非 {isdigit, isupper, startswith} 时
license: MIT
compatibility: >-
  op ∈ {isdigit, isupper, startswith}；text.isdigit 可用；text.startswith 可用
allowed-tools: Read Write Bash
metadata:
  version: "1.0"
  skill-author: 灵枢（AEIS）
  last-reviewed: "2026-08-29"
  kccs:
    trigger_words: ["字符串判断", "工具-字符串判断", "Python 字"]
    when: "op ∈ {isdigit, isupper, startswith}；text.isdigit 可用；text.startswith 可用"
    sub: ["① op 分支处理"]
    execute: "按 op 分派"
    not_applicable: ["op 非 {isdigit, isupper, startswith} 时"]
  calibration: "对照：Python 字符串方法族（isdigit/startswith/isupper）"
---

# 工具-字符串判断（pylang-82b73f3d）

## When to use

任务「字符串判断」；对照：Python 字符串方法族（isdigit/startswith/isupper）。

## 克制条款（不适用条件）

op 非 {isdigit, isupper, startswith} 时

## How to execute

按 op 分派

## Verification

- 单元样例 5 条（cases 断言）
- 物理基底：按 calibration 对照（编译/运行/断言裁决）

## References

- 单元库：compiler_code_units.py「工具-字符串判断」
