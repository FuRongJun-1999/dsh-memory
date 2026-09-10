---
name: compiler-61ff016b
description: >-
  名实一致 / 校验-名实一致 / 名实校验——引用须绑定实 / 名实校验 / 名称引用须有绑定实体。用户提到这些词时使用本技能。
  场景：对照：名实校验——引用须绑定实体（以名举实，未绑定拦截）。
  【不适用】Not for 以下场景：条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）
license: MIT
compatibility: >-
  参数 refs/bindings 合法
allowed-tools: Read Write Bash
metadata:
  version: "1.0"
  skill-author: 灵枢（AEIS）
  last-reviewed: "2026-08-29"
  kccs:
    trigger_words: ["名实一致", "校验-名实一致", "名实校验——引用须绑定实", "名实校验", "名称引用须有绑定实体"]
    when: "参数 refs/bindings 合法"
    sub: []
    execute: "名实校验：名称引用须有绑定实体（以名举实——墨辩语义）"
    not_applicable: ["条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）"]
  calibration: "对照：名实校验——引用须绑定实体（以名举实，未绑定拦截）"
---

# 校验-名实一致（compiler-61ff016b）

## When to use

任务「名实一致」；对照：名实校验——引用须绑定实体（以名举实，未绑定拦截）。

## 克制条款（不适用条件）

条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）

## How to execute

名实校验：名称引用须有绑定实体（以名举实——墨辩语义）

## Verification

- 单元样例 3 条（cases 断言）
- 物理基底：按 calibration 对照（编译/运行/断言裁决）

## References

- 单元库：compiler_code_units.py「校验-名实一致」
