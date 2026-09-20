# -*- coding: utf-8 -*-
"""超边（hyperedge）验收：第四阶段计划批次 A（T1-T4）。

T1 注册面 4 处对齐（audit 真源 ×2 + 工具面自描述 + 对齐清单）+ register 注入；
T2 schema 往返（row → payload → node → payload 六列逐字段一致）；
T3 audit 三态（未注入 DEFER / 注入后 ACCEPT、REJECT）；
T4 fail-closed（缺列/坏结构显式报错不猜测）+ writepipe 链端到端落盘。
"""

import os
import shutil
import sys
import tempfile
import traceback

from . import audit as audit_mod
from . import hyperedge
from . import writepipe
from .mdcos import MdCGSecure
from .security import Principal

_ok = 0
_bad = []

# 台账六列两种典型行：标准行（六列全值）与稀疏行（早期遗留，仅 verify_id/iter_id）
_ROW_STD = {"received_at": "2026-09-17T16:40:07",
            "verify_id": "verify-fff1ce7-phase0", "commit": "fff1ce7",
            "verdict": "PASS", "receipt_job": "h1789634407680_445c",
            "iter_id": "iter-002-carrier-align"}
_ROW_SPARSE = {"received_at": "", "verify_id": "close-clean-batch",
               "commit": "", "verdict": "", "receipt_job": "",
               "iter_id": "iter-002-carrier-align"}


def _check(name, cond, detail=""):
    global _ok
    if cond:
        _ok += 1
        print("  ok   %s" % name)
    else:
        _bad.append("%s %s" % (name, detail))
        print("  FAIL %s %s" % (name, detail))


def _src(name):
    here = os.path.dirname(os.path.abspath(__file__))
    with open(os.path.join(here, name), encoding="utf-8") as f:
        return f.read()


def _mk_cg(tmp):
    p = Principal(tenant="default", actor="t_hyperedge", role="designer",
                  can_write=True, can_admin=True)
    return MdCGSecure(tempfile.mkdtemp(dir=tmp), principal=p)


def _t1_registry():
    print("\n【T1】注册面 4 处对齐 + register 注入")
    _check("① audit.CONTENT_KINDS 注册 hyperedge（回放比对语义）",
           "hyperedge" in audit_mod.CONTENT_KINDS
           and "回放" in audit_mod.CONTENT_KINDS["hyperedge"],
           str(audit_mod.CONTENT_KINDS.get("hyperedge")))
    _check("② audit.KIND_BASIS[hyperedge]=test",
           audit_mod.KIND_BASIS.get("hyperedge") == "test",
           str(audit_mod.KIND_BASIS.get("hyperedge")))
    # ③④ 工具面自描述与对齐清单：源码文本断言（与 test_p2_mcp 守卫同口径，
    # 防「真源扩了、自描述没跟」）
    _check("③ mcp_server content_kind 描述含 hyperedge",
           "work_wip|ccg_marks|hyperedge" in _src("mcp_server.py"))
    _check("④ test_p2_mcp 对齐清单含 hyperedge",
           '"ccg_marks", "hyperedge"' in _src("test_p2_mcp.py"))
    # register 注入面（MDCG_VERIFIER_MODULES 回调契约）：注入幂等、可还原
    ok = False
    try:
        hyperedge.register(audit_mod)
        ok = (audit_mod.VERIFIERS.get("hyperedge") is hyperedge.verify_payload)
        hyperedge.register(audit_mod)          # 重复加载幂等
        ok = ok and (audit_mod.VERIFIERS.get("hyperedge")
                     is hyperedge.verify_payload)
    except Exception as exc:  # noqa: BLE001
        print("      register 异常：%r" % exc)
    finally:
        audit_mod.VERIFIERS.pop("hyperedge", None)   # 还原默认态（T3 重测 DEFER）
    _check("register(audit_mod) 注入幂等可回调", ok)


def _t2_roundtrip():
    print("\n【T2】schema 往返（row→payload→node→payload）")
    p = hyperedge.row_from_ledger(_ROW_STD)
    _check("载荷三键齐备",
           set(p) == {"ledger_row", "frontmatter", "content"}, str(sorted(p)))
    fm = p["frontmatter"]
    _check("fm 键集齐备（EXTRA_FM_KEYS 全在）",
           all(k in fm for k in hyperedge.EXTRA_FM_KEYS), str(sorted(fm)))
    _check("fm 值映射正确（零编造）",
           fm["content_kind"] == "hyperedge"
           and fm["edge_type"] == "cross_verify"
           and fm["source"] == "receipts_ledger"
           and fm["participants"] == [_ROW_STD["verify_id"],
                                      _ROW_STD["receipt_job"]]
           and fm["evidence"] == [{"verify_id": _ROW_STD["verify_id"],
                                   "commit": _ROW_STD["commit"],
                                   "verdict": _ROW_STD["verdict"],
                                   "received_at": _ROW_STD["received_at"]}]
           and fm["corrections"] == []
           and fm["iter_id"] == _ROW_STD["iter_id"]
           and fm["received_at"] == _ROW_STD["received_at"]
           and fm["verdict"] == _ROW_STD["verdict"]
           and fm["ledger_row"]["receipt_job"] == _ROW_STD["receipt_job"],
           repr(fm)[:200])
    node = {"id": hyperedge.node_id_for(_ROW_STD),
            "frontmatter": dict(fm), "content": p["content"]}
    p2 = hyperedge.payload_from_node(node)
    v = hyperedge.verify_payload(p2)
    _check("节点回放重建 ACCEPT", v["state"] == "ACCEPT", str(v)[:140])
    _check("detail 带幂等 id",
           (v.get("detail") or {}).get("node_id") == node["id"], str(v)[:140])
    rebuilt = hyperedge.rows_from_fm(p2["frontmatter"])
    _check("六列逐字段一致",
           all(rebuilt[c] == _ROW_STD[c] for c in hyperedge.LEDGER_COLUMNS),
           repr(rebuilt))
    ps = hyperedge.row_from_ledger(_ROW_SPARSE)
    vs = hyperedge.verify_payload(hyperedge.payload_from_node(
        {"frontmatter": ps["frontmatter"], "content": ps["content"]}))
    _check("稀疏行（空列占位）往返一致", vs["state"] == "ACCEPT", str(vs)[:140])
    _check("稀疏行正文空字段为事实陈述（非编造占位）",
           "（台账原始行无此字段）" in ps["content"])
    _check("幂等键稳定且区分不同行",
           hyperedge.node_id_for(_ROW_STD)
           == hyperedge.node_id_for(dict(_ROW_STD))
           and hyperedge.node_id_for(_ROW_STD)
           != hyperedge.node_id_for(_ROW_SPARSE))
    _check("正文四段标记齐备",
           all(m in p["content"] for m in hyperedge.CONTENT_MARKERS))
    _check("build_content 决定论（同 fm 恒同正文）",
           hyperedge.build_content(fm) == p["content"])


def _t3_audit_states():
    print("\n【T3】audit 三态（未注入 DEFER / 注入后 ACCEPT、REJECT）")
    payload = hyperedge.row_from_ledger(_ROW_STD)
    saved = audit_mod.VERIFIERS.pop(hyperedge.CONTENT_KIND, None)
    try:
        v = audit_mod.audit("hyperedge", payload)
        _check("未注入验证器 → DEFER（诚实不假装通过）",
               v["state"] == "DEFER", str(v)[:140])
        audit_mod.register_verifier(hyperedge.CONTENT_KIND,
                                    hyperedge.verify_payload)
        v = audit_mod.audit("hyperedge", payload)
        _check("注入后一致载荷 ACCEPT", v["state"] == "ACCEPT", str(v)[:140])
        tampered = {"ledger_row": payload["ledger_row"],
                    "frontmatter": hyperedge.fm_from_row(
                        dict(_ROW_STD, commit="deadbee0")),
                    "content": payload["content"]}
        v = audit_mod.audit("hyperedge", tampered)
        _check("锚与结构不一致 REJECT（点名差异列）",
               v["state"] == "REJECT" and "commit" in v["evidence"],
               str(v)[:160])
        v = audit_mod.audit("hyperedge",
                            {"frontmatter": payload["frontmatter"],
                             "content": payload["content"]})
        _check("缺 ledger_row 锚 REJECT（fail-closed）",
               v["state"] == "REJECT", str(v)[:140])
        v = audit_mod.audit("hyperedge", {"content": "x", "action": None})
        _check("无 fm 键载荷 REJECT（不猜测）", v["state"] == "REJECT",
               str(v)[:140])
    finally:
        if saved is not None:
            audit_mod.VERIFIERS[hyperedge.CONTENT_KIND] = saved


def _t4_failclosed_and_pipeline(tmp):
    print("\n【T4】fail-closed 与 writepipe 链端到端")
    try:
        hyperedge.row_from_ledger({"verify_id": "x"})
        _check("缺列显式报错（不猜测补值）", False, "未抛 ValueError")
    except ValueError:
        _check("缺列显式报错（不猜测补值）", True)
    except Exception as exc:  # noqa: BLE001
        _check("缺列显式报错（不猜测补值）", False, repr(exc))
    try:
        hyperedge.rows_from_fm({"participants": ["only-one"]})
        _check("participants 非定长二元显式报错", False, "未抛 ValueError")
    except ValueError:
        _check("participants 非定长二元显式报错", True)
    p = hyperedge.row_from_ledger(_ROW_STD)
    _check("corrections 迁移期恒空", p["frontmatter"]["corrections"] == [])
    # 透传纯函数：非 hyperedge 零键、hyperedge 只收非 None 超边键
    _check("_hyperedge_extra 非 hyperedge 返回空",
           writepipe._hyperedge_extra({"content_kind": "text",
                                       "iter_id": "x"}) == {})
    ex = writepipe._hyperedge_extra({"content_kind": "hyperedge",
                                     "iter_id": "i1", "corrections": None})
    _check("_hyperedge_extra 只收非 None 超边键",
           ex == {"content_kind": "hyperedge", "iter_id": "i1"}, repr(ex))
    # writepipe 链端到端：a 平铺 fm 键 → audit 闸（验证器装配）→ 链尾落 fm
    cg = _mk_cg(tmp)
    audit_mod.register_verifier(hyperedge.CONTENT_KIND,
                                hyperedge.verify_payload, override=True)
    try:
        a = {"op": "write", "node_id": hyperedge.node_id_for(_ROW_STD),
             "content_kind": "hyperedge", "content": p["content"],
             "layer": "knowledge", "tags": ["receipt"]}
        a.update(p["frontmatter"])            # fm 键平铺（EXTRA_FM_KEYS 通道）
        out = writepipe.default_pipeline().execute(cg, a)
        _check("writepipe 落盘 committed", out.get("committed") is True,
               str(out)[:180])
        rec = cg.get(a["node_id"]) or {}
        fm = rec.get("frontmatter") or {}
        _check("超边 fm 落盘完整（锚 + 结构键）",
               fm.get("content_kind") == "hyperedge"
               and fm.get("participants") == p["frontmatter"]["participants"]
               and (fm.get("ledger_row") or {}).get("commit") == _ROW_STD["commit"]
               and (fm.get("evidence") or [{}])[0].get("verdict") == "PASS"
               and fm.get("iter_id") == _ROW_STD["iter_id"],
               str({k: fm.get(k)
                    for k in ("content_kind", "participants")})[:180])
        v = hyperedge.verify_payload(hyperedge.payload_from_node(rec))
        _check("落库节点回放 ACCEPT（写读同进程）", v["state"] == "ACCEPT",
               str(v)[:140])
    finally:
        audit_mod.VERIFIERS.pop(hyperedge.CONTENT_KIND, None)


def main():
    tmp = tempfile.mkdtemp(prefix="hyperedge_")
    try:
        _t1_registry()
        _t2_roundtrip()
        _t3_audit_states()
        _t4_failclosed_and_pipeline(tmp)
    except Exception:  # noqa: BLE001
        traceback.print_exc()
        _bad.append("未捕获异常")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
        # 全局态还原：验证器注册表不留测试残留
        audit_mod.VERIFIERS.pop(hyperedge.CONTENT_KIND, None)
    print("\nhyperedge 验收：%d 通过%s"
          % (_ok, ("，%d 失败：%s" % (len(_bad), "; ".join(_bad))) if _bad else ""))
    return 1 if _bad else 0


if __name__ == "__main__":
    sys.exit(main())
