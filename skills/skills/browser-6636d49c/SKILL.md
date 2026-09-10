---
name: browser-6636d49c
description: >-
  拖放交互 / 浏览器-拖放交互 / 拖放 / dragstart 开。用户提到这些词时使用本技能。
  场景：对照：拖放 API——dragstart 数据携带/drop 目标投放。
  【不适用】Not for 以下场景：op 非 {dragstart, drop, get} 时
license: MIT
compatibility: >-
  op ∈ {dragstart, drop, get}
allowed-tools: Read Write Bash
metadata:
  version: "1.0"
  skill-author: 灵枢（AEIS）
  last-reviewed: "2026-08-29"
  kccs:
    trigger_words: ["拖放交互", "浏览器-拖放交互", "拖放", "dragstart 开"]
    when: "op ∈ {dragstart, drop, get}"
    sub: ["① op 分支处理"]
    execute: "按 op 分派"
    not_applicable: ["op 非 {dragstart, drop, get} 时"]
  calibration: "对照：拖放 API——dragstart 数据携带/drop 目标投放"
---

# 浏览器-拖放交互（browser-6636d49c）

## When to use

任务「拖放交互」；对照：拖放 API——dragstart 数据携带/drop 目标投放。

## 克制条款（不适用条件）

op 非 {dragstart, drop, get} 时

## How to execute

按 op 分派

## Verification

- 单元样例 4 条（cases 断言）
- 物理基底：按 calibration 对照（编译/运行/断言裁决）

## References

- 单元库：compiler_code_units.py「浏览器-拖放交互」
