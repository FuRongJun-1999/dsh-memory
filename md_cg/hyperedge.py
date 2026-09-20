# -*- coding: utf-8 -*-
"""超边（hyperedge）：跨端验证回执的认知图形式化投影。

上游真源 = 互验协议运行时文件（hive/interop/_receipts_ledger.tsv，六列）；
超边节点是历史回执在认知图中的**形式化镜像**（一行 = 一条超边，回执粒度），
单向投影：超边不反向覆写台账，协议运行时逻辑零改动。

六列 → fm + 正文完整自包含回执卡，机械映射零编造：
    received_at / verify_id / commit / verdict / receipt_job / iter_id
  - participants  定长二元 [verify_id, receipt_job]（六列机械可得的全部参与者
                  信息；role/harness/unit/session 归因字段台账无载，不编造）
  - evidence      [{verify_id, commit, verdict, received_at}]
  - corrections   []（迁移期恒空；后续跨端修正经修正面回填）
  - ledger_row    六列整行锚（与结构键互为回放校验）

幂等键：he_<sha1(六列值 join)[:10]>——同一台账行重复迁移得到同一节点 id。

验证器 verify_payload 做「结构键反解 ↔ ledger_row 锚」逐字段回放比对 + 正文
四段标记检查，经 register_verifier("hyperedge", …) 注入（或 MDCG_VERIFIER_MODULES
外部注入；未注入时 audit DEFER——诚实不假装通过）。

本模块不含写库逻辑；写入由调用方走 cg(op=write, content_kind="hyperedge", …)
经 writepipe 既有审核链（五动词纪律：不重复造写入通道）。
"""
from __future__ import annotations

import hashlib

CONTENT_KIND = "hyperedge"
EDGE_TYPE = "cross_verify"          # 唯一类型，留扩展位
SOURCE_NAME = "receipts_ledger"     # 溯源锚（协议真源 TSV）
LEDGER_COLUMNS = ("received_at", "verify_id", "commit", "verdict",
                  "receipt_job", "iter_id")

# 写入面透传给 cg.add(**extra) 的 fm 键集合（writepipe._hyperedge_extra 按此
# 收集非 None 键）。落盘面丢字段 = 上游声明静默失效（比报错更难发现）。
EXTRA_FM_KEYS = ("content_kind", "edge_type", "participants", "evidence",
                 "corrections", "iter_id", "source", "received_at",
                 "verdict", "ledger_row")

# 正文四段标记（build_content 段落标题词；验证器检查齐备——无 fm 解析能力
# 的外部工具直读正文即可取数，这是「可被外部理解的正式结构」的最低保障）。
CONTENT_MARKERS = ("参与者", "证据", "修正", "时间")

_EMPTY_NOTE = "（台账原始行无此字段）"   # 空字段的事实陈述（非编造占位）


# 生效条件：v 传入即归一为去空格字符串（None 得空串），无条件分支；
def _clean(v):
    return "" if v is None else str(v).strip()


# 生效条件：row 为含六列键的 dict 时返回六列清洗副本；缺列或非 dict 即抛
# ValueError（fail-closed，不猜测补值）；
def _norm_row(row):
    if not isinstance(row, dict):
        raise ValueError("台账行须为 dict（六列键），得到 %s" % type(row).__name__)
    missing = [c for c in LEDGER_COLUMNS if c not in row]
    if missing:
        raise ValueError("台账行缺列：%s（fail-closed，不猜测补值）" % missing)
    return {c: _clean(row.get(c)) for c in LEDGER_COLUMNS}


# 生效条件：row 经 _norm_row 校验即返回固定键集 fm（content_kind/edge_type/
# participants/evidence/corrections/iter_id/source/received_at/verdict/ledger_row）；
def fm_from_row(row):
    """台账行 → 超边 fm（schema v0.1，协议冻结前允许破坏性调整）。"""
    r = _norm_row(row)
    return {
        "content_kind": CONTENT_KIND,
        "edge_type": EDGE_TYPE,
        # 定长二元：空串占位保证反解对称（[0]→verify_id、[1]→receipt_job）。
        "participants": [r["verify_id"], r["receipt_job"]],
        "evidence": [{"verify_id": r["verify_id"], "commit": r["commit"],
                      "verdict": r["verdict"], "received_at": r["received_at"]}],
        "corrections": [],
        "iter_id": r["iter_id"],
        "source": SOURCE_NAME,
        "received_at": r["received_at"],
        "verdict": r["verdict"],
        "ledger_row": dict(r),
    }


# 生效条件：fm 的 participants 为定长二元、evidence 为单项列表时返回六列重建
# 行（回放方向 H1：反解六列）；形态不符即抛 ValueError；
def rows_from_fm(fm):
    """fm 结构键 → 台账行（反解方向，不依赖 ledger_row 锚）。"""
    parts = fm.get("participants")
    if not isinstance(parts, list) or len(parts) != 2:
        raise ValueError("participants 须为定长二元 [verify_id, receipt_job]")
    ev = fm.get("evidence")
    if not isinstance(ev, list) or len(ev) != 1 or not isinstance(ev[0], dict):
        raise ValueError("evidence 须为单项列表"
                         "（{verify_id, commit, verdict, received_at}）")
    e = ev[0]
    return {
        "received_at": _clean(e.get("received_at")),
        "verify_id": _clean(parts[0]),
        "commit": _clean(e.get("commit")),
        "verdict": _clean(e.get("verdict")),
        "receipt_job": _clean(parts[1]),
        "iter_id": _clean(fm.get("iter_id")),
    }


# 生效条件：fm 含六列信息（ledger_row 锚优先，缺锚走结构键反解）时返回六列行；
# 两者皆不可解析即抛 ValueError；
def _row_of_fm(fm):
    anchored = fm.get("ledger_row")
    if isinstance(anchored, dict):
        return {c: _clean(anchored.get(c)) for c in LEDGER_COLUMNS}
    return rows_from_fm(fm)


# 生效条件：fm 经 _row_of_fm 可解析即返回含四段标记（参与者/证据/修正/时间）
# 的正文，空字段以「台账原始行无此字段」事实陈述呈现；
def build_content(fm):
    """超边 fm → 四段正文（参与者/证据/修正/时间）。"""
    r = _row_of_fm(fm)

    def v(col):
        return r[col] if r[col] else _EMPTY_NOTE

    corr = fm.get("corrections") or []
    lines = [
        "# 跨端验证超边（%s / %s）" % (CONTENT_KIND, EDGE_TYPE),
        "",
        "## 参与者",
        "- verify_id: %s" % v("verify_id"),
        "- receipt_job: %s" % v("receipt_job"),
        "",
        "## 证据",
        "- commit: %s" % v("commit"),
        "- verdict: %s" % v("verdict"),
        "- received_at: %s" % v("received_at"),
        "",
        "## 修正",
    ]
    lines.extend(("- %s" % _clean(c) for c in corr if _clean(c)) if corr
                 else ["无（迁移期恒空；后续跨端修正经修正面回填）"])
    lines.extend([
        "",
        "## 时间",
        "- received_at: %s" % v("received_at"),
        "- iter_id: %s" % v("iter_id"),
        "",
        "溯源：%s（TSV 真源单向投影，超边不反向覆写台账）" % SOURCE_NAME,
    ])
    return "\n".join(lines)


# 生效条件：row 经 _norm_row 校验即返回载荷 {ledger_row, frontmatter, content}
# （写入面读向齐备，幂等 id 另经 node_id_for 取）；
def row_from_ledger(row):
    """台账行 → 超边载荷（{ledger_row, frontmatter, content}）。"""
    r = _norm_row(row)
    fm = fm_from_row(r)
    return {"ledger_row": dict(r), "frontmatter": fm,
            "content": build_content(fm)}


# 生效条件：node 为 dict（frontmatter 嵌套或 fm 键平铺两形态）且结构键可反解
# 时返回载荷（ledger_row 优先取节点锚，缺锚用结构重建行）；结构不可反解即抛
# ValueError；
def payload_from_node(node):
    """节点 → 载荷（回放重建读向 H1）。"""
    if not isinstance(node, dict):
        raise ValueError("节点须为 dict")
    fm = node.get("frontmatter") if isinstance(node.get("frontmatter"), dict) \
        else node
    anchored = fm.get("ledger_row")
    rebuilt = rows_from_fm(fm)
    row = ({c: _clean(anchored.get(c)) for c in LEDGER_COLUMNS}
           if isinstance(anchored, dict) else rebuilt)
    return {"ledger_row": row, "frontmatter": fm,
            "content": node.get("content") or ""}


# 生效条件：a（writepipe 写入请求，fm 键平铺顶层）传入即返回验证器三键载荷
# {ledger_row, frontmatter, content}——frontmatter 收集 a 中非 None 的
# EXTRA_FM_KEYS 键；ledger_row 非 dict 时为 None（由验证器 fail-closed 裁决）；
def audit_payload(a):
    """writepipe audit 闸的超边载荷装配（fm 键平铺 → 三键载荷）。"""
    row = a.get("ledger_row")
    return {"ledger_row": row if isinstance(row, dict) else None,
            "frontmatter": {k: a.get(k) for k in EXTRA_FM_KEYS
                            if a.get(k) is not None},
            "content": a.get("content") or ""}


# 生效条件：row 经 _norm_row 校验即返回 he_<sha1(逐列「len:val」拼接)[:10]>
# （同一台账行恒同 id，重复迁移幂等；任意列内容不可伪造边界）；
def node_id_for(row):
    """幂等键：同一台账行重复迁移得到同一节点 id。

    **无歧义规范化**（2026-09-20 v14 缺陷 G 修复）：逐列 `<len>:<val>` 前缀
    拼接——长度前缀由本函数计算、不可被列内容伪造，故任意两列之间搬移含任意
    字符的文本都得不同 canon。旧实现直接 `"\\x1f".join(...)`：`verify_id="a"`
    + `commit="b\\x1fc"` 与 `verify_id="a\\x1fb"` + `commit="c"` 撞同一 id
    （不是 SHA-1 碰撞，是规范化没做转义/长度前缀）。

    id 口径变更说明：canon 输入形态改变 → id 取值随之改变。属 schema v0.1
    内的破坏性调整（该 schema 明示允许）；实测库内 `he_` 节点为 0，无历史
    迁移数据需兼容。
    """
    r = _norm_row(row)
    canon = "".join("%d:%s" % (len(r[c]), r[c]) for c in LEDGER_COLUMNS)
    return "he_" + hashlib.sha1(canon.encode("utf-8")).hexdigest()[:10]


# 生效条件：payload 缺 ledger_row/frontmatter、结构键不可反解、反解与锚不一致
# 或正文缺四段标记即 REJECT；逐字段一致且标记齐备即 ACCEPT（detail 带幂等 id）；
# 其它异常照抛（由 audit 包为 DEFER）；
def verify_payload(payload, ctx=None):
    """audit 验证器签名：回放比对（fm/content 反解 ↔ ledger_row 锚）。"""
    if not isinstance(payload, dict):
        return {"state": "REJECT", "evidence": "payload 须为 dict，得到 %s"
                                                % type(payload).__name__}
    row = payload.get("ledger_row")
    fm = payload.get("frontmatter")
    if not isinstance(fm, dict):
        fm = payload        # 平铺形态：载荷自身承载 fm 键（writepipe 闸外直调）
    if not isinstance(row, dict):
        return {"state": "REJECT",
                "evidence": "payload 缺 ledger_row 锚（回执卡不自包含）"}
    try:
        anchored = {c: _clean(row.get(c)) for c in LEDGER_COLUMNS}
        rebuilt = rows_from_fm(fm)          # 形态坏 → ValueError → REJECT
    except ValueError as exc:
        return {"state": "REJECT", "evidence": str(exc)}
    diffs = ["%s: %r != %r" % (c, anchored[c], rebuilt[c])
             for c in LEDGER_COLUMNS if anchored[c] != rebuilt[c]]
    if diffs:
        return {"state": "REJECT", "evidence": "回放比对不一致：%s" % "; ".join(diffs),
                "detail": {"field_diffs": diffs}}
    ctext = payload.get("content") if isinstance(payload.get("content"), str) else ""
    miss = [m for m in CONTENT_MARKERS if m not in ctext]
    if miss:
        return {"state": "REJECT", "evidence": "正文缺四段标记：%s（不自包含）" % miss}
    return {"state": "ACCEPT",
            "evidence": "回放重建六列逐字段一致（verify_id=%r）"
                        % anchored["verify_id"],
            "detail": {"node_id": node_id_for(anchored)}}


# 生效条件：audit_mod 提供 register_verifier 即把 verify_payload 以 override=True
# 注入（重复加载幂等）；
def register(audit_mod):
    """MDCG_VERIFIER_MODULES 入口：把回放比对验证器注入 audit。"""
    audit_mod.register_verifier(CONTENT_KIND, verify_payload, override=True)
