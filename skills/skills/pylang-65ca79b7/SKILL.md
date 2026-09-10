---
name: pylang-65ca79b7
description: >-
  描述符协议 / 元编程-描述符协议 / CPython 描。用户提到这些词时使用本技能。
  场景：对照：CPython 描述符协议（__get__/__set__，property 与 @property 底层）。
  【不适用】Not for 以下场景：条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）
license: MIT
compatibility: >-
  参数 storage/desc/name/value 合法
allowed-tools: Read Write Bash
metadata:
  version: "1.0"
  skill-author: 灵枢（AEIS）
  last-reviewed: "2026-08-29"
  kccs:
    trigger_words: ["描述符协议", "元编程-描述符协议", "CPython 描"]
    when: "参数 storage/desc/name/value 合法"
    sub: ["① 条件判定 ② 结果处理"]
    execute: "描述符协议：读走 __get__ 写走 __set__（property 底层机制，属性访问托管）"
    not_applicable: ["条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）"]
  calibration: "对照：CPython 描述符协议（__get__/__set__，property 与 @property 底层）"
---

# 元编程-描述符协议（pylang-65ca79b7）

## When to use

任务「描述符协议」；对照：CPython 描述符协议（__get__/__set__，property 与 @property 底层）。

## 克制条款（不适用条件）

条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）

## How to execute

描述符协议：读走 __get__ 写走 __set__（property 底层机制，属性访问托管）

## Verification

- 单元样例 2 条（cases 断言）
- 物理基底：按 calibration 对照（编译/运行/断言裁决）

## References

- 单元库：compiler_code_units.py「元编程-描述符协议」
