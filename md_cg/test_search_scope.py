# -*- coding: utf-8 -*-
"""test_search_scope —— 检索面的口径分层（P0-b / F 接口，2026-11-06）

判什么：
  D 组 · 流水降权（真检索，临时根）
    D1 同一段散文，work_log 与 text 都在库里：无时间线索的查询，语义卡排前
    D2 该流水的最终分 = 原分 × EXEMPT_PENALTY（用同内容两节点比，比值恰 0.6）
    D3 查询带时间线索（「昨天」）时**不降权**：两节点同分（差异 < 1e-9）
    D4 语义卡（text）在任何情况下不被降权（自身分数与无豁免节点一致）
  E 组 · 概念卡（consolidate 接口）
    E1 `_concept_payload(...)` 产出的正文本身六要素齐全（nodefile 判 complete）
    E2 落库那次 `cg.add` 带 `content_kind="text"`（源码级断言，避免再漂一次）

为什么这样判：降权必须「可被读数看见」而不是静默过滤；比 0.6 的比值能抓住
「乘子位被别的后处理改写」这类回归；时间线索不降权那条能抓住「把所有流水
一起压死、问今天做了什么也查不到」的过度修正。

负控：
  · 把 EXEMPT_PENALTY 改成 1.0 → D2 变红（降权没生效）
  · 把 _TEMPORAL_Q 换成不匹配正则 → D3 变红（时间查询也被降权）
"""
import io
import os
import sys
import tempfile

from . import ccg_scope, consolidate, nodefile, writepipe

N = 0
BAD = []

SEM = """# 功能名：路由器怎么设置才不丢包
# 生效条件：需要给无线路由器做稳定化配置时
# 子功能：给出信道与频段选择
# 执行：改 5GHz 信道、关 2.4G 的 40MHz
# 验证方式：实测 30 天掉包率
# 不适用条件：企业级 AP
正文：信道拥挤会导致丢包。
"""

# 同一句正文，作为「流水」落库：内容与语义卡高度重合，才能比较降权效果。
FLOW = ("mn_gw_0021d1d4aa9d 于 2026-11-05 03:30 落下的检索流水："
        "路由器怎么设置才不丢包 信道拥挤会导致丢包。\n")


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


def _add(cg, nid, content, layer, kind, tags=()):
    return writepipe.default_pipeline().execute(cg, {
        "node_id": nid, "content": content, "layer": layer,
        "tags": list(tags), "content_kind": kind,
        "importance": 0.5, "role": "assistant"})


def _scores(cg, q):
    rows, _meta = cg.search(q, k=8, judge=False)
    out = {}
    for entry, score, _qual in rows:
        out[entry.get("id") or entry.get("path")] = float(score)
    return out


def main():
    root = tempfile.mkdtemp(prefix="mdcg-scope-")
    cg = _cg(root)
    _add(cg, "kn_router_sem", SEM, "knowledge", "text")
    v = _add(cg, "ctx_router_flow", FLOW, "contextual", "work_log")
    ck("D0 流水卡写入被接受", bool(v.get("verdict", {}).get("ok", v.get("ok"))),
       str(v.get("verdict") or v)[:200])

    s = _scores(cg, "路由器怎么设置才不丢包")
    a = s.get("kn_router_sem", 0.0)
    b = s.get("ctx_router_flow", 0.0)
    ck("D1 语义卡排前", a > b and b > 0.0, "sem=%s flow=%s" % (a, b))
    ratio = (b / a) if a else 0.0
    from . import mdcg as _mdcg
    pen = float(getattr(_mdcg, "EXEMPT_PENALTY", 0.0))
    # 比值必须对**字面量 0.6**，不能对模块常量：对着常量判，常量被改成 1.0 时
    # 这条断言会跟着一起绿（第一版就这样漏了负控）。
    ck("D2 常量确为 0.6", abs(pen - 0.6) < 1e-9, "pen=%.3f" % pen)
    ck("D2 流水分 = 原分 × 0.6", abs(ratio - 0.6) < 0.02,
       "ratio=%.4f（b=%s a=%s）" % (ratio, b, a))

    s2 = _scores(cg, "昨天路由器怎么设置才不丢包")
    a2 = s2.get("kn_router_sem", 0.0)
    b2 = s2.get("ctx_router_flow", 0.0)
    ck("D3 时间线索查询不降权", abs(a2 - b2) < 1e-9 or b2 >= a2 * 0.99,
       "sem=%s flow=%s" % (a2, b2))

    _add(cg, "kn_plain2", "# 功能名：路由器信道与频段\n正文：信道拥挤会导致丢包。\n",
         "knowledge", "text")
    s3 = _scores(cg, "路由器怎么设置才不丢包")
    ck("D4 语义卡不受降权影响",
       abs(s3.get("kn_router_sem", 0.0) - a) < 1e-9,
       "chg %s -> %s" % (a, s3.get("kn_router_sem")))

    body = consolidate._concept_payload(["m1", "m2"], ["c1"], [])
    ck("E1 概念卡正文六要素齐全", nodefile.ccg_completeness(body)["complete"] is True,
       str(nodefile.ccg_completeness(body)))

    src = io.open(os.path.join(os.path.dirname(__file__), "consolidate.py"),
                  encoding="utf-8").read()
    seg = src[src.find("cg.add(cid, content"):]
    seg = seg[:400]
    ck("E2 概念卡落 kind=text", 'content_kind="text"' in seg, seg[:160].replace("\n", " "))

    print("\n%d 条断言 · 失败 %d" % (N, len(BAD)))
    if BAD:
        print("失败项：" + ", ".join(BAD))
    return 0 if not BAD else 1


if __name__ == "__main__":
    sys.exit(main())
