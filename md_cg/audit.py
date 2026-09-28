# -*- coding: utf-8 -*-
"""写入审核：按内容类型分派的验证体系。

架构约束：验证能力不在认知图内（跑测试/识图/验收都不是记忆基底的职责）。
认知图只做三件事：按内容类型选验证器 → 调用 → 记账。缺能力返回 DEFER，绝不假装通过。

内容类型 → 验证动作：
    code        代码内容 → 实测              image_desc  图像描述 → 识图确认
    text        文字内容 → 合规 + 纪律        permission  权限操作 → 是否具有权限
    work_done   工作完成 → 验收              work_wip    工作进行 → 完整成果 + 纪律
    ccg_marks   CCG 六要素 → 编外验证方实测（生成方不得自证）

裁决四态复用 judge_qualification：ACCEPT / REJECT / DEFER / BLINDSPOT
验证器签名：fn(payload: dict, ctx: dict) -> {"state":..., "evidence":..., "detail":...}
"""
from __future__ import annotations

import json
import os
import re

ACCEPT, REJECT, DEFER, BLINDSPOT = "ACCEPT", "REJECT", "DEFER", "BLINDSPOT"
STATES = (ACCEPT, REJECT, DEFER, BLINDSPOT)

CONTENT_KINDS = {
    "code": "代码内容 → 实测（能跑 / 测试通过）",
    "image_desc": "图像描述 → 识图确认（描述与图像一致）",
    "text": "文字内容 → 合规 + 纪律",
    "permission": "权限操作 → 是否具有权限",
    "work_done": "工作完成 → 工作项是否通过验收",
    "work_wip": "工作进行 → 是否已有完整成果 + 是否符合纪律",
    "ccg_marks": "CCG 六要素候选 → 编外验证方实测确认（生成方不得自证）",
    "hyperedge": "跨端验证超边 → 回放重建比对（回执逐字段一致）",
}

# content_kind → 建议的 verification_basis
# （见 nodefile.VERIFICATION_BASIS：compiler|test|measurement|formal_proof|data|textbook|public_kb|other）
KIND_BASIS = {"code": "test", "image_desc": "measurement", "text": "other",
              "permission": "data", "work_done": "test", "work_wip": "other",
              "ccg_marks": "test", "hyperedge": "test"}

VERIFIERS = {}


# 生效条件：kind 属于 CONTENT_KINDS 且（kind 不在 VERIFIERS 或 override 为真值）时把 fn 写入 VERIFIERS[kind]；kind 未知、或 kind 已在 VERIFIERS 而 override 为假值时抛 ValueError。
def register_verifier(kind, fn, override=False):
    """注入/替换某类内容的验证器（外部能力接入点）。"""
    if kind not in CONTENT_KINDS:
        raise ValueError(f"未知内容类型：{kind}（可选 {sorted(CONTENT_KINDS)}）")
    if kind in VERIFIERS and not override:
        raise ValueError(f"验证器已存在：{kind}（需 override=True）")
    VERIFIERS[kind] = fn


# 生效条件：传入 state、kind、evidence（detail 可缺省为 None）时，返回以 state/kind/evidence 为键、basis 取 KIND_BASIS.get(kind)（查不到即 None）的判定字典。
def _verdict(state, kind, evidence, detail=None):
    return {"state": state, "kind": kind, "basis": KIND_BASIS.get(kind),
            "evidence": evidence, "detail": detail}


# ---------- 规则库（合规 / 纪律） ----------

# 生效条件：path 为假值（None 或空串）时回落到 os.environ 的 MDCG_POLICY_FILE，所得路径仍为假值或 os.path.exists 判定为假时返回 {}；否则按 json.load 读取，抛 OSError/ValueError 或结果非 dict 时返回 {}，是 dict 则返回该 dict。
def load_rulebook(path=None):
    """{"forbidden": [正则], "required": [正则]}；缺失返回空规则。"""
    path = path or os.environ.get("MDCG_POLICY_FILE")
    if not path or not os.path.exists(path):
        return {}
    try:
        with open(path, encoding="utf-8") as f:
            rules = json.load(f)
    except (OSError, ValueError):
        return {}
    return rules if isinstance(rules, dict) else {}


# 生效条件：kind 属于 rules 的 required_kinds（该键缺失或去空后为空列表时视为全部 kind）时才检查 required；forbidden 对所有 kind 恒检查。两类去空后全空即返回 DEFER；有任一 forbidden 命中即返回 REJECT 与「命中禁止规则：<模式>」（非法正则跳过）；required 适用且存在缺失项即返回 REJECT 与「缺少必需要素：<展示名、连接>（补齐后重写即可，本条未入库）」并附 detail={"missing": [...], "missing_patterns": [...]}（两数组按下标一一对应）；全部通过即 ACCEPT（required 为空时措辞如实说明未配置必需规则，required 非空但被 kind 跳过时如实说明不适用于该 kind）。返回三元组 (state, evidence, detail)。
def _rule_check(text, rules, kind="text"):
    """规则为空 → DEFER（无规则不能假装合规）。

    两类规则的生效面**不对称**：forbidden 是内容政策（机密外泄形态），对所有
    content_kind 恒生效；required 是**成文格式**要求（CCG 六要素），只对
    `required_kinds` 收窄内的 kind 生效——该键缺失或为空即「全部 kind」，
    与改动前（required 对所有 kind 生效）行为一致，向后兼容。

    缺失项**全列不截断**（原实现只列前 3 个，写入方拿不到完整补齐清单）；
    展示名优先取 required_labels 的同下标中文名（policy 侧展示件，缺失或与
    去空后的 required 长度不一致即整体回落正则串）——labels 畸形不得抛错，
    也不得改变判定，它只影响证据文本。

    边界（如实）：required 非空但被 kind 跳过、且 forbidden 为空时判 ACCEPT，
    证据里点明「不适用于该 kind」——「规则不适用于此类内容」与「未配置规则」
    是两件事（后者才 DEFER）。若部署方要求某 kind 也恒判 DEFER，应收窄
    required_kinds（去掉该 kind）而不是靠本函数猜。
    """
    forbidden = [r for r in (rules.get("forbidden") or []) if r]
    required = [r for r in (rules.get("required") or []) if r]
    if not forbidden and not required:
        return DEFER, "未配置合规/纪律规则（MDCG_POLICY_FILE），无法判定", None
    for pat in forbidden:
        try:
            if re.search(pat, text):
                return REJECT, f"命中禁止规则：{pat}", None
        except re.error:
            continue
    kinds = [str(k) for k in (rules.get("required_kinds") or []) if str(k)]
    req_active = bool(required) and (not kinds or str(kind) in kinds)
    if req_active:
        labels = rules.get("required_labels")
        labels = list(labels) if isinstance(labels, list) else []
        if len(labels) != len(required):
            labels = []                      # 长度不匹配 → 整体回落正则串
        missing, missing_patterns = [], []
        for i, pat in enumerate(required):
            try:
                if not re.search(pat, text):
                    missing_patterns.append(pat)
                    missing.append(str(labels[i]) if labels else pat)
            except re.error:
                continue
        if missing_patterns:
            return (REJECT,
                    "缺少必需要素：%s（补齐后重写即可，本条未入库）"
                    % "、".join(missing),
                    {"missing": missing, "missing_patterns": missing_patterns})
    if not required:
        return (ACCEPT,
                f"通过 {len(forbidden)} 条禁止规则（未配置必需规则）", None)
    if not req_active:
        return (ACCEPT,
                f"通过 {len(forbidden)} 条禁止规则"
                f"（{len(required)} 条必需规则不适用于 content_kind={kind}）", None)
    return ACCEPT, f"通过 {len(forbidden)} 条禁止 + {len(required)} 条必需规则", None


# 生效条件：rules 为 None 时回落 load_rulebook()；对 rules["forbidden"] 去空后的每条模式求出全部命中跨度，按跨度合并（重叠/相邻者合并、占位符取其中**最先声明**那条规则的序号）后整段替换为「[已过滤:禁表#i]」，返回替换后的文本；非法正则跳过不抛错；无命中时原样返回 text。
def redact_forbidden(text, rules=None):
    """把命中禁止规则的片段替换成占位符——负记忆（rejected）落盘前用。

    REJECT 的内容仍记入负记忆（「这条被拒过」本身有价值），但命中禁表的
    片段正是**不该入库的东西**（凭据形态），原样写进 rejected 层等于拦截
    之后又把凭据存了一遍（issue #43）。占位符只带禁表序号，不带原文，也
    不带原文哈希；否决原因（evidence）里已有命中的模式，可审计。

    为什么按**跨度合并**而不是逐条 `re.sub` 串行替换（2026-09-28 PR#44 复核
    实测的反例）：串行替换时先命中的窄规则会先把文字换成占位符，宽规则随后
    就再也匹配不上那段被替换过的文字——全形态令牌 `mdcg1.<role>.<id>.<secret>`
    里 id 段先被 `\\btk_...` 掩掉，宽规则 `mdcg1\\....` 便无法命中，
    **密钥段原样留在负记忆里**（拦截了 id、漏了真正的凭据）。跨度合并与规则
    书写顺序无关：任一规则命中的字符一律被掩，重叠部分并为一段。
    """
    if rules is None:
        rules = load_rulebook()
    pats = [r for r in (rules.get("forbidden") or []) if r]
    spans = []          # (起, 止, 规则序号) —— 序号为去空后 1 起的下标（占位符标签）
    for i, pat in enumerate(pats, 1):
        try:
            for m in re.finditer(pat, text):
                if m.end() > m.start():     # 零宽命中不掩（掩了等于插字符）
                    spans.append((m.start(), m.end(), i))
        except re.error:
            continue                        # 非法正则跳过，不因一条坏规则废掉整次脱敏
    if not spans:
        return text
    spans.sort()
    merged = []         # 重叠或相接的跨度并成一段，标签取最先声明的那条规则
    for st, en, i in spans:
        if merged and st <= merged[-1][1]:
            pst, pen, pi = merged[-1]
            merged[-1] = (pst, en if en > pen else pen, pi if pi < i else i)
        else:
            merged.append((st, en, i))
    out, last = [], 0
    for st, en, i in merged:
        out.append(text[last:st])
        out.append("[已过滤:禁表#%d]" % i)
        last = en
    out.append(text[last:])
    return "".join(out)


# ---------- 内建验证器 ----------

# 生效条件：以 payload['content']（为假值则回落 payload['text']，再为假值取空串）作为文本，用 ctx['rules']（为假值则回落 load_rulebook()）按 kind='text' 做规则检查，返回 _verdict(检查状态, 'text', 证据, 规则检查给出的 detail)；缺要素 REJECT 时 detail 形如 {"missing": [中文名...], "missing_patterns": [正则...]}（其余状态为 None）。
def _verify_text(payload, ctx):
    text = str(payload.get("content") or payload.get("text") or "")
    state, ev, detail = _rule_check(text, ctx.get("rules") or load_rulebook(),
                                    "text")
    return _verdict(state, "text", ev, detail)


# 生效条件：ctx['principal'] 缺失或为 None 时恒 DEFER；否则按 payload['action']（为假值取空串）是否属于 admin/forget/restore/review_decide 分别取 p.can_admin 或 p.can_write，且 p 具 allows 方法而 payload['sensitivity'] 为真值时再叠加 p.allows(sensitivity)，按最终 ok 返回 ACCEPT/REJECT。
def _verify_permission(payload, ctx):
    p = ctx.get("principal")
    if p is None:
        return _verdict(DEFER, "permission", "缺少 principal，无法判定权限")
    action = str(payload.get("action") or "")
    if action in ("admin", "forget", "restore", "review_decide"):
        ok = bool(getattr(p, "can_admin", False))
    else:
        ok = bool(getattr(p, "can_write", False))
    sens = payload.get("sensitivity")
    if ok and sens and hasattr(p, "allows"):
        ok = bool(p.allows(sens))
    return _verdict(ACCEPT if ok else REJECT, "permission",
                    f"action={action or 'write'} can_write={getattr(p, 'can_write', None)} "
                    f"can_admin={getattr(p, 'can_admin', None)}")


# 生效条件：payload['content']（为假值取空串）经 ctx['rules']（为假值回落 load_rulebook()）按 kind='work_wip' 检查后，state==REJECT 即 REJECT（证据前缀「纪律不合规：」，缺要素时把规则检查的 detail 一并透传）；否则 ctx['cg'] 非 None 且 payload['topic']（为假值回落 payload['query']，再为假值取空串）非空且 cg.search 结果含 ACCEPT 状态节点时 DEFER（查询抛异常则跳过该路）；再 state==DEFER 时 DEFER，否则 ACCEPT。
def _verify_work_wip(payload, ctx):
    text = str(payload.get("content") or "")
    state, ev, detail = _rule_check(text, ctx.get("rules") or load_rulebook(),
                                    "work_wip")
    if state == REJECT:
        return _verdict(REJECT, "work_wip", f"纪律不合规：{ev}", detail)
    cg = ctx.get("cg")
    topic = str(payload.get("topic") or payload.get("query") or "")
    if cg is not None and topic:
        try:
            res, _ = cg.search(topic, layer="knowledge", k=5, record=False)
            done = [n.get("id") for n, _s, q in res if q.get("state") == ACCEPT]
            if done:
                return _verdict(DEFER, "work_wip",
                                f"已存在同主题成果节点 {done[:3]}，应合并而非新增")
        except Exception:  # noqa: BLE001 —— 查询失败不阻塞审核
            pass
    if state == DEFER:
        return _verdict(DEFER, "work_wip", ev)
    return _verdict(ACCEPT, "work_wip", f"纪律通过且未见重复成果（{ev}）")


# 生效条件：payload['content']（为假值取空串）为空白即 REJECT '空内容'；ast.parse 抛 SyntaxError 即 REJECT 语法错误；payload['test_cmd'] 与 os.environ 的 MDCG_CODE_TEST_CMD 均为假值时 ACCEPT（仅静态验证）；否则 shlex.split 抛 ValueError 或 subprocess 抛 OSError/SubprocessError 即 DEFER，returncode 为 0 即 ACCEPT，非 0 即 REJECT 并附 returncode 与 stdout/stderr 尾部。
def _verify_code(payload, ctx):
    """代码内容 → 实测：AST 可解析为最低门槛；给了 test_cmd 则真跑测试。

    test_cmd 只能由调用方显式提供（payload.test_cmd 或 MDCG_CODE_TEST_CMD），
    不配置时只做静态验证并如实说明，绝不假装"已实测"。
    """
    import ast
    import shlex
    import subprocess

    src = str(payload.get("content") or "")
    if not src.strip():
        return _verdict(REJECT, "code", "空内容")
    try:
        tree = ast.parse(src)
    except SyntaxError as exc:
        return _verdict(REJECT, "code", f"语法错误 L{exc.lineno}: {exc.msg}")
    n_def = sum(isinstance(x, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
                for x in ast.walk(tree))
    # P2-18（批次 30，外部审查报告）：test_cmd 只允许服务端 env 配置——
    # payload 是模型可控输入面，一旦接到工具参数顶层即为 RCE 注入点。
    cmd = os.environ.get("MDCG_CODE_TEST_CMD")
    if not cmd:
        return _verdict(ACCEPT, "code",
                        f"AST 解析通过（{n_def} 个定义）；未配置 test_cmd，仅静态验证")
    try:
        argv = shlex.split(cmd)
    except ValueError as exc:
        return _verdict(DEFER, "code", f"test_cmd 解析失败：{exc}")
    try:
        # encoding 必须显式指定：`text=True` 会退回 locale 编码（Windows 常为 gbk），
        # 被测命令只要输出非 gbk 字节，读取线程就抛 UnicodeDecodeError →
        # p.stdout/p.stderr 可能为空 → 下一行的失败证据丢失，
        # 「实测失败」会退化成一句没有依据的 REJECT（对齐 whitebox.py 的写法）。
        p = subprocess.run(argv, cwd=ctx.get("cwd"), capture_output=True,
                           text=True, encoding="utf-8", errors="replace",
                           shell=False,
                           timeout=int(os.environ.get("MDCG_CODE_TEST_TIMEOUT", "60")))
    except (OSError, subprocess.SubprocessError) as exc:
        return _verdict(DEFER, "code", f"测试无法执行：{type(exc).__name__}: {exc}")
    if p.returncode == 0:
        return _verdict(ACCEPT, "code", f"实测通过：{cmd}")
    tail = ((p.stdout or "")[-300:] + (p.stderr or "")[-300:]).strip()
    return _verdict(REJECT, "code", f"实测失败 rc={p.returncode}：{tail}")


# 生效条件：调用 _pending 并传入 kind 与 why 后，其返回的内层闭包 _fn 对任意 payload/ctx 均求值为 _verdict(DEFER, kind, why)，其中 kind 与 why 来自外层 _pending 的闭包，而非 _fn 的形参；。
def _pending(kind, why):
# 生效条件：调用 _pending 并传入 kind 与 why 后，其返回的内层闭包 _fn 对任意 payload/ctx 均求值为 _verdict(DEFER, kind, why)，其中 kind 与 why 来自外层 _pending 的闭包，而非 _fn 的形参；。
    def _fn(payload, ctx):
        return _verdict(DEFER, kind, why)
    return _fn


# 生效条件：payload['node_id'] 去空后为空即 DEFER；否则取 payload['unit_verdict']（为假值回落 payload['verdict']）去空转大写，其属于 STATES 时——verifier 为空即 DEFER、ctx['compiled_by']（为假值回落 payload['compiled_by']）非空且等于 verifier 即 REJECT E041、verdict==ACCEPT 而 evidence 为空即 DEFER、其余按该 verdict 裁定；其不属于 STATES 时经 units.probe 探测（探测抛异常亦恒 DEFER）后恒 DEFER 并给出通道与下一步提示。
def _verify_ccg_marks(payload, ctx):
    """CCG 六要素候选的验证闸门：**只认认知图外的复核裁决**（裁定 A）。

    本闸门**不在写入路径里阻塞跑 LLM**——写入是同步闸门，等待外部单元会卡住写路径。
    正确的异步三段式：compile（ccgc）→ 外部单元复核（蜂巢 reflect/verify，或
    harness 端子代理）→ 带 `unit_verdict` 回到本闸门 → ACCEPT 才谈得上写入
    （`ccgc.link` 仍**独立**校验签章，本闸门不是唯一防线）。

    payload 键：
        node_id       目标节点（必填）
        unit_verdict  外部单元裁决 ACCEPT/REJECT/DEFER/BLINDSPOT
                      （缺 → DEFER + 给出「下一步怎么拿到裁决」的通道提示）
        verifier      验证方标识（须 != compiled_by，E041）
        evidence      裁决依据（ACCEPT 而无依据 → DEFER：无依据不通过）
        model/allow_degrade/channel  可选，仅用于探测降级通道
    ctx 键：
        compiled_by   编译执行者（E041 比对）
    """
    node_id = str(payload.get("node_id") or "").strip()
    if not node_id:
        return _verdict(DEFER, "ccg_marks", "缺少 node_id：六要素候选须指明目标节点")
    verdict = str(payload.get("unit_verdict") or payload.get("verdict") or "").strip().upper()
    verifier = str(payload.get("verifier") or "").strip()
    evidence = str(payload.get("evidence") or "").strip()
    compiled_by = str(ctx.get("compiled_by") or payload.get("compiled_by") or "").strip()

    if verdict in STATES:
        if not verifier:
            return _verdict(DEFER, "ccg_marks",
                            "有裁决但缺验证方标识（verifier）——无法证明是编外复核")
        if compiled_by and verifier == compiled_by:
            return _verdict(REJECT, "ccg_marks",
                            "E041 自证拒绝：验证方标识 == 编译执行者（LLM 不得自己验证自己）")
        if verdict == ACCEPT and not evidence:
            return _verdict(DEFER, "ccg_marks",
                            "ACCEPT 但未给出裁决依据（evidence 为空）——无依据不通过")
        return _verdict(verdict, "ccg_marks", evidence or "（未给依据）",
                        detail={"node_id": node_id, "verifier": verifier,
                                "job_id": payload.get("job_id") or ""})

    # 无裁决 → 探测复核通道，按三态给出「下一步怎么拿到裁决」（不阻塞、不假装通过）
    try:
        from . import units
        p = units.probe(model=payload.get("model") or "",
                        allow_degrade=bool(payload.get("allow_degrade")),
                        channel=payload.get("channel") or "")
    except Exception as exc:                      # noqa: BLE001 —— 探测失败亦不假装
        return _verdict(DEFER, "ccg_marks",
                        "未获复核裁决，且复核通道探测失败：%s: %s"
                        % (type(exc).__name__, exc))
    if p["state"] == units.HIVE:
        nxt = ("复核通道=蜂巢（model=%s）：cg(op=ccg, action=review, node_id=%s, "
               "blocking=true) 取得裁决后带 unit_verdict/verifier 重入本闸门"
               % (p["model"], node_id))
    elif p["state"] == units.SUBAGENT:
        nxt = ("已降级 harness 端子代理（channel=%s）：把 units.review 返回的 prompt 交给"
               "子代理执行，取回 JSON 裁决后带 unit_verdict/verifier 重入本闸门"
               % p["channel"])
    else:
        nxt = p["hint"]
    return _verdict(DEFER, "ccg_marks",
                    "六要素候选尚未经编外复核（未获 unit_verdict）——缺复核恒不通过",
                    detail={"channel_state": p["state"], "next": nxt,
                            "jobs_dir": p["jobs_dir"], "model": p["model"],
                            "node_id": node_id})


# ---------- 分派入口 ----------

# 生效条件：content_kind 去空后不在 CONTENT_KINDS 即 BLINDSPOT；否则取 VERIFIERS 中该 kind 的验证器，缺失即 DEFER，调用抛异常即 DEFER，成功则以返回值 state（不在 STATES 时降级为 DEFER）连同 evidence/detail 构造裁定。
def audit(content_kind, payload=None, ctx=None):
    """按内容类型分派验证器。未知类型 → BLINDSPOT；缺验证器 → DEFER。"""
    kind = (content_kind or "").strip()
    payload, ctx = payload or {}, ctx or {}
    if kind not in CONTENT_KINDS:
        return _verdict(BLINDSPOT, kind, f"未知内容类型：{kind!r}（可选 {sorted(CONTENT_KINDS)}）")
    fn = VERIFIERS.get(kind)
    if fn is None:
        return _verdict(DEFER, kind, f"未注入 {kind} 验证器")
    try:
        v = fn(payload, ctx) or {}
    except Exception as exc:  # noqa: BLE001 —— 验证器异常不视为通过
        return _verdict(DEFER, kind, f"验证器异常：{type(exc).__name__}: {exc}")
    state = v.get("state") if v.get("state") in STATES else DEFER
    return _verdict(state, kind, str(v.get("evidence") or ""), v.get("detail"))


# 生效条件：对模块级常量 CONTENT_KINDS 中的每个 k 返回 action=CONTENT_KINDS[k]、basis=KIND_BASIS[k]、verifier 为 'builtin'（k 在 VERIFIERS 中）否则 'missing'。
def kinds():
    """内容类型清单 + 验证器可用性（供 service_info / health 自描述）。"""
    return {k: {"action": CONTENT_KINDS[k], "basis": KIND_BASIS[k],
                "verifier": "builtin" if k in VERIFIERS else "missing"}
            for k in CONTENT_KINDS}


# ---------- 外部能力接入（**能力外置，认知图只留接口**） ----------
#
# 架构约束（见模块 docstring）：识图/实测/验收等**能力不在认知图内**。
# 认知图只做三件事：按内容类型选验证器 → 调用 → 记账。
# 因此本模块**不内置任何具体能力实现**（不读图像、不跑测试、不连网络），
# 只提供注入点：外部模块在被 import 时调用 register_verifier(...)，
# 或提供 register(audit_module) 函数由本函数回调。
#
# 能力模块通常位于**私有运行时仓**（如灵枢身体 AEIS），经 MDCG_VERIFIER_MODULES
# 以 import 路径声明；公开的大脑仓不含这些能力。
VERIFIER_MODULES_ENV = "MDCG_VERIFIER_MODULES"


# 生效条件：modules 为 None 时按 os.environ 的 VERIFIER_MODULES_ENV（为假值取空串）取逗号分隔模块名，去空后列表为空即返回空报告；否则逐个 import_module 并调用其可调用的 register(本模块)，单个导入或调用失败记入 failed 且 strict 为真值时立即抛出、为假值时继续，成功者记入 loaded，最后以 CONTENT_KINDS 生成 verifiers 可用性映射。
def load_external_verifiers(modules=None, strict=False):
    """按 `MDCG_VERIFIER_MODULES`（逗号分隔 import 路径）加载外部验证器模块。

    单个模块失败不影响其余（除非 strict=True）；失败原因如实返回，不静默。
    返回 {"loaded": [...], "failed": [{"module","error"}], "verifiers": {...}}。
    """
    import importlib
    import sys as _sys
    spec = modules
    if spec is None:
        spec = os.environ.get(VERIFIER_MODULES_ENV) or ""
    names = [x.strip() for x in str(spec).split(",") if x.strip()]
    # P2-19（批次 30）：模块名格式白名单——拒绝空串外的异常形态（路径分隔/
    # 通配/扩展名等非 import 路径输入），加载动作本身写 stderr（可见性）。
    import re as _re
    _bad = [n for n in names if not _re.match(r"^[A-Za-z_][A-Za-z0-9_.]*$", n)]
    rep = {"loaded": [], "failed": [], "verifiers": {}}
    for n in _bad:
        names.remove(n)
        rep["failed"].append({"module": n,
                              "error": "模块名不符合 import 路径格式（P2-19 白名单）"})
    if not names:
        return rep
    this = _sys.modules[__name__]
    for name in names:
        try:
            mod = importlib.import_module(name)
        except Exception as exc:                              # noqa: BLE001
            rep["failed"].append({"module": name,
                                  "error": "%s: %s" % (type(exc).__name__, exc)})
            if strict:
                raise
            continue
        _sys.stderr.write("[mdcg-audit] 已加载外部验证器模块: %s\n" % name)
        fn = getattr(mod, "register", None)
        if callable(fn):
            try:
                fn(this)
            except Exception as exc:                          # noqa: BLE001
                rep["failed"].append({"module": name,
                                      "error": "register(): %s: %s"
                                               % (type(exc).__name__, exc)})
                if strict:
                    raise
                continue
        rep["loaded"].append(name)
    rep["verifiers"] = {k: ("builtin" if k in VERIFIERS else "missing")
                        for k in CONTENT_KINDS}
    return rep


# ---------- 内建注册（缺外部能力的用 DEFER 占位） ----------

register_verifier("text", _verify_text)
register_verifier("permission", _verify_permission)
register_verifier("work_wip", _verify_work_wip)
register_verifier("code", _verify_code)
# image_desc / work_done 的**能力**由外部模块注入（见上）。未注入时 DEFER——
# 诚实说明缺什么，绝不假装通过。
register_verifier("image_desc", _pending("image_desc", "未注入识图验证器（需视觉能力）"))
register_verifier("work_done", _pending("work_done", "未注入验收器（需验收标准）"))
# ccg_marks：闸门本身不是「能力」而是**准入判据**——只认编外单元的裁决
# （unit_verdict + verifier）；无裁决时探测复核通道（蜂巢→配置→子代理）并给出
# 下一步，恒不假装通过。真实复核由外部单元完成，认知图只负责记账。
register_verifier("ccg_marks", _verify_ccg_marks)