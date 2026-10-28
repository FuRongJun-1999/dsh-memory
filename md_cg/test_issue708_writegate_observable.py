# -*- coding: utf-8 -*-
# 功能名：分层写入闸的可观测性与审计链连续性守卫（issue #708）
# 生效条件：python -X utf8 -m md_cg.test_issue708_writegate_observable；被测面＝writegate.warn_report、security warn 计数、_write_review_record 的 reviewers 透传
# 子功能：①warn 档写入成功且计数可读（不依赖子进程 stderr）②warn_report 形状与有界性 ③enforce 下审计节点**带** reviewers 能落、**不带**仍被拒（对照证明不是放水）④review_decide→_finish_decision→_record_decision→require_layer_write 全链透传锚点
# 执行：临时库跑三种角色/三档位，断言返回体与 warn_report；再静态断言调用链透传
# 验证方式：全部 PASS exit 0，否则 exit 1
# 不适用条件：不判 DSH 是否转发子进程 stderr（宿主面，本守卫只保证"不依赖它"）；不判 review_decide 的业务语义
"""issue #708：warn 档不可观测 + enforce 下裁决审计节点被同一闸挡住。

病灶（报告人 Starrain08 实测）：
  · warn 档只写子进程 stderr，DSH 不转发进 desktop-next.log ⇒ 用户「完全看不到」，等于没有观察期；
  · enforce 档下 `_write_review_record` 写 structural，而 structural 属 2 档（需 reflect+verify），
    该调用**不传 reviewers** ⇒ 审计节点被同一个闸挡住（jsonl 还在，可复核的 md 节点没了）。
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


def _clean_env(T):
    for k in list(os.environ):
        if k.startswith("MDCG_"):
            del os.environ[k]
    os.environ.update(MDCG_ROOT=os.path.join(T, "brain"),
                      MDCG_STATE_ROOT=os.path.join(T, "stroot"),
                      MDCG_AUX_ROOT=os.path.join(T, "auxroot"),
                      MDCG_DATA_ROOT=os.path.join(T, "dataroot"),
                      MDCG_EXPORT_ROOT=T, MDCG_SUSTAIN="0", MDCG_SLEEP="0")


def main():
    T = tempfile.mkdtemp(prefix="i708g_")
    try:
        _clean_env(T)
        from md_cg import writegate as wg
        from md_cg.mdcos import MdCGSecure
        from md_cg.security import Principal
        from md_cg.tokens import role_spec

        def P(role, clr="internal"):
            s = role_spec(role)
            return Principal(role=role, clearance=clr, can_write=s["can_write"],
                             can_admin=s["can_admin"], layers_allow=s["layers_allow"],
                             ops_allow=s["ops_allow"])

        print("== A warn 档：写入成功 + 计数可读（#708 病灶①）")
        os.environ["MDCG_WRITE_GATE"] = "warn"
        os.environ["MDCG_REVIEW_CHANNELS"] = "subagent"
        os.environ.pop("MDCG_REVIEWERS", None)
        base = wg.warn_report()
        cg = MdCGSecure(os.path.join(T, "brain"), principal=P("record"), autoflush=1)
        nid = cg.add("probe_k1", "probe content one", layer="knowledge")
        cg.close()
        ok(bool(nid), "A1 warn 档 write knowledge 成功（不阻断）", nid)
        rep = wg.warn_report()
        ok(rep["total"] >= base["total"] + 1,
           "A2 warn 计数 +1（修前不可见：只写 stderr）", (base["total"], rep["total"]))
        ok(any(k.startswith("knowledge@L1") for k in rep["by_layer"]),
           "A3 计数按层分桶（knowledge@L1）", list(rep["by_layer"])[:4])
        ok(bool(rep["recent"]) and "reason" in rep["recent"][-1],
           "A4 recent 摘要含 reason（无内容、无节点 id）", rep["recent"][-1] if rep["recent"] else None)
        ok(rep["mode"] == "warn", "A5 mode 透出", rep["mode"])

        print("== B warn_report 形状与有界性")
        ok(set(rep) >= {"mode", "total", "by_layer", "recent", "hint"}, "B1 键齐全", sorted(rep))
        ok(len(rep["recent"]) <= 5, "B2 recent 最多 5 条", len(rep["recent"]))
        ok(wg.WARN_RECENT_MAX == 20, "B3 有界常量在位", wg.WARN_RECENT_MAX)

        print("== C enforce：审计节点带 reviewers 能落（#708 病灶②）")
        os.environ["MDCG_WRITE_GATE"] = "enforce"
        sg = role_spec("designer")
        p = Principal(role="designer", clearance="secret", can_write=sg["can_write"],
                      can_admin=sg["can_admin"], layers_allow=sg["layers_allow"],
                      ops_allow=sg["ops_allow"])
        cg2 = MdCGSecure(os.path.join(T, "brain"), principal=p, autoflush=1)
        rec = {"pid": "p1", "round": 1, "decision": "accept", "status": "accepted",
               "redteam_verdict": "absent", "issues": [], "verify_hash": "vh",
               "t": 1793000000, "actor": "tester", "target_id": "n1",
               "record_node_id": "audit_p1_r1", "record_hash": "a" * 64}
        try:
            out = cg2._write_review_record(rec, reviewers=("reflect", "verify"))
            ok(bool(out), "C1 带 reviewers ⇒ 审计节点落盘成功", out)
        except Exception as e:  # noqa: BLE001
            ok(False, "C1 带 reviewers ⇒ 审计节点落盘成功", "%s: %s" % (type(e).__name__, e))

        try:
            cg2._write_review_record(dict(rec, record_node_id="audit_p2_r1"), reviewers=None)
            ok(False, "C2 不带 reviewers 仍应被拒（对照：不是放水）", "竟然成功了")
        except Exception as e:  # noqa: BLE001
            ok("分层复核闸" in str(e) or "AccessDenied" in type(e).__name__,
               "C2 不带 reviewers 仍被拒（对照）", "%s: %s" % (type(e).__name__, str(e)[:60]))
        cg2.close()

        print("== D 全链透传锚点（静态）")
        src = open(os.path.join(ROOT, "md_cg", "mdcos.py"), encoding="utf-8").read()
        ok("def _write_review_record(self, rec, reviewers=None)" in src,
           "D1 _write_review_record 接 reviewers")
        ok("reviewed_by=reviewers" in src, "D2 add(...) 透传 reviewed_by")
        ok("reviewers=kw.get(\"reviewed_by\")" in src,
           "D3 MdCGSecure.add 把 reviewed_by 交给 require_layer_write")
        ok("def _record_decision(self, pid, item, decision, status, reason, round_no," in src,
           "D4 _record_decision 存在")
        ok("_write_review_record(rec, reviewers=reviewers)" in src,
           "D5 _record_decision → _write_review_record 透传")
        ok(src.count("reviewers=reviewed_by)") == 2,
           "D6 两处 _finish_decision 调用点都传 reviewed_by", src.count("reviewers=reviewed_by)"))

        print("== E 透传后仍需齐备（不得变成万能放行）")
        cg3 = MdCGSecure(os.path.join(T, "brain"), principal=p, autoflush=1)
        try:
            cg3._write_review_record(dict(rec, record_node_id="audit_p3_r1"), reviewers=("reflect",))
            ok(False, "E1 只给 reflect（缺 verify）应被拒（2 档需两者）", "竟然成功了")
        except Exception as e:  # noqa: BLE001
            ok("AccessDenied" in type(e).__name__, "E1 只给 reflect 仍被拒", str(e)[:60])
        cg3.close()
    finally:
        shutil.rmtree(T, ignore_errors=True)

    print()
    print("issue #708 守卫：%d 通过 / %d 失败" % (len(_PASS), len(_FAIL)))
    if _FAIL:
        for f in _FAIL:
            print("  -", f)
    return 0 if not _FAIL else 1


if __name__ == "__main__":
    raise SystemExit(main())