---
name: compiler-9f7be5ad
description: >-
  字符类别 / 词法-字符类别 / 词法——字符类别判定 / 字母/数字/空白/其他。用户提到这些词时使用本技能。
  场景：对照：词法——字符类别判定（字母/数字/空白/其他）。
  【不适用】Not for 以下场景：条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）
license: MIT
compatibility: >-
  ch.isalpha 可用；ch.isdigit 可用
allowed-tools: Read Write Bash
metadata:
  version: "1.0"
  skill-author: 灵枢（AEIS）
  last-reviewed: "2026-08-29"
  kccs:
    trigger_words: ["字符类别", "词法-字符类别", "词法——字符类别判定", "字母/数字/空白/其他"]
    when: "ch.isalpha 可用；ch.isdigit 可用"
    sub: ["① 条件判定 ② 结果处理"]
    execute: "字符类别：字母/数字/空白/其他（词法分类基础）"
    not_applicable: ["条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）"]
  calibration: "对照：词法——字符类别判定（字母/数字/空白/其他）"
---

# 词法-字符类别（compiler-9f7be5ad）

## When to use

任务「字符类别」；对照：词法——字符类别判定（字母/数字/空白/其他）。

## 克制条款（不适用条件）

条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）

## How to execute

字符类别：字母/数字/空白/其他（词法分类基础）

## Verification

- 单元样例 4 条（cases 断言）
- 物理基底：按 calibration 对照（编译/运行/断言裁决）

## References

- 单元库：compiler_code_units.py「词法-字符类别」
