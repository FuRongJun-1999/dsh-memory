# -*- coding: utf-8 -*-
# 功能名：append_jsonl 调用点的「显式承认」白名单（issue #547）
# 生效条件：python -u -X utf8 -m md_cg.test_issue547_append_jsonl_whitelist；被测面＝md_cg/ 下全部非测试 .py 的 AST
# 子功能：S 组＝自证扫描非空转；A 组＝白名单外模块出现 append_jsonl 调用即红；K 组＝白名单内不误报
# 执行：AST 遍历每个文件的 Call 节点，func.id == 'append_jsonl' 即计一次；模块不在 _LOSSY_OK 则收进 violations
# 验证方式：violations 为空且扫描总数 >= 60 即通过（退出码 0）
# 不适用条件：不判「某落点该不该迁 ledger」（那是逐条审定，见 issue 正文）；不判 append_jsonl_ledger（已是分片形态）

# issue #547（2026-10-18 DSH 端）：append_jsonl 的 docstring 划的线是「丢一条无所谓的簿记」，
# 但实测有 67 个直接调用点分布在 30 个模块 —— 里面必然混着「其实不能丢」的落点
# （#543/#546/#549 三次实测：审计台账类丢 29–39% 行而 add 仍返成功）。
#
# 本条不试图一次审定完 67 处（那需要逐点读调用上下文），而是把「沉默的默认」变成「显式的承认」：
#   · 白名单 _LOSSY_OK = 现状 30 模块（承认既有），故现在不红；
#   · 新增的调用点必须先把这个模块加进白名单，加的那一刻就得回答「这处能不能丢」；
#   · 审定完一处就从白名单移除（迁 append_jsonl_ledger 或加 durable=True）。
#
# 这样白名单的长度本身就是进度条：从 30 走向 0，每一步都是「一处落点被确认不能丢并迁走」。
#
# 为什么用 AST 而不是 grep：grep 会把注释、字符串、append_jsonl_ledger(（前缀相同）一并算进去。
_LOSSY_OK = frozenset({
    "backfill", "consolidate", "mdcos", "mdcg", "subgraph",
    "sustain", "crosscheck", "forgetting", "freshness", "govern",
    "predict", "provenance", "vision_evidence", "weights", "autonomy",
    "crypto", "evidence", "fsutil", "goal_gen", "lifecycle",
    "metacognition", "protect", "reconcile", "refine", "rotate",
    "scrub", "sleep", "trust", "twophase", "writepipe",
})

import ast
import os
import sys

MD_PKG = os.path.dirname(os.path.abspath(__file__))

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
        print("  FAIL %s  <- %r" % (title, detail))


def _scan():
    hits = []
    total = 0
    for name in sorted(os.listdir(MD_PKG)):
        if not name.endswith(".py") or name.startswith("test_"):
            continue
        try:
            src = open(os.path.join(MD_PKG, name), encoding="utf-8").read()
        except OSError:
            continue
        if "append_jsonl(" not in src:
            continue
        try:
            tree = ast.parse(src)
        except SyntaxError:
            continue
        n = 0
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and getattr(node.func, "id", None) == "append_jsonl":
                n += 1
        if n:
            hits.append((name[:-3], n))
            total += n
    return hits, total


print("== S 组：扫描非空转（防判据瞎了）==")
hits, total = _scan()
ok(total >= 60, "S1 扫描到 >= 60 个调用点（实测 %d）" % total, total)
ok(len(hits) >= 20, "S2 扫描到 >= 20 个模块（实测 %d）" % len(hits), len(hits))

print("== A 组：白名单外的调用点必须红 ==")
violations = [(m, n) for m, n in hits if m not in _LOSSY_OK]
ok(not violations, "A1 无白名单外的 append_jsonl 调用点", violations)

print("== K 组：白名单内不误报 ==")
in_ok = [(m, n) for m, n in hits if m in _LOSSY_OK]
ok(bool(in_ok), "K1 白名单内仍有已知调用点（%d 模块 / %d 处）" % (len(in_ok), sum(n for _, n in in_ok)), in_ok[:4])

print("")
print("=" * 56)
print("append_jsonl 调用点：白名单 %d 模块 / 已知 %d 处 / 总计 %d 处" % (len(_LOSSY_OK), sum(n for _, n in in_ok), total))
print("通过 %d / 失败 %d" % (PASS, FAIL))
for f in FAILS:
    print("  - %s" % f)
sys.exit(0 if FAIL == 0 else 1)