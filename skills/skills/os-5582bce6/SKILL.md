---
name: os-5582bce6
description: >-
  日志恢复 / 文件-日志恢复 / OS 文 / 文件系统日志 / 崩溃后重放。用户提到这些词时使用本技能。
  场景：对照：OS 文件系统日志——journal 重放（崩溃恢复，write/delete 条目应用）。
  【不适用】Not for 以下场景：条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）
license: MIT
compatibility: >-
  参数 entries/disk 合法
allowed-tools: Read Write Bash
metadata:
  version: "1.0"
  skill-author: 灵枢（AEIS）
  last-reviewed: "2026-08-29"
  kccs:
    trigger_words: ["日志恢复", "文件-日志恢复", "OS 文", "文件系统日志", "崩溃后重放"]
    when: "参数 entries/disk 合法"
    sub: ["① 调用 dict"]
    execute: "循环迭代；顺序调用"
    not_applicable: ["条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）"]
  calibration: "对照：OS 文件系统日志——journal 重放（崩溃恢复，write/delete 条目应用）"
---

# 文件-日志恢复（os-5582bce6）

## When to use

任务「日志恢复」；对照：OS 文件系统日志——journal 重放（崩溃恢复，write/delete 条目应用）。

## 克制条款（不适用条件）

条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）

## How to execute

循环迭代；顺序调用

## Verification

- 单元样例 2 条（cases 断言）
- 物理基底：按 calibration 对照（编译/运行/断言裁决）

## References

- 单元库：compiler_code_units.py「文件-日志恢复」
