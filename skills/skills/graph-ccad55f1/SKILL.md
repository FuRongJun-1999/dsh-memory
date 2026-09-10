---
name: graph-ccad55f1
description: >-
  加密存储 / 图安全-加密存储 / 图安全——加密存储 / 图加密 / 节点值异或密钥 / 图解密 / 密钥异或还原节点值。用户提到这些词时使用本技能。
  场景：对照：图安全——加密存储（异或加密/解密，静态数据保护）。
  【不适用】Not for 以下场景：条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）
license: MIT
compatibility: >-
  参数 value/key 合法
allowed-tools: Read Write Bash
metadata:
  version: "1.0"
  skill-author: 灵枢（AEIS）
  last-reviewed: "2026-08-29"
  kccs:
    trigger_words: ["加密存储", "图安全-加密存储", "图安全——加密存储", "图加密", "节点值异或密钥", "图解密", "密钥异或还原节点值"]
    when: "参数 value/key 合法"
    sub: ["① 调用 chr；② 调用 ord"]
    execute: "顺序调用"
    not_applicable: ["条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）"]
  calibration: "对照：图安全——加密存储（异或加密/解密，静态数据保护）"
---

# 图安全-加密存储（graph-ccad55f1）

## When to use

任务「加密存储」；对照：图安全——加密存储（异或加密/解密，静态数据保护）。

## 克制条款（不适用条件）

条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）

## How to execute

顺序调用

## Verification

- 单元样例 2 条（cases 断言）
- 物理基底：按 calibration 对照（编译/运行/断言裁决）

## References

- 单元库：compiler_code_units.py「图安全-加密存储」
