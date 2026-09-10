---
name: browser-2895ff52
description: >-
  文件系统访问 / 浏览器-文件系统访问 / open 打。用户提到这些词时使用本技能。
  场景：对照：File System Access——本地文件打开/写/读。
  【不适用】Not for 以下场景：op 非 {open, read, write} 时
license: MIT
compatibility: >-
  op ∈ {open, read, write}
allowed-tools: Read Write Bash
metadata:
  version: "1.0"
  skill-author: 灵枢（AEIS）
  last-reviewed: "2026-08-29"
  kccs:
    trigger_words: ["文件系统访问", "浏览器-文件系统访问", "open 打"]
    when: "op ∈ {open, read, write}"
    sub: ["① op 分支处理"]
    execute: "按 op 分派"
    not_applicable: ["op 非 {open, read, write} 时"]
  calibration: "对照：File System Access——本地文件打开/写/读"
---

# 浏览器-文件系统访问（browser-2895ff52）

## When to use

任务「文件系统访问」；对照：File System Access——本地文件打开/写/读。

## 克制条款（不适用条件）

op 非 {open, read, write} 时

## How to execute

按 op 分派

## Verification

- 单元样例 4 条（cases 断言）
- 物理基底：按 calibration 对照（编译/运行/断言裁决）

## References

- 单元库：compiler_code_units.py「浏览器-文件系统访问」
