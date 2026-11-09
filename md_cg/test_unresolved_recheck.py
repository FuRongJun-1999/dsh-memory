"""unresolved 到期复查（recheck v2）判据：正控 / 负控成对。

判据要判什么：`recheck` 只在**点名 ids** 且 `dry_run=False` 时结案；
到期未到、复查期内复现过、未点名、dry_run、别的层、cap 上限——一律不许动。

跑法：`cd /tmp && PYTHONPATH=/home/ubuntu/mdcg python3 -X utf8 -m md_cg.test_unresolved_recheck`
"""
from __future__ import annotations

import os
import shutil
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from md_cg import unresolved as U  # noqa: E402
from md_cg.mdcos import MdCGOS  # noqa: E402

PASS = []
FAIL = []


def ok(cond, name, got=""):
    (PASS if cond else FAIL).append(name)
    print(("PASS " if cond else "FAIL ") + name + (f"  [{got}]" if got else ""))


def layer_of(cg, nid):
    return ((cg.index or {}).get("nodes") or {}).get(nid, {}).get("layer")


def make(root, n):
    cg = MdCGOS(root)
    ids = []
    for i in range(n):
        ids.append(cg.add_unresolved("复查判据问题 %d 号" % i))
    return cg, ids


def main():
    tmp = tempfile.mkdtemp(prefix="unrrecheck-")
    try:
        # ---------- 正控：点名 + 到期 + 未复现 → 结案到 rejected ----------
        root = os.path.join(tmp, "root1")
        cg, ids = make(root, 1)
        nid = ids[0]
        ok(layer_of(cg, nid) == "unresolved", "A0 新写的未解问题在 unresolved 层", layer_of(cg, nid))
        rep = U.recheck(cg, days=0, cap=10, dry_run=False, ids=[nid])
        ok(rep["ok"] and nid in rep["closed"], "A1 点名 + 到期未复现 → 结案", rep.get("closed"))
        ok(layer_of(cg, nid) == "rejected", "A2 结案后层变 rejected（不是删除）", layer_of(cg, nid))

        # ---------- 负控 1：不给 ids → 只出清单，绝不结案 ----------
        root = os.path.join(tmp, "root2")
        cg, ids = make(root, 2)
        nid = ids[0]
        rep = U.recheck(cg, days=0, cap=10, dry_run=False)
        ok(rep.get("no_ids") is True and rep["closed"] == []
           and len(rep["candidates"]) == 2 and layer_of(cg, nid) == "unresolved",
           "B1 不给 ids → 只列清单、一条都不结", rep.get("closed"))
        ok(rep["candidates"][0]["question"].startswith("复查判据问题"),
           "B1b 清单带问题正文（供人判断，而不是只给 id）", rep["candidates"][0]["question"][:20])

        # ---------- 负控 2：未到期 → 不在候选 ----------
        root = os.path.join(tmp, "root3")
        cg, ids = make(root, 1)
        nid = ids[0]
        rep = U.recheck(cg, days=1, cap=10, dry_run=False)
        ok(rep["candidates"] == [] and layer_of(cg, nid) == "unresolved",
           "B2 未到期不进候选", rep.get("candidates"))

        # ---------- 负控 3：复查期内复现（last_access 前移）→ 不进候选 ----------
        root = os.path.join(tmp, "root4")
        cg, ids = make(root, 1)
        nid = ids[0]
        ent = cg.index["nodes"][nid]
        ent["last_access"] = float(ent.get("created_at") or 0) + 7200
        rep = U.recheck(cg, days=0, cap=10, dry_run=False, ids=[nid])
        ok(rep["candidates"] == [] and rep["closed"] == []
           and layer_of(cg, nid) == "unresolved", "B3 复查期内被再访问过 → 不进候选", rep.get("closed"))

        # ---------- 负控 4：dry_run → 点名也不落盘 ----------
        root = os.path.join(tmp, "root5")
        cg, ids = make(root, 1)
        nid = ids[0]
        rep = U.recheck(cg, days=0, cap=10, dry_run=True, ids=[nid])
        ok(rep["closed"] == [] and layer_of(cg, nid) == "unresolved",
           "B4 dry_run 点名也不落盘", rep.get("closed"))

        # ---------- 负控 5：别的层不参与 ----------
        root = os.path.join(tmp, "root6")
        cg, _ = make(root, 1)
        kid = "kn_sample_01"
        cg.add(kid, "普通知识节点，不该被 unresolved 复查碰到", layer="knowledge")
        rep = U.recheck(cg, days=0, cap=10, dry_run=False)
        ok(all(c["id"] != kid for c in rep["candidates"]), "B5 knowledge 节点不进候选", kid)

        # ---------- 负控 6：cap 上限 + 点名不在候选时记 skipped ----------
        root = os.path.join(tmp, "root7")
        cg, ids = make(root, 3)
        rep = U.recheck(cg, days=0, cap=2, dry_run=True)
        ok(len(rep["picked"]) == 2 and len(rep["candidates"]) == 3,
           "B6 cap 只截 picked，候选清单仍全列", (len(rep["picked"]), len(rep["candidates"])))
        rep = U.recheck(cg, days=0, cap=10, dry_run=False, ids=[ids[0], "unr_不存在"])
        ok(rep["closed"] == [ids[0]] and len(rep["skipped"]) == 1,
           "B7 不在候选的 id 记 skipped 而不静默丢弃", rep.get("skipped"))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    print(f"\n{len(PASS)} 通过 / {len(FAIL)} 失败")
    if FAIL:
        for n in FAIL:
            print("  失败：", n)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
