---
name: compiler-6af76fd6
description: >-
  常量池 / 编译-常量池 / 编译——常量池字面量去重 / add 去。用户提到这些词时使用本技能。
  场景：对照：编译——常量池字面量去重（LDC 索引引用）。
  【不适用】Not for 以下场景：op 非 {add, get, size} 时
license: MIT
compatibility: >-
  op ∈ {add, get, size}；pool.index 可用
allowed-tools: Read Write Bash
metadata:
  version: "1.0"
  skill-author: 灵枢（AEIS）
  last-reviewed: "2026-08-29"
  kccs:
    trigger_words: ["常量池", "编译-常量池", "编译——常量池字面量去重", "add 去"]
    when: "op ∈ {add, get, size}；pool.index 可用"
    sub: ["① op 分支处理"]
    execute: "按 op 分派；顺序调用"
    not_applicable: ["op 非 {add, get, size} 时"]
  calibration: "对照：编译——常量池字面量去重（LDC 索引引用）"
---

# 编译-常量池（compiler-6af76fd6）

## When to use

任务「常量池」；对照：编译——常量池字面量去重（LDC 索引引用）。

## 克制条款（不适用条件）

op 非 {add, get, size} 时

## How to execute

按 op 分派；顺序调用

## Verification

- 单元样例 4 条（cases 断言）
- 物理基底：按 calibration 对照（编译/运行/断言裁决）

## References

- 单元库：compiler_code_units.py「编译-常量池」
