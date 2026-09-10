---
name: browser-09e60b35
description: >-
  画中画 / 浏览器-画中画 / open 打。用户提到这些词时使用本技能。
  场景：对照：Picture-in-Picture——画中画窗口开关。
  【不适用】Not for 以下场景：op 非 {active, close, open} 时
license: MIT
compatibility: >-
  op ∈ {active, close, open}
allowed-tools: Read Write Bash
metadata:
  version: "1.0"
  skill-author: 灵枢（AEIS）
  last-reviewed: "2026-08-29"
  kccs:
    trigger_words: ["画中画", "浏览器-画中画", "open 打"]
    when: "op ∈ {active, close, open}"
    sub: ["① op 分支处理"]
    execute: "按 op 分派"
    not_applicable: ["op 非 {active, close, open} 时"]
  calibration: "对照：Picture-in-Picture——画中画窗口开关"
---

# 浏览器-画中画（browser-09e60b35）

## When to use

任务「画中画」；对照：Picture-in-Picture——画中画窗口开关。

## 克制条款（不适用条件）

op 非 {active, close, open} 时

## How to execute

按 op 分派

## Verification

- 单元样例 4 条（cases 断言）
- 物理基底：按 calibration 对照（编译/运行/断言裁决）

## References

- 单元库：compiler_code_units.py「浏览器-画中画」
