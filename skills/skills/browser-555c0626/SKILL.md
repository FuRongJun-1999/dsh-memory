---
name: browser-555c0626
description: >-
  同源策略 / 安全-同源策略 / 浏览器安全——同源策略 / 协议+域名+端口 全同才。用户提到这些词时使用本技能。
  场景：对照：浏览器安全——同源策略（协议+域名+端口，同源才允许跨域读写）。
  【不适用】Not for 以下场景：条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）
license: MIT
compatibility: >-
  参数 a/b 合法
allowed-tools: Read Write Bash
metadata:
  version: "1.0"
  skill-author: 灵枢（AEIS）
  last-reviewed: "2026-08-29"
  kccs:
    trigger_words: ["同源策略", "安全-同源策略", "浏览器安全——同源策略", "协议+域名+端口 全同才"]
    when: "参数 a/b 合法"
    sub: ["① 调用 parts"]
    execute: "顺序调用"
    not_applicable: ["条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）"]
  calibration: "对照：浏览器安全——同源策略（协议+域名+端口，同源才允许跨域读写）"
---

# 安全-同源策略（browser-555c0626）

## When to use

任务「同源策略」；对照：浏览器安全——同源策略（协议+域名+端口，同源才允许跨域读写）。

## 克制条款（不适用条件）

条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）

## How to execute

顺序调用

## Verification

- 单元样例 3 条（cases 断言）
- 物理基底：按 calibration 对照（编译/运行/断言裁决）

## References

- 单元库：compiler_code_units.py「安全-同源策略」
