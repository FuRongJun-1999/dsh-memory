---
name: os-329a2147
description: >-
  初始化流程 / 启动-初始化流程 / OS init——依 / init 进 / 按依赖顺序启动服务。用户提到这些词时使用本技能。
  场景：对照：OS init——依赖排序启动（先依赖后服务）。
  【不适用】Not for 以下场景：条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）
license: MIT
compatibility: >-
  参数 services 合法
allowed-tools: Read Write Bash
metadata:
  version: "1.0"
  skill-author: 灵枢（AEIS）
  last-reviewed: "2026-08-29"
  kccs:
    trigger_words: ["初始化流程", "启动-初始化流程", "OS init——依", "init 进", "按依赖顺序启动服务"]
    when: "参数 services 合法"
    sub: ["① 调用 set；② 调用 sorted；③ 调用 all"]
    execute: "循环迭代；顺序调用"
    not_applicable: ["条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）"]
  calibration: "对照：OS init——依赖排序启动（先依赖后服务）"
---

# 启动-初始化流程（os-329a2147）

## When to use

任务「初始化流程」；对照：OS init——依赖排序启动（先依赖后服务）。

## 克制条款（不适用条件）

条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）

## How to execute

循环迭代；顺序调用

## Verification

- 单元样例 2 条（cases 断言）
- 物理基底：按 calibration 对照（编译/运行/断言裁决）

## References

- 单元库：compiler_code_units.py「启动-初始化流程」
