---
name: browser-434b74b8
description: >-
  资源优先级 / 浏览器-资源优先级 / register 登。用户提到这些词时使用本技能。
  场景：对照：资源优先级——关键脚本/样式优先加载。
  【不适用】Not for 以下场景：op 非 {priority, register} 时
license: MIT
compatibility: >-
  op ∈ {priority, register}
allowed-tools: Read Write Bash
metadata:
  version: "1.0"
  skill-author: 灵枢（AEIS）
  last-reviewed: "2026-08-29"
  kccs:
    trigger_words: ["资源优先级", "浏览器-资源优先级", "register 登"]
    when: "op ∈ {priority, register}"
    sub: ["① op 分支处理"]
    execute: "按 op 分派"
    not_applicable: ["op 非 {priority, register} 时"]
  calibration: "对照：资源优先级——关键脚本/样式优先加载"
---

# 浏览器-资源优先级（browser-434b74b8）

## When to use

任务「资源优先级」；对照：资源优先级——关键脚本/样式优先加载。

## 克制条款（不适用条件）

op 非 {priority, register} 时

## How to execute

按 op 分派

## Verification

- 单元样例 4 条（cases 断言）
- 物理基底：按 calibration 对照（编译/运行/断言裁决）

## References

- 单元库：compiler_code_units.py「浏览器-资源优先级」
