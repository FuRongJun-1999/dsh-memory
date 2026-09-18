# -*- coding: utf-8 -*-
"""判据面指纹（口径与编外实例逐字一致，已由反解 + 命中验证：5a2778a -> c5a3280201a4499f）。

# 功能名：判据面指纹复算
# 生效条件：需要比对「判据面文件集合」在两端是否同一（互验断言 A3 的机械输入）时；任一修订号可用
# 子功能：集合=md_cg 下所有 test_*.py + scripts/run_tests.py；算法=sha256(按仓库相对路径升序拼接各文件字节)，取值前 16 个十六进制字符
# 执行：python -X utf8 scripts/criteria_fingerprint.py [--commit <rev>] [--json]（--commit 用 git archive 抽树计算，不改工作树）
# 验证方式：--commit 5a2778a 应得 c5a3280201a4499f（与编外 receipt 一致）；--commit main 同值即表示两端判据面逐字节同一
# 不适用条件：本脚本不入判据集合（名字非 test_*、且非 run_tests.py），但它**落在 scripts/ 下**——若将来口径扩为「scripts 下所有 .py」则会使集合变化，须同步两端
"""
import argparse
import hashlib
import io
import json
import os
import subprocess
import sys
import tarfile
import tempfile

TARGET_REL = "scripts/run_tests.py"
TRUNC = 16


# 生效条件：给定 root 时，递归收集 root/md_cg 下文件名以 test_ 开头且以 .py 结尾的文件（跳过 __pycache__ 目录），并在 os.path.exists(root/TARGET_REL) 为真时追加模块级常量 TARGET_REL，返回去重排序后的以 "/" 分隔的相对路径列表；
def files_from_worktree(root):
    out = []
    for base, dirs, names in os.walk(os.path.join(root, "md_cg")):
        dirs[:] = [d for d in sorted(dirs) if d != "__pycache__"]
        for fn in sorted(names):
            if fn.startswith("test_") and fn.endswith(".py"):
                out.append(os.path.relpath(os.path.join(base, fn), root).replace(os.sep, "/"))
    if os.path.exists(os.path.join(root, TARGET_REL)):
        out.append(TARGET_REL)
    return sorted(set(out))


# 生效条件：对给定 commit 执行 git archive --format=tar 的 returncode 为 0 时，把 stdout 作为 tar 解包到 tempfile.mkdtemp 新建的目录并返回该目录路径，returncode 非 0 时抛 SystemExit；
def worktree_of(commit):
    """把某修订抽到临时目录（git archive + tarfile，纯 Python，不改 .git/工作树）。"""
    r = subprocess.run(["git", "archive", "--format=tar", commit], capture_output=True)
    if r.returncode != 0:
        raise SystemExit("git archive 失败：" + r.stderr.decode("utf-8", "replace")[:200])
    tmp = tempfile.mkdtemp(prefix="criteria_")
    with tarfile.open(fileobj=io.BytesIO(r.stdout)) as tf:
        tf.extractall(tmp)
    return tmp


# 生效条件：给定 root 时，逐个以二进制读取 files_from_worktree(root) 返回的每个文件并更新 sha256，返回 {"files": 该列表长度, "value": 摘要 hexdigest 的前 TRUNC 位}；
def fingerprint(root):
    files = files_from_worktree(root)
    h = hashlib.sha256()
    for f in files:
        with open(os.path.join(root, f), "rb") as fh:
            h.update(fh.read())
    return {"files": len(files), "value": h.hexdigest()[:TRUNC]}


# 生效条件：无必需形参；--commit 为非空串时 root 取 worktree_of(--commit)，为空串时取 --root（argparse 缺省 "."），--json 为真时打印 json.dumps(fp) 否则打印 CRITERIA_FINGERPRINT 单行文本，均返回 0，且 fp["commit"] 在 --commit 为空串时回落为 "<worktree>"、非空串时为该参数值；
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--commit", default="")
    ap.add_argument("--root", default=".")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()
    root = a.root
    if a.commit:
        root = worktree_of(a.commit)
    fp = fingerprint(root)
    fp["commit"] = a.commit or "<worktree>"
    if a.json:
        print(json.dumps(fp, ensure_ascii=False))
    else:
        print("CRITERIA_FINGERPRINT files=" + str(fp["files"]) + " value=" + fp["value"]
              + " commit=" + fp["commit"])
    return 0


if __name__ == "__main__":
    sys.exit(main())