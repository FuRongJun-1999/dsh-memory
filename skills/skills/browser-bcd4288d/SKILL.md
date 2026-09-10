---
name: browser-bcd4288d
description: >-
  图像生成 / 浏览器-图像生成 / generate 生。用户提到这些词时使用本技能。
  场景：对照：Image Generation——文本提示生成图像。
  【不适用】Not for 以下场景：op 非 {count, generate, last} 时
license: MIT
compatibility: >-
  op ∈ {count, generate, last}
allowed-tools: Read Write Bash
metadata:
  version: "1.0"
  skill-author: 灵枢（AEIS）
  last-reviewed: "2026-08-29"
  kccs:
    trigger_words: ["图像生成", "浏览器-图像生成", "generate 生"]
    when: "op ∈ {count, generate, last}"
    sub: ["① op 分支处理"]
    execute: "按 op 分派"
    not_applicable: ["op 非 {count, generate, last} 时"]
  calibration: "对照：Image Generation——文本提示生成图像"
---

# 浏览器-图像生成（browser-bcd4288d）

## When to use

任务「图像生成」；对照：Image Generation——文本提示生成图像。

## 克制条款（不适用条件）

op 非 {count, generate, last} 时

## How to execute

按 op 分派

## Verification

- 单元样例 4 条（cases 断言）
- 物理基底：按 calibration 对照（编译/运行/断言裁决）

## References

- 单元库：compiler_code_units.py「浏览器-图像生成」
