---
name: browser-85553126
description: >-
  权限API / 浏览器-权限API / Permissions  / 请求 / query 查。用户提到这些词时使用本技能。
  场景：对照：Permissions API——权限查询/请求（prompt/granted/denied）。
  【不适用】Not for 以下场景：op 非 {query, request} 时
license: MIT
compatibility: >-
  op ∈ {query, request}
allowed-tools: Read Write Bash
metadata:
  version: "1.0"
  skill-author: 灵枢（AEIS）
  last-reviewed: "2026-08-29"
  kccs:
    trigger_words: ["权限API", "浏览器-权限API", "Permissions ", "请求", "query 查"]
    when: "op ∈ {query, request}"
    sub: ["① op 分支处理"]
    execute: "按 op 分派"
    not_applicable: ["op 非 {query, request} 时"]
  calibration: "对照：Permissions API——权限查询/请求（prompt/granted/denied）"
---

# 浏览器-权限API（browser-85553126）

## When to use

任务「权限API」；对照：Permissions API——权限查询/请求（prompt/granted/denied）。

## 克制条款（不适用条件）

op 非 {query, request} 时

## How to execute

按 op 分派

## Verification

- 单元样例 4 条（cases 断言）
- 物理基底：按 calibration 对照（编译/运行/断言裁决）

## References

- 单元库：compiler_code_units.py「浏览器-权限API」
