---
name: pylang-486a1e94
description: >-
  二分查找 / 工具-二分查找 / bisect——有 / 有序序列定位目标。用户提到这些词时使用本技能。
  场景：对照：bisect——有序序列折半查找（命中索引/-1）。
  【不适用】Not for 以下场景：条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）
license: MIT
compatibility: >-
  参数 seq/target 合法
allowed-tools: Read Write Bash
metadata:
  version: "1.0"
  skill-author: 灵枢（AEIS）
  last-reviewed: "2026-08-29"
  kccs:
    trigger_words: ["二分查找", "工具-二分查找", "bisect——有", "有序序列定位目标"]
    when: "参数 seq/target 合法"
    sub: ["① 调用 len"]
    execute: "循环迭代；顺序调用"
    not_applicable: ["条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）"]
  calibration: "对照：bisect——有序序列折半查找（命中索引/-1）"
---

# 工具-二分查找（pylang-486a1e94）

## When to use

任务「二分查找」；对照：bisect——有序序列折半查找（命中索引/-1）。

## 克制条款（不适用条件）

条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）

## How to execute

循环迭代；顺序调用

## Verification

- 单元样例 4 条（cases 断言）
- 物理基底：按 calibration 对照（编译/运行/断言裁决）

## References

- 单元库：compiler_code_units.py「工具-二分查找」
