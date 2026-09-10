---
name: pylang-ecf27e0c
description: >-
  蜂群服务发现 / 蜂群-服务发现。用户提到这些词时使用本技能。
  场景：对照：蓝牙互联网条件卡 F4 服务发现专项（T11 完整版条件卡_其余六目标 目标 7）——蜂群注册表精确匹配口径。
  【不适用】Not for 以下场景：模糊匹配/发现延迟/负载均衡选择不在本单元范围（精确匹配口径）
license: MIT
compatibility: >-
  nodes 为 (节点名, 能力列表) 序列；capability 为字符串
allowed-tools: Read Write Bash
metadata:
  version: "1.0"
  skill-author: 灵枢（AEIS）
  last-reviewed: "2026-08-29"
  kccs:
    trigger_words: ["蜂群服务发现", "蜂群-服务发现"]
    when: "nodes 为 (节点名, 能力列表) 序列；capability 为字符串"
    sub: ["① 遍历节点注册表；② 能力成员精确判定；③ 命中节点收集"]
    execute: "循环迭代；条件分派"
    not_applicable: ["模糊匹配/发现延迟/负载均衡选择不在本单元范围（精确匹配口径）"]
  calibration: "对照：蓝牙互联网条件卡 F4 服务发现专项（T11 完整版条件卡_其余六目标 目标 7）——蜂群注册表精确匹配口径"
---

# 蜂群-服务发现（pylang-ecf27e0c）

## When to use

任务「蜂群服务发现」；对照：蓝牙互联网条件卡 F4 服务发现专项（T11 完整版条件卡_其余六目标 目标 7）——蜂群注册表精确匹配口径。

## 克制条款（不适用条件）

模糊匹配/发现延迟/负载均衡选择不在本单元范围（精确匹配口径）

## How to execute

循环迭代；条件分派

## Verification

- 单元样例 4 条（cases 断言）
- 物理基底：按 calibration 对照（编译/运行/断言裁决）

## References

- 单元库：compiler_code_units.py「蜂群-服务发现」
