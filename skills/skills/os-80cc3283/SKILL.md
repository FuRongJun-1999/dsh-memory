---
name: os-80cc3283
description: >-
  缺页处理 / 内存-缺页处理 / OS 虚 / present=0 → 。用户提到这些词时使用本技能。
  场景：对照：OS 虚拟内存——缺页处理（命中/加载/无空闲帧拒绝；置换交由页置换策略）。
  【不适用】Not for 以下场景：free_frames 为空/非法时
license: MIT
compatibility: >-
  参数 page_table/vpn/free_frames/load 合法
allowed-tools: Read Write Bash
metadata:
  version: "1.0"
  skill-author: 灵枢（AEIS）
  last-reviewed: "2026-08-29"
  kccs:
    trigger_words: ["缺页处理", "内存-缺页处理", "OS 虚", "present=0 → "]
    when: "参数 page_table/vpn/free_frames/load 合法"
    sub: ["① 调用 load"]
    execute: "顺序调用"
    not_applicable: ["free_frames 为空/非法时"]
  calibration: "对照：OS 虚拟内存——缺页处理（命中/加载/无空闲帧拒绝；置换交由页置换策略）"
---

# 内存-缺页处理（os-80cc3283）

## When to use

任务「缺页处理」；对照：OS 虚拟内存——缺页处理（命中/加载/无空闲帧拒绝；置换交由页置换策略）。

## 克制条款（不适用条件）

free_frames 为空/非法时

## How to execute

顺序调用

## Verification

- 单元样例 3 条（cases 断言）
- 物理基底：按 calibration 对照（编译/运行/断言裁决）

## References

- 单元库：compiler_code_units.py「内存-缺页处理」
