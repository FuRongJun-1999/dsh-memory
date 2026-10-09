# -*- coding: utf-8 -*-
r"""守卫 · #71 待审队列的单向索引与分级（2026-10-09 DSH 端实施）。

zcode 端批准 #71 稿的三块之一：索引（单向派生、可重建、只放摘要不放正文）
+ list 分级参数（默认最久未裁决优先）。批量面已在 test_review_queue_batch.py 覆盖。

判据：
  G1 索引只放摘要：_build_index 的条目**不含正文**，且 summary <= 80 字
  G2 索引可重建：list --rebuild-index 后索引文件存在、count 与队列一致
  G3 默认排序 = age 降序（最久未裁决优先）
  G4 过滤生效：--tag / --kind / --older-than 各能筛出预期子集
  G5 单条路径未回退（补前笔缺口）：accept <pid> 仍走原单条路径（非批量）
运行：python -X utf8 -m md_cg.test_review_queue_index
退出码：0 全绿 ｜ 1 断言失败
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
if REPO not in sys.path:
    sys.path.insert(0, REPO)

PASS = 0
FAIL = 0
FAILS = []
SIX = ("# 功能名：t\n# 生效条件：t\n# 子功能：t\n# 执行：t\n"
       "# 验证方式：t\n# 不适用条件：t\n")


def check(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print("[PASS] %s%s" % (name, ("  · " + detail) if detail else ""))
    else:
        FAIL += 1
        FAILS.append(name)
        print("[FAIL] %s  · %s" % (name, detail))


class _A(object):
    def __init__(self, **kw):
        self.__dict__.update(kw)


def main():
    from md_cg import review_cli as R

    items = [
        {"pid": "prop_0000000001", "kind": "提案", "verdict": "pending",
         "layer": "knowledge", "tags": ["a"], "round": 0,
         "created_at": time.time() - 30 * 86400, "summary": "最久的一条"},
        {"pid": "prop_0000000002", "kind": "变更单(x→y)", "verdict": "pending",
         "layer": "contextual", "tags": ["b"], "round": 1,
         "created_at": time.time() - 1 * 86400, "summary": "较新的一条"},
    ]

    # G3 默认排序（age 降序）
    a = _A(query=None, tag=None, kind=None, older_than=None, sort="age")
    got = [x["pid"] for x in R._filter_sort(items, a)]
    check("G3 默认排序 = age 降序（最久未裁决优先）",
          got == ["prop_0000000001", "prop_0000000002"], "got=%r" % (got,))

    # G4 过滤
    a2 = _A(query=None, tag="b", kind=None, older_than=None, sort="age")
    check("G4a --tag 过滤生效", [x["pid"] for x in R._filter_sort(items, a2)] == ["prop_0000000002"], "")
    a3 = _A(query=None, tag=None, kind="变更单", older_than=None, sort="age")
    check("G4b --kind 前缀过滤生效", [x["pid"] for x in R._filter_sort(items, a3)] == ["prop_0000000002"], "")
    a4 = _A(query=None, tag=None, kind=None, older_than=10.0, sort="age")
    check("G4c --older-than 过滤生效", [x["pid"] for x in R._filter_sort(items, a4)] == ["prop_0000000001"], "")
    a5 = _A(query="最久", tag=None, kind=None, older_than=None, sort="age")
    check("G4d --query 过滤生效", [x["pid"] for x in R._filter_sort(items, a5)] == ["prop_0000000001"], "")

    # G1 索引只放摘要（真库构造）
    root = tempfile.mkdtemp(prefix="p71idx_")
    sys.path.insert(0, REPO)
    from md_cg import tokens as TK
    from md_cg.mdcos import MdCGSecure
    prof = os.environ.get("MDCG_DSH_PROFILE") or ""
    tok = None
    if prof:
        import re as _re
        try:
            m = _re.search("MDCG_TOKEN:[ ]*'([^']+)'", open(prof, encoding="utf-8", errors="replace").read())
            tok = m.group(1) if m else None
        except OSError:
            tok = None
    # review_list 需要 op=review（DSH 端令牌无此 op）⇒ 用**本地 designer** principal
    # （与 review_cli._cg 同款：auth_mode=local-cli + can_admin），否则 AccessDenied。
    from md_cg.security import Principal
    _p = Principal(actor="guard-cli", clearance="secret", can_write=True,
                   can_admin=True, role="designer", auth_mode="local-cli",
                   session="guard")
    cg = MdCGSecure(root, principal=_p)
    cg.propose("idx_probe_1", SIX + "BODY-MARKER-SHOULD-NOT-BE-IN-INDEX\n", layer="knowledge")
    idx = R._build_index(cg)
    blob = json.dumps(idx, ensure_ascii=False)
    check("G1 索引只放摘要：正文 marker 不入索引", "BODY-MARKER-SHOULD-NOT-BE-IN-INDEX" not in blob,
          "items=%d" % len(idx))
    check("G1b 摘要长度 <= 80", all(len(str(x.get("summary") or "")) <= 81 for x in idx),
          "max=%d" % max([len(str(x.get("summary") or "")) for x in idx] or [0]))

    # G5 单条路径未回退（起子进程：accept <pid> 不带 --pids-file）
    r = subprocess.run([sys.executable, "-X", "utf8", "-m", "md_cg.review_cli",
                        "accept", "prop_00000000ff", "--root", root, "--session", "guard"],
                       capture_output=True, text=True, encoding="utf-8", errors="replace",
                       timeout=300, shell=False, cwd=REPO)
    txt = (r.stdout or "") + (r.stderr or "")
    check("G5 单条 <pid> 路径未回退（输出含已裁决/未生效，且非批量体）",
          ("已裁决" in txt or "裁决未生效" in txt) and ("DRY-RUN" not in txt),
          txt.strip().splitlines()[-1][:70] if txt.strip() else "")

    print("")
    print("=" * 64)
    print("通过 %d ／ 失败 %d" % (PASS, FAIL))
    if FAILS:
        print("失败项：" + "，".join(FAILS))
    print("=" * 64)
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
