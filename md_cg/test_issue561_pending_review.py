# -*- coding: utf-8 -*-
# 功能名：#561 第①项（#553 可见性）——读面对「有待复核新值」的节点标注 pending_review
# 生效条件：python -X utf8 -m md_cg.test_issue561_pending_review；被测面＝mcp_server 的 cg(op=read) 单节点分支 + mdcos.pending_proposals
# 子功能：A/K 组＝初始待审与反恒真；R 组＝红队打回、重开实例与再次审批；T 组＝reject/noop 终态；--mutate＝两类错误改法恰好点红
# 执行：直接跑；全部 PASS 即通过（退出码 0）
# 验证方式：断言全过 + 退出码 0；--mutate 的两条定点变异须恰好命中各自红项
# 不适用条件：① 不判检索列表（search/recall）是否逐条标注（本项只钉单节点读面；列表面加标注要按结果数付扫描成本）；
#   ② 不判 DSH 宿主侧提示（#561 第②项）；③ 不判治理面 review_list 的形状（既有守卫覆盖）。
"""issue #561 第①项守卫：读面的「有新值待复核」必须可见。

背景：智能论 3.4 的四态里 DEFER 不冒充接受——但**读者若只看到旧值**，会把「待复核」
误当「最新」。本条不改裁决语义，只在读面 additive 落两个键：
`pending_review: true` 与 `pending_proposals: [pid…]`；没有待复核提案时**不落键**。
"""
from __future__ import annotations

import os
import sys
import tempfile
import json
import subprocess
import inspect
import textwrap

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO not in sys.path:
    sys.path.insert(0, _REPO)

PASS = 0
FAIL = 0
FAILS = []


def ok(cond, title, detail=None):
    global PASS, FAIL
    if cond:
        PASS += 1
        print("  PASS %s" % title)
    else:
        FAIL += 1
        FAILS.append(title)
        print("  FAIL %s  <- %r" % (title, str(detail)[:180]))


def main():
    tmp = tempfile.mkdtemp(prefix="i561_")
    os.environ.update({
        "MDCG_ROOT": os.path.join(tmp, "brain"),
        "MDCG_STATE_ROOT": os.path.join(tmp, "state"),
        "MDCG_AUX_ROOT": os.path.join(tmp, "auxstore"),
        "MDCG_DATA_ROOT": os.path.join(tmp, "data"),
        "MDCG_EXPORT_ROOT": tmp, "MDCG_SUSTAIN": "0", "MDCG_SLEEP": "0",
    })
    for k in ("MDCG_TOKEN", "MDCG_VERIFY_KEY"):
        os.environ.pop(k, None)
    from md_cg import crypto
    os.environ[crypto.MASTER_ENV] = "ab" * 32
    from md_cg import mcp_server as MS
    from md_cg.mdcos import MdCGSecure, MdCGOS
    from md_cg.security import Principal

    _apply_mutation(MdCGOS)

    p = Principal(tenant="t", actor="designer", role="designer",
                  clearance="private", can_write=True, can_admin=True)
    cg = MdCGSecure(os.environ["MDCG_ROOT"], principal=p)
    cg.add("A", "生产环境数据库端口是 5433。", layer="contextual")
    cg.add("B", "与提案无关的节点。", layer="contextual")

    def read(nid):
        return MS.call_tool(cg, "cg", {"op": "read", "node_id": nid})

    print("== A 组：队列里挂着针对 A 的待裁决提案 ==")
    pv = cg.propose("A", "生产环境数据库端口是 5432（新值，待复核）。",
                    layer="contextual", info=True)
    pid = pv.get("pid") if isinstance(pv, dict) else pv
    ok(bool(pid), "A00 提案已入队（前置）", pv)
    ra = read("A")
    ok(isinstance(ra, dict) and ra.get("pending_review") is True,
       "A01 读面标 pending_review=True", ra.get("pending_review") if isinstance(ra, dict) else ra)
    ok(isinstance(ra, dict) and pid in (ra.get("pending_proposals") or []),
       "A02 读面列出待裁决 pid", (ra or {}).get("pending_proposals"))
    ok(isinstance(ra, dict) and "5433" in (ra.get("content") or ""),
       "A03 旧值仍在（不改语义：主库正文逐字不变）", (ra or {}).get("content"))

    print("== K 组：反恒真与边界 ==")
    rb = read("B")
    ok(isinstance(rb, dict) and "pending_review" not in rb
       and "pending_proposals" not in rb,
       "K01 无待复核提案的节点**不落键**（反恒真）",
       {k: v for k, v in (rb or {}).items() if k.startswith("pending")})
    ok(cg.pending_proposals("A") == [pid], "K02 单点读数与读面一致", cg.pending_proposals("A"))
    ok(cg.pending_proposals("") == [] and cg.pending_proposals("NOPE") == [],
       "K03 空/不存在 id ⇒ 空列表（不抛）",
       (cg.pending_proposals(""), cg.pending_proposals("NOPE")))
    print("== R 组：红队打回仍待再审批，读面不能提前关闭 ==")
    rr = cg.review_decide(pid, "reject", redteam={
        "verdict": "reject", "round": 1, "issues": ["合成用例：需再次审批"]})
    ok(rr.get("state") == "needs_reapproval", "R00 红队打回进入非终态", rr)
    queued = [r for r in cg.review_list() if r.get("pid") == pid]
    ok(len(queued) == 1 and queued[0].get("status") == "needs_reapproval"
       and pid not in cg._closed_pids(), "R01 治理面仍待审且未关闭", queued)
    ra_pending = read("A")
    ok(ra_pending.get("pending_review") is True
       and pid in ra_pending.get("pending_proposals", []),
       "R02 待再审批在读面仍可见", ra_pending)
    ok("5433" in ra_pending.get("content", "")
       and "5432" not in ra_pending.get("content", ""),
       "R03 红队打回不写入提案新值", ra_pending.get("content"))
    reopened = MdCGSecure(os.environ["MDCG_ROOT"], principal=p)
    reread = MS.call_tool(reopened, "cg", {"op": "read", "node_id": "A"})
    ok(reread.get("pending_review") is True
       and pid in reread.get("pending_proposals", []),
       "R04 重新打开实例仍可见", reread)
    cg.review_decide(pid, "accept", reason="test",
                     redteam={"verdict": "pass", "round": 2})
    ra2 = read("A")
    ok(isinstance(ra2, dict) and "pending_review" not in ra2,
       "K04 裁决后键随之消失（不是一次性标记）",
       {k: v for k, v in (ra2 or {}).items() if k.startswith("pending")})
    ok(isinstance(ra2, dict) and "5432" in (ra2.get("content") or ""),
       "K05 裁决 accept 后新值已并入（旧值仍在，聚合可读）",
       (ra2 or {}).get("content"))

    print("== T 组：真正终态不得留下待复核标记 ==")
    for nid, action in (("C", "reject"), ("D", "noop")):
        cg.add(nid, "终态对照旧值：" + nid, layer="contextual")
        pv2 = cg.propose(nid, "终态对照候选：" + nid, layer="contextual", info=True)
        pid2 = pv2.get("pid") if isinstance(pv2, dict) else pv2
        before2 = read(nid)
        ok(before2.get("pending_review") is True,
           "T00 " + action + " 对照前置确实待审", before2)
        result2 = cg.review_decide(pid2, action, reason="合成终态对照")
        after2 = read(nid)
        ok(result2.get("ok") is True and "pending_review" not in after2
           and "pending_proposals" not in after2,
           "T01 " + action + " 终态不留标记", after2)

    print("")
    print("=" * 60)
    print("#561① 守卫：%d 通过，%d 失败" % (PASS, FAIL))
    for f in FAILS:
        print("  红项：" + f)
    print("RESULT " + json.dumps({"pass": PASS, "fail": FAIL, "failures": FAILS}, ensure_ascii=False))
    return 0 if FAIL == 0 else 1


def _apply_mutation(cls):
    """只在显式变异子进程内改函数副本，不改磁盘源码。"""
    flag = next((x.split("=", 1)[1] for x in sys.argv
                 if x.startswith("--mutation=")), None)
    if flag is None:
        return
    fn = cls.pending_proposals
    source = textwrap.dedent(inspect.getsource(fn))
    needle = 'if (not pid or (decided.get(pid) or {}).get("status")\n                in TERMINAL_DECISION_STATUS):'
    replacements = {"old-decided": "if not pid or pid in decided:",
                    "keep-terminal": "if not pid:"}
    if flag not in replacements or source.count(needle) != 1:
        raise RuntimeError("变异锚点缺失或未知变异：" + str(flag))
    namespace = dict(fn.__globals__)
    exec(compile(source.replace(needle, replacements[flag]),
                 "<pending-proposals-mutation>", "exec"), namespace)
    cls.pending_proposals = namespace["pending_proposals"]


def _run_mutations():
    expected = {
        "old-decided": {"R02 待再审批在读面仍可见", "R04 重新打开实例仍可见"},
        "keep-terminal": {"K04 裁决后键随之消失（不是一次性标记）",
                          "T01 reject 终态不留标记", "T01 noop 终态不留标记"},
    }
    for name, red in expected.items():
        proc = subprocess.run([sys.executable, "-X", "utf8", "-m",
            "md_cg.test_issue561_pending_review", "--mutation=" + name],
            cwd=_REPO, capture_output=True, text=True, encoding="utf-8", timeout=30)
        lines = [s[len("RESULT "):] for s in proc.stdout.splitlines()
                 if s.startswith("RESULT ")]
        result = json.loads(lines[-1]) if lines else {}
        actual = set(result.get("failures", []))
        if proc.returncode != 1 or actual != red:
            print(proc.stdout)
            print(proc.stderr)
            print("变异自证失败：", name, "expected=", sorted(red), "actual=", sorted(actual))
            return 1
        print("PASS mutation", name, "恰好点红", sorted(actual))
    print("定点变异：2 通过，0 失败")
    return 0


if __name__ == "__main__":
    sys.exit(_run_mutations() if "--mutate" in sys.argv else main())
