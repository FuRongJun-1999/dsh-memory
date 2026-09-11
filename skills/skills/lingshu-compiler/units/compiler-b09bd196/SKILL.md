---
name: compiler-b09bd196
description: >-
  数字后缀 / 词法-数字后缀 / 词法——数字字面量后缀。用户提到这些词时使用本技能。
  场景：对照：词法——数字字面量后缀（0x/0b/k/m）。
  【不适用】Not for 以下场景：条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）
license: MIT
compatibility: >-
  text.lower 可用；t.startswith 可用
allowed-tools: Read Write Bash
metadata:
  version: "1.0"
  skill-author: 灵枢（AEIS）
  last-reviewed: "2026-08-29"
  kccs:
    trigger_words: ["数字后缀", "词法-数字后缀", "词法——数字字面量后缀"]
    when: "text.lower 可用；t.startswith 可用"
    sub: ["① 调用 int"]
    execute: "顺序调用"
    not_applicable: ["条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）"]
  calibration: "对照：词法——数字字面量后缀（0x/0b/k/m）"
---

# 词法-数字后缀（compiler-b09bd196）

## When to use

任务「数字后缀」；对照：词法——数字字面量后缀（0x/0b/k/m）。

## 克制条款（不适用条件）

条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）

## How to execute

顺序调用

## Verification

- 单元样例 4 条（cases 断言）
- 物理基底：按 calibration 对照（编译/运行/断言裁决）

## References

- 单元库：compiler_code_units.py「词法-数字后缀」
