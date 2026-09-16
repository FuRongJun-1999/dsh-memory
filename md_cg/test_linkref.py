# -*- coding: utf-8 -*-
"""linkref（正文裸 id 引用 → reference 边）验收：R-L1b，2026-09-17。

验收口径：抽取语义（命中/去重保序/排除自身/白名单防幽灵边/真实前缀域全覆盖/
脏键与含中文 id 排除/id 紧邻汉字不漏抽/YAML 键名不误匹配）｜端到端建边与幂等｜
覆写后「边跟随新正文」｜负路由（REJECT/DEFER/gated 短路不建边）｜韧性
（append_edge 抛异常不阻断写入）｜opt-out｜源判据（self 层留痕与脏键不作源）｜
链权重 reference=0.50 且不入因果链默认集｜**读隔离两面**：密级面（known_ids 经
_readable 过滤，与库读面同口径）+ 密钥面（live_targets 实读校验，剔除密级够但
无 DEK 的死目标，免生悬空边）。
"""

import json
import os
import shutil
import sys
import tempfile
import traceback

from . import chain, linkref, writepipe
from .mdcos import MdCGSecure
from .security import Principal

_ok = 0
_bad = []
_seq = [0]


def _check(name, cond, detail=""):
    global _ok
    if cond:
        _ok += 1
        print("  ok   %s" % name)
    else:
        _bad.append("%s %s" % (name, detail))
        print("  FAIL %s %s" % (name, detail))


def _mk_cg(tmp, role="designer"):
    _seq[0] += 1
    root = os.path.join(tmp, "root_%02d_%s" % (_seq[0], role))
    p = Principal(tenant="default", actor="t_" + role, role=role,
                  can_write=(role != "guest"),
                  can_admin=(role == "designer"))
    return MdCGSecure(root, principal=p)


def _policy(tmp, required=("PASSED",), forbidden=("FORBIDDEN_WORD",)):
    path = os.path.join(tmp, "policy.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"forbidden": list(forbidden),
                   "required": list(required)}, f)
    os.environ["MDCG_POLICY_FILE"] = path
    return path


def _fm(cg, nid):
    got = cg._edge_node(nid)
    return got[0] if got else {}


def _ref_edges(cg, nid):
    fm = _fm(cg, nid)
    return [e for e in (fm.get("edges") or [])
            if isinstance(e, dict) and e.get("relation_type") == linkref.RELATION]


def main():
    tmp = tempfile.mkdtemp(prefix="linkref_")
    old_policy = os.environ.pop("MDCG_POLICY_FILE", None)
    try:
        _run(tmp)
    except Exception:
        traceback.print_exc()
        _bad.append("未捕获异常")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
        if old_policy is not None:
            os.environ["MDCG_POLICY_FILE"] = old_policy
        else:
            os.environ.pop("MDCG_POLICY_FILE", None)
    print("\nlinkref 验收：%d 通过%s" % (
        _ok, ("，%d 失败：%s" % (len(_bad), "; ".join(_bad))) if _bad else ""))
    return 1 if _bad else 0


def _run(tmp):
    policy = _policy(tmp)
    pipe = writepipe.install_default_gates(writepipe.WritePipeline())
    cg = _mk_cg(tmp)
    A, B, TGT = "mem_1789125080573", "concept_d8eee20f2f", "mem_tgt0001"

    # ---------- 1 纯函数：抽取语义 ----------
    txt = "见 %s 与 %s；再一次 %s；%s" % (A, B, A, A)
    got = linkref.extract_refs(txt, known={A, B})
    _check("裸id命中", got == [A, B], repr(got))
    _check("去重保序", got.count(A) == 1, repr(got))
    _check("排除自身", linkref.extract_refs(txt, known={A, B}, exclude=A) == [B])
    _check("白名单过滤未知id(防幽灵边)",
           linkref.extract_refs(txt + " 幽灵 mem_9999999999999", known={A, B})
           == [A, B])
    _check("known=None按形态放行", linkref.extract_refs(txt, known=None) == [A, B])
    _check("真实前缀域命中(kp/note/vpipe/arc)",
           linkref.extract_refs(
               "见 kp_GIL_1787752832598 与 note_abc123 与 vpipe_0001 与 arc_0001",
               known={"kp_GIL_1787752832598", "note_abc123", "vpipe_0001",
                      "arc_0001"})
           == ["kp_GIL_1787752832598", "note_abc123", "vpipe_0001", "arc_0001"])
    _check("非库内id被白名单拦截(rev/prop/sess)",
           linkref.extract_refs("rev_483f03ac3558_r1 prop_1a2b3c sess_abc",
                                known=set()) == [])
    _check("YAML式键名被白名单拦截",
           linkref.extract_refs("part_of: x derived_from: y relation_type: z",
                                known={A}) == [])
    _check("id紧邻汉字仍命中(非词边界误判)",
           linkref.extract_refs("见%s的说明" % A, known={A}) == [A])
    _check("形态近似但更长的id不误命中",
           linkref.extract_refs(A + "9", known={A}) == [])
    _check("形态判据放行规范id",
           linkref.is_linkable_id(A) and linkref.is_linkable_id("kp_GIL_1787"))
    _check("形态判据排除脏键(None/中文标题式/含中文混合id)",
           not linkref.is_linkable_id("None")
           and not linkref.is_linkable_id("README中英差距报告节（94.6vs52）")
           and not linkref.is_linkable_id("kp_GIL全局解_1787752832598"))
    _check("空文本", linkref.extract_refs("", known={A}) == [])

    # ---------- 2 边形态与链权重 ----------
    e = linkref.make_edge(A)
    _check("边形态", e["target"] == A and e["relation_type"] == "reference"
           and e["verified"] is False and "created_at" in e, repr(e))
    _check("边权重=0.50", chain.edge_weight(e) == 0.5, repr(chain.edge_weight(e)))
    _check("reference已登记权重表", chain.EDGE_WEIGHTS.get("reference") == 0.50)
    _check("reference不入因果链默认集",
           "reference" not in chain.CHAIN_TYPES_DEFAULT)
    _check("reference不入因果类型集", "reference" not in chain.CAUSAL_TYPES)

    # ---------- 2b 源节点层/形态判据（审计留痕与脏键不作源） ----------
    _check("self层不作源", linkref.is_linkable_source(A, "self") is False)
    _check("记忆本体层可作源",
           all(linkref.is_linkable_source(A, x)
               for x in ("knowledge", "contextual", "rejected", "", None)))
    _check("脏键id不作源", linkref.is_linkable_source("None", "knowledge") is False)
    _check("self层排除常量", linkref.SOURCE_EXCLUDE_LAYERS == ("self",))

    # ---------- 2c 白名单读隔离一致性（known_ids 与库读面同口径） ----------
    class _StubCG:
        def __init__(self, nodes, guard=None):
            self.index = {"nodes": nodes}
            if guard is not None:
                self._readable = guard
    _n = {A: {"s": "internal"}, B: {"s": "secret"}}
    _check("known_ids按读隔离过滤",
           linkref.known_ids(_StubCG(_n, lambda e: e["s"] == "internal"))
           == {A})
    _check("known_ids无读面时不过滤(非安全库MdCG)",
           linkref.known_ids(_StubCG(_n)) == {A, B})
    _check("known_ids读面抛异常则fail-closed",
           linkref.known_ids(_StubCG(_n, lambda e: 1 / 0)) == set())
    _check("known_ids无索引回退空集", linkref.known_ids(object()) == set())

    # ---------- 2d 目标侧第二道读隔离：密钥面（live_targets 实读校验） ----------
    # 背景（20260917 取证）：private/secret 正文是密文，解封需本身份 DEK；
    # 无 DEK 时 get 返回 None，但 _readable 只看索引密级字段 → 白名单会混入
    # 「密级够、密钥不够」的死目标（真实库 secret 下 459 条），建边即产生悬空边。
    class _StubReadCG:
        def __init__(self, ok, boom=()):
            self.calls = []
            self._ok = set(ok)
            self._boom = set(boom)

        def get(self, nid):
            self.calls.append(nid)
            if nid in self._boom:
                raise RuntimeError("locked")
            return {"id": nid} if nid in self._ok else None

    _s = _StubReadCG(ok={A}, boom={"mem_locked1"})
    _check("live_targets保留实读可得目标、剔除密钥隔离目标",
           linkref.live_targets(_s, [A, "mem_locked1", "mem_missing1"]) == [A],
           repr(_s.calls))
    _check("live_targets夹带抛异常目标fail-closed",
           linkref.live_targets(_s, ["mem_locked1"]) == [])
    _s2 = _StubReadCG(ok={A})
    _cache = {}
    linkref.live_targets(_s2, [A, A], cache=_cache)
    _check("live_targets缓存复用(同id只实读一次)",
           _s2.calls == [A] and _cache.get(A) is True, repr(_s2.calls))
    _check("live_targets空输入", linkref.live_targets(_s2, []) == [])

    # ---------- 3 端到端 ----------
    out_t = pipe.execute(cg, {"content_kind": "text", "content": "目标 PASSED",
                              "layer": "knowledge", "node_id": TGT})
    _check("目标节点落盘", out_t.get("committed") is True, repr(out_t))
    out_s = pipe.execute(cg, {"content_kind": "text",
                              "content": "PASSED 关联 %s 的说明" % TGT,
                              "layer": "knowledge", "node_id": "mem_src0001"})
    _check("源节点落盘", out_s.get("committed") is True, repr(out_s))
    refs = _ref_edges(cg, "mem_src0001")
    _check("端到端建reference边",
           len(refs) == 1 and refs[0]["target"] == TGT, repr(refs))

    pipe.execute(cg, {"content_kind": "text",
                      "content": "PASSED 关联 %s 的说明" % TGT,
                      "layer": "knowledge", "node_id": "mem_src0001"})
    _check("重复写入幂等", len(_ref_edges(cg, "mem_src0001")) == 1,
           repr(_ref_edges(cg, "mem_src0001")))

    pipe.execute(cg, {"content_kind": "text",
                      "content": "PASSED 关联 mem_ghost9999",
                      "layer": "knowledge", "node_id": "mem_src0002"})
    _check("未入库目标不建边", _ref_edges(cg, "mem_src0002") == [])

    pipe.execute(cg, {"content_kind": "text",
                      "content": "PASSED 本节点 mem_self0001 见 %s" % TGT,
                      "layer": "knowledge", "node_id": "mem_self0001"})
    _check("正文自引用被排除",
           [x["target"] for x in _ref_edges(cg, "mem_self0001")] == [TGT],
           repr(_ref_edges(cg, "mem_self0001")))

    pipe.execute(cg, {"content_kind": "text",
                      "content": "PASSED 关联 %s" % TGT, "linkref": False,
                      "layer": "knowledge", "node_id": "mem_src0003"})
    _check("linkref=False显式关闭", _ref_edges(cg, "mem_src0003") == [])

    pipe.execute(cg, {"content_kind": "text", "content": "目标2 PASSED",
                      "layer": "knowledge", "node_id": "mem_tgt0002"})
    pipe.execute(cg, {"content_kind": "text",
                      "content": "PASSED 现改关联 mem_tgt0002",
                      "layer": "knowledge", "node_id": "mem_src0001"})
    _check("覆写后边跟随新正文",
           [x["target"] for x in _ref_edges(cg, "mem_src0001")]
           == ["mem_tgt0002"], repr(_ref_edges(cg, "mem_src0001")))

    # ---------- 4 负路由 ----------
    out_r = pipe.execute(cg, {"content_kind": "text",
                              "content": "FORBIDDEN_WORD 关联 %s" % TGT,
                              "layer": "knowledge", "node_id": "mem_rej0001"})
    _check("REJECT路径不落盘不建边",
           out_r.get("committed") is False and _fm(cg, "mem_rej0001") == {},
           repr(out_r))

    os.environ.pop("MDCG_POLICY_FILE", None)
    out_d = pipe.execute(cg, {"content_kind": "text",
                              "content": "无规则可判 关联 %s" % TGT,
                              "layer": "knowledge", "node_id": "mem_def0001"})
    _check("DEFER路径不落盘不建边",
           out_d.get("moved_to") == "review_queue"
           and _fm(cg, "mem_def0001") == {}, repr(out_d))
    os.environ["MDCG_POLICY_FILE"] = policy

    out_g = pipe.execute(cg, {"content_kind": "text",
                              "content": "PASSED 关联 %s" % TGT, "gated": True,
                              "layer": "contextual", "node_id": "mem_gat0001"})
    _check("gated走替代执行路径(短路→after不执行)",
           "gate" in out_g, repr(out_g))

    # ---------- 5 韧性：建链失败不阻断写入 ----------
    p2 = writepipe.install_default_gates(writepipe.WritePipeline())
    cg2 = _mk_cg(tmp)
    p2.execute(cg2, {"content_kind": "text", "content": "目标 PASSED",
                     "layer": "knowledge", "node_id": "mem_f0"})
    orig = cg2.append_edge

    def _boom(*a, **k):
        raise RuntimeError("append_edge boom")

    cg2.append_edge = _boom
    try:
        out = p2.execute(cg2, {"content_kind": "text",
                               "content": "PASSED 关联 mem_f0",
                               "layer": "knowledge", "node_id": "mem_f1"})
        _check("建链失败不阻断写入", out.get("committed") is True, repr(out))
    except Exception as ex:  # noqa: BLE001
        _check("建链失败不阻断写入", False, "异常%r" % ex)
    finally:
        cg2.append_edge = orig

    # ---------- 5b 目标实读不出（密钥隔离）→ 不建边 ----------
    p3 = writepipe.install_default_gates(writepipe.WritePipeline())
    cg3 = _mk_cg(tmp)
    p3.execute(cg3, {"content_kind": "text", "content": "目标3 PASSED",
                     "layer": "knowledge", "node_id": "mem_k0"})
    g_orig = cg3.get

    def _locked(nid, *a, **k):
        return None if nid == "mem_k0" else g_orig(nid, *a, **k)

    cg3.get = _locked
    try:
        out = p3.execute(cg3, {"content_kind": "text",
                               "content": "PASSED 关联 mem_k0",
                               "layer": "knowledge", "node_id": "mem_k1"})
        _check("目标实读不出(密钥隔离)不建边——免生悬空边",
               out.get("committed") is True and _ref_edges(cg3, "mem_k1") == [],
               repr(_ref_edges(cg3, "mem_k1")))
    finally:
        cg3.get = g_orig

    # ---------- 6 边域幂等（append_edge 本体） ----------
    _check("append_edge自身幂等",
           cg.append_edge("mem_tgt0002", linkref.make_edge(TGT)) is True
           and cg.append_edge("mem_tgt0002", linkref.make_edge(TGT)) is False)


if __name__ == "__main__":
    sys.exit(main())
