---
name: compiler-cf5776a4
description: >-
  字节码序列化 / 字节码-序列化 / C3 原。用户提到这些词时使用本技能。
  场景：对照：C3 原生编译——字节码文件格式（op字符串+arg类型标记编码）。
  【不适用】Not for 以下场景：条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）
license: MIT
compatibility: >-
  code 为 (op, arg) 指令列表；arg 为 int/str/None
allowed-tools: Read Write Bash
metadata:
  version: "1.0"
  skill-author: 灵枢（AEIS）
  last-reviewed: "2026-08-29"
  kccs:
    trigger_words: ["字节码序列化", "字节码-序列化", "C3 原"]
    when: "code 为 (op, arg) 指令列表；arg 为 int/str/None"
    sub: ["① op 定长前缀编码 ② arg 类型分派编码 ③ 拼装字节串"]
    execute: "struct.pack 前缀长度 + utf-8 op + arg 按类型编码"
    not_applicable: ["条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）"]
  calibration: "对照：C3 原生编译——字节码文件格式（op字符串+arg类型标记编码）"
---

# 字节码-序列化（compiler-cf5776a4）

## When to use

任务「字节码序列化」；对照：C3 原生编译——字节码文件格式（op字符串+arg类型标记编码）。

## 克制条款（不适用条件）

条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）

## How to execute

struct.pack 前缀长度 + utf-8 op + arg 按类型编码

## Verification

- 单元样例 1 条（cases 断言）
- 物理基底：按 calibration 对照（编译/运行/断言裁决）

## References

- 单元库：compiler_code_units.py「字节码-序列化」
