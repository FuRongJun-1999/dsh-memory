---
name: os-fcdd828d
description: >-
  时钟节拍 / 系统-时钟节拍 / 定时器——节拍推进 / 已过时间 / 频率 / tick 推。用户提到这些词时使用本技能。
  场景：对照：定时器——节拍推进/已过时间/频率（HZ）。
  【不适用】Not for 以下场景：op 非 {elapsed, hz, tick} 时
license: MIT
compatibility: >-
  op ∈ {elapsed, hz, tick}
allowed-tools: Read Write Bash
metadata:
  version: "1.0"
  skill-author: 灵枢（AEIS）
  last-reviewed: "2026-08-29"
  kccs:
    trigger_words: ["时钟节拍", "系统-时钟节拍", "定时器——节拍推进", "已过时间", "频率", "tick 推"]
    when: "op ∈ {elapsed, hz, tick}"
    sub: ["① op 分支处理"]
    execute: "按 op 分派"
    not_applicable: ["op 非 {elapsed, hz, tick} 时"]
  calibration: "对照：定时器——节拍推进/已过时间/频率（HZ）"
---

# 系统-时钟节拍（os-fcdd828d）

## When to use

任务「时钟节拍」；对照：定时器——节拍推进/已过时间/频率（HZ）。

## 克制条款（不适用条件）

op 非 {elapsed, hz, tick} 时

## How to execute

按 op 分派

## Verification

- 单元样例 4 条（cases 断言）
- 物理基底：按 calibration 对照（编译/运行/断言裁决）

## References

- 单元库：compiler_code_units.py「系统-时钟节拍」
