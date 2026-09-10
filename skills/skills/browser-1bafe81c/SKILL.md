---
name: browser-1bafe81c
description: >-
  振动反馈 / 浏览器-振动反馈 / start 启。用户提到这些词时使用本技能。
  场景：对照：navigator.vibrate——振动启动/停止/状态。
  【不适用】Not for 以下场景：op 非 {active, start, stop} 时
license: MIT
compatibility: >-
  op ∈ {active, start, stop}
allowed-tools: Read Write Bash
metadata:
  version: "1.0"
  skill-author: 灵枢（AEIS）
  last-reviewed: "2026-08-29"
  kccs:
    trigger_words: ["振动反馈", "浏览器-振动反馈", "start 启"]
    when: "op ∈ {active, start, stop}"
    sub: ["① op 分支处理"]
    execute: "按 op 分派"
    not_applicable: ["op 非 {active, start, stop} 时"]
  calibration: "对照：navigator.vibrate——振动启动/停止/状态"
---

# 浏览器-振动反馈（browser-1bafe81c）

## When to use

任务「振动反馈」；对照：navigator.vibrate——振动启动/停止/状态。

## 克制条款（不适用条件）

op 非 {active, start, stop} 时

## How to execute

按 op 分派

## Verification

- 单元样例 4 条（cases 断言）
- 物理基底：按 calibration 对照（编译/运行/断言裁决）

## References

- 单元库：compiler_code_units.py「浏览器-振动反馈」
