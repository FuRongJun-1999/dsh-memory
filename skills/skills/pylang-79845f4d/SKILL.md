---
name: pylang-79845f4d
description: >-
  多行字符串 / 语法-多行字符串 / Python 三 / 三引号解析。用户提到这些词时使用本技能。
  场景：对照：Python 三引号字符串（跨行字面量）。
  【不适用】Not for 以下场景：条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）
license: MIT
compatibility: >-
  src.find 可用
allowed-tools: Read Write Bash
metadata:
  version: "1.0"
  skill-author: 灵枢（AEIS）
  last-reviewed: "2026-08-29"
  kccs:
    trigger_words: ["多行字符串", "语法-多行字符串", "Python 三", "三引号解析"]
    when: "src.find 可用"
    sub: ["① 调用 chr；② 调用 len"]
    execute: "顺序调用"
    not_applicable: ["条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）"]
  calibration: "对照：Python 三引号字符串（跨行字面量）"
---

# 语法-多行字符串（pylang-79845f4d）

## When to use

任务「多行字符串」；对照：Python 三引号字符串（跨行字面量）。

## 克制条款（不适用条件）

条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）

## How to execute

顺序调用

## Verification

- 单元样例 2 条（cases 断言）
- 物理基底：按 calibration 对照（编译/运行/断言裁决）

## References

- 单元库：compiler_code_units.py「语法-多行字符串」
