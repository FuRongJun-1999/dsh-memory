# -*- coding: utf-8 -*-
"""盲区消解票据（阶段三 §5.4）：BLINDSPOT/DEFER 盲区 → 四类消解票据（任务卡形态）挂认知图。

四类分类判据（确定性、声明式、可审计，不做语义猜测）：
  task      — 盲区查询指纹精确命中某 unresolved 层节点正文首行指纹
              （issue #445：q_sha 指纹比对，判据等价、原文不进票据链）
              → 直接立工程任务卡
  grilling  — defer 主导（defer > blindspot，信息不完整须澄清）；执行通道=宿主侧
              访谈（grill），md_cg 库内无访谈工具，本模块只建卡不越权代答（边界如实）
  research  — blindspot >= 3（反复未知）→ 研究议题（检索/调研补证）
  prototype — 其余 → 最小探针实验验证

幂等：tasks.upsert 同 slug 即同任务，重复生成不新建卡（updated 计数）。
依赖挂接：票据即任务节点（认知图节点天然在图上、可检索）。「升级为正式工程
任务时的机械 depends_on 边」由使用者在该卡更新时显式填写——本模块不伪造
工程边，消解路径以正文声明。
预演：apply=False 只出清单不落库（与 learn/reconstruct 的 opt-in 同构，
默认链路零变更）。
"""
from . import metacognition, tasks

TICKET_TYPES = ("research", "prototype", "grilling", "task")

_RESOLVE = {
    "research": "检索/调研补证（外部研究系列吸收流程），产出知识节点后复核 gap_hint",
    "prototype": "构造最小探针实验验证，结论回写认知图",
    "grilling": "澄清缺位：执行通道=宿主侧访谈（grill）；库内无访谈工具，不越权代答",
    "task": "直接立工程任务推进（关联 unresolved 悬挂线索）",
}

_JUDGE = {
    "research": "blindspot>=3（反复未知 → 研究议题）",
    "prototype": "其余（偶发未知 → 最小探针）",
    "grilling": "defer 主导（信息不完整 → 须澄清）",
    "task": "query 精确命中 unresolved 节点正文首行",
}


def classify(item, unresolved_first_fps):
    """按确定性判据给盲区分派票据类型。

    unresolved_first_fps={首行 q_sha 指纹: node_id}（issue #445：盲区簇与
    首行都以不可逆指纹比对，票据链不携带查询原文）。
    """
    qsha = str(item.get("q_sha") or "")
    if qsha and qsha in unresolved_first_fps:
        return "task"
    b = int(item.get("blindspot") or 0)
    d = int(item.get("defer") or 0)
    if d > b:
        return "grilling"
    if b >= 3:
        return "research"
    return "prototype"


def _plan_text(item, ttype, unresolved_first_fps):
    qk = str(item.get("q_key") or "")
    lines = [
        "来源：盲区簇 q_key=%s（blindspot=%s defer=%s samples=%s）" % (
            qk, item.get("blindspot"), item.get("defer"),
            item.get("samples")),
        "分类判据：%s" % _JUDGE[ttype],
    ]
    if ttype == "task" and str(item.get("q_sha") or "") in unresolved_first_fps:
        lines.append("关联悬挂：unresolved 节点 %s"
                     % unresolved_first_fps[str(item.get("q_sha"))])
    lines.append("消解路径：%s" % _RESOLVE[ttype])
    lines.append("完成判据：盲区簇后续反思记录中 BLINDSPOT/DEFER 归零（gap_hint 复核）")
    return "\n".join(lines)


def make_tickets(cg, *, types=None, limit=10, min_blindspot=0,
                 apply=False, actor=None) -> dict:
    """盲区 → 消解票据。apply=False 预演（零落库）；apply=True 经 tasks.upsert 落卡。"""
    want = tuple(t for t in (types or TICKET_TYPES) if str(t).strip())
    bad = [t for t in want if str(t).strip().lower() not in TICKET_TYPES]
    if bad:
        return {"ok": False,
                "error": "未知票据类型：%s（可选 %s）" % (bad, list(TICKET_TYPES))}

    mp = metacognition.blindspots(cg, limit=max(int(limit), 20))
    items = []
    for it in mp.get("items") or []:
        b = int(it.get("blindspot") or 0)
        d = int(it.get("defer") or 0)
        if b >= int(min_blindspot) or d >= 1:
            items.append(it)

    # issue #445：unresolved 首行按 q_sha 指纹登记（与盲区簇的 q_sha 同口径
    # 比对，「query 精确命中首行」的判据等价保留，原文不进票据链）。
    unresolved_first_fps = {}
    for u in mp.get("unresolved") or []:
        first = str(u.get("content") or "").strip().splitlines()
        if first and first[0].strip():
            unresolved_first_fps.setdefault(
                metacognition.q_fp(first[0].strip()), u.get("node_id"))

    out, created, updated, errors = [], 0, 0, 0
    for it in items[:int(limit)]:
        qk = str(it.get("q_key") or "").strip()
        if not qk:
            continue
        ttype = classify(it, unresolved_first_fps)
        if ttype not in [str(t).strip().lower() for t in want]:
            out.append({"type": ttype, "q_key": qk, "skipped": "types 过滤"})
            continue
        name = "票据:%s:%s" % (ttype, qk)
        if not apply:
            out.append({"type": ttype, "q_key": qk, "name": name, "dry_run": True})
            continue
        r = tasks.upsert(
            cg, name, plan=_plan_text(it, ttype, unresolved_first_fps),
            status="active",
            note="盲区簇 q_key=%s｜blindspot=%s｜defer=%s" % (
                qk, it.get("blindspot"), it.get("defer")),
            tags=["blindspot-ticket", "ticket:%s" % ttype],
            actor=actor or "blindspot_tickets")
        if r.get("ok"):
            if r.get("created"):
                created += 1
            else:
                updated += 1
            out.append({"node_id": r.get("node_id"), "type": ttype,
                        "q_key": qk, "created": bool(r.get("created"))})
        else:
            errors += 1
            out.append({"type": ttype, "q_key": qk, "error": r.get("error")})

    return {"ok": errors == 0, "action": "tickets", "op": "insight",
            "scanned": len(items), "created": created, "updated": updated,
            "errors": errors, "applied": bool(apply), "tickets": out,
            "unresolved_count": len(unresolved_first_fps)}
