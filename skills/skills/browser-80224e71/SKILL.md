---
name: browser-80224e71
description: >-
  全屏模式 / 浏览器-全屏模式 / enter 元。用户提到这些词时使用本技能。
  场景：对照：Fullscreen API——元素全屏进入/退出。
  【不适用】Not for 以下场景：op 非 {enter, exit} 时
license: MIT
compatibility: >-
  op ∈ {enter, exit}
allowed-tools: Read Write Bash
metadata:
  version: "1.0"
  skill-author: 灵枢（AEIS）
  last-reviewed: "2026-08-29"
  kccs:
    trigger_words: ["全屏模式", "浏览器-全屏模式", "enter 元"]
    when: "op ∈ {enter, exit}"
    sub: ["① op 分支处理"]
    execute: "按 op 分派"
    not_applicable: ["op 非 {enter, exit} 时"]
  calibration: "对照：Fullscreen API——元素全屏进入/退出"
---

# 浏览器-全屏模式（browser-80224e71）

## When to use

任务「全屏模式」；对照：Fullscreen API——元素全屏进入/退出。

## 克制条款（不适用条件）

op 非 {enter, exit} 时

## How to execute

按 op 分派

## Verification

- 单元样例 3 条（cases 断言）
- 物理基底：按 calibration 对照（编译/运行/断言裁决）

## References

- 单元库：compiler_code_units.py「浏览器-全屏模式」
