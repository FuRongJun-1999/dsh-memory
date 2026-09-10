---
name: pylang-c42465ec
description: >-
  元类定制 / 元编程-元类定制 / CPython meta / hook 在。用户提到这些词时使用本技能。
  场景：对照：CPython metaclass __new__ 拦截类创建（校验/注入类属性）。
  【不适用】Not for 以下场景：条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）
license: MIT
compatibility: >-
  k.startswith 可用
allowed-tools: Read Write Bash
metadata:
  version: "1.0"
  skill-author: 灵枢（AEIS）
  last-reviewed: "2026-08-29"
  kccs:
    trigger_words: ["元类定制", "元编程-元类定制", "CPython meta", "hook 在"]
    when: "k.startswith 可用"
    sub: ["① 调用 dict；② 调用 type；③ 调用 hook"]
    execute: "顺序调用"
    not_applicable: ["条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）"]
  calibration: "对照：CPython metaclass __new__ 拦截类创建（校验/注入类属性）"
---

# 元编程-元类定制（pylang-c42465ec）

## When to use

任务「元类定制」；对照：CPython metaclass __new__ 拦截类创建（校验/注入类属性）。

## 克制条款（不适用条件）

条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）

## How to execute

顺序调用

## Verification

- 单元样例 2 条（cases 断言）
- 物理基底：按 calibration 对照（编译/运行/断言裁决）

## References

- 单元库：compiler_code_units.py「元编程-元类定制」
