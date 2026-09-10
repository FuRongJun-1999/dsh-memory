---
name: compiler-98b4c42f
description: >-
  循环展开 / 编译-循环展开 / 编译优化——循环展开。用户提到这些词时使用本技能。
  场景：对照：编译优化——循环展开（固定次数体复制，上限防膨胀）。
  【不适用】Not for 以下场景：条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）
license: MIT
compatibility: >-
  参数 body/times/max_unroll 合法
allowed-tools: Read Write Bash
metadata:
  version: "1.0"
  skill-author: 灵枢（AEIS）
  last-reviewed: "2026-08-29"
  kccs:
    trigger_words: ["循环展开", "编译-循环展开", "编译优化——循环展开"]
    when: "参数 body/times/max_unroll 合法"
    sub: ["① 调用 list"]
    execute: "顺序调用"
    not_applicable: ["条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）"]
  calibration: "对照：编译优化——循环展开（固定次数体复制，上限防膨胀）"
---

# 编译-循环展开（compiler-98b4c42f）

## When to use

任务「循环展开」；对照：编译优化——循环展开（固定次数体复制，上限防膨胀）。

## 克制条款（不适用条件）

条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）

## How to execute

顺序调用

## Verification

- 单元样例 4 条（cases 断言）
- 物理基底：按 calibration 对照（编译/运行/断言裁决）

## References

- 单元库：compiler_code_units.py「编译-循环展开」
