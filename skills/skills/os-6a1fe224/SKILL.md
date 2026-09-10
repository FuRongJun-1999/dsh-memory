---
name: os-6a1fe224
description: >-
  页置换 / 内存-页置换 / OS 虚 / LRU 页 / 页序列 + 容量 → 缺。用户提到这些词时使用本技能。
  场景：对照：OS 虚拟内存——LRU 页置换（容量 3 时 8 页访问 5 次缺页）。
  【不适用】Not for 以下场景：条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）
license: MIT
compatibility: >-
  page_seq 为页访问序列；capacity 为物理帧容量
allowed-tools: Read Write Bash
metadata:
  version: "1.0"
  skill-author: 灵枢（AEIS）
  last-reviewed: "2026-08-29"
  kccs:
    trigger_words: ["页置换", "内存-页置换", "OS 虚", "LRU 页", "页序列 + 容量 → 缺"]
    when: "page_seq 为页访问序列；capacity 为物理帧容量"
    sub: ["① 命中页前移 ② 未命中缺页计数 ③ 满时淘汰最久未用"]
    execute: "frames 列表维护 LRU 序（remove+append 前移）"
    not_applicable: ["条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）"]
  calibration: "对照：OS 虚拟内存——LRU 页置换（容量 3 时 8 页访问 5 次缺页）"
---

# 内存-页置换（os-6a1fe224）

## When to use

任务「页置换」；对照：OS 虚拟内存——LRU 页置换（容量 3 时 8 页访问 5 次缺页）。

## 克制条款（不适用条件）

条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）

## How to execute

frames 列表维护 LRU 序（remove+append 前移）

## Verification

- 单元样例 3 条（cases 断言）
- 物理基底：按 calibration 对照（编译/运行/断言裁决）

## References

- 单元库：compiler_code_units.py「内存-页置换」
