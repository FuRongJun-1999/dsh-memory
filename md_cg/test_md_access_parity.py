# -*- coding: utf-8 -*-
"""P45 · md 直读访问层与 SQLite 派生库的逐位对拍守卫。

验证目标
--------
1) **查询等价**：白箱检索层全部 ~8 处真实直查 SQL（KCCS 注释索引 /
   学科路由 / 四要素卡递归 / 知识点对齐 / 卡定位），在 MdConn（md 直读）
   与 SQLite 派生库上以**多组真实参数**运行，结果逐行逐列逐序相等；
2) **行序等价**：无 ORDER BY 时 MdConn 返回序 = _restore 插入序
   （LAYERS 权威序 × os.walk 序）——fetchone / LIMIT 1 语义等价的前提；
3) **解析等价**：md_access 自包含 frontmatter 解析（独立部署 fallback）
   与 nodefile 权威解析全库逐字段一致——独立部署形态的守卫；
4) **fail-closed**：写语句、超文法 SQL、未知列均拒绝不静默。

运行：`python -m md_cg.test_md_access_parity`
"""
from __future__ import annotations

import json
import os
import sqlite3
import sys
import tempfile

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(_HERE))

from .md_whitebox import DEFAULT_ROOT, build_db_from_md, corpus_gap  # noqa: E402

# 平铺导入引导（对齐 whitebox_kb/__init__：md_access 需在 sys.path 注入后导入）
_WB = os.path.join(_HERE, "whitebox_kb")
for _p in (_WB, os.path.join(_WB, "wisdom")):
    if _p not in sys.path:
        sys.path.insert(0, _p)
from md_access import LAYERS, MdConn, _parse_node_text  # noqa: E402 平铺导入

_N_ASSERT = 0


def _ok(cond, label):
    global _N_ASSERT
    _N_ASSERT += 1
    tag = "PASS" if cond else "FAIL"
    print(f"  [{tag}] {label}")
    return bool(cond)


# 8 处真实直查 SQL（与检索层源码逐字符一致，参数以 ? 绑定）
CASES = [
    # semantic_translate L2519 卡定位
    ("卡定位", "SELECT id FROM nodes WHERE layer='knowledge' "
     "AND state_attributes LIKE ? AND tags NOT LIKE '%knowledge_point%' "
     "LIMIT 1", ['%"name": "{name}"%']),
    # semantic_translate L2527 卡内知识点扫描
    ("知识点扫描", "SELECT state_attributes, content FROM nodes "
     "WHERE layer='knowledge' AND tags LIKE ? AND tags LIKE ?",
     ['%knowledge_point%', '%card:{prefix}%']),
    # semantic_translate L2599 整卡行
    ("整卡行", "SELECT * FROM nodes WHERE layer='knowledge' "
     "AND state_attributes LIKE ?", ['%"name": "{name}"%']),
    # semantic_translate L2945 KCCS 注释索引（全库）
    ("KCCS索引", "SELECT id, state_attributes, content FROM nodes "
     "WHERE state_attributes LIKE '%\"comment\"%'", []),
    # semantic_translate L3161 学科路由第一段（全库）
    ("学科路由", "SELECT state_attributes FROM nodes "
     "WHERE state_attributes LIKE '%\"comment\"%'", []),
    # semantic_translate L3244 学科卡扫描
    ("学科卡", "SELECT id, content, state_attributes FROM nodes "
     "WHERE state_attributes LIKE '%\"kind\": \"subject_card\"%' LIMIT 200", []),
    # semantic_translate L3584 知识点直答定位
    ("kp直答", "SELECT content FROM nodes WHERE tags LIKE ? AND tags LIKE ? "
     "AND state_attributes LIKE ? LIMIT 1",
     ['%knowledge_point%', '%card:{prefix}%', '%"name": "{kp}"%']),
    # wisdom_book L826 卡名预过滤
    ("卡名预过滤", "SELECT * FROM nodes WHERE layer='knowledge' "
     "AND state_attributes LIKE '%\"name\"%' "
     "AND tags NOT LIKE '%knowledge_point%'", []),
]


def _sample_params(md_conn):
    """从 md 语料提取真实参数样例：卡名 / (card 前缀, 知识点名) 配对。"""
    names, pairs = [], []
    rows = md_conn.execute(
        "SELECT tags, state_attributes FROM nodes WHERE tags LIKE '%card:%' "
        "LIMIT 60").fetchall()
    for tags_json, sa_json in rows:
        try:
            sa = json.loads(sa_json or "{}")
            tags = (json.loads(tags_json or "[]")
                    if isinstance(tags_json, str) else tags_json or [])
        except Exception:
            continue
        nm = sa.get("name") or ""
        pr = next((t[5:] for t in tags
                   if isinstance(t, str) and t.startswith("card:")), None)
        if pr and nm:
            pairs.append((pr, nm))
        if len(pairs) >= 4:
            break
    card_rows = md_conn.execute(
        "SELECT state_attributes FROM nodes WHERE layer='knowledge' "
        "AND state_attributes LIKE ? AND tags NOT LIKE '%knowledge_point%' "
        "LIMIT 60", ('%"kind": "subject_card"%',)).fetchall()
    for (sa_json,) in card_rows:
        try:
            nm = (json.loads(sa_json or "{}").get("name")) or ""
        except Exception:
            continue
        if nm and nm not in names:
            names.append(nm)
        if len(names) >= 3:
            break
    return (names,
            [p for p, _ in pairs],   # prefix 样例（与 kp 名同源配对）
            [k for _, k in pairs])   # kp 名样例


def _param_groups(arg_tpls, samples):
    """槽位模板列表 → 完整参数组列表。

    含同一占位符的槽位按索引 i 取样例（prefix 与 kp 同源配对不拆散），
    静态槽原样；每组是合法完整参数向量。
    """
    used = {}
    for t in arg_tpls:
        for k in ("name", "prefix", "kp"):
            if "{" + k + "}" in t:
                used[k] = samples.get(k) or []
    n = max((len(v) for v in used.values()), default=1)
    return [[t.format(**{k: v[i % len(v)] for k, v in used.items()})
             for t in arg_tpls] for i in range(n)]


def main():
    ok = True
    # 依赖自辩（2026-09-20 v14 缺陷 F）：md 语料是 gitignored 本地数据面，
    # 缺失/空壳时**本模块自己**打 SKIP 返回 0——不再依赖外部 runner 探测
    # （旁路执行时 runner 不在场），也不再留下未捕获异常或空壳副作用。
    _gap = corpus_gap(DEFAULT_ROOT)
    if _gap:
        print("SKIP test_md_access_parity：%s" % _gap)
        return 0
    print("== [1] 重建派生库 + 建 MdConn ==")
    stats = build_db_from_md(force=True, verbose=True)
    md_conn = MdConn(DEFAULT_ROOT, layers=LAYERS)
    sq = sqlite3.connect(f"file:{stats['db']}?mode=ro", uri=True)
    try:
        n_sq = sq.execute("SELECT COUNT(*) FROM nodes").fetchone()[0]
        n_md = len(md_conn._all_rows())
        print(f"  派生库 nodes={n_sq}  md 直读行={n_md}")
        # 判据=三方等价（派生库 == md 直读 == 还原计数）。旧断言把 `== 4355`（导出前
        # 快照行数）一并写死：绝对行数是本地数据面规模、非代码契约，锚死它会让「数据面
        # 正常生长」被误判成等价性破坏（2026-09-19 重跑 migrate_wisdom_graph.export 后
        # 4355 → 4459 即由此假红）。保留量级下界防退化为空库。
        ok &= _ok(n_sq == n_md == stats["nodes"] and n_sq >= 4000,
                  f"行数三方等价（派生库 {n_sq} == md 直读 {n_md} == "
                  f"还原 {stats['nodes']}）且 >= 4000")

        print("== [2] 8 处真实 SQL 逐位对拍 ==")
        names, prefixes, kps = _sample_params(md_conn)
        print(f"  样例：卡名×{len(names)} 前缀×{len(prefixes)} kp名×{len(kps)}")
        ok &= _ok(bool(names and prefixes and kps), "真实参数样例非空")
        samples = {"name": names, "prefix": prefixes, "kp": kps}
        total_bad = 0
        for label, sql, arg_tpls in CASES:
            params_list = (_param_groups(arg_tpls, samples)
                           if arg_tpls else [[]])
            bad = 0
            for p in params_list:
                a = sq.execute(sql, p).fetchall()
                b = md_conn.execute(sql, p).fetchall()
                if a != b:
                    bad += 1
                    if bad == 1:
                        print(f"    差异样例 params={p}")
                        print(f"      sql : {a[:2]}")
                        print(f"      md  : {b[:2]}")
            total_bad += bad
            ok &= _ok(bad == 0, f"{label}：{len(params_list)} 组参数逐位一致")
        _ok(total_bad == 0, f"对拍总差异 0（实得 {total_bad}）")

        print("== [3] 行序等价（插入序 = rowid 序） ==")
        # 无 WHERE 的 `SELECT id` 在 SQLite 走覆盖索引（id 字典序），不反映
        # 插入序；白箱 8 处直查全带谓词（rowid 扫描），行序等价的正确测量
        # 是 `ORDER BY rowid`（= 插入序）与 MdConn 行序的一致性。
        a = [r[0] for r in
             sq.execute("SELECT id FROM nodes ORDER BY rowid").fetchall()]
        b = [r[0] for r in md_conn._all_rows()]
        ok &= _ok(a == b, f"插入序一致（{len(a)} 行）")

        print("== [4] 解析等价（自包含 fallback vs nodefile，抽样 500） ==")
        if _HERE not in sys.path:
            sys.path.insert(0, _HERE)  # nodefile 平铺导入需 md_cg 目录在 path
        import nodefile
        import md_access as _ma
        checked = diff = 0
        root = DEFAULT_ROOT
        for dirpath, _dirs, files in os.walk(root):
            for fn in files:
                if not fn.endswith(".md"):
                    continue
                checked += 1
                if checked > 500:
                    break
                p = os.path.join(dirpath, fn)
                try:
                    text = open(p, encoding="utf-8").read()
                except OSError:
                    continue
                f1, c1 = nodefile.loads(text)
                saved = _ma._nf_loads
                try:
                    _ma._nf_loads = None   # 强制走自包含 fallback 解析
                    f2, c2 = _parse_node_text(text)
                finally:
                    _ma._nf_loads = saved
                if f1 != f2 or c1 != c2:
                    diff += 1
                    if diff == 1:
                        print(f"    解析差异: {p}")
                        print(f"      nodefile : {json.dumps(f1, ensure_ascii=False)[:160]}")
                        print(f"      fallback : {json.dumps(f2, ensure_ascii=False)[:160]}")
            if checked > 500:
                break
        ok &= _ok(diff == 0 and checked > 0,
                  f"自包含解析与 nodefile 逐字段一致（{checked} 文件，"
                  f"差异 {diff}）")

        print("== [5] fail-closed ==")
        try:
            md_conn.execute("UPDATE nodes SET access_count = 1")
            ok &= _ok(False, "写语句应拒绝")
        except NotImplementedError:
            ok &= _ok(True, "写语句拒绝（NotImplementedError）")
        try:
            md_conn.execute("SELECT id FROM edges")
            ok &= _ok(False, "非 nodes 表应拒绝")
        except NotImplementedError:
            ok &= _ok(True, "非 nodes 表拒绝（超文法）")
        try:
            md_conn.execute("SELECT no_such_col FROM nodes")
            ok &= _ok(False, "未知列应拒绝")
        except NotImplementedError:
            ok &= _ok(True, "未知列拒绝")
    finally:
        sq.close()
        md_conn.close()

    print(f"\n{'全部通过' if ok else '存在失败项'}（{_N_ASSERT} 断言）")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
