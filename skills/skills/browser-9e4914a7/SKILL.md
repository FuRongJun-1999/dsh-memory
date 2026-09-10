---
name: browser-9e4914a7
description: >-
  网页共享 / 浏览器-网页共享 / share 分。用户提到这些词时使用本技能。
  场景：对照：Web Share API——网页内容分享。
  【不适用】Not for 以下场景：op 非 {can_share, last, share} 时
license: MIT
compatibility: >-
  op ∈ {can_share, last, share}
allowed-tools: Read Write Bash
metadata:
  version: "1.0"
  skill-author: 灵枢（AEIS）
  last-reviewed: "2026-08-29"
  kccs:
    trigger_words: ["网页共享", "浏览器-网页共享", "share 分"]
    when: "op ∈ {can_share, last, share}"
    sub: ["① op 分支处理"]
    execute: "按 op 分派；顺序调用"
    not_applicable: ["op 非 {can_share, last, share} 时"]
  calibration: "对照：Web Share API——网页内容分享"
---

# 浏览器-网页共享（browser-9e4914a7）

## When to use

任务「网页共享」；对照：Web Share API——网页内容分享。

## 克制条款（不适用条件）

op 非 {can_share, last, share} 时

## How to execute

按 op 分派；顺序调用

## Verification

- 单元样例 4 条（cases 断言）
- 物理基底：按 calibration 对照（编译/运行/断言裁决）

## References

- 单元库：compiler_code_units.py「浏览器-网页共享」
