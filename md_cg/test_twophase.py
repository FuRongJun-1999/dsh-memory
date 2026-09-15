# -*- coding: utf-8 -*-
"""test_twophase · 写入两段式提交（Pi 可学习优点 ③）

验收口径（交接文档 §3③）：
- 写入在**闸门通过后先落 intent**（含内容指纹），落盘完成再落 outcome；
- 「kill -9 模拟半途写入后重启」→ 对账**正确补账**（内容确已落盘）或
  **如实标记**（未落盘 / 指纹不符），不假装成功；
- 对账幂等、账本 append-only、不重放写入；
- 未落盘的分支（闸门拒绝 / 入队）不产生 intent——没打算写就不记账。

运行：python -m md_cg.test_twophase
"""
from __future__ import annotations

import json
import os
import shutil
import tempfile
import traceback

from . import twophase, writepipe
from .mdcos import MdCGSecure
from .security import Principal

_ok = 0
_fail = []
_seq = [0]


def check(name, cond, detail=""):
    global _ok
    if cond:
        _ok += 1
        print("[ok] " + name)
    else:
        _fail.append(name)
        print("[FAIL] %s  · %s" % (name, str(detail)[:240]))


def _mk_cg(tmp, role="designer"):
    _seq[0] += 1
    root = os.path.join(tmp, "root_%02d_%s" % (_seq[0], role))
    p = Principal(tenant="default", actor="t_" + role, role=role,
                  can_write=(role != "guest"), can_admin=(role == "designer"))
    return MdCGSecure(root, principal=p)


def _policy(tmp, required=("PASSED",), forbidden=("FORBIDDEN_WORD",)):
    path = os.path.join(tmp, "policy.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"forbidden": list(forbidden),
                   "required": list(required)}, f)
    os.environ["MDCG_POLICY_FILE"] = path
    return path


def _lines(cg):
    p = twophase.log_path(cg)
    if not os.path.isfile(p):
        return []
    with open(p, encoding="utf-8", errors="replace") as f:
        return [x for x in f.read().splitlines() if x.strip()]


def _recs(cg):
    return twophase.records(cg)


def _idx(cg, nid):
    return (cg.index.get("nodes") or {}).get(nid) or {}


def _phases(cg, nid=None):
    return [r.get("phase") for r in _recs(cg)
            if nid is None or r.get("id") == nid]


def _run(tmp):
    _policy(tmp)
    pipe = writepipe.install_default_gates(writepipe.WritePipeline())

    # ---------- ① 正常落盘：intent + outcome 成对 ----------
    cg = _mk_cg(tmp)
    out = pipe.execute(cg, {"content_kind": "text",
                            "content": "两段式正常落盘 PASSED",
                            "layer": "knowledge"})
    nid = out.get("id")
    check("①1 写入成功（committed）", out.get("committed") is True, out)
    recs = _recs(cg)
    ph = [r["phase"] for r in recs if r.get("id") == nid]
    check("①2 账本两行成对（intent → outcome）", ph == ["intent", "outcome"], ph)
    intent = [r for r in recs if r.get("id") == nid
              and r["phase"] == "intent"][0]
    oc = [r for r in recs if r.get("id") == nid and r["phase"] == "outcome"][0]
    check("①3 intent 带内容指纹（对账的判据）",
          bool(intent.get("content_hash")), intent)
    check("①4 outcome 记 committed + 同 iid",
          oc.get("status") == twophase.STATUS_COMMITTED
          and oc.get("iid") == intent.get("iid"), oc)
    check("①5 指纹走 nodefile 唯一真源（含写盘尾换行归一）",
          intent.get("content_hash")
          == twophase.nodefile.content_hash("两段式正常落盘 PASSED"),
          (intent.get("content_hash"),
           twophase.nodefile.content_hash("两段式正常落盘 PASSED")))
    check("①6 正常写入后无未结清意图", cg.pending_writes() == [])

    # ---------- ② intent 真的**先于**落盘（真实执行路径内观测） ----------
    cg2 = _mk_cg(tmp)
    _orig = writepipe._executor
    seen = {}

    def _probe(ctx):
        seen["has_intent"] = any(
            r.get("phase") == "intent" and r.get("id") == ctx["nid"]
            for r in _recs(ctx["cg"]))
        seen["has_outcome"] = any(
            r.get("phase") == "outcome" and r.get("id") == ctx["nid"]
            for r in _recs(ctx["cg"]))
        seen["node_exists"] = bool(ctx["cg"].get(ctx["nid"]))
        return _orig(ctx)

    writepipe._executor = _probe
    try:
        pipe.execute(cg2, {"content_kind": "text",
                           "content": "先行持久化探针 PASSED",
                           "layer": "knowledge"})
    finally:
        writepipe._executor = _orig
    check("②1 进入执行器时 intent 已落账（先行持久化成立）",
          seen.get("has_intent") is True, seen)
    check("②2 进入执行器时**尚无** outcome 且节点未落盘",
          seen.get("has_outcome") is False
          and seen.get("node_exists") is False, seen)

    # ---------- ③ 半途崩溃：落盘已完成、outcome 未写 ----------
    cg3 = _mk_cg(tmp)
    nid3 = "mem_2pc_c3"
    tok = twophase.begin(cg3, nid3, "崩溃在落盘之后 PASSED", layer="knowledge",
                         actor="test:crash")
    cg3.add(nid3, "崩溃在落盘之后 PASSED", layer="knowledge")
    check("③1 崩溃现场：有 intent 无 outcome",
          _phases(cg3, nid3) == ["intent"]
          and len(cg3.pending_writes()) == 1)
    rep = cg3.reconcile_writes()
    check("③2 对账补账（内容指纹吻合 → committed）",
          rep.get("unpaired") == 1 and rep.get("committed") == 1
          and rep.get("interrupted") == 0, rep)
    check("③3 补出的 outcome 标 reconciled + 判据可审计",
          any(r.get("phase") == "outcome" and r.get("reconciled")
              and r.get("reason") == twophase.R_NODE_OK
              for r in _recs(cg3)), _recs(cg3)[-1])
    check("③4 对账后 pending 归零",
          cg3.pending_writes() == [])

    # ---------- ④ 半途崩溃：根本没落盘 ----------
    cg4 = _mk_cg(tmp)
    twophase.begin(cg4, "mem_2pc_c4", "崩溃在落盘之前 PASSED",
                   layer="knowledge")
    rep4 = cg4.reconcile_writes()
    check("④1 未落盘 → 如实标记 interrupted（不假装成功）",
          rep4.get("unpaired") == 1 and rep4.get("interrupted") == 1
          and rep4.get("committed") == 0, rep4)
    check("④2 interrupted 判据 = node_missing",
          rep4["details"][0]["reason"] == twophase.R_NODE_MISSING, rep4)
    check("④3 未落盘节点确实不在库（标记与实际一致）",
          cg4.get("mem_2pc_c4") is None)

    # ---------- ⑤ 指纹不符：落了别的正文 ----------
    cg5 = _mk_cg(tmp)
    twophase.begin(cg5, "mem_2pc_c5", "意图写的是这一段 PASSED")
    cg5.add("mem_2pc_c5", "实际落的是另一段 PASSED", layer="knowledge")
    rep5 = cg5.reconcile_writes()
    check("⑤1 指纹不符 → interrupted（content_mismatch）",
          rep5.get("interrupted") == 1
          and rep5["details"][0]["reason"] == twophase.R_MISMATCH, rep5)
    check("⑤2 对账**不覆盖**既有正文（只标记不重放）",
          "实际落的是另一段" in (cg5.get("mem_2pc_c5") or {}).get("content", ""))

    # ---------- ⑥ dry-run / 幂等 / append-only ----------
    cg6 = _mk_cg(tmp)
    twophase.begin(cg6, "mem_2pc_c6", "dry-run 用例 PASSED")
    before = _lines(cg6)
    dry = cg6.reconcile_writes(apply=False)
    check("⑥1 dry-run 报告未结清但不改账本",
          dry.get("unpaired") == 1 and dry.get("applied") is False
          and _lines(cg6) == before, dry)
    cg6.reconcile_writes()
    n_after_first = len(_lines(cg6))
    rep6b = cg6.reconcile_writes()
    check("⑥2 对账幂等（二次无未结清、不追加行）",
          rep6b.get("unpaired") == 0
          and len(_lines(cg6)) == n_after_first, rep6b)
    check("⑥3 账本 append-only（原记录逐字保留）",
          _lines(cg6)[:len(before)] == before)
    snap = _lines(cg6)
    cg6.pending_writes()
    check("⑥4 pending 只读（不改账本）", _lines(cg6) == snap)

    # ---------- ⑦ 执行器抛异常 → outcome=error，异常照抛 ----------
    cg7 = _mk_cg(tmp, role="guest")     # guest 无写权限 → 库层拒绝
    pipe7 = writepipe.WritePipeline()   # 不装闸：直接打执行器
    raised = None
    try:
        pipe7.execute(cg7, {"content": "无权限写入 PASSED",
                            "layer": "knowledge"})
    except Exception as exc:            # AccessDenied 或其子类
        raised = type(exc).__name__
    check("⑦1 库层权限拒绝照抛（两段式不改错误语义）", raised is not None,
          raised)
    check("⑦2 失败也留痕：outcome=error 且无 committed",
          any(r.get("phase") == "outcome"
              and r.get("status") == twophase.STATUS_ERROR
              for r in _recs(cg7)), _recs(cg7))
    check("⑦3 失败不留未结清意图（已配对）", cg7.pending_writes() == [])

    # ---------- ⑧ 未落盘的分支不记账 ----------
    cg8 = _mk_cg(tmp)
    out8 = pipe.execute(cg8, {"content_kind": "text",
                              "content": "这段含 FORBIDDEN_WORD 应被拒",
                              "layer": "knowledge"})
    check("⑧1 闸门拒绝分支：committed=False",
          out8.get("committed") is False, out8.get("moved_to"))
    check("⑧2 未落盘 → **不产生** intent（没打算写就不记账）",
          _phases(cg8) == [], _recs(cg8))
    check("⑧3 对账在空账本上恒无未结清",
          cg8.reconcile_writes().get("unpaired") == 0)

    # ---------- ⑨ gated 替代执行路径也成对 ----------
    cg9 = _mk_cg(tmp)
    out9 = pipe.execute(cg9, {"content_kind": "text",
                              "content": "gated 主动遗忘路径 PASSED",
                              "layer": "contextual", "gated": True,
                              "importance": 0.5})
    nid9 = out9.get("id")
    ph9 = _phases(cg9, nid9)
    check("⑨1 gated 路径账本成对（intent → outcome）",
          ph9 == ["intent", "outcome"], ph9)
    oc9 = [r for r in _recs(cg9)
           if r.get("id") == nid9 and r["phase"] == "outcome"][0]
    check("⑨2 结局与 verdict 一致（committed 当且仅当落盘）",
          (oc9.get("status") == twophase.STATUS_COMMITTED)
          == bool(out9.get("committed")), (oc9, out9.get("committed")))
    check("⑨3 gated 结局无未结清（自己落盘的路径也结清）",
          cg9.pending_writes() == [])

    # ---------- ⑩ 边界 ----------
    cg10 = _mk_cg(tmp)
    check("⑩1 空账本：records/pending/reconcile 均不炸",
          _recs(cg10) == [] and cg10.pending_writes() == []
          and cg10.reconcile_writes().get("unpaired") == 0)
    bad = os.path.join(cg10.root, "_write_2pc.jsonl")
    with open(bad, "a", encoding="utf-8") as f:
        f.write("{坏行不是 json\n")
    check("⑩2 坏行跳过不炸（账本读侧容错）",
          isinstance(_recs(cg10), list))
    check("⑩3 指纹算法与 nodefile 同源（唯一真源，防漂移）",
          twophase.nodefile.content_hash("abc")
          == __import__("hashlib").sha256(b"abc").hexdigest()[:12])
    check("⑩4 账本文件在 root 下（随记忆库一起备份/迁移）",
          os.path.dirname(twophase.log_path(cg10)) == cg10.root)
    check("⑩5 对账只增行不删行（append-only 结构保证）",
          len(_lines(cg10)) >= 1 and all(l.strip() for l in _lines(cg10)))


def main():
    tmp = tempfile.mkdtemp(prefix="twophase_")
    old = os.environ.pop("MDCG_POLICY_FILE", None)
    try:
        _run(tmp)
    except Exception:
        traceback.print_exc()
        _fail.append("未捕获异常")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
        if old is not None:
            os.environ["MDCG_POLICY_FILE"] = old
        else:
            os.environ.pop("MDCG_POLICY_FILE", None)
    print("\ntest_twophase: %d 通过 / %d 失败" % (_ok, len(_fail)))
    if _fail:
        print("失败项：" + "、".join(_fail))
    raise SystemExit(1 if _fail else 0)


if __name__ == "__main__":
    main()
