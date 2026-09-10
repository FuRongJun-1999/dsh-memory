# -*- coding: utf-8 -*-
"""统一时间核（钉死批条款 3：核形状唯一）

    X_i(t) = X_i,∞ + (X_i,0 - X_i,∞)·e^(-γ_i·t)

全库一切时间演化必须经本模块。核形状唯一（指数族），状态 X 与
衰减率 γ 按对象配置；任何在本模块之外出现的衰减核实现
（exp(-t/τ)、×(1-factor)、EMA 保持率）都是 bug——
由 tools/time_core_lint.py 按 E5 口径机械化审计。
规范依据：docs/概念钉死批_GPT四点评审_v0.1.md 钉死 3。
"""
import math


def cred(x0: float, x_inf: float, gamma: float, dt: float) -> float:
    """连续指数核：状态从 x0 向终值 x_inf 衰减，速率 γ，历时 dt。"""
    return x_inf + (x0 - x_inf) * math.exp(-gamma * dt)


def cred_factor(gamma: float, dt: float, floor: float = 0.0, ceil: float = 1.0) -> float:
    """归一化保持因子 e^(-γ·dt)，clamp 到 [floor, ceil]。

    适用于 x0=1、x_inf=0 的新近度加权形态（如知识飞轮 recency factor）。
    """
    f = math.exp(-gamma * dt)
    return max(floor, min(ceil, f))


def cred_step(x: float, factor: float) -> float:
    """离散指数核单步：x ← x·(1-factor)。

    decay_cycle 逐周期形态；n 步后 x·(1-factor)^n = x·e^(n·ln(1-factor))，
    与连续核同族——衰减率 γ = -ln(1-factor) 每周期。
    """
    return x * (1.0 - factor)


def cred_blend(last: float, incoming: float, retain: float) -> float:
    """指数平滑：last ← last·retain + incoming。

    gap/信息差等累积观测的离散指数核形态（保持率 retain = 1-λ）。
    """
    return last * retain + incoming
