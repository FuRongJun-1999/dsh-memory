---
name: net-292ef917
description: >-
  报文重排序 / 网络-报文重排序 / TCP 乱 / put 乱。用户提到这些词时使用本技能。
  场景：对照：TCP 乱序重排——按序号缓冲并按序递交（reordering）。
  【不适用】Not for 以下场景：op 非 {flush, put} 时
license: MIT
compatibility: >-
  op ∈ {flush, put}
allowed-tools: Read Write Bash
metadata:
  version: "1.0"
  skill-author: 灵枢（AEIS）
  last-reviewed: "2026-08-29"
  kccs:
    trigger_words: ["报文重排序", "网络-报文重排序", "TCP 乱", "put 乱"]
    when: "op ∈ {flush, put}"
    sub: ["① op 分支处理"]
    execute: "按 op 分派；循环迭代；顺序调用"
    not_applicable: ["op 非 {flush, put} 时"]
  calibration: "对照：TCP 乱序重排——按序号缓冲并按序递交（reordering）"
---

# 网络-报文重排序（net-292ef917）

## When to use

任务「报文重排序」；对照：TCP 乱序重排——按序号缓冲并按序递交（reordering）。

## 克制条款（不适用条件）

op 非 {flush, put} 时

## How to execute

按 op 分派；循环迭代；顺序调用

## Verification

- 单元样例 4 条（cases 断言）
- 物理基底：按 calibration 对照（编译/运行/断言裁决）

## References

- 单元库：compiler_code_units.py「网络-报文重排序」
