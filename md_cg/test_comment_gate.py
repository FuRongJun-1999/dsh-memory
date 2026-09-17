# -*- coding: utf-8 -*-
"""comment_gate 验收（环二入口）。

验收口径：
1. 唯一真源：阈值取 refine.GATE_MIN_PASS_RATE（本模块不再定义一份）
2. 候选判据机械：只有「代码节点且正文缺生效条件」入池（有注释的那条不入池）
3. 工单：确定性抽样（同 seed 同工单）+ 带源码落点（code_ref 坐标 + 落点规则）
4. 只读纪律：apply 只落留痕，**不改任何节点**（改前改后内容 sha 相同）
5. 闸门：<0.90 不放行、>=0.90 放行、无批次不放行
6. 分派：run(action=comment_gate) 走只读工单；comment_gate_verdict 走闸门
"""
from __future__ import annotations

import os
import sys
import tempfile

from . import codeindex, comment_gate, refindex, refine
from .mdcos import MdCGSecure
from .security import Principal

_ok = 0
_bad = []


def _check(name, cond, detail=""):
    global _ok
    if cond:
        _ok += 1
        print("  ok   %s" % name)
    else:
        _bad.append("%s %s" % (name, detail))
        print("  FAIL %s %s" % (name, detail))


ANNOTATED = ('"""样本。"""' + chr(10) + chr(10) + chr(10) +
             "# 生效条件：入参 x 为整数" + chr(10) +
             "def with_cond(x):" + chr(10) + "    return x + 1" + chr(10))
PLAIN = ('"""样本。"""' + chr(10) + chr(10) + chr(10) +
         "def no_cond(x):" + chr(10) + "    return x + 2" + chr(10))


def _mk_graph(root):
    p = Principal(tenant="default", actor="t_test", role="designer",
                  can_write=True, can_admin=True)
    return MdCGSecure(root, principal=p)


def main():
    print("=" * 68)
    print("md_cg comment_gate 验收（代码符号条件化注释抽样闸门）")
    print("=" * 68)
    tmp = tempfile.mkdtemp(prefix="mdcg_comment_gate_")
    root = os.path.join(tmp, "root")
    code = os.path.join(tmp, "code")
    os.makedirs(code)
    with open(os.path.join(code, "a.py"), "w", encoding="utf-8") as f:
        f.write(ANNOTATED)
    with open(os.path.join(code, "b.py"), "w", encoding="utf-8") as f:
        f.write(PLAIN)
    cg = _mk_graph(root)
    items, errors, stats = refindex.index_dir(code, kind="code_ref",
                                             ledger=refindex.Ledger(cg.root))
    ids, _sens = refindex.add_items(cg, items, kind="code_ref", root=code)
    cg.flush()
    print("索引条目=%d 节点=%d 错误=%d" % (len(items), len(ids), len(errors)))

    _check("阈值唯一真源=refine.GATE_MIN_PASS_RATE",
           comment_gate.GATE_MIN_PASS_RATE == refine.GATE_MIN_PASS_RATE,
           str(comment_gate.GATE_MIN_PASS_RATE))
    by_name = {it["name"]: codeindex.node_id(it) for it in items}
    cands, cmeta = comment_gate.candidates(cg)
    # 注：模块级条目同样缺生效条件 → 也是合法候选；故按符号名判定而非计条数
    _check("候选判据机械：缺生效条件者入池、已注释者不入池",
           by_name["no_cond"] in cands and by_name["with_cond"] not in cands,
           "cands=%s no=%s with=%s" % (len(cands), by_name["no_cond"],
                                       by_name["with_cond"]))
    _check("候选池状态如实上报（pool/candidates 与实取一致）",
           cmeta.get("pool", 0) == len(items) and cmeta.get("candidates") == len(cands),
           str(cmeta))
    p1 = comment_gate.plan(cg, n=20, seed="cmt-1")
    p2 = comment_gate.plan(cg, n=20, seed="cmt-1")
    _check("同 seed 工单确定性（sample 与 sha 一致）",
           p1["sample"] == p2["sample"] and p1["sample_sha"] == p2["sample_sha"],
           str(p1["sample"]))
    _check("工单只读（dry_run=True，不改节点）", p1["dry_run"] is True and p1["readonly"] is True)
    it = next((x for x in p1["items"]
               if (x.get("code_ref") or {}).get("name") == "no_cond"), {})
    ref = (it.get("code_ref") or {})
    _check("工单带源码落点坐标（path/lineno/end）",
           ref.get("path") == "b.py" and ref.get("lineno") and ref.get("end"),
           str(ref))
    _check("工单带落点规则（两窗口，契约 §三.2）",
           "leading" in str(it.get("landing_rule") or "")
           and "body" in str(it.get("landing_rule") or ""),
           str(it.get("landing_rule"))[:80])
    _check("工单缺项口径=缺生效条件",
           it.get("ccg_missing") == ["生效条件"], str(it.get("ccg_missing")))
    _check("SPEC 四项核对清单与 0.90 闸门口径在案",
           len(comment_gate.SPEC["review_items"]) == 4
           and comment_gate.SPEC["gate"]["min_pass_rate"] == 0.90)

    nid = by_name["no_cond"]
    before = (cg.get(nid) or {}).get("content") or ""
    r = comment_gate.apply(cg, n=20, seed="cmt-1", verdicts=["忠实"],
                           actor="t_test", note="自测")
    after = (cg.get(nid) or {}).get("content") or ""
    _check("apply 落留痕且通过率=1.0", r["ok"] and r["gate"]["pass_rate"] == 1.0,
           str(r.get("gate")))
    _check("apply 之后放行（>=0.90）", r["gate"]["expand_allowed"] is True)
    _check("apply 不改节点（内容逐字相同）", before == after and before != "")
    _check("留痕文件已落盘", os.path.exists(os.path.join(root, comment_gate.LOG_NAME)))
    g1 = comment_gate.gate(cg)
    _check("gate 复算通过率=1.0 且放行", g1["pass_rate"] == 1.0 and g1["expand_allowed"] is True,
           str(g1))
    r2 = comment_gate.apply(cg, n=20, seed="cmt-1", verdicts=[False, False, False],
                            actor="t_test", batch="low")
    _check("低通过率（0/3）不放行且给原因",
           r2["gate"]["expand_allowed"] is False and "rate" in str(r2["gate"]["reason"]),
           str(r2["gate"]))
    g2 = comment_gate.gate(cg, batch="low")
    _check("gate(batch=low) 复算为不放行", g2["expand_allowed"] is False, str(g2))
    g3 = comment_gate.gate(cg, batch="不存在")
    _check("无批次 → no_batch 不放行", g3["expand_allowed"] is False
           and g3["reason"] == "no_batch", str(g3))
    run1 = comment_gate.run(cg, "comment_gate", n=5)
    _check("run(comment_gate) 走只读工单", run1["dry_run"] is True
           and run1["action"] == "comment_gate")
    from . import mcp_server
    d1 = mcp_server._maintain_call(cg, {"op": "maintain", "action": "comment_gate", "n": 5})
    _check("经 maintain 分派可达（op 面接线）",
           d1.get("action") == "comment_gate" and d1.get("dry_run") is True
           and d1.get("readonly") is True, str(d1.get("action")))
    d2 = mcp_server._maintain_call(cg, {"action": "comment_gate_gate"})
    _check("经 maintain 分派可取闸门（comment_gate_gate）",
           "expand_allowed" in d2, str(sorted(d2.keys()))[:90])
    from .mdcos import MdCGSecure as _S
    from .security import AccessDenied as _AD
    cg_low = _S(root, principal=Principal(tenant="default", actor="t_low",
                                          role="record", can_write=True,
                                          can_admin=False))
    denied = False
    try:
        comment_gate.apply(cg_low, n=5, seed="cmt-1", verdicts=["忠实"])
    except _AD:
        denied = True
    except Exception:
        denied = False
    _check("apply 需管理权（闸门自持在模块内，分发面不漏挂）", denied)
    d3 = mcp_server._maintain_call(cg, {"action": "comment_gate_verdict"})
    _check("经 maintain 分派可取闸门（别名 comment_gate_verdict）",
           "expand_allowed" in d3, str(sorted(d3.keys()))[:90])
    run2 = comment_gate.run(cg, "comment_gate_verdict")
    _check("run(comment_gate_verdict) 走闸门", "expand_allowed" in run2)
    raised = False
    try:
        comment_gate.run(cg, "nope")
    except ValueError:
        raised = True
    _check("未知 action fail-closed", raised)
    # ---- 源级候选枚举（绕开重索引代价；不依赖认知图）----
    sp1 = comment_gate.plan_sources(code, n=20, seed="src-1")
    _check("源级枚举可见未注释符号（不依赖认知图）",
           sp1["examined"] >= 1 and sp1["candidates"] >= 1 and sp1["sampled"] >= 1,
           "examined=%s cands=%s sampled=%s" % (sp1["examined"], sp1["candidates"],
                                                sp1["sampled"]))
    src_names = [it["name"] for it in sp1["items"]]
    _check("源级工单排除已注释符号（no_cond 在、with_cond 不在）",
           "no_cond" in src_names and "with_cond" not in src_names, str(src_names))
    _check("源级工单带源码坐标（path/lineno/end）",
           all((it["code_ref"].get("path") and it["code_ref"].get("lineno")
                and it["code_ref"].get("end")) for it in sp1["items"]))
    _check("源级抽样确定性（同 seed 同工单）",
           comment_gate.plan_sources(code, n=20, seed="src-1")["items"] == sp1["items"])
    _check("源级工单只读且声明模式",
           sp1["dry_run"] is True and sp1["mode"] == "source_level")
    _check("源级枚举经 run 分派可达",
           comment_gate.run(cg, "comment_gate_sources", n=5)["mode"] == "source_level")
    print()
    print("PASS %d / FAIL %d" % (_ok, len(_bad)))
    for b in _bad:
        print("  - " + b)
    return 1 if _bad else 0


if __name__ == "__main__":
    sys.exit(main())
