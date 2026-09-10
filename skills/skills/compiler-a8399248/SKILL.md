---
name: compiler-a8399248
description: >-
  语句分隔 / 语法-语句分隔 / 语法——分号语句分隔 / 按分号拆分多语句。用户提到这些词时使用本技能。
  场景：对照：语法——分号语句分隔（多语句序列）。
  【不适用】Not for 以下场景：条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）
license: MIT
compatibility: >-
  s.strip 可用
allowed-tools: Read Write Bash
metadata:
  version: "1.0"
  skill-author: 灵枢（AEIS）
  last-reviewed: "2026-08-29"
  kccs:
    trigger_words: ["语句分隔", "语法-语句分隔", "语法——分号语句分隔", "按分号拆分多语句"]
    when: "s.strip 可用"
    sub: []
    execute: "语句分隔：按分号拆分多语句（语句序列解析）"
    not_applicable: ["条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）"]
  calibration: "对照：语法——分号语句分隔（多语句序列）"
---

# 语法-语句分隔（compiler-a8399248）

## When to use

任务「语句分隔」；对照：语法——分号语句分隔（多语句序列）。

## 克制条款（不适用条件）

条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）

## How to execute

语句分隔：按分号拆分多语句（语句序列解析）

## Verification

- 单元样例 4 条（cases 断言）
- 物理基底：按 calibration 对照（编译/运行/断言裁决）

## References

- 单元库：compiler_code_units.py「语法-语句分隔」
