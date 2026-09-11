---
name: compiler-0355bffb
description: >-
  VM单步 / 调试-单步 / C4 调 / VM 单 / 执行一条指令 → 。用户提到这些词时使用本技能。
  场景：对照：C4 调试器单步（一条指令 → 新状态；止/无为=控制流信号）。
  【不适用】Not for 以下场景：op 非 {DAO, DE, LOAD, PUSH, STORE, WUWEI, ZHI, ZHIZU, ZIRAN} 时
license: MIT
compatibility: >-
  code 为指令列表；ip 为当前指令指针
allowed-tools: Read Write Bash
metadata:
  version: "1.0"
  skill-author: 灵枢（AEIS）
  last-reviewed: "2026-08-29"
  kccs:
    trigger_words: ["VM单步", "调试-单步", "C4 调", "VM 单", "执行一条指令 → "]
    when: "code 为指令列表；ip 为当前指令指针"
    sub: ["① 取当前指令 ② 分派执行 ③ 返回下一状态"]
    execute: "按 op 分派，止/无为→halt，越界→None"
    not_applicable: ["op 非 {DAO, DE, LOAD, PUSH, STORE, WUWEI, ZHI, ZHIZU, ZIRAN} 时"]
  calibration: "对照：C4 调试器单步（一条指令 → 新状态；止/无为=控制流信号）"
---

# 调试-单步（compiler-0355bffb）

## When to use

任务「VM单步」；对照：C4 调试器单步（一条指令 → 新状态；止/无为=控制流信号）。

## 克制条款（不适用条件）

op 非 {DAO, DE, LOAD, PUSH, STORE, WUWEI, ZHI, ZHIZU, ZIRAN} 时

## How to execute

按 op 分派，止/无为→halt，越界→None

## Verification

- 单元样例 3 条（cases 断言）
- 物理基底：按 calibration 对照（编译/运行/断言裁决）

## References

- 单元库：compiler_code_units.py「调试-单步」
