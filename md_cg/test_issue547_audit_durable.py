# -*- coding: utf-8 -*-
# 功能名：#547 审计账本写点的耐用性一致性（同一 `_audit.jsonl` 不得一半 durable、一半缺省）
# 生效条件：python -X utf8 -m md_cg.test_issue547_audit_durable；被测面＝md_cg/ 下非测试 .py 的 AST
# 子功能：A 组＝凡向 AUDIT_FILE 追加的 append_jsonl 调用必须带 durable=True · K 组＝扫描面非空转 ·
#         E 组＝主写点（mdcos._audit）仍在位（判据锚）
# 执行：AST 遍历每个 Call 节点，`append_jsonl` 且第一实参源码含 AUDIT_FILE ⇒ 查 keywords 里 durable 为真
# 验证方式：违例为空且命中数 >= 4 即通过（退出码 0）
# 不适用条件：① 不判 `append_jsonl_ledger`（identity 的分片形态，走 read_jsonl_ledger 读面）；
#   ② 不判其它账本（decisions/inbox 用 strict=True，见各自注释）；③ 不判写失败后的记账链（fsutil 单点）。
"""issue #547 守卫：审计账本写点的耐用性必须一致。

背景（#549 实测）：`append_jsonl` 缺省是「丢一条无所谓的簿记」，6 进程 × 20 条实测
静默丢 **29–39%** 行。`_audit.jsonl` 的主写点（`mdcos._audit`）已改 `durable=True`
（FileLock 临界区内追加），但 `protect` / `trust` / `lifecycle` / `crypto` 也写**同一个
文件**、却仍走缺省路 ⇒ 同一账本两种耐用性：丢行时「发生过」与「没发生过」不可区分
（T0 ③ 静默错误）。本守卫把「凡写 `_audit.jsonl` 必 durable」钉成结构判据。
"""
from __future__ import annotations

import ast
import glob
import io
import os
import sys

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
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


def _durable(call):
    for kw in call.keywords:
        if kw.arg == "durable" and isinstance(kw.value, ast.Constant) \
                and kw.value.value is True:
            return True
    return False


def main():
    hits, bad = [], []
    for p in sorted(glob.glob(os.path.join(_REPO, "md_cg", "*.py"))):
        base = os.path.basename(p)
        if base.startswith("test_"):
            continue
        src = io.open(p, encoding="utf-8").read()
        try:
            tree = ast.parse(src)
        except SyntaxError:
            continue
        for n in ast.walk(tree):
            if not (isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
                    and n.func.id == "append_jsonl"):
                continue
            if not n.args:
                continue
            seg = ast.get_source_segment(src, n.args[0]) or ""
            if "AUDIT_FILE" not in seg:
                continue
            rel = "md_cg/" + base
            hits.append((rel, n.lineno))
            if not _durable(n):
                bad.append((rel, n.lineno))

    print("== A 组：写 `_audit.jsonl` 的 append_jsonl 必须 durable ==")
    ok(len(hits) >= 4, "K01 扫描面非空转（命中的审计写点 %d 处）" % len(hits), hits)
    ok(not bad, "A01 审计写点全部带 durable=True（同一账本一种耐用性）", bad)

    print("== E 组：主写点锚 ==")
    msrc = io.open(os.path.join(_REPO, "md_cg", "mdcos.py"), encoding="utf-8").read()
    ok("append_jsonl(self.audit_log, rec, durable=True)" in msrc,
       "E01 mdcos._audit 的主写点仍为 durable（本判据的锚）")

    print("")
    print("=" * 56)
    print("#547 审计耐用性守卫：%d 通过，%d 失败" % (PASS, FAIL))
    for f in FAILS:
        print("  红项：" + f)
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
