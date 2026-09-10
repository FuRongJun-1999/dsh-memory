---
name: browser-7be57bbe
description: >-
  颜色转换 / 渲染-颜色转换 / hex→rgb 解。用户提到这些词时使用本技能。
  场景：对照：CSS 颜色——hex↔rgb 双向转换。
  【不适用】Not for 以下场景：op 非 {hex2rgb, rgb2hex} 时
license: MIT
compatibility: >-
  op ∈ {hex2rgb, rgb2hex}；value.lstrip 可用
allowed-tools: Read Write Bash
metadata:
  version: "1.0"
  skill-author: 灵枢（AEIS）
  last-reviewed: "2026-08-29"
  kccs:
    trigger_words: ["颜色转换", "渲染-颜色转换", "hex→rgb 解"]
    when: "op ∈ {hex2rgb, rgb2hex}；value.lstrip 可用"
    sub: ["① op 分支处理"]
    execute: "按 op 分派；顺序调用"
    not_applicable: ["op 非 {hex2rgb, rgb2hex} 时"]
  calibration: "对照：CSS 颜色——hex↔rgb 双向转换"
---

# 渲染-颜色转换（browser-7be57bbe）

## When to use

任务「颜色转换」；对照：CSS 颜色——hex↔rgb 双向转换。

## 克制条款（不适用条件）

op 非 {hex2rgb, rgb2hex} 时

## How to execute

按 op 分派；顺序调用

## Verification

- 单元样例 4 条（cases 断言）
- 物理基底：按 calibration 对照（编译/运行/断言裁决）

## References

- 单元库：compiler_code_units.py「渲染-颜色转换」
