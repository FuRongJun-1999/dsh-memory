# -*- coding: utf-8 -*-
"""守卫 · 台账 sigs 的窗口外回收（issue #1001）。

现象：_writelimit.json 的 sigs 只增不减，代码里没有任何删除路径；而
_window_stamp 对 CONVERGE_WINDOW 之外的戳恒返 None ⇒ 那些条目**永远不可能被命中**，
对判定零贡献，却让每一次记忆写入都要多解析一份随条数线性增长的 JSON
（issue 实测：3604 条 = 89.49 ms/次，剔除窗口外后 3.32 ms）。

本守卫钉住七件事：
  G1 窗口外旧戳：落盘时被回收（判定面等价，不删活条目）
  G2 窗口内记录：原样保留
  G3 **未来戳：保留**（时钟回拨/并发写的痕，等 now 追上仍可能命中——回收与判据不是一回事）
  G4 垃圾记账（非 dict / 非数值戳 / NaN）：回收（它们永远进不了比对分支）
  G5 阈值之下（SIGS_GC_MIN）不扫：小台账不该为回收付出每次写入的成本
  G6 判定面等价：清理前后 check() 对同一内容给出同一结论
  G7 stats 如实外露 sigs_dead（回收阈值之下靠它看账该不该瘦身）

运行：python -m md_cg.test_writelimit_prune
"""
from __future__ import annotations

import json
import os
import shutil
import tempfile
import time

# 夹具隔离：本守卫不考档位面（档位守卫 = test_autonomy_modes.py）
from . import autonomy_modes as _autonomy_modes          # noqa: E402
os.environ[_autonomy_modes.AUTONOMY_ENV_KEYS["mode"]] = "full"

from .mdcos import MdCGOS                                # noqa: E402
from . import writelimit as W                            # noqa: E402

_d = tempfile.mkdtemp(prefix="mdcg_wlprune_")
cg = MdCGOS(_d)


def check(name, cond, detail=""):
    assert cond, "[FAIL] %s %s" % (name, detail)
    print("[ok] %s" % name)


def _path():
    return os.path.join(cg.root, W.STATE_FILE)


def _put(sigs, rate=None):
    """直接造台账（绕过限流器，专测回收面）。"""
    with open(_path(), "w", encoding="utf-8") as f:
        json.dump({"sigs": sigs, "rate": rate or {}}, f, ensure_ascii=False)
    return sigs


def _get():
    with open(_path(), encoding="utf-8") as f:
        return json.load(f)


NOW = time.time()
CONTENT = "批次511收官记忆"          # 短骨架 → 有签名（同 test_writelimit A1 口径）
SIG = W.template_signature(CONTENT)
assert SIG, "夹具前提：该正文必须能产出签名"


def _dead(n, prefix="dead"):
    return {"%s_%06d" % (prefix, i): {"nid": "n%d" % i, "n": 1,
                                      "t": NOW - W.CONVERGE_WINDOW - 3600}
            for i in range(n)}


# ---------------------------------------------------------------- G5 阈值之下不动
_put(_dead(10))
before = len(_get()["sigs"])
W.check(cg, CONTENT, role="user")
check("G5 阈值之下不回收（小台账不为回收付成本）",
      before <= len(_get()["sigs"]) <= before + 1, len(_get()["sigs"]))

# ---------------------------------------------------------------- G1 窗口外回收
sigs = _dead(600)
sigs["live_in_window"] = {"nid": "n_live", "n": 1, "t": NOW - 60}
sigs["live_future"] = {"nid": "n_future", "n": 1, "t": NOW + 3600}
sigs["bad_scalar"] = "not-a-dict"
sigs["bad_ts"] = {"nid": "n_bad", "t": "昨天", "n": 1}
sigs["bad_nan"] = {"nid": "n_nan", "t": float("nan"), "n": 1}
_put(sigs)
check("G1a 造好 605 条（600 死在窗口外 + 5 条活/垃圾）", len(_get()["sigs"]) == 605, len(_get()["sigs"]))
size_before = os.path.getsize(_path())

W.check(cg, CONTENT, role="user")
after = _get()["sigs"]
check("G1b 落盘时窗口外旧戳被回收", not any(k.startswith("dead_") for k in after),
      [k for k in after if k.startswith("dead_")][:3])
check("G1c 垃圾记账一并回收（非 dict / 非数值 / NaN）",
      not any(k in after for k in ("bad_scalar", "bad_ts", "bad_nan")), list(after))
check("G2 窗口内记录原样保留",
      "live_in_window" in after and after["live_in_window"]["nid"] == "n_live")
check("G3 未来戳保留（回收 != 判据）",
      "live_future" in after and after["live_future"]["nid"] == "n_future")
check("G1d 文件显著变小", os.path.getsize(_path()) < size_before * 0.2,
      (size_before, os.path.getsize(_path())))
check("G1e 存活条目只剩 2~3 条", len(after) <= 3, list(after))

# ---------------------------------------------------------------- G6 判定面等价
base = _dead(600)
base[SIG] = {"nid": "n_old", "n": 7, "t": NOW - W.CONVERGE_WINDOW - 10}
_put(base)
verdict = W.check(cg, CONTENT, role="user")
after2 = _get()["sigs"]
check("G6 窗口外同签名不聚合、不因回收改变结论", verdict is None, verdict)
check("G6b 回收后仍无死条目", not any(k.startswith("dead_") for k in after2), list(after2)[:4])

# ---------------------------------------------------------------- G4b inf 戳
# json.load 会把 1e400 / Infinity 读成 inf；now - inf = -inf 恒 < window ⇒ 既不回收也不命中。
inf_sigs = {"inf_pad_%06d" % i: {"nid": "n%d" % i, "n": 1, "t": NOW - 60} for i in range(300)}
inf_sigs["inf_pos"] = {"nid": "n_inf", "n": 1, "t": float("inf")}
inf_sigs["inf_neg"] = {"nid": "n_ninf", "n": 1, "t": float("-inf")}
_put(inf_sigs)
W.check(cg, CONTENT, role="user")
after_inf = _get()["sigs"]
check("G4b ±inf 戳被回收（否则是永不可回收的死重）",
      "inf_pos" not in after_inf and "inf_neg" not in after_inf, list(after_inf)[:3])

# ---------------------------------------------------------------- G9 阈值边界
def _mixed(dead_n, live_n):
    d = {"thr_dead_%06d" % i: {"nid": "d%d" % i, "n": 1,
                                "t": NOW - W.CONVERGE_WINDOW - 60} for i in range(dead_n)}
    d.update({"thr_live_%06d" % i: {"nid": "l%d" % i, "n": 1, "t": NOW - 60}
              for i in range(live_n)})
    return d

# 直接调 _prune_sigs 量边界（走 check() 会顺手写入一条新签名，把 256 顶成 257，测不到边界本身）
st_a = {"sigs": _mixed(1, W.SIGS_GC_MIN - 1)}       # 恰好 = 阈值：不扫
n_a = W._prune_sigs(st_a, now=NOW)
check("G9a 恰好 = 阈值：不回收（不付扫描成本）",
      n_a == 0 and "thr_dead_000000" in st_a["sigs"], (n_a, len(st_a["sigs"])))
st_b = {"sigs": _mixed(1, W.SIGS_GC_MIN)}           # 阈值 +1：扫
n_b = W._prune_sigs(st_b, now=NOW)
check("G9b 阈值 +1：触发回收",
      n_b == 1 and "thr_dead_000000" not in st_b["sigs"], (n_b, len(st_b["sigs"])))

# ---------------------------------------------------------------- G8 时间轴一致
# 回收必须用调用方在锁内算好的 now，而不是墙钟：回放/测试显式传历史 now 时，
# 相对「回放时刻」仍活的记账不能因为「相对今天已过窗」被删掉。
HIST = NOW - 30 * 86400.0
hist_sigs = {"hist_dead_%06d" % i: {"nid": "n%d" % i, "n": 1,
                                   "t": HIST - W.CONVERGE_WINDOW - 60}
             for i in range(600)}
hist_sigs["alive_at_hist"] = {"nid": "n_hist_alive", "n": 1, "t": HIST - 60}
_put(hist_sigs)
W.check(cg, CONTENT, role="user", now=HIST)
after3 = _get()["sigs"]
check("G8 历史 now 回放：相对该时刻仍活的记账不被墙钟误删",
      "alive_at_hist" in after3, list(after3)[:3])
check("G8b 历史 now 回放：相对该时刻已死的仍被回收",
      not any(k.startswith("hist_dead_") for k in after3),
      [k for k in after3 if k.startswith("hist_dead_")][:2])

# ---------------------------------------------------------------- G7 stats 外露
_put(_dead(600))
st = W.stats(cg)
check("G7a stats 外露 sigs_dead", st.get("sigs_dead") == 600, st)
check("G7b stats 外露回收阈值", st.get("sigs_gc_threshold") == W.SIGS_GC_MIN, st)

# ---------------------------------------------------------------- 清理
shutil.rmtree(_d, ignore_errors=True)
print()
print("台账 sigs 回收守卫：全部通过")
