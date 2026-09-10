---
name: browser-59a0ada4
description: >-
  语音合成 / 浏览器-语音合成 / speak 朗。用户提到这些词时使用本技能。
  场景：对照：SpeechSynthesis——文本朗读/暂停/继续。
  【不适用】Not for 以下场景：op 非 {pause, resume, speak} 时
license: MIT
compatibility: >-
  op ∈ {pause, resume, speak}
allowed-tools: Read Write Bash
metadata:
  version: "1.0"
  skill-author: 灵枢（AEIS）
  last-reviewed: "2026-08-29"
  kccs:
    trigger_words: ["语音合成", "浏览器-语音合成", "speak 朗"]
    when: "op ∈ {pause, resume, speak}"
    sub: ["① op 分支处理"]
    execute: "按 op 分派"
    not_applicable: ["op 非 {pause, resume, speak} 时"]
  calibration: "对照：SpeechSynthesis——文本朗读/暂停/继续"
---

# 浏览器-语音合成（browser-59a0ada4）

## When to use

任务「语音合成」；对照：SpeechSynthesis——文本朗读/暂停/继续。

## 克制条款（不适用条件）

op 非 {pause, resume, speak} 时

## How to execute

按 op 分派

## Verification

- 单元样例 4 条（cases 断言）
- 物理基底：按 calibration 对照（编译/运行/断言裁决）

## References

- 单元库：compiler_code_units.py「浏览器-语音合成」
