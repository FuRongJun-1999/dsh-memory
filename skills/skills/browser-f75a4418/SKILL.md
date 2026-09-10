---
name: browser-f75a4418
description: >-
  资源完整性 / 浏览器-资源完整性 / SRI 子 / 子资源完整性 / 哈希比对。用户提到这些词时使用本技能。
  场景：对照：SRI 子资源完整性——脚本哈希校验（防篡改）。
  【不适用】Not for 以下场景：条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）
license: MIT
compatibility: >-
  参数 resource_hash/expected 合法
allowed-tools: Read Write Bash
metadata:
  version: "1.0"
  skill-author: 灵枢（AEIS）
  last-reviewed: "2026-08-29"
  kccs:
    trigger_words: ["资源完整性", "浏览器-资源完整性", "SRI 子", "子资源完整性", "哈希比对"]
    when: "参数 resource_hash/expected 合法"
    sub: ["① 条件判定 ② 结果处理"]
    execute: "子资源完整性：哈希比对（SRI——防篡改第三方脚本）"
    not_applicable: ["条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）"]
  calibration: "对照：SRI 子资源完整性——脚本哈希校验（防篡改）"
---

# 浏览器-资源完整性（browser-f75a4418）

## When to use

任务「资源完整性」；对照：SRI 子资源完整性——脚本哈希校验（防篡改）。

## 克制条款（不适用条件）

条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）

## How to execute

子资源完整性：哈希比对（SRI——防篡改第三方脚本）

## Verification

- 单元样例 3 条（cases 断言）
- 物理基底：按 calibration 对照（编译/运行/断言裁决）

## References

- 单元库：compiler_code_units.py「浏览器-资源完整性」
