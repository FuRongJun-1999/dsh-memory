---
name: net-8f6169e9
description: >-
  HTTP状态码 / 网络-HTTP状态码 / HTTP 状 / 2xx 成。用户提到这些词时使用本技能。
  场景：对照：HTTP 状态码分类（RFC 9110：2xx/3xx/4xx/5xx）。
  【不适用】Not for 以下场景：条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）
license: MIT
compatibility: >-
  参数 code 合法
allowed-tools: Read Write Bash
metadata:
  version: "1.0"
  skill-author: 灵枢（AEIS）
  last-reviewed: "2026-08-29"
  kccs:
    trigger_words: ["HTTP状态码", "网络-HTTP状态码", "HTTP 状", "2xx 成"]
    when: "参数 code 合法"
    sub: ["① 条件判定 ② 结果处理"]
    execute: "HTTP 状态码分类：2xx 成功/3xx 重定向/4xx 客户端错/5xx 服务端错"
    not_applicable: ["条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）"]
  calibration: "对照：HTTP 状态码分类（RFC 9110：2xx/3xx/4xx/5xx）"
---

# 网络-HTTP状态码（net-8f6169e9）

## When to use

任务「HTTP状态码」；对照：HTTP 状态码分类（RFC 9110：2xx/3xx/4xx/5xx）。

## 克制条款（不适用条件）

条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）

## How to execute

HTTP 状态码分类：2xx 成功/3xx 重定向/4xx 客户端错/5xx 服务端错

## Verification

- 单元样例 4 条（cases 断言）
- 物理基底：按 calibration 对照（编译/运行/断言裁决）

## References

- 单元库：compiler_code_units.py「网络-HTTP状态码」
