---
name: os-6158581b
description: >-
  参数校验 / 系统调用-参数校验 / OS 系 / 系统调用参数校验 / 类型检查。用户提到这些词时使用本技能。
  场景：对照：OS 系统调用——参数类型校验（copy_from_user 语义，非法拒绝）。
  【不适用】Not for 以下场景：条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）
license: MIT
compatibility: >-
  参数 args/types 合法
allowed-tools: Read Write Bash
metadata:
  version: "1.0"
  skill-author: 灵枢（AEIS）
  last-reviewed: "2026-08-29"
  kccs:
    trigger_words: ["参数校验", "系统调用-参数校验", "OS 系", "系统调用参数校验", "类型检查"]
    when: "参数 args/types 合法"
    sub: ["① 调用 zip；② 调用 len；③ 调用 isinstance"]
    execute: "循环迭代；顺序调用"
    not_applicable: ["条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）"]
  calibration: "对照：OS 系统调用——参数类型校验（copy_from_user 语义，非法拒绝）"
---

# 系统调用-参数校验（os-6158581b）

## When to use

任务「参数校验」；对照：OS 系统调用——参数类型校验（copy_from_user 语义，非法拒绝）。

## 克制条款（不适用条件）

条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）

## How to execute

循环迭代；顺序调用

## Verification

- 单元样例 3 条（cases 断言）
- 物理基底：按 calibration 对照（编译/运行/断言裁决）

## References

- 单元库：compiler_code_units.py「系统调用-参数校验」
