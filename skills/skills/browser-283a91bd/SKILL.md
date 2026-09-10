---
name: browser-283a91bd
description: >-
  推送通知 / 通知-推送消息 / Push API——订 / 推送 / 订阅/推送。用户提到这些词时使用本技能。
  场景：对照：Push API——订阅/推送（服务器推送通知到设备）。
  【不适用】Not for 以下场景：op 非 {send, subscribe} 时
license: MIT
compatibility: >-
  op ∈ {send, subscribe}
allowed-tools: Read Write Bash
metadata:
  version: "1.0"
  skill-author: 灵枢（AEIS）
  last-reviewed: "2026-08-29"
  kccs:
    trigger_words: ["推送通知", "通知-推送消息", "Push API——订", "推送", "订阅/推送"]
    when: "op ∈ {send, subscribe}"
    sub: ["① op 分支处理"]
    execute: "按 op 分派"
    not_applicable: ["op 非 {send, subscribe} 时"]
  calibration: "对照：Push API——订阅/推送（服务器推送通知到设备）"
---

# 通知-推送消息（browser-283a91bd）

## When to use

任务「推送通知」；对照：Push API——订阅/推送（服务器推送通知到设备）。

## 克制条款（不适用条件）

op 非 {send, subscribe} 时

## How to execute

按 op 分派

## Verification

- 单元样例 3 条（cases 断言）
- 物理基底：按 calibration 对照（编译/运行/断言裁决）

## References

- 单元库：compiler_code_units.py「通知-推送消息」
