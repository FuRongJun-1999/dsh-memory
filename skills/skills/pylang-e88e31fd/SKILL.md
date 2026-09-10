---
name: pylang-e88e31fd
description: >-
  文本分词 / 工具-文本分词 / tokenize——非 / 非字母字符分割并转小写。用户提到这些词时使用本技能。
  场景：对照：tokenize——非字母数字分割（文本分词）。
  【不适用】Not for 以下场景：条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）
license: MIT
compatibility: >-
  text.lower 可用
allowed-tools: Read Write Bash
metadata:
  version: "1.0"
  skill-author: 灵枢（AEIS）
  last-reviewed: "2026-08-29"
  kccs:
    trigger_words: ["文本分词", "工具-文本分词", "tokenize——非", "非字母字符分割并转小写"]
    when: "text.lower 可用"
    sub: []
    execute: "文本分词：非字母字符分割并转小写（简单 tokenizer）"
    not_applicable: ["条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）"]
  calibration: "对照：tokenize——非字母数字分割（文本分词）"
---

# 工具-文本分词（pylang-e88e31fd）

## When to use

任务「文本分词」；对照：tokenize——非字母数字分割（文本分词）。

## 克制条款（不适用条件）

条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）

## How to execute

文本分词：非字母字符分割并转小写（简单 tokenizer）

## Verification

- 单元样例 3 条（cases 断言）
- 物理基底：按 calibration 对照（编译/运行/断言裁决）

## References

- 单元库：compiler_code_units.py「工具-文本分词」
