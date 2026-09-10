---
name: browser-bfad66a5
description: >-
  请求合并 / 浏览器-请求合并 / 请求合并——多请求成批传 / create 建。用户提到这些词时使用本技能。
  场景：对照：请求合并——多请求成批传输（减少往返）。
  【不适用】Not for 以下场景：op 非 {add, count, create} 时
license: MIT
compatibility: >-
  op ∈ {add, count, create}
allowed-tools: Read Write Bash
metadata:
  version: "1.0"
  skill-author: 灵枢（AEIS）
  last-reviewed: "2026-08-29"
  kccs:
    trigger_words: ["请求合并", "浏览器-请求合并", "请求合并——多请求成批传", "create 建"]
    when: "op ∈ {add, count, create}"
    sub: ["① op 分支处理"]
    execute: "按 op 分派；顺序调用"
    not_applicable: ["op 非 {add, count, create} 时"]
  calibration: "对照：请求合并——多请求成批传输（减少往返）"
---

# 浏览器-请求合并（browser-bfad66a5）

## When to use

任务「请求合并」；对照：请求合并——多请求成批传输（减少往返）。

## 克制条款（不适用条件）

op 非 {add, count, create} 时

## How to execute

按 op 分派；顺序调用

## Verification

- 单元样例 4 条（cases 断言）
- 物理基底：按 calibration 对照（编译/运行/断言裁决）

## References

- 单元库：compiler_code_units.py「浏览器-请求合并」
