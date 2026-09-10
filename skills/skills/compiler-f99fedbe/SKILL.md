---
name: compiler-f99fedbe
description: >-
  条件空间符号类型 / 校验-条件空间符号类型 / C2 语 / 条件空间=类型系统 / 条件声明中的符号必须已定 / conditions: 。用户提到这些词时使用本技能。
  场景：对照：C2 语义——条件空间=类型系统（若条件空间X则符号Y类型Z 编译期校验）。
  【不适用】Not for 以下场景：条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）
license: MIT
compatibility: >-
  参数 conditions/symbol_types 合法
allowed-tools: Read Write Bash
metadata:
  version: "1.0"
  skill-author: 灵枢（AEIS）
  last-reviewed: "2026-08-29"
  kccs:
    trigger_words: ["条件空间符号类型", "校验-条件空间符号类型", "C2 语", "条件空间=类型系统", "条件声明中的符号必须已定", "conditions: "]
    when: "参数 conditions/symbol_types 合法"
    sub: []
    execute: "条件空间=类型系统：条件声明中的符号必须已定义类型（编译期静态检查）；conditions: [{'space': '伴侣', 'symbol': '情感权重', 'type': '数值'}]"
    not_applicable: ["条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）"]
  calibration: "对照：C2 语义——条件空间=类型系统（若条件空间X则符号Y类型Z 编译期校验）"
---

# 校验-条件空间符号类型（compiler-f99fedbe）

## When to use

任务「条件空间符号类型」；对照：C2 语义——条件空间=类型系统（若条件空间X则符号Y类型Z 编译期校验）。

## 克制条款（不适用条件）

条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）

## How to execute

条件空间=类型系统：条件声明中的符号必须已定义类型（编译期静态检查）；conditions: [{'space': '伴侣', 'symbol': '情感权重', 'type': '数值'}]

## Verification

- 单元样例 3 条（cases 断言）
- 物理基底：按 calibration 对照（编译/运行/断言裁决）

## References

- 单元库：compiler_code_units.py「校验-条件空间符号类型」
