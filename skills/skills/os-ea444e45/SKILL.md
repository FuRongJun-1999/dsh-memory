---
name: os-ea444e45
description: >-
  文件描述符 / 文件-文件描述符 / OS 文 / 打开文件表 / 关闭。用户提到这些词时使用本技能。
  场景：对照：OS 文件系统——打开文件表（fd 最小分配，0/1/2 标准流保留）。
  【不适用】Not for 以下场景：条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）
license: MIT
compatibility: >-
  参数 table/path 合法
allowed-tools: Read Write Bash
metadata:
  version: "1.0"
  skill-author: 灵枢（AEIS）
  last-reviewed: "2026-08-29"
  kccs:
    trigger_words: ["文件描述符", "文件-文件描述符", "OS 文", "打开文件表", "关闭"]
    when: "参数 table/path 合法"
    sub: []
    execute: "循环迭代"
    not_applicable: ["条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）"]
  calibration: "对照：OS 文件系统——打开文件表（fd 最小分配，0/1/2 标准流保留）"
---

# 文件-文件描述符（os-ea444e45）

## When to use

任务「文件描述符」；对照：OS 文件系统——打开文件表（fd 最小分配，0/1/2 标准流保留）。

## 克制条款（不适用条件）

条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）

## How to execute

循环迭代

## Verification

- 单元样例 3 条（cases 断言）
- 物理基底：按 calibration 对照（编译/运行/断言裁决）

## References

- 单元库：compiler_code_units.py「文件-文件描述符」
