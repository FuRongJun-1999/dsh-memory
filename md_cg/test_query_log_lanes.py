# -*- coding: utf-8 -*-
"""test_query_log_lanes —— 查询日志的每路候选与路名族映射（2026-11-07）

判什么（D 组的前置条件）：
  A1 真检索确实写日志，行里有 `lanes`
  A2 `lanes[lane]` 三键齐（n / top / s），top ≤10、s ≤3
  A3 top 里的 id 都是库里真节点（不是 None / 不是路径）
  A4 每路分数按降序（`s` 单调不增）
  A5 `lane_family` 覆盖所有出现过的路名，且 `bm25→lexical`、`time_anchor→temporal`
  A6 旧键 `paths` 仍在（不破坏既有读数脚本）
  B1 `MDCG_QUERY_LOG=0` 时一行都不写
  B2 日志写不进去（root 指向不存在目录）时检索照常返回结果
  C1 快路径（`cg.search` 的 T2 直查）不写这种行——**如实**：日志只覆盖 RRF
     入口（`recall(use_rrf=True)`／`cg(op=read)`），小语料直查不入账。

为什么这样判：D（归一化融合）要用「每路给了哪些候选、分多高」判断
「这一路是不是被另一路盖住了」；只有数量时两者在日志里同形。A3 用「id 必须
在索引里」挡住把 `path` 当 id 写进去这类静默错位；B2 挡住「日志失败把检索
一起拖死」。
"""
import io
import json
import os
import sys
import tempfile

from . import writepipe

SEM = """# 功能名：路由器怎么设置才不丢包
# 生效条件：需要给无线路由器做稳定化配置时
# 子功能：给出信道与频段选择
# 执行：改 5GHz 信道、关 2.4G 的 40MHz
# 验证方式：实测 30 天掉包率
# 不适用条件：企业级 AP
正文：信道拥挤会导致丢包，路由器的信道与频段要一起调。
"""

N = 0
BAD = []


def ck(name, cond, detail=""):
    global N
    N += 1
    if cond:
        print("  ok   %s" % name)
    else:
        BAD.append(name)
        print("  FAIL %s  %s" % (name, detail))


def _cg(root):
    from .mdcos import MdCGSecure
    from .security import Principal
    return MdCGSecure(root, principal=Principal(
        actor="dsh-memory", role="designer", tenant="default",
        clearance="private", can_write=True, can_admin=True), autoflush=8)


def _add(cg, nid, content, layer="knowledge", kind="text"):
    return writepipe.default_pipeline().execute(cg, {
        "node_id": nid, "content": content, "layer": layer,
        "tags": [], "content_kind": kind, "importance": 0.5, "role": "assistant"})


def _lines(root):
    p = os.path.join(root, "_queries.jsonl")
    if not os.path.exists(p):
        return []
    return [ln for ln in io.open(p, encoding="utf-8").read().splitlines() if ln.strip()]


def main():
    root = tempfile.mkdtemp(prefix="mdcg-qlanes-")
    cg = _cg(root)
    for i in range(3):
        _add(cg, "kn_q%d" % i,
             SEM.replace("路由器怎么设置才不丢包", "路由器怎么设置才不丢包·第%d条" % i))

    # 生产读路径是 RRF（`cg(op=read)` 默认 bm25=True → search_rrf；recall 缺省
    # use_rrf=True）。`cg.search()` 走 T2_global_like 快路径**不写**本日志，
    # 这是刻意口径（见 C1）。
    cg.recall("路由器怎么设置才不丢包", budget_tokens=400, k=8, judge=False)
    lines = _lines(root)
    ck("A1 检索写了日志", len(lines) == 1, "lines=%d" % len(lines))
    if not lines:
        print("\n%d 条断言 · 失败 %d" % (N, len(BAD)))
        return 1
    rec = json.loads(lines[-1])
    ck("A1 行里有 lanes", isinstance(rec.get("lanes"), dict) and bool(rec["lanes"]),
       str(list((rec.get("lanes") or {}).keys()))[:120])

    lanes = rec.get("lanes") or {}
    shape_ok = all(isinstance(v, dict) and {"n", "top", "s"} <= set(v) for v in lanes.values())
    ck("A2 三键齐", shape_ok, json.dumps(lanes, ensure_ascii=False)[:220])
    caps = all(len(v.get("top") or []) <= 10 and len(v.get("s") or []) <= 3
               for v in lanes.values())
    ck("A2 截断上限（top<=10, s<=3）", caps, "max_top=%d" % max(len(v.get("top") or []) for v in lanes.values()))

    idx = set(cg.index["nodes"].keys())
    ids = [i for v in lanes.values() for i in (v.get("top") or [])]
    ck("A3 top 全在索引里", bool(ids) and all(i in idx for i in ids),
       "bad=%s" % [i for i in ids if i not in idx][:5])

    mono = True
    for v in lanes.values():
        s = v.get("s") or []
        mono = mono and all(s[i] >= s[i + 1] - 1e-9 for i in range(len(s) - 1))
    ck("A4 每路分数降序", mono, json.dumps({k: v.get("s") for k, v in lanes.items()})[:200])

    fam = rec.get("lane_family") or {}
    cover = all(name in fam for name in lanes)
    ck("A5 族映射覆盖所有路名", cover, "缺=%s" % [n for n in lanes if n not in fam])
    ck("A5 bm25→lexical、time_anchor→temporal",
       fam.get("bm25") == "lexical" and fam.get("time_anchor") == "temporal",
       json.dumps(fam, ensure_ascii=False)[:160])

    ck("A6 旧键 paths 仍在", isinstance(rec.get("paths"), dict) and bool(rec["paths"]),
       str(rec.get("paths"))[:120])

    n0 = len(_lines(root))
    os.environ["MDCG_QUERY_LOG"] = "0"
    try:
        cg.recall("路由器怎么设置才不丢包", budget_tokens=400, k=8, judge=False)
    finally:
        os.environ.pop("MDCG_QUERY_LOG", None)
    ck("B1 MDCG_QUERY_LOG=0 不写", len(_lines(root)) == n0, "%d→%d" % (n0, len(_lines(root))))

    # 日志不可写：把实例的 root 临时指向不存在目录（写日志会 FileNotFoundError，
    # 必须被 try/except 吞掉，检索结果照旧）。
    _real_root = cg.root
    cg.root = os.path.join(root, "no", "such", "dir")
    try:
        pack = cg.recall("路由器怎么设置才不丢包", budget_tokens=400, k=8, judge=False)
    except Exception as e:                                     # noqa: BLE001
        pack = {"err": repr(e)}
    finally:
        cg.root = _real_root
    ck("B2 日志不可写时检索不受影响",
       bool(pack.get("pack") or pack.get("recent") is not None) and "err" not in pack,
       str(pack.get("err"))[:140])

    n1 = len(_lines(root))
    try:
        cg.search("路由器怎么设置才不丢包", k=8, judge=False)
    except Exception:                                          # noqa: BLE001
        pass
    ck("C1 快路径（T2 直查）不写日志", len(_lines(root)) == n1,
       "%d→%d" % (n1, len(_lines(root))))

    print("\n%d 条断言 · 失败 %d" % (N, len(BAD)))
    if BAD:
        print("失败项：" + ", ".join(BAD))
    return 0 if not BAD else 1


if __name__ == "__main__":
    sys.exit(main())
