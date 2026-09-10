---
name: compiler-6de326c0
description: >-
  逃逸分析 / 分析-逃逸分析 / 逃逸分析——返回 / 存储即逃逸 / 对象是否逃逸函数。用户提到这些词时使用本技能。
  场景：对照：逃逸分析——返回/存储即逃逸（栈分配优化）。
  【不适用】Not for 以下场景：条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）
license: MIT
compatibility: >-
  参数 alloc/ops 合法
allowed-tools: Read Write Bash
metadata:
  version: "1.0"
  skill-author: 灵枢（AEIS）
  last-reviewed: "2026-08-29"
  kccs:
    trigger_words: ["逃逸分析", "分析-逃逸分析", "逃逸分析——返回", "存储即逃逸", "对象是否逃逸函数"]
    when: "参数 alloc/ops 合法"
    sub: ["① 条件判定 ② 结果处理"]
    execute: "逃逸分析：对象是否逃逸函数（栈上分配可行性）"
    not_applicable: ["条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）"]
  calibration: "对照：逃逸分析——返回/存储即逃逸（栈分配优化）"
---

# 分析-逃逸分析（compiler-6de326c0）

## When to use

任务「逃逸分析」；对照：逃逸分析——返回/存储即逃逸（栈分配优化）。

## 克制条款（不适用条件）

条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）

## How to execute

逃逸分析：对象是否逃逸函数（栈上分配可行性）

## Verification

- 单元样例 4 条（cases 断言）
- 物理基底：按 calibration 对照（编译/运行/断言裁决）

## References

- 单元库：compiler_code_units.py「分析-逃逸分析」
