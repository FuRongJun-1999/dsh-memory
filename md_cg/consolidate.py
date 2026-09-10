# -*- coding: utf-8 -*-
"""md_cg · 离线固化：LLM 补 CCG 四要素 → 确定性验证 → 固化为 md 字段

为什么是「离线固化」而不是「在线向量」：
    白箱第 1 篇：相似度可以产生候选，但**不授予执行资格**；资格必须由条件证据裁决。
    LLM 是黑箱，它的输出只能是**候选条件**，不能直接成为检索依据——否则在线检索
    就被黑箱污染，CCG 28%→88% 的改进会退化回去。故本工具把 LLM 严格限制在
    **离线一次性的固化工序**里：

        读节点 → LLM 产出四要素候选 → 确定性验证 → 通过才写进 md 字段

    在线检索（search / recall / _path_semantic）仍然只读 md 里已固化的字段，全程白箱。

理论 / 纪律对齐（docs/工作纪律_认知图条目_v1.1.json）：
    · 第 3 条 白箱方法：不猜测；**未验证不写入**。
    · 第 5 条 验证纪律：**未经验证不固化**——入库前必须走验证（回放 / 断言 / 回归）。
    · 第 13 条 访谈澄清：节点四要素 = 条件 / 子内容 / 如何执行 / 不适用条件
      ——本工具固化的正是这四个字段（对齐 CCG 的生效条件 / 子功能 / 执行 / 不适用条件）。
    · 《智能的认知过程》：新条件能否**稳定解释误差**？成立 → 纳入知识结构；
      不成立 → **不固化**，标记为待验证。
    故 verdict 三态对齐白箱资格判定：ACCEPT（固化）/ REJECT（丢弃）/ DEFER（只存候选）。

验证分三段闸门——前两段确定性零 LLM，第三段是「双模型交叉验证」：

    闸门 1 · grounding 支撑度（确定性）：候选短语必须能在节点正文里找到字符级依据，
        否则判为幻觉 → REJECT。（对应「不猜测」）
    闸门 2 · replay 回放（确定性）：把候选条件当作查询，回放生产检索路径的判定：
         · pos_recall    以「生效条件」为查询 → 本节点应被召回，且不被自身负条件挡住；
         · neg_separated 以「不适用条件」为查询 → 应触发条件级负路由，且负条件与正文
                         低相关（负条件必须是「域外」的，不能把知识本身否定掉）；
         · no_conflict   生效条件与不适用条件不得互相覆盖。
       三者同时成立才算「条件稳定」。（对应「回放 / 断言 / 回归」）
    闸门 3 · 验证单元（GLM，独立模型）：逐条核验候选是否有正文依据、负条件是否真域外。
        硬约束：**验证单元只能否决，不能新增/改写**——它没有产出权，
        否则验证环节自己就成了新的幻觉源。

    回放器复用 _path_semantic 的同一批原语（_declared_conditions / _neg_hit /
    _weighted_coverage / expand_query_terms_weighted），并由 P6 测试与真实
    MdCGOS._path_semantic 做一致性回归，保证不漂移。

双模型角色分工（用户配置，可用环境变量覆盖）：
    反思单元 reflect → 默认 deepseek-v4.1-flash-expires-on-0910
                       （IDE 显示名 DeepSeek-V4.1-Flash；限时模型，见常量注释）
    验证单元 verify  → 默认 glm-5.3-flash    （IDE 显示名 GLM-5.3-flash）
    环境变量：MDCG_REFLECT_MODEL/BASE/KEY、MDCG_VERIFY_MODEL/BASE/KEY。
    注意 IDE 显示名 ≠ API 模型 id；`--check` 可零 token 探测各网关真实 id。
    两个模型分属不同厂商，避免同源模型的系统性偏见互相印证（交叉验证的本意）。

    · 验证单元不可用（未配 key）时，默认 **不固化**（DEFER）——纪律 5「未经验证不固化」；
      确需单模型跑通可显式 --no-verify（provenance 记为 skipped）或 --self-verify
      （同模型自审，provenance 记为 self_verify=true，属于降级模式）。
    · 「验证方式」是 CCG 必需要素，其值 = 声明的验证基底。本工具可写
      `# 验证方式：<声明>`（--verification-basis，默认即上面的双模型声明）；
      frontmatter.verification_basis 只能取 nodefile 的枚举
      (compiler/test/measurement/formal_proof/data/other)，双 LLM 交叉验证对应 "other"。
      纯文本声明无需 LLM → --basis-only 可零成本补齐全库（纪律 3：不猜测）。

零第三方依赖（D-005）：HTTP 走标准库 urllib.request；reflect_fn / verify_fn 可注入
（离线可测）。默认 --dry-run，只有 --apply 才写盘（纪律 6：改动可核对）。
写盘只动 CCG 字段与 provenance，**不覆盖已有非空字段**（除非 --overwrite）。
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import sys
import time
import urllib.error
import urllib.request

from . import crypto, evolution, nodefile, routing
from .fsutil import append_jsonl
from .mdcg import BUCKETED_LAYERS, bigrams, expand_query_terms_weighted
from .mdcos import (MdCGOS, _ccg_field, _declared_conditions, _neg_hit, _sig,
                    _weighted_coverage)

# ---- 常量 ----------------------------------------------------------------

# 与工作纪律第 13 条「节点四要素」同构：
#   生效条件   ↔ conditions（什么时候适用）
#   子功能     ↔ subgraph / depends_on（子内容）
#   执行       ↔ execution（如何执行）
#   不适用条件 ↔ negative（什么时候不适用）
CCG_FIELDS = ("生效条件", "子功能", "执行", "不适用条件")
MULTI_FIELDS = ("生效条件", "子功能", "不适用条件")      # 列表型
SINGLE_FIELDS = ("执行",)                                # 单值型

# LLM 常把「子功能」写成「子内容」，别名容错（固化时统一落到标准字段名）
FIELD_ALIASES = {
    "生效条件": ("生效条件", "适用条件", "conditions", "condition"),
    "子功能": ("子功能", "子内容", "子流程", "subgraph", "sub"),
    "执行": ("执行", "如何执行", "执行方式", "execution", "how"),
    "不适用条件": ("不适用条件", "不适用", "负条件", "negative", "reject"),
}

# 默认 grounding 阈值：不适用条件描述的是「域外」情境，与正文天然低相关，
# 故阈值放宽；其余三要素必须能在正文里找到实打实的依据。
DEFAULT_GROUNDING = {"生效条件": 0.5, "子功能": 0.5, "执行": 0.5, "不适用条件": 0.34}

MAX_BODY_CHARS = 3000      # 正文截断（控制 token，且条件主要来自开头）
MAX_TERMS = 8              # 单字段候选条数上限
MAX_TERM_LEN = 40          # 单条候选长度上限

# CCG 声明行（`# 生效条件：…` 等）——它们不是正文，grounding/replay 必须把它们剥掉，
# 否则已写入的「不适用条件」会在二次运行时被当成正文依据，导致节点自我否定。
_CCG_LINE_RE = re.compile(
    r"^\s*#\s*(功能名|生效条件|子功能|执行|验证方式|不适用条件)\s*[:：]")


def body_text(content: str) -> str:
    """剥掉 CCG 声明行后的正文——验证只认正文，不认已写下的声明。"""
    return "\n".join(l for l in (content or "").split("\n")
                     if not _CCG_LINE_RE.match(l))

# ---- 双模型角色（反思单元 / 验证单元）-------------------------------------

REFLECT_ROLE = "reflect"       # 反思单元：产出候选
VERIFY_ROLE = "verify"         # 验证单元：否决候选（无产出权）
ROLES = (REFLECT_ROLE, VERIFY_ROLE)

# 推荐模型（真实 API id，经实际调用确认；可用 MDCG_<ROLE>_MODEL 覆盖）
# 注意：reflect 的 id 带过期标记（expires-on-0910），属**限时模型**——过期后 /models
# 列表会下架该 id，届时改用 deepseek-v4-flash 或用 MDCG_REFLECT_MODEL 覆盖。
ROLE_DEFAULT_MODEL = {REFLECT_ROLE: "deepseek-v4.1-flash-expires-on-0910",
                      VERIFY_ROLE: "glm-5.3-flash"}
ROLE_DEFAULT_BASE = {REFLECT_ROLE: "https://api.deepseek.com",
                     VERIFY_ROLE: "https://open.bigmodel.cn/api/paas/v4"}
_ROLE_ENV = {REFLECT_ROLE: ("MDCG_REFLECT_MODEL", "MDCG_REFLECT_BASE", "MDCG_REFLECT_KEY"),
             VERIFY_ROLE: ("MDCG_VERIFY_MODEL", "MDCG_VERIFY_BASE", "MDCG_VERIFY_KEY")}
# 验证单元 key 的常见别名（智谱系）
VERIFY_KEY_ALIASES = ("ZHIPU_API_KEY", "ZHIPUAI_API_KEY", "GLM_API_KEY", "BIGMODEL_API_KEY")

# 「验证方式」的声明文本（可 --verification-basis 覆盖 / --no-basis 关闭）
BASIS_TEMPLATE = "双模型交叉验证（反思单元={reflect}，验证单元={verify}）"
# frontmatter.verification_basis 只能取 nodefile 的枚举；双 LLM 交叉验证 → other
BASIS_ENUM_DEFAULT = "other"

REFLECT_PROMPT = (
    "你是认知图节点的**反思单元**。给定一个知识节点的标题与正文，反思并抽取四要素。\n"
    "只输出一个 JSON 对象，不要任何解释或代码围栏。\n"
    "字段含义：\n"
    '  "生效条件": 什么查询/情境下该知识**适用**（短语数组，2~5 条）\n'
    '  "子功能": 该知识包含的子内容/子步骤（短语数组，2~5 条）\n'
    '  "执行": 如何执行/如何使用该知识（单个字符串）\n'
    '  "不适用条件": 什么查询/情境下该知识**不**适用（短语数组，1~3 条）\n'
    "硬约束：\n"
    "  1. 每条短语必须能在正文中找到依据，禁止编造正文里没有的工具/概念；\n"
    "  2. 不适用条件必须是**正文之外的邻近易混情境**，不得与生效条件语义重叠；\n"
    "  3. 短语要短（不超过 20 字），不要写完整句子。\n"
    "输出格式："
    '{{"生效条件": ["..."], "子功能": ["..."], "执行": "...", "不适用条件": ["..."]}}\n'
    "标题：{title}\n正文：\n{body}"
)

VERIFY_PROMPT = (
    "你是认知图节点的**验证单元**。你的职责是**否决**，不是补充。\n"
    "只能从候选里删除不成立的条目，**绝不允许新增或改写任何条目**。\n"
    "给定标题、正文与反思单元给出的候选四要素，逐条核验：\n"
    "  · 该条目是否真的能在正文中找到依据？找不到依据 → 删除；\n"
    "  · 不适用条件是否真的域外？若它其实是该节点的适用情境 → 删除；\n"
    "  · 生效条件与不适用条件是否语义重叠？重叠者删除其一（保留更贴合正文的那个）。\n"
    "只输出一个 JSON 对象，键为字段名，值为 "
    '{{"keep": ["保留的条目"], "drop": ["删除的条目"], "reason": "一句话理由"}}。\n'
    "候选：{cand}\n标题：{title}\n正文：\n{body}"
)


# ---- LLM 侧（黑箱只在离线工序，产出候选）--------------------------------

def role_config(role: str, model: str = None, base: str = None,
                key: str = None) -> tuple:
    """解析某角色的 (model, base, key)：显式参数 > 角色环境变量 > 通用兜底。

    key 刻意**不**让验证单元回落到 DEEPSEEK_API_KEY——跨厂商混用会把一个厂商的
    凭证发到另一个厂商的网关，既必然失败又构成凭证外泄。
    """
    m_env, b_env, k_env = _ROLE_ENV[role]
    if key is None:
        key = os.environ.get(k_env)
        if key is None and role == VERIFY_ROLE:
            for alias in VERIFY_KEY_ALIASES:
                key = os.environ.get(alias)
                if key:
                    break
        if key is None:
            key = os.environ.get("MDCG_LLM_KEY")
        if key is None and role == REFLECT_ROLE:
            key = os.environ.get("DEEPSEEK_API_KEY")
    model = (model or os.environ.get(m_env) or os.environ.get("MDCG_LLM_MODEL")
             or ROLE_DEFAULT_MODEL[role])
    base = (base or os.environ.get(b_env) or os.environ.get("MDCG_LLM_BASE")
            or ROLE_DEFAULT_BASE[role])
    return model, base, key


def http_llm(prompt: str, model: str = None, base: str = None, key: str = None,
             role: str = None, timeout: int = 120, max_tokens: int = 1200) -> str:
    """标准库 HTTP 调 LLM（OpenAI 兼容 /chat/completions）。零第三方依赖。

    role 给定时按该角色配置解析（reflect / verify），否则走通用配置。
    """
    if role:
        model, base, key = role_config(role, model, base, key)
    else:
        model = (model or os.environ.get("MDCG_LLM_MODEL")
                 or ROLE_DEFAULT_MODEL[REFLECT_ROLE])
        base = (base or os.environ.get("MDCG_LLM_BASE")
                or ROLE_DEFAULT_BASE[REFLECT_ROLE])
        key = (key or os.environ.get("MDCG_LLM_KEY")
               or os.environ.get("DEEPSEEK_API_KEY"))
    if not key:
        raise RuntimeError(
            f"未配置 {role or 'llm'} 的 API key"
            f"（{_ROLE_ENV[role][2] if role in _ROLE_ENV else 'MDCG_LLM_KEY'}）")
    payload = json.dumps({
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": max_tokens,
    }).encode("utf-8")
    req = urllib.request.Request(
        base.rstrip("/") + "/chat/completions", data=payload,
        headers={"Authorization": f"Bearer {key}",
                 "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")[:300]
        raise RuntimeError(f"HTTP {exc.code} model={model} base={base} :: {detail}") from None
    return data["choices"][0]["message"]["content"]


def probe_models(role: str, timeout: int = 20) -> dict:
    """零 token 探测：列出该角色网关的可用模型 id（GET /models）。"""
    model, base, key = role_config(role)
    if not key:
        return {"role": role, "model": model, "base": base, "ok": False,
                "error": "no_key", "models": []}
    req = urllib.request.Request(
        base.rstrip("/") + "/models",
        headers={"Authorization": f"Bearer {key}"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        ids = [m.get("id") for m in (data.get("data") or []) if m.get("id")]
    except Exception as exc:                        # noqa: BLE001 —— 探测要抗单点
        return {"role": role, "model": model, "base": base, "ok": False,
                "error": f"{type(exc).__name__}: {exc}"[:200], "models": []}
    res = {"role": role, "model": model, "base": base, "ok": True,
           "model_available": model in ids, "models": ids}
    if not res["model_available"]:
        res["note"] = ("该 id 未出现在 /models 列表：可能是限时/按需模型，或已下架；"
                       "以实际 /chat/completions 调用结果为准")
    return res


def _extract_json_obj(raw: str):
    """从 LLM 输出里抠出第一个 JSON 对象（容忍代码围栏 / 前后废话）。"""
    s = (raw or "").strip()
    i, j = s.find("{"), s.rfind("}")
    if i < 0 or j <= i:
        return None
    try:
        return json.loads(s[i:j + 1])
    except ValueError:
        return None


def _as_terms(v, limit: int = MAX_TERMS):
    """把 LLM 给的值规范成去重、限长的短语列表。"""
    if v is None:
        return []
    if isinstance(v, str):
        items = [v]
    elif isinstance(v, (list, tuple)):
        items = list(v)
    else:
        items = [str(v)]
    out = []
    for x in items:
        s = str(x).strip().strip("，。;；、,.;\"'“”")
        if not s or len(s) > MAX_TERM_LEN:
            continue
        if s not in out:
            out.append(s)
        if len(out) >= limit:
            break
    return out


def parse_candidate(raw: str) -> dict:
    """LLM 原始输出 → {字段: 列表/字符串}；解析失败返回 {}。"""
    obj = _extract_json_obj(raw)
    if not isinstance(obj, dict):
        return {}
    out = {}
    for field in CCG_FIELDS:
        val = None
        for alias in FIELD_ALIASES[field]:
            if alias in obj and obj[alias] not in (None, "", [], {}):
                val = obj[alias]
                break
        if val is None:
            continue
        if field in SINGLE_FIELDS:
            terms = _as_terms(val, limit=1)
            if terms:
                out[field] = terms[0]
        else:
            terms = _as_terms(val)
            if terms:
                out[field] = terms
    return out


def parse_verdict(raw: str) -> dict:
    """验证单元输出 → {字段: {keep, drop, has_keep, reason}}；解析失败返回 {}。"""
    obj = _extract_json_obj(raw)
    if not isinstance(obj, dict):
        return {}
    out = {}
    for field in CCG_FIELDS:
        val = None
        for alias in FIELD_ALIASES[field]:
            if alias in obj and obj[alias] not in (None, "", [], {}):
                val = obj[alias]
                break
        if val is None:
            continue
        if isinstance(val, list):          # 容忍只给 keep 数组
            out[field] = {"keep": _as_terms(val), "drop": [], "has_keep": True,
                          "reason": ""}
        elif isinstance(val, dict):
            out[field] = {"keep": _as_terms(val.get("keep")),
                          "drop": _as_terms(val.get("drop")),
                          "has_keep": "keep" in val,
                          "reason": str(val.get("reason") or "")[:200]}
    return out


def narrow_by_verdict(kept: dict, verdict: dict):
    """按验证单元裁决收窄候选——**只能否决，不能新增**。

    · 验证单元未表态的字段 → 保留（沉默不等于否决）
    · has_keep=True → 取「候选 ∩ keep」；否则只按 drop 剔除
    返回 (收窄后候选, 被剔除明细)。
    """
    if not verdict:
        return dict(kept), {}
    out, dropped = {}, {}
    for field, val in kept.items():
        terms = val if isinstance(val, list) else [val]
        vd = verdict.get(field)
        if vd is None:
            out[field] = val
            continue
        dropset = set(vd.get("drop") or [])
        keepset = set(vd.get("keep") or [])
        surv, gone = [], []
        for t in terms:
            if t in dropset:
                gone.append(t)
            elif vd.get("has_keep") and t not in keepset:
                gone.append(t)
            else:
                surv.append(t)
        if gone:
            dropped[field] = {"terms": gone, "reason": vd.get("reason") or ""}
        if surv:
            out[field] = surv if field in MULTI_FIELDS else surv[0]
    return out, dropped


# ---- 确定性验证（零 LLM）-------------------------------------------------

def grounding_score(term: str, body: str) -> float:
    """候选短语在正文里的字符级支撑度 = 命中 bigram 数 / 总 bigram 数。"""
    bg = bigrams(term or "")
    if not bg:
        return 0.0
    hit = sum(1 for g in bg if g in (body or ""))
    return hit / len(bg)


def grounding_filter(cand: dict, body: str, thresholds: dict = None):
    """逐字段过滤候选：返回 (kept, detail)。不达标者丢弃（对应「不猜测」）。"""
    th = dict(DEFAULT_GROUNDING)
    th.update(thresholds or {})
    kept, detail = {}, {}
    for field, val in cand.items():
        terms = val if isinstance(val, list) else [val]
        ok_terms, scores = [], {}
        for t in terms:
            g = grounding_score(t, body)
            scores[t] = round(g, 3)
            if g >= th.get(field, 0.5):
                ok_terms.append(t)
        detail[field] = {"scores": scores, "kept": len(ok_terms)}
        if ok_terms:
            kept[field] = ok_terms if field in MULTI_FIELDS else ok_terms[0]
    return kept, detail


def replay_check(pos_terms, neg_terms, body: str) -> dict:
    """回放生产判定：正例召回 + 负例剔除 + 无自相矛盾。

    复用 _path_semantic 的同一批原语，保证与生产路同源（P6 与真实路做一致性回归）。
    """
    pos_text = " ".join(pos_terms or [])
    neg_text = " ".join(neg_terms or [])
    tw_pos = expand_query_terms_weighted(pos_text) if pos_text else {}
    tw_neg = expand_query_terms_weighted(neg_text) if neg_text else {}

    # 1. 正例：以生效条件为查询，本节点正文应被命中，且不被自身负条件挡住
    pos_recall = bool(pos_text) and _weighted_coverage(tw_pos, body) > 0.0 \
        and not _neg_hit(tw_pos, neg_terms)

    # 2. 负例：以不适用条件为查询，应触发条件级负路由；且负条件与正文低相关
    #    （负条件必须是「域外」的，若与正文强相关，等于让知识否定自己）
    if neg_terms:
        neg_separated = _neg_hit(tw_neg, neg_terms) \
            and _weighted_coverage(tw_neg, body) < 0.5
    else:
        neg_separated = True

    # 3. 生效条件与不适用条件不得互相覆盖
    no_conflict = (not pos_text) or (not neg_text) \
        or _weighted_coverage(tw_pos, neg_text) < 0.5

    ok = pos_recall and neg_separated and no_conflict
    return {"pos_recall": pos_recall, "neg_separated": neg_separated,
            "no_conflict": no_conflict, "ok": ok}


# ---- 写盘（固化）---------------------------------------------------------

def _has_ccg_line(content: str, field: str) -> bool:
    return f"# {field}：" in (content or "") or f"# {field}:" in (content or "")


def existing_fields(fm: dict, content: str) -> dict:
    """节点当前已有的四要素：正文 CCG 行 或 frontmatter.comment 任一存在即算有。"""
    comment = (fm.get("state_attributes") or {}).get("comment") or {}
    out = {}
    for field in CCG_FIELDS:
        v = comment.get(field)
        if v not in (None, "", [], {}):
            out[field] = v
        elif _has_ccg_line(content, field):
            out[field] = True
    return out


def _upsert_ccg_line(content: str, field: str, value: str) -> str:
    """在正文里写入/替换 `# <字段>：<值>`，优先插在「# 功能名」之后。"""
    lines = (content or "").split("\n")
    for i, ln in enumerate(lines):
        s = ln.strip()
        if not s.startswith("#") or field not in s:
            continue
        name = s.lstrip("#").strip().split("：")[0].split(":")[0].strip()
        if name == field:
            lines[i] = f"# {field}：{value}"
            return "\n".join(lines)
    newline = f"# {field}：{value}"
    for i, ln in enumerate(lines):
        if ln.strip().startswith("# 功能名"):
            lines.insert(i + 1, newline)
            return "\n".join(lines)
    return newline + "\n" + (content or "")


def _evo_pattern(kept: dict) -> str:
    """规律（一句话）：这一类节点反复缺的正是这批条件。"""
    names = "、".join(kept.keys())
    return f"缺「{names}」的节点条件不可判；补齐后四要素完整、可路由"


def _evo_evidence(prov: dict) -> str:
    """证据：本次固化凭什么成立（模型 / 闸门 / 回放）。"""
    parts = []
    rf = (prov.get("reflect") or {}).get("model") or ""
    vf = (prov.get("verify") or {}).get("model") or ""
    if rf:
        parts.append(f"reflect={rf}")
    if vf:
        parts.append(f"verify={vf}")
    if prov.get("grounding"):
        parts.append("grounding通过")
    if prov.get("replay"):
        parts.append("replay通过")
    vb = prov.get("verification_basis") or ""
    if vb:
        parts.append(vb)
    return " · ".join(parts)


def _apply_node(cg, e, fm: dict, content: str, kept: dict, prov: dict,
                basis: str = "", basis_enum: str = BASIS_ENUM_DEFAULT):
    """把通过验证的字段固化进 md：正文 CCG 行 + frontmatter.comment + 负条件 + provenance。

    固化 = 对一条缺失条件的补充 → 同步落一条演化条目（md 账本，可回滚）。
    """
    nid = e.get("id") or os.path.basename(e["path"])[:-3]
    before = evolution.state_of(cg, nid) or {}
    comment = (fm.get("state_attributes") or {}).get("comment")
    if not isinstance(comment, dict):
        fm["state_attributes"] = dict(fm.get("state_attributes") or {})
        fm["state_attributes"]["comment"] = {}
        comment = fm["state_attributes"]["comment"]
    for field, val in kept.items():
        text = "；".join(val) if isinstance(val, list) else str(val)
        content = _upsert_ccg_line(content, field, text)
        comment[field] = text
        if field == "不适用条件":
            # 同步 frontmatter.non_applicable_conditions（引擎负路由读它）
            cur = [str(x) for x in (fm.get("non_applicable_conditions") or [])]
            for t in (val if isinstance(val, list) else [val]):
                if t not in cur:
                    cur.append(t)
            fm["non_applicable_conditions"] = cur
    if basis:
        content = _upsert_ccg_line(content, "验证方式", basis)
        comment["验证方式"] = basis
        if not nodefile.verification_basis_valid(fm):
            # 枚举里没有「LLM 交叉验证」这一档，只能落到 other（声明文本在 CCG 行里）
            fm["verification_basis"] = basis_enum
    fm["llm_consolidation"] = prov
    cg._write_node(nid, os.path.join(cg.root, e["path"]), fm, content,
                   durable=True)
    # 每一次修改都是对缺失条件的补充：记录规律 + 状态，不记录实现。
    evolution.record(
        cg, node_id=nid,
        pattern=_evo_pattern(kept),
        missing="、".join(kept.keys()),
        action="补齐 CCG 字段：" + "、".join(kept.keys()),
        evidence=_evo_evidence(prov),
        source="consolidate", kind=evolution.KIND_CONDITION_GAP,
        before=before, after=evolution.state_of(cg, nid) or {})


def consolidate(root: str, layer: str = None, limit: int = None, apply: bool = False,
                overwrite: bool = False, llm_fn=None, reflect_fn=None,
                verify_fn=None, reflect_model: str = "", verify_model: str = "",
                verification_basis: str = "", basis_enum: str = BASIS_ENUM_DEFAULT,
                require_verify: bool = True, thresholds: dict = None,
                verbose: bool = True) -> dict:
    """对正排层节点做「反思单元产出候选 → 白箱闸门 → 验证单元否决 → 固化」。

    llm_fn 是 reflect_fn 的旧名（向后兼容，单模型模式）。
    require_verify=True 且无 verify_fn → 一律 DEFER（纪律 5：未经验证不固化）。
    """
    reflect_fn = reflect_fn or llm_fn
    cg = MdCGOS(root)
    entries = cg._candidates(layer=layer)
    t0 = time.time()
    rep = {"root": root, "layer": layer, "dry_run": not apply,
           "reflect_model": reflect_model, "verify_model": verify_model,
           "reflect": bool(reflect_fn), "verify": bool(verify_fn), "llm": bool(reflect_fn),
           "require_verify": require_verify,
           "verification_basis": verification_basis,
           "nodes_scanned": len(entries),
           "targeted": 0, "accepted": 0, "rejected": 0, "deferred": 0,
           "skipped_complete": 0, "written": 0, "reasons": {},
           "per_field": {f: 0 for f in CCG_FIELDS}, "verify_dropped": 0,
           "verification_basis_missing": 0, "samples": []}

    def _bump(reason):
        rep["reasons"][reason] = rep["reasons"].get(reason, 0) + 1

    for e in entries:
        if limit is not None and rep["targeted"] >= limit:
            break
        nid = os.path.basename(e["path"])[:-3]
        fm, content = cg._read(e)
        if fm is None:
            _bump("read_failed")
            continue
        if crypto.is_encrypted(content):
            _bump("locked")           # 无密钥 → fail-closed：绝不改写密文
            continue
        have = existing_fields(fm, content)
        missing = [f for f in CCG_FIELDS if f not in have]
        if not nodefile.verification_basis_valid(fm):
            rep["verification_basis_missing"] += 1
        if not missing:
            rep["skipped_complete"] += 1
            continue
        rep["targeted"] += 1

        if not reflect_fn:
            rep["deferred"] += 1
            _bump("no_llm")
            continue

        # 1) 反思单元：产出候选（黑箱，唯一产出权）
        body = body_text(content)[:MAX_BODY_CHARS]
        title = _ccg_field(content, "功能名") or nid
        prompt = REFLECT_PROMPT.format(title=title, body=body)
        try:
            raw = reflect_fn(prompt)
        except Exception as exc:                     # noqa: BLE001 —— 离线批处理要抗单点失败
            rep["deferred"] += 1
            _bump(f"reflect_error:{type(exc).__name__}")
            continue
        cand = parse_candidate(raw)
        if not cand:
            rep["deferred"] += 1
            _bump("parse_failed")
            continue

        # 2) 白箱闸门：grounding + replay（零 LLM，先跑，省调用）
        kept, gdetail = grounding_filter(cand, body, thresholds)
        pos = kept.get("生效条件") or []
        neg = kept.get("不适用条件") or []
        replay = replay_check(pos, neg, body)
        if not kept or not replay["ok"]:
            rep["rejected"] += 1
            _bump("replay_failed" if kept else "grounding_failed")
            if verbose and len(rep["samples"]) < 8:
                rep["samples"].append({"id": nid, "verdict": "REJECT",
                                       "stage": "whitebox", "grounding": gdetail,
                                       "replay": replay})
            continue

        # 3) 验证单元：逐条核验，只能否决、不能新增
        dropped, vprompt, vd = {}, "", None
        if verify_fn:
            vprompt = VERIFY_PROMPT.format(
                cand=json.dumps(kept, ensure_ascii=False), title=title, body=body)
            try:
                vd = parse_verdict(verify_fn(vprompt))
                kept, dropped = narrow_by_verdict(kept, vd)
            except Exception as exc:                 # noqa: BLE001
                rep["deferred"] += 1
                _bump(f"verify_error:{type(exc).__name__}")
                continue
            if not kept:
                rep["rejected"] += 1
                _bump("verify_rejected")
                if verbose and len(rep["samples"]) < 8:
                    rep["samples"].append({"id": nid, "verdict": "REJECT",
                                           "stage": "verify", "dropped": dropped})
                continue
            rep["verify_dropped"] += sum(len(d["terms"]) for d in dropped.values())
        elif require_verify:
            # 验证单元不可用 → 不固化（纪律 5：未经验证不固化）
            rep["deferred"] += 1
            _bump("verify_unavailable")
            continue

        # 3) 不覆盖已有非空字段（保护人工既有知识）
        if not overwrite:
            kept = {f: v for f, v in kept.items() if f not in have}
            if not kept:
                rep["skipped_complete"] += 1
                continue

        prov = {"at": round(time.time(), 3), "verdict": "ACCEPT",
                "source_hash": _sig(content),
                "reflect": {"model": reflect_model, "prompt_hash": _sig(prompt),
                            "fields": sorted(kept)},
                "verify": ({"model": verify_model, "prompt_hash": _sig(vprompt),
                            "dropped": dropped, "verdict_fields": sorted(vd or {}),
                            "self_verify": verify_fn is reflect_fn}
                           if verify_fn else {"model": "", "status": "skipped"}),
                "grounding": gdetail, "replay": replay,
                "verification_basis": verification_basis}
        rep["accepted"] += 1
        for f in kept:
            rep["per_field"][f] += 1
        if apply:
            _apply_node(cg, e, fm, content, kept, prov,
                        verification_basis, basis_enum)
            append_jsonl(os.path.join(cg.root, "_consolidate.jsonl"),
                         {"t": time.time(), "id": nid, "verdict": "ACCEPT",
                          "fields": sorted(kept),
                          "reflect_model": reflect_model,
                          "verify_model": verify_model, "dropped": dropped,
                          "source_hash": prov["source_hash"], "replay": replay})
            rep["written"] += 1
        if verbose and len(rep["samples"]) < 8:
            rep["samples"].append({"id": nid, "verdict": "ACCEPT",
                                   "fields": sorted(kept), "dropped": dropped,
                                   "replay": replay})

    if apply and rep["written"]:
        # 正文新增了 `# 不适用条件：` / `# 验证方式：` → 索引字段变了
        cg.rebuild_index()
    rep["elapsed_sec"] = round(time.time() - t0, 3)
    return rep


def fill_verification_basis(root: str, basis: str, layer: str = None,
                            limit: int = None, apply: bool = False,
                            basis_enum: str = BASIS_ENUM_DEFAULT) -> dict:
    """只补「验证方式」——声明文本是常量，不需要黑箱生成，零 LLM 成本。

    对应纪律 3「不猜测」：验证基底必须由人/流程声明，而不是让模型编出来。
    """
    cg = MdCGOS(root)
    entries = cg._candidates(layer=layer)
    rep = {"root": root, "layer": layer, "dry_run": not apply, "basis": basis,
           "basis_enum": basis_enum, "nodes_scanned": len(entries),
           "targeted": 0, "skipped_present": 0, "skipped_locked": 0,
           "written": 0}
    for e in entries:
        if limit is not None and rep["written"] >= limit:
            break
        fm, content = cg._read(e)
        if fm is None:
            continue
        if crypto.is_encrypted(content):
            rep["skipped_locked"] += 1    # 无密钥 → fail-closed：绝不改写密文
            continue
        if _has_ccg_line(content, "验证方式"):
            rep["skipped_present"] += 1
            continue
        rep["targeted"] += 1
        if not apply:
            continue
        comment = (fm.get("state_attributes") or {}).get("comment")
        if not isinstance(comment, dict):
            fm["state_attributes"] = dict(fm.get("state_attributes") or {})
            fm["state_attributes"]["comment"] = {}
            comment = fm["state_attributes"]["comment"]
        content = _upsert_ccg_line(content, "验证方式", basis)
        comment["验证方式"] = basis
        if not nodefile.verification_basis_valid(fm):
            fm["verification_basis"] = basis_enum
        nid = e.get("id") or os.path.basename(e["path"])[:-3]
        cg._write_node(nid, os.path.join(cg.root, e["path"]), fm, content,
                       durable=True)
        rep["written"] += 1
    if apply and rep["written"]:
        cg.rebuild_index()
    return rep


# ==========================================================================
# 情境层批量提升（consolidate.promote）
# ==========================================================================
#
# 场景：情境层（contextual）里有些记忆被反复命中/并入——它们已经不是「一次情境」，
# 而是稳定的规律。本动作把它们提升为长期知识（knowledge），并保留：
#   · 双向可追溯：promoted_from + 演化账本（KIND_LAYER_SHIFT）；
#   · 条件门槛：四要素（CCG）不全者**不提升**（未可判定就不该升格为长期知识）；
#   · 可预演：apply=False 只出报表；可留痕：`_maintain.jsonl`。

MAINTAIN_LOG = "_maintain.jsonl"
CCG_REQUIRED = ("生效条件", "子功能", "执行", "不适用条件")


def _relocate_layer(cg, nid, e, fm, content, target_layer):
    """把节点正文迁到目标层的正确目录（含分桶），删除旧文件。返回新相对路径。"""
    d = os.path.join(cg.root, target_layer)
    bucket = None
    if target_layer in BUCKETED_LAYERS:
        bucket = routing.bucket_dir(routing.route_key(fm.get("condition_space"),
                                                      fm.get("tags")))
        d = os.path.join(d, bucket)
    os.makedirs(d, exist_ok=True)
    new_path = os.path.join(d, f"{nid}.md")
    old_path = os.path.join(cg.root, e.get("path") or f"{nid}.md")
    cg._write_node(nid, new_path, fm, content, durable=True)
    if os.path.abspath(old_path) != os.path.abspath(new_path) and os.path.exists(old_path):
        os.remove(old_path)
    return {"path": os.path.relpath(new_path, cg.root).replace("\\", "/"),
            "bucket": bucket}


def promote_memories(root, source_layer="contextual", target_layer="knowledge",
                     min_merge=2, min_importance=0.6, require_conditions=True,
                     limit=None, apply=False, actor="maintain") -> dict:
    """把反复命中的情境记忆批量提升为长期知识（可预演 / 可留痕 / 可追溯）。"""
    cg = MdCGOS(root)
    entries = cg._candidates(layer=source_layer)
    rep = {"root": root, "source_layer": source_layer, "target_layer": target_layer,
           "dry_run": not apply, "nodes_scanned": len(entries), "targeted": 0,
           "skipped_locked": 0, "skipped_incomplete": 0, "skipped_not_hot": 0,
           "written": 0, "promoted": [], "samples": [],
           "min_merge": min_merge, "min_importance": min_importance,
           "require_conditions": bool(require_conditions)}
    batch = time.strftime("%Y%m%d-%H%M%S")
    for e in entries:
        if limit is not None and rep["written"] >= int(limit):
            break
        fm, content = cg._read(e)
        if fm is None:
            continue
        if crypto.is_encrypted(content):
            rep["skipped_locked"] += 1      # 无密钥 → fail-closed，绝不解密回写
            continue
        nid = e.get("id") or os.path.basename(e["path"])[:-3]
        hits = max(int(fm.get("merge_count") or 0),
                   int(fm.get("access_count") or 0),
                   int(fm.get("recall_count") or 0))
        imp = float(fm.get("importance") or e.get("importance") or 0.0)
        complete = all(_has_ccg_line(content, f) for f in CCG_REQUIRED)
        if require_conditions and not complete:
            rep["skipped_incomplete"] += 1  # 四要素不全 → 不可判定，不升格
            continue
        hot = hits >= int(min_merge)
        if not hot and imp < float(min_importance):
            rep["skipped_not_hot"] += 1
            continue
        rep["targeted"] += 1
        item = {"id": nid, "hits": hits, "importance": round(imp, 4),
                "conditions_complete": complete,
                "basis": fm.get("verification_basis")}
        if len(rep["samples"]) < 8:
            rep["samples"].append(item)
        if not apply:
            continue
        before = evolution.state_of(cg, nid) or {}
        fm["layer"] = target_layer
        fm["promoted_from"] = source_layer
        fm["promoted_at"] = time.time()
        fm["promotion_basis"] = {"hits": hits, "importance": round(imp, 4),
                                 "conditions_complete": complete, "batch": batch,
                                 "actor": actor}
        moved = _relocate_layer(cg, nid, e, fm, content, target_layer)
        evolution.record(
            cg, node_id=nid,
            pattern="情境记忆反复命中/并入 → 提升为长期知识",
            missing="", action=f"层迁移 {source_layer}→{target_layer}",
            evidence=f"hits={hits} importance={imp:.2f} conditions_complete={complete}",
            source="consolidate", kind=evolution.KIND_LAYER_SHIFT,
            before=before, after=evolution.state_of(cg, nid) or {})
        append_jsonl(os.path.join(cg.root, MAINTAIN_LOG), {
            "t": time.time(), "action": "promote", "batch": batch, "id": nid,
            "from": source_layer, "to": target_layer, "hits": hits,
            "importance": round(imp, 4), "path": moved["path"], "actor": actor})
        rep["promoted"].append(nid)
        rep["written"] += 1
    if apply and rep["written"]:
        cg.rebuild_index()
    rep["note"] = ("dry-run：未写盘；apply=True 才迁移层"
                   if not apply else f"已提升 {rep['written']} 个节点到 {target_layer}")
    return rep


def rollback_promotion(root, node_ids=None, batch=None, actor="maintain") -> dict:
    """回滚情境提升：把 promoted_from 层迁回，并记一条演化条目。"""
    cg = MdCGOS(root)
    recs = [r for r in _read_maintain(root)
            if r.get("action") == "promote"
            and (not batch or r.get("batch") == batch)
            and (not node_ids or str(r.get("id")) in {str(x) for x in node_ids})]
    if not recs:
        return {"ok": False, "error": "no_records", "reverted": 0}
    reverted, ids = 0, []
    for rec in recs:
        nid = rec["id"]
        e = (cg.index.get("nodes") or {}).get(nid)
        if not e:
            continue
        fm, content = cg._read(e)
        if fm is None or crypto.is_encrypted(content):
            continue
        back = rec.get("from") or "contextual"
        before = evolution.state_of(cg, nid) or {}
        fm["layer"] = back
        fm["promoted_from"] = None
        fm["promotion_basis"] = {"rollback_of": rec.get("batch"), "actor": actor}
        _relocate_layer(cg, nid, e, fm, content, back)
        evolution.record(cg, node_id=nid, pattern="提升回滚：长期知识退回情境层",
                         action=f"层迁移 {rec.get('to')}→{back}",
                         evidence=f"rollback batch={rec.get('batch')}",
                         source="consolidate", kind=evolution.KIND_ROLLBACK,
                         before=before, after=evolution.state_of(cg, nid) or {})
        append_jsonl(os.path.join(cg.root, MAINTAIN_LOG), {
            "t": time.time(), "action": "promote_rollback", "batch": rec.get("batch"),
            "id": nid, "to": back, "actor": actor})
        reverted += 1
        ids.append(nid)
    if reverted:
        cg.rebuild_index()
    return {"ok": True, "reverted": reverted, "ids": ids}


# ==========================================================================
# 层归位（consolidate.contextualize）
# ==========================================================================
#
# 场景：批次流水账（note_/milestone_/retest6_）与感知产物（imgpart_/vpipe_）混在
# knowledge 层——它们的语义是**情境**（某次批次的记录 / 某张图的一次观测），不是
# 长期知识；但也不该进 rejected/unresolved（那是「失效 / 未解」，不是「情境」）。
# 故归位到 contextual：
#   · 只改 layer 与落点目录；正文 / 密级 / id / tags 一律不动；
#   · **保留可召回**（contextual 已在层白名单内，且 predict._SAFE_LAYERS 含之）；
#   · 可预演（apply=False）/ 可留痕（`_maintain.jsonl`）/ 可追溯（KIND_LAYER_SHIFT）
#     / 可回滚（按 batch 或 id 反向迁层）。
#
# 与 promote 的关系：promote 是 contextual→knowledge（升格），本动作是
# knowledge→contextual（归位）。两者共用 `_relocate_layer` 与批次台账，方向相反。

CONTEXTUALIZE_REASON_DEFAULT = "情境性内容归位（批次流水账 / 感知产物）"


def _entry_id(e) -> str:
    """索引条目取 id：优先 `id` 字段，回落到文件名（索引不保证带 id）。"""
    return str(e.get("id") or os.path.basename(e.get("path") or "")[:-3])


def _unique_batch(root, base) -> str:
    """批次号去重：**同一秒内的两次调用不得共用批次号**。

    否则「按批次回滚」会连带命中上一次的台账记录（回滚必须是精确的、可对账的）。
    """
    seen = {r.get("batch") for r in _read_maintain(root)}
    if base not in seen:
        return base
    n = 2
    while f"{base}.{n}" in seen:
        n += 1
    return f"{base}.{n}"


def contextualize_prefixes(root, prefixes=None, node_ids=None,
                           source_layer="knowledge", target_layer="contextual",
                           reason="", limit=None, apply=False,
                           actor="maintain") -> dict:
    """按 id 前缀（或定向 id 列表）把节点从 source_layer 归位到 target_layer。

    默认方向 knowledge→contextual。`prefixes` / `node_ids` **至少给一个**：
    宁可少搬，不可全库乱搬——不传白名单直接报错，拒绝「一次误调用把整个知识层改层」
    这种不可归因的批量改写。`node_ids` 用于定向（含「回滚后单独补迁」的对称操作）。
    """
    pref = tuple(str(p) for p in (prefixes or ()) if str(p))
    ids = {str(i) for i in (node_ids or ()) if str(i)} or None
    if not pref and not ids:
        raise ValueError("contextualize 需要显式 prefixes 或 node_ids"
                         "（如 ['note_','imgpart_']），拒绝对整层无差别改写")
    cg = MdCGOS(root)

    def _hit(e) -> bool:
        nid = _entry_id(e)
        return nid in ids if ids is not None else nid.startswith(pref)

    entries = [e for e in cg._candidates(layer=source_layer) if _hit(e)]
    batch = _unique_batch(root, time.strftime("%Y%m%d-%H%M%S"))
    rep = {"root": root, "action": "contextualize", "dry_run": not apply,
           "source_layer": source_layer, "target_layer": target_layer,
           "prefixes": list(pref), "node_ids": sorted(ids) if ids else [],
           "reason": reason or CONTEXTUALIZE_REASON_DEFAULT,
           "nodes_scanned": len(entries), "targeted": 0, "skipped_locked": 0,
           "skipped_already": 0, "written": 0, "moved": [], "samples": [],
           "batch": batch}
    for e in entries:
        if limit is not None and rep["written"] >= int(limit):
            break
        nid = _entry_id(e)
        if not _hit(e):
            continue
        fm, content = cg._read(e)
        if fm is None:
            continue
        if crypto.is_encrypted(content):
            rep["skipped_locked"] += 1      # 无密钥 → fail-closed，绝不解密回写
            continue
        if fm.get("layer") != source_layer:
            rep["skipped_already"] += 1
            continue
        rep["targeted"] += 1
        if len(rep["samples"]) < 8:
            rep["samples"].append({"id": nid, "from": fm.get("layer"),
                                   "path": e.get("path")})
        if not apply:
            continue
        before = evolution.state_of(cg, nid) or {}
        fm["layer"] = target_layer
        fm["contextualized_from"] = source_layer
        fm["contextualized_at"] = time.time()
        fm["contextualization_basis"] = {"reason": rep["reason"], "batch": batch,
                                         "actor": actor}
        moved = _relocate_layer(cg, nid, e, fm, content, target_layer)
        evolution.record(
            cg, node_id=nid,
            pattern="情境性内容（批次流水账 / 感知产物）混在知识层 → 归位情境层",
            missing="层归属规则", action=f"层迁移 {source_layer}→{target_layer}",
            evidence=f"prefix={str(nid).split('_')[0]}_ reason={rep['reason']}",
            source="consolidate", kind=evolution.KIND_LAYER_SHIFT,
            before=before, after=evolution.state_of(cg, nid) or {})
        append_jsonl(os.path.join(cg.root, MAINTAIN_LOG), {
            "t": time.time(), "action": "contextualize", "batch": batch, "id": nid,
            "from": source_layer, "to": target_layer, "path": moved["path"],
            "bucket": moved.get("bucket"), "reason": rep["reason"], "actor": actor})
        rep["moved"].append(nid)
        rep["written"] += 1
    if apply and rep["written"]:
        cg.rebuild_index()
    rep["note"] = ("dry-run：未写盘；apply=True 才归位"
                   if not apply else f"已归位 {rep['written']} 个节点到 {target_layer}")
    return rep


def rollback_contextualize(root, node_ids=None, batch=None, actor="maintain") -> dict:
    """回滚层归位：按 `_maintain.jsonl` 的 contextualize 记录把节点迁回原层。"""
    cg = MdCGOS(root)
    recs = [r for r in _read_maintain(root)
            if r.get("action") == "contextualize"
            and (not batch or r.get("batch") == batch)
            and (not node_ids or str(r.get("id")) in {str(x) for x in node_ids})]
    if not recs:
        return {"ok": False, "error": "no_records", "reverted": 0}
    reverted, ids = 0, []
    for rec in recs:
        nid = rec["id"]
        e = (cg.index.get("nodes") or {}).get(nid)
        if not e:
            continue
        fm, content = cg._read(e)
        if fm is None or crypto.is_encrypted(content):
            continue
        back = rec.get("from") or "knowledge"
        before = evolution.state_of(cg, nid) or {}
        fm["layer"] = back
        fm["contextualized_from"] = None
        fm["contextualization_basis"] = {"rollback_of": rec.get("batch"),
                                         "actor": actor}
        _relocate_layer(cg, nid, e, fm, content, back)
        evolution.record(cg, node_id=nid,
                         pattern="层归位回滚：情境层迁回原层",
                         action=f"层迁移 {rec.get('to')}→{back}",
                         evidence=f"rollback batch={rec.get('batch')}",
                         source="consolidate", kind=evolution.KIND_ROLLBACK,
                         before=before, after=evolution.state_of(cg, nid) or {})
        append_jsonl(os.path.join(cg.root, MAINTAIN_LOG), {
            "t": time.time(), "action": "contextualize_rollback",
            "batch": rec.get("batch"), "id": nid, "to": back, "actor": actor})
        reverted += 1
        ids.append(nid)
    if reverted:
        cg.rebuild_index()
    return {"ok": True, "reverted": reverted, "ids": ids}


def contextualize_history(root, limit=50):
    """层归位的批次记录（只读）。"""
    recs = [r for r in _read_maintain(root)
            if r.get("action") in ("contextualize", "contextualize_rollback")]
    return {"ok": True, "records": recs[-(int(limit) or 50):]}


def _read_maintain(root):
    from .fsutil import read_jsonl
    return list(read_jsonl(os.path.join(root, MAINTAIN_LOG)))


# ==========================================================================
# 归纳聚类（consolidate.induce）
# ==========================================================================
#
# 与 promote 的分工：
#   promote —— 把**已经存在**的单条情境记忆升格为长期知识（节点不变，只迁层）；
#   induce  —— 把**多条**具体记忆归纳为一个**新的概念节点**（新增节点）。
#
# 归纳是「由具体到一般」的推理，其输出**不是事实断言**，而是待验证的假设：
#   · 证据基底一律记 inferred（未经验证），不得冒充 verified；
#   · 概念节点必须携带成员清单 + `generalizes`/`instance_of` 对称边，保证可回溯；
#   · 归纳不出「共同条件」时默认**拒绝生成**（没有条件依据的抽象＝编造，对齐
#     纪律 3「不猜测」）；确需放宽须显式 require_conditions=False，且概念正文
#     会写明「未归纳出共同条件」，不掩盖证据缺口。

INDUCE_MIN_CLUSTER = 3
INDUCE_MIN_JACCARD = 0.30
INDUCE_MAX_NODES = 400
INDUCE_MAX_TERMS = 6
CONCEPT_REL = "generalizes"          # concept → member（inferred）
CONCEPT_MEMBER_REL = "instance_of"   # member → concept（inferred）
CONCEPT_PREFIX = "concept_"
CONCEPT_IMPORTANCE = 0.5
CONCEPT_TAGS = ("concept", "induced")
# 归纳候选排除：受保护节点，以及洞察/场景/前馈/概念等派生物（避免自我进食）
INDUCE_SKIP_TAGS = ("insight", "scene", "reconstructed", "gap_hint", "concept")


def _concept_id(members):
    """概念节点 id：由成员清单派生，保证「同成员 ⇒ 同 id」的幂等性。"""
    h = hashlib.sha1("|".join(sorted(str(m) for m in members))
                     .encode("utf-8")).hexdigest()
    return CONCEPT_PREFIX + h[:10]


def _jaccard(a, b):
    if not a or not b:
        return 0.0
    return len(a & b) / float(len(a | b))


def _common_terms(term_sets, min_share=0.6):
    """出现在 ≥ min_share 比例成员中的词面（共同条件）；少于 2 个成员共享不算。"""
    if not term_sets:
        return []
    cnt = {}
    for s in term_sets:
        for t in set(s or ()):
            cnt[t] = cnt.get(t, 0) + 1
    need = max(2, int(math.ceil(min_share * len(term_sets))))
    return sorted(t for t, c in cnt.items() if c >= need)


def _union_terms(term_sets, limit=INDUCE_MAX_TERMS):
    seen = []
    for s in term_sets:
        for t in sorted(s or ()):
            if t not in seen:
                seen.append(t)
    return seen[:limit]


def _link_concept(cg, cid, members, reason, actor, batch):
    """写概念↔成员对称 inferred 边（幂等：已存在则不重复写）。"""
    nodes = (getattr(cg, "index", None) or {}).get("nodes") or {}
    out = {"concept": cid, "members": []}
    cnode = cg.get(cid)
    if cnode:
        fm = cnode.get("frontmatter") or {}
        edges = list(fm.get("edges") or [])
        have = {str(e.get("target")) for e in edges if isinstance(e, dict)}
        added = False
        for m in members:
            if m in have:
                continue
            edges.append({"target": m, "relation_type": CONCEPT_REL,
                          "reason": reason, "created_at": time.time(),
                          "confidence": 0.5, "verified": 0, "evidence": "inferred"})
            added = True
        if added:
            fm["edges"] = edges
            ent = nodes.get(cid) or {}
            cg._write_node(cid, os.path.join(cg.root, ent.get("path") or f"{cid}.md"),
                           fm, cnode.get("content") or "")
            if ent:
                ent["edges"] = edges
    for m in members:
        node = cg.get(m)
        if not node:
            continue
        fm = node.get("frontmatter") or {}
        edges = list(fm.get("edges") or [])
        if any(isinstance(e, dict) and str(e.get("target")) == cid for e in edges):
            continue
        edges.append({"target": cid, "relation_type": CONCEPT_MEMBER_REL,
                      "reason": reason, "created_at": time.time(),
                      "confidence": 0.5, "verified": 0, "evidence": "inferred"})
        fm["edges"] = edges
        fm["induced_concept"] = cid
        ent = nodes.get(m) or {}
        cg._write_node(m, os.path.join(cg.root, ent.get("path") or f"{m}.md"),
                       fm, node.get("content") or "")
        if ent:
            ent["edges"] = edges
        out["members"].append(m)
    return out


def _concept_payload(members, common_pos, neg_union):
    """概念节点正文：把成员的共性条件抽象为可追溯的知识条目（显式标注 inferred）。"""
    label = "、".join(common_pos[:INDUCE_MAX_TERMS])
    pos_txt = "；".join(common_pos[:INDUCE_MAX_TERMS]) or "（未归纳出共同条件）"
    neg_txt = "；".join(neg_union[:INDUCE_MAX_TERMS]) or "（未判定）"
    return (
        "# 功能名：归纳概念：%s\n"
        "# 生效条件：%s\n"
        "# 子功能：%d 条具体记忆的共性（成员：%s）\n"
        "# 执行：由 consolidate.induce 归纳聚合（inferred；未经验证，不得直接当事实使用）\n"
        "# 验证方式：待验证（inferred 假设，需外部证据或实践重复后方可升格）\n"
        "# 不适用条件：%s\n"
        % (label or "共性", pos_txt, len(members), "、".join(members), neg_txt)
    )


def induce_memories(cg_or_root, source_layer="contextual", target_layer="knowledge",
                    min_cluster=INDUCE_MIN_CLUSTER, min_jaccard=INDUCE_MIN_JACCARD,
                    max_nodes=INDUCE_MAX_NODES, require_conditions=True,
                    limit=None, apply=False, actor="maintain", **extra):
    """归纳聚类：把多条具体记忆归纳为概念层条目（inferred，非事实断言）。

    流程：读取源层 → bigram 相似度贪心聚类 → 提炼共同条件 → 生成概念节点
    （apply=True）→ 写 `generalizes` / `instance_of` 对称 inferred 边 → 写留痕。

    apply=False（默认）只出候选报表（可预演）；apply=True 才写盘（可留痕、可回溯）。
    幂等：概念 id 由成员清单派生，同成员重复归纳不新增节点。
    """
    cg = cg_or_root if isinstance(cg_or_root, MdCGOS) else MdCGOS(str(cg_or_root))
    from . import subgraph                     # 惰性导入：复用统一的条件/词面抽取

    # MCP 分发层会把未提供的参数以 None 传入；此处归一化，避免 int(None) 崩溃，
    # 也避免 require_conditions=None 被当成 False 而悄悄关掉「无共同条件即拒绝生成」
    # 这条纪律（默认必须为真，放宽只能显式传 False）。
    min_cluster = INDUCE_MIN_CLUSTER if min_cluster is None else int(min_cluster)
    min_jaccard = INDUCE_MIN_JACCARD if min_jaccard is None else float(min_jaccard)
    max_nodes = INDUCE_MAX_NODES if max_nodes is None else int(max_nodes)
    if require_conditions is None:
        require_conditions = True

    nodes = (getattr(cg, "index", None) or {}).get("nodes") or {}
    pool = [nid for nid, e in nodes.items()
            if (not source_layer or (e or {}).get("layer") == source_layer)
            and not (e or {}).get("protected")
            and not (set(INDUCE_SKIP_TAGS) & set((e or {}).get("tags") or []))]
    pool.sort()
    truncated = len(pool) > int(max_nodes)
    pool = pool[:int(max_nodes)]

    cache = {}
    for nid in pool:
        got = subgraph._node_terms_and_grams(cg, nid)
        if got and got["grams"]:
            cache[nid] = got
    keys = sorted(cache.keys())

    rep = {"ok": True, "action": "induce", "op": "consolidate",
           "source_layer": source_layer, "target_layer": target_layer,
           "dry_run": not apply, "nodes_scanned": len(pool), "indexed": len(keys),
           "truncated": truncated, "min_cluster": int(min_cluster),
           "min_jaccard": float(min_jaccard),
           "require_conditions": bool(require_conditions),
           "skipped_small": 0, "skipped_no_condition": 0, "skipped_existing": 0,
           "clusters": 0, "written": 0, "concepts": [], "samples": [],
           "log": MAINTAIN_LOG}

    # ---- 贪心聚类（只读） ----
    assigned, proposals = set(), []
    for i, a in enumerate(keys):
        if a in assigned:
            continue
        ga = cache[a]["grams"]
        grp = [b for b in keys[i + 1:]
               if b not in assigned
               and _jaccard(ga, cache[b]["grams"]) >= float(min_jaccard)]
        if len(grp) + 1 < int(min_cluster):
            continue
        members = [a] + grp
        assigned.update(members)
        common_pos = _common_terms([cache[m]["pos"] for m in members])
        if require_conditions and not common_pos:
            rep["skipped_no_condition"] += 1
            continue
        neg_union = _union_terms([cache[m]["neg"] for m in members])
        proposals.append({
            "members": members, "concept_id": _concept_id(members),
            "common_conditions": common_pos, "non_applicable": neg_union,
            "reason": ("%d 条记忆内容相近且共享条件「%s」→ 归纳为概念"
                       % (len(members), "、".join(common_pos) or "无")),
        })
    rep["clusters"] = len(proposals)
    for p in proposals[:8]:
        rep["samples"].append(p)

    if not apply:
        rep["note"] = ("dry-run：未写盘；apply=True 才生成概念节点与 inferred 边"
                       if proposals else "无满足条件的聚类（内容不够相近或缺乏共同条件）")
        rep["concepts"] = [p["concept_id"] for p in proposals]
        return rep

    # ---- 落库（可留痕） ----
    batch = time.strftime("%Y%m%d-%H%M%S")
    for p in proposals:
        if limit is not None and rep["written"] >= int(limit):
            break
        cid = p["concept_id"]
        if cid in nodes:
            rep["skipped_existing"] += 1
            continue
        content = _concept_payload(p["members"], p["common_conditions"],
                                   p["non_applicable"])
        cg.add(cid, content, layer=target_layer, tags=list(CONCEPT_TAGS),
               importance=CONCEPT_IMPORTANCE, verification_basis="other",
               induced_from=list(p["members"]), induced_at=time.time(),
               induction={"method": "bigram_jaccard", "min_jaccard": float(min_jaccard),
                          "common_conditions": p["common_conditions"], "batch": batch,
                          "actor": actor, "evidence": "inferred"},
               actor=actor)
        _link_concept(cg, cid, p["members"], p["reason"], actor, batch)
        append_jsonl(os.path.join(cg.root, MAINTAIN_LOG), {
            "t": time.time(), "action": "induce", "batch": batch, "concept": cid,
            "members": list(p["members"]), "common_conditions": p["common_conditions"],
            "source_layer": source_layer, "target_layer": target_layer, "actor": actor})
        rep["concepts"].append(cid)
        rep["written"] += 1
    if rep["written"]:
        cg.rebuild_index()
    rep["note"] = (f"已归纳 {rep['written']} 个概念节点（inferred，待验证）"
                   if rep["written"] else "无可落库的归纳（均跳过或已达 limit）")
    return rep


# ---- CLI ----------------------------------------------------------------

def _cli(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description="md_cg 离线固化：反思单元(LLM)产出候选 → 白箱闸门 → "
                    "验证单元(LLM)否决 → 固化为 md 字段")
    ap.add_argument("--root", required=True, help="md 认知图根目录")
    ap.add_argument("--layer", default=None, help="只处理某层（如 knowledge）")
    ap.add_argument("--limit", type=int, default=None, help="只处理前 N 个待补节点")
    ap.add_argument("--apply", action="store_true", help="真正写盘（默认只验证）")
    ap.add_argument("--dry-run", action="store_true", help="只验证不写盘（默认行为）")
    ap.add_argument("--overwrite", action="store_true",
                    help="允许覆盖已有非空字段（默认保护人工既有知识）")
    ap.add_argument("--reflect-model", default=None,
                    help=f"反思单元模型（默认 {ROLE_DEFAULT_MODEL[REFLECT_ROLE]}）")
    ap.add_argument("--verify-model", default=None,
                    help=f"验证单元模型（默认 {ROLE_DEFAULT_MODEL[VERIFY_ROLE]}）")
    ap.add_argument("--self-verify", action="store_true",
                    help="降级：验证单元复用反思单元模型（非交叉验证，provenance 标记）")
    ap.add_argument("--no-verify", action="store_true",
                    help="降级：跳过验证单元，仅靠白箱闸门（不推荐）")
    ap.add_argument("--verification-basis", default=None,
                    help="写入 `# 验证方式：` 的声明文本（默认双模型声明）")
    ap.add_argument("--no-basis", action="store_true", help="不写「验证方式」")
    ap.add_argument("--basis-only", action="store_true",
                    help="只补「验证方式」（零 LLM 成本），不做四要素反思")
    ap.add_argument("--min-grounding", type=float, default=None,
                    help="统一 grounding 阈值（默认按字段 0.5 / 不适用条件 0.34）")
    ap.add_argument("--no-llm", action="store_true",
                    help="不调用 LLM，只做四要素完整性普查")
    ap.add_argument("--check", action="store_true",
                    help="零 token 探测两个角色网关的可用模型后退出")
    ap.add_argument("--report", default=None, help="把汇总 JSON 另存一份")
    a = ap.parse_args(argv)

    r_model, _, r_key = role_config(REFLECT_ROLE, a.reflect_model)
    v_model, _, v_key = role_config(VERIFY_ROLE, a.verify_model)

    if a.check:
        out = {"reflect": probe_models(REFLECT_ROLE),
               "verify": probe_models(VERIFY_ROLE)}
        print(json.dumps(out, ensure_ascii=False, indent=2))
        return 0

    basis = None if a.no_basis else (
        a.verification_basis or BASIS_TEMPLATE.format(reflect=r_model, verify=v_model))

    if a.basis_only:
        rep = fill_verification_basis(a.root, basis, layer=a.layer, limit=a.limit,
                                      apply=a.apply)
        print(json.dumps(rep, ensure_ascii=False, indent=2))
        if a.report:
            with open(a.report, "w", encoding="utf-8") as f:
                json.dump(rep, f, ensure_ascii=False, indent=2)
        return 0

    thresholds = ({f: a.min_grounding for f in CCG_FIELDS}
                  if a.min_grounding is not None else None)

    reflect_fn = verify_fn = None
    if not a.no_llm:
        if not r_key:
            print(f"[consolidate] 反思单元未配置 key"
                  f"（{_ROLE_ENV[REFLECT_ROLE][2]} / DEEPSEEK_API_KEY）→ 退化为普查模式",
                  file=sys.stderr)
        else:
            reflect_fn = (lambda p: http_llm(p, role=REFLECT_ROLE,   # noqa: E731
                                             model=a.reflect_model))
            if a.self_verify:
                verify_fn = reflect_fn
            elif not a.no_verify:
                if v_key:
                    verify_fn = (lambda p: http_llm(p, role=VERIFY_ROLE,  # noqa: E731
                                                    model=a.verify_model))
                else:
                    print(f"[consolidate] 验证单元未配置 key"
                          f"（{_ROLE_ENV[VERIFY_ROLE][2]} / ZHIPU_API_KEY / GLM_API_KEY）"
                          "→ 待补节点将 DEFER，不写盘（纪律 5：未经验证不固化）",
                          file=sys.stderr)

    rep = consolidate(a.root, layer=a.layer, limit=a.limit, apply=a.apply,
                      overwrite=a.overwrite, reflect_fn=reflect_fn,
                      verify_fn=verify_fn, reflect_model=r_model,
                      verify_model=v_model if verify_fn else "",
                      verification_basis=basis or "",
                      require_verify=not a.no_verify, thresholds=thresholds)
    print(json.dumps(rep, ensure_ascii=False, indent=2))
    if a.report:
        with open(a.report, "w", encoding="utf-8") as f:
            json.dump(rep, f, ensure_ascii=False, indent=2)
    return 0


if __name__ == "__main__":
    raise SystemExit(_cli())
