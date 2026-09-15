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
"""

import time

__all__ = ["WritePipeline", "default_pipeline"]


class WritePipeline:
    """写入拦截器链（实例级；default_pipeline() 提供进程级默认单例）。"""

    def __init__(self):
        self._before = []  # [(name, fn)]
        self._after = []   # [(name, fn)]

    # ---------- 注册表 ----------

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

    def unregister_before(self, name):
        n0 = len(self._before)
        self._before = [x for x in self._before if x[0] != str(name)]
        return len(self._before) != n0

    def register_after(self, name, fn):
        """注册 after 观察者：fn(ctx, out)，落盘成功后按序调用。"""
        if not callable(fn):
            raise TypeError(f"after 钩子必须可调用：{name!r}")
        self.unregister_after(name)
        self._after.append((str(name), fn))

    def unregister_after(self, name):
        n0 = len(self._after)
        self._after = [x for x in self._after if x[0] != str(name)]
        return len(self._after) != n0

    def names(self):
        return {"before": [n for n, _f in self._before],
                "after": [n for n, _f in self._after]}

    # ---------- 执行 ----------

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
                return out
        out = _executor(ctx)
        ctx["out"] = out
        for _name, fn in self._after:
            fn(ctx, out)
        return out


# --------------------------------------------------------------------------
# 默认链（原 mcp_server._cg_dispatch op=="write" 分支，行为逐字节搬运）
# --------------------------------------------------------------------------

def _gate_audit(ctx):
    """校验闸：audit.audit 四态。ACCEPT 放行；REJECT 负记忆；其余入审核队列。"""
    a = ctx["a"]
    cg = ctx["cg"]
    from . import audit
    verdict = audit.audit(
        (a.get("content_kind") or "").strip(),
        {"content": a.get("content", ""), "action": a.get("action"),
         "sensitivity": a.get("sensitivity"),
         "topic": a.get("query") or a.get("intent")},
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
                   "python scripts/review_cli.py list 后 accept/reject，"
                   "或 cg(op=review, pid=<pid>, decision=accept|reject|"
                   "edit|merge, reason=<理由>)" % verdict.get("state")}
    if pr.get("dedup"):
        out["dedup"] = True
        out["dup_of"] = pr["pid"]
        out["dup_status"] = pr.get("dup_status")
        out["hint"] = (
            "同内容提案已存在（pid=%s，状态=%s，幂等去重），"
            "本次未重复入队——无需重试；落盘须由设计者权限（can_admin）"
            "对该 pid 裁决：python scripts/review_cli.py list 后 accept/reject，"
            "或 cg(op=review, pid=<pid>, decision=accept|reject|edit|merge, "
            "reason=<理由>)" % (pr["pid"], pr.get("dup_status") or "pending"))
    return out


def _gate_consistency(ctx):
    """冲突闸：节点间自动冲突检测（三级决策）。

    不通过时按 on_conflict：reject=直接拒绝；defer=转入审核队列。
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
    blocked = ((v == "REJECT" and oc == "reject")
               or (v in ("REJECT", "BLINDSPOT") and oc == "defer"))
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
                   "python scripts/review_cli.py list 后 accept/reject，"
                   "或 cg(op=review, pid=<pid>, decision=accept|reject|"
                   "edit|merge, reason=<理由>)"}
    if pr.get("dedup"):
        out["dedup"] = True
        out["dup_of"] = pr["pid"]
        out["hint"] = (
            "同内容提案已存在于审核队列（pid=%s，幂等去重），"
            "本次未重复入队——无需重试；"
            "落盘须由设计者权限（can_admin）对该 pid 裁决："
            "python scripts/review_cli.py list 后 accept/reject，"
            "或 cg(op=review, pid=<pid>, decision=accept|reject|"
            "edit|merge, reason=<理由>)" % pr["pid"])
    return out


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
    out = {"ok": committed, "id": ctx["nid"], "committed": committed,
           "gate": res, "verdict": ctx["verdict"]}
    if ctx.get("cvd") is not None:
        out["consistency"] = ctx["cvd"]
    if v == "MERGE":
        out["moved_to"] = "merged_into:" + str(res.get("merged_into"))
    elif v in ("DROP", "DEFER"):
        out["moved_to"] = v.lower()
    return out


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
           relation=a.get("relation"))
    out = {"ok": True, "id": ctx["nid"], "committed": True,
           "verdict": ctx["verdict"]}
    if ctx.get("cvd") is not None:
        out["consistency"] = ctx["cvd"]
    return out


def _split_ids(value):
    # 与 mcp_server._split_ids 同源（延迟导入，单一真源）
    from .mcp_server import _split_ids as _f
    return _f(value)


# --------------------------------------------------------------------------
# 进程级默认链（单例；mcp_server op=write 一行分发到此）
# --------------------------------------------------------------------------

_DEFAULT = None


def install_default_gates(pipe):
    """把默认六道闸以拦截器形态注册（幂等：同名替换，可重复调用）。"""
    pipe.register_before("audit", _gate_audit)
    pipe.register_before("consistency", _gate_consistency)
    pipe.register_before("gated", _gate_gated)
    return pipe


def default_pipeline():
    """进程级默认写入链（单例）。自定义闸门 register_before 即插即拔。"""
    global _DEFAULT
    if _DEFAULT is None:
        _DEFAULT = install_default_gates(WritePipeline())
    return _DEFAULT
