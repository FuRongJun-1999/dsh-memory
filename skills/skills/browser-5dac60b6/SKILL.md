---
name: browser-5dac60b6
description: >-
  CORS检查 / 安全-CORS检查 / CORS / 同源放行 / 简单请求放。用户提到这些词时使用本技能。
  场景：对照：浏览器安全——CORS 跨域资源共享（同源/简单/预检三态）。
  【不适用】Not for 以下场景：条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）
license: MIT
compatibility: >-
  参数 origin/target/method 合法
allowed-tools: Read Write Bash
metadata:
  version: "1.0"
  skill-author: 灵枢（AEIS）
  last-reviewed: "2026-08-29"
  kccs:
    trigger_words: ["CORS检查", "安全-CORS检查", "CORS", "同源放行 / 简单请求放"]
    when: "参数 origin/target/method 合法"
    sub: ["① 条件判定 ② 结果处理"]
    execute: "CORS：同源放行 / 简单请求放行 / 预检判定（跨域资源共享）"
    not_applicable: ["条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）"]
  calibration: "对照：浏览器安全——CORS 跨域资源共享（同源/简单/预检三态）"
---

# 安全-CORS检查（browser-5dac60b6）

## When to use

任务「CORS检查」；对照：浏览器安全——CORS 跨域资源共享（同源/简单/预检三态）。

## 克制条款（不适用条件）

条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）

## How to execute

CORS：同源放行 / 简单请求放行 / 预检判定（跨域资源共享）

## Verification

- 单元样例 4 条（cases 断言）
- 物理基底：按 calibration 对照（编译/运行/断言裁决）

## References

- 单元库：compiler_code_units.py「安全-CORS检查」
