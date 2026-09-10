---
name: os-8cb7279d
description: >-
  瓶颈检测 / 性能-瓶颈检测 / OS 性 / 利用率最高的资源。用户提到这些词时使用本技能。
  场景：对照：OS 性能——瓶颈检测（最高利用率资源）。
  【不适用】Not for 以下场景：resources 为空/非法时
license: MIT
compatibility: >-
  参数 resources 合法
allowed-tools: Read Write Bash
metadata:
  version: "1.0"
  skill-author: 灵枢（AEIS）
  last-reviewed: "2026-08-29"
  kccs:
    trigger_words: ["瓶颈检测", "性能-瓶颈检测", "OS 性", "利用率最高的资源"]
    when: "参数 resources 合法"
    sub: ["① 调用 max"]
    execute: "顺序调用"
    not_applicable: ["resources 为空/非法时"]
  calibration: "对照：OS 性能——瓶颈检测（最高利用率资源）"
---

# 性能-瓶颈检测（os-8cb7279d）

## When to use

任务「瓶颈检测」；对照：OS 性能——瓶颈检测（最高利用率资源）。

## 克制条款（不适用条件）

resources 为空/非法时

## How to execute

顺序调用

## Verification

- 单元样例 2 条（cases 断言）
- 物理基底：按 calibration 对照（编译/运行/断言裁决）

## References

- 单元库：compiler_code_units.py「性能-瓶颈检测」
