---
name: pylang-ca9332cf
description: >-
  动态建类 / 元编程-动态建类 / type 运 / （元编程——类型即工厂 / 运行期定义新类型）。用户提到这些词时使用本技能。
  场景：对照：CPython type(name, bases, dict)（动态创建类；无显式基类→隐式 object 基类）。
  【不适用】Not for 以下场景：条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）
license: MIT
compatibility: >-
  k.startswith 可用
allowed-tools: Read Write Bash
metadata:
  version: "1.0"
  skill-author: 灵枢（AEIS）
  last-reviewed: "2026-08-29"
  kccs:
    trigger_words: ["动态建类", "元编程-动态建类", "type 运", "（元编程——类型即工厂", "运行期定义新类型）"]
    when: "k.startswith 可用"
    sub: ["① 调用 type；② 调用 tuple；③ 调用 dict"]
    execute: "顺序调用"
    not_applicable: ["条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）"]
  calibration: "对照：CPython type(name, bases, dict)（动态创建类；无显式基类→隐式 object 基类）"
---

# 元编程-动态建类（pylang-ca9332cf）

## When to use

任务「动态建类」；对照：CPython type(name, bases, dict)（动态创建类；无显式基类→隐式 object 基类）。

## 克制条款（不适用条件）

条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）

## How to execute

顺序调用

## Verification

- 单元样例 2 条（cases 断言）
- 物理基底：按 calibration 对照（编译/运行/断言裁决）

## References

- 单元库：compiler_code_units.py「元编程-动态建类」
