---
name: net-61580202
description: >-
  会话状态 / 蜂群-会话状态 / 会话层——连接状态机 / 蜂群会话状态机。用户提到这些词时使用本技能。
  场景：对照：会话层——连接状态机（同步→确认→建立→关闭；非法事件不迁移）。
  【不适用】Not for 以下场景：条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）
license: MIT
compatibility: >-
  参数 session/event 合法
allowed-tools: Read Write Bash
metadata:
  version: "1.0"
  skill-author: 灵枢（AEIS）
  last-reviewed: "2026-08-29"
  kccs:
    trigger_words: ["会话状态", "蜂群-会话状态", "会话层——连接状态机", "蜂群会话状态机"]
    when: "参数 session/event 合法"
    sub: ["① 条件判定 ② 结果处理"]
    execute: "蜂群会话状态机：LISTEN→SYN_SENT→ESTABLISHED（确认）→CLOSED（结束）"
    not_applicable: ["条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）"]
  calibration: "对照：会话层——连接状态机（同步→确认→建立→关闭；非法事件不迁移）"
---

# 蜂群-会话状态（net-61580202）

## When to use

任务「会话状态」；对照：会话层——连接状态机（同步→确认→建立→关闭；非法事件不迁移）。

## 克制条款（不适用条件）

条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）

## How to execute

蜂群会话状态机：LISTEN→SYN_SENT→ESTABLISHED（确认）→CLOSED（结束）

## Verification

- 单元样例 4 条（cases 断言）
- 物理基底：按 calibration 对照（编译/运行/断言裁决）

## References

- 单元库：compiler_code_units.py「蜂群-会话状态」
