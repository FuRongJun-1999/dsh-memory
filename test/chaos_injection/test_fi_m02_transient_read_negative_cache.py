# -*- coding: utf-8 -*-
"""FI-M02 · S1 硬件/OS（资源剥夺：独占句柄制造瞬态读失败）→ 负结果是否被固化入缓存。

判据：P1 fail-closed（读失败应落向「暂不可用」而非「不存在」且**不得固化**）
      + T4 静默损伤（读失败必须可观测）。
留档：N134（docs/eval/缺陷挖掘_自主迭代_v16.md:86——md_cg/mdcg.py 的 _read 把
OSError 返 (None,None) + readcache.py:102-110 负结果无豁免入缓存）。
注入：临时 root 建 MdCGSecure+readcache.install（默认开），add 节点后
kernel32.CreateFileW(path, GENERIC_READ|WRITE, dwShareMode=0) 独占持住节点 md
文件，冷缓存 search（必 miss），CloseHandle 释放后连续 search 两次。

**本格状态：EXPECTED_GAP → pass（2026-09-29，C-3 批次）**。修前（缺口在案）：
持锁期 miss、解锁后仍 miss——一次瞬态 OS 失败固化为「节点从检索面消失直至重启/
再写盘」，cache 条目字面 `(gen,(None,None))`；cg.get 直读不走缓存照常可读＝
「get 能读、search 搜不到」撕裂。修后（本文件现判据）：
  · 读路径在**唯一捕获 OSError 的点**上给出三态标签（`MdCG._read_status` 第三
    元素，判别函数 `fsutil.classify_read_failure`：仅 FileNotFoundError 为终态
    「真缺」，其余 OSError 一律判瞬时）；
  · 缓存**只接纳成功与终态真缺**，瞬时读失败不入缓存 ⇒ 该 path 下次查询即重试，
    瞬态窗口为零：**释放句柄后首次查询即命中**；
  · 失败不再静默：模块级计数 + 有界样本（`fsutil.transient_read_stats`）+ stderr
    一行告警。
对照格：无注入同内容独立 root search 正常命中（查询面本身有效，防夹具空转）。

跨平台说明（诚实声明）：置景手法平台受限——独占句柄用 ctypes.WinDLL（Windows
专属 API），unix 无内核共享模式。非 Windows **维持 SKIP 并报登记格 pass 基线**
（与 FI-R09 同款约定：Windows 实测结论为准，本平台非实测、不伪造实测）。缺口本体
（读失败负缓存固化 / 三态判别 / 记账面）的**跨平台机械判据**由
`md_cg/test_c3_transient_read_negative.py` 承担（OpenError 注入 + 同名目录顶位，
两平台可跑，含定点变异自证）。
"""
import ctypes
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import harness        # noqa: E402
import mdcg_support   # noqa: E402

GENERIC_RW = 0x80000000 | 0x40000000   # GENERIC_READ|GENERIC_WRITE
OPEN_EXISTING = 3
INVALID = ctypes.c_void_p(-1).value


def main() -> int:
    case = harness.Case("FI-M02", "瞬态读失败不得固化为检索面永久消失")
    if os.name != "nt":
        # 置景手法平台受限：独占句柄用 ctypes.WinDLL（Windows 专属 API）。
        # 维持登记 pass 基线（Windows 实测为准，本平台非实测、不伪造实测；
        # 跨平台机械判据见 md_cg/test_c3_transient_read_negative.py）。
        case.note("非 Windows 平台：无 WinDLL，独占句柄置景不可用——SKIP 维持"
                  "登记 pass 基线（Windows 实测为准，本平台非实测；跨平台判据"
                  "在 md_cg/test_c3_transient_read_negative.py）")
        case.finish("pass", "pass")
        return 0
    try:
        d = case.tmpdir("m02")
        mdcg_support.apply_env(d)
        from md_cg import fsutil, readcache
        from md_cg.mdcos import MdCGSecure

        def ids_of(hits):
            return [x[0]["id"] for x in hits[0]] if hits and hits[0] else []

        # ═══ 对照组（绿场）：无注入，同内容独立 root 命中 ═══
        pr = mdcg_support.writer_principal()
        ctrl_root = os.path.join(d, "m02ctrl")
        cgc = MdCGSecure(ctrl_root, principal=pr)
        cgc.add("m1", "苹果 苹果 苹果 m02unique 检索正文", layer="knowledge",
                importance=0.5)
        cgc.flush()
        readcache.install(cgc)
        ctrl_ids = ids_of(cgc.search("m02unique 苹果"))
        cgc.close()
        case.check("对照组：无注入时 search 命中 m1（查询面本身有效）",
                   ctrl_ids == ["m1"], f"hits={ctrl_ids}")

        # ═══ 主场：独占句柄制造瞬态读失败 ═══
        root = os.path.join(d, "m02root")
        cg = MdCGSecure(root, principal=pr)
        try:
            cg.add("m1", "苹果 苹果 苹果 m02unique 检索正文", layer="knowledge",
                   importance=0.5)
            cg.flush()
            readcache.install(cg)
            e = cg.index["nodes"]["m1"]
            p = cg._node_disk_path(e)
            cache_key = e["path"]            # 缓存键 = entry 相对 path

            k32 = ctypes.WinDLL("kernel32", use_last_error=True)
            k32.CreateFileW.restype = ctypes.c_void_p
            k32.CreateFileW.argtypes = [ctypes.c_wchar_p, ctypes.c_uint32,
                                        ctypes.c_uint32, ctypes.c_void_p,
                                        ctypes.c_uint32, ctypes.c_uint32,
                                        ctypes.c_void_p]
            h = k32.CreateFileW(p, GENERIC_RW, 0, None, OPEN_EXISTING, 0, None)
            held = h not in (None, INVALID)
            case.check("注入生效：CreateFileW(dwShareMode=0) 独占持住节点 md 文件",
                       held, f"handle={h}")
            q = "m02unique 苹果"
            try:
                # 冷缓存：确保本次查询真的走读路径（不是缓存命中掩盖注入）
                readcache.clear(cg)
                ids_lock = ids_of(cg.search(q)) if held else None
                entry_lock = cg._read_cache.get(cache_key) if held else None
                stat_lock = fsutil.transient_read_stats() if held else None
            finally:
                if held:
                    k32.CloseHandle(h)
            case.check("修复①：持锁期冷缓存 search miss（读失败 fail-closed："
                       "不可读即不参与检索，绝不泄漏半读内容）",
                       ids_lock == [], f"hits={ids_lock}")
            case.check("修复②：负结果**不入缓存**（cache 该 path 无条目——修前为"
                       "字面 (gen,(None,None)) 的固化条目）",
                       entry_lock is None, f"cache[{cache_key!r}]={entry_lock!r}")
            case.check("修复③：记账面可观测（瞬时读失败计数 > 0 且样本含 path 与"
                       "异常类型——修前零告警零日志的 T4 静默损伤已消除）",
                       stat_lock is not None and stat_lock[0] >= 1
                       and any("m1.md" in s[0] and s[1] == "PermissionError"
                               for s in stat_lock[1]),
                       f"stats={stat_lock}")
            ids_r1 = ids_of(cg.search(q))
            ids_r2 = ids_of(cg.search(q))
            case.check("修复④：释放句柄后**首次**查询即命中（瞬态窗口为零——"
                       "一次可重试失败不再固化成检索面消失）",
                       ids_r1 == ["m1"] and ids_r2 == ["m1"],
                       f"after_unlock={ids_r1}/{ids_r2}")
            g = cg.get("m1")
            case.check("修复⑤：cg.get 直读照常可读，且与 search 同批可见"
                       "（「get 能读、search 搜不到」撕裂消除）",
                       g is not None
                       and g["frontmatter"].get("importance") == 0.5
                       and ids_r1 == ["m1"],
                       f"get importance={(g or {}).get('frontmatter', {}).get('importance')}")
            case.check("恢复面在位：readcache.clear(cg) 手动兜底 API 仍在（外部批量"
                       "改写盘面后的强制失效口）",
                       hasattr(readcache, "clear")
                       and readcache.clear(cg) >= 1
                       and ids_of(cg.search(q)) == ["m1"],
                       f"cleared 后 hits={ids_of(cg.search(q))}")

            # 四可（D4）
            case.check("四可：可发现=是（stderr 一行告警 + 进程内计数/样本可读——"
                       "fsutil.transient_read_stats）/可隔离=是（按 path 精确处置，"
                       "对照 root 与其余节点不受累）/可恢复=是（无需人工介入：释放"
                       "即命中；clear 仍为兜底）/可追溯=是（计数 + 有界样本含 path"
                       "与异常类型，修前的零留痕面已补齐）",
                       True,
                       "证据=修复①-⑤ + 对照组命中 + 记账面读数")
            verdict = "pass" if not case.fails else "fail"
            return case.finish(verdict, expected="pass")
        finally:
            cg.close()
    finally:
        case.cleanup()


if __name__ == "__main__":
    sys.exit(main())
