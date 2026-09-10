---
name: os-0c7f14cb
description: >-
  稀疏文件 / 文件-稀疏文件 / 稀疏文件——数据块存储+ / write 写。用户提到这些词时使用本技能。
  场景：对照：稀疏文件——数据块存储+空洞零填充（稀疏存储）。
  【不适用】Not for 以下场景：op 非 {holes, read, write} 时
license: MIT
compatibility: >-
  op ∈ {holes, read, write}
allowed-tools: Read Write Bash
metadata:
  version: "1.0"
  skill-author: 灵枢（AEIS）
  last-reviewed: "2026-08-29"
  kccs:
    trigger_words: ["稀疏文件", "文件-稀疏文件", "稀疏文件——数据块存储+", "write 写"]
    when: "op ∈ {holes, read, write}"
    sub: ["① op 分支处理"]
    execute: "按 op 分派；顺序调用"
    not_applicable: ["op 非 {holes, read, write} 时"]
  calibration: "对照：稀疏文件——数据块存储+空洞零填充（稀疏存储）"
---

# 文件-稀疏文件（os-0c7f14cb）

## When to use

任务「稀疏文件」；对照：稀疏文件——数据块存储+空洞零填充（稀疏存储）。

## 克制条款（不适用条件）

op 非 {holes, read, write} 时

## How to execute

按 op 分派；顺序调用

## Verification

- 单元样例 4 条（cases 断言）
- 物理基底：按 calibration 对照（编译/运行/断言裁决）

## References

- 单元库：compiler_code_units.py「文件-稀疏文件」
