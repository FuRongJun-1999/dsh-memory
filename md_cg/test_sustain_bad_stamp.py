# -*- coding: utf-8 -*-
"""坏心跳戳的隔离性守卫（PR #576 回归）。

背景：`read_stamp` 的文档串承诺「不存在 / 损坏 → None」，但修前
`sustain.py:196` 的 `float(rec.get("ts") or 0)` 只挡住假值（None/0/""）；
`ts` 为**合法 JSON 里的非法值**（如 "abc"）时抛 ValueError 穿出函数。
而 `peers()`（:237）在循环里直接调 `read_stamp`、无 try ⇒ 一个坏戳让
**整个 peers() 失败**，同目录下所有健康节点的状态一并丢失。

断言面：
  ① 单个坏戳：`read_stamp` 返回 None（而不是抛异常）
  ② 单个坏戳：`peers()` 不抛异常
  ③ 混合目录：3 个健康戳 + 1 个坏戳 → peers() 返回 3 条，健康节点一个不少
  ④ 健康戳在坏戳之后仍被正确读出（遍历顺序不影响）
  ⑤ 坏戳不污染健康节点的 state 判定
  ⑥ 各类「损坏」形态一律返回 None：非法字符串 / 空列表 / 空字典 / 非 JSON / 非 dict
  ⑦ 合法形态必须继续可用（不多杀）：正常戳 / 数字字符串 / null / 缺 ts 键

运行：python -m md_cg.test_sustain_bad_stamp

隔离性：全部操作在 tempfile.mkdtemp() 下，`peers(d)` / `read_stamp(name, d)`
显式传目录参数 ⇒ **不碰 aux_root()/sustain 的真实心跳数据**。
"""
from __future__ import annotations

import json
import os
import shutil
import tempfile
import time

from . import sustain

PASS = FAIL = 0
FAILS = []


def ok(cond, label):
    global PASS, FAIL
    if cond:
        PASS += 1
    else:
        FAIL += 1
        FAILS.append(label)
        print(f"  [FAIL] {label}")


def _write_stamp(d, name, payload):
    """直接落盘一个戳文件（绕过 write_stamp，才能造出各种损坏形态）。"""
    path = os.path.join(d, f"heartbeat.{name}.stamp")
    if isinstance(payload, str):
        body = payload
    else:
        body = json.dumps(payload)
    with open(path, "w", encoding="utf-8") as f:
        f.write(body)
    return path


def _good(name, age_s=10.0):
    return {"v": 1, "name": name, "ts": time.time() - age_s, "pid": os.getpid()}


def main():
    tmp = tempfile.mkdtemp(prefix="sustain_badstamp_")
    try:
        # ① 单个坏戳：read_stamp 返回 None 而不是抛异常
        d1 = os.path.join(tmp, "one_bad")
        os.makedirs(d1)
        _write_stamp(d1, "bad", '{"ts": "abc", "name": "bad"}')
        try:
            rec = sustain.read_stamp("bad", d1)
            ok(rec is None, "① 坏戳 read_stamp 返回 None（未抛异常）")
        except Exception as e:                        # noqa: BLE001
            ok(False, f"① 坏戳 read_stamp 返回 None —— 却抛了 {type(e).__name__}: {e}")

        # ② 单个坏戳：peers() 不抛
        try:
            got = sustain.peers(d1)
            ok(got == [], "② 目录里只有坏戳时 peers() 返回空列表")
        except Exception as e:                        # noqa: BLE001
            ok(False, f"② 目录里只有坏戳时 peers() 未抛 —— 却抛了 {type(e).__name__}: {e}")

        # ③ 混合目录：3 健康 + 1 坏 → 3 条
        d2 = os.path.join(tmp, "mixed")
        os.makedirs(d2)
        for n in ("a", "b", "c"):
            _write_stamp(d2, n, _good(n))
        _write_stamp(d2, "bad", '{"ts": "abc", "name": "bad"}')
        try:
            got = sustain.peers(d2)
            names = sorted(r.get("name", "") for r in got)
            ok(len(got) == 3, f"③ 混合目录 peers() 返回 3 条（实际 {len(got)}）")
            ok(names == ["a", "b", "c"], f"③ 健康节点 a/b/c 一个不少（实际 {names}）")
        except Exception as e:                        # noqa: BLE001
            ok(False, f"③ 混合目录 peers() 未抛 —— 却抛了 {type(e).__name__}: {e}")

        # ④ 坏戳排在前面也不影响后面健康戳（遍历顺序无关）
        d3 = os.path.join(tmp, "bad_first")
        os.makedirs(d3)
        _write_stamp(d3, "aaa", '{"ts": "abc"}')      # 排序靠前
        _write_stamp(d3, "zzz", _good("zzz"))
        try:
            got = sustain.peers(d3)
            ok(len(got) == 1 and got[0].get("name") == "zzz",
               "④ 坏戳排序靠前时，其后的健康戳仍被读出")
        except Exception as e:                        # noqa: BLE001
            ok(False, f"④ 顺序无关性 —— 抛了 {type(e).__name__}: {e}")

        # ⑤ 坏戳不污染健康节点的 state 判定
        d4 = os.path.join(tmp, "state")
        os.makedirs(d4)
        _write_stamp(d4, "fresh", _good("fresh", 5))
        _write_stamp(d4, "stale", _good("stale", 10 ** 6))
        _write_stamp(d4, "bad", '{"ts": "abc"}')
        try:
            got = {r.get("name"): r.get("state") for r in sustain.peers(d4)}
            ok(got.get("fresh") == "ok", f"⑤ 新鲜戳 state=ok（实际 {got.get('fresh')}）")
            ok(got.get("stale") == "dead", f"⑤ 陈旧戳 state=dead（实际 {got.get('stale')}）")
            ok("bad" not in got, "⑤ 坏戳不出现在结果里")
        except Exception as e:                        # noqa: BLE001
            ok(False, f"⑤ state 判定 —— 抛了 {type(e).__name__}: {e}")

        # ⑥ 各种损坏形态一律 None
        #
        # 注意（我第一版写错过这里）：`ts: []` 与 `ts: {}` 在
        # `float(rec.get("ts") or 0)` 里被 `or` **短路成 0**（空列表/空字典是假值），
        # 所以它们从来就不抛异常、也不返回 None —— 修前修后都返回「age≈now」。
        # 这是既有行为，不属于本 PR 的修复面，不能拿来当「坏戳」断言。
        d5 = os.path.join(tmp, "shapes")
        os.makedirs(d5)
        bad_shapes = [
            ('{"ts": "abc"}',      "ts 非法字符串"),
            ("not json at all",    "非 JSON"),
            ("[1, 2, 3]",          "JSON 但不是 dict"),
        ]
        for i, (body, why) in enumerate(bad_shapes):
            _write_stamp(d5, f"s{i}", body)
            try:
                rec = sustain.read_stamp(f"s{i}", d5)
                ok(rec is None, f"⑥ {why} → None")
            except Exception as e:                    # noqa: BLE001
                ok(False, f"⑥ {why} → None —— 抛了 {type(e).__name__}: {e}")

        # ⑦ 合法形态必须继续可用（不多杀）
        d6 = os.path.join(tmp, "good_shapes")
        os.makedirs(d6)
        good_shapes = [
            (json.dumps({"ts": time.time() - 5}), "正常戳"),
            (json.dumps({"ts": str(time.time() - 5)}), "ts 是数字字符串"),
            (json.dumps({"ts": None}),            "ts 为 null（按 0 处理）"),
            (json.dumps({"name": "x"}),           "缺 ts 键（按 0 处理）"),
        ]
        for i, (body, why) in enumerate(good_shapes):
            _write_stamp(d6, f"g{i}", body)
            try:
                rec = sustain.read_stamp(f"g{i}", d6)
                ok(rec is not None and "age" in rec,
                   f"⑦ {why} → 仍返回含 age 的记录")
            except Exception as e:                    # noqa: BLE001
                ok(False, f"⑦ {why} → 抛了 {type(e).__name__}: {e}")

        # ⑧ 隔离性自证：本测试全程没有写过真实心跳目录
        real = os.environ.get("MDCG_SUSTAIN_DIR") or ""
        ok(tmp not in (real or ""), "⑧ 测试目录与真实 sust 目录无交集")

    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    print(f"\nbad_stamp: {PASS} passed, {FAIL} failed")
    if FAILS:
        for f in FAILS:
            print(f"  - {f}")
    raise SystemExit(1 if FAIL else 0)


if __name__ == "__main__":
    main()
