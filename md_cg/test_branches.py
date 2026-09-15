# -*- coding: utf-8 -*-
"""记忆演化分支（branches，Pi 移植④）验收：交接文档 §3④。

蓝图验收两条：
① fork → 分支改写 → merge 后主支节点 derived_from 链完整可回溯；
② 放弃分支不污染主支检索（召回主支时分支节点零命中）。
"""

import os
import shutil
import sys
import tempfile
import traceback

from . import branches
from .mdcos import MdCGSecure
from .security import AccessDenied, Principal

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


def _mk_cg(tmp, role="designer", seq=[0]):
    seq[0] += 1
    root = os.path.join(tmp, "root_%02d_%s" % (seq[0], role))
    p = Principal(tenant="default", actor="t_" + role, role=role,
                  can_write=(role != "guest"),
                  can_admin=(role == "designer"))
    return MdCGSecure(root, principal=p)


def _fm(cg, nid):
    rec = cg.get(nid) or {}
    return rec.get("frontmatter") or {}


def _content(cg, nid):
    return ((cg.get(nid) or {}).get("content") or "").strip()


def _hits(cg, q, **kw):
    """命中集 id 清单（零污染断言的口径：分支 nid 不出现，而非结果为空——
    T3 全扫兜底本就会返回低分主支节点，那是检索器既有行为不是污染）。"""
    return [h[0].get("id") for h in cg.search(q, **kw)[0]]


def main():
    tmp = tempfile.mkdtemp(prefix="branches_")
    try:
        _run(tmp)
    except Exception:
        traceback.print_exc()
        _bad.append("未捕获异常")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    print("\nbranches 验收：%d 通过%s" % (
        _ok, ("，%d 失败：%s" % (len(_bad), "; ".join(_bad))) if _bad else ""))
    return 1 if _bad else 0


def _run(tmp):
    # ---------- 1 fork：副本血缘 + 防呆 + 幂等 ----------
    cg = _mk_cg(tmp)
    cg.add("mem_a", "A内容alpha", layer="knowledge", verification_basis="test",
           consistency=False)
    cg.add("mem_b", "B内容beta", layer="contextual", verification_basis="test",
           consistency=False, derived_from=["anc1"], relation="merged_from")
    r = branches.fork(cg, ["mem_a", "mem_b"], branch_id="exp1", note="实验一")
    _check("fork成功", r.get("ok") is True and r.get("branch_id") == "exp1",
           repr(r))
    fm_a = _fm(cg, "mem_a@exp1")
    _check("副本血缘", fm_a.get("branch_id") == "exp1"
           and fm_a.get("branched_from") == "mem_a"
           and fm_a.get("derived_from") == ["mem_a"]
           and fm_a.get("derived_relation") == "split_from", repr(fm_a))
    _check("副本内容继承", _content(cg, "mem_a@exp1") == "A内容alpha")
    _check("fork空入参拒", branches.fork(cg, []).get("ok") is False)
    _check("fork非法id拒", branches.fork(
        cg, ["mem_a"], branch_id="BAD ID!").get("ok") is False)
    r2 = branches.fork(cg, ["mem_a", "mem_a", "mem_c"], branch_id="exp1")
    _check("fork幂等skipped", r2.get("ok") is False
           and len([s for s in r2.get("skipped", [])
                    if "已存在" in s.get("why", "")]) == 2
           and len([s for s in r2.get("skipped", [])
                    if "不存在" in s.get("why", "")]) == 1, repr(r2))

    # ---------- 2 蓝图验收②：主支检索零污染 ----------
    # 分支上改写副本走 rewrite（唯一正路）——add 是全量重建 fm，裸 add
    # 不重传 branch_id 会让副本在索引里退化成主支（实验泄漏进主支检索）。
    rr = branches.rewrite(cg, "mem_a@exp1", "A改写exp版")
    _check("rewrite改写成功", rr.get("ok") is True
           and rr.get("branch_id") == "exp1", repr(rr))
    # rewrite 防呆：非分支/不存在拒；归属与血缘不可篡改（extra 伪造键被剥离）
    _check("rewrite非分支拒", branches.rewrite(
        cg, "mem_a", "x").get("ok") is False)
    _check("rewrite不存在拒", branches.rewrite(
        cg, "mem_z@exp1", "x").get("ok") is False)
    branches.rewrite(cg, "mem_a@exp1", "A改写exp版", branch_id="伪造",
                     branched_from="mem_zzz", derived_from=["fake"])
    fm_rr = _fm(cg, "mem_a@exp1")
    _check("rewrite归属不可篡改", fm_rr.get("branch_id") == "exp1"
           and fm_rr.get("branched_from") == "mem_a"
           and fm_rr.get("derived_from") == ["mem_a"], repr(fm_rr))
    _check("主支检索分支内容零命中",
           "mem_a@exp1" not in _hits(cg, "A改写exp版"),
           repr(_hits(cg, "A改写exp版")))
    _check("主支检索原内容仍命中", bool(cg.search("A内容alpha")[0]))
    _check("分支内检索命中改写",
           bool(branches.search(cg, "A改写exp版", "exp1")[0]),
           repr(branches.search(cg, "A改写exp版", "exp1")))
    _check("分支内检索主支也可见",
           bool(branches.search(cg, "B内容beta", "exp1")[0]))
    # 其他分支互不可见（用各自独有内容词验：对方分支 nid 不在命中集）
    branches.fork(cg, ["mem_a"], branch_id="exp2")
    branches.rewrite(cg, "mem_a@exp2", "A改写exp2版")
    h_e1 = [h[0].get("id") for h in branches.search(cg, "A改写exp2版",
                                                    "exp1")[0]]
    h_e2 = [h[0].get("id") for h in branches.search(cg, "A改写exp版",
                                                    "exp2")[0]]
    _check("跨分支隐身",
           "mem_a@exp2" not in h_e1 and "mem_a@exp1" not in h_e2,
           "e1=%r e2=%r" % (h_e1, h_e2))

    # ---------- 3 蓝图验收①：merge 溯源链完整 ----------
    r = branches.merge(cg, "exp1", reason="实验通过")
    _check("merge成功", r.get("ok") is True and len(r.get("merged", [])) == 2,
           repr(r))
    _check("主支内容已回写", _content(cg, "mem_a") == "A改写exp版")
    fm_a = _fm(cg, "mem_a")
    chain = fm_a.get("derived_from") or []
    _check("主支链追加分支且原链保留",
           "mem_a@exp1" in chain
           and fm_a.get("derived_relation") == "merged_from"
           and fm_a.get("merged_from_branch") == "exp1", repr(fm_a))
    anc = _fm(cg, "mem_b").get("derived_from") or []
    _check("原链保留(mem_b)", "anc1" in anc and "mem_b@exp1" in anc, repr(anc))
    _check("merge后主支检索命中回写", bool(cg.search("A改写exp版")[0]))
    _check("merge幂等安全", branches.merge(cg, "exp1").get("ok") is True
           and _content(cg, "mem_a") == "A改写exp版")
    r = branches.merge(cg, "br_void")
    _check("merge空分支拒", r.get("ok") is False)

    # merge 时主支不可达 → skipped 不炸（索引与脏缓存一并摘除才是完整模拟）
    cg2 = _mk_cg(tmp)
    cg2.add("mem_x", "X内容", layer="knowledge", verification_basis="test",
            consistency=False)
    branches.fork(cg2, ["mem_x"], branch_id="orphan")
    (cg2.index["nodes"]).pop("mem_x", None)
    (cg2._dirty or {}).pop("mem_x", None)
    r = branches.merge(cg2, "orphan")
    _check("merge主支缺失skipped", r.get("ok") is False
           and len(r.get("skipped", [])) == 1, repr(r))

    # ---------- 4 discard：教训必填 + 冷归档 + 权限 ----------
    cg3 = _mk_cg(tmp)
    cg3.add("mem_k", "K内容", layer="knowledge", verification_basis="test",
            consistency=False)
    branches.fork(cg3, ["mem_k"], branch_id="dead")
    branches.rewrite(cg3, "mem_k@dead", "K改写dead版")
    r = branches.discard(cg3, "dead", "假设有错，教训：不要急")
    _check("discard缺标记拒", r.get("ok") is False
           and set(r.get("missing", [])) == {"分支假设", "实验结果"}
           and r.get("required") == list(branches.BRANCH_MARKS), repr(r))
    # guest 无 can_admin → 结构性拒绝（guest 无写权建不了节点，
    # 分支由 designer 建好并 flush 后，guest 开同一 root 只试 discard）
    branches.fork(cg3, ["mem_k"], branch_id="guest_br")
    cg3.flush()
    cg_guest = MdCGSecure(cg3.root,
                          principal=Principal(tenant="default",
                                              actor="t_guest", role="guest",
                                              can_write=False,
                                              can_admin=False))
    try:
        branches.discard(cg_guest, "guest_br",
                         "分支假设x 实验结果y 教训z")
        _check("discard需can_admin", False, "guest 未被拒")
    except AccessDenied:
        _check("discard需can_admin", True)
    except Exception as e:  # noqa: BLE001
        _check("discard需can_admin", False,
               "异常=%s:%s" % (type(e).__name__, e))
    # designer 全流程
    r = branches.discard(cg3, "dead",
                         "分支假设：覆盖写更快 实验结果：丢失血缘 教训：血缘必保留")
    _check("discard成功", r.get("ok") is True and r.get("moved") == 1, repr(r))
    _check("教训节点入库", bool(_fm(cg3, "branch_summary_dead")))
    _check("教训节点可检索", bool(cg3.search("血缘必保留")[0]),
           repr(cg3.search("血缘必保留")))
    cold = os.path.join(cg3.root, branches.COLD_DIR, "dead",
                        "mem_k@dead.md")
    _check("分支文件冷区保留", os.path.exists(cold), cold)
    _check("索引已摘除", "mem_k@dead" not in cg3.index["nodes"])
    _check("list_branches已不含", all(
        b.get("branch_id") != "dead"
        for b in branches.list_branches(cg3).get("branches", [])))
    _check("discard空分支拒",
           branches.discard(cg3, "dead", "分支假设a 实验结果b 教训c").get("ok")
           is False)

    # ---------- 5 list_branches 聚合 + insight act 分派冒烟 ----------
    cg4 = _mk_cg(tmp)
    cg4.add("mem_p", "P内容", layer="knowledge", verification_basis="test",
            consistency=False)
    branches.fork(cg4, ["mem_p"], branch_id="live1")
    lst = branches.list_branches(cg4)
    g = {b.get("branch_id"): b for b in lst.get("branches", [])}.get("live1")
    _check("list_branches聚合", g is not None and g.get("nodes") == ["mem_p@live1"]
           and g.get("branched_from") == ["mem_p"], repr(lst))
    r = cg4.insight("fork", node_ids=["mem_p"], branch_id="live2", note="n")
    _check("insight act=fork", r.get("ok") is True
           and r.get("branch_id") == "live2", repr(r))
    r = cg4.insight("branches")
    _check("insight act=branches", r.get("ok") is True
           and len(r.get("branches", [])) == 2, repr(r))
    r = cg4.insight("branch_rewrite", node_id="mem_p@live2", content="P内容v2")
    _check("insight act=branch_rewrite", r.get("ok") is True
           and _content(cg4, "mem_p@live2") == "P内容v2", repr(r))
    r = cg4.insight("branch_search", content="P内容v2", branch_id="live2")
    _check("insight act=branch_search", bool(r[0]), repr(r))
    r = cg4.insight("branch_merge", branch_id="live2", reason="r")
    _check("insight act=branch_merge", r.get("ok") is True
           and _content(cg4, "mem_p") == "P内容v2", repr(r))
    r = cg4.insight("branch_discard", branch_id="live2",
                    content="分支假设p 实验结果q 教训r")
    _check("insight act=branch_discard", r.get("ok") is True, repr(r))

    # ---------- 6 session 过滤正交不回归 ----------
    cg5 = _mk_cg(tmp)
    cg5.add("mem_s1", "会话一内容", layer="knowledge", verification_basis="test",
            consistency=False)
    branches.fork(cg5, ["mem_s1"], branch_id="sx")
    res, meta = cg5.search("会话一内容", session="sess_zzz")
    _check("session过滤与branch过滤正交", not res, repr(res))
    res, meta = cg5.search("会话一内容")
    _check("默认检索主支正常", bool(res), repr(meta))


if __name__ == "__main__":
    sys.exit(main())
