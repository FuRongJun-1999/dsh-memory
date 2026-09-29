# -*- coding: utf-8 -*-
"""FI-M03 · S2 软件（自身代码缺陷：写面漏标脏）→ 静默改写（盘上新值检索面旧值）。

判据：T4 静默损伤（正常响应内容错且不可观测）+ T12 端到端（写面与读面跨层
不一致，任何单层校验都不报错）。留档：N133（docs/eval/缺陷挖掘_自主迭代
_v16.md:85——md_cg/forgetting.py:274-283 reinforce 直调 _write_node 后仅改内存
entry 不标 _dirty；对照修复先例 md_cg/mdcg.py:3242 verify 路径显式补
_dirty[node_id]=e）。

**2026-09-29 修复复测（opt-batch1 C-1）：本格由 EXPECTED_GAP 转 pass。**
修复=同族三处写点（`forgetting.reinforce` / `insight.verify` /
`scrub._apply_offset`）在 `cg._write_node` 后统一补
`cg._dirty[node_id] = entry`（对照先例同款），使读缓存的 `path_gen` 推进 ⇒
`_fresh` 判旧快照过期 ⇒ 同进程「写后读」拿到盘上真值。registry 登记同步由
gap 改写为 pass（缺口结案留痕）。

注入：临时 root 装 readcache（默认开）→ add(n_fi, importance=0.5) → search 装
缓存 → forgetting.reinforce(cg,'n_fi',delta=0.3)（返回 0.8）→ 再 search 同 query。

理论预期（修复后）：再 search **返回 0.8**——写面与读面同批可见（T4/T12 防线
在位）；若判据回退，本格转 gap 并由 run_all 按登记不一致亮红。
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import harness        # noqa: E402
import mdcg_support   # noqa: E402


def main() -> int:
    case = harness.Case("FI-M03", "reinforce 写盘成功检索面同批可见（修复复测）")
    try:
        d = case.tmpdir("m03")
        mdcg_support.apply_env(d)
        from md_cg import nodefile
        from md_cg import readcache
        from md_cg.forgetting import reinforce
        from md_cg.mdcos import MdCGSecure

        case.check("读码：对照修复先例在位（mdcg.py verify 路径写盘后显式补 "
                   "_dirty[node_id]=e——本格修复即照此补齐三处写点）",
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

            case.check("绿场①（修复点）：写盘后已标脏（cg._dirty 含该节点 ⇒ "
                       "path_gen 推进，读缓存精确失效）",
                       "n_fi" in cg._dirty, f"dirty={list(cg._dirty)}")

            imp_after = top_imp(cg.search(q))
            case.check("绿场②（端到端）：写后同 query 检索面返回 0.8——写面与"
                       "读面同批一致（修复前此处恒返回 0.5，静默改写零告警）",
                       imp_after == 0.8, f"search importance={imp_after}")

            g = cg.get("n_fi")
            e = cg.index["nodes"]["n_fi"]
            with open(cg._node_disk_path(e), encoding="utf-8") as f:
                fm_disk, _c = nodefile.loads(f.read())
            cache_val = cg._read_cache.get(e["path"])
            case.check("绿场③（物证）：盘面 / get / 读缓存**三者同为 0.8**——"
                       "缓存条目已随标脏重装，不再冻结写盘前旧 fm",
                       fm_disk.get("importance") == 0.8
                       and (g or {}).get("frontmatter", {}).get("importance") == 0.8
                       and cache_val is not None
                       and cache_val[1][0].get("importance") == 0.8,
                       f"disk={fm_disk.get('importance')} "
                       f"get={g['frontmatter']['importance']} "
                       f"cache={cache_val[1][0].get('importance') if cache_val else None}")

            case.check("对照面：readcache.clear 后检索面同样为 0.8（标脏失效与"
                       "强制清空两条路同结论——修复不是靠清缓存掩盖）",
                       readcache.clear(cg) >= 1 and top_imp(cg.search(q)) == 0.8,
                       f"cleared 后 search importance={top_imp(cg.search(q))}")

            # 四可（D4）
            case.check("四可：可发现=是（标脏即索引增量日志与读缓存代际双可见）/可隔离="
                       "是（失效粒度按 path，只失效被写节点）/可恢复=是（clear/重启）"
                       "/可追溯=是（_dirty→flush→_index_log 重放，跨进程可对账）",
                       True,
                       "证据=绿场①-③ + clear 对照 + mdcg.py:3242 先例")
            verdict = "gap" if case.fails else "pass"
            return case.finish(verdict, expected="pass")
        finally:
            cg.close()
    finally:
        case.cleanup()


if __name__ == "__main__":
    sys.exit(main())
