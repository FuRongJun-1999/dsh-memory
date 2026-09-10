---
name: compiler-0f3787e6
description: >-
  字节码反序列化 / 字节码-反序列化 / C3 原 / .pbc 字。用户提到这些词时使用本技能。
  场景：对照：C3 原生编译——.pbc 加载（与序列化对称，往返一致性由校准⑫验证）。
  【不适用】Not for 以下场景：条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）
license: MIT
compatibility: >-
  struct.unpack_from 可用
allowed-tools: Read Write Bash
metadata:
  version: "1.0"
  skill-author: 灵枢（AEIS）
  last-reviewed: "2026-08-29"
  kccs:
    trigger_words: ["字节码反序列化", "字节码-反序列化", "C3 原", ".pbc 字"]
    when: "struct.unpack_from 可用"
    sub: ["① 调用 len；② 调用 ValueError；③ 调用 str"]
    execute: "循环迭代；顺序调用"
    not_applicable: ["条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）"]
  calibration: "对照：C3 原生编译——.pbc 加载（与序列化对称，往返一致性由校准⑫验证）"
---

# 字节码-反序列化（compiler-0f3787e6）

## When to use

任务「字节码反序列化」；对照：C3 原生编译——.pbc 加载（与序列化对称，往返一致性由校准⑫验证）。

## 克制条款（不适用条件）

条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）

## How to execute

循环迭代；顺序调用

## Verification

- 单元样例 2 条（cases 断言）
- 物理基底：按 calibration 对照（编译/运行/断言裁决）

## References

- 单元库：compiler_code_units.py「字节码-反序列化」
