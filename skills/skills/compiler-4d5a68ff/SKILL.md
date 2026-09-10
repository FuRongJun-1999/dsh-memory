---
name: compiler-4d5a68ff
description: >-
  条件空间类型 / 校验-条件空间类型 / 智能论——条件空间=类型 / 使用须在已声明空间内。用户提到这些词时使用本技能。
  场景：对照：智能论——条件空间=类型系统（未声明空间拦截）。
  【不适用】Not for 以下场景：条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）
license: MIT
compatibility: >-
  参数 declared/used 合法
allowed-tools: Read Write Bash
metadata:
  version: "1.0"
  skill-author: 灵枢（AEIS）
  last-reviewed: "2026-08-29"
  kccs:
    trigger_words: ["条件空间类型", "校验-条件空间类型", "智能论——条件空间=类型", "使用须在已声明空间内"]
    when: "参数 declared/used 合法"
    sub: ["① 调用 sorted；② 调用 set"]
    execute: "顺序调用"
    not_applicable: ["条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）"]
  calibration: "对照：智能论——条件空间=类型系统（未声明空间拦截）"
---

# 校验-条件空间类型（compiler-4d5a68ff）

## When to use

任务「条件空间类型」；对照：智能论——条件空间=类型系统（未声明空间拦截）。

## 克制条款（不适用条件）

条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）

## How to execute

顺序调用

## Verification

- 单元样例 3 条（cases 断言）
- 物理基底：按 calibration 对照（编译/运行/断言裁决）

## References

- 单元库：compiler_code_units.py「校验-条件空间类型」
