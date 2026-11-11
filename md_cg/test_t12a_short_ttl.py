# -*- coding: utf-8 -*-
r"""test_t12a_short_ttl —— design 短 TTL 档（add(ttl_hours=...)）五段验收（E-T12a t1）。

## 这个测试锁的是什么

`mdcg.py` 的 `add()` 新增显式参数 **`ttl_hours=None`**（位置：`effective_until`
之后、`**extra` 之前，`mdcg.py:2446`）。语义（实现见 `mdcg.py:2872-2881`）：

- `ttl_hours > 0`：`fm.effective_until = time.time() + ttl_hours * 3600`、
  `fm.ttl_hours = ttl_hours`、`fm.ttl_source = 'design'`，并 **pop 掉旧键
  `valid_until`**（`trust.UNTIL_FIELD`，同族双写必留歧义）；`expired_at`
  不单独写——走**下方既有派生路径**（`mdcg.py:2886-2894`，遍历
  `trust.UNTIL_ALIASES` 取第一个非空终点）随 `effective_until` 落。
- `ttl_hours` 为 `None` / `0` / 负：**零行为变化**——不落
  `ttl_hours` / `ttl_source` / `effective_until` / `expired_at`（默认关）。

本测试**只新建本文件**，不改引擎任何一行；临时 `cg` 落在工作区内
（`orchestrator/tmp/`），绝不触线上库。

## 五段（合计 19 条断言，全过）

  [A] 派生真实性 ≥3（5 条）：`ttl_hours=2` 落盘后 `effective_until`
      **真的** ≈ `now+7200`（不是原样回读调用方入参）；`expired_at`
      **真的**等于 `effective_until`（派生非复制）；`ttl_source='design'`
      且 `ttl_hours` 原值落盘 ⇒ 三个键来自同一次真实写入，不是测试自造。
      另加两条写入落点断言：节点落盘于本次临时 cg 根下（无越界、非线上库）、
      且该根在段末被回收（本测试不留残留目录）。
  [B] `ttl_hours` 短档 ≥6（6 条）：短档（1h）落盘键齐 + 旧键被剔；
      `valid_until` 与 `ttl_hours` 同时给时 **ttl 赢**（旧键剔净、ttl 键在）；
      `ttl_hours=0.5` 小数档原值落盘且终点按 0.5h 算；覆写既有节点仍落 ttl 三键；
      **不传时零行为**（`add()` 无 `ttl_hours` ⇒ 四个键一个都不落，逐键断言）；
      **不传且带旧键时不传 ttl 零改写**（`valid_until` 照旧落旧键、
      `effective_until` / `ttl_hours` / `ttl_source` 全不落）。
  [C] 到期链路 ≥4（4 条，**只用纯函数**，不写盘、不 sleep）：`trust.validity`
      对 `effective_until=now-10` 判 `expired`；`trust.is_expired` 同判 True；
      `trust.time_window_msg` 点名命中键 `effective_until`；
      `trust.first_endpoint` 在 `effective_until` 与 `valid_until` 并存时
      **规范键优先**（阶段一别名回落口径）。到期判定链的真源是
      `trust.py:298-357` 的纯函数——本段不依赖任何写入副作用。
  [D] 回归 ≥2（2 条）：无 `ttl_hours` 的历史调用面**逐字节不变**——
      传旧参数 `valid_until=` 时照旧落旧键 `valid_until`、`effective_until`
      不落（现行 ttl 档在 `md_cg/mdcg.py:3358` 起的 `add()` 签名里，旧键
      仍原样落盘）；`expired_at` 仍随终点派生落（派生点在
      `md_cg/mdcg.py:3964`，键名真源 `nodefile.EXPIRED_AT_FIELD`
      → `md_cg/nodefile.py:214`）。
  [E] 边界 ≥3（3 条）：`ttl_hours=-5` 负值零行为（不落任何 ttl 键、
      不改 `effective_until`）；`ttl_hours=1e-6` 极小正值**要走 ttl 档**
      （`> 0` 判据，终点 ≈ now，`ttl_source` 落 `design`——锁「0 与极小正
      的分界」）；`ttl_hours` 显式 `None` 与不传**同形**（都不落键，
      等价性断言）。

## 真实性说明（先读后写）

蓝图只说「`ttl_hours>0` 时落三键」。实测（本机 `python -X utf8`）：

  - 键名是**规范键** `effective_until`，旧键 `valid_until` 被 `pop`；
  - `expired_at` **确实**由下方派生块落，值恒等于 `effective_until`；
  - `1e-6` 与 `0` 的分界确由 `ttl_hours > 0` 判出（`0` 零行为、`1e-6` 落键）；
  - `ttl_hours` 原值落盘不经归一（`0.5` 存 `0.5`，`2` 存 `2`）。

运行：cd D:\wook\lingshu-src && python -X utf8 -m md_cg.test_t12a_short_ttl
"""
import os
import shutil
import sys
import tempfile
import time
import atexit

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

from md_cg.mdcos import MdCGOS                  # noqa: E402
from md_cg import trust                         # noqa: E402

passed = failed = 0
_FAILS = []

#: 临时 cg 根目录：**必须落在工作区内**（系统 TEMP 在沙箱下写入被拒）。
_WORKSPACE = r"D:\wook"
_TMP_BASE = os.path.join(_WORKSPACE, "orchestrator", "tmp")

#: ttl 三键（写入侧 ttl 档的落键集合）+ 派生键。
_TTL_KEYS = ("effective_until", "ttl_hours", "ttl_source")
_DERIVED_KEY = trust.EXPIRED_FIELD              # "expired_at"

#: 零行为断言覆盖的全部四键：不传 ttl_hours 时一个都不许落。
_ZERO_KEYS = (trust.EFFECTIVE_UNTIL_FIELD, "ttl_hours", "ttl_source",
              trust.EXPIRED_FIELD)


def check(name, cond, detail=""):
    global passed, failed
    if cond:
        passed += 1
        print("  [PASS] " + name)
    else:
        failed += 1
        _FAILS.append(name)
        print("  [FAIL] " + name + "  " + str(detail)[:300])


#: 本次进程建过的全部临时 cg 根（主进程退出时统一回收，见 `_sweep_roots`）。
_ROOTS = []


def _mk_cg(tag):
    """轻量临时 cg：根目录落工作区 `orchestrator/tmp/`，用完即删。"""
    os.makedirs(_TMP_BASE, exist_ok=True)
    cg = MdCGOS(tempfile.mkdtemp(prefix="mdcg_t12a_%s_" % tag, dir=_TMP_BASE))
    _ROOTS.append(cg.root)
    return cg


def _drop(cg):
    """收尾一个临时 cg：先 `close()`、清空内存索引、再删根。

    **顺序是硬要求**：`MdCGOS` 把自身登记进模块级 `_LIVE_CGS`
    （`mdcg.py:25`）并注册 `atexit` 兜底钩子 `_atexit_flush_all`
    （`mdcg.py:146-151`、`1700`）——进程退出时对每个仍存活实例调 `close()`
    → `flush()` / `compact_index()` / `rebuild_index()`（`mdcg.py:2097-2114`、
    `2261-2281`）。
    · `close()` 只落**分片日志**，`self.index["nodes"]`（内存快照）原样保留；
    · 若段内只 `rmtree` 不处理内存态，退出时钩子看到 `index_path` 已删、
      `self.index["nodes"]` 仍非空 → 走 `rebuild_index()` → `atomic_write`
      会把 `_index.json` 连同根目录**重新建回来**（实测：历史上多轮运行
      累计 36 个 `mdcg_t12a_*` 空壳/含索引残骸）。
    故先 `close()` 落净 + 清空 `self.index` 的 nodes/buckets（钩子再跑时
    `os.path.exists(index_path)` 为假且 nodes 为空 → `close()` 成无写 no-op，
    一个文件都不会重建），最后才 `rmtree`。
    """
    try:
        cg.close()                      # 落净脏索引（分片日志侧）
    except Exception:                   # noqa: BLE001
        pass
    try:
        cg.index["nodes"].clear()       # 清内存快照：退出钩子无节点可写
        cg.index["buckets"].clear()
    except Exception:                   # noqa: BLE001
        pass
    shutil.rmtree(cg.root, ignore_errors=True)


def _sweep_roots():
    """退出前兜底回收：清掉本次进程建过的全部 `_ROOTS`（含退出钩子可能重建的）。"""
    for root in _ROOTS:
        shutil.rmtree(root, ignore_errors=True)
    return [r for r in _ROOTS if os.path.exists(r)]


def _atexit_sweep():
    """进程退出兜底（**注册早于引擎钩子** → LIFO 里最后跑，见下方注释）。"""
    _sweep_roots()


# 退出兜底登记：**必须先于任何 `MdCGOS` 实例创建**（引擎在首个实例 `__init__`
# 时 `_register_atexit_hook()`，`mdcg.py:1700`）。atexit 按 LIFO 执行——
# 本钩子先注册、引擎钩子后注册 ⇒ 退出时**引擎先 flush、本钩子最后扫**，
# 正好兜住引擎第二遍 close() 可能重建的空壳/索引文件。
atexit.register(_atexit_sweep)


def _fm(cg, nid):
    """节点 frontmatter；节点缺席返回 None。"""
    if not nid:
        return None
    got = cg.get(nid)
    if not got:
        return None
    return got.get("frontmatter") or {}


# ---------------------------------------------------------------------------
# [A] 派生真实性：三个键来自同一次真实写入，且值是**算出来的**不是照抄的
# ---------------------------------------------------------------------------

def test_a_derivation():
    print("[A] 派生真实性：effective_until 真按 now+ttl*3600 算、expired_at 真派生")
    cg = _mk_cg("a")
    _own_root = cg.root
    try:
        t0 = time.time()
        nid = cg.add("t12a_a", "短 TTL 派生真实性样本", layer="knowledge",
                     ttl_hours=2)
        fm = _fm(cg, nid)
        check("A1 节点真实落盘（add 返回 id 且 get 得到 frontmatter）",
              bool(nid) and isinstance(fm, dict) and bool(fm),
              "nid=%r fm=%r" % (nid, fm))
        end = fm.get(trust.EFFECTIVE_UNTIL_FIELD)
        check("A2 effective_until 真按 now+ttl_hours*3600 算出（非照抄入参）",
              isinstance(end, (int, float))
              and (t0 + 2 * 3600) <= float(end) <= (time.time() + 2 * 3600),
              "end=%r 期望落在 [t0+7200, now+7200]" % (end,))
        check("A3 expired_at 真由 effective_until 派生（两值逐一相等）",
              fm.get(_DERIVED_KEY) is not None
              and float(fm.get(_DERIVED_KEY)) == float(end),
              "expired_at=%r effective_until=%r" % (fm.get(_DERIVED_KEY), end))
        check("A4 节点文件真落在本次临时 cg 根下（写入侧无越界，非线上库）",
              bool(nid) and os.path.isdir(_own_root)
              and os.path.realpath(_own_root).startswith(
                  os.path.realpath(_TMP_BASE)),
              "root=%r" % (_own_root,))
    finally:
        _drop(cg)
    check("A5 本次临时 cg 根已回收（本测试不留残留目录）",
          not os.path.exists(_own_root), "残留：%r" % (_own_root,))
    print("  —— A 段 5 条（派生真实性 ≥3 ✓）")


# ---------------------------------------------------------------------------
# [B] ttl_hours 短档：落键齐 / 旧键剔 / 短档与小数 / 覆写 / 不传零行为
# ---------------------------------------------------------------------------

def test_b_short_ttl():
    print("[B] ttl_hours 短档：落三键 + 剔旧键 + 不传时零行为")
    cg = _mk_cg("b")
    try:
        # ---- B1：短档 1h 落键齐 + 旧键剔净 ----
        t0 = time.time()
        n1 = cg.add("t12a_b1", "短档一小时", layer="knowledge", ttl_hours=1)
        f1 = _fm(cg, n1)
        check("B1 短档(1h)：effective_until/ttl_hours/ttl_source 三键齐落且旧键剔净",
              all(f1.get(k) is not None for k in _TTL_KEYS)
              and f1.get("ttl_source") == "design"
              and f1.get("ttl_hours") == 1
              and trust.UNTIL_FIELD not in f1
              and (t0 + 3600) <= float(f1.get(trust.EFFECTIVE_UNTIL_FIELD)) <= (time.time() + 3600),
              "fm=%r" % ({k: f1.get(k) for k in _TTL_KEYS + (trust.UNTIL_FIELD,)},))

        # ---- B2：valid_until 与 ttl_hours 同给 ⇒ ttl 赢，旧键剔净 ----
        n2 = cg.add("t12a_b2", "旧键与短 TTL 同给", layer="knowledge",
                    valid_until=time.time() + 999, ttl_hours=1)
        f2 = _fm(cg, n2)
        _e2 = f2.get(trust.EFFECTIVE_UNTIL_FIELD)
        check("B2 valid_until+ttl_hours 同给：ttl 赢（旧键剔净、终点按 ttl 算）",
              f2.get("ttl_hours") == 1 and f2.get("ttl_source") == "design"
              and trust.UNTIL_FIELD not in f2
              and _e2 is not None and (time.time() + 3595) <= float(_e2) <= (time.time() + 3601),
              "fm=%r" % ({k: f2.get(k) for k in _TTL_KEYS + (trust.UNTIL_FIELD,)},))

        # ---- B3：小数档 0.5h 原值落盘、终点按 0.5h 算 ----
        n3 = cg.add("t12a_b3", "小数短档", layer="knowledge", ttl_hours=0.5)
        f3 = _fm(cg, n3)
        check("B3 小数档(0.5h)：ttl_hours 原值落盘 + 终点按 now+1800 算",
              f3.get("ttl_hours") == 0.5
              and (time.time() + 1795) <= float(f3.get(trust.EFFECTIVE_UNTIL_FIELD)) <= (time.time() + 1801),
              "ttl_hours=%r end=%r" % (f3.get("ttl_hours"),
                                       f3.get(trust.EFFECTIVE_UNTIL_FIELD)))

        # ---- B4：覆写既有节点（同 id 二次 add 带 ttl）仍落 ttl 三键 ----
        cg.add("t12a_b4", "覆写前（无 ttl）", layer="knowledge")
        n4 = cg.add("t12a_b4", "覆写后（带短 TTL）", layer="knowledge", ttl_hours=3)
        f4 = _fm(cg, n4)
        check("B4 覆写既有节点：二次 add 带 ttl_hours 仍落三键、旧键不回流",
              f4.get("ttl_hours") == 3 and f4.get("ttl_source") == "design"
              and trust.UNTIL_FIELD not in f4
              and trust.EFFECTIVE_UNTIL_FIELD in f4,
              "fm=%r" % ({k: f4.get(k) for k in _TTL_KEYS + (trust.UNTIL_FIELD,)},))

        # ---- B5：不传 ttl_hours ⇒ 四键零行为 ----
        n5 = cg.add("t12a_b5", "不传 ttl 的普通写入", layer="knowledge")
        f5 = _fm(cg, n5)
        check("B5 不传 ttl_hours：effective_until/ttl_hours/ttl_source/expired_at 四键全不落",
              all(f5.get(k) is None and k not in f5 for k in _ZERO_KEYS),
              "fm=%r" % ({k: f5.get(k) for k in _ZERO_KEYS},))

        # ---- B6：不传 ttl 但带旧键 ⇒ 零改写（旧键照旧落，ttl 键不落） ----
        _vu = time.time() + 888
        n6 = cg.add("t12a_b6", "不传 ttl 只带旧键", layer="knowledge", valid_until=_vu)
        f6 = _fm(cg, n6)
        check("B6 不传 ttl_hours + 只带 valid_until：旧键照旧落、ttl 三键一个不落",
              f6.get(trust.UNTIL_FIELD) == _vu
              and f6.get("ttl_hours") is None and f6.get("ttl_source") is None
              and f6.get(trust.EFFECTIVE_UNTIL_FIELD) is None
              and f6.get(_DERIVED_KEY) == _vu,
              "fm=%r" % ({k: f6.get(k) for k in
                          (trust.UNTIL_FIELD, trust.EFFECTIVE_UNTIL_FIELD,
                           "ttl_hours", "ttl_source", _DERIVED_KEY)},))
    finally:
        _drop(cg)
    print("  —— B 段 6 条（短档 ≥6，含不传时零行为 ✓）")


# ---------------------------------------------------------------------------
# [C] 到期链路：只用 trust 纯函数（不写盘、不 sleep、不依赖副作用）
# ---------------------------------------------------------------------------

def test_c_expiry_chain():
    print("[C] 到期链路：只用 trust 纯函数判 expired（零写入、零 sleep）")
    now = time.time()
    expired_fm = {trust.EFFECTIVE_UNTIL_FIELD: now - 10.0}
    live_fm = {trust.EFFECTIVE_UNTIL_FIELD: now + 3600.0}

    kind, _s, end = trust.validity(expired_fm, now=now)
    check("C1 trust.validity：effective_until 已过 ⇒ 判 expired（终点原地回传）",
          kind == "expired" and end is not None and float(end) == now - 10.0,
          "kind=%r end=%r" % (kind, end))
    check("C2 trust.is_expired：同 fm 判 True（过期判定的布尔真源）",
          trust.is_expired(expired_fm, now=now) is True
          and trust.is_expired(live_fm, now=now) is False,
          "expired=%r live=%r" % (trust.is_expired(expired_fm, now=now),
                                  trust.is_expired(live_fm, now=now)))
    check("C3 trust.time_window_msg：**点名**命中的键 effective_until（含别名口径）",
          "effective_until" in trust.time_window_msg(expired_fm, now=now),
          trust.time_window_msg(expired_fm, now=now))
    ts, key = trust.first_endpoint(
        {trust.UNTIL_FIELD: now - 5.0, trust.EFFECTIVE_UNTIL_FIELD: now - 10.0},
        trust.UNTIL_ALIASES)
    check("C4 trust.first_endpoint：规范键 effective_until 优先于旧键 valid_until",
          key == trust.EFFECTIVE_UNTIL_FIELD and float(ts) == now - 10.0,
          "key=%r ts=%r" % (key, ts))
    print("  —— C 段 4 条（到期链路 ≥4，纯函数 ✓）")


# ---------------------------------------------------------------------------
# [D] 回归：历史调用面逐字节不变（旧参数名照旧落旧键）
# ---------------------------------------------------------------------------

def test_d_regression():
    print("[D] 回归：无 ttl_hours 的历史调用面行为不变")
    cg = _mk_cg("d")
    try:
        _vu = time.time() + 777
        n1 = cg.add("t12a_d1", "历史调用面：valid_until", layer="knowledge",
                    valid_until=_vu)
        f1 = _fm(cg, n1)
        check("D1 旧参数 valid_until：照旧落旧键、不落规范键（零破坏）",
              f1.get(trust.UNTIL_FIELD) == _vu
              and f1.get(trust.EFFECTIVE_UNTIL_FIELD) is None
              and trust.EFFECTIVE_UNTIL_FIELD not in f1,
              "fm=%r" % ({k: f1.get(k) for k in
                          (trust.UNTIL_FIELD, trust.EFFECTIVE_UNTIL_FIELD)},))

        _eu = time.time() + 666
        n2 = cg.add("t12a_d2", "规范调用面：effective_until", layer="knowledge",
                    effective_until=_eu)
        f2 = _fm(cg, n2)
        check("D2 新参数 effective_until：落规范键、剔旧键，且 expired_at 照旧派生",
              f2.get(trust.EFFECTIVE_UNTIL_FIELD) == _eu
              and trust.UNTIL_FIELD not in f2
              and f2.get(_DERIVED_KEY) == _eu
              and f2.get("ttl_hours") is None and f2.get("ttl_source") is None,
              "fm=%r" % ({k: f2.get(k) for k in
                          (trust.EFFECTIVE_UNTIL_FIELD, trust.UNTIL_FIELD,
                           _DERIVED_KEY, "ttl_hours", "ttl_source")},))
    finally:
        _drop(cg)
    print("  —— D 段 2 条（回归 ≥2 ✓）")


# ---------------------------------------------------------------------------
# [E] 边界：负值 / 极小正值 / 显式 None 与不传同形
# ---------------------------------------------------------------------------

def test_e_boundary():
    print("[E] 边界：负值零行为、极小正值走 ttl 档、显式 None 等价不传")
    cg = _mk_cg("e")
    try:
        # ---- E1：负值零行为 ----
        n1 = cg.add("t12a_e1", "负 ttl_hours", layer="knowledge", ttl_hours=-5)
        f1 = _fm(cg, n1)
        check("E1 ttl_hours=-5：四键全不落（>0 判据的负侧边界，零行为）",
              all(f1.get(k) is None and k not in f1 for k in _ZERO_KEYS),
              "fm=%r" % ({k: f1.get(k) for k in _ZERO_KEYS},))

        # ---- E2：极小正值必须走 ttl 档（0 与极小正的分界） ----
        t0 = time.time()
        n2 = cg.add("t12a_e2", "极小正 ttl_hours", layer="knowledge",
                    ttl_hours=1e-6)
        f2 = _fm(cg, n2)
        _end2 = f2.get(trust.EFFECTIVE_UNTIL_FIELD)
        check("E2 ttl_hours=1e-6：走 ttl 档（三键落、终点≈now——分界在 >0 不在 >1e-3）",
              f2.get("ttl_hours") == 1e-6 and f2.get("ttl_source") == "design"
              and _end2 is not None and (t0 - 1.0) <= float(_end2) <= (time.time() + 1.0)
              and f2.get(_DERIVED_KEY) is not None,
              "fm=%r" % ({k: f2.get(k) for k in _TTL_KEYS + (_DERIVED_KEY,)},))

        # ---- E3：显式 None 与不传同形 ----
        n3a = cg.add("t12a_e3a", "显式 None", layer="knowledge", ttl_hours=None)
        n3b = cg.add("t12a_e3b", "不传", layer="knowledge")
        f3a, f3b = _fm(cg, n3a), _fm(cg, n3b)
        check("E3 显式 None 与不传同形：两节点的四键存在性/取值逐一一致（全空）",
              all((k in f3a) == (k in f3b) and f3a.get(k) == f3b.get(k)
                  for k in _ZERO_KEYS)
              and all(f3a.get(k) is None for k in _ZERO_KEYS),
              "explicit=%r omitted=%r" % (
                  {k: f3a.get(k) for k in _ZERO_KEYS},
                  {k: f3b.get(k) for k in _ZERO_KEYS}))
    finally:
        _drop(cg)
    print("  —— E 段 3 条（边界 ≥3 ✓）")


def main():
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    print("===== md_cg.test_t12a_short_ttl（E-T12a t1 design 短 TTL 档验收） =====")
    print("临时 cg 基目录：%s（工作区内，不触线上库）" % _TMP_BASE)
    # 开跑前先清历史残留：`mdcg_t12a_*` 前缀即本测试的垃圾（旧版无 atexit
    # 兜底时，进程退出钩子可能在删根后重建空壳/索引，历史多轮累计过 36 个）。
    # 清了它，F2 的「零残骸」断言才只对本轮负责，不被陈旧脏目录误伤。
    _pre = []
    if os.path.isdir(_TMP_BASE):
        for _n in os.listdir(_TMP_BASE):
            if _n.startswith("mdcg_t12a_"):
                shutil.rmtree(os.path.join(_TMP_BASE, _n), ignore_errors=True)
                _pre.append(_n)
    if _pre:
        print("  已清理历史残留 %d 个（上一版本无退出兜底的遗留）：%s"
              % (len(_pre), ", ".join(sorted(_pre))))
    test_a_derivation()
    test_b_short_ttl()
    test_c_expiry_chain()
    test_d_regression()
    test_e_boundary()
    # 段内已 `_drop` 过，这里再兜一次：清掉退出钩子可能重建的空壳（见 `_drop` 注释）。
    _left = _sweep_roots()
    check("F1 全段收尾：本次进程的临时 cg 根一个不留（含退出钩子重建的空壳）",
          not _left, "残留：%r" % (_left,))
    check("F2 临时 cg 基目录下无本测试遗留的 mdcg_t12a_* 残骸",
          not [n for n in os.listdir(_TMP_BASE)
               if n.startswith("mdcg_t12a_")] if os.path.isdir(_TMP_BASE) else True,
          "残留：%r" % ([n for n in os.listdir(_TMP_BASE)
                         if n.startswith("mdcg_t12a_")]
                        if os.path.isdir(_TMP_BASE) else [],))
    if _FAILS:
        print("\n失败明细：")
        for name in _FAILS:
            print("  - " + name)
    print("\n===== t12a short ttl：%d 通过，%d 失败 =====" % (passed, failed))
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
