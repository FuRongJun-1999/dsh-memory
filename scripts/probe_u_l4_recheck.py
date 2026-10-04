# -*- coding: utf-8 -*-
"""U 维重测探针 v2：标尺 §2.3 L4 四场景 + 回滚链路在 v0.7.2 现值上的重跑。

对照对象：v1.0 报告 §六（2026-09-12）四场景读数——
  S1 同条件不同值 = ACCEPT 静默写入（FAIL）· S2 不同条件 = DEFER（假阳性）·
  S3 负条件互斥 = DEFER+unresolved（PASS）· S4 自否定 = REJECT（PASS）；回滚链路成立。
隔离临时库（tempfile.mkdtemp），不触碰活库。
2026-10-04 复核修订：回滚链断言更正——`evolution.rollback` 只回写状态字段、
正文不参与回滚；原 print 标签「content restored」为误导，已更正并加正文对照两行。
"""
import json
import sys
import tempfile

sys.stdout.reconfigure(encoding="utf-8")

from md_cg.mdcos import MdCGOS
from md_cg import evolution

root = tempfile.mkdtemp(prefix="mdcg_uprobe2_")
cg = MdCGOS(root)
print("root =", root)


def show(tag, r):
    dv = [c for c in (r.get("conflicts") or [])
          if c.get("type") == "same_condition_divergence"]
    cf = [c for c in (r.get("conflicts") or [])
          if c.get("type") != "same_condition_divergence"]
    out = {"verdict": r.get("verdict"), "reason": r.get("reason"),
           "conflict_strength": r.get("conflict_strength")}
    if dv:
        out["divergences"] = [{k: c.get(k) for k in ("with", "same_condition",
                                                     "slot_overlap", "conclusion_overlap")}
                              for c in dv]
    if cf:
        out["other_conflicts"] = [{k: c.get(k) for k in ("type", "with", "score")}
                                  for c in cf]
    if r.get("missing"):
        out["missing"] = r["missing"]
    print(tag, json.dumps(out, ensure_ascii=False, default=str))


# ============ S1：同条件空间 · 结论槽取值分歧（v1.0 时为 ACCEPT 静默覆盖）============
H = ("# 功能名：网关心跳端口与重连参数\n"
     "# 子功能：端口取值与退避次数\n"
     "# 生效条件：网关在线且心跳已启用\n")
BODY_OLD = ("服务端心跳端口：9090。客户端使用长连接轮询，超时时间为 30 秒。\n"
            "故障处置：连接断开后由客户端指数退避重连，最多重试 5 次。")
BODY_NEW = ("服务端心跳端口：8080。客户端使用长连接轮询，超时时间为 30 秒。\n"
            "故障处置：连接断开后由客户端指数退避重连，最多重试 8 次。")
cg.add("s1_old", H + "\n" + BODY_OLD + "\n", layer="knowledge", importance=0.5)
r = cg.check_consistency(H + "\n" + BODY_NEW + "\n", layer="knowledge", depth=0,
                         auto_flywheel=True)
show("S1", r)

# ============ S2：不同条件（v1.0 时只给 DEFER「假阳性」）============
H2 = ("# 功能名：网关心跳端口与重连参数\n"
      "# 子功能：测试环境端口取值与退避次数\n"
      "# 生效条件：测试环境的网关在线且心跳已启用\n")
r = cg.check_consistency(H2 + "\n" + BODY_NEW + "\n", layer="knowledge", depth=0,
                         auto_flywheel=True)
show("S2", r)

# ============ S3：负条件互斥（v1.0 时 DEFER + 落 unresolved）============
cg.add("k_offline", "# 功能名：离线批处理\n# 生效条件：离线环境\n# 不适用条件：生产环境\n",
       layer="knowledge", non_applicable_conditions=["生产环境"], importance=0.4)
r = cg.check_consistency("# 功能名：生产批处理\n# 生效条件：生产环境\n",
                         layer="knowledge", depth=0, auto_flywheel=True)
show("S3", r)

# ============ S4：自否定（v1.0 时 REJECT）============
r = cg.check_consistency("# 功能名：存储策略\n# 生效条件：删除生产数据\n",
                         non_applicable_conditions=["删除生产数据"],
                         layer="knowledge", depth=0)
show("S4", r)

# ============ 回滚链路（v1.0 时成立；本轮实测「变更→留痕→dry_run→实回滚」）============
try:
    before = evolution.state_of(cg, "s1_old")
    cg.add("s1_old", H + "\n" + BODY_NEW + "\n", layer="knowledge",
           importance=0.5, override=True)
    after = evolution.state_of(cg, "s1_old")
    ev = evolution.record(cg, node_id="s1_old", pattern="探针留痕", missing="无",
                          action="结构变更留痕", evidence="u_probe3",
                          before=before, after=after)
    eid = ev.get("entry_id")
    print("EV record:", eid, "| changed:", bool(after != before))
    rb1 = evolution.rollback(cg, eid, dry_run=True)
    print("EV rollback dry ok:", json.dumps(rb1, ensure_ascii=False, default=str)[:240])
    rb2 = evolution.rollback(cg, eid)
    print("EV rollback ok:", json.dumps(rb2, ensure_ascii=False, default=str)[:240])
    back = evolution.state_of(cg, "s1_old")
    print("EV state fields restored:", back == before)
    # 复核修订（2026-10-04）：rollback 仅回写 state_of 状态字段（layer/confidence/
    # importance/condition_space/non_applicable_conditions/edges/verification_basis），
    # **正文不参与回滚**——覆盖后正文原样保留。以下两行对照把该事实公开实测。
    got = cg.get("s1_old") or {}
    _body_now = (got.get("content") or "").strip()
    print("EV content after rollback equals initial (A):",
          _body_now == (H + "\n" + BODY_OLD).strip())
    print("EV content after rollback equals overwritten (B):",
          _body_now == (H + "\n" + BODY_NEW).strip())
except Exception as e:
    print("EV PROBE FAIL:", type(e).__name__, e)

print("DONE")
