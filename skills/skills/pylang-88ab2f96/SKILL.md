---
name: pylang-88ab2f96
description: >-
  切片赋值 / 语法-切片赋值 / CPython 切 / a[start:end]。用户提到这些词时使用本技能。
  场景：对照：CPython 切片赋值（a[start:end]=values 区间写入/插入/追加，与切片读取互补）。
  【不适用】Not for 以下场景：条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）
license: MIT
compatibility: >-
  参数 arr/start/end/values 合法
allowed-tools: Read Write Bash
metadata:
  version: "1.0"
  skill-author: 灵枢（AEIS）
  last-reviewed: "2026-08-29"
  kccs:
    trigger_words: ["切片赋值", "语法-切片赋值", "CPython 切", "a[start:end]"]
    when: "参数 arr/start/end/values 合法"
    sub: ["① 调用 list"]
    execute: "顺序调用"
    not_applicable: ["条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）"]
  calibration: "对照：CPython 切片赋值（a[start:end]=values 区间写入/插入/追加，与切片读取互补）"
---

# 语法-切片赋值（pylang-88ab2f96）

## When to use

任务「切片赋值」；对照：CPython 切片赋值（a[start:end]=values 区间写入/插入/追加，与切片读取互补）。

## 克制条款（不适用条件）

条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）

## How to execute

顺序调用

## Verification

- 单元样例 5 条（cases 断言）
- 物理基底：按 calibration 对照（编译/运行/断言裁决）

## References

- 单元库：compiler_code_units.py「语法-切片赋值」
