# -*- coding: utf-8 -*-
"""写入路径拦截器链（Pi 钩子化机制移植，交接文档 §3⑥「闸门即扩展」）。

pi 机制（packages/coding-agent/docs/extensions.md）：全生命周期事件总线，
闸门/路径保护/审批全是以扩展形态叠加的，核心没有硬编码策略。灵枢对应：
write 的六道闸（audit 校验 / consistency 冲突 / review 审核 / gated 主动遗忘
/ writelimit 限流 / 权限）的次序与启停原先硬编码在 mcp_server._cg_dispatch
的 if/else 流程里，加一道闸要改核心文件。本模块把它重构为显式拦截器链：

- **before 链**：拦截器按注册序执行。返回 None = 放行（链继续）；
  返回 dict = 终态响应（短路——不落盘，或该拦截器已代为落盘/入队）。
- **after 链**：落盘成功后依次执行（观测者；返回值忽略；异常不吞——
  写入已成功，钩子故障必须暴露而非静默）。
- **ctx 为可变 dict**：a=原始入参 / cg=实例 / nid=节点 id / verdict=校验闸
  裁决 / cvd=冲突闸裁决。拦截器改写 ctx["a"]["content"] 等字段即实现
  REWRITE（改写后传给后续链与执行器）。
- **链尾执行器（_executor）是常驻环节**，不在注册表中、不提供卸载 API；
  它调 cg.add 落盘，而角色/层权限校验（require_layer_write）在
  MdCGSecure.add **库层内部**——是落盘必经之路，结构上不可被任何拦截器
  绕过（反面清单：不学 pi 的全权信任，信任必须结构强制）。

默认链（install_default_gates，与重构前 _cg_dispatch write 分支行为逐字
节一致）：audit → consistency → gated → _executor。

验收口径（交接文档 §3⑥）：全部既有写入测试零改动通过；新增/移除一个
拦截器不改核心文件（register_before / unregister_before 即插即拔）。

**③ 两段式提交（2026-09-16 叠加）**：链尾执行器与 gated 闸（两条**真实落盘**
路径）各自在执行落盘前调 `twophase.begin` 落 intent、落盘后调 `twophase.commit`
记 outcome；崩溃在两者之间时由 `twophase.reconcile` 据正文指纹补账/标记。
边界（如实）：`_gate_audit` 的 REJECT（写负记忆）与各闸的 propose（**未落盘**，
仅入审核队列）不在两段式覆盖面内——前者是短小负记录、后者本就没有落盘动作。

**④ 写提交边界（2026-09-16 叠加）**：`execute` 的两条出口（before 链短路 /
链尾执行器 + after 链之后）统一调 `_commit_visibility`——把内存脏索引
`flush()` 到分片日志，使本次写入对**其他进程**立即可见。这是第16条「写入后
读回确认」的跨进程前置条件（server 级 `autoflush=1` 是同一问题的兜底，
覆盖不经本链的写入路径）。根因取证见 `_commit_visibility` 文档串。
"""

import time

from . import twophase, trust

__all__ = ["WritePipeline", "default_pipeline"]


# 生效条件：调用即对 cg 执行 flush()（无脏数据时为 no-op），且仅当该调用抛异常而 out 是 dict 时在 out 写入 "flush_error"，异常本身不外抛；
def _commit_visibility(cg, out):
    """写提交边界（2026-09-16）：把内存脏索引落分片日志，使本次写入对其他进程立即可见。

    根因（第4条取证）：写入只经 `_stage` 入内存 + `_dirty`，须达 `autoflush`
    （默认 64）或 `close()` 才 `flush()` 落 `_index_log/`；MCP server 常驻、
    不 close，故单条写入在阈值前**对其他进程不可见**——`_load_index` 读的是
    「快照 `_index.json` + 分片日志重放」，而快照只在 compact/rebuild 时重写。
    症状即第16条「写入后读回确认」在跨进程读面上系统性误报（写入返回
    committed=true，读回却检索不到）。

    边界（如实）：无脏数据时 `flush()` 是 no-op，成本只在「确有落盘」时产生；
    失败**不抛异常**——写入内容已落盘，抛出去会让调用方误判「写入失败」而
    重试（两段式账本已记 committed，重试即重复写入）。改为在响应里如实标记
    `flush_error`，不静默。
    """
    try:
        cg.flush()
    except Exception as exc:  # noqa: BLE001 —— 索引可见性故障不得改写写入语义
        if isinstance(out, dict):
            out["flush_error"] = "%s: %s" % (type(exc).__name__, exc)


class WritePipeline:
    """写入拦截器链（实例级；default_pipeline() 提供进程级默认单例）。"""

# 生效条件：无前置；初始化 _before / _after 两条空链（元素为 (name, fn) 二元组），不做任何注册、不触盘；
    def __init__(self):
        self._before = []  # [(name, fn)]
        self._after = []   # [(name, fn)]

    # ---------- 注册表 ----------

# 生效条件：fn 可调用时先按 name 摘除同名项，再在 position 为 None 时把 (str(name), fn) 追加到链尾、否则插入 max(0, int(position))（position=0 非 None，走插入分支）；fn 不可调用则抛 TypeError；
    def register_before(self, name, fn, position=None):
        """注册 before 拦截器（同名幂等替换；position=None 追加到链尾）。

        fn(ctx) -> None | dict（终态响应，短路）。
        """
        if not callable(fn):
            raise TypeError(f"拦截器必须可调用：{name!r}")
        self.unregister_before(name)
        item = (str(name), fn)
        if position is None:
            self._before.append(item)
        else:
            self._before.insert(max(0, int(position)), item)

# 生效条件：按 str(name) 过滤 _before，仅保留 x[0] != str(name) 的项（即删除全部同名项），并返回删除前后长度是否不等以表示是否确有移除；
    def unregister_before(self, name):
        n0 = len(self._before)
        self._before = [x for x in self._before if x[0] != str(name)]
        return len(self._before) != n0

# 生效条件：fn 可调用时先按 name 摘除同名项，再把 (str(name), fn) 追加到 _after 链尾；fn 不可调用则抛 TypeError；
    def register_after(self, name, fn):
        """注册 after 观察者：fn(ctx, out)，落盘成功后按序调用。"""
        if not callable(fn):
            raise TypeError(f"after 钩子必须可调用：{name!r}")
        self.unregister_after(name)
        self._after.append((str(name), fn))

# 生效条件：按 str(name) 过滤 _after，仅保留 x[0] != str(name) 的项（即删除全部同名项），并返回删除前后长度是否不等以表示是否确有移除；
    def unregister_after(self, name):
        n0 = len(self._after)
        self._after = [x for x in self._after if x[0] != str(name)]
        return len(self._after) != n0

# 生效条件：无前置；返回 {"before": [...注册名], "after": [...注册名]}，只暴露名字不暴露函数对象，顺序即执行顺序；
    def names(self):
        return {"before": [n for n, _f in self._before],
                "after": [n for n, _f in self._after]}

    # ---------- 执行 ----------

# 生效条件：传入 cg 与 a（a 为假值如 None 时按 {} 处理，nid 取 a.get("node_id") 或其假值回落 "mem_"+毫秒时间戳），任一 before 钩子返回非 None 即记 halted_by 并经 _commit_visibility 短路返回该响应，全部放行则记 twophase 意图后跑 _executor（其抛 BaseException 时记 STATUS_ERROR 并原样重抛）再顺序跑 after 链、_commit_visibility 并返回落盘 out；
    def execute(self, cg, a):
        """写入请求入口：跑 before 链 → 链尾执行器 → after 链。

        before 链任一非 None 返回值即终态响应（与重构前各分支的 return
        形态逐字节一致）；链尾执行器产生落盘响应，after 链只观测不改写。
        """
        a = a or {}
        ctx = {"cg": cg, "a": a,
               "nid": a.get("node_id")
               or ("mem_" + str(int(time.time() * 1000))),
               "verdict": None, "cvd": None}
        for name, fn in self._before:
            out = fn(ctx)
            if out is not None:
                ctx["halted_by"] = name
                _commit_visibility(cg, out)
                return out
        # ③ 两段式：闸门**全部放行**（确认要写）→ 先落意图，再执行落盘，
        # 最后记结果。崩溃若发生在两者之间，`reconcile` 能据正文指纹回答
        # 「那笔写入到底落盘了没有」，而不是留下一条无痕的静默记忆。
        tok = twophase.begin(cg, ctx["nid"], a.get("content", ""),
                             layer=a.get("layer") or "knowledge",
                             actor="writepipe:executor")
        try:
            out = _executor(ctx)
        except BaseException as exc:
            # 执行器抛异常（权限拒绝/校验失败）= 写入未完成 → 账本记 error，
            # 异常照抛不吞（两段式只记账，不改写既有错误语义）。
            twophase.commit(cg, tok, status=twophase.STATUS_ERROR,
                            reason=type(exc).__name__)
            raise
        ctx["out"] = out
        twophase.commit(cg, tok, status=twophase.STATUS_COMMITTED,
                        reason="executor_ok")
        for _name, fn in self._after:
            fn(ctx, out)
        _commit_visibility(cg, out)
        return out


# --------------------------------------------------------------------------
# 默认链（原 mcp_server._cg_dispatch op=="write" 分支，行为逐字节搬运）
# --------------------------------------------------------------------------

# 生效条件：ctx["a"] 经 audit.audit 得出的 state 为 ACCEPT 时返 None 放行，为 REJECT 时经 cg.add_rejected 返回 ok=False/moved_to="rejected"，其余 state 经 cg.propose 返回 moved_to="review_queue"（pr 带 dedup 时再附 dedup/dup_of/dup_status 并改写 hint）；
def _gate_audit(ctx):
    """校验闸：audit.audit 四态。ACCEPT 放行；REJECT 负记忆；其余入审核队列。"""
    a = ctx["a"]
    cg = ctx["cg"]
    from . import audit
    payload = {"content": a.get("content", ""), "action": a.get("action"),
               "sensitivity": a.get("sensitivity"),
               "topic": a.get("query") or a.get("intent")}
    if (a.get("content_kind") or "").strip() == "hyperedge":
        # 超边验证器（回放比对）需要锚与结构键：fm 键平铺在 a 顶层，
        # 经 hyperedge.audit_payload 装配三键载荷（缺锚由验证器 fail-closed）。
        from . import hyperedge as _he
        payload = _he.audit_payload(a)
    verdict = audit.audit(
        (a.get("content_kind") or "").strip(),
        payload,
        {"cg": cg, "principal": getattr(cg, "principal", None)})
    ctx["verdict"] = verdict
    st = verdict["state"]
    if st == audit.ACCEPT:
        return None
    if st == audit.REJECT:
        rid = cg.add_rejected((a.get("content") or "")[:200], verdict["evidence"],
                              verification_basis=verdict.get("basis") or "test",
                              tags=a.get("tags"))
        return {"ok": False, "id": rid, "committed": False,
                "moved_to": "rejected", "verdict": verdict,
                "hint": "这是审核闸门的正常行为：内容未过内容政策审核（REJECT），"
                        "已记入负记忆——不是工具故障，重试同样结果；"
                        "拒绝依据见 verdict.evidence"}
    from .mcp_server import _proposal_extras
    pr = cg.propose(ctx["nid"], a.get("content", ""), info=True,
                    layer=a.get("layer") or "knowledge",
                    tags=a.get("tags"), condition_space=a.get("condition_space"),
                    **_proposal_extras(a, verdict))
    out = {"ok": True, "id": ctx["nid"], "pid": pr["pid"], "committed": False,
           "moved_to": "review_queue", "verdict": verdict,
           "hint": "这是校验闸门的正常行为（verdict=%s）：内容未达 ACCEPT，"
                   "已入审核队列——不需要重试；落盘须由设计者权限（can_admin）"
                   "对提案 pid 裁决（agent 端无裁决权是设计），转告使用者："
                   "python -m md_cg.review_cli list 后 accept/reject，"
                   "或 cg(op=review, pid=<pid>, decision=accept|reject|"
                   "edit|merge, reason=<理由>)" % verdict.get("state")}
    if pr.get("dedup"):
        out["dedup"] = True
        out["dup_of"] = pr["pid"]
        out["dup_status"] = pr.get("dup_status")
        out["hint"] = (
            "同内容提案已存在（pid=%s，状态=%s，幂等去重），"
            "本次未重复入队——无需重试；落盘须由设计者权限（can_admin）"
            "对该 pid 裁决：python -m md_cg.review_cli list 后 accept/reject，"
            "或 cg(op=review, pid=<pid>, decision=accept|reject|edit|merge, "
            "reason=<理由>)" % (pr["pid"], pr.get("dup_status") or "pending"))
    return out


# 生效条件：ctx["a"]["consistency"] 为假值时返回 None；on_conflict 缺键或假值回落 "defer"，仅当 verdict=REJECT 且 on_conflict=reject（返回 moved_to="conflict_rejected"）或 verdict∈{REJECT,BLINDSPOT} 且 on_conflict=defer（转 review_queue，去重命中时改写 hint）才拦截，其余 on_conflict 取值返回 None；
def _gate_consistency(ctx):
    """冲突闸：节点间自动冲突检测（三级决策）。

    仅 REJECT（明确判为冲突）按 on_conflict 处置：reject=直接拒绝；
    defer=转入审核队列。BLINDSPOT（无可比对节点，检测前提不存在）恒放行，
    cvd 审计经链尾透出（issue #26：无法比对 ≠ 冲突，入队是死胡同）。
    """
    a = ctx["a"]
    cg = ctx["cg"]
    if not bool(a.get("consistency", True)):
        return None
    from .mcp_server import _proposal_extras
    oc = (a.get("on_conflict") or "defer").strip().lower()
    cvd = cg.check_consistency(
        a.get("content", ""),
        layer=a.get("layer") or ("contextual" if a.get("gated")
                                 else "knowledge"),
        condition_space=a.get("condition_space"),
        non_applicable_conditions=a.get("non_applicable_conditions"),
        tags=a.get("tags"), exclude=ctx["nid"], auto_flywheel=True)
    ctx["cvd"] = cvd
    v = cvd.get("verdict")
    # issue #26（2026-09-23）：BLINDSPOT ≠ REJECT——冲突闸的 BLINDSPOT 唯一出口
    # 是 comparable==0（既有节点无一声明条件，含空库），语义是「检测前提不
    # 存在」而非「已判定冲突」；defer 入队后裁决者面对同样空白（无可操作
    # 下一步，死胡同）。故 BLINDSPOT 恒放行：cvd 经链尾 _executor 的
    # consistency 字段如实透出（放行原因可观测）；REJECT（明确冲突）维持
    # 原拦截语义。原先两者等同拦截 → 空库首次写入恒不落盘（README 推荐的
    # content_kind=code 通路必失败——库越空越写不进）。
    blocked = (v == "REJECT" and oc in ("reject", "defer"))
    if not blocked:
        return None
    if oc == "reject":
        return {"ok": False, "id": ctx["nid"], "committed": False,
                "moved_to": "conflict_rejected",
                "consistency": cvd, "verdict": ctx["verdict"]}
    pr = cg.propose(ctx["nid"], a.get("content", ""), info=True,
                    layer=a.get("layer") or "knowledge",
                    tags=a.get("tags"),
                    condition_space=a.get("condition_space"),
                    **_proposal_extras(a, ctx["verdict"]))
    out = {"ok": False, "id": ctx["nid"], "pid": pr["pid"],
           "committed": False,
           "moved_to": "review_queue", "consistency": cvd,
           "verdict": ctx["verdict"],
           "hint": "这是冲突闸门的正常行为：本次写入与既有条件/纪律冲突"
                   "（on_conflict=defer），已转入审核队列待裁决——"
                   "不是工具故障，重试同样结果；"
                   "落盘须由设计者权限（can_admin）裁决，转告使用者："
                   "python -m md_cg.review_cli list 后 accept/reject，"
                   "或 cg(op=review, pid=<pid>, decision=accept|reject|"
                   "edit|merge, reason=<理由>)"}
    if pr.get("dedup"):
        out["dedup"] = True
        out["dup_of"] = pr["pid"]
        out["hint"] = (
            "同内容提案已存在于审核队列（pid=%s，幂等去重），"
            "本次未重复入队——无需重试；"
            "落盘须由设计者权限（can_admin）对该 pid 裁决："
            "python -m md_cg.review_cli list 后 accept/reject，"
            "或 cg(op=review, pid=<pid>, decision=accept|reject|"
            "edit|merge, reason=<理由>)" % pr["pid"])
    return out


# 生效条件：ctx["a"] 的 gated 为假值时返 None 放行；为真值时按 cg.remember_gated 返回的 verdict 落两段式账，且仅 verdict 为 ACCEPT 时 ok/committed 为 True，verdict 为 MERGE 时记 committed 并置 moved_to="merged_into:"+merged_into，verdict 为 DROP/DEFER 时记 aborted 且 moved_to 为其小写值；
def _gate_gated(ctx):
    """主动遗忘闸（gated=true 时启用）：writelimit 限流 + forgetting 三问四态。

    本闸是「替代执行路径」：命中即由 remember_gated 代为落盘/合并/丢弃并
    返回终态；未启用（gated 假值）放行给链尾执行器。
    """
    a = ctx["a"]
    cg = ctx["cg"]
    if not a.get("gated"):
        return None
    hint = a.get("importance_hint")
    if hint is None and a.get("importance") is not None:
        hint = float(a["importance"])
    # ③ 两段式：本闸是**替代执行路径**（自己落盘），意图必须由它先记——
    # 若等 execute 在链后统一记，intent 会晚于本闸内部的写盘，「先行持久化」
    # 就不成立了。落盘前的窗口因此仍然被账本覆盖。
    tok = twophase.begin(cg, ctx["nid"], a.get("content", ""),
                         layer=a.get("layer") or "contextual",
                         actor="writepipe:gated")
    res = cg.remember_gated(
        ctx["nid"], a.get("content", ""), layer=a.get("layer") or "contextual",
        role=a.get("role"), tags=a.get("tags"),
        condition_space=a.get("condition_space"),
        verification_basis=(a.get("verification_basis")
                            or (ctx.get("verdict") or {}).get("basis")),
        non_applicable_conditions=a.get("non_applicable_conditions"),
        importance_hint=hint, override=bool(a.get("override")),
        consistency=False,
        derived_from=_split_ids(a.get("derived_from")),
        relation=a.get("relation"))
    v = res.get("verdict")
    committed = v == "ACCEPT"
    # 结局如实记：ACCEPT=落盘完成；MERGE=内容并入既有节点（不再以本次内容成
    # 文，指纹对账不适用，故直接记 committed 并注明去向）；DROP/DEFER=未落盘。
    if committed:
        twophase.commit(cg, tok, status=twophase.STATUS_COMMITTED,
                        reason="gated_accept")
    elif v == "MERGE":
        twophase.commit(cg, tok, status=twophase.STATUS_COMMITTED,
                        reason="merged_into:%s" % res.get("merged_into"))
    else:
        twophase.commit(cg, tok, status=twophase.STATUS_ABORTED,
                        reason="gated_%s" % str(v).lower())
    out = {"ok": committed, "id": ctx["nid"], "committed": committed,
           "gate": res, "verdict": ctx["verdict"]}
    if ctx.get("cvd") is not None:
        out["consistency"] = ctx["cvd"]
    if v == "MERGE":
        out["moved_to"] = "merged_into:" + str(res.get("merged_into"))
    elif v in ("DROP", "DEFER"):
        out["moved_to"] = v.lower()
    # gated 是**替代落盘路径**（自行落盘/合并后直接返回终态、不跑 after 链），故
    # 一跳同步传播须在此单独触发——否则 MERGE 类覆写会漏传下游（非对称边界，
    # 与 `_after_trust` 注释互指）。
    if committed or v == "MERGE":
        prop = trust.mark_dependents(
            cg, ctx["nid"],
            reason="上游节点被 gated 写入/合并（内容或验证态可能已变）",
            actor="writepipe:gated", trigger="write_gated")
        if isinstance(prop, dict) and prop.get("changed"):
            out["propagation"] = {"changed": prop.get("changed"),
                                  "updated": (prop.get("updated") or [])[:10]}
    return out


# 生效条件：ctx["a"]["content"] 的「# 子功能：」行含显式跨节点引用（`@<节点 id>`）且 depends_on 解析为空时返回 ok=False/error="E050" 的终态；depends_on 含库中不存在的 id 时返回 ok=False/error="E051" 的终态；其余（无该行 / 哨兵 / 自然语言自述 / 声明且目标齐备）返回 None 放行；
def _gate_deps(ctx):
    """依赖声明闸（before 链：linkref 之后、audit 之前）：**硬拒条件缺失**。

    「声明」的界定（收窄裁定 b，2026-09-19）：以 `@<节点 id>` 显式引用为界——
    自然语言**自述子功能**（描述本单元**内部**构成）不构成依赖声明。原因：CCG
    编译产物六要素必含「子功能」行，若沿用「非哨兵即声明」，每个 CCG 节点落库后
    都会被自己的闸门永久要求 depends_on（E050 死锁，test_ccgc V16f 实证）。
    依赖不是必填元数据；**只有显式声称依赖却不落字段**才是违规（声称与落盘不一致）。

    为何是硬拒而非告警：依赖是失效传播的**唯一入口**。声明缺失时，「上游变了
    下游要存疑」这条链从源头就不存在——它既不报错、也不留任何信号，缺陷以
    「静默不传播」的形态长期存活（比报错更难发现）。故按契约缺失处理，与
    `ccgc` 的 E 码体系同构（E050 声明缺失 / E051 目标不存在）。

    张力消解（与 provenance「写路径永不阻断」纪律的边界，二者不冲突）：
      - **声明缺失 / 目标不可解析 = 契约违规** → 硬拒（本闸只做这件事）；
      - **传播落盘失败 = 运维降级** → 告警不阻断（见 `_after_trust`）。

    判据基于**入参**而非落盘后回读：首次写入时节点尚不存在，回读式校验会
    永远放行（等于闸门失效）。
    """
    a = ctx["a"]
    cg = ctx["cg"]
    from . import nodefile
    if not nodefile.declares_dependency(a.get("content") or ""):
        return None
    deps = trust.as_deps(a.get("depends_on"))
    if not deps:
        return {"ok": False, "id": ctx["nid"], "committed": False,
                "gate": "deps", "error": "E050",
                "verdict": ctx.get("verdict"),
                "hint": ("依赖声明缺失（E050）：正文以 " + nodefile.DEP_REF_MARK
                         + "<节点 id> 显式声明了跨节点依赖（「# 子功能：」行），"
                           "但 depends_on 未给出可解析目标。依赖必须是**可解析的字段**"
                           "（形如 depends_on=[\"<被依赖节点 id>\"]），不能只是散文——"
                           "否则被依赖单元变动时，下游无处可传。补齐后重试；"
                           "若该行只是描述本单元内部构成（自述），去掉 "
                         + nodefile.DEP_REF_MARK + " 引用或改填「无」即可。"
                           "本闸是契约闸门的正常行为，不是工具故障。")}
    known = set((getattr(cg, "index", None) or {}).get("nodes") or {})
    missing = [d for d in deps if d not in known]
    if missing:
        return {"ok": False, "id": ctx["nid"], "committed": False,
                "gate": "deps", "error": "E051", "missing": missing[:10],
                "verdict": ctx.get("verdict"),
                "hint": "依赖目标不存在（E051）：depends_on 指向 "
                        + ", ".join(missing[:5])
                        + "，但库中查无此节点——声称依赖一个并不存在的地基，"
                          "失效传播会在此处断链。请先建立被依赖节点，或修正 id。"}
    return None


# 生效条件：out 为 dict 且 out["committed"] 为真时，调 trust.mark_dependents 做一跳同步传播（异常吞掉并降级），并在节点时间轴非「时效内」时往 out 写 "validity" 提示；其余情况直接返回不做任何动作；
def _after_trust(ctx, out):
    """after 观察者：落盘后触发**一跳同步传播** + 时效提示。

    为何落在 after 而非 before：只有真正落盘（内容确实变了）才构成「地基动了」；
    before 链短路路径（REJECT / DEFER）本就不跑 after 链，语义天然正确。
    例外：`gated` 是替代落盘路径（自行落盘并返回终态、不跑 after），故它的
    传播在 `_gate_gated` 内部单独触发（见该处注释）。

    **永不抛**：传播失败只降级（`trust.mark_dependents` 内部已兜底并写台账），
    绝不把「写入已成功」改写为失败——与 `_commit_visibility` 同款边界。
    """
    if not isinstance(out, dict) or not out.get("committed"):
        return
    cg = ctx["cg"]
    nid = ctx.get("nid")
    if not nid:
        return
    prop = trust.mark_dependents(
        cg, nid, reason="上游节点被写入/覆写（内容或验证态可能已变）",
        actor="writepipe:trust", trigger="write")
    if isinstance(prop, dict) and prop.get("changed"):
        out["propagation"] = {"changed": prop.get("changed"),
                              "updated": (prop.get("updated") or [])[:10]}
    # 热路径失效（2026-09-19 热温冷分层）：写入后清缓存
    try:
        from . import hotcache as _hc
        _hc.invalidate(cg, nid)
    except Exception:                                  # noqa: BLE001
        pass  # 缓存失效失败不阻断写入（永不抛）

    # 冷路径入队（2026-09-19 热温冷分层）：异步深度验证
    try:
        from . import coldverify as _cv
        _cv.enqueue(cg, nid, action="reverify",
                    reason="writepipe:after_trust")
    except Exception:                                  # noqa: BLE001
        pass  # 入队失败不阻断写入


# 生效条件：a 的 content_kind 非 hyperedge 即返回 {}，为 hyperedge 时延迟导入
# hyperedge.EXTRA_FM_KEYS 收集 a 中非 None 的对应键返回（其余写入零键透传）；
def _hyperedge_extra(a):
    """hyperedge 写入的 fm 扩展键透传。计划决策 2：超边写入走 write 动词既有
    审核链、不造新通道——链尾执行器是唯一落盘点，cg.add 经 **extra 落 fm，
    故扩展键在此透传；落盘面丢字段 = 上游声明静默失效。延迟导入防循环依赖。"""
    if (a.get("content_kind") or "").strip() != "hyperedge":
        return {}
    from . import hyperedge as _he
    return {k: a[k] for k in _he.EXTRA_FM_KEYS if a.get(k) is not None}


# 生效条件：由链尾以含 cg 与 a 的 ctx 调用即无条件执行 cg.add 落盘并返回 ok=True/committed=True，ctx["cvd"] 非 None 时附加 consistency 字段；
def _executor(ctx):
    """链尾执行器（常驻不可卸载）：cg.add 直写落盘。

    角色/层权限校验（require_layer_write）在 MdCGSecure.add 库层内部，
    结构上不可被拦截器绕过——拦截器只能裁决「写不写」，改不了「谁能写」。
    """
    a = ctx["a"]
    cg = ctx["cg"]
    cg.add(ctx["nid"], a.get("content", ""),
           layer=a.get("layer") or "knowledge",
           tags=a.get("tags"), condition_space=a.get("condition_space"),
           importance=float(a.get("importance", 0.5)),
           verification_basis=a.get("verification_basis")
           or (ctx.get("verdict") or {}).get("basis"),
           non_applicable_conditions=a.get("non_applicable_conditions"),
           override=bool(a.get("override")), consistency=False,
           derived_from=_split_ids(a.get("derived_from")),
           relation=a.get("relation"),
           # 可验证记忆单元（裁定 D）：依赖/双时间轴/验证态随写入落 fm。
           # 透传而非丢弃——落盘面丢字段＝上游声明静默失效（比报错难发现）。
           depends_on=trust.as_deps(a.get("depends_on")),
           valid_from=a.get("valid_from"), valid_until=a.get("valid_until"),
           verification_state=a.get("verification_state"),
           **_hyperedge_extra(a))
    out = {"ok": True, "id": ctx["nid"], "committed": True,
           "verdict": ctx["verdict"]}
    if ctx.get("cvd") is not None:
        out["consistency"] = ctx["cvd"]
    return out


# 生效条件：value 传入即无条件延迟导入并转调 mcp_server._split_ids 后原样返回其结果（本符号无自身分支）；
def _split_ids(value):
    # 与 mcp_server._split_ids 同源（延迟导入，单一真源）
    from .mcp_server import _split_ids as _f
    return _f(value)


# --------------------------------------------------------------------------
# 进程级默认链（单例；mcp_server op=write 一行分发到此）
# --------------------------------------------------------------------------

_DEFAULT = None


# 生效条件：pipe 传入即对其依次注册 before 的 linkref(position=0)/deps/audit/consistency/gated 与 after 的 linkref/trust（同名幂等替换），并返回同一 pipe；
def install_default_gates(pipe):
    """把默认闸以拦截器形态注册（幂等：同名替换，可重复调用）。

    链序（2026-09-19 起）：
        before = linkref(解析) → deps(依赖声明) → audit → consistency → gated
                 → 链尾执行器
        after  = linkref(建边) → trust(一跳传播)

    linkref 置于链首的理由：正文引用解析是**纯读、无副作用**，且其结果必须
    先于任何短路闸写入 ctx，供 after 链消费。短路闸（REJECT/DEFER/gated）
    返回终态时 `execute` 不跑 after 链，故未落盘的写入不会建边——语义正确。

    deps 夹在 linkref 与 audit 之间的理由：两件事都与内容政策无关，故在 audit
    之前；linkref 之后是因为它只解析正文引用、不动依赖声明——依赖是**字段域**
    而非正文域，顺序倒置不会互相污染，但保持「解析在前、裁决在后」的一致读序。

    after 的 trust 置于 linkref 之后：建边先于传播——传播按 `depends_on`
    反查（字段域）而非边域，故顺序不影响正确性；置于其后只为让 ctx 中的
    边信息先落定，便于排障时读 ctx。

    linkref 的**落点是 after 而非注入 `a["edges"]`**：`cg.add` 是全量重建
    fm，注入 edges 会在覆写既有节点时清空其原有边（破坏性副作用）；
    `append_edge` 是边域窄原语且幂等（见 linkref 模块 docstring）。
    依赖声明同忌经 `a["edges"]` 注入——走 `depends_on` 字段域。
    """
    from . import linkref
    pipe.register_before("linkref", linkref.before_hook(), position=0)
    pipe.register_before("deps", _gate_deps)
    pipe.register_before("audit", _gate_audit)
    pipe.register_before("consistency", _gate_consistency)
    pipe.register_before("gated", _gate_gated)
    pipe.register_after("linkref", linkref.after_hook())
    pipe.register_after("trust", _after_trust)
    return pipe


# 生效条件：模块级 _DEFAULT 为 None 时新建 WritePipeline 并经 install_default_gates 注册后缓存返回，否则直接返回已缓存的 _DEFAULT 单例；
def default_pipeline():
    """进程级默认写入链（单例）。自定义闸门 register_before 即插即拔。"""
    global _DEFAULT
    if _DEFAULT is None:
        _DEFAULT = install_default_gates(WritePipeline())
    return _DEFAULT