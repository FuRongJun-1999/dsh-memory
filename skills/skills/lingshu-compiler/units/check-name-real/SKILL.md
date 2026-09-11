---
name: check-name-real
description: >-
  名实校验 / 校验-名实 / name_checker / 以名举实 / 要求的符号必须已声明。用户提到这些词时使用本技能。
  场景：对照：name_checker 以名举实（符号表→协议实体）。
  【不适用】Not for 以下场景：条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）
license: MIT
compatibility: >-
  参数 required/declared 合法
allowed-tools: Read Write Bash
metadata:
  version: "1.0"
  skill-author: 灵枢（AEIS）
  last-reviewed: "2026-08-29"
  kccs:
    trigger_words: ["名实校验", "校验-名实", "name_checker", "以名举实", "要求的符号必须已声明"]
    when: "参数 required/declared 合法"
    sub: []
    execute: "以名举实：要求的符号必须已声明（墨辩静态检查）"
    not_applicable: ["条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）"]
  calibration: "对照：name_checker 以名举实（符号表→协议实体）"
---

# 校验-名实（check-name-real）

## When to use

任务「名实校验」；对照：name_checker 以名举实（符号表→协议实体）。

## 克制条款（不适用条件）

条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）

## How to execute

以名举实：要求的符号必须已声明（墨辩静态检查）

## Verification

- 单元样例 3 条（cases 断言）
- 物理基底：按 calibration 对照（编译/运行/断言裁决）

## References

- 单元库：compiler_code_units.py「校验-名实」
