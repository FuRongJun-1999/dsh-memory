---
name: os-5a096a1f
description: >-
  系统调用 / 系统调用-接口 / OS 系 / 编号 → 处理函数分派。用户提到这些词时使用本技能。
  场景：对照：OS 系统调用——编号分派（syscall 表，未知编号返回 None）。
  【不适用】Not for 以下场景：条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）
license: MIT
compatibility: >-
  参数 table/num/args 合法
allowed-tools: Read Write Bash
metadata:
  version: "1.0"
  skill-author: 灵枢（AEIS）
  last-reviewed: "2026-08-29"
  kccs:
    trigger_words: ["系统调用", "系统调用-接口", "OS 系", "编号 → 处理函数分派"]
    when: "参数 table/num/args 合法"
    sub: ["① 调用 fn"]
    execute: "顺序调用"
    not_applicable: ["条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）"]
  calibration: "对照：OS 系统调用——编号分派（syscall 表，未知编号返回 None）"
---

# 系统调用-接口（os-5a096a1f）

## When to use

任务「系统调用」；对照：OS 系统调用——编号分派（syscall 表，未知编号返回 None）。

## 克制条款（不适用条件）

条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）

## How to execute

顺序调用

## Verification

- 单元样例 3 条（cases 断言）
- 物理基底：按 calibration 对照（编译/运行/断言裁决）

## References

- 单元库：compiler_code_units.py「系统调用-接口」
