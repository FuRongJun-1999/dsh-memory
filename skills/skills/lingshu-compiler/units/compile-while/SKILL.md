---
name: compile-while
description: >-
  循环编译 / 编译-循环 / （while 语 / 条件为假即退出。用户提到这些词时使用本技能。
  场景：对照：当…执行=while 语句（条件先判→体→回跳；假则跳出到循环后）。
  【不适用】Not for 以下场景：条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）
license: MIT
compatibility: >-
  cond_instrs/body_instrs 为指令列表（条件字节码/循环体字节码）
allowed-tools: Read Write Bash
metadata:
  version: "1.0"
  skill-author: 灵枢（AEIS）
  last-reviewed: "2026-08-29"
  kccs:
    trigger_words: ["循环编译", "编译-循环", "（while 语", "条件为假即退出"]
    when: "cond_instrs/body_instrs 为指令列表（条件字节码/循环体字节码）"
    sub: ["① 拼接条件指令 ② 假跳转至循环后 ③ 体尾回跳条件"]
    execute: "JUMP_IF_FALSE 跳出 + JUMP 回跳形成循环（while 语义）"
    not_applicable: ["条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）"]
  calibration: "对照：当…执行=while 语句（条件先判→体→回跳；假则跳出到循环后）"
---

# 编译-循环（compile-while）

## When to use

任务「循环编译」；对照：当…执行=while 语句（条件先判→体→回跳；假则跳出到循环后）。

## 克制条款（不适用条件）

条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）

## How to execute

JUMP_IF_FALSE 跳出 + JUMP 回跳形成循环（while 语义）

## Verification

- 单元样例 2 条（cases 断言）
- 物理基底：按 calibration 对照（编译/运行/断言裁决）

## References

- 单元库：compiler_code_units.py「编译-循环」
