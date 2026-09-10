---
name: pylang-ba956e52
description: >-
  JSON序列化 / 工具-JSON序列化 / loads / JSON 序 / dict ↔ 字。用户提到这些词时使用本技能。
  场景：对照：CPython json.dumps/loads（结构化数据序列化往返）。
  【不适用】Not for 以下场景：条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）
license: MIT
compatibility: >-
  json.loads 可用；json.dumps 可用
allowed-tools: Read Write Bash
metadata:
  version: "1.0"
  skill-author: 灵枢（AEIS）
  last-reviewed: "2026-08-29"
  kccs:
    trigger_words: ["JSON序列化", "工具-JSON序列化", "loads", "JSON 序", "dict ↔ 字"]
    when: "json.loads 可用；json.dumps 可用"
    sub: []
    execute: "JSON 序列化：dict ↔ 字符串往返（数据交换标准）"
    not_applicable: ["条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）"]
  calibration: "对照：CPython json.dumps/loads（结构化数据序列化往返）"
---

# 工具-JSON序列化（pylang-ba956e52）

## When to use

任务「JSON序列化」；对照：CPython json.dumps/loads（结构化数据序列化往返）。

## 克制条款（不适用条件）

条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）

## How to execute

JSON 序列化：dict ↔ 字符串往返（数据交换标准）

## Verification

- 单元样例 3 条（cases 断言）
- 物理基底：按 calibration 对照（编译/运行/断言裁决）

## References

- 单元库：compiler_code_units.py「工具-JSON序列化」
