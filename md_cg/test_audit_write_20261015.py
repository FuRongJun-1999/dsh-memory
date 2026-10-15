# -*- coding: utf-8 -*-
# 生效条件：python -X utf8 -m md_cg.test_audit_write_20261015 [--mutate] 时运行；
#           被测面 = md_cg/mdcg.py 的 neg_condition_hits。
# 子功能：一组缺陷判据的定点回归——#362(b) 负条件两侧字符归一（NFKC + casefold）。
# 执行：真跑库层调用路径（MdCGOS / judge_qualification），逐条断言读数。
# 验证方式：python -X utf8 -m md_cg.test_audit_write_20261015（全绿 rc=0）；
#           --mutate 逐条把修复判据还原成缺陷形态（**进程内源码替换，不写任何文件**），
#           每一条都必须让套件转红，否则判 ANCHOR-MISS/空转。
# 不适用条件：①只覆盖 #362 的 (b) 宽度/大小写归一，不覆盖 (a) 否定作用域 /
#             (c) 繁简 / (d) 边界问句抑制（本批未修）②不评价检索质量与召回率。
"""审计批次 2026-10-15 写入面单缺陷守卫。

负条件判据缺字符归一是本条缺陷的根因：全角/半角与大小写差异使负条件漏拒。
断言只钉「真实调用路径上的行为读数」，不做源码字面比对之外的形态检查。

--mutate 的变异在**进程内**对函数源码做字面替换后 exec（不落盘、不改源文件），
故共享源码零残留；跨副本的「恢复原缺陷必红」另见证据目录的副本跑法。
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import types

from . import mdcg as M
from .mdcos import MdCGOS

_PASS = []
_FAIL = []


def ok(cond, msg, extra=""):
    (_PASS if cond else _FAIL).append(msg)
    print(("  PASS " if cond else "  FAIL ") + msg
          + (("  <- " + str(extra)) if (extra and not cond) else ""))


def _ccg(name, cond, neg):
    return ("# 功能名：%s\n# 生效条件：%s\n# 子功能：审计探针\n"
            "# 执行：读入参\n# 验证方式：编译器/静态检查通过\n"
            "# 不适用条件：%s\n" % (name, cond, neg))


# ---------------------------------------------------------------- D（#362b）
def d_neg_condition_normalization():
    print("== D 负条件两侧字符归一（issue #362 b）==")
    cases = (
        ("D1 负条件全角 / 问句半角", ["４Ｇ单模终端"], "4G单模终端 支持吗", True),
        ("D2 负条件全角数字 / 问句半角", ["ＵＳＢ２．０接口"],
         "USB2.0接口 怎么接", True),
        ("D3 负条件小写 / 问句大写", ["pdf 扫描件"], "PDF 扫描件 怎么处理", True),
        ("D4 对照·只中一词仍放行", ["抓取 管线"], "抓取这条路怎么走", False),
        ("D5 对照·旁注通用词不否决", ["其它机器/其它 DSH profile"],
         "DSH 端怎么接", False),
    )
    for label, neg, q, expect in cases:
        got = bool(M.neg_condition_hits(neg,
                                        json.dumps({"query": q},
                                                   ensure_ascii=False), ""))
        ok(got == expect, "%s（期望命中=%s）" % (label, expect), got)
    root = tempfile.mkdtemp(prefix="audit362_")
    cg = MdCGOS(root)
    cg.add("neg_fw", _ccg("终端接入方式", "问终端接入方式时", "４Ｇ单模终端")
           + "\n正文。", layer="knowledge", verification_basis="test",
           non_applicable_conditions=["４Ｇ单模终端"])
    node = cg.get("neg_fw") or {}
    q = M.MdCG.judge_qualification(
        {"frontmatter": node.get("frontmatter") or {},
         "content": node.get("content") or ""}, "4G单模终端 支持吗", None)
    ok(q.get("state") == "REJECT",
       "D6 端到端：资格判定腿按负条件命中判 REJECT", q)
    cg.close()


_GROUPS = (d_neg_condition_normalization,)


# ---------------------------------------------------------------- 变异自证
# 每条 = (说明, 目标, 还原成缺陷形态的替换对)。替换在**进程内**做（exec 源码副本），
# 不写盘、不改共享源码；锚点必须逐字出现在当前实现里，漂移即 ANCHOR-MISS（rc=2）。
_MUTATIONS = (
    ("#362b 归一函数退化成恒等", "neg_condition_hits",
     ("    def _fold(s):\n"
      '        return unicodedata.normalize("NFKC", s).casefold()',
      "    def _fold(s):\n"
      "        return s")),
)

_TARGETS = {
    "neg_condition_hits": lambda: (M, "neg_condition_hits", None),
}


def _run_groups() -> int:
    _PASS.clear()
    _FAIL.clear()
    for g in _GROUPS:
        g()
    return len(_FAIL)


def _func_source(func, name) -> str:
    """取函数源码：`inspect.getsource` 对模块级函数会连带整份模块文本返回
    （源码尾部不含函数定义头的行即被一并带上），直接字面替换会改到别处。
    这里从 `def <name>(` 那一行截起，末尾补一个换行。"""
    import inspect
    src = inspect.getsource(func)
    lines = src.splitlines()
    head = "def %s(" % name
    for i, l in enumerate(lines):
        if l.startswith(head):
            return "\n".join(lines[i:]) + "\n"
    return src


def _mutate():
    print("!! 变异模式：把修复判据逐条还原成缺陷形态，套件必须转红\n")
    live = {n: getattr(*_TARGETS[n]()[:2]) for n in _TARGETS}
    bad = []
    clean = _run_groups()
    print("  未变异基线：失败=%d" % clean)
    if clean:
        bad.append("未变异基线即失败")
    for name, target, (old, new) in _MUTATIONS:
        holder, attr, prefix = _TARGETS[target]()
        src = _func_source(getattr(holder, attr), attr)
        if old not in src:
            print("  ANCHOR-MISS %s —— 变异锚点漂移（实现改了却没同步本表）" % name)
            bad.append(name)
            continue
        ns = dict(vars(holder if isinstance(holder, types.ModuleType)
                           else sys.modules[holder.__module__]))
        body = src.replace(old, new)
        exec(compile((prefix or "") + body, "audit_mut.py", "exec"), ns)
        setattr(holder, attr, ns[attr])
        try:
            fails = _run_groups()
        finally:
            setattr(holder, attr, live[target])
        verdict = "红（有判别力）" if fails else "**仍全绿 = 该判据断言空转**"
        print("  %s → 失败=%d  %s" % (name, fails, verdict))
        if not fails:
            bad.append(name)
    print("\n变异判别力：%s" % ("PASS（每条修复判据都有断言把它钉死）" if not bad
                                else "FAIL —— " + "、".join(bad)))
    return 0 if not bad else 2


def main() -> int:
    if "--mutate" in sys.argv:
        return _mutate()
    for g in _GROUPS:
        g()
    print("\n审计写入面守卫：%d 通过，%d 失败" % (len(_PASS), len(_FAIL)))
    return 0 if not _FAIL else 1


if __name__ == "__main__":
    sys.exit(main())
