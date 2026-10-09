# -*- coding: utf-8 -*-
r"""守卫 · #88 冲突检测的**结论面**（2026-10-09 DSH 端实施，照 test_w7_redlines.py 范式）。

缺陷（GitHub #88）：consistency._body_text 调 nodefile._strip_ccg_segments 把六要素
**整段**剥掉，其中含承载结论的「# 执行」行；而 policy 强制 text 类须写成六要素
⇒ **最规范的记忆正文恒为空** ⇒ 结论比较两侧皆空、恒判相等 ⇒ 同条件下「端口 5432」
与「端口 6543」判「无冲突」（ACCEPT）。

修法（路线 A）：新增独立函数 _conclusion_text 作为**结论面**，与 _body_text 分离；
_body_text 行为**一字不动**（它仍归自否定检测使用——那里必须剥掉「不适用条件」，
否则每个声明了不适用条件的正常节点都会被误判为自相矛盾）。

结论面口径（**实测选定，非偏好**）：
  CONCLUSION_FIELDS = ("执行",)  ＋  CONCLUSION_INCLUDE_BODY = True
  ⇒ 结论面 = 「执行」行 + 自由正文。
  三变体实测（四探针 × 四条既有验收件）：
    V1 子功能+执行 + 含正文 → 探针 R1/R2/R3a/R3b = DEFER/DEFER/ACCEPT/DEFER；p11 45/0
    V2 执行 only  + 含正文 → 同上，**与 V1 逐位相同**（子功能冗余）
    V3 执行 only  + 不含正文 → p11 **43/2**（G2/G3 红：结论写在自由正文里的形态被吞）
  ⇒ 按「最小改动优先」取 V2；V3 证明「含正文」是必需的。

判据（正断言组 A）：
  A1 结论在六要素「执行」行内、其余字段全同 ⇒ **DEFER**（修前 ACCEPT —— 本 issue 的核心）
  A2 无「执行」行、结论写在自由正文 ⇒ **DEFER**（防「只取字段」把这类真分歧吞掉）
  A3 结论面完全相同（真重复）⇒ **ACCEPT**（防放宽成「一律报冲突」）
  A4 结论面两边皆空 ⇒ **ACCEPT**（无从分歧；与改前口径一致，不制造假冲突）

反面证明（--mutate A）：在内存中注入「该能力丧失」，要求**恰好**命中期望红项集合。
运行：
  python -X utf8 -m md_cg.test_issue88_conclusion_face             # 正断言
  python -X utf8 -m md_cg.test_issue88_conclusion_face --mutate A  # 变异自证
退出码：0 全绿 ｜ 1 断言失败 ｜ 2 锚点漂移（变异表失效，fail-closed）
"""
from __future__ import annotations

import contextlib
import inspect
import io
import sys
import tempfile

from .mdcos import MdCGOS
from . import consistency, nodefile

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


CS = {"task": "端口配置", "env": "生产"}


def _six(exec_line):
    return ("# 功能名：数据库端口配置\n"
            "# 生效条件：部署到生产环境时\n"
            "# 子功能：端口取值\n"
            "# 执行：" + exec_line + "\n"
            "# 验证方式：读配置文件确认\n"
            "# 不适用条件：本地开发环境\n")


def _verdict(a_content, b_content):
    root = tempfile.mkdtemp(prefix="p88g_")
    cg = MdCGOS(root)
    cg.add("k_a", a_content, layer="knowledge", condition_space=CS,
           importance=0.5, consistency=False)
    r = consistency.check(cg, b_content, layer="knowledge",
                          condition_space=CS, log_write=False)
    return r.get("verdict"), len(r.get("conflicts") or [])


#: 自由正文相同的一句（用于构造「正文同、执行行不同」）
_TAIL = "同一份记录。\n"


def group_a(_root):
    v, d = _verdict(_six("端口是 5432"), _six("端口是 6543"))
    check("A1 结论在六要素「执行」行内、其余字段全同 ⇒ DEFER（修前 ACCEPT —— 本 issue 核心）",
          v == "DEFER" and d == 1, "%s/%d" % (v, d))

    # 构造要点：**「执行」行两侧相同、结论只在自由正文里**——这才是「含正文」真正
    # 必需的形态（V3 变体 p11 43/2 的同源形态：G2/G3 标定用例没有「执行」行）。
    # 首版 A2 把「执行」行也写成 5432/6543 ⇒ 关掉含正文后执行行仍不同、照判 DEFER，
    # 变异2 因此不转红（用例没打到被变异的那一层）。
    # 构造要点：**没有「执行」行**、结论只在自由正文里——这正是 p11 的 G2/G3
    # 标定用例形态，也是「含正文」真正必需的形态（V3 变体实测 p11 43/2 即此形态被吞）。
    _noexec_a = ("# 功能名：数据库端口配置\n"
                 "# 生效条件：部署到生产环境时\n"
                 "# 子功能：端口取值\n"
                 "# 不适用条件：本地开发环境\n"
                 "生产库对外端口是 5432，仅内网可达。\n")
    _noexec_b = ("# 功能名：数据库端口配置\n"
                 "# 生效条件：部署到生产环境时\n"
                 "# 子功能：端口取值\n"
                 "# 不适用条件：本地开发环境\n"
                 "生产库对外端口是 6543，需经跳板机访问。\n")
    v, d = _verdict(_noexec_a, _noexec_b)
    check("A2 无「执行」行、结论只在自由正文 ⇒ DEFER（防只取字段吞掉这类真分歧）",
          v == "DEFER" and d == 1, "%s/%d" % (v, d))

    # A5：有「执行」行且**两侧逐字相同**（模板话），结论只在正文 —— 必须仍判 DEFER。
    # 这条一度被我误记为「已知边界：模板话稀释导致判 ACCEPT」，实际那次 ACCEPT 的真因是
    # CONCLUSION_FIELDS 常量被写坏（见 A6），**稀释并不存在**。留此断言以防该误判回流。
    v, d = _verdict(_six("按配置文件设定") + "生产库对外端口是 5432。\n",
                    _six("按配置文件设定") + "生产库对外端口是 6543。\n")
    check("A5 执行行两侧逐字相同（模板话）、结论只在正文 ⇒ 仍 DEFER（无稀释）",
          v == "DEFER" and d == 1, "%s/%d" % (v, d))

    # A6：结论面常量的**形态**自检。曾经踩过：生成式拼 "(" + '"执行"' + ")" 漏掉尾逗号
    # ⇒ ("执行") 在 Python 里是**字符串**而非元组 ⇒ 被迭代成「执」「行」两个字段名
    # ⇒ 字段取值只靠 "# 执行" 以 "# 执" 开头而碰巧命中，正文面又因开关为假未并入
    # ⇒ 结论面恒空 ⇒ 一切比对判「重复」。此类退化不会自己报错，只能靠形态断言兜住。
    check("A6 结论面常量形态：须为元组且每项是完整 CCG 字段名（防漏尾逗号退化成字符串）",
          isinstance(consistency.CONCLUSION_FIELDS, tuple)
          and len(consistency.CONCLUSION_FIELDS) >= 1
          and all(f in nodefile.CCG_MARKS for f in consistency.CONCLUSION_FIELDS),
          repr(consistency.CONCLUSION_FIELDS))

    v, d = _verdict(_six("端口是 5432") + _TAIL, _six("端口是 5432") + _TAIL)
    check("A3 结论面完全相同（真重复）⇒ ACCEPT（防放宽成一律报冲突）",
          v == "ACCEPT" and d == 0, "%s/%d" % (v, d))

    # 有条件声明、但既无「执行」行也无自由正文 ⇒ 结论面两边皆空。
    # （不能用「无条件声明的两条笔记」——那按四态路由本就是 BLINDSPOT，
    #   与结论面无关；首版即错在此，是把路由态当成了结论面态。）
    _noexec = ("# 功能名：数据库端口配置\n"
               "# 生效条件：部署到生产环境时\n"
               "# 子功能：端口取值\n"
               "# 不适用条件：本地开发环境\n")
    v, d = _verdict(_noexec, _noexec)
    check("A4 结论面两边皆空 ⇒ ACCEPT（无从分歧，不制造假冲突）",
          v == "ACCEPT" and d == 0, "%s/%d" % (v, d))


_GROUPS = {"A": group_a}


# ---------------- 定点变异（内存注入；apply() 返回 restore()） ----------------

def _mut_a1():
    """结论面退回 _body_text ⇒ 修复前行为（纯六要素正文为空、恒判重复）。"""
    orig = consistency._conclusion_text
    consistency._conclusion_text = consistency._body_text
    return lambda: setattr(consistency, "_conclusion_text", orig)


def _mut_a2():
    """结论面不并入自由正文 ⇒ 结论写在正文里的形态被吞（V3 实测 p11 43/2 的同源退化）。"""
    orig = consistency.CONCLUSION_INCLUDE_BODY
    consistency.CONCLUSION_INCLUDE_BODY = False
    return lambda: setattr(consistency, "CONCLUSION_INCLUDE_BODY", orig)


def _mut_a4():
    """常量退化成字符串（生成式漏尾逗号）——复现那次「结论面恒空」的退化。"""
    orig = consistency.CONCLUSION_FIELDS
    consistency.CONCLUSION_FIELDS = "执行"
    return lambda: setattr(consistency, "CONCLUSION_FIELDS", orig)


def _mut_a3():
    """结论面恒返回同一常量 ⇒ 任何比对都判「重复」（放宽成一律不报冲突）。"""
    orig = consistency._conclusion_text
    consistency._conclusion_text = lambda content: "SAME"
    return lambda: setattr(consistency, "_conclusion_text", orig)


#: 组 → [(变异名, 应用函数, 期望转红断言前缀集合)]
_MUTATIONS = {
    # 期望集合**按实测校正**（首版四处都猜错了，是变异自证把预期拉回事实的）：
    #   ①退回 _body_text 只打 A1 —— A2 形态下 _body_text 本就非空，正文照常可比
    #   ②不并入正文打 A2+A5 —— 这两条都靠正文承载结论
    #   ③恒同打 A1+A2+A5
    #   ④常量退化只打 A6 —— 正文面兜住了结论，A2 不红；这正是形态断言的用武之地
    "A": [("结论面退回 _body_text（复现 #88 失明）", _mut_a1, {"A1"}),
          ("结论面不并入自由正文", _mut_a2, {"A2", "A5"}),
          ("结论面恒同（放宽成一律判重复）", _mut_a3, {"A1", "A2", "A5"}),
          ("常量漏尾逗号退化成字符串（执/行 两字段）", _mut_a4, {"A6"})],
}

#: 源码锚点自检（命中次数必须恰为 1，否则实现已漂移、变异表失效）。
#: 每条锚点**必须带上它所在的函数名**——首版漏了这层，拿 _conclusion_text 的源码
#: 去数 check 里的锚点，命中 0 次 ⇒ 自检误报 ANCHOR-MISS（fail-closed 本身是对的，
#: 错的是锚点与来源函数没配对）。
_ANCHORS = [
    ("_conclusion_text 含字段取值", "nodefile.ccg_field_value(content, f)", "_conclusion_text"),
    ("_conclusion_text 含正文并入开关", "if CONCLUSION_INCLUDE_BODY:", "_conclusion_text"),
    ("check 内结论比对改看结论面", "e_body = _conclusion_text(body)", "check"),
]


def _anchor_preflight():
    srcs = {"_conclusion_text": inspect.getsource(consistency._conclusion_text),
            "check": inspect.getsource(consistency.check)}
    bad = []
    for label, anchor, fn in _ANCHORS:
        n = srcs[fn].count(anchor)
        if n != 1:
            bad.append((label, anchor, n))
    if not bad:
        return 0
    for label, anchor, n in bad:
        print("  ANCHOR-MISS %s：命中 %d 次（期望 1）%r" % (label, n, anchor))
    print("  => 实现已漂移，变异表失效：退出码 2（fail-closed）")
    return 2


def _run_group(name, root):
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
    print("!! #88 定点变异自证 · 组 %s：内存注入退化，逐条要求**恰好**命中期望红项\n" % name)
    root = tempfile.mkdtemp(prefix="p88m_")
    try:
        with contextlib.redirect_stdout(io.StringIO()):
            base_red, _, _ = _run_group(name, root)
        print("  未变异基线：红项 %d %s" % (len(base_red), "（应为 0）" if not base_red else sorted(base_red)))
        bad = []
        if base_red:
            bad.append("基线即转红：%s" % sorted(base_red))
        for mname, apply, expect in _MUTATIONS[name]:
            restore = apply()
            try:
                with contextlib.redirect_stdout(io.StringIO()):
                    red, _, _ = _run_group(name, root)
            except Exception as exc:                      # noqa: BLE001
                red = {"<变异体异常:%s>" % type(exc).__name__}
            finally:
                restore()
            ok = (red == expect)
            print("  [%s] %s → 红项 %s（期望 %s）" % ("OK" if ok else "BAD", mname, sorted(red), sorted(expect)))
            if not ok:
                bad.append("%s：得 %s 期望 %s" % (mname, sorted(red), sorted(expect)))
    finally:
        pass
    if bad:
        print("\n变异自证失败：")
        for b in bad:
            print("  · " + b)
        return 1
    print("\n变异自证通过：%d 条退化各自**恰好**命中期望红项" % len(_MUTATIONS[name]))
    return 0


def main():
    print("[#88 结论面] 正断言组 A")
    _run_group("A", tempfile.mkdtemp(prefix="p88p_"))
    print("\n==== #88 结果：%d 通过 / %d 失败 ====" % (PASS, FAIL))
    if FAILS:
        print("失败项：" + "、".join(FAILS))
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    if "--mutate" in sys.argv:
        i = sys.argv.index("--mutate")
        sys.exit(_mutate(sys.argv[i + 1] if i + 1 < len(sys.argv) else ""))
    sys.exit(main())
