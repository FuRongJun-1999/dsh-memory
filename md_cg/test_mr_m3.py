# -*- coding: utf-8 -*-
"""M3 定位自测（D1 字段级定位）：六类定位器 + 契约四键 + 批量/包 + 零写入。

真源：docs/记忆评审系统_立项设计与施工交接_20260915.md §5 D1
      `locate(node_id, issue_hint) -> [{field, span, issue_kind, evidence}]`

纪律（同 test_mr_m1/m2）：
  · **自备数据源**——合成节点 + tempfile 合成库，零依赖真源库（外部 clone 全绿）。
  · **零写入实锤**——全部相位跑完后认知图指纹逐字节不变（M3 是只读模块）。
  · **确定性**——同一输入两次调用逐字节一致；`now` 显式传入，不靠墙钟。
  · **不猜**——语义级矛盾归 blindspot（`contradiction_semantic`），不编造字符区间。

覆盖：A 基础工具（纯函数）  B 问题面定位器（含字段层门限、指纹不一致成因）+ 观测面
      （observation_aged：观测时刻不是失效声明，**不进告警面**）
      C 提示过滤与 blindspot（含 stale 的**依赖存在性**判据：载体消失/漂移）
      D 契约与确定性  E 批量与包  F 零写入
运行：python -m md_cg.test_mr_m3
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import sys
import tempfile

from . import codeindex as CI
from . import conformance as CF
from . import nodefile as NF
from . import writelimit as WL
from .mreview import locate as LC

PASS = FAIL = SKIP = 0
FAILS = []


def ok(cond, label):
    global PASS, FAIL
    if cond:
        PASS += 1
    else:
        FAIL += 1
        FAILS.append(label)
        print("  FAIL %s" % label)


def skip(label):
    global SKIP
    SKIP += 1
    print("  SKIP %s" % label)


# ---------------------------- 合成库 ----------------------------

def ccg(fn="示例节点", *, 生效="载体/位置：本地仓；时间：全时窗（任意时刻成立）；方法：test；约束：无",
        sub="a/b", exe="python -m md_cg.demo", ver="test", neg="无", extra=""):
    """六要素齐全的正文（防 `_loc_missing_field` 的 CCG 缺行噪声干扰其它判据）。"""
    return ("# 功能名：%s\n# 生效条件：%s\n# 子功能：%s\n# 执行：%s\n"
            "# 验证方式：%s\n# 不适用条件：%s\n%s" % (fn, 生效, sub, exe, ver, neg, extra))


def full_cs(*, pos="本地仓", tw=(0.0, 9999999999.0), tool="test", con="无"):
    return {"observation_position": pos, "time_window": list(tw),
            "observation_tool": tool, "existence_constraint": con}


def mkroot(root, nodes):
    """合成认知图根：`_index.json` + 节点盘文件（文件文本由 NF.dumps 生成）。"""
    os.makedirs(root, exist_ok=True)
    idx = {}
    for nid, spec in nodes.items():
        fm = dict(spec.get("fm") or {})
        fm.setdefault("id", nid)
        content = spec.get("content") or ""
        rel = spec.get("path") or ("knowledge/%s.md" % nid)
        p = os.path.join(root, rel)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "w", encoding="utf-8") as f:
            f.write(NF.dumps(fm, content))
        meta = dict(spec.get("meta") or {})
        meta.setdefault("path", rel)
        meta.setdefault("layer", spec.get("layer") or "knowledge")
        meta.setdefault("content_hash", NF.content_hash(content))
        meta.update({"id": nid, "path": rel})
        meta["path"] = rel
        idx[nid] = meta
    with open(os.path.join(root, CF.INDEX_FILE), "w", encoding="utf-8") as f:
        json.dump({"nodes": idx}, f, ensure_ascii=False)
    return root


def snapshot(root):
    out = {}
    for dp, _dns, fns in os.walk(root):
        for fn in fns:
            p = os.path.join(dp, fn)
            with open(p, "rb") as f:
                out[os.path.relpath(p, root)] = hashlib.md5(f.read()).hexdigest()
    return out


def kinds_of(hits):
    return sorted({h["issue_kind"] for h in hits})


def fields_of(hits, kind=None):
    return sorted({h["field"] for h in hits if kind is None or h["issue_kind"] == kind})


NOW = 1789000000.0        # 固定「当前时间」（2026-09 量级），不靠墙钟
EXPIRED = (1000.0, 2000.0)


# ---------------------------- A 组：基础工具 ----------------------------

def phase_a(tmp):
    print("[A] 基础工具（纯函数）")

    c = "第一句。第二句！第三句？第四句；"
    sp = LC.sentence_spans(c)
    ok(len(sp) == 4 and [i for i, _s, _e, _t in sp] == [0, 1, 2, 3],
       "A1 sentence_spans 句索引连续（%s）" % [i for i, _s, _e, _t in sp])
    ok(all(c[s:e] == t for _i, s, e, t in sp), "A2 span 与原文切片逐字对应")
    ok(LC.sentence_spans("") == [] and LC.sentence_spans("   ") == [],
       "A3 空/纯空白正文零句（不编号空句）")
    ok([t for _i, _s, _e, t in LC.sentence_spans("甲。\n乙。")] == ["甲。", "乙。"],
       "A4 换行是句尾且空句不编号（分隔符不残留在句首）")

    body = ccg(extra="尾句。")
    ms = LC.mark_spans(body)
    ok(set(ms) == set(NF.CCG_MARKS), "A5 mark_spans 六要素全提（实得 %s）" % sorted(ms))
    ok(all(body[s:e].startswith("#") for s, e in ms.values()),
       "A6 要素行 span 覆盖整行")
    ok(LC.mark_spans(ccg() + "# 功能名：第二个\n").get("功能名")
       == LC.mark_spans(ccg()).get("功能名"), "A7 同要素取首次出现（确定性）")

    text = NF.dumps({"id": "n1", "path": "knowledge/n1.md", "tags": []}, ccg())
    ks = LC.key_line_spans(text)
    ok(ks.get("id", (None, None))[0] == 2, "A8 key_line_spans 行号 1-based（实得 %s）"
       % (ks.get("id") or (None,))[0])
    ok("功能名" not in ks and "---" not in ks,
       "A9 正文 `#` 行与 `---` 分隔线都排除在 frontmatter 之外")
    ok(ks.get("id") and text[ks["id"][1][0]:ks["id"][1][1]].startswith('id:'),
       "A10 键行 span 切片以键名开头")

    root = mkroot(os.path.join(tmp, "a"), {
        "n1": {"content": ccg(), "meta": {"layer": "knowledge", "tags": ["a"]}},
        "n2": {"content": "短", "path": "", "meta": {"layer": "knowledge"}},
    })
    nd = LC.load_node("n1", root)
    ok(nd and nd["meta"].get("layer") == "knowledge" and "# 功能名：" in (nd["content"] or ""),
       "A11 load_node 取索引 meta + 文件正文")
    ok(nd and nd["fm"].get("id") == "n1", "A12 loads 解析出的 fm 是文件真源")
    ok(LC.load_node("ghost", root) is None, "A13 索引无此节点 → None（不猜路径）")
    ok(LC.load_node("n1", root, index={"nodes": {"n1": {"path": "knowledge/n1.md"}}})
       is not None, "A14 index 可显式注入（不读盘 index）")
    ok(LC._index(root).get("n1") is not None, "A15 _index 兼容 {nodes:…} 形态")
    ok(LC._index(root, index={"n1": {"path": "x"}}) == {"n1": {"path": "x"}},
       "A16 裸 dict 索引原样透传")

    ok(LC._snippet("甲" * 200, [0, 200]).endswith("…"), "A17 超长片段截断加省略号")
    ok(LC._line_of(text, nd["content"], [0, 5]) == 6,
       "A18 _line_of 定位到正文首行（实得 %s）" % LC._line_of(text, nd["content"], [0, 5]))
    ok(LC._line_of(None, "x", [0, 1]) is None and LC._line_of(text, "不存在", [0, 1]) is None,
       "A19 无 text / 正文不在文件内 → line=None（不编造）")
    ok(LC.canonical_kind("dup_content") == "dup"
       and LC.canonical_kind("template_flow_digits_only") == "template_flow",
       "A20 M1/D1 用词归并到 D1 规范名")
    ok(LC.canonical_kind("天外飞仙") == "天外飞仙", "A21 未知类别原样返回（不假装认路）")


# ---------------------------- B 组：六类定位器 ----------------------------

def phase_b(tmp):
    print("[B] 六类定位器")

    # B1-B6 missing_field
    m = {"id": "b1", "layer": "knowledge", "content_hash": "h1",
         "tags": ["a"], "role": "", "importance": 0.5, "evidence_count": 3,
         "lifecycle_state": "active", "condition_space": full_cs()}
    hits = LC.locate_ex("b1", "missing_field", meta=m, content=ccg(),
                        text="", fm={}, peers=[], now=NOW)["hits"]
    ok(fields_of(hits) == ["role"] and all(h["span"] is None for h in hits),
       "B1 字段两处皆空 → missing_field 且 span=None（实得 %s）" % fields_of(hits))

    m2 = dict(m, evidence_count=0, role="knowledge-card")
    hits = LC.locate_ex("b1", "missing_field", meta=m2, content=ccg(),
                        text="", fm={}, peers=[], now=NOW)["hits"]
    ok("evidence_count" in fields_of(hits) and "evidence_zero" in {h["rule"] for h in hits},
       "B2 evidence_count=0 → 专项命中（rule=evidence_zero）")

    m3 = dict(m, importance=1.7, role="k")
    hits = LC.locate_ex("b1", "missing_field", meta=m3, content=ccg(),
                        text="", fm={}, peers=[], now=NOW)["hits"]
    ok("importance" in fields_of(hits) and "field_invalid" in {h["rule"] for h in hits},
       "B3 importance 越界 → 字段存在但不可用")

    m4 = dict(m, condition_space={"observation_position": "本地"},
              role="k", tags=["a"])
    body = ccg()
    hits = LC.locate_ex("b1", "missing_field", meta=m4, content=body,
                        text="", fm={}, peers=[], now=NOW)["hits"]
    h = [x for x in hits if x["field"] == "condition_space"]
    ok(bool(h) and h[0]["span"] is not None
       and body[h[0]["span"][0]:h[0]["span"][1]].startswith("# 生效条件"),
       "B4 四槽不全 → 指向正文「# 生效条件」行（%d/4）"
       % (len(NF.CONDITION_SLOTS) - 3))

    cut = "# 功能名：只有一行\n正文没有其它要素。\n"
    hits = LC.locate_ex("b1", "missing_field", meta=dict(m, role="k", tags=["a"]),
                        content=cut, text="", fm={}, peers=[], now=NOW)["hits"]
    hm = [x for x in hits if x["rule"] == "ccg_incomplete"]
    ok(bool(hm) and hm[0]["field"] == "content" and hm[0]["span"] is None
       and "生效条件" in hm[0]["evidence"],
       "B5 正文缺 CCG 要素行 → field=content 且 span=None（行不存在，不编造区间）")
    ok(not [x for x in LC.locate_ex("b1", "missing_field", meta=m3, content=ccg(),
                                    text="", fm={}, peers=[], now=NOW)["hits"]
            if x["rule"] == "ccg_incomplete"],
       "B6 要素齐全 → 无 ccg_incomplete 噪声")

    # B7-B10 weak_source
    hits = LC.locate_ex("b1", "weak_source",
                        meta={"verification_basis": "", "tags": ["计算机"]},
                        content=ccg(), text="", fm={}, peers=[], now=NOW)["hits"]
    ok(len(hits) == 1 and hits[0]["rule"] == "basis_absent", "B7 基底为空 → basis_absent")

    hits = LC.locate_ex("b1", "weak_source",
                        meta={"verification_basis": "self", "tags": ["计算机"]},
                        content=ccg(), text="", fm={}, peers=[], now=NOW)["hits"]
    ok(len(hits) == 1 and hits[0]["rule"] == "basis_enum", "B8 基底越枚举 → basis_enum")

    hits = LC.locate_ex("b1", "weak_source",
                        meta={"verification_basis": "textbook", "tags": ["计算机"]},
                        content=ccg(), text="", fm={}, peers=[], now=NOW)["hits"]
    ok(len(hits) == 1 and hits[0]["rule"] == "basis_licensed"
       and "science" in hits[0]["evidence"], "B9 理科×textbook → 赛道不相容（实得 %s）"
       % (hits[0]["evidence"] if hits else "无"))

    hits = LC.locate_ex("b1", "weak_source",
                        meta={"verification_basis": "textbook", "tags": ["语文"]},
                        content=ccg(), text="", fm={}, peers=[], now=NOW)["hits"]
    ok(hits == [], "B10 文科×textbook 合规 → 零命中（不误报）")

    # B11-B12c observation_aged（原「stale」的时间窗口径：**观测时刻不是失效声明**）
    m5 = dict(m, role="k", tags=["a"], condition_space=full_cs(tw=EXPIRED))
    body = ccg()
    hits = LC.locate_ex("b1", "observation_aged", meta=m5, content=body, text="",
                        fm={}, peers=[], now=NOW)["hits"]
    ok(len(hits) == 1 and hits[0]["field"] == "condition_space"
       and hits[0]["severity"] == "info" and "观测时刻" in hits[0]["evidence"],
       "B11 时间窗过期 → observation_aged（观测面·info，不冒充失效）")

    m6 = dict(m5, condition_space=full_cs(tw=(0.0, NF.FULL_TIME_WINDOW_MAX)))
    ok(LC.locate_ex("b1", "observation_aged", meta=m6, content=body, text="", fm={},
                    peers=[], now=NOW)["hits"] == [],
       "B12 全时窗是合法声明 → 不判")

    # B12b-B12c 时间窗来源链（真库口径：索引快照只带 time_window，**无 condition_space 键**）
    m_nocs = {k: v for k, v in m.items() if k != "condition_space"}
    hits = LC.locate_ex("b1", "observation_aged", meta=dict(m_nocs, role="k"),
                        content=body, text="",
                        fm={"condition_space": full_cs(tw=EXPIRED)}, peers=[],
                        now=NOW)["hits"]
    ok(len(hits) == 1 and hits[0]["rule"] == "observation_window_passed",
       "B12b 快照无条件空间 → 回退 fm 真源仍判（实得 %d 条）" % len(hits))

    hits = LC.locate_ex("b1", "observation_aged",
                        meta=dict(m_nocs, role="k", time_window=list(EXPIRED)),
                        content=body, text="", fm={}, peers=[], now=NOW)["hits"]
    ok(len(hits) == 1 and hits[0]["rule"] == "observation_window_passed",
       "B12c 快照只带 time_window → 真库口径下仍判")

    # B12d-B12e **观测面不进评审告警面**（B+C 修正的关键隔离断言）
    hits = LC.locate_ex("b1", None, meta=m5, content=body, text="", fm={},
                        peers=[], now=NOW)["hits"]
    ok(all(h["issue_kind"] != "observation_aged" for h in hits),
       "B12d 默认全量定位不含 observation_aged（不进评审告警面）")
    ok("observation_aged" in LC.ADVISORY_KINDS
       and "observation_aged" not in LC.ISSUE_KINDS,
       "B12e observation_aged 归观测面（ADVISORY_KINDS），不占问题面 D1 六类")

    # C stale —— **依赖存在性**（B+C 修正：时效判定看载体是否还在，不看观测时刻）
    src = tempfile.mkdtemp(prefix="m3src_")
    slines = ["def f():", "    return 1", "", "def g():", "    return 2"]
    with open(os.path.join(src, "mod.py"), "w", encoding="utf-8") as f:
        f.write("\n".join(slines))
    ref_ok = {"path": "mod.py", "name": "f", "kind": "def", "lineno": 1, "end": 2,
              "lang": "py", "precise": True,
              "hash": CI.region_hash(slines, 1, 2), "root": src}
    hits = LC.locate_ex("c1", "stale", meta={}, content=body, text="",
                        fm={"code_ref": dict(ref_ok)}, peers=[], now=NOW)["hits"]
    ok(hits == [], "C1 依赖源文件在且区间哈希吻合 → 零命中（不误报）")

    hits = LC.locate_ex("c1", "stale", meta={}, content=body, text="",
                        fm={"code_ref": dict(ref_ok, hash="000000000000")},
                        peers=[], now=NOW)["hits"]
    ok(len(hits) == 1 and hits[0]["rule"] == "ref_stale"
       and hits[0]["field"] == "code_ref",
       "C2 源文件在但区间哈希不符（已漂移）→ stale")

    hits = LC.locate_ex("c1", "stale", meta={}, content=body, text="",
                        fm={"code_ref": dict(ref_ok, path="gone.py")},
                        peers=[], now=NOW)["hits"]
    ok(len(hits) == 1 and hits[0]["rule"] == "ref_dangling",
       "C3 依赖源文件不存在（悬空）→ stale（载体消失）")

    hits = LC.locate_ex("c1", "stale", meta={}, content=body, text="",
                        fm={"doc_ref": {"path": "x.md", "lineno": 1, "end": 2,
                                        "hash": "000000000000"}},
                        peers=[], now=NOW)["hits"]
    ok(hits == [], "C4 ref 无 root（判不了）→ 零命中（观测手段不足不冒充失效）")

    hits = LC.locate_ex("c1", None, meta=m5, content=body, text="",
                        fm={"code_ref": dict(ref_ok, path="gone.py")},
                        peers=[], now=NOW)["hits"]
    ok(any(h["issue_kind"] == "stale" for h in hits),
       "C5 默认全量定位会跑 stale（依赖存在性属问题面）")
    shutil.rmtree(src, ignore_errors=True)

    # B13-B14 dup
    same = ccg(fn="重复节点")
    peers = LC.build_peers([{"node_id": "b1", "content": same},
                            {"node_id": "b2", "content": same}])
    hits = LC.locate_ex("b1", "dup",
                        meta=dict(m, role="k", content_hash=NF.content_hash(same)),
                        content=same, text="", fm={}, peers=peers.get("b1"),
                        now=NOW)["hits"]
    ok(len(hits) == 1 and hits[0]["field"] == "content_hash"
       and hits[0]["span"] == [0, len(same)] and hits[0]["peer"] == "b2",
       "B13 同内容指纹 → dup 指整篇正文（peer=%s）"
       % (hits[0]["peer"] if hits else "无"))

    hits = LC.locate_ex("b1", "dup", meta=dict(m, role="k", tags=["a"]),
                        content=ccg(fn="甲"), text="", fm={},
                        peers=LC.build_peers([{"node_id": "b1", "content": ccg(fn="甲")},
                                              {"node_id": "b2", "content": ccg(fn="乙")}]
                                             ).get("b1"), now=NOW)["hits"]
    ok(hits == [], "B14 内容不同 → 不判 dup（不误报）")

    # B15 template_flow：逐句骨架相同、仅数值不同
    t1 = ccg(fn="批次 1 收官", extra="本批处理 100 条记录，耗用 12 秒。第二句写 200 条。")
    t2 = ccg(fn="批次 2 收官", extra="本批处理 300 条记录，耗用 45 秒。第二句写 400 条。")
    peers2 = LC.build_peers([{"node_id": "b1", "content": t1},
                             {"node_id": "b2", "content": t2}])
    hits = LC.locate_ex("b1", "template_flow", meta=dict(m, role="k", tags=["a"]),
                        content=t1, text="", fm={}, peers=peers2.get("b1"), now=NOW)["hits"]
    ok(len(hits) >= 2 and all(h["field"] == "content" and h["span"] is not None
                              for h in hits),
       "B15 同模板流水 → 逐句给出 span（%d 句命中）" % len(hits))
    ok(all(t1[h["span"][0]:h["span"][1]].strip()[:LC.SNIPPET_MAX] == h["snippet"]
           for h in hits),
       "B16 片段=span 切片去空白截断（与实现同口径，可肉眼复核）")
    ok(hits and hits[0]["sentence"] is not None and hits[0]["peer"] == "b2",
       "B17 携带句索引与对照节点（人工可跳行）")

    hits = LC.locate_ex("b1", "template_flow", meta=dict(m, role="k", tags=["a"]),
                        content=t1, text="", fm={},
                        peers=LC.build_peers([{"node_id": "b1", "content": t1}]).get("b1"),
                        now=NOW)["hits"]
    ok(hits == [], "B18 无对照节点 → 不判流水")

    # B19-B21 contradiction（确定性）
    body = ccg()
    hits = LC.locate_ex("b1", "contradiction",
                        meta={"content_hash": "declared!", "role": "k", "tags": ["a"]},
                        content=body, text="", fm={}, peers=[], now=NOW)["hits"]
    ok(len(hits) == 1 and hits[0]["rule"] == "hash_declared_vs_actual"
       and NF.content_hash(body) in hits[0]["evidence"],
       "B19 索引声明指纹 ≠ 正文实算 → contradiction")

    hits = LC.locate_ex("b1", "contradiction",
                        meta={"content_hash": NF.content_hash(body), "role": "k"},
                        content=body, text="", fm={"id": "别的id"}, peers=[],
                        now=NOW)["hits"]
    ok(len(hits) == 1 and hits[0]["rule"] == "id_declared_vs_index"
       and hits[0]["field"] == "id", "B20 文件 id ≠ 索引键 → contradiction")

    hits = LC.locate_ex("b1", "contradiction",
                        meta={"content_hash": NF.content_hash(body), "role": "k"},
                        content=body, text="", fm={"id": "b1"}, peers=[], now=NOW)["hits"]
    ok(hits == [], "B21 声明与事实一致 → 零命中")

    # B22-B25 字段层门限（判据同源：派生自 M1 规则库，不另立一份）
    scope = LC.field_layer_scope()
    ok(scope.get("role") == ["knowledge"]
       and scope.get("evidence_count") == ["knowledge"],
       "B22 层门限派生自 rules/*.json 的 matcher.layer（实得 %s）" % scope)
    ok("verification_basis" not in scope,
       "B23 未限层的字段不入表 = 全层适用（M1 R-BASIS-MISSING 无 layer 门限）")

    hits = LC.locate_ex("b1", "missing_field",
                        meta=dict(m, layer="contextual", role="", evidence_count=0,
                                  tags=[]),
                        content=ccg(), text="", fm={}, peers=[], now=NOW)["hits"]
    fld = fields_of(hits)
    ok("role" not in fld and "evidence_count" not in fld,
       "B24 非 knowledge 层 → 限层字段越层不报（与 M1 `_scope` 同口径，实得 %s）" % fld)
    ok("tags" in fld,
       "B25 未限层字段不受门限影响（tags 仍全层检查，实得 %s）" % fld)

    # B26-B28 指纹不一致的**成因**（同一条命中，两种成因，处置完全不同）
    cause, note = LC.hash_mismatch_cause({"content_hash": "x"}, root=None, path=None)
    ok(cause == "unknown" and "成因未判定" in note,
       "B26 无盘上证据 → cause=unknown（不假装知道成因）")

    root = mkroot(os.path.join(tmp, "b_lag"), {
        "n1": {"content": body, "meta": {"content_hash": "declared!"}},
    })
    node_f = os.path.join(root, "knowledge", "n1.md")
    idx_f = os.path.join(root, CF.INDEX_FILE)
    mt = os.path.getmtime(node_f)
    os.utime(idx_f, (mt - 60.0, mt - 60.0))    # 索引快照比节点文件旧 60s
    hc = [h for h in LC.locate_ex("n1", "contradiction", root=root, now=NOW)["hits"]
          if h["rule"] == "hash_declared_vs_actual"]
    ok(hc and hc[0]["cause"] == "index_lag" and "快照滞后" in hc[0]["evidence"],
       "B27 文件比索引快照新 → cause=index_lag（正常写路径现象，实得 %s）"
       % (hc[0]["cause"] if hc else "无命中"))

    os.utime(idx_f, (mt + 60.0, mt + 60.0))    # 索引快照不旧于节点文件
    hc = [h for h in LC.locate_ex("n1", "contradiction", root=root, now=NOW)["hits"]
          if h["rule"] == "hash_declared_vs_actual"]
    ok(hc and hc[0]["cause"] == "true_mismatch" and "真源相抵触" in hc[0]["evidence"],
       "B28 索引快照不旧于文件 → cause=true_mismatch（需查，实得 %s）"
       % (hc[0]["cause"] if hc else "无命中"))


# ---------------------------- C 组：提示过滤与 blindspot ----------------------------

def _mixed():
    """同时命中多类的节点：role 空 + 四槽不全（missing_field）+ 指纹不符（contradiction）。

    `condition_space` 刻意只声明 1 槽——让 D 组同时存在「可指区间」（`# 生效条件` 行）
    与「无区间」（frontmatter 声明类）两种命中，契约两侧都被覆盖。
    基底取 `textbook` + `语文`（文科档）——让 `weak_source` 真的干净，
    C 组才能验证「该类无问题就返回空、不借机报别的类」。
    """
    body = ccg()
    return dict({"content_hash": "declared!", "role": "", "tags": ["语文"],
                 "layer": "knowledge", "verification_basis": "textbook",
                 "importance": 0.5, "evidence_count": 3, "lifecycle_state": "active",
                 "condition_space": {"observation_position": "本地仓"}}), body


def phase_c(tmp):
    print("[C] 提示过滤与 blindspot")
    m, body = _mixed()
    kw = dict(meta=m, content=body, text="", fm={}, peers=[], now=NOW)

    all_hits = LC.locate_ex("c1", None, **kw)["hits"]
    ok({"missing_field", "contradiction"} <= set(kinds_of(all_hits)),
       "C1 hint=None → 全量定位（实得 %s）" % kinds_of(all_hits))

    only = LC.locate_ex("c1", "weak_source", **kw)["hits"]
    ok(all(h["issue_kind"] == "weak_source" for h in only),
       "C2 hint=类别 → 只跑该类（实得 %s）" % kinds_of(only))
    ok(only == [], "C3 该类无问题 → 空（不借机报别的类）")

    by_field = LC.locate_ex("c1", "role", **kw)["hits"]
    ok(by_field and all(h["field"] == "role" for h in by_field),
       "C4 hint=字段名 → 按字段过滤全量结果（实得 %s）" % fields_of(by_field))

    both = LC.locate_ex("c1", {"issue_kind": "missing_field", "field": "role"}, **kw)["hits"]
    ok(both and len(both) == len(by_field), "C5 dict 形态 hint 同时收类别与字段")

    lst = LC.locate_ex("c1", ["contradiction", "missing_field"], **kw)["hits"]
    ok(len(lst) == len(all_hits)
       and set(kinds_of(lst)) == {"contradiction", "missing_field"}
       and LC.locate_ex("c1", ["contradiction", {"field": "role"}], **kw)["hits"] == [],
       "C6 list 形态 hint 收集多个类别；类别与字段是收窄关系（交集空即空，不退回全量）"
       "（实得 %d 条 %s）" % (len(lst), kinds_of(lst)))

    ex = LC.locate_ex("c1", "contradiction_semantic", **kw)
    ok(ex["hits"] == [] and ex["blindspot"] and "语义" in ex["blindspot"][0],
       "C7 语义级矛盾 → blindspot 且零 hits（不猜、不编造区间）")
    ok(ex["blindspot"] == LC.locate_ex("c1", "contradiction_semantic", **kw)["blindspot"],
       "C8 blindspot 文本确定（可断言）")

    ex2 = LC.locate_ex("c1", ["contradiction_semantic", "missing_field"], **kw)
    ok(ex2["blindspot"] and ex2["hits"]
       and all(h["issue_kind"] == "missing_field" for h in ex2["hits"]),
       "C9 blindspot 与可定位类别同批共存（互不吞没）")

    unk = LC.locate_ex("c1", "天外飞仙", **kw)
    ok(unk["hits"] == [] and unk["blindspot"] == [],
       "C10 未知提示 → 当字段过滤后为空，不炸也不假装认路")

    alias = LC.locate_ex("c1", "dup_content", **kw)["hits"]
    ok(all(h["issue_kind"] == "dup" for h in alias) and bool(alias) is False,
       "C11 M1 用词 dup_content 归并为 dup（无重复故空）")

    ok(LC.blindspot_reason("contradiction") == "" and
       LC.blindspot_reason("contradiction_semantic") != "",
       "C12 blindspot_reason 单一归口（可定位类别返回空串）")


# ---------------------------- D 组：契约与确定性 ----------------------------

def phase_d(tmp):
    print("[D] 契约与确定性")
    m, body = _mixed()
    kw = dict(meta=m, content=body, text="", fm={}, peers=[], now=NOW)
    hits = LC.locate("d1", None, **kw)

    ok(isinstance(hits, list), "D1 locate() 契约入口返回 list")
    ok(all({"field", "span", "issue_kind", "evidence"} <= set(h) for h in hits),
       "D2 四键齐备（实得 %s）" % (sorted(hits[0]) if hits else "无命中"))
    ok(all(h["issue_kind"] in LC.ISSUE_KINDS for h in hits),
       "D3 issue_kind 全落 D1 枚举（实得 %s）" % kinds_of(hits))
    ok(all(str(h["evidence"]).strip() for h in hits),
       "D4 evidence 非空（白箱判据：为何算问题）")

    sp = [h for h in hits if h["span"] is not None]
    ok(all(isinstance(h["span"], list) and len(h["span"]) == 2
           and h["span"][0] < h["span"][1] and h["span"][1] <= len(body) for h in sp),
       "D5 span 是正文内的半开区间 [start,end)")
    ok(all(isinstance(h["span"][0], int) and isinstance(h["span"][1], int) for h in sp),
       "D6 span 端点为整数（可复算切片）")
    ok(all(body[h["span"][0]:h["span"][1]].strip() != "" for h in sp),
       "D7 span 指向非空片段")
    ok(all(h.get("snippet") != "" for h in sp),
       "D8 有 span 即有片段（人工核对可肉眼确认）")
    ok(all(not h.get("snippet") for h in hits if h["span"] is None),
       "D9 声明类命中无区间 → 片段为空（不编造区间）")

    h2 = LC.locate("d1", None, **kw)
    ok(json.dumps(hits, ensure_ascii=False) == json.dumps(h2, ensure_ascii=False),
       "D10 同一输入两次调用逐字节一致（确定性）")
    ok(LC.locate_ex("d1", None, **kw)["load"]["content_len"] == len(body),
       "D11 load 回报正文长度（审计留痕）")

    key = [(h["issue_kind"], str(h["field"])) for h in hits]
    ok(key == sorted(key), "D12 命中按 (issue_kind, field, span, peer) 稳定排序（实得 %s）" % key)

    try:
        LC.locate_ex("d1", None, meta=m, content=None, text="", fm={}, peers=[], now=NOW)
        raised = False
    except ValueError:
        raised = True
    ok(raised, "D13 无正文且无 root → fail-closed 报错（不假装能定位）")


# ---------------------------- E 组：批量与包 ----------------------------

def _pkg(entries, bid="bE"):
    return {"bundle_id": bid, "group_kind": "batch", "group_key": "g",
            "size": len(entries), "entries": entries}


def _ent(nid, *, excerpt="", h="", **kw):
    e = {"ref": nid, "node_id": nid, "excerpt": excerpt, "content_hash": h,
         "layer": "knowledge", "tags": ["a"]}
    e.update(kw)
    return e


def _clean_meta(**kw):
    """合规 meta（理科档 × test 基底）——「干净」必须是真干净，否则 clean 断言无意义。

    `layer="knowledge"`：层门限（真源 = M1 规则库 `matcher.layer`）下，
    `role`/`evidence_count` 只在本层检查；缺层节点根本不进判据，clean 断言会空转。
    """
    m = {"role": "knowledge-card", "tags": ["计算机"], "layer": "knowledge",
         "verification_basis": "test",
         "importance": 0.5, "evidence_count": 2, "lifecycle_state": "active",
         "condition_space": full_cs()}
    m.update(kw)
    return m


def phase_e(tmp):
    print("[E] 批量与包")
    same = ccg(fn="重复的")
    diff = ccg(fn="独一无二的甲")
    peers = LC.build_peers([{"node_id": "e1", "content": same},
                            {"node_id": "e2", "content": same},
                            {"node_id": "e3", "content": diff}])
    ok([p["node_id"] for p in peers["e1"]] == ["e2"]
       and [p["node_id"] for p in peers["e2"]] == ["e1"],
       "E1 build_peers 同内容指纹互为对照（双向）")
    ok(peers["e3"] == [], "E2 内容不同 → 不同组（不是「同批即同组」）")

    t1 = ccg(fn="批次 1 收官", extra="处理 100 条。")
    t2 = ccg(fn="批次 2 收官", extra="处理 200 条。")
    p2 = LC.build_peers([{"node_id": "e1", "content": t1},
                         {"node_id": "e2", "content": t2}])
    ok([p["node_id"] for p in p2["e1"]] == ["e2"],
       "E3 同标题模板骨架 → 互为对照（指纹不同也入组）")
    ok(all(p["sk"] for p in p2["e1"]), "E4 对照项携带模板骨架（M1 同源口径）")

    ok(LC.build_peers([]) == {}, "E5 空批 → 空映射（不炸）")
    ok("e1" in LC.build_peers([{"node_id": "e1", "content": same}]),
       "E6 单条批仍回填键（调用方不必判空）")

    items = [{"node_id": "e1", "content": ccg(fn="干净的"), "meta": _clean_meta()},
             {"node_id": "e2", "content": ccg(fn="有问题的"),
              "meta": _clean_meta(role="")}]
    rep = LC.locate_many(items=items, now=NOW)
    ok(rep["nodes"] == 2 and rep["clean"] == ["e1"] and rep["missing"] == [],
       "E7 locate_many 报「干净」条（没问题≠没看，clean=%s）" % rep["clean"])
    ok(rep["by_kind"].get("missing_field") == 1 and rep["by_field"].get("role") == 1,
       "E8 by_kind/by_field 汇总正确（%s / %s）" % (rep["by_kind"], rep["by_field"]))
    ok(all(h["node_id"] == "e2" for h in rep["hits"]), "E9 命中归属到正确节点")

    root = mkroot(os.path.join(tmp, "e"), {
        "n1": {"content": ccg(fn="盘上节点"), "meta": _clean_meta(role="")},
        "n2": {"content": ccg(fn="盘上无问题"), "meta": _clean_meta()},
    })
    rep2 = LC.locate_many(["n1", "n2", "ghost"], root=root, now=NOW)
    ok(rep2["nodes"] == 2 and rep2["missing"] == ["ghost"],
       "E10 读不到的节点单列 missing（「没看」≠「没问题」，missing=%s）" % rep2["missing"])
    ok(rep2["clean"] == ["n2"], "E11 读盘形态同样分流 clean")
    ok(rep2["hits"] and rep2["hits"][0]["field"] == "role",
       "E12 读盘形态命中与显式 items 同判据")

    exc9 = ccg(fn="只在摘录里的节点")
    pkg = _pkg([_ent("n1", excerpt="摘录里没有特征码", h="过期指纹"),
                _ent("p9", excerpt=exc9, h=NF.content_hash(exc9),
                     **_clean_meta(condition_space={"observation_position": "本地仓",
                                                    "time_window": [0.0, 9999999999.0],
                                                    "observation_tool": "test"}))])
    rep3 = LC.locate_package(pkg, root=root, now=NOW)
    ok(rep3["bundle_id"] == "bE" and rep3["entries"] == 2 and rep3["nodes"] == 2,
       "E13 locate_package 带包标识与条目计数")
    ok(any(h["node_id"] == "n1" for h in rep3["hits"]),
       "E14 包内可读节点走读盘正文（准确）")
    p9 = [h for h in rep3["hits"] if h["node_id"] == "p9"]
    ok(p9 and all(h["field"] == "condition_space" for h in p9)
       and exc9[p9[0]["span"][0]:p9[0]["span"][1]].startswith("# 生效条件"),
       "E15 文件不可读 → 用包内 excerpt 仍给出正文区间（降级但仍可指，实得 %s）"
       % kinds_of(p9))
    ok(not [h for h in rep3["hits"] if h["node_id"] == "n1"
            and h["issue_kind"] == "dup"],
       "E16 excerpt 不冒充正文做重复判定（诚实降级）")

    s = LC.summary(rep3["hits"])
    ok(s["total"] == len(rep3["hits"]) and s["nodes"] == len(s["node_ids"])
       and s["by_kind"], "E17 summary 汇总口径自洽")
    ok(LC.summary([])["total"] == 0 and LC.summary([])["node_ids"] == [],
       "E18 空命中 summary 不炸")

    md = LC.markdown_table(rep3["hits"])
    ok(md.count("\n") >= len(rep3["hits"]) + 1 and "人工判定" in md,
       "E19 markdown_table 逐条一行且留人工判定列")
    ok(LC.markdown_table([{"node_id": "x", "issue_kind": "dup", "field": "c",
                           "span": None, "evidence": "含|竖线"}]).count("\\|") == 1,
       "E20 表格竖线转义（不破坏表格结构）")

    code = LC.main(["--root", root, "--node", "n1", "--json"])
    ok(code == 0, "E21 CLI --json 退出码 0")
    code2 = LC.main(["--root", root, "--node", "n1", "--kind", "missing_field",
                     "--markdown"])
    ok(code2 == 0, "E22 CLI --kind + --markdown 退出码 0")
    # 本用例断言「缺 root → fail-closed」，而 locate 的 --root 缺省读环境变量 MDCG_ROOT
    # → 环境里存在该变量时用例必假失败（非 hermetic）。故用例内显式清除、用完还原。
    _saved_root = os.environ.pop("MDCG_ROOT", None)
    try:
        ok(LC.main(["--node", "n1"]) == 2, "E23 缺 root → 退出码 2（fail-closed）")
    finally:
        if _saved_root is not None:
            os.environ["MDCG_ROOT"] = _saved_root
    ok(LC.main(["--root", root]) == 2, "E24 缺 node → 退出码 2（不静默空跑）")


# ---------------------------- F 组：零写入 ----------------------------

def phase_f(tmp):
    print("[F] 零写入")
    root = mkroot(os.path.join(tmp, "f"), {
        "n1": {"content": ccg(fn="批次 1 收官", extra="处理 100 条。"),
               "meta": {"role": "", "tags": ["a"], "importance": 0.5,
                        "evidence_count": 0, "lifecycle_state": "active",
                        "condition_space": full_cs(tw=EXPIRED)}},
        "n2": {"content": ccg(fn="批次 2 收官", extra="处理 200 条。"),
               "meta": {"role": "knowledge-card", "tags": ["语文"],
                        "importance": 0.5, "evidence_count": 1,
                        "lifecycle_state": "active",
                        "condition_space": full_cs()}},
    })
    before = snapshot(root)
    LC.locate_many(["n1", "n2"], root=root, now=NOW)
    LC.locate_package(_pkg([_ent("n1"), _ent("n2")]), root=root, now=NOW)
    LC.locate("n1", None, root=root, now=NOW)
    LC.main(["--root", root, "--node", "n1", "--node", "n2"])
    ok(snapshot(root) == before,
       "F1 全相位跑完认知图指纹逐字节不变（M3 只读）")
    ok(not os.path.exists(os.path.join(root, "_mreview")),
       "F2 定位不另立状态目录（无残留）")


# ---------------------------- main ----------------------------

def main(argv=None):
    with tempfile.TemporaryDirectory(prefix="mrev_m3_") as tmp:
        phase_a(tmp)
        phase_b(tmp)
        phase_c(tmp)
        phase_d(tmp)
        phase_e(tmp)
        phase_f(tmp)
    print("\nM3 自测：%d 通过 / %d 失败 / %d 跳过" % (PASS, FAIL, SKIP))
    if FAILS:
        print("失败项：")
        for f in FAILS:
            print("  - %s" % f)
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
