# -*- coding: utf-8 -*-
"""test_bootstrap_channel_b —— 通道 B cases 未过分支守卫（V22）

背景：run_channel_b 的 verifier 失败分支（cases 物理验证未过）曾把
_rej_list 初始化为空串 ""（scripts/bootstrap_loop.py:370，对照沙箱拒绝
分支 :319 的正确 []）——首次失败（rejected_log.json 不存在时）即
AttributeError 崩溃：整轮通道 B 中止、队列状态不落盘（:380-385 回写
未执行）→ 条目永远 pending，每轮重试再崩，通道 B 死循环。
V21-4 冒烟的失败样本走的是沙箱拒绝分支（[] 正确），从未踩到此分支。

运行：python -X utf8 scripts/test_bootstrap_channel_b.py
"""
import importlib.util
import json
import os
import shutil
import sys
import tempfile

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
        "bl_v22_guard", os.path.join(HERE, "scripts", "bootstrap_loop.py"))
    m = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(m)
    except SystemExit:
        pass

    smoke = tempfile.mkdtemp(prefix="v22_channel_b_")
    m.STATE = smoke                          # 隔离状态目录
    try:
        # 场景（缺陷复现形态）：函数本身合法（过 AST 沙箱），但 cases
        # 期望不符 → 走 :365 else「cases 物理验证未过」分支（非沙箱拒绝
        # 分支）——旧代码 _rej_list="" 在此 AttributeError。
        code = ("def guard_add(a, b):\n"
                "    return a + b\n")
        q = {"pending": [{"task": "守卫加法", "code": code,
                          "cases": [[[3, 4], 100]],   # fn(3,4)=7 ≠ 100
                          "status": "new"}]}
        with open(os.path.join(smoke, "channel_b_queue.json"), "w",
                  encoding="utf-8") as f:
            json.dump(q, f, ensure_ascii=False)

        print("[1] cases 未过首跑不崩（rejected_log.json 不存在时）")
        crashed = None
        try:
            res = m.run_channel_b(None, max_tasks=5)
        except Exception as e:                # 旧代码：AttributeError
            crashed = e
            res = None
        check("run_channel_b 不抛异常（旧代码 AttributeError 崩溃）",
              crashed is None, repr(crashed))
        if res is None:
            return finish()
        check("stats：generated=1 passed=0 failed=1（source=queue）",
              res.get("generated") == 1 and res.get("passed") == 0
              and res.get("failed") == 1 and res.get("source") == "queue",
              repr(res))

        print("[2] 崩溃下游三件：拒绝留痕 / 队列回写 / 死循环消除")
        rej_p = os.path.join(smoke, "channel_b_drafts", "rejected_log.json")
        rej = (json.load(open(rej_p, encoding="utf-8"))
               if os.path.exists(rej_p) else None)
        check("rejected_log.json 首跑即产生（旧代码此路径永不产生）",
              isinstance(rej, list), rej_p)
        check("拒绝留痕含该 task 且 layer=queue_verifier",
              isinstance(rej, list) and any(
                  r.get("task") == "守卫加法"
                  and r.get("layer") == "queue_verifier" for r in rej),
              repr(rej)[:120])
        q2 = json.load(open(os.path.join(smoke, "channel_b_queue.json"),
                            encoding="utf-8"))
        st = {t["task"]: t.get("status") for t in q2.get("pending", [])}
        check("队列回写 status=failed（旧代码崩溃时回写未执行→永久 "
              "pending 死循环）",
              st.get("守卫加法") == "failed", repr(st))

        # ---- 首条 continue 饥饿守卫：缺 cases/code 不标 status ----
        # 病灶：run_channel_b 首条 `if not code or not cases: continue`
        # 不给 item 标 status——坏条目（channel_b_queue.json 是模型可控
        # 输入）永久 pending 且占据 queue[:max_tasks] 处理窗口：max_tasks
        # 个坏条目即令合法条目永不被处理（stats 恒 0 无报错，静默饥饿）。
        # 同型修复先例就在同函数 fname 缺失分支（标 failed 防永久占位）。
        print("[3] 首条 continue 饥饿守卫（缺 cases/code 必须标 failed）")
        smoke3 = tempfile.mkdtemp(prefix="v23_channel_b_starve_")
        m.STATE = smoke3
        try:
            good_code = ("def good_add(a, b):\n"
                         "    return a + b\n")
            q3 = {"pending": [
                {"task": "坏1", "code": "", "cases": [[[1, 1], 2]]},
                {"task": "坏2", "code": good_code},
                {"task": "坏3", "cases": [[[1, 1], 2]]},
                {"task": "好1", "code": good_code, "cases": [[[3, 4], 7]],
                 "status": "new"},
            ]}
            with open(os.path.join(smoke3, "channel_b_queue.json"), "w",
                      encoding="utf-8") as f:
                json.dump(q3, f, ensure_ascii=False)

            r1 = m.run_channel_b(None, max_tasks=3)   # 3 坏条目占满窗口
            check("轮1 坏条目计入 stats failed=3（旧代码恒 0 静默）",
                  r1.get("failed") == 3 and r1.get("generated") == 0,
                  repr(r1))
            q3w = json.load(open(os.path.join(smoke3,
                                              "channel_b_queue.json"),
                                 encoding="utf-8"))
            st3 = {t["task"]: t.get("status") for t in q3w.get("pending", [])}
            check("轮1 队列回写坏条目 status=failed（旧代码无 status 键"
                  "→永久 pending 占位）",
                  all(st3.get(f"坏{i}") == "failed" for i in (1, 2, 3)),
                  repr(st3))

            r2 = m.run_channel_b(None, max_tasks=3)   # 窗口应已让给好条目
            check("轮2 好条目进入处理窗口（饥饿消除：generated=1 passed=1；"
                  "旧代码仍 {0,0,0} 好条目永不被处理）",
                  r2.get("generated") == 1 and r2.get("passed") == 1,
                  repr(r2))
            q3f = json.load(open(os.path.join(smoke3,
                                              "channel_b_queue.json"),
                                 encoding="utf-8"))
            stf = {t["task"]: t.get("status")
                   for t in q3f.get("pending", [])}
            check("轮2 好条目 status=verified 且固化入 verified_units",
                  stf.get("好1") == "verified" and "task:好1" in json.load(
                      open(os.path.join(smoke3,
                                        "channel_b_verified_units.json"),
                           encoding="utf-8")),
                  repr(stf))
        finally:
            shutil.rmtree(smoke3, ignore_errors=True)
    finally:
        shutil.rmtree(smoke, ignore_errors=True)
    return finish()


def finish():
    print(f"\nbootstrap 通道 B 守卫: {passed} 通过 / {failed} 失败")
    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(main())
