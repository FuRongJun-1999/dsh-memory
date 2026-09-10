---
name: browser-25afee4d
description: >-
  沙箱隔离 / 安全-沙箱隔离 / iframe sandb / grant 授。用户提到这些词时使用本技能。
  场景：对照：iframe sandbox——权限裁剪（allow-scripts 等逐项授权/校验）。
  【不适用】Not for 以下场景：op 非 {check, grant, revoke} 时
license: MIT
compatibility: >-
  op ∈ {check, grant, revoke}；capabilities.discard 可用
allowed-tools: Read Write Bash
metadata:
  version: "1.0"
  skill-author: 灵枢（AEIS）
  last-reviewed: "2026-08-29"
  kccs:
    trigger_words: ["沙箱隔离", "安全-沙箱隔离", "iframe sandb", "grant 授"]
    when: "op ∈ {check, grant, revoke}；capabilities.discard 可用"
    sub: ["① op 分支处理"]
    execute: "按 op 分派"
    not_applicable: ["op 非 {check, grant, revoke} 时"]
  calibration: "对照：iframe sandbox——权限裁剪（allow-scripts 等逐项授权/校验）"
---

# 安全-沙箱隔离（browser-25afee4d）

## When to use

任务「沙箱隔离」；对照：iframe sandbox——权限裁剪（allow-scripts 等逐项授权/校验）。

## 克制条款（不适用条件）

op 非 {check, grant, revoke} 时

## How to execute

按 op 分派

## Verification

- 单元样例 4 条（cases 断言）
- 物理基底：按 calibration 对照（编译/运行/断言裁决）

## References

- 单元库：compiler_code_units.py「安全-沙箱隔离」
