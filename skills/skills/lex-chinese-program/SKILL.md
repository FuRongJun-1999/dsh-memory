---
name: lex-chinese-program
description: >-
  中文程序词法 / 词法-中文程序 / 中文程序行 → 。用户提到这些词时使用本技能。
  场景：对照：protocol-compiler lexer（九章算术结构/若则/道德经指令/步骤序号）。
  【不适用】Not for 以下场景：条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）
license: MIT
compatibility: >-
  line 为中文程序源码行
allowed-tools: Read Write Bash
metadata:
  version: "1.0"
  skill-author: 灵枢（AEIS）
  last-reviewed: "2026-08-29"
  kccs:
    trigger_words: ["中文程序词法", "词法-中文程序", "中文程序行 → "]
    when: "line 为中文程序源码行"
    sub: ["① 九章算术结构识别 ② 条件/指令/步骤分类 ③ 提取载荷"]
    execute: "前缀匹配 + 分类返回 (kind, payload)"
    not_applicable: ["条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）"]
  calibration: "对照：protocol-compiler lexer（九章算术结构/若则/道德经指令/步骤序号）"
---

# 词法-中文程序（lex-chinese-program）

## When to use

任务「中文程序词法」；对照：protocol-compiler lexer（九章算术结构/若则/道德经指令/步骤序号）。

## 克制条款（不适用条件）

条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）

## How to execute

前缀匹配 + 分类返回 (kind, payload)

## Verification

- 单元样例 7 条（cases 断言）
- 物理基底：按 calibration 对照（编译/运行/断言裁决）

## References

- 单元库：compiler_code_units.py「词法-中文程序」
