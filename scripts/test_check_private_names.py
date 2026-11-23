#!/usr/bin/env python
# -*- coding: utf-8 -*-
r"""scripts/check_private_names.py 的自证（判据有判别力，不是摆设）。

# 功能名：test_check_private_names —— 私域标识冻结守卫的 6 组自证
# 生效条件：本机 git 可执行（用它建临时仓）；临时目录可写
# 子功能：G1 基线一致 ⇒ 绿 / G2 计数增长 ⇒ 红 / G3 新命中文件 ⇒ 红 / G4 基线陈旧 ⇒ 红 /
#         G5 非 git 目录 ⇒ exit 2（fail-closed）/ G6 本仓实跑 ⇒ exit 0（当前基线态）
# 执行：python -X utf8 scripts/test_check_private_names.py
# 验证方式：末行「结果：6 pass / 0 fail」，退出码即判定（0 = 全过）
# 不适用条件：不判「基线里那 828 个文件该不该清」——那是人的裁量动作，见脚本头「不适用条件」。
"""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import check_private_names as M

_PASS = 0
_FAIL = 0


def ok(cond, label, detail=""):
    global _PASS, _FAIL
    if cond:
        _PASS += 1
        print("  [PASS] %s" % label)
    else:
        _FAIL += 1
        print("  [FAIL] %s  %s" % (label, detail))


def _repo(files):
    """建一个有 .git 的临时仓，写入 files 并 git add（ls-files 才看得见）。"""
    root = tempfile.mkdtemp(prefix="privnames_")
    subprocess.run(["git", "init", "-q"], cwd=root, capture_output=True, timeout=60)
    for name, body in files.items():
        path = os.path.join(root, name.replace("/", os.sep))
        os.makedirs(os.path.dirname(path) or root, exist_ok=True)
        with open(path, "w", encoding="utf-8", newline="\n") as f:
            f.write(body)
    subprocess.run(["git", "add", "-A"], cwd=root, capture_output=True, timeout=60)
    return root


def g1_baseline_green():
    root = _repo({"a.md": "一行提到 AEIS 的情况\n"})
    seen = M.count_hits(root, M.tracked_files(root))
    added, grown, stale = M.diff(seen, {"a.md": {"AEIS": 1}})
    ok(not (added or grown or stale), "G1 基线与扫面一致 ⇒ 绿",
       repr((added, grown, stale)))


def g2_growth_red():
    root = _repo({"a.md": "AEIS 两处 AEIS\n"})
    seen = M.count_hits(root, M.tracked_files(root))
    added, grown, stale = M.diff(seen, {"a.md": {"AEIS": 1}})
    ok(bool(grown) and "1 → 2" in grown[0], "G2 计数增长 ⇒ 红（并报出 1 → 2）", repr(grown))


def g3_new_file_red():
    root = _repo({"a.md": "干净\n", "b.md": "这里冒出 AEIS\n"})
    seen = M.count_hits(root, M.tracked_files(root))
    added, _grown, _stale = M.diff(seen, {"a.md": {"AEIS": 0}})
    ok(any("b.md" in a for a in added), "G3 新命中文件 ⇒ 红", repr(added))


def g4_stale_red():
    root = _repo({"a.md": "干净\n"})
    seen = M.count_hits(root, M.tracked_files(root))
    _added, _grown, stale = M.diff(seen, {"gone.md": {"AEIS": 3}})
    ok(any("gone.md" in s for s in stale), "G4 基线陈旧（文件已不在扫面）⇒ 红", repr(stale))


def g5_not_a_repo_fail_closed():
    root = tempfile.mkdtemp(prefix="privnames_bare_")
    rc = M.main(["--root", root])
    ok(rc == 2, "G5 非 git 目录 ⇒ exit 2（fail-closed，不静默放过）", "rc=%r" % rc)


def g6_real_repo_green():
    rc = M.main([])
    ok(rc == 0, "G6 本仓当前基线态 ⇒ exit 0", "rc=%r" % rc)


def main():
    print("check_private_names 自证")
    for fn in (g1_baseline_green, g2_growth_red, g3_new_file_red, g4_stale_red,
               g5_not_a_repo_fail_closed, g6_real_repo_green):
        try:
            fn()
        except Exception as exc:
            ok(False, fn.__name__ + " 未捕获异常", repr(exc))
    print("结果：%d pass / %d fail" % (_PASS, _FAIL))
    return 1 if _FAIL else 0


if __name__ == "__main__":
    sys.exit(main())