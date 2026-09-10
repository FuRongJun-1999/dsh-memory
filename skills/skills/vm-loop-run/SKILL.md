---
name: vm-loop-run
description: >-
  循环执行 / VM-循环执行 / while 循 / 算术+比较+回跳。用户提到这些词时使用本技能。
  场景：对照：while 循环 VM 运行（i=1→3 累积 1+2=3 于 s；死循环被步数上限拦截）。
  【不适用】Not for 以下场景：op 非 {ADD, CMP_LT, JUMP, JUMP_IF_FALSE, LOAD, PUSH, STORE, SUB} 时
license: MIT
compatibility: >-
  op ∈ {ADD, CMP_LT, JUMP, JUMP_IF_FALSE, LOAD, PUSH, STORE, SUB}
allowed-tools: Read Write Bash
metadata:
  version: "1.0"
  skill-author: 灵枢（AEIS）
  last-reviewed: "2026-08-29"
  kccs:
    trigger_words: ["循环执行", "VM-循环执行", "while 循", "算术+比较+回跳"]
    when: "op ∈ {ADD, CMP_LT, JUMP, JUMP_IF_FALSE, LOAD, PUSH, STORE, SUB}"
    sub: ["① op 分支处理"]
    execute: "按 op 分派；循环迭代；顺序调用"
    not_applicable: ["op 非 {ADD, CMP_LT, JUMP, JUMP_IF_FALSE, LOAD, PUSH, STORE, SUB} 时"]
  calibration: "对照：while 循环 VM 运行（i=1→3 累积 1+2=3 于 s；死循环被步数上限拦截）"
---

# VM-循环执行（vm-loop-run）

## When to use

任务「循环执行」；对照：while 循环 VM 运行（i=1→3 累积 1+2=3 于 s；死循环被步数上限拦截）。

## 克制条款（不适用条件）

op 非 {ADD, CMP_LT, JUMP, JUMP_IF_FALSE, LOAD, PUSH, STORE, SUB} 时

## How to execute

按 op 分派；循环迭代；顺序调用

## Verification

- 单元样例 3 条（cases 断言）
- 物理基底：按 calibration 对照（编译/运行/断言裁决）

## References

- 单元库：compiler_code_units.py「VM-循环执行」
