---
name: pylang-c017681a
description: >-
  字典推导 / 推导式-字典推导 / 字典推导——键值函数映射 / 键值函数映射建字典。用户提到这些词时使用本技能。
  场景：对照：字典推导——键值函数映射建字典（dict comprehension）。
  【不适用】Not for 以下场景：条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）
license: MIT
compatibility: >-
  参数 items/key_fn/val_fn 合法
allowed-tools: Read Write Bash
metadata:
  version: "1.0"
  skill-author: 灵枢（AEIS）
  last-reviewed: "2026-08-29"
  kccs:
    trigger_words: ["字典推导", "推导式-字典推导", "字典推导——键值函数映射", "键值函数映射建字典"]
    when: "参数 items/key_fn/val_fn 合法"
    sub: ["① 调用 key_fn；② 调用 val_fn"]
    execute: "顺序调用"
    not_applicable: ["条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）"]
  calibration: "对照：字典推导——键值函数映射建字典（dict comprehension）"
---

# 推导式-字典推导（pylang-c017681a）

## When to use

任务「字典推导」；对照：字典推导——键值函数映射建字典（dict comprehension）。

## 克制条款（不适用条件）

条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）

## How to execute

顺序调用

## Verification

- 单元样例 3 条（cases 断言）
- 物理基底：按 calibration 对照（编译/运行/断言裁决）

## References

- 单元库：compiler_code_units.py「推导式-字典推导」
