---
name: compile-func-def
description: >-
  函数定义 / 编译-函数定义 / protocol-com / 定义 名 / 返回 。用户提到这些词时使用本技能。
  场景：对照：protocol-compiler 函数定义（入口=函数体起点，体末 RETURN）。
  【不适用】Not for 以下场景：条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）
license: MIT
compatibility: >-
  参数 name/params/body_instrs 合法
allowed-tools: Read Write Bash
metadata:
  version: "1.0"
  skill-author: 灵枢（AEIS）
  last-reviewed: "2026-08-29"
  kccs:
    trigger_words: ["函数定义", "编译-函数定义", "protocol-com", "定义 名", "返回 "]
    when: "参数 name/params/body_instrs 合法"
    sub: ["① 调用 list"]
    execute: "顺序调用"
    not_applicable: ["条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）"]
  calibration: "对照：protocol-compiler 函数定义（入口=函数体起点，体末 RETURN）"
---

# 编译-函数定义（compile-func-def）

## When to use

任务「函数定义」；对照：protocol-compiler 函数定义（入口=函数体起点，体末 RETURN）。

## 克制条款（不适用条件）

条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）

## How to execute

顺序调用

## Verification

- 单元样例 1 条（cases 断言）
- 物理基底：按 calibration 对照（编译/运行/断言裁决）

## References

- 单元库：compiler_code_units.py「编译-函数定义」
