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
}

# content_kind → 建议的 verification_basis
# （见 nodefile.VERIFICATION_BASIS：compiler|test|measurement|formal_proof|data|textbook|public_kb|other）
KIND_BASIS = {"code": "test", "image_desc": "measurement", "text": "other",
              "permission": "data", "work_done": "test", "work_wip": "other",
              "ccg_marks": "test"}

VERIFIERS = {}


def register_verifier(kind, fn, override=False):
    """注入/替换某类内容的验证器（外部能力接入点）。"""
    if kind not in CONTENT_KINDS:
        raise ValueError(f"未知内容类型：{kind}（可选 {sorted(CONTENT_KINDS)}）")
    if kind in VERIFIERS and not override:
        raise ValueError(f"验证器已存在：{kind}（需 override=True）")
    VERIFIERS[kind] = fn


def _verdict(state, kind, evidence, detail=None):
    return {"state": state, "kind": kind, "basis": KIND_BASIS.get(kind),
            "evidence": evidence, "detail": detail}


# ---------- 规则库（合规 / 纪律） ----------

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


def _rule_check(text, rules):
    """规则为空 → DEFER（无规则不能假装合规）。"""
    forbidden = [r for r in (rules.get("forbidden") or []) if r]
    required = [r for r in (rules.get("required") or []) if r]
    if not forbidden and not required:
        return DEFER, "未配置合规/纪律规则（MDCG_POLICY_FILE），无法判定"
    for pat in forbidden:
        try:
            if re.search(pat, text):
                return REJECT, f"命中禁止规则：{pat}"
        except re.error:
            continue
    missing = []
    for pat in required:
        try:
            if not re.search(pat, text):
                missing.append(pat)
        except re.error:
            continue
    if missing:
        return REJECT, f"缺少必需要素：{missing[:3]}"
    return ACCEPT, f"通过 {len(forbidden)} 条禁止 + {len(required)} 条必需规则"


# ---------- 内建验证器 ----------

def _verify_text(payload, ctx):
    text = str(payload.get("content") or payload.get("text") or "")
    state, ev = _rule_check(text, ctx.get("rules") or load_rulebook())
    return _verdict(state, "text", ev)


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


def _verify_work_wip(payload, ctx):
    text = str(payload.get("content") or "")
    state, ev = _rule_check(text, ctx.get("rules") or load_rulebook())
    if state == REJECT:
        return _verdict(REJECT, "work_wip", f"纪律不合规：{ev}")
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
    cmd = payload.get("test_cmd") or os.environ.get("MDCG_CODE_TEST_CMD")
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


def _pending(kind, why):
    def _fn(payload, ctx):
        return _verdict(DEFER, kind, why)
    return _fn


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
    rep = {"loaded": [], "failed": [], "verifiers": {}}
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
