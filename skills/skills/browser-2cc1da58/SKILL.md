---
name: browser-2cc1da58
description: >-
  扩展管理 / 浏览器-扩展管理 / 浏览器扩展——安装 / 启停 / 权限检查 / install 安。用户提到这些词时使用本技能。
  场景：对照：浏览器扩展——安装/启停/权限检查（最小权限原则）。
  【不适用】Not for 以下场景：op 非 {check, enable, install} 时
license: MIT
compatibility: >-
  op ∈ {check, enable, install}
allowed-tools: Read Write Bash
metadata:
  version: "1.0"
  skill-author: 灵枢（AEIS）
  last-reviewed: "2026-08-29"
  kccs:
    trigger_words: ["扩展管理", "浏览器-扩展管理", "浏览器扩展——安装", "启停", "权限检查", "install 安"]
    when: "op ∈ {check, enable, install}"
    sub: ["① op 分支处理"]
    execute: "按 op 分派；顺序调用"
    not_applicable: ["op 非 {check, enable, install} 时"]
  calibration: "对照：浏览器扩展——安装/启停/权限检查（最小权限原则）"
---

# 浏览器-扩展管理（browser-2cc1da58）

## When to use

任务「扩展管理」；对照：浏览器扩展——安装/启停/权限检查（最小权限原则）。

## 克制条款（不适用条件）

op 非 {check, enable, install} 时

## How to execute

按 op 分派；顺序调用

## Verification

- 单元样例 4 条（cases 断言）
- 物理基底：按 calibration 对照（编译/运行/断言裁决）

## References

- 单元库：compiler_code_units.py「浏览器-扩展管理」
