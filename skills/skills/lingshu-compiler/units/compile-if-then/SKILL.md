---
name: compile-if-then
description: >-
  编译条件 / 编译-若则 / 若则=条件语句 / 条件跳转编译。用户提到这些词时使用本技能。
  场景：对照：若则=条件语句（v0.2 codegen if/else 的字节码形态）。
  【不适用】Not for 以下场景：条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）
license: MIT
compatibility: >-
  cond_instrs/then_instrs/else_instrs 为指令列表（条件/真分支/假分支字节码）
allowed-tools: Read Write Bash
metadata:
  version: "1.0"
  skill-author: 灵枢（AEIS）
  last-reviewed: "2026-08-29"
  kccs:
    trigger_words: ["编译条件", "编译-若则", "若则=条件语句", "条件跳转编译"]
    when: "cond_instrs/then_instrs/else_instrs 为指令列表（条件/真分支/假分支字节码）"
    sub: ["① 拼接条件指令 ② 假跳转至 else ③ 真分支尾跳至结束"]
    execute: "JUMP_IF_FALSE（条件假跳）+ JUMP（跳过 else）"
    not_applicable: ["条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）"]
  calibration: "对照：若则=条件语句（v0.2 codegen if/else 的字节码形态）"
---

# 编译-若则（compile-if-then）

## When to use

任务「编译条件」；对照：若则=条件语句（v0.2 codegen if/else 的字节码形态）。

## 克制条款（不适用条件）

条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）

## How to execute

JUMP_IF_FALSE（条件假跳）+ JUMP（跳过 else）

## Verification

- 单元样例 1 条（cases 断言）
- 物理基底：按 calibration 对照（编译/运行/断言裁决）

## References

- 单元库：compiler_code_units.py「编译-若则」
