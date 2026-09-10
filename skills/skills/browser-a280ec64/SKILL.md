---
name: browser-a280ec64
description: >-
  网络信息 / 浏览器-网络信息 / set 记。用户提到这些词时使用本技能。
  场景：对照：Network Information API——effectiveType 网络类型与高速判定。
  【不适用】Not for 以下场景：op 非 {fast, get, set} 时
license: MIT
compatibility: >-
  op ∈ {fast, get, set}
allowed-tools: Read Write Bash
metadata:
  version: "1.0"
  skill-author: 灵枢（AEIS）
  last-reviewed: "2026-08-29"
  kccs:
    trigger_words: ["网络信息", "浏览器-网络信息", "set 记"]
    when: "op ∈ {fast, get, set}"
    sub: ["① op 分支处理"]
    execute: "按 op 分派"
    not_applicable: ["op 非 {fast, get, set} 时"]
  calibration: "对照：Network Information API——effectiveType 网络类型与高速判定"
---

# 浏览器-网络信息（browser-a280ec64）

## When to use

任务「网络信息」；对照：Network Information API——effectiveType 网络类型与高速判定。

## 克制条款（不适用条件）

op 非 {fast, get, set} 时

## How to execute

按 op 分派

## Verification

- 单元样例 4 条（cases 断言）
- 物理基底：按 calibration 对照（编译/运行/断言裁决）

## References

- 单元库：compiler_code_units.py「浏览器-网络信息」
