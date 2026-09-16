# -*- coding: utf-8 -*-
"""体检读数规模纪律验证（O(1) 元数据口径，替代全量扫描）。

背景（第 4 条取证）：审计日志无上界增长（实测 ~2 条/s、累计 ~21.5 M 条 / 4.0 GB），
而健康度只需要「量级」这一 O(1) 信息。旧实现 `len(list(read_jsonl(p)))` 把只读体检
绑到 O(n) 全量解析上（4.0 GB → RSS 5 GB+、数十分钟不返回、整条 MCP 通道被一次调用
堵死）；改用流式数行仍要 O(n) 磁盘 IO，随运行时长线性劣化——同属「指标与代价错配」。

断言面：
  ① 缺失文件：零读数不炸（bytes=0 / events=0 / exact=True）
  ② 阈值内：events 精确 == 日志行数（口径与物化读一致，改造不丢读数）
  ③ 超阈值：只读元数据 + 尾部估算，exact=False，且**不触发任何全量计数**（O(n) 守卫）
  ④ 估算忠于量级：与真实行数相对误差 < 20%（可用但不假装精确）
  ⑤ health_os 集成：审计面走 _log_scale，**read_jsonl/count_jsonl 都不得再碰审计路径**
     （防退回物化读/全量扫的核心回归守卫）
  ⑥ 口径连续：小审计文件下 health_os 仍给出精确条数 + exact=True

运行：python -m md_cg.test_health_scale
"""
from __future__ import annotations

import json
import os
import shutil
import tempfile

from . import mdcos as mdcos_mod
from .mdcos import MdCGOS

PASS = FAIL = 0
FAILS = []


def ok(cond, label):
    global PASS, FAIL
    if cond:
        PASS += 1
    else:
        FAIL += 1
        FAILS.append(label)
        print(f"  FAIL {label}")


def _write_log(path, n, pad=100):
    with open(path, "w", encoding="utf-8") as f:
        for i in range(n):
            f.write(json.dumps({"t": float(i), "op": "add", "i": i,
                                "pad": "x" * pad}) + "\n")
    return os.path.getsize(path)


class _Spy:
    """记录 mdcos 模块级 read_jsonl / count_jsonl 的调用路径（探针）。"""

    def __enter__(self):
        self.read, self.count = [], []
        self._read, self._count = mdcos_mod.read_jsonl, mdcos_mod.count_jsonl
        spy = self

        def _r(p, *a, **k):
            spy.read.append(p)
            return spy._read(p, *a, **k)

        def _c(p, *a, **k):
            spy.count.append(p)
            return spy._count(p, *a, **k)

        mdcos_mod.read_jsonl, mdcos_mod.count_jsonl = _r, _c
        return self

    def __exit__(self, *exc):
        mdcos_mod.read_jsonl, mdcos_mod.count_jsonl = self._read, self._count
        return False


def main():
    tmp = tempfile.mkdtemp(prefix="mdcg_scale_")
    try:
        root = os.path.join(tmp, "root")
        os.makedirs(root, exist_ok=True)
        cg = MdCGOS(root)
        audit = cg.audit_log

        # ---------- ① 缺失文件 ----------
        s = cg._log_scale(os.path.join(root, "_nope.jsonl"))
        ok(s["bytes"] == 0 and s["events"] == 0 and s["exact"] is True,
           "①缺失日志 → 零读数不炸（bytes=0/events=0/exact=True）")

        # ---------- ② 阈值内精确 ----------
        n = 200
        size = _write_log(audit, n)
        cg.AUDIT_COUNT_MAX_BYTES = size + 1
        s = cg._log_scale(audit)
        ok(s["exact"] is True and s["events"] == n and s["bytes"] == size,
           "②规模在阈值内 → 精确条数（%d 行，与物化读口径一致）" % n)

        # ---------- ③ 超阈值：O(1)，不触发全量计数 ----------
        cg.AUDIT_COUNT_MAX_BYTES = 1024          # 人工压低阈值，等价于 GB 级日志
        with _Spy() as spy:
            s = cg._log_scale(audit)
        ok(s["exact"] is False and s["bytes"] == size,
           "③超阈值 → exact=False，bytes 仍为 O(1) 精确元数据")
        ok(s["events"] is not None and s["events"] > 0,
           "③b超阈值仍给读数（尾部采样估算），不是拒不回答")
        ok(not spy.count and not spy.read,
           "③c超阈值分支零全量调用（未 count_jsonl / 未 read_jsonl）——O(n) 守卫")

        # ---------- ④ 估算忠于量级 ----------
        rel = abs(s["events"] - n) / float(n)
        ok(rel < 0.20,
           "④估算与真实行数相对误差 %.1f%% < 20%%（量级可用，不假装精确）" % (rel * 100))

        # ---------- ⑤ health_os 集成：审计路径零全量读 ----------
        with _Spy() as spy:
            h = cg.health_os()
        o = h["os"]
        ok(o["audit_events_exact"] is False and o["audit_bytes"] == size
           and o["audit_events"] == s["events"],
           "⑤health_os 透出审计量级（exact=False/bytes 精确/events=估算）")
        ok(not any("_audit.jsonl" in p for p in spy.read),
           "⑤bhealth_os 不再对审计日志做物化读（read_jsonl 未被以审计路径调用）")
        ok(not any("_audit.jsonl" in p for p in spy.count),
           "⑤chealth_os 不再对审计日志做全量计数（count_jsonl 未被以审计路径调用）")

        # ---------- ⑥ 口径连续：小日志仍精确 ----------
        cg.AUDIT_COUNT_MAX_BYTES = 64 << 20
        root2 = os.path.join(tmp, "root2")
        os.makedirs(root2, exist_ok=True)
        cg2 = MdCGOS(root2)
        _write_log(cg2.audit_log, 37)
        o2 = cg2.health_os()["os"]
        ok(o2["audit_events"] == 37 and o2["audit_events_exact"] is True,
           "⑥小日志 → health_os 仍给精确条数（37 行，改造不丢读数）")

        # ---------- ⑦ 真实写入风格：流式行数 == 物化条数（口径等价） ----------
        import random

        from .fsutil import append_jsonl, read_jsonl
        real = os.path.join(root, "_real.jsonl")
        for i in range(50):
            append_jsonl(real, {"i": i, "pad": "y" * random.randint(1, 80)})
        n_real = len(list(read_jsonl(real)))
        s_real = cg._log_scale(real)
        ok(s_real["events"] == n_real == 50 and s_real["exact"] is True,
           "⑦完整写入日志：流式行数 %s == 物化条数 %d（口径逐位相等）"
           % (s_real["events"], n_real))
        os.remove(real)

        # ---------- ⑧ 半截尾行边界：下界口径，最多差 1 行 ----------
        bad = os.path.join(root, "_bad.jsonl")
        with open(bad, "w", encoding="utf-8") as f:
            f.write('{"ok": 1}\nnot-json\n{"ok": 2}')      # 末行未终止 + 非法 JSON
        sb = cg._log_scale(bad)
        n_material = len(list(read_jsonl(bad)))
        ok(sb["events"] == 2 and sb["exact"] is True,
           "⑧半截尾行不计入（换行数 2 vs 物化条数 %d）——下界口径，差 1 行在量级容差内"
           % n_material)
        os.remove(bad)

        cg.close()
        cg2.close()
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    print(f"\nhealth_scale: {PASS} pass / {FAIL} fail")
    if FAILS:
        for f in FAILS:
            print(f" - {f}")
    raise SystemExit(1 if FAIL else 0)


if __name__ == "__main__":
    main()
