# -*- coding: utf-8 -*-
r"""守卫 · #69 内外面边界（2026-10-09 设计者裁决「甲」）。

裁决原文：「（inbox 明文处置）：甲＝保裁决（原文可追溯）。隐私是对外隐私。
内部交流都以可追溯为标准」。全文见节点 mem_ruling_69_20261009。

⇒ 本守卫钉两条**相反方向**的性质，缺一不可：
  G1 **对外隔离**：hippocampus 必须在 admission._SKIP_DIRS 里 ⇒ inbox 不进发布件。
  G2 **内部保留**：DEFER（进审核队列）的提案正文**逐字**留在 inbox，**不脱敏**。
  G3 **REJECT 分支仍脱敏**（既有行为未回退）：命中禁表的写入在 rejected/ 里不留原文。
  G4 判据自洽：G2 与 G3 并存 ⇒「保留/脱敏」是按**分支**分的，不是按"是否敏感"分的。

判据为何不恒真：G1 指向一个**集合成员**（移除即红）；G2/G3 都指向**文件里有无某段文本**
（可构造反例）；G4 是 G2∧G3 的合取，任一被改都会红。
运行：python -X utf8 -m md_cg.test_issue69_audit_boundary
退出码：0 全绿 ｜ 1 断言失败
"""
from __future__ import annotations

import os
import re
import sys
import tempfile

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


def _cg(root):
    from md_cg import tokens as TK
    from md_cg.mdcos import MdCGSecure
    prof = os.environ.get("MDCG_DSH_PROFILE") or ""
    tok = None
    if prof:
        try:
            m = re.search("MDCG_TOKEN:[ ]*'([^']+)'",
                          open(prof, encoding="utf-8", errors="replace").read())
            tok = m.group(1) if m else None
        except OSError:
            tok = None
    return MdCGSecure(root, principal=TK.verify_token(tok) if tok else None)


def main():
    from md_cg import admission, writepipe
    # G1 对外隔离
    check("G1 hippocampus 在 admission._SKIP_DIRS（inbox 不进发布件）",
          "hippocampus" in tuple(getattr(admission, "_SKIP_DIRS", ()) or ()),
          "_SKIP_DIRS=%r" % (getattr(admission, "_SKIP_DIRS", None),))

    root = tempfile.mkdtemp(prefix="p69_")
    cg = _cg(root)
    pipe = writepipe.WritePipeline()

    # G2 内部保留：**直接走 inbox 的写入口**（MdCGSecure.propose）验证正文逐字保留。
    # 两版教训（留档）：首版用 content_kind="text"、次版用 "work_done" 经 pipe.execute
    # 构造，**两次都实测被判 ACCEPT 直接落盘、inbox 根本没被创建** ⇒ 判据落空。
    # 原因是 DEFER→propose 的出口判定不在 writepipe.execute 这一层。
    # #69 的命题本身就是「inbox 里保不保留原文」⇒ 直接测 propose 最贴题、也最稳。
    marker = "INTERNAL-TRACE-MARKER-9f3a"
    cg.propose("p69_defer", marker, layer="knowledge")
    inbox = os.path.join(root, "hippocampus", "inbox.jsonl")
    box = ""
    if os.path.exists(inbox):
        box = open(inbox, encoding="utf-8", errors="replace").read()
    check("G2 DEFER 提案正文逐字留在 inbox（不脱敏，内部可追溯）",
          marker in box, "inbox 存在=%r 命中=%r" % (os.path.exists(inbox), marker in box))

    # G2b（**#69 甲的核心断言**）：连**含凭据形态**的正文也必须逐字留在 inbox——
    # 甲明确「不收窄明文面」。若有人给 propose 加脱敏，本条必红（＝变异②的等价物：
    # 不需要改代码注入，而是断言"保留"这件事本身，任何收窄都会打破它）。
    secret_like = "password=NotARealPassword123"
    cg.propose("p69_defer_secret", secret_like, layer="knowledge")
    box2 = ""
    if os.path.exists(inbox):
        box2 = open(inbox, encoding="utf-8", errors="replace").read()
    check("G2b 含凭据形态的正文也逐字留 inbox（甲：不收窄明文面）",
          secret_like in box2, "命中=%r" % (secret_like in box2))

    # G3 REJECT 分支仍脱敏：命中禁表 ⇒ rejected/ 不留原文
    secret = "password=NotARealPassword123"
    pipe.execute(cg, {"node_id": "p69_reject", "content": SIX + secret + "\n",
                      "content_kind": "text"})
    rej_dir = os.path.join(root, "rejected")
    leaked = False
    if os.path.isdir(rej_dir):
        for fn in os.listdir(rej_dir):
            try:
                if secret in open(os.path.join(rej_dir, fn), encoding="utf-8",
                                  errors="replace").read():
                    leaked = True
            except OSError:
                continue
    check("G3 REJECT 分支仍脱敏（rejected/ 不留原文）", not leaked, "leaked=%r" % leaked)

    # G4 两面并存（保留按分支分，不按"是否敏感"分）
    check("G4 保留与脱敏并存 ⇒ 边界按分支划分（G2 ∧ G3）", (marker in box) and (not leaked),
          "")

    print("")
    print("=" * 64)
    print("通过 %d ／ 失败 %d" % (PASS, FAIL))
    if FAILS:
        print("失败项：" + "，".join(FAILS))
    print("=" * 64)
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
