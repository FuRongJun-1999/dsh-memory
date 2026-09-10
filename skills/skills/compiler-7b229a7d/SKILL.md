---
name: compiler-7b229a7d
description: >-
  紧凑编码 / 字节码-紧凑编码 / C3 .pbc 体 / encode 变。用户提到这些词时使用本技能。
  场景：对照：C3 .pbc 体积优化——varint 变长整数（小整数 1 字节）。
  【不适用】Not for 以下场景：b 越界（Lt）时；mode 非 {decode, encode} 时
license: MIT
compatibility: >-
  mode ∈ {decode, encode}
allowed-tools: Read Write Bash
metadata:
  version: "1.0"
  skill-author: 灵枢（AEIS）
  last-reviewed: "2026-08-29"
  kccs:
    trigger_words: ["紧凑编码", "字节码-紧凑编码", "C3 .pbc 体", "encode 变"]
    when: "mode ∈ {decode, encode}"
    sub: ["1 mode 分支处理"]
    execute: "按 op 分派；循环迭代；顺序调用"
    not_applicable: ["b 越界（Lt）时；mode 非 {decode, encode} 时"]
  calibration: "对照：C3 .pbc 体积优化——varint 变长整数（小整数 1 字节）"
---

# 字节码-紧凑编码（compiler-7b229a7d）

## When to use

任务「紧凑编码」；对照：C3 .pbc 体积优化——varint 变长整数（小整数 1 字节）。

## 克制条款（不适用条件）

b 越界（Lt）时；mode 非 {decode, encode} 时

## How to execute

按 op 分派；循环迭代；顺序调用

## Verification

- 单元样例 4 条（cases 断言）
- 物理基底：按 calibration 对照（编译/运行/断言裁决）

## References

- 单元库：compiler_code_units.py「字节码-紧凑编码」
