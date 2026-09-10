---
name: compiler-0361708a
description: >-
  元组解析 / 语法-元组解析 / 语法——元组字面量 / '' 解析。用户提到这些词时使用本技能。
  场景：对照：语法——元组字面量（(元素,元素) 解析）。
  【不适用】Not for 以下场景：条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）
license: MIT
compatibility: >-
  参数 tokens/i 合法
allowed-tools: Read Write Bash
metadata:
  version: "1.0"
  skill-author: 灵枢（AEIS）
  last-reviewed: "2026-08-29"
  kccs:
    trigger_words: ["元组解析", "语法-元组解析", "语法——元组字面量", "'' 解析"]
    when: "参数 tokens/i 合法"
    sub: ["① 调用 tuple；② 调用 len"]
    execute: "循环迭代；顺序调用"
    not_applicable: ["条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）"]
  calibration: "对照：语法——元组字面量（(元素,元素) 解析）"
---

# 语法-元组解析（compiler-0361708a）

## When to use

任务「元组解析」；对照：语法——元组字面量（(元素,元素) 解析）。

## 克制条款（不适用条件）

条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）

## How to execute

循环迭代；顺序调用

## Verification

- 单元样例 3 条（cases 断言）
- 物理基底：按 calibration 对照（编译/运行/断言裁决）

## References

- 单元库：compiler_code_units.py「语法-元组解析」
