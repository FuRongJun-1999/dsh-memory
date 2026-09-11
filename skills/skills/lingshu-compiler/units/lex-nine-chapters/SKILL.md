---
name: lex-nine-chapters
description: >-
  九章算术 / 词法-九章算术 / DAYUE / SHUYUE / 九章算术结构 / 问曰/答曰/术曰 → 。用户提到这些词时使用本技能。
  场景：对照：TokenType WENYUE/DAYUE/SHUYUE（九章算术结构）。
  【不适用】Not for 以下场景：条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）
license: MIT
compatibility: >-
  text 以九章算术结构词（问曰/答曰/术曰）开头
allowed-tools: Read Write Bash
metadata:
  version: "1.0"
  skill-author: 灵枢（AEIS）
  last-reviewed: "2026-08-29"
  kccs:
    trigger_words: ["九章算术", "词法-九章算术", "DAYUE", "SHUYUE", "九章算术结构", "问曰/答曰/术曰 → "]
    when: "text 以九章算术结构词（问曰/答曰/术曰）开头"
    sub: ["① 结构词前缀匹配 ② 命中返回类型标记 ③ 未命中返 None"]
    execute: "顺序匹配三个结构词，命中即返 (词_STRUCT, 词)"
    not_applicable: ["条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）"]
  calibration: "对照：TokenType WENYUE/DAYUE/SHUYUE（九章算术结构）"
---

# 词法-九章算术（lex-nine-chapters）

## When to use

任务「九章算术」；对照：TokenType WENYUE/DAYUE/SHUYUE（九章算术结构）。

## 克制条款（不适用条件）

条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）

## How to execute

顺序匹配三个结构词，命中即返 (词_STRUCT, 词)

## Verification

- 单元样例 4 条（cases 断言）
- 物理基底：按 calibration 对照（编译/运行/断言裁决）

## References

- 单元库：compiler_code_units.py「词法-九章算术」
