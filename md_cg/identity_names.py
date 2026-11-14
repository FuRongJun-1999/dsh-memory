# -*- coding: utf-8 -*-
"""身份中文名对照表（单一真源）——机器侧仍用小写段值，展示侧一律中文。

使用者裁定（2026-11-14，选「甲」）：会话身份五元组的段值保持机器可读形态
（s5.<harness>.<unit>.<workspace>.<start_epoch>.<msg_digest12>，跨端可复算），
但界面上全部显示中文。故对照表只做展示层翻译，不参与形态、不写入节点。

判据纪律：
  · 未知段值 → 原样显示并标注「未知身份」，不猜中文；
  · 新增身份值必须先在本表登记，否则展示为原文（守卫会点名缺登记）。
"""
from __future__ import annotations

UNIT_NAMES = {
    "agent": "执行者",
    "designer": "设计者",
    "maintainer": "维护者",
    "auditor": "审计者",
    "verifier": "验证者",
    "recorder": "记录者",
    "reflector": "反思者",
    "output": "输出者",
    "sustain": "维生者",
    "roleplay": "角色扮演",
    "user": "使用者",
}

HARNESS_NAMES = {
    "dsh": "DSH 端",
    "zcode": "zcode 端",
    "codebuddy": "CodeBuddy 端",
    "codex": "Codex 端",
}


# 生效条件：value 为段值（任意大小写）；返回中文展示名，未登记则原样返回（不猜）
def human_unit(value) -> str:
    v = str(value or "").strip().lower()
    return UNIT_NAMES.get(v, v) if v else "未登记身份"


# 生效条件：value 为运行宿主段值；返回中文展示名，未登记则原样返回
def human_harness(value) -> str:
    v = str(value or "").strip().lower()
    return HARNESS_NAMES.get(v, v) if v else "未登记端"


# 生效条件：会话标识形如 s5.<harness>.<unit>.<workspace>.<epoch>.<digest>；解析失败返回空 dict（不猜）
def parse_identity(session) -> dict:
    s = str(session or "")
    if not s.startswith("s5."):
        return {}
    parts = s.split(".")
    if len(parts) < 6:
        return {}
    return {
        "harness": parts[1],
        "unit": parts[2],
        "workspace": parts[3],
        "start_epoch": parts[4],
        "msg_digest12": parts[5],
        "unit_cn": human_unit(parts[2]),
        "harness_cn": human_harness(parts[1]),
    }
