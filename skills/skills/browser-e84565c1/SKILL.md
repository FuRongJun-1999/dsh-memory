---
name: browser-e84565c1
description: >-
  音频上下文 / 浏览器-音频上下文 / osc 振。用户提到这些词时使用本技能。
  场景：对照：Web Audio——振荡器/音量/启动。
  【不适用】Not for 以下场景：op 非 {gain, osc, start} 时
license: MIT
compatibility: >-
  op ∈ {gain, osc, start}
allowed-tools: Read Write Bash
metadata:
  version: "1.0"
  skill-author: 灵枢（AEIS）
  last-reviewed: "2026-08-29"
  kccs:
    trigger_words: ["音频上下文", "浏览器-音频上下文", "osc 振"]
    when: "op ∈ {gain, osc, start}"
    sub: ["① op 分支处理"]
    execute: "按 op 分派"
    not_applicable: ["op 非 {gain, osc, start} 时"]
  calibration: "对照：Web Audio——振荡器/音量/启动"
---

# 浏览器-音频上下文（browser-e84565c1）

## When to use

任务「音频上下文」；对照：Web Audio——振荡器/音量/启动。

## 克制条款（不适用条件）

op 非 {gain, osc, start} 时

## How to execute

按 op 分派

## Verification

- 单元样例 4 条（cases 断言）
- 物理基底：按 calibration 对照（编译/运行/断言裁决）

## References

- 单元库：compiler_code_units.py「浏览器-音频上下文」
