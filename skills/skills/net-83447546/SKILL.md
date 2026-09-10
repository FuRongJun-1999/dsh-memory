---
name: net-83447546
description: >-
  数据去重 / 网络-数据去重 / 网络去重——指纹识别重复 / hash 指。用户提到这些词时使用本技能。
  场景：对照：网络去重——指纹识别重复载荷（dedup）。
  【不适用】Not for 以下场景：op 非 {dedup, hash, store} 时
license: MIT
compatibility: >-
  op ∈ {dedup, hash, store}
allowed-tools: Read Write Bash
metadata:
  version: "1.0"
  skill-author: 灵枢（AEIS）
  last-reviewed: "2026-08-29"
  kccs:
    trigger_words: ["数据去重", "网络-数据去重", "网络去重——指纹识别重复", "hash 指"]
    when: "op ∈ {dedup, hash, store}"
    sub: ["① op 分支处理"]
    execute: "按 op 分派；顺序调用"
    not_applicable: ["op 非 {dedup, hash, store} 时"]
  calibration: "对照：网络去重——指纹识别重复载荷（dedup）"
---

# 网络-数据去重（net-83447546）

## When to use

任务「数据去重」；对照：网络去重——指纹识别重复载荷（dedup）。

## 克制条款（不适用条件）

op 非 {dedup, hash, store} 时

## How to execute

按 op 分派；顺序调用

## Verification

- 单元样例 4 条（cases 断言）
- 物理基底：按 calibration 对照（编译/运行/断言裁决）

## References

- 单元库：compiler_code_units.py「网络-数据去重」
