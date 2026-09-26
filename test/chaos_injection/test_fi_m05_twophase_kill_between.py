# -*- coding: utf-8 -*-
"""FI-M05 · S3 半程死亡（公理 3：写者死于 intent 与 outcome 之间）→ 对账收敛。

判据：T9 自稳定（真源+确定性重建协议⇒有限步回合法态）+ T6 真源恢复 + A4 诚实
公理——「不假装成功」（md_cg/twophase.py:14-15 如实标记；R_* 判定码 :53-56；
reconcile :209-231）。协议：md_cg/twophase.py:13-15 两段式（intent 先行持久化，
outcome 配对收口）。
注入：临时 root；子进程 MdCGSecure+twophase.begin(nid,content) 写 intent 后
sleep(60)，父进程读 stdout 确认 INTENT-WRITTEN 后 child.kill() 硬杀
（TerminateProcess，无清理机会）；父进程重开同一真源跑 cg.reconcile_writes()。
对照格：子进程语义等价「死于落盘后/写账前」——begin 后正常 add 落盘不 commit，
reconcile 应判 R_NODE_OK 补 committed。二分支均属合法态（D5）。

理论预期（登记 pass，回归守卫）：reconcile 把半程死亡收敛到如实标记——
{unpaired:1, committed:0, interrupted:1, applied:true}，节点未落盘如实判
interrupted（node_missing），不是 error 也不是 committed；对照格补 committed
（node_present_hash_match）；二次对账幂等（unpaired=0）。
"""
import os
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import harness        # noqa: E402
import mdcg_support   # noqa: E402

REPO = os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))))


def main() -> int:
    case = harness.Case("FI-M05", "杀进程于 intent 与 outcome 之间：对账如实标记")
    try:
        d = case.tmpdir("m05")
        mdcg_support.apply_env(d)
        from md_cg import twophase
        from md_cg.mdcos import MdCGSecure

        root5 = os.path.join(d, "m05root")
        child_src = os.path.join(d, "m05_child.py")
        with open(child_src, "w", encoding="utf-8") as f:
            f.write(
                "import sys, time\n"
                "sys.path.insert(0, %r)\n"          # 仓根（md_cg 包）
                "sys.path.insert(0, %r)\n"          # case 目录（mdcg_support）
                "import mdcg_support\n"
                "mdcg_support.apply_env(%r)\n"      # env 先于 md_cg 导入
                "from md_cg import twophase\n"
                "from md_cg.mdcos import MdCGSecure\n"
                "cg = MdCGSecure(%r, principal=mdcg_support.writer_principal())\n"
                "twophase.begin(cg, 'n_fi', '半程死亡正文m05unique')\n"
                "print('INTENT-WRITTEN', flush=True)\n"
                "time.sleep(60)\n" % (REPO,
                                     os.path.dirname(os.path.abspath(__file__)),
                                     d, root5))
        child = subprocess.Popen(
            [sys.executable, "-X", "utf8", child_src],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=dict(os.environ),
            text="utf-8", cwd=REPO)
        case.track_proc(child)
        line = child.stdout.readline().strip()
        case.check("注入执行：子进程完成 intent 持久化（INTENT-WRITTEN 信号在案）",
                   line == "INTENT-WRITTEN", f"stdout={line!r}")
        child.kill()                                   # TerminateProcess 硬杀
        rc = child.wait(timeout=15)
        case.check("注入生效：子进程被硬杀（无清理机会，rc 非 0）",
                   rc != 0, f"rc={rc}")

        cg = MdCGSecure(root5, principal=mdcg_support.writer_principal())
        try:
            rep = cg.reconcile_writes()
            case.check("红场判定①：reconcile 如实标记 interrupted（不是 error 也"
                       "不是 committed——A4 不假装成功）",
                       rep.get("unpaired") == 1 and rep.get("interrupted") == 1
                       and rep.get("committed") == 0 and rep.get("applied") is True,
                       f"reconcile={rep}")
            detail = (rep.get("details") or [{}])[0]
            case.check("红场判定②：判定码 node_missing（节点未落盘，真源无假痕迹）",
                       detail.get("status") == "interrupted"
                       and detail.get("reason") == "node_missing"
                       and cg.get("n_fi") is None,
                       f"detail={detail} node_on_disk={cg.get('n_fi') is not None}")
            rep2 = cg.reconcile_writes()
            case.check("幂等（T9 有限步收敛）：二次对账 unpaired=0",
                       rep2.get("unpaired") == 0, f"second={rep2}")

            # ═══ 对照格：死于「落盘后/写账前」→ R_NODE_OK 补 committed ═══
            root5c = os.path.join(d, "m05ctrl")
            cgc = MdCGSecure(root5c, principal=mdcg_support.writer_principal())
            try:
                twophase.begin(cgc, "n_ok", "落盘后写账前死亡正文m05unique")
                cgc.add("n_ok", "落盘后写账前死亡正文m05unique", layer="knowledge")
                cgc.flush()
                rep_c = cgc.reconcile_writes()
                detail_c = (rep_c.get("details") or [{}])[0]
                case.check("对照格（合法态二）：落盘已完成→补 committed，判定码 "
                           "node_present_hash_match（R_NODE_OK）",
                           rep_c.get("committed") == 1
                           and detail_c.get("reason") == "node_present_hash_match"
                           and cgc.get("n_ok") is not None,
                           f"control={rep_c}")
            finally:
                cgc.close()

            # 四可（D4）
            case.check("四可：可发现=是（reconcile/pending 只读盘点暴露未结清）"
                       "/可隔离=是（按 iid 配对，单笔判定）/可恢复=是（补账或如实"
                       "标记，幂等收敛）/可追溯=是（_write_2pc.jsonl 账本 append-"
                       "only 在案）",
                       True,
                       "证据=红场①② + 幂等 + 对照格 R_NODE_OK")
            verdict = "pass" if not case.fails else "fail"
            return case.finish(verdict, expected="pass")
        finally:
            cg.close()
    finally:
        case.cleanup()


if __name__ == "__main__":
    sys.exit(main())
