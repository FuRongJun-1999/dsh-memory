---
name: browser-50fecd89
description: >-
  历史记录 / 浏览器-历史记录 / 浏览器历史——后退 / 前进 / visit 记。用户提到这些词时使用本技能。
  场景：对照：浏览器历史——后退/前进（访问栈+位置指针）。
  【不适用】Not for 以下场景：op 非 {back, forward, visit} 时
license: MIT
compatibility: >-
  op ∈ {back, forward, visit}
allowed-tools: Read Write Bash
metadata:
  version: "1.0"
  skill-author: 灵枢（AEIS）
  last-reviewed: "2026-08-29"
  kccs:
    trigger_words: ["历史记录", "浏览器-历史记录", "浏览器历史——后退", "前进", "visit 记"]
    when: "op ∈ {back, forward, visit}"
    sub: ["① op 分支处理"]
    execute: "按 op 分派；顺序调用"
    not_applicable: ["op 非 {back, forward, visit} 时"]
  calibration: "对照：浏览器历史——后退/前进（访问栈+位置指针）"
---

# 浏览器-历史记录（browser-50fecd89）

## When to use

任务「历史记录」；对照：浏览器历史——后退/前进（访问栈+位置指针）。

## 克制条款（不适用条件）

op 非 {back, forward, visit} 时

## How to execute

按 op 分派；顺序调用

## Verification

- 单元样例 5 条（cases 断言）
- 物理基底：按 calibration 对照（编译/运行/断言裁决）

## References

- 单元库：compiler_code_units.py「浏览器-历史记录」
