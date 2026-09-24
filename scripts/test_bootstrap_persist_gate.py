# -*- coding: utf-8 -*-
"""test_bootstrap_persist_gate —— 通道 A 固化闸守卫（V22）

背景：run_once 曾以 persist_triggers(patches) 传**全量**补丁而非只含
verify_patch 通过者的 persisted（scripts/bootstrap_loop.py:419）——
验证失败的补丁也被写进 WISDOM 下 6 个 *_units.py 源文件，绕过自身
「补丁→验证→固化」闸（模块 docstring 声明的流程）。本守卫以
monkeypatch 台架固化「固化入参只含验证通过者」。

运行：python -X utf8 scripts/test_bootstrap_persist_gate.py
"""
import importlib.util
import os
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)

passed = failed = 0


def check(name, cond, detail=""):
    global passed, failed
    if cond:
        passed += 1
        print("  [PASS] " + name)
    else:
        failed += 1
        print("  [FAIL] " + name + "  " + str(detail)[:200])


def main():
    spec = importlib.util.spec_from_file_location(
        "bl_v22_persist", os.path.join(HERE, "scripts", "bootstrap_loop.py"))
    m = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(m)
    except SystemExit:
        pass

    captured = {}

    def fake_patch(g):
        return {"unit": "gap-unit-" + str(g), "domain": "graph",
                "add_triggers": ["触发词" + str(g)]}

    # 台架（与原缺陷报告复现同款）：2 gap、apply 恒过、verify 仅 unit 含
    # 'ok' 通过、persist 只捕获入参（不真改 wisdom 源文件）、日志不落盘。
    m.scan_route_gaps = lambda: ["x", "ok"]
    m.build_trigger_patch = fake_patch
    m.apply_patch = lambda p: True
    m.verify_patch = lambda p: "ok" in p["unit"]

    def fake_persist(patches):
        captured["units"] = [p["unit"] for p in patches]
        return len(patches)

    m.persist_triggers = fake_persist
    m.log_event = lambda rec: None

    res = m.run_once(channel_b=False)

    print("[1] 通道 A 台架口径（2 gap：1 验证过 / 1 验证败）")
    check("gaps=2 且补丁计数 verified=1 / failed=1",
          res.get("gaps") == 2 and res.get("patches_verified") == 1
          and res.get("patches_failed") == 1, repr(res))
    check("persist_triggers 被调用（persisted 非空）",
          "units" in captured, repr(res.get("persisted_files")))

    print("[2] V22 主诉：固化闸——只固化验证通过者")
    check("固化入参只含验证通过者 ['gap-unit-ok']（旧代码收到全量 "
          "['gap-unit-x','gap-unit-ok']——验证失败者也进固化）",
          captured.get("units") == ["gap-unit-ok"],
          repr(captured.get("units")))
    check("persisted_files == 固化条数（1，非全量 2）",
          res.get("persisted_files") == 1, repr(res.get("persisted_files")))

    print(f"\nbootstrap 固化闸守卫: {passed} 通过 / {failed} 失败")
    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(main())
