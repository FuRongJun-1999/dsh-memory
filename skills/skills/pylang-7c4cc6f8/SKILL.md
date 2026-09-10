---
name: pylang-7c4cc6f8
description: >-
  抛出异常 / 异常-抛出 / raise 语 / 构造异常对象并抛出。用户提到这些词时使用本技能。
  场景：对照：Python raise（构造异常实例并抛出）。
  【不适用】Not for 以下场景：条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）
license: MIT
compatibility: >-
  参数 etype/msg 合法
allowed-tools: Read Write Bash
metadata:
  version: "1.0"
  skill-author: 灵枢（AEIS）
  last-reviewed: "2026-08-29"
  kccs:
    trigger_words: ["抛出异常", "异常-抛出", "raise 语", "构造异常对象并抛出"]
    when: "参数 etype/msg 合法"
    sub: ["① 调用 etype"]
    execute: "顺序调用"
    not_applicable: ["条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）"]
  calibration: "对照：Python raise（构造异常实例并抛出）"
---

# 异常-抛出（pylang-7c4cc6f8）

## When to use

任务「抛出异常」；对照：Python raise（构造异常实例并抛出）。

## 克制条款（不适用条件）

条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）

## How to execute

顺序调用

## Verification

- 单元样例 1 条（cases 断言）
- 物理基底：按 calibration 对照（编译/运行/断言裁决）

## References

- 单元库：compiler_code_units.py「异常-抛出」
