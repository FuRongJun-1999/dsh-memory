---
name: browser-7da433f3
description: >-
  屏幕捕获 / 浏览器-屏幕捕获 / request 请。用户提到这些词时使用本技能。
  场景：对照：getDisplayMedia——屏幕捕获授权/选源/停止。
  【不适用】Not for 以下场景：op 非 {request, select, stop} 时
license: MIT
compatibility: >-
  op ∈ {request, select, stop}
allowed-tools: Read Write Bash
metadata:
  version: "1.0"
  skill-author: 灵枢（AEIS）
  last-reviewed: "2026-08-29"
  kccs:
    trigger_words: ["屏幕捕获", "浏览器-屏幕捕获", "request 请"]
    when: "op ∈ {request, select, stop}"
    sub: ["① op 分支处理"]
    execute: "按 op 分派"
    not_applicable: ["op 非 {request, select, stop} 时"]
  calibration: "对照：getDisplayMedia——屏幕捕获授权/选源/停止"
---

# 浏览器-屏幕捕获（browser-7da433f3）

## When to use

任务「屏幕捕获」；对照：getDisplayMedia——屏幕捕获授权/选源/停止。

## 克制条款（不适用条件）

op 非 {request, select, stop} 时

## How to execute

按 op 分派

## Verification

- 单元样例 4 条（cases 断言）
- 物理基底：按 calibration 对照（编译/运行/断言裁决）

## References

- 单元库：compiler_code_units.py「浏览器-屏幕捕获」
