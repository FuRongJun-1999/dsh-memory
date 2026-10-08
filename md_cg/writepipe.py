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
节一致）：audit → consistency → gated → **autonomy（三档自治档位闸，
2026-10-02 批次②）** → _executor。

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


# issue #82.3：写入硬上限（全 content_kind 统一）。
MAX_WRITE_BYTES = 1048576        # 1 MiB


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

# 生效条件：传入 cg 与 a（a 为假值如 None 时按 {} 处理，nid 取 a.get("node_id") 或其假值回落 mdcg.mint_auto_id(cg)——自动 id 的**唯一铸造点**，含毫秒位+6 位 hex 随机段与「已存在则换随机段重生成」的有界存在性闸），任一 before 钩子返回非 None 即记 halted_by 并经 _commit_visibility 短路返回该响应，全部放行则记 twophase 意图后跑 _executor（其抛 BaseException 时记 STATUS_ERROR 并原样重抛）再顺序跑 after 链、_commit_visibility 并返回落盘 out；
    def execute(self, cg, a):
        """写入请求入口：跑 before 链 → 链尾执行器 → after 链。

        before 链任一非 None 返回值即终态响应（与重构前各分支的 return
        形态逐字节一致）；链尾执行器产生落盘响应，after 链只观测不改写。
        """
        a = a or {}
        # ---- issue #82.2（2026-10-09 DSH 端实施）：work_wip 属过程件，
        # 缺省不得进 knowledge 层（否则分桶/条件路由被过程件稀释）。
        # 单点规范化：仅当未显式给 layer 且 content_kind==work_wip 时改路由到
        # contextual；各分支既有的 layer-or-knowledge 兜底不动（仍服务其余 kind）。
        if not a.get("layer") and (a.get("content_kind") or "").strip() == "work_wip":
            a = dict(a)
            a["layer"] = "contextual"
        # ---- issue #82.3（同批）：写入硬上限（全 kind 统一）。
        # 判据：存量最大 463KB、P999=17KB ⇒ 1 MiB 约 60 倍余量、零存量阻断。
        # 超限如实报（当前大小 + 上限），不截断、不静默。
        _wc = a.get("content") or ""
        _wbytes = len(_wc.encode("utf-8")) if isinstance(_wc, str) else 0
        if _wbytes > MAX_WRITE_BYTES:
            return {"ok": False, "error": "content 超过写入硬上限（issue #82.3）",
                    "bytes": _wbytes, "limit": MAX_WRITE_BYTES,
                    "verdict": {"state": "REJECT", "kind": (a.get("content_kind") or "text"),
                                "evidence": "content %d 字节 > 上限 %d" % (_wbytes, MAX_WRITE_BYTES)}}
        # B1（2026-09-30）：自动 id 的铸造**只有一份实现**（mdcg.mint_auto_id）
        # ——原先此处 `"mem_" + 毫秒` 与 mcp_server 的 mdcg_remember 分支各写一份，
        # 同毫秒自动写入铸出同一 id，被 add 的 upsert 语义静默顶替（无失败信号）。
        # 本处只委托，不复制判据。
        from .mdcg import mint_auto_id
        ctx = {"cg": cg, "a": a,
               "nid": a.get("node_id") or mint_auto_id(cg),
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

# 生效条件：verdict 的 detail.missing 非空（或 evidence 以「缺少必需要素」起首）时返回「可修正的缺要素」文案（含缺失清单与补齐指引，不含「重试同样结果」式劝退表述）；其余 REJECT（禁止规则命中＝政策违规）返回「重试同样结果」原文案。
def _reject_hint(verdict):
    """审核 REJECT 的 hint 分型（**单点生成处**）。

    为什么收敛在此：write 的 REJECT 出口只有本文件的 `_gate_audit` 一处
    （链尾 `_executor` 只管落盘成功；其余闸门的 hint 各有自己的语义），
    故分型逻辑集中在此函数，`_gate_audit` 只做调用——避免「同一语义两处
    文案」随改动各自漂移。

    两类 REJECT 对调用方的**可操作性**不同，文案必须分型（否则把可修正的
    缺要素误导成重试无用）：
      · 缺必需要素（成文格式不全）→ 内容可补，补完重写即落盘；
      · 命中禁止规则（内容政策违规）→ 内容本身不该入库，原样再发无意义。
    """
    detail = verdict.get("detail") or {}
    missing = [str(x) for x in (detail.get("missing") or [])]
    ev = str(verdict.get("evidence") or "")
    if missing or ev.startswith("缺少必需要素"):
        listed = "、".join(missing) if missing else ev
        return ("写入被拒（REJECT）：缺少必需要素——%s。"
                "这是**可修正**的拒收：按 CCG 六要素（功能名／生效条件／子功能／"
                "执行／验证方式／不适用条件，各占一行、以「# 要素名：」起首）"
                "补齐后重写即可，本条未入库；该次内容已记入负记忆（rejected），"
                "补全后重写为新条目。" % listed)
    return ("这是审核闸门的正常行为：内容未过内容政策审核（REJECT），"
            "已记入负记忆——不是工具故障，重试同样结果；"
            "拒绝依据见 verdict.evidence")


# 生效条件：先经 audit.resolve_rulebook() 判策略可用性——不可用（env 显式坏路径 / env 未设且包内默认也拿不到）即返回 ok=False/moved_to="policy_unavailable" 与结构化 error（含 code/reason/hint），**不进 audit、不 propose、不落任何节点**；可用则把规则经 ctx["rules"] 下传（含 forbidden=0 且 required=0 的空规则，空规则仍走 _rule_check 的 DEFER 分支），其后 ctx["a"] 经 audit.audit 得出的 state 为 ACCEPT 时返 None 放行，为 REJECT 时经 cg.add_rejected（正文先经 audit.redact_forbidden 把禁表命中替换为占位符、再截前 200 字）返回 ok=False/moved_to="rejected"（hint 由 _reject_hint 按「可修正的缺要素 / 政策违规」分型生成），其余 state 经 cg.propose 返回 moved_to="review_queue"（pr 带 dedup 时再附 dedup/dup_of/dup_status 并改写 hint）；
def _gate_audit(ctx):
    """校验闸：先判策略可用性（fail-closed），再按 audit.audit 四态分派。

    策略面（issue #43 问题 1 修复）：修前 env 未设 → load_rulebook 返回空规则
    → text 恒 DEFER → 落到本函数的**非 ACCEPT/REJECT 出口**（cg.propose），
    正文（含凭据）明文入 hippocampus/inbox.jsonl 且不经脱敏（脱敏只在 REJECT
    分支）。故策略不可用时在**提案入队之前**返回结构化错误：moved_to=
    "policy_unavailable"，响应体只带错误码/原因/hint，**不含正文**。
    """
    a = ctx["a"]
    cg = ctx["cg"]
    from . import audit
    rules, source, perr = audit.resolve_rulebook()
    ctx["policy"] = {"source": source}
    if perr is not None:
        return {"ok": False, "id": ctx["nid"], "committed": False,
                "moved_to": "policy_unavailable",
                "policy": {"source": source}, "error": perr,
                "hint": "写入被拒（fail-closed）：策略不可用——%s。%s"
                        % (perr["reason"], perr["hint"])}
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
        {"cg": cg, "principal": getattr(cg, "principal", None),
         # 规则来源已在闸门单点解析（含包内默认回落），下传给验证器——
         # 验证器仍保留 `ctx.get("rules") or load_rulebook()` 的兜底。
         "rules": rules})
    ctx["verdict"] = verdict
    st = verdict["state"]
    if st == audit.ACCEPT:
        return None
    if st == audit.REJECT:
        # 先脱敏再截断：命中禁表的凭据不得随负记忆落盘（issue #43）；
        # 截断在后，避免凭据跨 200 字边界被截成不再匹配模式的残片而漏过。
        # tags 与正文**同口径脱敏**（PR#44 复核补）：正文命中而 tags 夹带凭据时，
        # 原先 tags 原样进负记忆——凭据照样落盘，只是换了个字段。
        tags = a.get("tags")
        if isinstance(tags, (list, tuple)):
            tags = [audit.redact_forbidden(t) if isinstance(t, str) else t for t in tags]
        rid = cg.add_rejected(audit.redact_forbidden(a.get("content") or "")[:200],
                              verdict["evidence"],
                              verification_basis=verdict.get("basis") or "test",
                              tags=tags)
        return {"ok": False, "id": rid, "committed": False,
                "moved_to": "rejected", "verdict": verdict,
                "hint": _reject_hint(verdict)}
    from .mcp_server import _proposal_extras
    pr = cg.propose(ctx["nid"], a.get("content", ""), info=True,
                    layer=a.get("layer") or "knowledge",
                    tags=a.get("tags"), condition_space=a.get("condition_space"),
                    **_proposal_extras(a, verdict))
    out = {"ok": True, "id": ctx["nid"], "pid": pr["pid"], "committed": False,
           "moved_to": "review_queue", "verdict": verdict,
           "hint": "这是校验闸门的正常行为（verdict=%s）：内容未达 ACCEPT，"
                   "已入审核队列——不需要重试；落盘须经裁决（can_admin 权限）"
                   "——agent 可在经蜂群或验证端复核后自行裁决，例外须转使用者"
                   "（智能论这类重要协议真源 / 对外发送信息数据 / 可能泄露·病毒·"
                   "恶意操纵）：python -m md_cg.review_cli list 后 accept/reject，"
                   "或 cg(op=review, pid=<pid>, decision=accept|reject|"
                   "edit|merge, reason=<理由>)" % verdict.get("state")}
    if pr.get("dedup"):
        out["dedup"] = True
        out["dup_of"] = pr["pid"]
        out["dup_status"] = pr.get("dup_status")
        out["hint"] = (
            "同内容提案已存在（pid=%s，状态=%s，幂等去重），"
            "本次未重复入队——无需重试；落盘须经裁决（can_admin 权限）："
            "python -m md_cg.review_cli list 后 accept/reject，"
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
                   "落盘须经裁决（can_admin 权限）——agent 可在经蜂群或验证端"
                   "复核后自行裁决，例外须转使用者（智能论这类重要协议真源 / "
                   "对外发送信息数据 / 可能泄露·病毒·恶意操纵）："
                   "python -m md_cg.review_cli list 后 accept/reject，"
                   "或 cg(op=review, pid=<pid>, decision=accept|reject|"
                   "edit|merge, reason=<理由>)"}
    if pr.get("dedup"):
        out["dedup"] = True
        out["dup_of"] = pr["pid"]
        out["hint"] = (
            "同内容提案已存在于审核队列（pid=%s，幂等去重），"
            "本次未重复入队——无需重试；"
            "落盘须经裁决（can_admin 权限）："
            "python -m md_cg.review_cli list 后 accept/reject，"
            "或 cg(op=review, pid=<pid>, decision=accept|reject|"
            "edit|merge, reason=<理由>)" % pr["pid"])
    return out


# 生效条件：ctx["a"] 的 gated 为假值时返 None 放行；为真值时按 cg.remember_gated（a.get("sensitivity") 一并透传——同一漏传族，B2）返回的 verdict 落两段式账，且仅 verdict 为 ACCEPT 时 ok/committed 为 True，verdict 为 MERGE 时记 committed 并置 moved_to="merged_into:"+merged_into，verdict 为 DROP/DEFER 时记 aborted 且 moved_to 为其小写值；
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
        # B2（2026-09-30）：同一漏传族——gated 分支也是**落盘路径**
        # （remember_gated → add），不透传则声明 private 在此静默降级 internal。
        sensitivity=a.get("sensitivity"),
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
    elif v == "CONFIRM":
        # 三档自治批次②：变更确认档下 B 合并已出变更单（未合并）——去向如实
        # 透出 review_queue（DROP/DEFER 两态的字面量分支一字未动）。
        out["moved_to"] = res.get("moved_to") or "review_queue"
        out["mutation"] = res.get("mutation")
        out["autonomy"] = res.get("autonomy")
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


# 生效条件：a.get("ghostref") 为 False 时跳过（opt-out，与 linkref=False 同款）；否则对 a["content"]
# 做幽灵引用检测（ghostref.check：短语层 + id 层），结果非空时分别写入 ctx["ghost_phrases"] /
# ctx["late_refs"] 供链尾执行器落 fm 与出口告警消费；**恒返回 None（永不短路）**——本闸是标记/告警级，
# 不参与拒收判定。
def _gate_ghostref(ctx):
    """幽灵引用闸（before 链：linkref 之后、deps 之前）：标记 + 降级告警，**不拒收**。

    两条防线（对齐评估 v0.1 §2 L1「转引不得升级」；CD-WHALE-01 发现 C）：
      ① 短语层：回指短语（「上次的/之前的/明明讲过」）且句内无可解析出处
         ⇒ ctx["ghost_phrases"] → 落 fm.uncertain_refs（A2 标记面）；
      ② id 层：引用目标创建时刻晚于本文档声明的生效起点（valid_from/
         effective_from）⇒ ctx["late_refs"] → 出口降级告警（不改建边判定）。

    为何不短路（与 deps 硬拒的边界）：回指是现实写作的常态——「上次的帐篷」
    在对话记忆里天然存在，缺失的是**出处记录**而非内容本身。拒收会把正常
    记忆挡在门外；标记让「出处不确定」这事可见、可裁决（未决不进二值）。

    为何消费 ctx["linkref_targets"] 而非重算：linkref 是 targets 的唯一
    写入点（同一次解析的两个面）；重算会引入「两次解析结果漂移」的可能。
    """
    a = ctx["a"]
    if a.get("ghostref") is False:
        return None
    from . import ghostref as _ghostref
    # own_from 取显式声明（**is None 判定**：0/空串不做假值跳转——
    # 与 budget_tokens「显式 0 也是显式」同款口径）。
    _own = a.get("valid_from")
    if _own is None:
        _own = a.get("effective_from")
    rep = _ghostref.check(ctx["cg"], a.get("content") or "",
                          linkref_targets=ctx.get("linkref_targets"),
                          own_from=_own)
    if rep["ghost_phrases"]:
        ctx["ghost_phrases"] = rep["ghost_phrases"]
    if rep["late_refs"]:
        ctx["late_refs"] = rep["late_refs"]
    return None


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


# 生效条件：由链尾以含 cg 与 a 的 ctx 调用即无条件执行 cg.add 落盘（a.get("sensitivity") 一并透传——落盘面丢字段＝上游声明静默失效，B2）并返回 ok=True/committed=True，ctx["cvd"] 非 None 时附加 consistency 字段；落盘前另取「同内容已存在」与「覆写既有同 id 节点」两个读数（P-9b ⑥），命中即在返回体附 dup_of/dup_ratio/dup_compared/dup_hint 与 overwrite_of/overwrite_ratio——**只加提示，不改落盘行为、不改 verdict**；
def _executor(ctx):
    """链尾执行器（常驻不可卸载）：cg.add 直写落盘。

    角色/层权限校验（require_layer_write）在 MdCGSecure.add 库层内部，
    结构上不可被拦截器绕过——拦截器只能裁决「写不写」，改不了「谁能写」。
    """
    a = ctx["a"]
    cg = ctx["cg"]
    # importance 显式 null（JSON null→None）时 get 的缺省值不生效，直接
    # float(None) 抛 TypeError 崩主写路径——回退默认 0.5（与 add 缺省同口径）；
    # 0 / 0.0 等合法 falsy 数值照传（_gate_gated :304 已是同款 None 判定）。
    _imp = a.get("importance")
    # ⑥（P-9b）：本执行器是**直写落盘点**之一（另一处 = mcp_server 的
    # mdcg_remember 非 gated 分支）。直写不去重是文档化现状（writelimit.py
    # 模块头注 :9-12：限流/同构聚合只作用 contextual 层，knowledge 等手动纪律
    # 写入不受限）——故**不改落盘行为、不改 verdict**，只在返回体补
    # 「同内容已存在」（dup_of/dup_ratio）与「本次是覆写」（overwrite_of/
    # overwrite_ratio）两个读数。判据复用 forgetting 的同一实现
    # （redundancy/prior_node/self_coverage）；两个读数都必须在 cg.add **之前**
    # 取（add 后索引必有 nid：覆写判据恒真、覆盖度恒 1.0）。
    from . import forgetting as _forgetting
    _content = a.get("content", "")
    _prior = _forgetting.prior_node(cg, ctx["nid"])
    _prior_cov = (_forgetting.self_coverage(cg, _prior, _content)
                  if _prior is not None else None)
    _dup = _forgetting.redundancy(cg, _content,
                                  layer=a.get("layer") or "knowledge",
                                  exclude=ctx["nid"])
    cg.add(ctx["nid"], _content,
           # B2（2026-09-30）：密级透传。此前本实参表**缺 sensitivity**，而
           # 同文件 _gate_audit 的 payload（:219）带着它交给审核闸——两面口径
           # 分叉：审核闸按调用方声明的密级判，落盘闸按 DEFAULT_SENSITIVITY
           # 回落 internal，声明 private 的正文以明文 + fm internal 落盘
           # （纯漏传，非设计取舍）。透传即修好，**不得**在此自行 _seal_content
           # （会绕过 fm 与 _write_node 的单一密封点）。
           sensitivity=a.get("sensitivity"),
           layer=a.get("layer") or "knowledge",
           tags=a.get("tags"), condition_space=a.get("condition_space"),
           importance=0.5 if _imp is None else float(_imp),
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
           # A1 补接（2026-10-05，路线 C 动工时经 audit 现值面发现）：检验强度
           # 透传。此前 add 层已支持该形参，但**写链实参表漏传**——经 MCP
           # op=write 声明 check_strength 一律静默丢弃（与 B2 sensitivity 漏传
           # 同族：上游声明、落盘面丢字段，比报错难发现）。
           check_strength=a.get("check_strength"),
           # A2 幽灵引用标记（正文属性：每次写入按当次检测重算，不继承——
           # 与 check_strength 的声明继承相反；缺省 None 不落键）。
           uncertain_refs=ctx.get("ghost_phrases") or None,
           **_hyperedge_extra(a))
    out = {"ok": True, "id": ctx["nid"], "committed": True,
           "verdict": ctx["verdict"]}
    if ctx.get("cvd") is not None:
        out["consistency"] = ctx["cvd"]
    # A2 幽灵引用出口（标记/告警级，不改写入语义）：短语层标记已随
    # uncertain_refs 落 fm，此处把「值写进了哪里、怎么处置」如实带回。
    if ctx.get("ghost_phrases"):
        from . import nodefile
        _gp = list(ctx["ghost_phrases"])
        out["ghost_refs"] = _gp[:16]
        out["ghost_hint"] = (
            "幽灵引用标记（A2）：正文含无可解析出处的回指短语（%s）——"
            "已落 fm.%s（**未拒收**）。若其指代某条既有记忆，请改为可解析引用"
            "（正文写裸 id，写入链自动建 reference 边）；确为首次出现时，"
            "该标记即「出处待补」的诚实记录。"
            % ("、".join(_gp[:5]), nodefile.UNCERTAIN_REFS_FIELD))
    if ctx.get("late_refs"):
        out["late_refs"] = list(ctx["late_refs"])[:10]
        out["late_hint"] = (
            "目标晚于自身（A2 降级告警）：本文档声明的生效起点早于被引目标的"
            "创建时刻——引用了「当时尚不存在」的目标。边照常建立（linkref 不看"
            "时间轴）；请核对两条时间轴：若引用意图成立可忽略，若是回填/转写"
            "产生的时序错觉，请修正 valid_from。")
    # ⑥：直写提示（不改落盘行为、不改 verdict；见本函数开头注释）
    if _prior is not None:
        out["overwrite_of"] = _prior
        out["overwrite_ratio"] = _prior_cov
    if _dup["with"] and _dup["max"] >= _forgetting.DUP_MERGE:
        out["dup_of"] = _dup["with"]
        out["dup_ratio"] = round(_dup["max"], 4)
        out["dup_compared"] = _dup["compared"]
        out["dup_hint"] = (
            "同内容已存在于 %s（覆盖度 %.2f≥%.2f）；本路径是直写（gated=false："
            "knowledge 层手动纪律写入不受限流/去重约束，见 writelimit.py 模块头注），"
            "正文已按原样落盘——如需并入既有节点请显式处理"
            % (_dup["with"], _dup["max"], _forgetting.DUP_MERGE))
    return out


# ---- 三档自治闸（设计 v0.2 §三 · 批次②） ----------------------------------

#: 改写单要复现「原动作」所需的载荷键（**写链 payload 白名单**）：变更单裁决
#: accept 时按此重放 cg.add，使「直接写」与「出单→确认→写」两条路径落盘的
#: 节点 fm 等价（issue50-c F1 的同一教训：入队时丢声明 = 两条路径元数据不等价）。
#: `sensitivity`/`layer` 不在列（各自有专属槽：rec.sensitivity / rec.layer）；
#: `override` 在列（受保护节点的覆写授权是原动作的一部分，不能替调用方补）。
_AUTONOMY_META_KEYS = ("tags", "condition_space", "verification_basis",
                       "non_applicable_conditions", "derived_from", "relation",
                       "depends_on", "valid_from", "valid_until",
                       "verification_state", "importance", "importance_source",
                       # A1 补接（2026-10-05）：检验强度同族入载荷——否则
                       # confirm 档出单 → accept 重放会丢该声明（与
                       # verification_state 同款的「两条路径元数据不等价」坑）。
                       "check_strength",
                       "override")


# 生效条件：ctx 的 a/cg/nid 就绪时以 forgetting.prior_node 判「同 id 已存在」（存在=C 改写、不存在=A 新增）并交 autonomy_modes.decide 判定——ALLOW 返回 None 放行（与改动前同一条链）；FORBID 返回 ok=False/moved_to="autonomy_forbidden" 的终态（fail-closed，不落盘、不出单）；CONFIRM 经 autonomy_modes.propose_mutation 出变更单（复用既有 propose 单点）并返回 ok=True/committed=False/moved_to="review_queue" 的终态（**不落盘**）；
def _gate_autonomy(ctx):
    """档位闸：`cg(op=write)` 对**既有 node_id 的覆写**（C 改写）在变更确认档出单。

    位置（设计 §三 硬约束②「纯加严」）：before 链**末位**——audit / consistency
    / gated 三道既有资格闸全部放行之后、链尾执行器落盘之前。故：
      · 档位**不参与**资格判定（内容政策/冲突/限流/遗忘裁决一律照旧先跑）；
      · 档位**不放宽**任何既有判据（放行分支就是「返回 None」= 原链原样）；
      · 覆写面的其余资格闸（层闸 + 写保护闸 + 降级闸）住在 `cg.add` 内部，
        故出单**之前**先经 `cg.write_qualify`（同一批 protect 单点，只判不写）
        跑一遍——受保护/越权覆写照旧当场被拒，不会变成「静默入队」。

    动作类判定：`forgetting.prior_node` 同 id 存在 ⇒ **C 改写**；不存在 ⇒
    **A 新增**（A 在缺省档与会话档都放行，只有计划档会 fail-closed 拦下——
    设计 §三「计划外零变更」）。判据复用既有单点，不另写一份存在性判据。

    不落盘的边界（如实）：`gated=true` 的写入在上游 `_gate_gated` 已是**替代
    执行路径**（自行落盘/合并后直接返回终态、不走本闸），故本闸不覆盖它；
    该面的档位判定由 `remember_gated` 自己的单点承担——**C 改写 / A 新增**在
    `MdCGOS._autonomy_gate_rewrite`、**B 合并**在 `MdCGOS._autonomy_gate_merge`。
    本闸只覆盖走链尾执行器的直写（`gated=false` 的 `cg(op=write)`）。
    三处共用同一张矩阵（`autonomy_modes.decide`），不各写一份判据。

    订正记录（2026-10-02，补强批次）：本句此前写「其覆写/合并分别由
    `remember_gated` 的 C/B 判定覆盖」——B 合并确已覆盖，**C 覆写当时没有**
    （该分支直调 `self.add`），属失实陈述（独立复核发现 1 的代码根据）。
    补强批次在 `_autonomy_gate_rewrite` 落码后本句才与实现逐句一致。
    """
    a = ctx["a"]
    cg = ctx["cg"]
    nid = ctx["nid"]
    from . import autonomy_modes as _am
    from . import forgetting as _forgetting
    prior = _forgetting.prior_node(cg, nid)
    action = _am.C_REWRITE if prior is not None else _am.A_ADD
    if prior is not None:
        # 资格在先（纯加严）：覆写的层闸/写保护闸住在 `cg.add` 内部，若档位闸
        # 先出单，一次本该 `AccessDenied`/`ProtectionError` 的覆写会变成静默入队
        # ——那是放宽既有判据。故按**同一批 protect 单点**先跑一遍资格（只判不写）。
        cg.write_qualify(nid, target_layer=a.get("layer"),
                         override=bool(a.get("override")),
                         actor=getattr(cg, "actor", None))
    dec = _am.decide(action)
    if dec["decision"] == _am.ALLOW:
        return None
    # 档位判定读数（**不参与资格判定**，只如实透出档位/动作类/判定）
    _aut = {"mode": dec["mode"], "action": dec["action"],
            "action_name": dec["action_name"], "decision": dec["decision"]}
    if dec["decision"] == _am.FORBID:
        return {"ok": False, "id": nid, "committed": False,
                "moved_to": "autonomy_forbidden", "error": "autonomy_forbid",
                "autonomy": _aut, "verdict": ctx.get("verdict"),
                "hint": dec["hint"]}
    meta = {k: a[k] for k in _AUTONOMY_META_KEYS if a.get(k) is not None}
    pay = _am.mutation_payload(
        action, nid, after=a.get("content", ""),
        reason="写链覆写（cg(op=write) 对既有节点 %s 的 %s）"
               % (nid, _am.ACTION_NAMES[action]),
        primitive="add", meta=meta)
    pr = _am.propose_mutation(cg, action, nid, payload=pay,
                              layer=a.get("layer") or "knowledge",
                              sensitivity=a.get("sensitivity"), info=True)
    return {"ok": True, "id": nid, "pid": pr["pid"], "committed": False,
            "moved_to": "review_queue", "autonomy": _aut, "mutation": pay,
            "verdict": ctx.get("verdict"),
            "hint": ("%s 本次未落盘：变更单已入审核队列（pid=%s，目标 %s）。"
                     % (dec["hint"], pr["pid"], nid))}


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
                 → autonomy(档位) → 链尾执行器
        after  = linkref(建边) → trust(一跳传播)

    autonomy（三档自治批次②）恒在最末：档位判定只决定「立即落」还是「出变更
    单」，必须晚于全部既有资格闸（纯加严，设计 §三 硬约束②）。

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
    # A2 幽灵引用闸（2026-10-05）：插在 linkref 之后——判据 ② 要消费
    # ctx["linkref_targets"]（linkref 是 targets 的唯一写入点）；判据 ① 的
    # 「句内无可解析出处」与 linkref 同源（同一次检测的两个面）。**永不短路**
    # （标记/告警级，不做拒收——设计稿 v0.1 复核修订：幽灵引用检查器限定
    # 短语层标记；回指是现实写作常态，拒收会把正常记忆挡在门外）。
    pipe.register_before("ghostref", _gate_ghostref, position=1)
    pipe.register_before("deps", _gate_deps)
    pipe.register_before("audit", _gate_audit)
    pipe.register_before("consistency", _gate_consistency)
    pipe.register_before("gated", _gate_gated)
    # 档位闸**链尾**（三档自治批次②，设计 §三 硬约束②）：既有资格闸全部通过
    # 之后、链尾执行器落盘之前——档位只决定「立即落」还是「出变更单」，不参与
    # 资格判定。gated 分支是替代执行路径（自行落盘并已 return），其合并/覆写由
    # remember_gated 的 B/C 判定覆盖（`_autonomy_gate_merge` / 补强批次的
    # `_autonomy_gate_rewrite`），故本闸登记在 gated 之后即可。
    pipe.register_before("autonomy", _gate_autonomy)
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