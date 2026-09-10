---
name: lex-dao-de-jing
description: >-
  道德经词法 / 词法-道德经 / TokenType 道 / 道德经助记符。用户提到这些词时使用本技能。
  场景：对照：TokenType 道德经助记符（道/德/自然/无为/谷/牝/柔/朴/止/知足）。
  【不适用】Not for 以下场景：条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）
license: MIT
compatibility: >-
  word 为道德经助记符文本（道/德/自然/无为/止/知足）
allowed-tools: Read Write Bash
metadata:
  version: "1.0"
  skill-author: 灵枢（AEIS）
  last-reviewed: "2026-08-29"
  kccs:
    trigger_words: ["道德经词法", "词法-道德经", "TokenType 道", "道德经助记符"]
    when: "word 为道德经助记符文本（道/德/自然/无为/止/知足）"
    sub: ["① 剥离尾部标点 ② 助记符查映射表 ③ 未收录返回 None"]
    execute: "rstrip 标点 + dict.get，命中返指令码"
    not_applicable: ["条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）"]
  calibration: "对照：TokenType 道德经助记符（道/德/自然/无为/谷/牝/柔/朴/止/知足）"
---

# 词法-道德经（lex-dao-de-jing）

## When to use

任务「道德经词法」；对照：TokenType 道德经助记符（道/德/自然/无为/谷/牝/柔/朴/止/知足）。

## 克制条款（不适用条件）

条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）

## How to execute

rstrip 标点 + dict.get，命中返指令码

## Verification

- 单元样例 6 条（cases 断言）
- 物理基底：按 calibration 对照（编译/运行/断言裁决）

## References

- 单元库：compiler_code_units.py「词法-道德经」
