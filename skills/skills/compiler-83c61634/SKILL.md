---
name: compiler-83c61634
description: >-
  编译管线 / 编译-管线静态检查 / C2 语 / 条件空间=类型系统 / 静态检查→字节码）——名。用户提到这些词时使用本技能。
  场景：对照：C2 语义——名实=静态检查、条件空间=类型系统（编译期拦截类型错误/未声明空间）。
  【不适用】Not for 以下场景：kind 非 {COND} 时
license: MIT
compatibility: >-
  kind ∈ {COND}；_re.search 可用；m.group 可用
allowed-tools: Read Write Bash
metadata:
  version: "1.0"
  skill-author: 灵枢（AEIS）
  last-reviewed: "2026-08-29"
  kccs:
    trigger_words: ["编译管线", "编译-管线静态检查", "C2 语", "条件空间=类型系统", "静态检查→字节码）——名"]
    when: "kind ∈ {COND}；_re.search 可用；m.group 可用"
    sub: ["1 kind 分支处理"]
    execute: "按 op 分派；循环迭代；顺序调用"
    not_applicable: ["kind 非 {COND} 时"]
  calibration: "对照：C2 语义——名实=静态检查、条件空间=类型系统（编译期拦截类型错误/未声明空间）"
---

# 编译-管线静态检查（compiler-83c61634）

## When to use

任务「编译管线」；对照：C2 语义——名实=静态检查、条件空间=类型系统（编译期拦截类型错误/未声明空间）。

## 克制条款（不适用条件）

kind 非 {COND} 时

## How to execute

按 op 分派；循环迭代；顺序调用

## Verification

- 单元样例 4 条（cases 断言）
- 物理基底：按 calibration 对照（编译/运行/断言裁决）

## References

- 单元库：compiler_code_units.py「编译-管线静态检查」
