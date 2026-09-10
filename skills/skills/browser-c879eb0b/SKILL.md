---
name: browser-c879eb0b
description: >-
  文本摘要 / 浏览器-文本摘要 / summarize 提。用户提到这些词时使用本技能。
  场景：对照：Summarizer——文本要点提取摘要。
  【不适用】Not for 以下场景：op 非 {last, length, summarize} 时
license: MIT
compatibility: >-
  op ∈ {last, length, summarize}
allowed-tools: Read Write Bash
metadata:
  version: "1.0"
  skill-author: 灵枢（AEIS）
  last-reviewed: "2026-08-29"
  kccs:
    trigger_words: ["文本摘要", "浏览器-文本摘要", "summarize 提"]
    when: "op ∈ {last, length, summarize}"
    sub: ["① op 分支处理"]
    execute: "按 op 分派；顺序调用"
    not_applicable: ["op 非 {last, length, summarize} 时"]
  calibration: "对照：Summarizer——文本要点提取摘要"
---

# 浏览器-文本摘要（browser-c879eb0b）

## When to use

任务「文本摘要」；对照：Summarizer——文本要点提取摘要。

## 克制条款（不适用条件）

op 非 {last, length, summarize} 时

## How to execute

按 op 分派；顺序调用

## Verification

- 单元样例 4 条（cases 断言）
- 物理基底：按 calibration 对照（编译/运行/断言裁决）

## References

- 单元库：compiler_code_units.py「浏览器-文本摘要」
