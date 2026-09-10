---
name: browser-afa4091f
description: >-
  URL解析 / URL-解析 / URL 解 / 协议/主机/端口/路径。用户提到这些词时使用本技能。
  场景：对照：浏览器 URL——协议/主机/端口/路径解析。
  【不适用】Not for 以下场景：条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）
license: MIT
compatibility: >-
  url 为合法 URL 字符串（scheme://host[:port][/path]）
allowed-tools: Read Write Bash
metadata:
  version: "1.0"
  skill-author: 灵枢（AEIS）
  last-reviewed: "2026-08-29"
  kccs:
    trigger_words: ["URL解析", "URL-解析", "URL 解", "协议/主机/端口/路径"]
    when: "url 为合法 URL 字符串（scheme://host[:port][/path]）"
    sub: ["① 协议提取 ② 主机提取 ③ 端口/路径提取"]
    execute: "正则 `\\w+://...` 分组捕获"
    not_applicable: ["条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）"]
  calibration: "对照：浏览器 URL——协议/主机/端口/路径解析"
---

# URL-解析（browser-afa4091f）

## When to use

任务「URL解析」；对照：浏览器 URL——协议/主机/端口/路径解析。

## 克制条款（不适用条件）

条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）

## How to execute

正则 `\w+://...` 分组捕获

## Verification

- 单元样例 2 条（cases 断言）
- 物理基底：按 calibration 对照（编译/运行/断言裁决）

## References

- 单元库：compiler_code_units.py「URL-解析」
