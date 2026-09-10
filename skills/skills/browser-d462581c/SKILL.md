---
name: browser-d462581c
description: >-
  下载管理 / 浏览器-下载管理 / 浏览器下载——进度 / 暂停 / 恢复 / start 开。用户提到这些词时使用本技能。
  场景：对照：浏览器下载——进度/暂停/恢复（断点续传）。
  【不适用】Not for 以下场景：op 非 {pause, progress, resume, start} 时
license: MIT
compatibility: >-
  op ∈ {pause, progress, resume, start}
allowed-tools: Read Write Bash
metadata:
  version: "1.0"
  skill-author: 灵枢（AEIS）
  last-reviewed: "2026-08-29"
  kccs:
    trigger_words: ["下载管理", "浏览器-下载管理", "浏览器下载——进度", "暂停", "恢复", "start 开"]
    when: "op ∈ {pause, progress, resume, start}"
    sub: ["① op 分支处理"]
    execute: "按 op 分派"
    not_applicable: ["op 非 {pause, progress, resume, start} 时"]
  calibration: "对照：浏览器下载——进度/暂停/恢复（断点续传）"
---

# 浏览器-下载管理（browser-d462581c）

## When to use

任务「下载管理」；对照：浏览器下载——进度/暂停/恢复（断点续传）。

## 克制条款（不适用条件）

op 非 {pause, progress, resume, start} 时

## How to execute

按 op 分派

## Verification

- 单元样例 5 条（cases 断言）
- 物理基底：按 calibration 对照（编译/运行/断言裁决）

## References

- 单元库：compiler_code_units.py「浏览器-下载管理」
