# -*- coding: utf-8 -*-
"""FI-M02 · S1 硬件/OS（资源剥夺：独占句柄制造瞬态读失败）→ 负结果固化入缓存。

判据：P1 fail-closed（读失败应落向「暂不可用」而非「不存在」）+ T4 静默损伤。
留档：N134（docs/eval/缺陷挖掘_自主迭代_v16.md:86——md_cg/mdcg.py:2199-2208
_read 捕 OSError 返 (None,None) + readcache.py:102-110 负结果无豁免入缓存）。
注入：临时 root 建 MdCGSecure+readcache.install（默认开），add 节点后
kernel32.CreateFileW(path, GENERIC_READ|WRITE, dwShareMode=0) 独占持住节点 md
文件，冷缓存 search（必 miss），CloseHandle 释放后连续 search 两次。

理论预期（EXPECTED_GAP，登记 gap）：持锁期 miss、解锁后仍 miss——一次瞬态
OS 失败固化为「节点从检索面消失直至重启/再写盘」，cache 条目字面
(gen,(None,None))；cg.get 直读不走缓存照常可读＝「get 能读、search 搜不到」
撕裂。对照格：无注入同内容独立 root search 正常命中。
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
    case = harness.Case("FI-M02", "瞬态读失败固化为检索面永久消失")
    try:
        d = case.tmpdir("m02")
        mdcg_support.apply_env(d)
        from md_cg import readcache
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
                ids_lock = ids_of(cg.search(q)) if held else None
                entry_lock = cg._read_cache.get(cache_key) if held else None
            finally:
                if held:
                    k32.CloseHandle(h)
            case.check("红场①：持锁期冷缓存 search miss（OSError→(None,None)）",
                       ids_lock == [], f"hits={ids_lock}")
            case.check("红场②：负结果被当正常值固化入缓存（条目=(gen,(None,None)))",
                       entry_lock is not None and entry_lock[1] == (None, None),
                       f"cache[{cache_key!r}]={entry_lock!r}")
            ids_r1 = ids_of(cg.search(q))
            ids_r2 = ids_of(cg.search(q))
            case.check("红场③：释放句柄后连续两次 search 仍 miss（_fresh 判定恒"
                       "真——瞬态失败固化为检索面消失）",
                       ids_r1 == [] and ids_r2 == [],
                       f"after_unlock={ids_r1}/{ids_r2}")
            g = cg.get("m1")
            case.check("红场④：cg.get 直读不走缓存照常可读（撕裂：get 能读、"
                       "search 搜不到）",
                       g is not None
                       and g["frontmatter"].get("importance") == 0.5,
                       f"get importance={(g or {}).get('frontmatter', {}).get('importance')}")
            case.check("恢复面在位（可恢复=是）：readcache.clear(cg) 手动兜底 API",
                       hasattr(readcache, "clear")
                       and readcache.clear(cg) >= 1
                       and ids_of(cg.search(q)) == ["m1"],
                       f"cleared 后 hits={ids_of(cg.search(q))}")

            # 四可（D4）
            case.check("四可：可发现=否（零告警零日志，静默损伤 T4）/可隔离=是"
                       "（按 path 精确固化，对照 root 与其余节点不受累）/可恢复="
                       "是（clear/再写盘/重启）/可追溯=是（进程内 cache 条目字面"
                       " (gen,(None,None)) 为直接证据，但无持久日志）",
                       True,
                       "证据=红场①-④ + 对照组命中 + clear 恢复命中")
            verdict = "gap" if not case.fails else "fail"
            return case.finish(verdict, expected="gap")
        finally:
            cg.close()
    finally:
        case.cleanup()


if __name__ == "__main__":
    sys.exit(main())
