---
name: os-b776ade1
description: >-
  文件路径 / 文件-路径解析 / OS 文 / 路径解析 / 绝对/相对/.. /./。用户提到这些词时使用本技能。
  场景：对照：OS 文件系统——路径规范化（绝对/相对/.. 解析）。
  【不适用】Not for 以下场景：p 非 {..} 时
license: MIT
compatibility: >-
  path 为路径字符串；cwd 为当前工作目录
allowed-tools: Read Write Bash
metadata:
  version: "1.0"
  skill-author: 灵枢（AEIS）
  last-reviewed: "2026-08-29"
  kccs:
    trigger_words: ["文件路径", "文件-路径解析", "OS 文", "路径解析", "绝对/相对/.. /./"]
    when: "path 为路径字符串；cwd 为当前工作目录"
    sub: ["① 绝对/相对判定 ② 分量规整 ③ .. 上溯"]
    execute: "split 分量 + 栈式规整"
    not_applicable: ["p 非 {..} 时"]
  calibration: "对照：OS 文件系统——路径规范化（绝对/相对/.. 解析）"
---

# 文件-路径解析（os-b776ade1）

## When to use

任务「文件路径」；对照：OS 文件系统——路径规范化（绝对/相对/.. 解析）。

## 克制条款（不适用条件）

p 非 {..} 时

## How to execute

split 分量 + 栈式规整

## Verification

- 单元样例 4 条（cases 断言）
- 物理基底：按 calibration 对照（编译/运行/断言裁决）

## References

- 单元库：compiler_code_units.py「文件-路径解析」
