---
name: graph-d43b387a
description: >-
  布隆过滤 / 图索引-布隆过滤 / 图索引——布隆过滤器 / 布隆过滤器 / 多哈希位数组（成员可能判 / 哈希一 / 字符码和取模 / 哈希二。用户提到这些词时使用本技能。
  场景：对照：图索引——布隆过滤器（多哈希位数组，快速成员判定，可误报）。
  【不适用】Not for 以下场景：条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）
license: MIT
compatibility: >-
  参数 items/probe 合法
allowed-tools: Read Write Bash
metadata:
  version: "1.0"
  skill-author: 灵枢（AEIS）
  last-reviewed: "2026-08-29"
  kccs:
    trigger_words: ["布隆过滤", "图索引-布隆过滤", "图索引——布隆过滤器", "布隆过滤器", "多哈希位数组（成员可能判", "哈希一", "字符码和取模", "哈希二"]
    when: "参数 items/probe 合法"
    sub: ["① 调用 sum；② 调用 h1；③ 调用 h2"]
    execute: "循环迭代；顺序调用"
    not_applicable: ["条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）"]
  calibration: "对照：图索引——布隆过滤器（多哈希位数组，快速成员判定，可误报）"
---

# 图索引-布隆过滤（graph-d43b387a）

## When to use

任务「布隆过滤」；对照：图索引——布隆过滤器（多哈希位数组，快速成员判定，可误报）。

## 克制条款（不适用条件）

条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）

## How to execute

循环迭代；顺序调用

## Verification

- 单元样例 3 条（cases 断言）
- 物理基底：按 calibration 对照（编译/运行/断言裁决）

## References

- 单元库：compiler_code_units.py「图索引-布隆过滤」
