---
name: browser-cf9f812e
description: >-
  缓存策略 / PWA-缓存策略 / PWA Service  / PWA 缓 / cache-first  / / stale 陈。用户提到这些词时使用本技能。
  场景：对照：PWA Service Worker——缓存策略（缓存优先/网络优先/陈旧再验证）。
  【不适用】Not for 以下场景：strategy 非 {cache-first, network-first} 时
license: MIT
compatibility: >-
  strategy ∈ {cache-first, network-first}
allowed-tools: Read Write Bash
metadata:
  version: "1.0"
  skill-author: 灵枢（AEIS）
  last-reviewed: "2026-08-29"
  kccs:
    trigger_words: ["缓存策略", "PWA-缓存策略", "PWA Service ", "PWA 缓", "cache-first ", "/ stale 陈"]
    when: "strategy ∈ {cache-first, network-first}"
    sub: ["1 strategy 分支处理"]
    execute: "按 op 分派"
    not_applicable: ["strategy 非 {cache-first, network-first} 时"]
  calibration: "对照：PWA Service Worker——缓存策略（缓存优先/网络优先/陈旧再验证）"
---

# PWA-缓存策略（browser-cf9f812e）

## When to use

任务「缓存策略」；对照：PWA Service Worker——缓存策略（缓存优先/网络优先/陈旧再验证）。

## 克制条款（不适用条件）

strategy 非 {cache-first, network-first} 时

## How to execute

按 op 分派

## Verification

- 单元样例 5 条（cases 断言）
- 物理基底：按 calibration 对照（编译/运行/断言裁决）

## References

- 单元库：compiler_code_units.py「PWA-缓存策略」
