---
name: compiler-a6daf076
description: >-
  字节码转储 / 分析-字节码转储 / C4 分 / 字节码 → 可读指令列表。用户提到这些词时使用本技能。
  场景：对照：C4 分析器字节码转储（可读调试输出）。
  【不适用】Not for 以下场景：条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）
license: MIT
compatibility: >-
  code 为指令列表（op, arg）
allowed-tools: Read Write Bash
metadata:
  version: "1.0"
  skill-author: 灵枢（AEIS）
  last-reviewed: "2026-08-29"
  kccs:
    trigger_words: ["字节码转储", "分析-字节码转储", "C4 分", "字节码 → 可读指令列表"]
    when: "code 为指令列表（op, arg）"
    sub: ["① 逐指令编号 ② 格式化指令行"]
    execute: "enumerate 生成 (地址, op, arg) 行"
    not_applicable: ["条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）"]
  calibration: "对照：C4 分析器字节码转储（可读调试输出）"
---

# 分析-字节码转储（compiler-a6daf076）

## When to use

任务「字节码转储」；对照：C4 分析器字节码转储（可读调试输出）。

## 克制条款（不适用条件）

条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）

## How to execute

enumerate 生成 (地址, op, arg) 行

## Verification

- 单元样例 1 条（cases 断言）
- 物理基底：按 calibration 对照（编译/运行/断言裁决）

## References

- 单元库：compiler_code_units.py「分析-字节码转储」
