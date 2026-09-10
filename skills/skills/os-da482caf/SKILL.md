---
name: os-da482caf
description: >-
  文件链接 / 文件-链接管理 / OS 文 / 软链接路径引用 / hard 硬。用户提到这些词时使用本技能。
  场景：对照：OS 文件系统——硬链接共享 inode/软链接路径引用（解析语义）。
  【不适用】Not for 以下场景：op 非 {hard, resolve, soft} 时
license: MIT
compatibility: >-
  op ∈ {hard, resolve, soft}
allowed-tools: Read Write Bash
metadata:
  version: "1.0"
  skill-author: 灵枢（AEIS）
  last-reviewed: "2026-08-29"
  kccs:
    trigger_words: ["文件链接", "文件-链接管理", "OS 文", "软链接路径引用", "hard 硬"]
    when: "op ∈ {hard, resolve, soft}"
    sub: ["① op 分支处理"]
    execute: "按 op 分派"
    not_applicable: ["op 非 {hard, resolve, soft} 时"]
  calibration: "对照：OS 文件系统——硬链接共享 inode/软链接路径引用（解析语义）"
---

# 文件-链接管理（os-da482caf）

## When to use

任务「文件链接」；对照：OS 文件系统——硬链接共享 inode/软链接路径引用（解析语义）。

## 克制条款（不适用条件）

op 非 {hard, resolve, soft} 时

## How to execute

按 op 分派

## Verification

- 单元样例 5 条（cases 断言）
- 物理基底：按 calibration 对照（编译/运行/断言裁决）

## References

- 单元库：compiler_code_units.py「文件-链接管理」
