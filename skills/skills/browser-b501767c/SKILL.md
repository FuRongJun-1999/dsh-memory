---
name: browser-b501767c
description: >-
  混合内容 / 安全-混合内容 / HTTPS 页。用户提到这些词时使用本技能。
  场景：对照：混合内容——HTTPS 页面加载 HTTP 子资源拦截（安全降级防护）。
  【不适用】Not for 以下场景：条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）
license: MIT
compatibility: >-
  page_scheme/res_scheme ∈ {https, http}
allowed-tools: Read Write Bash
metadata:
  version: "1.0"
  skill-author: 灵枢（AEIS）
  last-reviewed: "2026-08-29"
  kccs:
    trigger_words: ["混合内容", "安全-混合内容", "HTTPS 页"]
    when: "page_scheme/res_scheme ∈ {https, http}"
    sub: ["① HTTPS 页面检测 ② HTTP 子资源判定 ③ 拦截/放行"]
    execute: "页面 https 且资源 http → blocked，否则 allowed"
    not_applicable: ["条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）"]
  calibration: "对照：混合内容——HTTPS 页面加载 HTTP 子资源拦截（安全降级防护）"
---

# 安全-混合内容（browser-b501767c）

## When to use

任务「混合内容」；对照：混合内容——HTTPS 页面加载 HTTP 子资源拦截（安全降级防护）。

## 克制条款（不适用条件）

条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）

## How to execute

页面 https 且资源 http → blocked，否则 allowed

## Verification

- 单元样例 4 条（cases 断言）
- 物理基底：按 calibration 对照（编译/运行/断言裁决）

## References

- 单元库：compiler_code_units.py「安全-混合内容」
