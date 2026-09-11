---
name: compile-full-pipeline
description: >-
  完整编译 / 编译-完整管线 / 中文源码 → 字节码 / 流程 / 逐行词法 → 静态检查→ / 条件真值编译 / LOAD 左。用户提到这些词时使用本技能。
  场景：对照：白箱版 pc compile 单入口（词法→静态检查→编译）；若则真值计算由编译-若则单元深化。
  【不适用】Not for 以下场景：kw 非 {知足} 时
license: MIT
compatibility: >-
  kw ∈ {知足}；source.splitlines 可用；line.strip 可用
allowed-tools: Read Write Bash
metadata:
  version: "1.0"
  skill-author: 灵枢（AEIS）
  last-reviewed: "2026-08-29"
  kccs:
    trigger_words: ["完整编译", "编译-完整管线", "中文源码 → 字节码", "流程", "逐行词法 → 静态检查→", "条件真值编译", "LOAD 左"]
    when: "kw ∈ {知足}；source.splitlines 可用；line.strip 可用"
    sub: ["1 kw 分支处理"]
    execute: "按 op 分派；循环迭代；顺序调用"
    not_applicable: ["kw 非 {知足} 时"]
  calibration: "对照：白箱版 pc compile 单入口（词法→静态检查→编译）；若则真值计算由编译-若则单元深化"
---

# 编译-完整管线（compile-full-pipeline）

## When to use

任务「完整编译」；对照：白箱版 pc compile 单入口（词法→静态检查→编译）；若则真值计算由编译-若则单元深化。

## 克制条款（不适用条件）

kw 非 {知足} 时

## How to execute

按 op 分派；循环迭代；顺序调用

## Verification

- 单元样例 7 条（cases 断言）
- 物理基底：按 calibration 对照（编译/运行/断言裁决）

## References

- 单元库：compiler_code_units.py「编译-完整管线」
