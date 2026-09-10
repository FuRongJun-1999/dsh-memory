---
name: os-cfa66a1b
description: >-
  块管理 / 文件-块管理 / OS 文 / 块位图分配。用户提到这些词时使用本技能。
  场景：对照：OS 文件系统——块位图分配（连续块首次适配）。
  【不适用】Not for 以下场景：条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）
license: MIT
compatibility: >-
  参数 bitmap/size 合法
allowed-tools: Read Write Bash
metadata:
  version: "1.0"
  skill-author: 灵枢（AEIS）
  last-reviewed: "2026-08-29"
  kccs:
    trigger_words: ["块管理", "文件-块管理", "OS 文", "块位图分配"]
    when: "参数 bitmap/size 合法"
    sub: ["① 调用 len；② 调用 range；③ 调用 all"]
    execute: "循环迭代；顺序调用"
    not_applicable: ["条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）"]
  calibration: "对照：OS 文件系统——块位图分配（连续块首次适配）"
---

# 文件-块管理（os-cfa66a1b）

## When to use

任务「块管理」；对照：OS 文件系统——块位图分配（连续块首次适配）。

## 克制条款（不适用条件）

条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）

## How to execute

循环迭代；顺序调用

## Verification

- 单元样例 3 条（cases 断言）
- 物理基底：按 calibration 对照（编译/运行/断言裁决）

## References

- 单元库：compiler_code_units.py「文件-块管理」
