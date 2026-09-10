---
name: os-192b8ca9
description: >-
  段式管理 / 内存-段式管理 / map 登。用户提到这些词时使用本技能。
  场景：对照：分段内存——段登记/基址+限长越界检查。
  【不适用】Not for 以下场景：op 非 {access, base, map} 时
license: MIT
compatibility: >-
  op ∈ {access, base, map}
allowed-tools: Read Write Bash
metadata:
  version: "1.0"
  skill-author: 灵枢（AEIS）
  last-reviewed: "2026-08-29"
  kccs:
    trigger_words: ["段式管理", "内存-段式管理", "map 登"]
    when: "op ∈ {access, base, map}"
    sub: ["① op 分支处理"]
    execute: "按 op 分派"
    not_applicable: ["op 非 {access, base, map} 时"]
  calibration: "对照：分段内存——段登记/基址+限长越界检查"
---

# 内存-段式管理（os-192b8ca9）

## When to use

任务「段式管理」；对照：分段内存——段登记/基址+限长越界检查。

## 克制条款（不适用条件）

op 非 {access, base, map} 时

## How to execute

按 op 分派

## Verification

- 单元样例 4 条（cases 断言）
- 物理基底：按 calibration 对照（编译/运行/断言裁决）

## References

- 单元库：compiler_code_units.py「内存-段式管理」
