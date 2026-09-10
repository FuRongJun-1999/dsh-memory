---
name: os-128f3820
description: >-
  模块加载 / 系统-模块加载 / 依赖满足才注册。用户提到这些词时使用本技能。
  场景：对照：内核模块装载——依赖全部已注册才加载，缺依赖拒绝。
  【不适用】Not for 以下场景：条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）
license: MIT
compatibility: >-
  registry 为已加载模块表；deps 为模块依赖名列表
allowed-tools: Read Write Bash
metadata:
  version: "1.0"
  skill-author: 灵枢（AEIS）
  last-reviewed: "2026-08-29"
  kccs:
    trigger_words: ["模块加载", "系统-模块加载", "依赖满足才注册"]
    when: "registry 为已加载模块表；deps 为模块依赖名列表"
    sub: ["① 依赖存在性检查 ② 全满足注册 ③ 缺依赖拒绝"]
    execute: "all(d in registry) → 注册返回 ok，否则 missing_deps"
    not_applicable: ["条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）"]
  calibration: "对照：内核模块装载——依赖全部已注册才加载，缺依赖拒绝"
---

# 系统-模块加载（os-128f3820）

## When to use

任务「模块加载」；对照：内核模块装载——依赖全部已注册才加载，缺依赖拒绝。

## 克制条款（不适用条件）

条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）

## How to execute

all(d in registry) → 注册返回 ok，否则 missing_deps

## Verification

- 单元样例 4 条（cases 断言）
- 物理基底：按 calibration 对照（编译/运行/断言裁决）

## References

- 单元库：compiler_code_units.py「系统-模块加载」
