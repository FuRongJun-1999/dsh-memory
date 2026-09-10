---
name: os-55672763
description: >-
  目录树 / 文件-目录树 / OS 文 / 目录树 + 列目录 / 根/子目录/文件 → 路。用户提到这些词时使用本技能。
  场景：对照：OS 文件系统——目录树（mkdir 层级 + ls 路径展开）。
  【不适用】Not for 以下场景：条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）
license: MIT
compatibility: >-
  prefix.rstrip 可用
allowed-tools: Read Write Bash
metadata:
  version: "1.0"
  skill-author: 灵枢（AEIS）
  last-reviewed: "2026-08-29"
  kccs:
    trigger_words: ["目录树", "文件-目录树", "OS 文", "目录树 + 列目录", "根/子目录/文件 → 路"]
    when: "prefix.rstrip 可用"
    sub: ["① 调用 sorted"]
    execute: "循环迭代；顺序调用"
    not_applicable: ["条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）"]
  calibration: "对照：OS 文件系统——目录树（mkdir 层级 + ls 路径展开）"
---

# 文件-目录树（os-55672763）

## When to use

任务「目录树」；对照：OS 文件系统——目录树（mkdir 层级 + ls 路径展开）。

## 克制条款（不适用条件）

条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）

## How to execute

循环迭代；顺序调用

## Verification

- 单元样例 2 条（cases 断言）
- 物理基底：按 calibration 对照（编译/运行/断言裁决）

## References

- 单元库：compiler_code_units.py「文件-目录树」
