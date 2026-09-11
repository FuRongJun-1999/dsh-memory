---
name: compiler-66377955
description: >-
  寄存器着色 / 编译-寄存器着色 / 寄存器分配——活跃区间冲 / 活跃区间贪心分配。用户提到这些词时使用本技能。
  场景：对照：寄存器分配——活跃区间冲突着色（贪心）。
  【不适用】Not for 以下场景：条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）
license: MIT
compatibility: >-
  参数 intervals/regs 合法
allowed-tools: Read Write Bash
metadata:
  version: "1.0"
  skill-author: 灵枢（AEIS）
  last-reviewed: "2026-08-29"
  kccs:
    trigger_words: ["寄存器着色", "编译-寄存器着色", "寄存器分配——活跃区间冲", "活跃区间贪心分配"]
    when: "参数 intervals/regs 合法"
    sub: ["① 条件判定 ② 结果处理"]
    execute: "循环迭代"
    not_applicable: ["条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）"]
  calibration: "对照：寄存器分配——活跃区间冲突着色（贪心）"
---

# 编译-寄存器着色（compiler-66377955）

## When to use

任务「寄存器着色」；对照：寄存器分配——活跃区间冲突着色（贪心）。

## 克制条款（不适用条件）

条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）

## How to execute

循环迭代

## Verification

- 单元样例 3 条（cases 断言）
- 物理基底：按 calibration 对照（编译/运行/断言裁决）

## References

- 单元库：compiler_code_units.py「编译-寄存器着色」
