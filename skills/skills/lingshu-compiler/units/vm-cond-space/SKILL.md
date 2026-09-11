---
name: vm-cond-space
description: >-
  条件空间 / VM-条件空间 / 创建协议路径。用户提到这些词时使用本技能。
  场景：对照：道=create_path（条件空间注册）、自然=restore_default。
  【不适用】Not for 以下场景：op 非 {自然, 道} 时（隐式盲区：返回默认值 [] = 未知行为——不适用）
license: MIT
compatibility: >-
  op ∈ {自然, 道}
allowed-tools: Read Write Bash
metadata:
  version: "1.0"
  skill-author: 灵枢（AEIS）
  last-reviewed: "2026-08-29"
  kccs:
    trigger_words: ["条件空间", "VM-条件空间", "创建协议路径"]
    when: "op ∈ {自然, 道}"
    sub: ["① op 分支处理"]
    execute: "按 op 分派；循环迭代；顺序调用"
    not_applicable: ["op 非 {自然, 道} 时（隐式盲区：返回默认值 [] = 未知行为——不适用）"]
  calibration: "对照：道=create_path（条件空间注册）、自然=restore_default"
---

# VM-条件空间（vm-cond-space）

## When to use

任务「条件空间」；对照：道=create_path（条件空间注册）、自然=restore_default。

## 克制条款（不适用条件）

op 非 {自然, 道} 时（隐式盲区：返回默认值 [] = 未知行为——不适用）

## How to execute

按 op 分派；循环迭代；顺序调用

## Verification

- 单元样例 2 条（cases 断言）
- 物理基底：按 calibration 对照（编译/运行/断言裁决）

## References

- 单元库：compiler_code_units.py「VM-条件空间」
