---
name: browser-43154cec
description: >-
  窗口管理 / 浏览器-窗口管理 / open 开。用户提到这些词时使用本技能。
  场景：对照：Window Management——多窗口开/移/关。
  【不适用】Not for 以下场景：op 非 {close, move, open} 时
license: MIT
compatibility: >-
  op ∈ {close, move, open}
allowed-tools: Read Write Bash
metadata:
  version: "1.0"
  skill-author: 灵枢（AEIS）
  last-reviewed: "2026-08-29"
  kccs:
    trigger_words: ["窗口管理", "浏览器-窗口管理", "open 开"]
    when: "op ∈ {close, move, open}"
    sub: ["① op 分支处理"]
    execute: "按 op 分派"
    not_applicable: ["op 非 {close, move, open} 时"]
  calibration: "对照：Window Management——多窗口开/移/关"
---

# 浏览器-窗口管理（browser-43154cec）

## When to use

任务「窗口管理」；对照：Window Management——多窗口开/移/关。

## 克制条款（不适用条件）

op 非 {close, move, open} 时

## How to execute

按 op 分派

## Verification

- 单元样例 4 条（cases 断言）
- 物理基底：按 calibration 对照（编译/运行/断言裁决）

## References

- 单元库：compiler_code_units.py「浏览器-窗口管理」
