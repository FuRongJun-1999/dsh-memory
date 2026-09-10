---
name: pylang-962954d9
description: >-
  字符串大写 / 字符串-大写 / mini_python.。用户提到这些词时使用本技能。
  场景：对照：mini_python.py str 方法白名单 upper（CPython str.upper ASCII 子集）。
  【不适用】Not for 以下场景：非 ASCII 字母（中文等）不在本单元范围，原样保留
license: MIT
compatibility: >-
  s 为字符串
allowed-tools: Read Write Bash
metadata:
  version: "1.0"
  skill-author: 灵枢（AEIS）
  last-reviewed: "2026-08-29"
  kccs:
    trigger_words: ["字符串大写", "字符串-大写", "mini_python."]
    when: "s 为字符串"
    sub: ["① 逐字符判定 a-z；② ASCII 偏移转大写；③ 非小写原样保留"]
    execute: "循环迭代；条件分派"
    not_applicable: ["非 ASCII 字母（中文等）不在本单元范围，原样保留"]
  calibration: "对照：mini_python.py str 方法白名单 upper（CPython str.upper ASCII 子集）"
---

# 字符串-大写（pylang-962954d9）

## When to use

任务「字符串大写」；对照：mini_python.py str 方法白名单 upper（CPython str.upper ASCII 子集）。

## 克制条款（不适用条件）

非 ASCII 字母（中文等）不在本单元范围，原样保留

## How to execute

循环迭代；条件分派

## Verification

- 单元样例 4 条（cases 断言）
- 物理基底：按 calibration 对照（编译/运行/断言裁决）

## References

- 单元库：compiler_code_units.py「字符串-大写」
