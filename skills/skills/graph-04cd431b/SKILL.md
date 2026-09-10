---
name: graph-04cd431b
description: >-
  时序查询 / 图查询-时序查询 / 时序图查询——时间点最近 / 时序图查询 / 时间点 → 该时刻图状态。用户提到这些词时使用本技能。
  场景：对照：时序图查询——时间点最近快照（快照序列时间回溯）。
  【不适用】Not for 以下场景：条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）
license: MIT
compatibility: >-
  参数 history/time 合法
allowed-tools: Read Write Bash
metadata:
  version: "1.0"
  skill-author: 灵枢（AEIS）
  last-reviewed: "2026-08-29"
  kccs:
    trigger_words: ["时序查询", "图查询-时序查询", "时序图查询——时间点最近", "时序图查询", "时间点 → 该时刻图状态"]
    when: "参数 history/time 合法"
    sub: ["① 调用 sorted"]
    execute: "循环迭代；顺序调用"
    not_applicable: ["条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）"]
  calibration: "对照：时序图查询——时间点最近快照（快照序列时间回溯）"
---

# 图查询-时序查询（graph-04cd431b）

## When to use

任务「时序查询」；对照：时序图查询——时间点最近快照（快照序列时间回溯）。

## 克制条款（不适用条件）

条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）

## How to execute

循环迭代；顺序调用

## Verification

- 单元样例 3 条（cases 断言）
- 物理基底：按 calibration 对照（编译/运行/断言裁决）

## References

- 单元库：compiler_code_units.py「图查询-时序查询」
