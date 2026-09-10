---
name: pylang-ecd569d2
description: >-
  字符串拆分 / 工具-字符串拆分 / 按分隔符拆。用户提到这些词时使用本技能。
  场景：对照：Python str.split（分隔符拆分，默认空白）。
  【不适用】Not for 以下场景：条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）
license: MIT
compatibility: >-
  text 为字符串；sep 为分隔符或 None（默认空白拆分）
allowed-tools: Read Write Bash
metadata:
  version: "1.0"
  skill-author: 灵枢（AEIS）
  last-reviewed: "2026-08-29"
  kccs:
    trigger_words: ["字符串拆分", "工具-字符串拆分", "按分隔符拆"]
    when: "text 为字符串；sep 为分隔符或 None（默认空白拆分）"
    sub: ["① 显式分隔符拆分 ② 默认空白拆分"]
    execute: "sep 非 None → text.split(sep)，否则 text.split()"
    not_applicable: ["条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）"]
  calibration: "对照：Python str.split（分隔符拆分，默认空白）"
---

# 工具-字符串拆分（pylang-ecd569d2）

## When to use

任务「字符串拆分」；对照：Python str.split（分隔符拆分，默认空白）。

## 克制条款（不适用条件）

条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）

## How to execute

sep 非 None → text.split(sep)，否则 text.split()

## Verification

- 单元样例 3 条（cases 断言）
- 物理基底：按 calibration 对照（编译/运行/断言裁决）

## References

- 单元库：compiler_code_units.py「工具-字符串拆分」
