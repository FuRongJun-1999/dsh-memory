# -*- coding: utf-8 -*-
r"""护栏 · #87 默认密级必须**单点同值**（2026-10-09 DSH 端；照 test_w7_redlines.py 范式）。

背景（GitHub #87 取证面，本端补）：仓里有两份**互相独立**的默认密级字面量——
  · md_cg/security.py:47  DEFAULT_SENSITIVITY = "internal"   （节点面；mdcos 从它导入）
  · md_cg/docindex.py:57  DEFAULT_SENSITIVITY = "internal"   （文档面；docindex 只 import
                            hashlib/os/re/codeindex/nodefile，**不 import security**）
今天两者**同值**，故不是缺陷；但**没有任何机制保证它们相等**。而 #87 的两条口径路线
（A 收紧读方上限 / B 抬高写方默认）都要动「默认密级」这一概念：

  · 若只改 docindex 那份 ⇒ **文档面**新默认、**节点面**仍旧值 ⇒ 同一条记忆两个默认；
  · 若只改 security 那份 ⇒ 反过来。

这正是本端在 #87 可实施稿里写的「两套默认」风险。本护栏把它从**静默不一致**变成**红测**。
本笔**不改任何产品行为**（两份今天同值，断言即为真），只把该不变式钉住。

判据：
  G1 两份默认密级**相等**（drift 护栏；改任一份而漏另一份 ⇒ 立刻红）
  G2 两份默认密级**都是合法档位**（在 security.SENSITIVITY_ORDER 内）
  G3 mdcos 实际导入的那份与 security 那份同源（防「导入处被换成第三个字面量」）
  G4 ROLE_SPECS 每个角色的 clearance_cap **都是合法档位**（只判合法性，**不判取值**——
     取值属 #87 口径裁定，不在本护栏内）

运行：
  python -X utf8 -m md_cg.test_issue87_default_sensitivity_single
  python -X utf8 -m md_cg.test_issue87_default_sensitivity_single --mutate A
退出码：0 全绿 ｜ 1 断言失败 ｜ 2 锚点漂移（fail-closed）
"""
from __future__ import annotations

import contextlib
import inspect
import io
import sys

from . import docindex, mdcos, security
from . import tokens as _tokens

PASS = 0
FAIL = 0
FAILS: list = []


def check(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print("  [PASS] %s%s" % (name, ("  · " + detail) if detail else ""))
    else:
        FAIL += 1
        FAILS.append(name)
        print("  [FAIL] %s  · %s" % (name, detail))


def group_a(_root=None):
    d_sec = security.DEFAULT_SENSITIVITY
    d_doc = docindex.DEFAULT_SENSITIVITY
    check("G1 两份默认密级相等（drift 护栏：只改一份即红）",
          d_sec == d_doc, "security=%r docindex=%r" % (d_sec, d_doc))

    order = security.SENSITIVITY_ORDER
    check("G2 两份默认密级都是合法档位",
          d_sec in order and d_doc in order, "order=%s" % (list(order),))

    d_md = getattr(mdcos, "DEFAULT_SENSITIVITY", None)
    check("G3 mdcos 导入的那份与 security 同源",
          d_md == d_sec, "mdcos=%r security=%r" % (d_md, d_sec))

    bad = {r: (s or {}).get("clearance_cap")
           for r, s in (_tokens.ROLE_SPECS or {}).items()
           if (s or {}).get("clearance_cap") not in order}
    check("G4 ROLE_SPECS 各角色 clearance_cap 均为合法档位（只判合法性，不判取值）",
          not bad, "非法项=%s" % (bad,))


_GROUPS = {"A": group_a}


# ---------------- 定点变异（内存注入；apply() 返回 restore()） ----------------

def _mut_g1():
    """只改文档面那份 ⇒ 复现「两套默认」（路线 B 只改一半的形态）。"""
    orig = docindex.DEFAULT_SENSITIVITY
    docindex.DEFAULT_SENSITIVITY = "restricted"
    return lambda: setattr(docindex, "DEFAULT_SENSITIVITY", orig)


def _mut_g2():
    """把默认密级改成非法档位。"""
    orig = security.DEFAULT_SENSITIVITY
    security.DEFAULT_SENSITIVITY = "topsecret"
    return lambda: setattr(security, "DEFAULT_SENSITIVITY", orig)


def _mut_g3():
    """把 mdcos 导入处换成第三个字面量。"""
    orig = getattr(mdcos, "DEFAULT_SENSITIVITY", None)
    mdcos.DEFAULT_SENSITIVITY = "public"
    return lambda: setattr(mdcos, "DEFAULT_SENSITIVITY", orig)


def _mut_g4():
    """把某角色的 clearance_cap 改成非法档位。"""
    role = sorted(_tokens.ROLE_SPECS)[0]
    orig = dict(_tokens.ROLE_SPECS[role])
    _tokens.ROLE_SPECS[role] = dict(orig, clearance_cap="topsecret")
    return lambda: _tokens.ROLE_SPECS.__setitem__(role, orig)


#: 组 → [(变异名, 应用函数, 期望转红断言前缀集合)]
_MUTATIONS = {
    # 期望集合**按实测校正**。变异 2 打三条而非一条，是**真实耦合**、不是缺陷：
    # 把 security 那份改成非法档位后，①它与 docindex 那份不再相等（G1 红）
    # ②它自身不再是合法档位（G2 红）③mdcos 用 from-import 取的是**值拷贝**，
    # 仍是旧值 ⇒ 与 security 不再同源（G3 红）。三条都该红。
    "A": [("只改文档面默认（两套默认）", _mut_g1, {"G1"}),
          ("默认密级改成非法档位", _mut_g2, {"G1", "G2", "G3"}),
          ("mdcos 导入处换成第三个字面量", _mut_g3, {"G3"}),
          ("某角色 clearance_cap 改成非法档位", _mut_g4, {"G4"})],
}

#: 源码锚点自检（命中次数必须恰为 1，否则实现已漂移、变异表失效）
_ANCHORS = [
    ("security 默认密级字面量", 'DEFAULT_SENSITIVITY = "internal"', security),
    ("docindex 默认密级字面量", 'DEFAULT_SENSITIVITY = "internal"', docindex),
]


def _anchor_preflight():
    bad = []
    for label, anchor, mod in _ANCHORS:
        src = inspect.getsource(mod)
        n = src.count(anchor)
        if n != 1:
            bad.append((label, anchor, n))
    if not bad:
        return 0
    for label, anchor, n in bad:
        print("  ANCHOR-MISS %s：命中 %d 次（期望 1）%r" % (label, n, anchor))
    print("  => 实现已漂移，变异表失效：退出码 2（fail-closed）")
    return 2


def _run_group(name, root=None):
    global PASS, FAIL
    PASS = FAIL = 0
    del FAILS[:]
    _GROUPS[name](root)
    return ({n.split(" ", 1)[0] for n in FAILS}, PASS, FAIL)


def _mutate(name):
    if name not in _MUTATIONS:
        print("未知组名 %r（可选 %s）" % (name, sorted(_MUTATIONS)))
        return 1
    rc = _anchor_preflight()
    if rc:
        return rc
    print("!! #87 定点变异自证 · 组 %s：内存注入退化，逐条要求**恰好**命中期望红项\n" % name)
    bad = []
    with contextlib.redirect_stdout(io.StringIO()):
        base_red, _, _ = _run_group(name)
    print("  未变异基线：红项 %d %s" % (len(base_red), "（应为 0）" if not base_red else sorted(base_red)))
    if base_red:
        bad.append("基线即转红：%s" % sorted(base_red))
    for mname, apply, expect in _MUTATIONS[name]:
        restore = apply()
        try:
            with contextlib.redirect_stdout(io.StringIO()):
                red, _, _ = _run_group(name)
        except Exception as exc:                      # noqa: BLE001
            red = {"<变异体异常:%s>" % type(exc).__name__}
        finally:
            restore()
        ok = (red == expect)
        print("  [%s] %s → 红项 %s（期望 %s）" % ("OK" if ok else "BAD", mname, sorted(red), sorted(expect)))
        if not ok:
            bad.append("%s：得 %s 期望 %s" % (mname, sorted(red), sorted(expect)))
    if bad:
        print("\n变异自证失败：")
        for b in bad:
            print("  · " + b)
        return 1
    print("\n变异自证通过：%d 条退化各自**恰好**命中期望红项" % len(_MUTATIONS[name]))
    return 0


def main():
    print("[#87 默认密级单点同值] 正断言组 A")
    _run_group("A")
    print("\n==== #87 护栏结果：%d 通过 / %d 失败 ====" % (PASS, FAIL))
    if FAILS:
        print("失败项：" + "、".join(FAILS))
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    if "--mutate" in sys.argv:
        i = sys.argv.index("--mutate")
        sys.exit(_mutate(sys.argv[i + 1] if i + 1 < len(sys.argv) else ""))
    sys.exit(main())
