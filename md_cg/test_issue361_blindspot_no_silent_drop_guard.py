# -*- coding: utf-8 -*-
"""issue #361 守卫：gated 写入 BLINDSPOT 不再静默丢正文（P0 数据丢失）。

病灶（2026-10-15，dsh-memory #361）：`mdcg_remember gated=true`（插件缺省：
consistency 缺省 true / on_conflict 缺省 defer）带六要素内容时，空库上
consistency.check 恒判 BLINDSPOT（comparable==0——BLINDSPOT 的**唯一**赋值点
是 consistency.py `comparable == 0 and (pos or neg)`；`comparable` 只对声明了
条件的既有节点计数，四态路由是严格 if/elif 链，comparable>0 时 BLINDSPOT 结构
性不可达）⇒ mdcg.add 的 `v in ("REJECT","BLINDSPOT") and on_conflict=="defer"`
return None ⇒ mdcos.remember_gated 的 written-is-None 出口只改 verdict=DEFER
**不入队**：正文不在任何节点、不在 hippocampus/inbox.jsonl、任何文件，唯一
痕迹是 _consistency.jsonl 一行不含正文的 BLINDSPOT。且**自我维持**：没有
东西落盘 ⇒ comparable 恒 0 ⇒ 下一条也丢（实测《民法典》200 条六要素
gated 写入 200/200 丢失、库内 0 节点）。

处置（与 issue #26 在 writepipe 冲突闸已裁定的口径对齐——BLINDSPOT 恒放行、
REJECT 维持拦截）：mdcg.add 的 defer 拦截只认 REJECT；BLINDSPOT 按 record
放行，verdict 如实落 fm.consistency（返回体经 mdcos 透出 consistency 读数，
「放行原因可观测」）。

断言：
  G1 空库 gated 六要素写入：正文落盘 + BLINDSPOT 读数如实（节点 fm 与返回体
     双面可观测）——能红旧实现（原先 nodes=0、返回体 written=null 无去向）；
  G2 批量 20 条零丢失（互异夹具绕开限流/合并面）：20/20 落盘、无一条带
     「written=None 且 consistency.verdict=BLINDSPOT」的静默丢签名；弱夹具
     （近重复形态）与 consistency=false 对照**逐位等价**（nodes/落盘数一致）；
  G3 防过修：REJECT（自否定，neg 走入参——i26 E3 同款）仍被拦（ok=false/
     verdict=DEFER/written=None，正文不进任何 contextual/knowledge 节点）；
     on_conflict=record 放行语义不变；on_conflict=reject 抛错语义不变；
     consistency=false 直通零回归；
  G4 返回体字段诚实：BLINDSPOT 放行形态 verdict=ACCEPT ⟺ written=节点id ⟺
     ok=true 三者自洽且 consistency.verdict=BLINDSPOT；REJECT 拦截形态
     written=None ⟹ ok=false 且 verdict=DEFER（不声称写入）。

Run: python -X utf8 -m md_cg.test_issue361_blindspot_no_silent_drop_guard
"""
import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from md_cg.mdcos import MdCGSecure
from md_cg.mcp_server import call_tool
from md_cg.security import Principal
from md_cg import consistency

PASS = 0
FAIL = 0
FAILS = []


def check(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  OK   {name}")
    else:
        FAIL += 1
        FAILS.append(name)
        print(f"  FAIL {name}  {detail}")


def make_cg(prefix):
    root = tempfile.mkdtemp(prefix=prefix)
    return MdCGSecure(os.path.join(root, "graph"), principal=Principal(
        actor="t_i361", clearance="secret", can_write=True,
        role="designer", auth_mode="test"))


def six_weak(i):
    """近重复六要素卡（issue 原始形态：同尾句/低互异——会吃限流与合并面）。"""
    return "\n".join([
        "# 功能名：民法典记忆第%d条" % i,
        "# 生效条件：合同编第%d章适用场景" % (i % 8 + 1),
        "# 子功能：条文取值",
        "# 执行：第%d条内容要点：当事人应当按照约定全面履行自己的义务" % i,
        "# 验证方式：读取法条原文核对",
        "# 不适用条件：无",
    ])


_TOPICS = ["买卖合同", "赠与合同", "租赁合同", "承揽合同", "保管合同",
           "运输合同", "技术合同", "合伙协议", "担保物权", "抵押登记",
           "遗嘱继承", "法定继承", "侵权责任", "无因管理", "不当得利",
           "人格权保护", "肖像许可", "名誉恢复", "隐私边界", "数据权益"]


def six_strong(i):
    """互异六要素卡（绕开近重复合并面；importance_hint≥0.7 绕开限流）。"""
    t = _TOPICS[i - 1]
    return "\n".join([
        "# 功能名：%s规则记忆" % t,
        "# 生效条件：%s纠纷进入司法程序且当事人主张权利" % t,
        "# 子功能：条文取值",
        "# 执行：规则要点%d：处理%s纠纷应当先审查合同效力再确定责任归属，"
        "证据交换期限届满前可申请调查令，缺席审理不影响事实认定" % (i, t),
        "# 验证方式：读取法条原文核对",
        "# 不适用条件：无",
    ])


def node_count(cg):
    return len(((getattr(cg, "index", None) or {}).get("nodes") or {}))


def walk_texts(root):
    for dirpath, _dirs, files in os.walk(root):
        for f in files:
            p = os.path.join(dirpath, f)
            try:
                with open(p, "r", encoding="utf-8", errors="replace") as fh:
                    yield p, fh.read()
            except OSError:
                pass


def memory_body_hit(cg, root, phrase):
    """短语是否落进任何 contextual/knowledge 记忆节点（排除工单/台账文件）。"""
    for nid in ((getattr(cg, "index", None) or {}).get("nodes") or {}):
        node = (cg.get(nid) or {})
        if (node.get("frontmatter") or {}).get("layer") in (
                "contextual", "knowledge"):
            if phrase in (node.get("content") or ""):
                return True
    return False


def main():
    print("== G1 空库 gated 六要素写入：不再静默丢正文 ==")
    cg = make_cg("i361g1_")
    root = os.path.dirname(cg.root.rstrip("/\\")) if False else cg.root
    key1 = "第1条内容要点"
    res = call_tool(cg, "mdcg_remember", {"content": six_weak(1), "gated": True})
    cvd = res.get("consistency") or {}
    nid = res.get("node_id")
    node = (cg.get(nid) or {}) if nid else {}
    fm_cvd = ((node.get("frontmatter") or {}).get("consistency") or {})
    check("G1a 正文落盘（节点含关键句，能红旧实现：原先 nodes=0）",
          bool(res.get("written")) and key1 in (node.get("content") or ""),
          json.dumps({k: res.get(k) for k in ("ok", "verdict", "written")},
                     ensure_ascii=False, default=str))
    check("G1b 库内恰 1 节点", node_count(cg) == 1, str(node_count(cg)))
    check("G1c fm.consistency.verdict=BLINDSPOT（放行原因落盘可观测）",
          fm_cvd.get("verdict") == "BLINDSPOT", str(fm_cvd))
    check("G1d 返回体 consistency.verdict=BLINDSPOT（与 #26 writepipe 面同形）",
          cvd.get("verdict") == "BLINDSPOT", str(cvd)[:160])
    cons_p = os.path.join(cg.root, "_consistency.jsonl")
    check("G1e _consistency.jsonl 留 BLINDSPOT 台账行",
          os.path.exists(cons_p) and "BLINDSPOT" in open(
              cons_p, encoding="utf-8", errors="replace").read())
    cg.close()

    print("== G2 批量 20 条零丢失 ==")
    # 强夹具：互异内容 + importance_hint≥0.7（绕开限流 RATE_MAX=8/60s 与
    # 近重复合并面）——纯粹检验「BLINDSPOT 不再造成丢失」这一条轴。
    cg2 = make_cg("i361g2a_")
    silent_drops, landed = [], 0
    first_cvd = None
    for i in range(1, 21):
        r = call_tool(cg2, "mdcg_remember",
                      {"content": six_strong(i), "gated": True,
                       "importance_hint": 0.8})
        cv = (r.get("consistency") or {}).get("verdict")
        if i == 1:
            first_cvd = cv
        if r.get("written"):
            landed += 1
        else:
            # 未落盘必须可归因：BLINDSPOT+未落盘 = #361 的静默丢签名（禁止）
            silent_drops.append((i, r.get("verdict"), cv,
                                 bool(r.get("proposed"))))
    keys = ["规则要点%d" % i for i in range(1, 21)]
    hits = [any(k in t for _p, t in walk_texts(cg2.root)) for k in keys]
    check("G2a 强夹具 20/20 落盘（能红旧实现：原先 0/20、库内 0 节点）",
          landed == 20 and node_count(cg2) == 20,
          "landed=%d nodes=%d" % (landed, node_count(cg2)))
    check("G2b 正文 20/20 可检索（节点或台账文件命中）",
          sum(hits) == 20, "%d/20" % sum(hits))
    check("G2c 无「BLINDSPOT+未落盘」静默丢签名",
          not silent_drops, str(silent_drops[:3]))
    check("G2d 首条即 BLINDSPOT（本批确实从盲区态起步）",
          first_cvd == "BLINDSPOT", str(first_cvd))
    cg2.close()
    # 弱夹具（issue 原始近重复形态）：与 consistency=false 对照**逐位等价**
    # ——修后一致性轴不再改变写入结局；未落盘部分是限流（RATE_MAX=8）与
    # 合并面的既有语义（#296 另一条通道，「先别写」可重试/变更单随单），
    # 两条腿（开/关 consistency）读数一致即证明与 #361 无关。
    cg3 = make_cg("i361g2b_")
    for i in range(1, 21):
        call_tool(cg3, "mdcg_remember", {"content": six_weak(i), "gated": True})
    w_keys = ["第%d条内容要点" % i for i in range(1, 21)]
    w_hits = sum(1 for k in w_keys
                 if any(k in t for _p, t in walk_texts(cg3.root)))
    w_nodes = node_count(cg3)
    cg3.close()
    cg4 = make_cg("i361g2c_")
    for i in range(1, 21):
        call_tool(cg4, "mdcg_remember",
                  {"content": six_weak(i), "gated": True, "consistency": False})
    c_hits = sum(1 for k in w_keys
                 if any(k in t for _p, t in walk_texts(cg4.root)))
    c_nodes = node_count(cg4)
    cg4.close()
    check("G2e 弱夹具与 consistency=false 对照逐位等价（nodes 与落盘数）",
          (w_nodes, w_hits) == (c_nodes, c_hits) and w_nodes >= 1,
          "gated=(%d,%d) control=(%d,%d)" % (w_nodes, w_hits, c_nodes, c_hits))

    print("== G3 防过修：真冲突与既有语义不回归 ==")
    bad = ("# 功能名：矛盾写入\n# 生效条件：调试模式开启\n"
           "# 子功能：示例\n# 验证方式：观察输出\n"
           "x = 1  # debugmode\nprint(x)\n")
    cg5 = make_cg("i361g3a_")
    res5 = call_tool(cg5, "mdcg_remember",
                     {"content": bad, "gated": True,
                      "non_applicable_conditions": ["debugmode"]})
    check("G3a REJECT 仍被拦（ok=false / verdict=DEFER / written=None）",
          res5.get("ok") is False and res5.get("verdict") == "DEFER"
          and res5.get("written") is None,
          json.dumps({k: res5.get(k) for k in ("ok", "verdict", "written")},
                     ensure_ascii=False, default=str))
    check("G3b REJECT 正文不进任何 contextual/knowledge 记忆节点",
          not memory_body_hit(cg5, cg5.root, "print(x)"))
    cons5 = os.path.join(cg5.root, "_consistency.jsonl")
    check("G3c REJECT 台账留痕（_consistency.jsonl 有 REJECT 行，修前既有追溯面）",
          os.path.exists(cons5) and "REJECT" in open(
              cons5, encoding="utf-8", errors="replace").read())
    cg5.close()
    cg6 = make_cg("i361g3b_")
    res6 = call_tool(cg6, "mdcg_remember",
                     {"content": bad, "gated": True,
                      "non_applicable_conditions": ["debugmode"],
                      "on_conflict": "record"})
    check("G3d on_conflict=record 放行语义不变（REJECT 照写）",
          bool(res6.get("written")) and res6.get("verdict") == "ACCEPT",
          json.dumps({k: res6.get(k) for k in ("verdict", "written")},
                     ensure_ascii=False, default=str))
    cg6.close()
    cg7 = make_cg("i361g3c_")
    raised = False
    try:
        cg7.add("reject_raise_probe", bad, layer="contextual",
                consistency=True, on_conflict="reject",
                non_applicable_conditions=["debugmode"])
    except consistency.ConsistencyError:
        raised = True
    check("G3e on_conflict=reject 抛错语义不变（基类 add 契约）", raised)
    cg7.close()
    cg8 = make_cg("i361g3d_")
    res8 = call_tool(cg8, "mdcg_remember",
                     {"content": six_weak(1), "gated": True,
                      "consistency": False})
    node8 = (cg8.get(res8.get("node_id")) or {})
    check("G3f consistency=false 直通零回归（照写且无 consistency 读数）",
          bool(res8.get("written"))
          and "第1条内容要点" in (node8.get("content") or "")
          and "consistency" not in res8,
          json.dumps({k: res8.get(k) for k in ("verdict", "written")},
                     ensure_ascii=False, default=str))
    cg8.close()

    print("== G4 返回体字段诚实 ==")
    cg9 = make_cg("i361g4a_")
    res9 = call_tool(cg9, "mdcg_remember",
                     {"content": six_weak(1), "gated": True})
    cvd9 = res9.get("consistency") or {}
    check("G4a BLINDSPOT 放行形态自洽：verdict=ACCEPT ⟺ written=节点id ⟺ ok=true",
          res9.get("verdict") == "ACCEPT"
          and res9.get("written") == res9.get("node_id")
          and res9.get("ok") is True,
          json.dumps({k: res9.get(k) for k in ("ok", "verdict", "written",
                                               "node_id")},
                     ensure_ascii=False, default=str))
    check("G4b 放行原因可观测：consistency.verdict=BLINDSPOT 且 reason 非空",
          cvd9.get("verdict") == "BLINDSPOT" and bool(cvd9.get("reason")),
          str(cvd9)[:160])
    node9 = (cg9.get(res9.get("node_id")) or {})
    check("G4c 节点 fm 与返回体读数一致（同一判定，两处同源）",
          ((node9.get("frontmatter") or {}).get("consistency") or {})
          .get("verdict") == cvd9.get("verdict"))
    check("G4d REJECT 拦截形态自洽：written=None ⟹ ok=false 且不声称 ACCEPT",
          res5.get("written") is None and res5.get("ok") is False
          and res5.get("verdict") != "ACCEPT")
    cg9.close()

    print()
    if FAILS:
        print(f"FAILED: {len(FAILS)} 项 → {', '.join(FAILS)}")
        return 1
    print(f"ALL OK: {PASS} 项（issue #361 gated BLINDSPOT 不静默丢正文守卫全绿）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
