---
name: browser-093c03ab
description: >-
  预加载 / 浏览器-预加载 / preload——关 / add 登。用户提到这些词时使用本技能。
  场景：对照：preload——关键资源提前加载（命中统计）。
  【不适用】Not for 以下场景：op 非 {add, stats, use} 时
license: MIT
compatibility: >-
  op ∈ {add, stats, use}
allowed-tools: Read Write Bash
metadata:
  version: "1.0"
  skill-author: 灵枢（AEIS）
  last-reviewed: "2026-08-29"
  kccs:
    trigger_words: ["预加载", "浏览器-预加载", "preload——关", "add 登"]
    when: "op ∈ {add, stats, use}"
    sub: ["① op 分支处理"]
    execute: "按 op 分派；顺序调用"
    not_applicable: ["op 非 {add, stats, use} 时"]
  calibration: "对照：preload——关键资源提前加载（命中统计）"
---

# 浏览器-预加载（browser-093c03ab）

## When to use

任务「预加载」；对照：preload——关键资源提前加载（命中统计）。

## 克制条款（不适用条件）

op 非 {add, stats, use} 时

## How to execute

按 op 分派；顺序调用

## Verification

- 单元样例 4 条（cases 断言）
- 物理基底：按 calibration 对照（编译/运行/断言裁决）

## References

- 单元库：compiler_code_units.py「浏览器-预加载」
