# -*- coding: utf-8 -*-
"""FI-M03 · S2 软件（自身代码缺陷：写面漏标脏）→ 静默改写（盘上新值检索面旧值）。

判据：T4 静默损伤（正常响应内容错且不可观测）+ T12 端到端（写面与读面跨层
不一致，任何单层校验都不报错）。留档：N133（docs/eval/缺陷挖掘_自主迭代
_v16.md:85——md_cg/forgetting.py:274-283 reinforce 直调 _write_node 后仅改内存
entry 不标 _dirty；对照修复先例 md_cg/mdcg.py:3242 verify 路径显式补
_dirty[node_id]=e）。
注入：临时 root 装 readcache（默认开）→ add(n_fi, importance=0.5) → search 装
缓存 → forgetting.reinforce(cg,'n_fi',delta=0.3)（返回 0.8）→ 再 search 同 query。

理论预期（EXPECTED_GAP，登记 gap）：再 search 仍返回 0.5，直读盘上为 0.8——
同进程写后读永久陈旧（path_gen/broad_gen 均不推进，缓存把写盘前旧值判新鲜）。
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import harness        # noqa: E402
import mdcg_support   # noqa: E402


def main() -> int:
    case = harness.Case("FI-M03", "reinforce 写盘成功检索面读旧值")
    try:
        d = case.tmpdir("m03")
        mdcg_support.apply_env(d)
        from md_cg import nodefile
        from md_cg import readcache
        from md_cg.forgetting import reinforce
        from md_cg.mdcos import MdCGSecure

        case.check("读码：对照修复先例在位（mdcg.py verify 路径写盘后显式补 "
                   "_dirty[node_id]=e——证明漏标脏危害与修复方向在案）",
                   "self._dirty[node_id] = e" in harness.src("md_cg/mdcg.py"),
                   "md_cg/mdcg.py:3242")

        cg = MdCGSecure(os.path.join(d, "m03root"),
                        principal=mdcg_support.writer_principal())
        try:
            cg.add("n_fi", "香蕉 m03unique 强化正文", layer="knowledge",
                   importance=0.5)
            cg.flush()
            readcache.install(cg)
            q = "m03unique 香蕉"

            def top_imp(hits):
                if hits and hits[0]:
                    return hits[0][0][0].get("frontmatter", {}).get("importance")
                return None

            imp_before = top_imp(cg.search(q))            # 装缓存
            case.check("基线：写入 0.5 且检索面读到 0.5（缓存已装填）",
                       imp_before == 0.5, f"search importance={imp_before}")

            r = reinforce(cg, "n_fi", delta=0.3)
            case.check("注入执行：reinforce 返回 importance=0.8（写面自认成功）",
                       r is not None and r.get("importance") == 0.8,
                       f"reinforce={r}")

            imp_after = top_imp(cg.search(q))
            case.check("红场①：写后同 query 检索面仍返回 0.5（静默改写，零告警）",
                       imp_after == 0.5, f"search importance={imp_after}")

            g = cg.get("n_fi")
            e = cg.index["nodes"]["n_fi"]
            with open(cg._node_disk_path(e), encoding="utf-8") as f:
                fm_disk, _c = nodefile.loads(f.read())
            cache_val = cg._read_cache.get(e["path"])
            case.check("红场②：盘面与直读均为 0.8——写盘成功，仅检索面陈旧"
                       "（get 能读新值 / search 永远搜不到新值型撕裂）",
                       fm_disk.get("importance") == 0.8
                       and (g or {}).get("frontmatter", {}).get("importance") == 0.8,
                       f"disk={fm_disk.get('importance')} get={g['frontmatter']['importance']}")
            case.check("红场③：缓存条目冻结写盘前旧 fm（importance=0.5）——"
                       "_fresh 判恒真的物证",
                       cache_val is not None
                       and cache_val[1][0].get("importance") == 0.5,
                       f"cache fm.importance={cache_val[1][0].get('importance') if cache_val else None}")
            case.check("恢复面在位（可恢复=是）：readcache.clear 后检索面见 0.8",
                       readcache.clear(cg) >= 1 and top_imp(cg.search(q)) == 0.8,
                       f"cleared 后 search importance={top_imp(cg.search(q))}")

            # 四可（D4）
            case.check("四可：可发现=否（零告警，仅跨面对账可发现，T4）/可隔离="
                       "是（仅被写节点 path 陈旧）/可恢复=是（clear/再写盘标脏/"
                       "重启；修复方向=N133 对照先例补 _dirty）/可追溯=是（盘面 "
                       "0.8 vs 缓存 0.5 可对账，无持久日志）",
                       True,
                       "证据=红场①-③ + clear 恢复 + mdcg.py:3242 先例")
            verdict = "gap" if not case.fails else "fail"
            return case.finish(verdict, expected="gap")
        finally:
            cg.close()
    finally:
        case.cleanup()


if __name__ == "__main__":
    sys.exit(main())
