---
name: net-4508101f
description: >-
  蜂群中继 / 网络-蜂群中继 / 蜂群网络——消息经邻居递 / seen 防 / 蜂群消息 / 源节点 → 邻居递归中继 / 递归中继 / 未访问则记录并继续转发给。用户提到这些词时使用本技能。
  场景：对照：蜂群网络——消息经邻居递归中继，seen 防回环（去中心化传播）。
  【不适用】Not for 以下场景：条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）
license: MIT
compatibility: >-
  参数 neighbors/source/message 合法
allowed-tools: Read Write Bash
metadata:
  version: "1.0"
  skill-author: 灵枢（AEIS）
  last-reviewed: "2026-08-29"
  kccs:
    trigger_words: ["蜂群中继", "网络-蜂群中继", "蜂群网络——消息经邻居递", "seen 防", "蜂群消息", "源节点 → 邻居递归中继", "递归中继", "未访问则记录并继续转发给"]
    when: "参数 neighbors/source/message 合法"
    sub: ["① 调用 set；② 调用 relay；③ 调用 sorted"]
    execute: "循环迭代；顺序调用"
    not_applicable: ["条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）"]
  calibration: "对照：蜂群网络——消息经邻居递归中继，seen 防回环（去中心化传播）"
---

# 网络-蜂群中继（net-4508101f）

## When to use

任务「蜂群中继」；对照：蜂群网络——消息经邻居递归中继，seen 防回环（去中心化传播）。

## 克制条款（不适用条件）

条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）

## How to execute

循环迭代；顺序调用

## Verification

- 单元样例 3 条（cases 断言）
- 物理基底：按 calibration 对照（编译/运行/断言裁决）

## References

- 单元库：compiler_code_units.py「网络-蜂群中继」
