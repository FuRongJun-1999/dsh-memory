# -*- coding: utf-8 -*-
"""test_preflight_failclosed.py —— preflight 门面 fail-closed 专项测试（补测④，矩阵 v0.2 #29）。

背景（§2A-3）：AEIS 门面在自我认知组件未装配时返回 ok:True（fail-open），
「检查未执行」被冒充为「检查通过」，违反白箱「未验证不放行」纪律。

改动：门面（真身 AEIS/aeis/api.py + 镜像 whitebox_kb/aeis_core/api.py 同步）
未装配时返回 ok:False + status=fail_closed + reason + 装配错误透传。

本测试用库内镜像（aeis_core 不含 self_cognition 模块 → 引擎装配必然失败
置 None）确定性触发未装配分支；委托路径用 stub 验证；双副本源码一致性
静态断言防漂移。
"""
import os
import sys

if hasattr(sys.stdout, "buffer"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from md_cg.whitebox_kb.aeis_core.api import Agent  # noqa: E402

PASS, FAIL = 0, 0


def check(name, ok, detail=""):
    global PASS, FAIL
    if ok:
        PASS += 1
        print(f"  [PASS] {name}" + (f"  · {detail}" if detail else ""))
    else:
        FAIL += 1
        print(f"  [FAIL] {name}" + (f"  · {detail}" if detail else ""))


# ------------------------------------------------------------------
# [1] 未装配分支：fail-closed（镜像引擎装配必然失败，确定性触发）
# ------------------------------------------------------------------
print("\n[1] 未装配分支 fail-closed（镜像 aeis_core 无 self_cognition 模块）\n")
a = Agent(identity="pf-fc-test", db_path=":memory:")
sc_err = getattr(a.engine, "_self_cognition_error", "")
print(f"  镜像引擎装配状态: _self_cognition={a.engine._self_cognition} "
      f"error={sc_err[:60]!r}")
a.engine._self_cognition = None  # 防御：测试进程若曾 import aeis 会污染别名注册，显式归零

r = a.preflight("任意待发布内容")
check("未装配 → ok is False（拦截）", r.get("ok") is False)
check("status=fail_closed", r.get("status") == "fail_closed")
check("reason=self_cognition_not_ready", r.get("reason") == "self_cognition_not_ready")
check("note 声明未验证不放行", "未验证不放行" in str(r.get("note", "")))
check("装配错误透传（可见可修）", "error" in r and r["error"] == str(sc_err or ""))

# ------------------------------------------------------------------
# [2] 组件在位 → 零干扰委托（门面不改变 sc 结果）
# ------------------------------------------------------------------
print("\n[2] 组件在位委托路径（stub 验证门面零干扰）\n")


class _StubSC:
    @staticmethod
    def preflight(text):
        return {"ok": False, "conflicts": ["破坏"], "issues": ["stub 拦截"]}


a.engine._self_cognition = _StubSC
r2 = a.preflight("含破坏词的内容")
check("委托：sc 结果原样返回", r2.get("ok") is False and r2.get("conflicts") == ["破坏"])
check("委托：门面未注入 fail_closed 字段", "status" not in r2)
a.engine._self_cognition = None

# ------------------------------------------------------------------
# [3] 双副本源码一致性（真身 ↔ 镜像，防漂移）
# ------------------------------------------------------------------
print("\n[3] 双副本源码一致性静态断言\n")
HERE = os.path.dirname(os.path.abspath(__file__))
mirror = open(os.path.join(HERE, "whitebox_kb", "aeis_core", "api.py"),
              encoding="utf-8").read()
i0 = mirror.find("def preflight")
seg_m = mirror[i0:mirror.find("def ", i0 + 10)]
check("镜像门面含 fail_closed", "fail_closed" in seg_m)
check("镜像 fail-open 签名已移除",
      '"ok": True, "note": "自我认知组件未装配"' not in seg_m)

aeis_api = os.path.normpath(os.path.join(HERE, "..", "..", "AEIS", "aeis", "api.py"))
if os.path.exists(aeis_api):
    real = open(aeis_api, encoding="utf-8").read()
    j0 = real.find("def preflight")
    seg_r = real[j0:real.find("def ", j0 + 10)]
    check("真身门面含 fail_closed", "fail_closed" in seg_r)
    check("真身 fail-open 签名已移除",
          '"ok": True, "note": "自我认知组件未装配"' not in seg_r)
    # 门面段逐行一致性（双副本纪律：真身与镜像同源同改）
    check("真身与镜像 preflight 段逐行一致", seg_r == seg_m)
else:
    print("  [SKIP] AEIS 仓不在同级路径，真身一致性由 AEIS 侧测试覆盖")

# ------------------------------------------------------------------
print("\n" + "=" * 60)
print(f"preflight fail-closed 专项测试：{PASS} 通过 / {FAIL} 失败")
sys.exit(0 if FAIL == 0 else 1)
