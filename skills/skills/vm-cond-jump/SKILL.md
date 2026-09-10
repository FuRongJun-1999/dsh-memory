---
name: vm-cond-jump
description: >-
  条件跳转 / VM-条件跳转 / 若…则…否则 / 栈顶为假则跳转。用户提到这些词时使用本技能。
  场景：对照：若条件为假则跳过 then 执行 else（JUMP_IF_FALSE）。
  【不适用】Not for 以下场景：stack 为空/非法时（隐式盲区：返回默认值 1 = 未知行为——不适用）
license: MIT
compatibility: >-
  参数 stack/ip/target 合法
allowed-tools: Read Write Bash
metadata:
  version: "1.0"
  skill-author: 灵枢（AEIS）
  last-reviewed: "2026-08-29"
  kccs:
    trigger_words: ["条件跳转", "VM-条件跳转", "若…则…否则", "栈顶为假则跳转"]
    when: "参数 stack/ip/target 合法"
    sub: ["① 条件判定 ② 结果处理"]
    execute: "若…则…否则：栈顶为假则跳转（智能论条件语句的 VM 语义）"
    not_applicable: ["stack 为空/非法时（隐式盲区：返回默认值 1 = 未知行为——不适用）"]
  calibration: "对照：若条件为假则跳过 then 执行 else（JUMP_IF_FALSE）"
---

# VM-条件跳转（vm-cond-jump）

## When to use

任务「条件跳转」；对照：若条件为假则跳过 then 执行 else（JUMP_IF_FALSE）。

## 克制条款（不适用条件）

stack 为空/非法时（隐式盲区：返回默认值 1 = 未知行为——不适用）

## How to execute

若…则…否则：栈顶为假则跳转（智能论条件语句的 VM 语义）

## Verification

- 单元样例 5 条（cases 断言）
- 物理基底：按 calibration 对照（编译/运行/断言裁决）

## References

- 单元库：compiler_code_units.py「VM-条件跳转」
