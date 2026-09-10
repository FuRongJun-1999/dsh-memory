---
name: net-d5fefa59
description: >-
  数据序列化 / 网络-数据序列化 / 字段表+值 → 紧凑编码。用户提到这些词时使用本技能。
  场景：对照：protobuf 序列化——字段序号+类型+值紧凑编码。
  【不适用】Not for 以下场景：条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）
license: MIT
compatibility: >-
  参数 fields/values 合法
allowed-tools: Read Write Bash
metadata:
  version: "1.0"
  skill-author: 灵枢（AEIS）
  last-reviewed: "2026-08-29"
  kccs:
    trigger_words: ["数据序列化", "网络-数据序列化", "字段表+值 → 紧凑编码"]
    when: "参数 fields/values 合法"
    sub: ["① 调用 enumerate"]
    execute: "循环迭代；顺序调用"
    not_applicable: ["条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）"]
  calibration: "对照：protobuf 序列化——字段序号+类型+值紧凑编码"
---

# 网络-数据序列化（net-d5fefa59）

## When to use

任务「数据序列化」；对照：protobuf 序列化——字段序号+类型+值紧凑编码。

## 克制条款（不适用条件）

条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）

## How to execute

循环迭代；顺序调用

## Verification

- 单元样例 3 条（cases 断言）
- 物理基底：按 calibration 对照（编译/运行/断言裁决）

## References

- 单元库：compiler_code_units.py「网络-数据序列化」
