---
name: vm-run-loop
description: >-
  执行循环 / VM-执行循环 / condition_vm。用户提到这些词时使用本技能。
  场景：对照：condition_vm 执行循环（止=halt/无为=yield/名实不符=错误）。
  【不适用】Not for 以下场景：op 非 {DAO, DE, JUMP, JUMP_IF_FALSE, LOAD, PUSH, STORE, WUWEI, ZHI, ZHIZU, ZIRAN} 时
license: MIT
compatibility: >-
  code 为指令列表；symbols 为符号表；trust 为初始信任值
allowed-tools: Read Write Bash
metadata:
  version: "1.0"
  skill-author: 灵枢（AEIS）
  last-reviewed: "2026-08-29"
  kccs:
    trigger_words: ["执行循环", "VM-执行循环", "condition_vm"]
    when: "code 为指令列表；symbols 为符号表；trust 为初始信任值"
    sub: ["① 按 ip 取指执行 ② 控制流信号处理 ③ 名实校验拦截"]
    execute: "循环取指分派，止/无为跳转，名实不符报错"
    not_applicable: ["op 非 {DAO, DE, JUMP, JUMP_IF_FALSE, LOAD, PUSH, STORE, WUWEI, ZHI, ZHIZU, ZIRAN} 时"]
  calibration: "对照：condition_vm 执行循环（止=halt/无为=yield/名实不符=错误）"
---

# VM-执行循环（vm-run-loop）

## When to use

任务「执行循环」；对照：condition_vm 执行循环（止=halt/无为=yield/名实不符=错误）。

## 克制条款（不适用条件）

op 非 {DAO, DE, JUMP, JUMP_IF_FALSE, LOAD, PUSH, STORE, WUWEI, ZHI, ZHIZU, ZIRAN} 时

## How to execute

循环取指分派，止/无为跳转，名实不符报错

## Verification

- 单元样例 8 条（cases 断言）
- 物理基底：按 calibration 对照（编译/运行/断言裁决）

## References

- 单元库：compiler_code_units.py「VM-执行循环」
