---
name: net-47a19838
description: >-
  消息分帧 / 蜂群-消息分帧 / 会话层——字节流分帧 / 蜂群会话层 / 字节流按分隔符分帧。用户提到这些词时使用本技能。
  场景：对照：会话层——字节流分帧（粘包拆帧、半包留待下段）。
  【不适用】Not for 以下场景：idx 越界（Lt）时
license: MIT
compatibility: >-
  buf.find 可用
allowed-tools: Read Write Bash
metadata:
  version: "1.0"
  skill-author: 灵枢（AEIS）
  last-reviewed: "2026-08-29"
  kccs:
    trigger_words: ["消息分帧", "蜂群-消息分帧", "会话层——字节流分帧", "蜂群会话层", "字节流按分隔符分帧"]
    when: "buf.find 可用"
    sub: ["① 调用 len"]
    execute: "循环迭代；顺序调用"
    not_applicable: ["idx 越界（Lt）时"]
  calibration: "对照：会话层——字节流分帧（粘包拆帧、半包留待下段）"
---

# 蜂群-消息分帧（net-47a19838）

## When to use

任务「消息分帧」；对照：会话层——字节流分帧（粘包拆帧、半包留待下段）。

## 克制条款（不适用条件）

idx 越界（Lt）时

## How to execute

循环迭代；顺序调用

## Verification

- 单元样例 3 条（cases 断言）
- 物理基底：按 calibration 对照（编译/运行/断言裁决）

## References

- 单元库：compiler_code_units.py「蜂群-消息分帧」
