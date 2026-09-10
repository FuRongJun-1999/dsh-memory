---
name: os-607f1963
description: >-
  磁盘配额 / 文件-磁盘配额 / OS 磁 / 用户使用量 + 新写入 。用户提到这些词时使用本技能。
  场景：对照：OS 磁盘配额——用户限额（使用量+写入 ≤ 限额，超限拒绝）。
  【不适用】Not for 以下场景：条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）
license: MIT
compatibility: >-
  参数 quotas/user/usage/size 合法
allowed-tools: Read Write Bash
metadata:
  version: "1.0"
  skill-author: 灵枢（AEIS）
  last-reviewed: "2026-08-29"
  kccs:
    trigger_words: ["磁盘配额", "文件-磁盘配额", "OS 磁", "用户使用量 + 新写入 "]
    when: "参数 quotas/user/usage/size 合法"
    sub: ["① 调用 float"]
    execute: "顺序调用"
    not_applicable: ["条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）"]
  calibration: "对照：OS 磁盘配额——用户限额（使用量+写入 ≤ 限额，超限拒绝）"
---

# 文件-磁盘配额（os-607f1963）

## When to use

任务「磁盘配额」；对照：OS 磁盘配额——用户限额（使用量+写入 ≤ 限额，超限拒绝）。

## 克制条款（不适用条件）

条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）

## How to execute

顺序调用

## Verification

- 单元样例 3 条（cases 断言）
- 物理基底：按 calibration 对照（编译/运行/断言裁决）

## References

- 单元库：compiler_code_units.py「文件-磁盘配额」
