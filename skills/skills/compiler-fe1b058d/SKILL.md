---
name: compiler-fe1b058d
description: >-
  操作符解析 / 词法-操作符解析 / 词法——操作符 / 多字符操作符优先。用户提到这些词时使用本技能。
  场景：对照：词法——操作符（最长匹配：双字符优先）。
  【不适用】Not for 以下场景：条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）
license: MIT
compatibility: >-
  参数 src/i 合法
allowed-tools: Read Write Bash
metadata:
  version: "1.0"
  skill-author: 灵枢（AEIS）
  last-reviewed: "2026-08-29"
  kccs:
    trigger_words: ["操作符解析", "词法-操作符解析", "词法——操作符", "多字符操作符优先"]
    when: "参数 src/i 合法"
    sub: ["① 条件判定 ② 结果处理"]
    execute: "操作符解析：多字符操作符优先（>= <= == != 先匹配双字符）"
    not_applicable: ["条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）"]
  calibration: "对照：词法——操作符（最长匹配：双字符优先）"
---

# 词法-操作符解析（compiler-fe1b058d）

## When to use

任务「操作符解析」；对照：词法——操作符（最长匹配：双字符优先）。

## 克制条款（不适用条件）

条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）

## How to execute

操作符解析：多字符操作符优先（>= <= == != 先匹配双字符）

## Verification

- 单元样例 4 条（cases 断言）
- 物理基底：按 calibration 对照（编译/运行/断言裁决）

## References

- 单元库：compiler_code_units.py「词法-操作符解析」
