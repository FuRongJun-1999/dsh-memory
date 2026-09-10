---
name: browser-7bb4871d
description: >-
  剪贴板 / 浏览器-剪贴板 / copy 写。用户提到这些词时使用本技能。
  场景：对照：浏览器 API——navigator.clipboard（copy/paste 读写剪贴板）。
  【不适用】Not for 以下场景：op 非 {clear, copy, paste} 时
license: MIT
compatibility: >-
  op ∈ {clear, copy, paste}
allowed-tools: Read Write Bash
metadata:
  version: "1.0"
  skill-author: 灵枢（AEIS）
  last-reviewed: "2026-08-29"
  kccs:
    trigger_words: ["剪贴板", "浏览器-剪贴板", "copy 写"]
    when: "op ∈ {clear, copy, paste}"
    sub: ["① op 分支处理"]
    execute: "按 op 分派"
    not_applicable: ["op 非 {clear, copy, paste} 时"]
  calibration: "对照：浏览器 API——navigator.clipboard（copy/paste 读写剪贴板）"
---

# 浏览器-剪贴板（browser-7bb4871d）

## When to use

任务「剪贴板」；对照：浏览器 API——navigator.clipboard（copy/paste 读写剪贴板）。

## 克制条款（不适用条件）

op 非 {clear, copy, paste} 时

## How to execute

按 op 分派

## Verification

- 单元样例 4 条（cases 断言）
- 物理基底：按 calibration 对照（编译/运行/断言裁决）

## References

- 单元库：compiler_code_units.py「浏览器-剪贴板」
