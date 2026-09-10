---
name: browser-f8f2966e
description: >-
  支付请求 / 浏览器-支付请求 / can_pay 检。用户提到这些词时使用本技能。
  场景：对照：Payment Request API——方法检查/支付/状态。
  【不适用】Not for 以下场景：op 非 {can_pay, pay, status} 时
license: MIT
compatibility: >-
  op ∈ {can_pay, pay, status}
allowed-tools: Read Write Bash
metadata:
  version: "1.0"
  skill-author: 灵枢（AEIS）
  last-reviewed: "2026-08-29"
  kccs:
    trigger_words: ["支付请求", "浏览器-支付请求", "can_pay 检"]
    when: "op ∈ {can_pay, pay, status}"
    sub: ["① op 分支处理"]
    execute: "按 op 分派"
    not_applicable: ["op 非 {can_pay, pay, status} 时"]
  calibration: "对照：Payment Request API——方法检查/支付/状态"
---

# 浏览器-支付请求（browser-f8f2966e）

## When to use

任务「支付请求」；对照：Payment Request API——方法检查/支付/状态。

## 克制条款（不适用条件）

op 非 {can_pay, pay, status} 时

## How to execute

按 op 分派

## Verification

- 单元样例 4 条（cases 断言）
- 物理基底：按 calibration 对照（编译/运行/断言裁决）

## References

- 单元库：compiler_code_units.py「浏览器-支付请求」
