"""可验证记忆单元（trust）验收：状态机 / 依赖图 / 双时间轴 / 失效传播 / 闸门 / 输出协议。

运行：python -m md_cg.test_trust   （或 python md_cg/test_trust.py）
范式：无第三方依赖的直接运行脚本（assert + 计数 + 非零退出），对齐 md_cg/test_*.py。

覆盖面（每个断言都在验「语义」而非「实现细节」）：
  ① 纯函数裁决：can_transition / check / require_transition
  ② as_deps 解析与 parse_time 容错
  ③ validity 双时间轴四态
  ④ state_of 缺省语义 + stamp 幂等
  ⑤ set_state 端到端（负路由 / 幂等 / 审计留痕 / 保护节点）
  ⑥ cg.add 覆写继承（全量重建 fm 不丢验证态与依赖）
  ⑦ 依赖反查索引 + 缓存失效
  ⑧ 一跳同步传播 mark_dependents（预演 / 落盘 / 幂等）
  ⑨ 多跳异步 propagate（BFS 可达 / 默认预演）
  ⑩ 写入闸门 E050 / E051 / 哨兵与自述豁免（真源 nodefile.declares_dependency；
     收窄裁定 b：仅 `@<节点 id>` 显式引用算依赖声明，自然语言自述不算）
  ⑪ 输出协议 statushdr（四态符号 / 开关）
  ⑫ 巡检 patrol 只读 + catalog 自描述
"""
import json
import os
import shutil
import sys
import tempfile

try:
    from . import trust, statushdr, nodefile, writepipe
    from .mdcg import MdCG
except ImportError:                                  # 直接脚本运行
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from md_cg import trust, statushdr, nodefile, writepipe
    from md_cg.mdcg import MdCG

PASS = 0
FAIL = []


def ok(cond, label):
    global PASS
    if cond:
        PASS += 1
    else:
        FAIL.append(label)
        print("  FAIL: " + label)


def eq(got, want, label):
    ok(got == want, "%s（got=%r want=%r）" % (label, got, want))


def phase(name):
    print("--- " + name)


A, B, C, D = ("mem_1789810000001", "mem_1789810000002",
              "mem_1789810000003", "mem_1789810000004")


def ccg(node, deps=None, **kw):
    """构造一条 CCG 契约正文（六要素齐；子功能按 deps 给出，**显式 @ 引用形态**）。

    注意：跨节点依赖的声明形态是 `@<节点 id>`（收窄裁定 b，2026-09-19）——
    自然语言自述子功能不构成依赖声明，故此处必须带 `@`，否则本文件的闸门断言
    测的就不是依赖链路了。
    """
    sub = ("依赖 " + "、".join("@" + d for d in deps)) if deps else "无"
    return ("# 功能名：%s\n# 生效条件：无条件\n# 子功能：%s\n# 执行：无\n"
            "# 验证方式：test\n# 不适用条件：无\n\n正文。" % (node, sub))


def main():
    tmp = tempfile.mkdtemp(prefix="mdcg_test_trust_")
    cg = MdCG(root=os.path.join(tmp, "kg"))

    # ---------------------------------------------------------------- ① 纯函数裁决
    phase("① 裁决")
    ok(trust.can_transition("unverified", "verified"), "unverified→verified 合法")
    ok(trust.can_transition("verified", "doubted"), "verified→doubted 合法")
    ok(trust.can_transition("unverified", "doubted"), "unverified→doubted 合法（负证据）")
    ok(not trust.can_transition("verified", "unverified"), "verified→unverified 拒绝（回落）")
    ok(not trust.can_transition("doubted", "expired"), "doubted→expired 拒绝（跳级）")
    ok(not trust.can_transition("unverified", "nope"), "未知状态拒绝")
    eq(trust.check("verified", "verified")[1], "noop", "同状态查得 noop")
    eq(trust.check("verified", "unverified")[1], "illegal_transition", "非法迁移码")
    ok(trust.check("verified", "unverified", protected=True, override=False)[0] is False,
       "受保护节点拒绝降级")
    ok(trust.check("unverified", "verified", protected=True, override=False)[0] is True,
       "受保护节点允许升级")
    ok(trust.check("verified", "doubted", protected=True, override=True)[0] is True,
       "override 放行合法降级（verified→doubted）")
    ok(trust.check("verified", "unverified", protected=True, override=True)[0] is False,
       "override 不豁免非法迁移（合法性优先于保护）")
    raised = False
    try:
        trust.require_transition("verified", "unverified")
    except trust.TrustError:
        raised = True
    ok(raised, "require_transition 非法即抛 TrustError")
    ok(trust.is_downgrade("verified", "doubted"), "verified→doubted 是降级")

    # ---------------------------------------------------------------- ② 解析容错
    phase("② 解析")
    eq(trust.as_deps(["b", "a", "b"]), ["a", "b"], "as_deps 列表去重排序")
    eq(trust.as_deps("x"), ["x"], "as_deps 单串")
    eq(trust.as_deps(None), [], "as_deps None")
    eq(trust.as_deps([None, ""]), [], "as_deps 过滤空值")
    eq(trust.as_deps("a, b"), ["a", "b"], "as_deps 逗号串")
    ok(trust.parse_time("2020-01-01") is not None, "parse_time 日期串")
    ok(trust.parse_time(None) is None, "parse_time None")
    ok(trust.parse_time(1700000000.0) == 1700000000.0, "parse_time 数字直通")
    ok(trust.parse_time("不是时间") is None, "parse_time 非法容错")

    # ---------------------------------------------------------------- ③ 双时间轴
    phase("③ 时间轴")
    eq(trust.validity({"valid_from": "2020-01-01", "valid_until": "2030-01-01"})[0],
       "active", "区间内=active")
    eq(trust.validity({"valid_from": "2099-01-01"})[0], "not_yet", "未来=not_yet")
    eq(trust.validity({"valid_until": "2001-01-01"})[0], "expired", "过去=expired")
    eq(trust.validity({})[0], "unknown", "无时间轴=unknown（不受限，非 active）")
    eq(trust.validity(None)[0], "unknown", "非 dict 亦 unknown（不猜测）")
    # 2026-09-19 阶段一：规范键优先 + 别名回落 + 信念时间（第三类语义）物理隔离
    eq(trust.validity({"effective_from": "2099-01-01"})[0], "not_yet",
       "规范键起点生效")
    eq(trust.validity({"effective_from": "2099-01-01",
                       "valid_from": "2020-01-01"})[0], "not_yet",
       "规范键优先于历史键")
    eq(trust.validity({"effective_until": "坏值",
                       "valid_until": "2001-01-01"})[0], "expired",
       "规范键不可解析 → 继续回落别名（不猜测定案）")
    eq(trust.validity({"effective_until": "2001-01-01"})[0], "expired",
       "规范键终点生效")
    eq(trust.validity({"believed_at": "2001-01-01"})[0], "unknown",
       "信念时间不参与时效判定（第三类语义）")
    ok(trust.believed_at({"believed_at": "2020-01-01"}) is not None
       and trust.believed_at({}) is None, "believed_at 读取器（epoch/None）")

    # ---------------------------------------------------------------- ④ 缺省与幂等
    phase("④ 缺省/幂等")
    eq(trust.state_of({}), "unverified", "缺字段按 unverified")
    eq(trust.state_of(None), "unverified", "None 按 unverified")
    fm = {}
    r1 = trust.stamp(fm, "verified", reason="t", actor="t")
    eq(r1[1], "ok", "stamp 首次迁移 code=ok")
    eq(trust.state_of(fm), "verified", "stamp 落字段")
    before = json.dumps(fm, sort_keys=True, default=str)
    r2 = trust.stamp(fm, "verified", reason="t", actor="t")
    eq(json.dumps(fm, sort_keys=True, default=str), before, "同状态 stamp 不重复写")
    eq(r2[1], "noop", "同状态 stamp code=noop（幂等不写盘）")

    # ---------------------------------------------------------------- ⑤ set_state 端到端
    phase("⑤ set_state")
    missing = trust.set_state(cg, "mem_not_exist", "verified")
    ok(missing.get("ok") is False and missing.get("error") == "node_not_found",
       "不存在节点负路由 node_not_found")
    cg.add(A, ccg("上游"), layer="knowledge", tags=["t1"])
    r = cg.set_verification(A, "verified", reason="首次", actor="tester",
                            evidence="ev-1", method="test")
    ok(r.get("ok") and r.get("changed"), "set_verification verified 成功")
    eq(trust.state_of((cg.get(A) or {}).get("frontmatter")), "verified",
       "fm 落 verification_state")
    eq((cg.index["nodes"][A] or {}).get("verification_state"), "verified",
       "索引快照同步（免读文件）")
    r2 = cg.set_verification(A, "verified", reason="重复", actor="tester")
    ok(r2.get("ok") and r2.get("changed") is False, "幂等：同状态 changed=False")
    led = trust.load_ledger(cg, node_id=A)
    ok(len(led) >= 1, "审计台账留痕")
    ok(all("to" in x for x in led), "台账含 to 字段")
    bad = cg.set_verification(A, "unverified", reason="回落", actor="tester")
    ok(bad.get("ok") is False, "非法迁移负路由不抛")

    # ---------------------------------------------------------------- ⑥ 覆写继承
    phase("⑥ 覆写继承")
    cg.add(B, ccg("下游", [A]), layer="knowledge", depends_on=[A],
           valid_from="2020-01-01", valid_until="2030-01-01")
    cg.set_verification(B, "verified", reason="t", actor="t")
    cg.add(B, ccg("下游 v2", [A]), layer="knowledge", depends_on=[A])
    fmb = (cg.get(B) or {}).get("frontmatter") or {}
    eq(trust.state_of(fmb), "verified", "覆写后验证态继承（防静默打回）")
    eq(fmb.get("depends_on"), [A], "覆写后依赖继承")
    eq(fmb.get("valid_from"), "2020-01-01", "覆写后时间轴继承")
    # 阶段一：规范键与信念时间的覆写继承（同 lifecycle/verification 的坑）
    cg.add(B, ccg("下游 v3", [A]), layer="knowledge", depends_on=[A],
           effective_from="2021-01-01", effective_until="2031-01-01",
           believed_at="2022-01-01")
    fmb3 = (cg.get(B) or {}).get("frontmatter") or {}
    eq(fmb3.get("effective_from"), "2021-01-01", "新规范参数落规范键")
    eq("valid_from" in fmb3, False, "落规范键时剔同族历史键（禁同族双写歧义）")
    eq(fmb3.get("believed_at"), "2022-01-01", "信念时间写入落 believed_at")
    cg.add(B, ccg("下游 v4", [A]), layer="knowledge", depends_on=[A])
    fmb4 = (cg.get(B) or {}).get("frontmatter") or {}
    eq(fmb4.get("effective_from"), "2021-01-01", "覆写后规范起点继承")
    eq(fmb4.get("effective_until"), "2031-01-01", "覆写后规范终点继承")
    eq(fmb4.get("believed_at"), "2022-01-01", "覆写后信念时间继承")

    # ---------------------------------------------------------------- ⑦ 反查索引
    phase("⑦ 反查索引")
    idx = trust.dependents_index(cg)
    ok(B in idx.get(A, []), "反查：谁依赖 A")
    eq(trust.deps_of(cg, B), [A], "正查：B 依赖谁")
    cg.add(D, ccg("新下游", [A]), layer="knowledge", depends_on=[A])
    trust.invalidate_cache(cg)
    ok(D in trust.dependents_index(cg).get(A, []), "写后缓存失效可重建")

    # ---------------------------------------------------------------- ⑧ 一跳传播
    phase("⑧ 一跳同步传播")
    dry = trust.mark_dependents(cg, A, reason="预演", apply=False)
    ok(dry.get("dry_run") and len(dry.get("dependents") or []) >= 2,
       "预演列出全部下游且不改盘")
    eq(dry.get("dependents"), sorted(dry.get("dependents") or []), "下游有序输出")
    ok(trust.state_of((cg.get(B) or {}).get("frontmatter")) == "verified",
       "预演未改盘（B 仍 verified）")
    wet = trust.mark_dependents(cg, A, reason="上游变动", actor="tester", trigger="t")
    ok(wet.get("changed") >= 2, "落盘：下游全部标存疑")
    eq(trust.state_of((cg.get(B) or {}).get("frontmatter")), "doubted", "B 已 doubted")
    eq(trust.state_of((cg.get(D) or {}).get("frontmatter")), "doubted", "D 已 doubted")
    again = trust.mark_dependents(cg, A, reason="重复", actor="tester")
    eq(again.get("changed"), 0, "重复传播幂等（changed=0）")
    none_dep = trust.mark_dependents(cg, C, reason="无下游")
    eq(none_dep.get("changed"), 0, "无下游不报错")

    # ---------------------------------------------------------------- ⑨ 多跳传播
    phase("⑨ 多跳异步传播")
    cg.add(C, ccg("中继", [D]), layer="knowledge", depends_on=[D])
    cg.set_verification(D, "verified", reason="t", actor="t")
    cg.set_verification(C, "verified", reason="t", actor="t")
    cg.set_verification(A, "expired", reason="时间到", actor="tester")
    dry2 = trust.propagate(cg)
    ok(dry2.get("dry_run"), "propagate 默认预演")
    ok(dry2.get("reachable", 0) >= 2, "预演可达多跳下游")
    wet2 = trust.propagate(cg, apply=True, actor="tester")
    ok(wet2.get("dry_run") is False, "apply=True 落盘")
    eq(trust.state_of((cg.get(B) or {}).get("frontmatter")), "doubted",
       "一跳下游 doubted")
    eq(trust.state_of((cg.get(C) or {}).get("frontmatter")), "doubted",
       "二跳下游 doubted（BFS 可达）")

    # ---------------------------------------------------------------- ⑩ 写入闸门
    phase("⑩ 写入闸门")
    ok(nodefile.declares_dependency(ccg("x", [A])), "显式 @ 引用判为 True")
    ok(not nodefile.declares_dependency(ccg("x")), "「无」哨兵判为 False")
    ok(not nodefile.declares_dependency("# 功能名：x\n\n正文"), "无该行判为 False")
    ok(not nodefile.declares_dependency("# 子功能：无（不依赖其他单元）"),
       "哨兵带括号说明仍为 False")
    # 收窄裁定 b（2026-09-19）：区分「自述子功能」与「跨节点依赖」——只有显式
    # `@<节点 id>` 引用才构成依赖声明；自然语言自述不算。否则 CCG 编译产物（六要素
    # 必含「子功能」行）落库后会被 E050 永久锁死（test_ccgc V16f 即该死锁的实证）。
    ok(not nodefile.is_dep_sentinel("无法确定依赖范围"),
       "「无法确定」不得误判为哨兵")
    ok(not nodefile.declares_dependency("# 子功能：无法确定依赖范围"),
       "自然语言自述不算依赖声明（收窄 b）")
    ok(not nodefile.declares_dependency(
        "# 子功能：按扩展名把文件路由到对应摄取器"),
       "CCG 编译产物形态的自述子功能不构成依赖声明（V16f 死锁根因）")
    ok(not nodefile.declares_dependency("# 子功能：联系 user@example.com"),
       "邮箱形态的 @ 不误判为引用（@ 左侧为标识符字符）")
    ok(not nodefile.declares_dependency("# 子功能：@所有人 知悉"),
       "中文 @ 不误判为引用（id 须以 [A-Za-z0-9_] 起头）")
    eq(nodefile.dep_refs("依赖 @mem_a、@code_b 与 @mem_a（回指 @mem_a）"),
       ["mem_a", "code_b"], "多引用去重保序提取")
    eq(nodefile.dep_refs("@code_3552109b6163"), ["code_3552109b6163"],
       "行首 @ 命中（左侧非标识符字符即可）")
    eq(nodefile.dep_refs("无"), [], "哨兵值提取为空列表")
    g1 = writepipe._gate_deps({"cg": cg, "nid": "mem_x1",
                               "a": {"content": ccg("x", [A]),
                                     "depends_on": [A]}, "verdict": {}})
    ok(g1 is None, "声明且目标可解析→放行")
    g2 = writepipe._gate_deps({"cg": cg, "nid": "mem_x2",
                               "a": {"content": ccg("x", [A]),
                                     "depends_on": A}, "verdict": {}})
    ok(g2 is None, "单值形态同样放行（as_deps 容错）")
    g2b = writepipe._gate_deps({"cg": cg, "nid": "mem_x2b",
                                "a": {"content": ccg("x", [A]),
                                      "depends_on": "%s, mem_ghost2" % A},
                                "verdict": {}})
    eq((g2b or {}).get("error"), "E051", "逗号串逐项解析（含悬空即拒）")
    g3 = writepipe._gate_deps({"cg": cg, "nid": "mem_x3",
                               "a": {"content": "# 功能名：x\n# 子功能：依赖 @mem_ghost\n"},
                               "verdict": {}})
    eq((g3 or {}).get("error"), "E050", "显式 @ 声明却无字段→E050 硬拒")
    ok((g3 or {}).get("committed") is False, "硬拒体 committed=False")
    g3b = writepipe._gate_deps({"cg": cg, "nid": "mem_x3b",
                                "a": {"content": "# 功能名：x\n# 子功能：依赖某物\n"},
                                "verdict": {}})
    ok(g3b is None, "自然语言自述子功能不触发闸门（收窄 b 的行为面）")
    g4 = writepipe._gate_deps({"cg": cg, "nid": "mem_x4",
                               "a": {"content": ccg("x", ["mem_ghost"]),
                                     "depends_on": ["mem_ghost"]}, "verdict": {}})
    eq((g4 or {}).get("error"), "E051", "依赖悬空→E051 硬拒")
    eq((g4 or {}).get("missing"), ["mem_ghost"], "E051 回带缺失目标")
    g5 = writepipe._gate_deps({"cg": cg, "nid": "mem_x5",
                               "a": {"content": ccg("x")}, "verdict": {}})
    ok(g5 is None, "哨兵值不触发闸门")
    names = writepipe.default_pipeline().names()
    ok("deps" in str(names) and "trust" in str(names), "闸与观察者已注册默认链")

    # ---------------------------------------------------------------- ⑪ 输出协议
    phase("⑪ 输出协议")
    head_b = statushdr.render(cg, B)
    ok(bool(head_b), "doubted 节点有状态头")
    ok(statushdr.MARK_DOUBTED in head_b, "状态头含存疑符号")
    head_a = statushdr.render(cg, A)
    ok(statushdr.MARK_ABNORMAL in head_a or statushdr.MARK_EXPIRED in head_a
       or bool(head_a), "异常/过期节点有状态头")
    ok(isinstance(statushdr.attach_heads(cg, {"node_id": B}), dict), "attach_heads 返回 dict")
    ok(statushdr.enabled(), "状态头默认开启")

    # ---------------------------------------------------------------- ⑫ 巡检与自描述
    phase("⑫ 巡检/自描述")
    rep = trust.patrol(cg)
    ok(rep.get("readonly") is True, "巡检只读标记")
    ok(rep.get("nodes", 0) >= 4, "巡检统计节点数")
    ok(rep.get("doubted_count", 0) >= 2, "巡检统计存疑积压")
    snap = trust.state_of((cg.get(B) or {}).get("frontmatter"))
    trust.patrol(cg)
    eq(trust.state_of((cg.get(B) or {}).get("frontmatter")), snap, "巡检不改状态")
    cat = trust.catalog(cg.root)
    for key in ("layer", "question", "states", "state_field", "deps_field",
                "time_fields", "ledger", "discipline"):
        ok(key in cat, "catalog 含键 " + key)
    ok("unverified" in cat["states"] and "doubted" in cat["states"], "catalog 状态枚举")
    s = trust.summary(cg)
    ok(isinstance(s, dict) and "doubted" in s, "summary 轻量摘要")
    de = trust.describe(cg, B)
    ok(de.get("ok") and de.get("depends_on") == [A], "describe 单节点全貌")
    ok(de.get("depended_by") is not None, "describe 含反查")

    # ---------------------------------------------------------------- ⑬ MCP 面接线
    phase("⑬ MCP 面：status op / 状态头 / 写闸硬拒")
    from md_cg import mcp_server as MS
    st = MS._cg_call(cg, {"op": "status", "node_id": A})
    eq(st.get("ok"), True, "op=status 单节点返回 ok")
    eq(st.get("state") or st.get("verification_state"), "expired", "status 透出验证态")
    ok(bool(st.get("status_head")), "status 带状态头")
    ok(isinstance(st.get("ledger"), list), "status 带履历台账")
    ok("depended_by" in st or "dependents" in st, "status 带下游反查")
    sm = MS._cg_call(cg, {"op": "status"})
    ok(isinstance(sm.get("summary"), dict), "op=status 摘要形态返回 summary")
    ok("status_head" in sm or "status_heads" in sm, "摘要形态亦挂状态头")
    sl = MS._cg_call(cg, {"op": "status", "action": "ledger"})
    ok(isinstance(sl.get("rows"), list), "action=ledger 读台账")

    # 写闸硬拒（MCP 端到端）：正文声明依赖却无可解析目标 → E050 / 悬空 → E051
    r50 = MS._cg_call(cg, {"op": "write", "content": ccg("闸门缺声明", [A]),
                           "content_kind": "text", "layer": "knowledge"})
    eq((r50 or {}).get("error"), "E050", "写闸硬拒 E050（声明依赖却无 depends_on）")
    r51 = MS._cg_call(cg, {"op": "write", "content": ccg("闸门悬空", ["mem_ghost_zz"]),
                           "content_kind": "text", "layer": "knowledge",
                           "depends_on": ["mem_ghost_zz"]})
    eq((r51 or {}).get("error"), "E051", "写闸硬拒 E051（依赖目标悬空）")
    ok(not (cg.get("mem_ghost_zz") or {}), "悬空目标未落盘（闸门真拒非事后回滚）")

    shutil.rmtree(tmp, ignore_errors=True)
    print("\nPASS=%d FAIL=%d" % (PASS, len(FAIL)))
    if FAIL:
        for f in FAIL:
            print("  - " + f)
        sys.exit(1)


main()
