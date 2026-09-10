# -*- coding: utf-8 -*-
"""test_navigate_self_bootstrap.py · CSPRE 导航递归测试（实现文档 §4.4 四组）

  ① 复合→原子 2 层导航链（婆媳相处 → 沟通情境 → 倾听共情）
  ② 深度边界：max_depth 耗尽 → structural_blindspot（复用 core.py 模式）
  ③ 原子直答回归：三角形内角和不递归（depth_used=1）
  ④ 可审计：导航链 fingerprint 稳定且非空
"""
import os
import sys

sys.stdout.reconfigure(encoding="utf-8")
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from wisdom_book import ConditionDex
from navigate import navigate_retrieve, chain_fingerprint

DB = os.path.join(HERE, "wisdom-book-cloud.db")
pass_n = fail_n = 0


def check(name, ok, detail=""):
    global pass_n, fail_n
    if ok:
        pass_n += 1
    else:
        fail_n += 1
    print(f'[{"✓" if ok else "✘"}] {name}{" — " + detail if detail else ""}')


dex = ConditionDex(db_path=DB, fresh=False)

# ---- ① 复合→原子 2 层导航 ----
r = navigate_retrieve(dex, "婆媳矛盾怎么处理")
check("①a 复合根命中", r["status"] == "resolved" and r.get("depth_used") == 2,
      f"status={r['status']} depth={r.get('depth_used')}")
chain = r.get("chain", [])
check("①b L0=composite / L1=atomic",
      len(chain) >= 2 and chain[0].get("knowledge_type") == "composite"
      and chain[-1].get("knowledge_type") == "atomic")
check("①c 导航链可读", "→" in (r.get("navigation") or ""))
check("①d 叶子直答", "倾听" in (r.get("direct_answer") or "")
      or "表达" in (r.get("direct_answer") or ""))
check("①e fingerprint 稳定非空",
      bool(r.get("fingerprint")) and len(r["fingerprint"]) == 64)

# ---- ② 深度边界 ----
r2 = navigate_retrieve(dex, "婆媳矛盾怎么处理", max_depth=1)
check("② max_depth=1 → structural_blindspot",
      r2["status"] == "structural_blindspot",
      f"status={r2['status']}")

# ---- ③ 原子直答回归（不递归） ----
r3 = navigate_retrieve(dex, "三角形内角和是多少")
check("③a 原子卡 depth_used=1（不递归）",
      r3["status"] == "resolved" and r3.get("depth_used") == 1,
      f"depth={r3.get('depth_used')}")
check("③b 直答含 180 度", "180" in (r3.get("direct_answer") or ""))

# ---- ④ 指纹确定性（同链同指纹） ----
r4a = navigate_retrieve(dex, "婆媳矛盾怎么处理")
r4b = navigate_retrieve(dex, "婆媳矛盾怎么处理")
check("④ 同导航双跑同指纹",
      r4a.get("fingerprint") == r4b.get("fingerprint") == r.get("fingerprint"))

dex.close()
print(f"\n=== CSPRE 导航递归测试: {pass_n + fail_n} 项中 {pass_n} 通过 ===")
sys.exit(0 if fail_n == 0 else 1)
