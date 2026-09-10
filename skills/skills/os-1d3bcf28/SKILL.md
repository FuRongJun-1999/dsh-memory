---
name: os-1d3bcf28
description: >-
  文件系统挂载 / 文件-系统挂载 / OS VFS——文 / VFS 挂 / 挂载点→文件系统。用户提到这些词时使用本技能。
  场景：对照：OS VFS——文件系统挂载（mount 注册/unmount 卸载/未挂载 None）。
  【不适用】Not for 以下场景：条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）
license: MIT
compatibility: >-
  参数 mounts/path/fs_type 合法
allowed-tools: Read Write Bash
metadata:
  version: "1.0"
  skill-author: 灵枢（AEIS）
  last-reviewed: "2026-08-29"
  kccs:
    trigger_words: ["文件系统挂载", "文件-系统挂载", "OS VFS——文", "VFS 挂", "挂载点→文件系统"]
    when: "参数 mounts/path/fs_type 合法"
    sub: ["① 条件判定 ② 结果处理"]
    execute: "VFS 挂载：挂载点→文件系统（mount 注册/unmount 卸载/查询）"
    not_applicable: ["条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）"]
  calibration: "对照：OS VFS——文件系统挂载（mount 注册/unmount 卸载/未挂载 None）"
---

# 文件-系统挂载（os-1d3bcf28）

## When to use

任务「文件系统挂载」；对照：OS VFS——文件系统挂载（mount 注册/unmount 卸载/未挂载 None）。

## 克制条款（不适用条件）

条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）

## How to execute

VFS 挂载：挂载点→文件系统（mount 注册/unmount 卸载/查询）

## Verification

- 单元样例 3 条（cases 断言）
- 物理基底：按 calibration 对照（编译/运行/断言裁决）

## References

- 单元库：compiler_code_units.py「文件-系统挂载」
