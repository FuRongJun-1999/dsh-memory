---
name: os-c980a25d
description: >-
  inode查询 / 文件-inode / OS 文 / inode 表。用户提到这些词时使用本技能。
  场景：对照：OS 文件系统 inode——文件名→元数据（大小/权限）查询。
  【不适用】Not for 以下场景：条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）
license: MIT
compatibility: >-
  参数 files/name 合法
allowed-tools: Read Write Bash
metadata:
  version: "1.0"
  skill-author: 灵枢（AEIS）
  last-reviewed: "2026-08-29"
  kccs:
    trigger_words: ["inode查询", "文件-inode", "OS 文", "inode 表"]
    when: "参数 files/name 合法"
    sub: ["① 条件判定 ② 结果处理"]
    execute: "循环迭代"
    not_applicable: ["条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）"]
  calibration: "对照：OS 文件系统 inode——文件名→元数据（大小/权限）查询"
---

# 文件-inode（os-c980a25d）

## When to use

任务「inode查询」；对照：OS 文件系统 inode——文件名→元数据（大小/权限）查询。

## 克制条款（不适用条件）

条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）

## How to execute

循环迭代

## Verification

- 单元样例 2 条（cases 断言）
- 物理基底：按 calibration 对照（编译/运行/断言裁决）

## References

- 单元库：compiler_code_units.py「文件-inode」
