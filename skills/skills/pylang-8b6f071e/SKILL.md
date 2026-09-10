---
name: pylang-8b6f071e
description: >-
  运算符重载 / 面向对象-运算符重载 / CPython 运 / 对象方法分派。用户提到这些词时使用本技能。
  场景：对照：CPython 运算符重载（__add__/__mul__ dunder 分派，未定义→TypeError 语义）。
  【不适用】Not for 以下场景：条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）
license: MIT
compatibility: >-
  参数 obj/other/op 合法
allowed-tools: Read Write Bash
metadata:
  version: "1.0"
  skill-author: 灵枢（AEIS）
  last-reviewed: "2026-08-29"
  kccs:
    trigger_words: ["运算符重载", "面向对象-运算符重载", "CPython 运", "对象方法分派"]
    when: "参数 obj/other/op 合法"
    sub: ["① 调用 method；② 调用 isinstance；③ 调用 getattr"]
    execute: "顺序调用"
    not_applicable: ["条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）"]
  calibration: "对照：CPython 运算符重载（__add__/__mul__ dunder 分派，未定义→TypeError 语义）"
---

# 面向对象-运算符重载（pylang-8b6f071e）

## When to use

任务「运算符重载」；对照：CPython 运算符重载（__add__/__mul__ dunder 分派，未定义→TypeError 语义）。

## 克制条款（不适用条件）

条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）

## How to execute

顺序调用

## Verification

- 单元样例 3 条（cases 断言）
- 物理基底：按 calibration 对照（编译/运行/断言裁决）

## References

- 单元库：compiler_code_units.py「面向对象-运算符重载」
