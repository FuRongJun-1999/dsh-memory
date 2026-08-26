# -*- coding: utf-8 -*-
"""诊断 compose_engine 对编程概念问题的响应"""
import sys, os
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, r"C:\Users\FuRongJun\AppData\Local\Programs\Python\Python310\lib\site-packages")

from wisdom import compose_engine as ce

for q in ["TypeScript 是什么", "什么是 TypeScript", "TypeScript 和 JavaScript 什么区别"]:
    print(f"\n=== {q} ===")
    try:
        r = ce.route_compose(q)
        print("ok:", r.get("ok"))
        print("scene:", r.get("scene"))
        print("direction:", r.get("direction"))
        print("answer 前 300:", (r.get("answer") or "")[:300])
        print("units:", [u for u, _ in (r.get("units") or [])])
        print("checks:", r.get("checks"))
    except Exception as e:
        print("异常:", e)
