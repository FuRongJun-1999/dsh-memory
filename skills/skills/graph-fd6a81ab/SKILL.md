---
name: graph-fd6a81ab
description: >-
  信任聚合 / 条件路由图-信任聚合 / 条件路由图——信任聚合 / 多路径信任合并。用户提到这些词时使用本技能。
  场景：对照：条件路由图——信任聚合（多路径合并取最大/平均）。
  【不适用】Not for 以下场景：op 非 {avg, max, record} 时
license: MIT
compatibility: >-
  op ∈ {avg, max, record}
allowed-tools: Read Write Bash
metadata:
  version: "1.0"
  skill-author: 灵枢（AEIS）
  last-reviewed: "2026-08-29"
  kccs:
    trigger_words: ["信任聚合", "条件路由图-信任聚合", "条件路由图——信任聚合", "多路径信任合并"]
    when: "op ∈ {avg, max, record}"
    sub: ["① op 分支处理"]
    execute: "按 op 分派；顺序调用"
    not_applicable: ["op 非 {avg, max, record} 时"]
  calibration: "对照：条件路由图——信任聚合（多路径合并取最大/平均）"
---

# 条件路由图-信任聚合（graph-fd6a81ab）

## When to use

任务「信任聚合」；对照：条件路由图——信任聚合（多路径合并取最大/平均）。

## 克制条款（不适用条件）

op 非 {avg, max, record} 时

## How to execute

按 op 分派；顺序调用

## Verification

- 单元样例 4 条（cases 断言）
- 物理基底：按 calibration 对照（编译/运行/断言裁决）

## References

- 单元库：compiler_code_units.py「条件路由图-信任聚合」
