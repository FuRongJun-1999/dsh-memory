# -*- coding: utf-8 -*-
# 功能名：复核模型在 enforce 档下的端到端可用性守卫（issue #709 及其连带发现）
# 生效条件：python -X utf8 -m md_cg.test_issue709_review_chain_enforce；被测面＝propose / review_decide(accept) / 审计节点 在 MDCG_WRITE_GATE=enforce 下的完整链
# 子功能：①propose 不被写层闸拦（否则死锁：要写 knowledge 需 reflect→要 reflect 需裁决→要裁决需提案→提案又要 reflect）②review_decide(accept, reviewed_by) 落业务节点成功 ③同一次裁决的审计节点也落盘且 record_error 为空 ④skip_gate 只给 propose（不得外溢到落盘路径）⑤层白名单/dual_check 不被削弱
# 执行：临时库 + enforce 档，按「propose → accept」真实顺序跑一遍，断言返回体关键字段
# 验证方式：全部 PASS exit 0，否则 exit 1
# 不适用条件：不判 warn/off 档行为（那两条由 test_issue708 / test_writegate_tiers 覆盖）；不判 MCP 层序列化
"""issue #709：enforce 下「批了但审计节点写不进去」，以及修它时连带发现的两个更靠前的缺口。

病灶链（都在同一条 reviewed_by 通路上）：
  ① `propose` 不落盘却按目标层要求复核单元 ⇒ enforce 下**连提案都提不进去**（死锁）；
  ② `review_decide` 的 accept 落业务节点（`add`）不传 reviewed_by ⇒ **裁决过了、落盘被拦**；
  ③ `_write_review_record` 写 structural 审计节点不传 reviewers ⇒ **审计链断裂**（#709 原文）。
"""
import os
import shutil
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

_PASS, _FAIL = [], []


def ok(cond, msg, detail=""):
    (_PASS if cond else _FAIL).append(msg)
    print(("  PASS " if cond else "  FAIL ") + msg + (("  <- " + str(detail)) if detail and not cond else ""))


def _fresh(T):
    for k in list(os.environ):
        if k.startswith("MDCG_"):
            del os.environ[k]
    os.environ.update(MDCG_ROOT=os.path.join(T, "brain"),
                      MDCG_STATE_ROOT=os.path.join(T, "stroot"),
                      MDCG_AUX_ROOT=os.path.join(T, "auxroot"),
                      MDCG_DATA_ROOT=os.path.join(T, "dataroot"),
                      MDCG_EXPORT_ROOT=T, MDCG_SUSTAIN="0", MDCG_SLEEP="0",
                      MDCG_WRITE_GATE="enforce", MDCG_REVIEW_CHANNELS="subagent")


def main():
    T = tempfile.mkdtemp(prefix="i709g_")
    try:
        _fresh(T)
        from md_cg.mdcos import MdCGSecure
        from md_cg.security import Principal
        from md_cg.tokens import role_spec

        sg = role_spec("designer")
        p = Principal(role="designer", clearance="secret", can_write=sg["can_write"],
                      can_admin=sg["can_admin"], layers_allow=sg["layers_allow"],
                      ops_allow=sg["ops_allow"])
        cg = MdCGSecure(os.path.join(T, "brain"), principal=p, autoflush=1)

        print("== A propose 在 enforce 下可用（死锁已解，病灶①）")
        try:
            pid = cg.propose("prop_a", "probe content A", layer="knowledge")
            ok(bool(pid), "A1 propose knowledge 成功（修前：被写层闸拦 ⇒ 死锁）", str(pid))
        except Exception as e:  # noqa: BLE001
            ok(False, "A1 propose knowledge 成功", "%s: %s" % (type(e).__name__, e))
            pid = None
        ok(callable(getattr(cg, "propose", None)), "A2 propose 方法仍在（未被移除）")

        print("== B accept 落业务节点（病灶②）")
        if pid:
            try:
                res = cg.review_decide(str(pid), "accept",
                                       reviewed_by=["reflect", "verify"], decided_by="tester")
                ok(bool(res.get("ok")), "B1 accept 返回 ok", res.get("error") or res.get("detail"))
                ok(bool(res.get("node_id")), "B2 业务节点已落盘（node_id 有值）", res.get("node_id"))
                ok(not res.get("record_error"),
                   "B3 **record_error 为空**（#709 原病灶：审计节点不再被同一闸拒）",
                   res.get("record_error"))
                ok(bool(res.get("record_node_id")),
                   "B4 审计节点 id 有值（审计链未断）", res.get("record_node_id"))
            except Exception as e:  # noqa: BLE001
                ok(False, "B1 accept 返回 ok", "%s: %s" % (type(e).__name__, e))

        print("== C skip_gate 不得外溢（只有 propose 用）")
        src = open(os.path.join(ROOT, "md_cg", "mdcos.py"), encoding="utf-8").read()
        n_skip = src.count("skip_gate=True")
        ok(n_skip == 1, "C1 全仓只有一处 skip_gate=True（propose）", n_skip)
        sec = open(os.path.join(ROOT, "md_cg", "security.py"), encoding="utf-8").read()
        ok("skip_gate: bool = False" in sec, "C2 require_layer_write 的 skip_gate 缺省 False")
        ok("if skip_gate:" in sec and "return None" in sec, "C3 skip_gate 只跳过闸、不跳过前面两步")
        i_skip = sec.find("if skip_gate:")
        i_allow = sec.find("if not self.allows_layer(layer)")
        ok(0 < i_allow < i_skip,
           "C4 层白名单检查在 skip_gate **之前**（未被跳过）", (i_allow, i_skip))

        print("== D 层白名单仍生效（propose 不得越权）")
        sg2 = role_spec("verify")
        p2 = Principal(role="verify", clearance="internal", can_write=sg2["can_write"],
                       can_admin=sg2["can_admin"], layers_allow=sg2["layers_allow"],
                       ops_allow=sg2["ops_allow"])
        cg2 = MdCGSecure(os.path.join(T, "brain"), principal=p2, autoflush=1)
        try:
            cg2.propose("prop_b", "probe content B", layer="knowledge")
            ok(False, "D1 verify 角色 propose knowledge 应被层白名单拒", "竟然成功了")
        except Exception as e:  # noqa: BLE001
            ok("无权写入" in str(e), "D1 verify 角色 propose knowledge 被层白名单拒", str(e)[:60])
        cg2.close()

        print("== E 落盘路径仍受闸（skip_gate 没有削弱写入）")
        try:
            cg.add("probe_direct", "probe content C", layer="knowledge")
            ok(False, "E1 无 reviewed_by 直写 knowledge 应被拒", "竟然成功了")
        except Exception as e:  # noqa: BLE001
            ok("分层复核闸" in str(e), "E1 无 reviewed_by 直写 knowledge 仍被拒（闸未被削弱）", str(e)[:60])
        # knowledge 是 1 档（只需 reflect）⇒ 给了 reflect **本就该通过**，这是档位正确的证据。
        try:
            nid2 = cg.add("probe_direct2", "probe content D", layer="knowledge",
                          reviewed_by=["reflect"])
            ok(bool(nid2), "E2 只给 reflect 直写 knowledge **通过**（1 档语义正确）", nid2)
        except Exception as e:  # noqa: BLE001
            ok(False, "E2 只给 reflect 直写 knowledge 应通过（1 档）", "%s: %s" % (type(e).__name__, str(e)[:60]))
        cg.close()
    finally:
        shutil.rmtree(T, ignore_errors=True)

    print()
    print("issue #709 守卫：%d 通过 / %d 失败" % (len(_PASS), len(_FAIL)))
    if _FAIL:
        for f in _FAIL:
            print("  -", f)
    return 0 if not _FAIL else 1


if __name__ == "__main__":
    raise SystemExit(main())