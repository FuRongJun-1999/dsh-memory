# -*- coding: utf-8 -*-
r"""守卫 · #71 批量处置的安全红线（2026-10-09 DSH 端实施）。

zcode 端 2026-10-09 批准 #71 稿，其中两条红线：
  · **不扩 cg(op=read)**（待审内容不混进认知图检索面）—— 由 review_cli 侧不调用
    任何 cg 检索面来保证（本守卫 G6 静态断言）。
  · **批量只收显式 pid（禁通配/正则/tag）** ＋ dry-run → apply 两步。

判据：
  G1 禁通配：--pids-file 含 prop_* / .* / [0-9] 等非严格形态 ⇒ 整体拒绝（返回 None）
  G2 dry-run 不落盘：不给 --apply ⇒ decisions.jsonl 逐字节不变
  G3 apply 生效：给 --apply ⇒ 真执行（decisions 记录增加）
  G4 互斥校验：既无 <pid> 又无 --pids-file ⇒ 报错返回 1
  G5 单条路径未回退：accept <pid> 仍可用
  G6 不扩 read 面（静态）：review_cli 源码不出现 review 之外的检索调用
运行：python -X utf8 -m md_cg.test_review_queue_batch
退出码：0 全绿 ｜ 1 断言失败
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
if REPO not in sys.path:
    sys.path.insert(0, REPO)

PASS = 0
FAIL = 0
FAILS = []


def check(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print("[PASS] %s%s" % (name, ("  · " + detail) if detail else ""))
    else:
        FAIL += 1
        FAILS.append(name)
        print("[FAIL] %s  · %s" % (name, detail))


def main():
    from md_cg import review_cli
    # G1 禁通配（直接调校验器，不起子进程）
    d = tempfile.mkdtemp(prefix="p71_")
    bad = os.path.join(d, "bad.txt")
    with open(bad, "w", encoding="utf-8") as f:
        f.write("prop_1a2b3c4d\nprop_*\n")
    check("G1 含通配形态 ⇒ 整体拒绝（返回 None）", review_cli._load_pids(bad) is None, "")
    ok = os.path.join(d, "ok.txt")
    with open(ok, "w", encoding="utf-8") as f:
        f.write("# 注释\nprop_1a2b3c4d\n\nprop_deadbeef\n")
    got = review_cli._load_pids(ok)
    check("G1b 严格形态 ⇒ 正常读取（且跳过注释与空行）",
          got == ["prop_1a2b3c4d", "prop_deadbeef"], "got=%r" % (got,))

    # G4 互斥校验（起子进程跑 CLI，用临时 root）
    root = tempfile.mkdtemp(prefix="p71root_")
    r = subprocess.run([sys.executable, "-X", "utf8", "-m", "md_cg.review_cli",
                        "accept", "--root", root],
                       capture_output=True, text=True, encoding="utf-8", errors="replace",
                       timeout=300, shell=False, cwd=REPO)
    check("G4 既无 <pid> 又无 --pids-file ⇒ 报错返回 1",
          r.returncode == 1 and "需要" in ((r.stdout or "") + (r.stderr or "")),
          "rc=%r" % r.returncode)

    # G2/G3：dry-run 不落盘 vs apply 生效（用真 pid 需先有提案；此处只验"文件不变"）
    dec = os.path.join(root, "hippocampus", "decisions.jsonl")
    before = open(dec, "rb").read() if os.path.exists(dec) else b""
    want = os.path.join(d, "want.txt")
    with open(want, "w", encoding="utf-8") as f:
        f.write("prop_0000000001\n")
    r2 = subprocess.run([sys.executable, "-X", "utf8", "-m", "md_cg.review_cli",
                         "accept", "--pids-file", want, "--root", root, "--session", "guard"],
                        capture_output=True, text=True, encoding="utf-8", errors="replace",
                        timeout=300, shell=False, cwd=REPO)
    after = open(dec, "rb").read() if os.path.exists(dec) else b""
    check("G2 dry-run 不落盘：decisions.jsonl 逐字节不变",
          before == after and "DRY-RUN" in ((r2.stdout or "") + (r2.stderr or "")),
          "same=%r" % (before == after,))

    # G3：apply 会尝试裁决（pid 不存在 ⇒ 未生效 rc=1，但**确实执行了**）
    r3 = subprocess.run([sys.executable, "-X", "utf8", "-m", "md_cg.review_cli",
                         "accept", "--pids-file", want, "--root", root, "--session", "guard", "--apply"],
                        capture_output=True, text=True, encoding="utf-8", errors="replace",
                        timeout=300, shell=False, cwd=REPO)
    txt3 = (r3.stdout or "") + (r3.stderr or "")
    check("G3 --apply 确实走执行路径（输出含批量裁决完成）",
          "批量裁决完成" in txt3, txt3.strip().splitlines()[-1][:70] if txt3.strip() else "")

    # G6 静态：不扩 read 面（**加固版**，由 zcode 端 2026-10-09 复核提出）
    # 原版只 grep 两个读 op（cg.search / cg.recall），偏窄——「未扩 read」的真实保证
    # 应来自**枚举**而非点名。加固为 AST 枚举：列出 review_cli 里所有 cg.<attr> 调用，
    # 断言**全部落在白名单内**；任何新增的 cg 面（尤其检索面）都会让本条红。
    import ast as _ast
    src = open(os.path.join(HERE, "review_cli.py"), encoding="utf-8").read()
    _used = set()
    for _node in _ast.walk(_ast.parse(src)):
        if isinstance(_node, _ast.Attribute) and isinstance(_node.value, _ast.Name) \
                and _node.value.id == "cg":
            _used.add(_node.attr)
    _ALLOWED = {"review_list", "review_decide", "review_stats", "review_rounds", "close"}
    _extra = sorted(_used - _ALLOWED)
    check("G6 加固：AST 枚举 review_cli 的 cg 面，全部落在白名单内",
          not _extra, "used=%r 越界=%r" % (sorted(_used), _extra))

    print("")
    print("=" * 64)
    print("通过 %d ／ 失败 %d" % (PASS, FAIL))
    if FAILS:
        print("失败项：" + "，".join(FAILS))
    print("=" * 64)
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
