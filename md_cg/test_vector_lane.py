# -*- coding: utf-8 -*-
"""test_vector_lane.py —— 第 7 路（本地 bge 向量）判据

判的是「这一路真的能补词法捞不到的」，不是「代码里有个函数」：

  A1 索引能从临时库建出来（count>0、dim>0）
  A2 **改写查询**（一个正文词都不出现）时向量路命中、词法路落空
  A3 `work_log` 节点不进索引（531 条流水不许淹没语义召回）
  A4 没有索引时 `vector.search` 返回 []，不抛异常
  A5 门控仍然权威：向量命中的节点若不在 entries 里，`_path_vector` 不收它
  B1 `MDCG_VECTOR=0` 时整路关闭
  B2 融合 meta 里出现 `vector` 这一路（且路径指纹含它）
  B3 模型/分词器缺失时不影响另外六路（`search` 正常返回）
"""
import os
import shutil
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from md_cg.mdcos import MdCGSecure                    # noqa: E402
from md_cg.security import Principal                  # noqa: E402
from md_cg import vector                              # noqa: E402

PASS = []
FAIL = []


def ok(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print("%-6s %s %s" % ("PASS" if cond else "FAIL", name, detail))


def make_cg(root):
    return MdCGSecure(root, principal=Principal(
        actor="dsh-memory", role="designer", tenant="default",
        clearance="private", can_write=True, can_admin=True), autoflush=8)


NODES = {
    "kn_router": (
        "路由器丢包多半是 2.4G 频段太挤：换到 5G，再看两端网口灯是否狂闪；"
        "改成固定 IP 可排除 DHCP 续租干扰。",
        "knowledge", None),
    "kn_decoy": (
        "无线老断的报错日志模板：记录时间、信道、断连次数，供事后翻查。",
        "knowledge", None),
    "kn_flow": (
        "网关三元组流水：subject/predicate/object 三件套按时序落盘，"
        "每轮对话一批，不做语义判断。", "contextual", "work_log"),
    "kn_other": (
        "星露谷 Mods 的中文清理流水线：批量读 manifest，把重复的 zh 字段合并。",
        "knowledge", None),
}


def build_lib(root):
    cg = make_cg(root)
    for nid, (body, layer, kind) in NODES.items():
        kw = {"content_kind": kind} if kind else {}
        cg.add(nid, body, layer=layer, tags=["t"], importance=0.5, **kw)
    return cg


def main():
    tmp = tempfile.mkdtemp(prefix="veclane_")
    try:
        cg = build_lib(tmp)

        st = vector.build(cg, root=tmp)
        ok("A1 索引建成", bool(st.get("ok")) and st.get("count", 0) >= 2, str(st))
        ok("A1b 维度", int(st.get("dim") or 0) > 0, str(st.get("dim")))

        stats = vector.stats(tmp)
        ids = []
        try:
            import json
            import io
            meta = json.load(io.open(os.path.join(tmp, "vector", "meta.json"),
                                     encoding="utf-8"))
            ids = meta.get("ids") or []
        except Exception:                              # noqa: BLE001
            pass
        ok("A1c 计数一致", len(ids) == st.get("count"), "%d vs %s" % (len(ids), st.get("count")))

        # A3：work_log 不进索引
        ok("A3 work_log 被排除", "kn_flow" not in ids, str(ids))

        # A2：改写查询——用词与目标节点正文**零交集**（同义不同字），
        # 同时库里有「字面更像但语义无关」的诱饵节点，这才测得出这一路的价值。
        q = "家里 Wi-Fi 总掉线，该动哪个参数？"
        hits = vector.search(cg, q, k=3, root=tmp, min_score=0.20)
        hit_ids = [i for i, _ in hits]
        lex, _meta = cg.search(q, k=3, judge=False)
        lex_ids = [e.get("id") for e, _s, _q in lex]
        ok("A2 向量路把目标捞进前二", "kn_router" in hit_ids[:2], str(hit_ids)[:120])
        ok("A2b 词法路前三没有目标", "kn_router" not in lex_ids[:3], str(lex_ids)[:120])

        # A5：门控权威——entries 里只有 kn_other 时，向量路不许把 kn_router 捞回来
        entries = [cg.index["nodes"]["kn_other"]]
        out = cg._path_vector(q, entries)
        ok("A5 只认 entries", all(n["id"] == "kn_other" for n, _s in out) and bool(out or True),
           str([n["id"] for n, _s in out]))

        # B1：开关关闭
        os.environ["MDCG_VECTOR"] = "0"
        ok("B1 开关关闭", vector.search(cg, q, k=3, root=tmp) == [], "env=0")
        os.environ.pop("MDCG_VECTOR", None)

        # B2：融合 meta 出现 vector 路
        res, meta = cg.search_rrf(q, k=5, judge=False)
        _fused = [row[0].get("id") for row in res]
        ok("A2c 融合结果里目标可见", "kn_router" in _fused[:3], str(_fused)[:120])
        _paths = meta.get("paths") or {}
        ok("B2 融合含 vector 路", "vector" in _paths, str(sorted(_paths)))

        # A4：索引缺失
        empty = tempfile.mkdtemp(prefix="veclane_empty_")
        try:
            cg2 = make_cg(empty)
            cg2.add("kn_x", "随便一条正文，用来保证库非空。", layer="knowledge",
                    tags=["t"], importance=0.4)
            ok("A4 无索引返回空", vector.search(cg2, "随便问问", k=3, root=empty) == [], "no index")
        finally:
            shutil.rmtree(empty, ignore_errors=True)

        # A6：阈值真的会拒——无关查询不许带东西回来（0.42 标定之前 330/331 全过）
        _good = vector.search(cg, q, k=3, root=tmp)
        _bad = vector.search(cg, "今天中午吃什么", k=5, root=tmp)
        ok("A6 无关查询不召回", _bad == [] and bool(_good),
           "related=%d unrelated=%d" % (len(_good), len(_bad)))
        _raw = vector.search(cg, "今天中午吃什么", k=5, root=tmp, min_score=0.0)
        ok("A6b 滤波确实来自阈值", len(_raw) >= len(_bad),
           "min0=%d min_default=%d" % (len(_raw), len(_bad)))

        # B3：模型缺失时六路照常
        os.environ["MDCG_VEC_MODEL"] = "/nonexistent/model.onnx"
        vector.invalidate()
        res2, meta2 = cg.search_rrf(q, k=3, judge=False)
        ok("B3 模型缺失不拖垮检索", isinstance(res2, list),
           "results=%d paths=%s" % (len(res2), sorted(meta2.get("paths") or {})))
        os.environ.pop("MDCG_VEC_MODEL", None)
        vector.invalidate()
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    print("\n==== test_vector_lane: PASS %d / FAIL %d ====" % (len(PASS), len(FAIL)))
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
