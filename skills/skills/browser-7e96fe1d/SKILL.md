---
name: browser-7e96fe1d
description: >-
  混合模式 / 渲染-混合模式 / multiply 正。用户提到这些词时使用本技能。
  场景：对照：canvas 混合模式——multiply/screen/overlay 通道计算。
  【不适用】Not for 以下场景：b 越界（Lt）时；mode 非 {multiply, overlay, screen} 时
license: MIT
compatibility: >-
  mode ∈ {multiply, overlay, screen}
allowed-tools: Read Write Bash
metadata:
  version: "1.0"
  skill-author: 灵枢（AEIS）
  last-reviewed: "2026-08-29"
  kccs:
    trigger_words: ["混合模式", "渲染-混合模式", "multiply 正"]
    when: "mode ∈ {multiply, overlay, screen}"
    sub: ["1 mode 分支处理"]
    execute: "按 op 分派；顺序调用"
    not_applicable: ["b 越界（Lt）时；mode 非 {multiply, overlay, screen} 时"]
  calibration: "对照：canvas 混合模式——multiply/screen/overlay 通道计算"
---

# 渲染-混合模式（browser-7e96fe1d）

## When to use

任务「混合模式」；对照：canvas 混合模式——multiply/screen/overlay 通道计算。

## 克制条款（不适用条件）

b 越界（Lt）时；mode 非 {multiply, overlay, screen} 时

## How to execute

按 op 分派；顺序调用

## Verification

- 单元样例 4 条（cases 断言）
- 物理基底：按 calibration 对照（编译/运行/断言裁决）

## References

- 单元库：compiler_code_units.py「渲染-混合模式」
