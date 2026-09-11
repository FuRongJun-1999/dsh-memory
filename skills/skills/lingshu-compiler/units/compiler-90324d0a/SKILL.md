---
name: compiler-90324d0a
description: >-
  条件空间存在 / 校验-条件空间存在性 / C2 语 / 条件空间=类型系统 / 使用的条件空间必须已声明。用户提到这些词时使用本技能。
  场景：对照：C2 语义——条件空间=类型系统（使用前必须声明，编译期拦截）。
  【不适用】Not for 以下场景：条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）
license: MIT
compatibility: >-
  参数 used_spaces/declared_spaces 合法
allowed-tools: Read Write Bash
metadata:
  version: "1.0"
  skill-author: 灵枢（AEIS）
  last-reviewed: "2026-08-29"
  kccs:
    trigger_words: ["条件空间存在", "校验-条件空间存在性", "C2 语", "条件空间=类型系统", "使用的条件空间必须已声明"]
    when: "参数 used_spaces/declared_spaces 合法"
    sub: []
    execute: "条件空间=类型系统：使用的条件空间必须已声明（编译期拦截未声明空间）"
    not_applicable: ["条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）"]
  calibration: "对照：C2 语义——条件空间=类型系统（使用前必须声明，编译期拦截）"
---

# 校验-条件空间存在性（compiler-90324d0a）

## When to use

任务「条件空间存在」；对照：C2 语义——条件空间=类型系统（使用前必须声明，编译期拦截）。

## 克制条款（不适用条件）

条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）

## How to execute

条件空间=类型系统：使用的条件空间必须已声明（编译期拦截未声明空间）

## Verification

- 单元样例 4 条（cases 断言）
- 物理基底：按 calibration 对照（编译/运行/断言裁决）

## References

- 单元库：compiler_code_units.py「校验-条件空间存在性」
