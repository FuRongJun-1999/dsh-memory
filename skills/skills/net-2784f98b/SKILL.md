---
name: net-2784f98b
description: >-
  帧解析 / 网络-帧解析 / RFC 6455——We / WebSocket 帧 / FIN/opcode/长。用户提到这些词时使用本技能。
  场景：对照：RFC 6455——WebSocket 帧解码（FIN/opcode/长度/载荷，与帧封装 ws_frame 互逆）。
  【不适用】Not for 以下场景：frame 非法（长度不足 2 字节）时越界抛错；掩码帧未处理
license: MIT
compatibility: >-
  frame 为 RFC 6455 帧字节（首字节 FIN+opcode，次字节长度）
allowed-tools: Read Write Bash
metadata:
  version: "1.0"
  skill-author: 灵枢（AEIS）
  last-reviewed: "2026-08-29"
  kccs:
    trigger_words: ["帧解析", "网络-帧解析", "RFC 6455——We", "WebSocket 帧", "FIN/opcode/长"]
    when: "frame 为 RFC 6455 帧字节（首字节 FIN+opcode，次字节长度）"
    sub: ["① 解析 FIN/opcode ② 解析长度（含 126/127 扩展）③ 截取载荷解码"]
    execute: "位运算取首字节 + 定长/扩展长度读法 + utf-8 解码"
    not_applicable: ["frame 非法（长度不足 2 字节）时越界抛错；掩码帧未处理"]
  calibration: "对照：RFC 6455——WebSocket 帧解码（FIN/opcode/长度/载荷，与帧封装 ws_frame 互逆）"
---

# 网络-帧解析（net-2784f98b）

## When to use

任务「帧解析」；对照：RFC 6455——WebSocket 帧解码（FIN/opcode/长度/载荷，与帧封装 ws_frame 互逆）。

## 克制条款（不适用条件）

frame 非法（长度不足 2 字节）时越界抛错；掩码帧未处理

## How to execute

位运算取首字节 + 定长/扩展长度读法 + utf-8 解码

## Verification

- 单元样例 4 条（cases 断言）
- 物理基底：按 calibration 对照（编译/运行/断言裁决）

## References

- 单元库：compiler_code_units.py「网络-帧解析」
