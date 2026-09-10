---
name: os-ecfceae7
description: >-
  文件元数据 / 文件-元数据查询 / OS stat——文 / stat 查。用户提到这些词时使用本技能。
  场景：对照：OS stat——文件元数据（大小/权限/类型）。
  【不适用】Not for 以下场景：条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）
license: MIT
compatibility: >-
  参数 fs/name 合法
allowed-tools: Read Write Bash
metadata:
  version: "1.0"
  skill-author: 灵枢（AEIS）
  last-reviewed: "2026-08-29"
  kccs:
    trigger_words: ["文件元数据", "文件-元数据查询", "OS stat——文", "stat 查"]
    when: "参数 fs/name 合法"
    sub: ["① 条件判定 ② 结果处理"]
    execute: "文件元数据：stat 查询（大小/权限/类型——文件信息）"
    not_applicable: ["条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）"]
  calibration: "对照：OS stat——文件元数据（大小/权限/类型）"
---

# 文件-元数据查询（os-ecfceae7）

## When to use

任务「文件元数据」；对照：OS stat——文件元数据（大小/权限/类型）。

## 克制条款（不适用条件）

条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）

## How to execute

文件元数据：stat 查询（大小/权限/类型——文件信息）

## Verification

- 单元样例 3 条（cases 断言）
- 物理基底：按 calibration 对照（编译/运行/断言裁决）

## References

- 单元库：compiler_code_units.py「文件-元数据查询」
