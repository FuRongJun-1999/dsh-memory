---
name: browser-60aefeeb
description: >-
  滚动容器 / 渲染-滚动容器 / 触底判定 / scroll 按。用户提到这些词时使用本技能。
  场景：对照：浏览器滚动——scrollTop 滚动位置/触底判定（视口滚动容器）。
  【不适用】Not for 以下场景：op 非 {bottom, position, scroll} 时
license: MIT
compatibility: >-
  op ∈ {bottom, position, scroll}
allowed-tools: Read Write Bash
metadata:
  version: "1.0"
  skill-author: 灵枢（AEIS）
  last-reviewed: "2026-08-29"
  kccs:
    trigger_words: ["滚动容器", "渲染-滚动容器", "触底判定", "scroll 按"]
    when: "op ∈ {bottom, position, scroll}"
    sub: ["① op 分支处理"]
    execute: "按 op 分派"
    not_applicable: ["op 非 {bottom, position, scroll} 时"]
  calibration: "对照：浏览器滚动——scrollTop 滚动位置/触底判定（视口滚动容器）"
---

# 渲染-滚动容器（browser-60aefeeb）

## When to use

任务「滚动容器」；对照：浏览器滚动——scrollTop 滚动位置/触底判定（视口滚动容器）。

## 克制条款（不适用条件）

op 非 {bottom, position, scroll} 时

## How to execute

按 op 分派

## Verification

- 单元样例 4 条（cases 断言）
- 物理基底：按 calibration 对照（编译/运行/断言裁决）

## References

- 单元库：compiler_code_units.py「渲染-滚动容器」
