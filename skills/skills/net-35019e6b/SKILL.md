---
name: net-35019e6b
description: >-
  超时重传 / 蜂群-超时重传 / 可靠传输——未确认包重传 / 超重试上限放弃 / 蜂群可靠传输 / 未确认包超时重传。用户提到这些词时使用本技能。
  场景：对照：可靠传输——未确认包重传，超重试上限放弃（TCP 重传语义）。
  【不适用】Not for 以下场景：条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）
license: MIT
compatibility: >-
  参数 packets/ack_ids/max_tries 合法
allowed-tools: Read Write Bash
metadata:
  version: "1.0"
  skill-author: 灵枢（AEIS）
  last-reviewed: "2026-08-29"
  kccs:
    trigger_words: ["超时重传", "蜂群-超时重传", "可靠传输——未确认包重传", "超重试上限放弃", "蜂群可靠传输", "未确认包超时重传"]
    when: "参数 packets/ack_ids/max_tries 合法"
    sub: ["① 条件判定 ② 结果处理"]
    execute: "循环迭代"
    not_applicable: ["条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）"]
  calibration: "对照：可靠传输——未确认包重传，超重试上限放弃（TCP 重传语义）"
---

# 蜂群-超时重传（net-35019e6b）

## When to use

任务「超时重传」；对照：可靠传输——未确认包重传，超重试上限放弃（TCP 重传语义）。

## 克制条款（不适用条件）

条件不满足即不适用（负路由：输入不满足生效条件时返回 None/不执行）

## How to execute

循环迭代

## Verification

- 单元样例 3 条（cases 断言）
- 物理基底：按 calibration 对照（编译/运行/断言裁决）

## References

- 单元库：compiler_code_units.py「蜂群-超时重传」
