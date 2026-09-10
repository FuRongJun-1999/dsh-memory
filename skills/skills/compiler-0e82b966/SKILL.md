---
name: compiler-0e82b966
description: >-
  协议词法对接 / 对接-协议词法 / protocol-com。用户提到这些词时使用本技能。
  场景：对照：protocol-compiler TokenType 枚举（道德经助记符/若则/九章算术）。
  【不适用】Not for 以下场景：条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）
license: MIT
compatibility: >-
  参数 token_name 合法
allowed-tools: Read Write Bash
metadata:
  version: "1.0"
  skill-author: 灵枢（AEIS）
  last-reviewed: "2026-08-29"
  kccs:
    trigger_words: ["协议词法对接", "对接-协议词法", "protocol-com"]
    when: "参数 token_name 合法"
    sub: []
    execute: "protocol-compiler TokenType → 白箱指令名（真实词法对接校准基准）"
    not_applicable: ["条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）"]
  calibration: "对照：protocol-compiler TokenType 枚举（道德经助记符/若则/九章算术）"
---

# 对接-协议词法（compiler-0e82b966）

## When to use

任务「协议词法对接」；对照：protocol-compiler TokenType 枚举（道德经助记符/若则/九章算术）。

## 克制条款（不适用条件）

条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）

## How to execute

protocol-compiler TokenType → 白箱指令名（真实词法对接校准基准）

## Verification

- 单元样例 6 条（cases 断言）
- 物理基底：按 calibration 对照（编译/运行/断言裁决）

## References

- 单元库：compiler_code_units.py「对接-协议词法」
