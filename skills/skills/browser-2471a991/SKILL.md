---
name: browser-2471a991
description: >-
  请求构建 / HTTP-请求构建 / HTTP 请。用户提到这些词时使用本技能。
  场景：对照：浏览器 HTTP 客户端——GET 请求构建（请求行+头）。
  【不适用】Not for 以下场景：条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）
license: MIT
compatibility: >-
  url 为请求路径；host 为主机名；headers 为附加头字典
allowed-tools: Read Write Bash
metadata:
  version: "1.0"
  skill-author: 灵枢（AEIS）
  last-reviewed: "2026-08-29"
  kccs:
    trigger_words: ["请求构建", "HTTP-请求构建", "HTTP 请"]
    when: "url 为请求路径；host 为主机名；headers 为附加头字典"
    sub: ["① 请求行拼接 ② Host 头 ③ 附加头展开"]
    execute: "首行 GET + Host + 逐头拼接"
    not_applicable: ["条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）"]
  calibration: "对照：浏览器 HTTP 客户端——GET 请求构建（请求行+头）"
---

# HTTP-请求构建（browser-2471a991）

## When to use

任务「请求构建」；对照：浏览器 HTTP 客户端——GET 请求构建（请求行+头）。

## 克制条款（不适用条件）

条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）

## How to execute

首行 GET + Host + 逐头拼接

## Verification

- 单元样例 2 条（cases 断言）
- 物理基底：按 calibration 对照（编译/运行/断言裁决）

## References

- 单元库：compiler_code_units.py「HTTP-请求构建」
