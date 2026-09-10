---
name: browser-0fd64fa5
description: >-
  Service Worker / 并行-Service Worker / activate / fetch 拦 / install→acti。用户提到这些词时使用本技能。
  场景：对照：Service Worker——install/activate/fetch 拦截（缓存优先/网络回退）。
  【不适用】Not for 以下场景：event 非 {activate, fetch, install} 时
license: MIT
compatibility: >-
  event ∈ {activate, fetch, install}
allowed-tools: Read Write Bash
metadata:
  version: "1.0"
  skill-author: 灵枢（AEIS）
  last-reviewed: "2026-08-29"
  kccs:
    trigger_words: ["Service Worker", "并行-Service Worker", "activate", "fetch 拦", "install→acti"]
    when: "event ∈ {activate, fetch, install}"
    sub: ["1 event 分支处理"]
    execute: "按 op 分派"
    not_applicable: ["event 非 {activate, fetch, install} 时"]
  calibration: "对照：Service Worker——install/activate/fetch 拦截（缓存优先/网络回退）"
---

# 并行-Service Worker（browser-0fd64fa5）

## When to use

任务「Service Worker」；对照：Service Worker——install/activate/fetch 拦截（缓存优先/网络回退）。

## 克制条款（不适用条件）

event 非 {activate, fetch, install} 时

## How to execute

按 op 分派

## Verification

- 单元样例 4 条（cases 断言）
- 物理基底：按 calibration 对照（编译/运行/断言裁决）

## References

- 单元库：compiler_code_units.py「并行-Service Worker」
