---
name: browser-1fdb5852
description: >-
  标签页通信 / 浏览器-标签页通信 / post 广。用户提到这些词时使用本技能。
  场景：对照：BroadcastChannel/postMessage——跨标签页广播通信。
  【不适用】Not for 以下场景：op 非 {listeners, post, recv} 时
license: MIT
compatibility: >-
  op ∈ {listeners, post, recv}
allowed-tools: Read Write Bash
metadata:
  version: "1.0"
  skill-author: 灵枢（AEIS）
  last-reviewed: "2026-08-29"
  kccs:
    trigger_words: ["标签页通信", "浏览器-标签页通信", "post 广"]
    when: "op ∈ {listeners, post, recv}"
    sub: ["① op 分支处理"]
    execute: "按 op 分派"
    not_applicable: ["op 非 {listeners, post, recv} 时"]
  calibration: "对照：BroadcastChannel/postMessage——跨标签页广播通信"
---

# 浏览器-标签页通信（browser-1fdb5852）

## When to use

任务「标签页通信」；对照：BroadcastChannel/postMessage——跨标签页广播通信。

## 克制条款（不适用条件）

op 非 {listeners, post, recv} 时

## How to execute

按 op 分派

## Verification

- 单元样例 4 条（cases 断言）
- 物理基底：按 calibration 对照（编译/运行/断言裁决）

## References

- 单元库：compiler_code_units.py「浏览器-标签页通信」
