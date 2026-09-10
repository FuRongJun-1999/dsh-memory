---
name: os-509a4596
description: >-
  哈希校验 / 可信-哈希校验 / 可信计算——文件哈希校验 / 文件完整性 / 哈希比对。用户提到这些词时使用本技能。
  场景：对照：可信计算——文件哈希校验（完整性验证，篡改检测）。
  【不适用】Not for 以下场景：条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）
license: MIT
compatibility: >-
  参数 file_hash/expected 合法
allowed-tools: Read Write Bash
metadata:
  version: "1.0"
  skill-author: 灵枢（AEIS）
  last-reviewed: "2026-08-29"
  kccs:
    trigger_words: ["哈希校验", "可信-哈希校验", "可信计算——文件哈希校验", "文件完整性", "哈希比对"]
    when: "参数 file_hash/expected 合法"
    sub: ["① 条件判定 ② 结果处理"]
    execute: "文件完整性：哈希比对（不匹配 → 篡改告警）"
    not_applicable: ["条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）"]
  calibration: "对照：可信计算——文件哈希校验（完整性验证，篡改检测）"
---

# 可信-哈希校验（os-509a4596）

## When to use

任务「哈希校验」；对照：可信计算——文件哈希校验（完整性验证，篡改检测）。

## 克制条款（不适用条件）

条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）

## How to execute

文件完整性：哈希比对（不匹配 → 篡改告警）

## Verification

- 单元样例 2 条（cases 断言）
- 物理基底：按 calibration 对照（编译/运行/断言裁决）

## References

- 单元库：compiler_code_units.py「可信-哈希校验」
