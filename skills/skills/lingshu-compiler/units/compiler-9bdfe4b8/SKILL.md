---
name: compiler-9bdfe4b8
description: >-
  循环不变式 / 编译-循环不变式 / 编译优化——循环不变式外 / 不变指令外提。用户提到这些词时使用本技能。
  场景：对照：编译优化——循环不变式外提（循环外计算）。
  【不适用】Not for 以下场景：条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）
license: MIT
compatibility: >-
  参数 body/invariant_ops 合法
allowed-tools: Read Write Bash
metadata:
  version: "1.0"
  skill-author: 灵枢（AEIS）
  last-reviewed: "2026-08-29"
  kccs:
    trigger_words: ["循环不变式", "编译-循环不变式", "编译优化——循环不变式外", "不变指令外提"]
    when: "参数 body/invariant_ops 合法"
    sub: ["① 条件判定 ② 结果处理"]
    execute: "循环迭代"
    not_applicable: ["条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）"]
  calibration: "对照：编译优化——循环不变式外提（循环外计算）"
---

# 编译-循环不变式（compiler-9bdfe4b8）

## When to use

任务「循环不变式」；对照：编译优化——循环不变式外提（循环外计算）。

## 克制条款（不适用条件）

条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）

## How to execute

循环迭代

## Verification

- 单元样例 3 条（cases 断言）
- 物理基底：按 calibration 对照（编译/运行/断言裁决）

## References

- 单元库：compiler_code_units.py「编译-循环不变式」
