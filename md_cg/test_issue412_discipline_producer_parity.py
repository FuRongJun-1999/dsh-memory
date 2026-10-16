# -*- coding: utf-8 -*-
# 功能名：纪律节点识别的**生产者—判据词形一致性**（issue #412）
# 生效条件：python -X utf8 -m md_cg.test_issue412_discipline_producer_parity [--mutate]；被测面＝md_cg/consistency.py 的判据单点（谓词 + 词形归一）、scripts/discipline_nodes.py 的**真实**投影生产者、md_cg/whitebox_kb/wisdom/migrate_wisdom.py 的元学科卡生产者
# 子功能：A 组＝正向对齐（**三处不匹配各自单列** + 跑生产者真产出 + 端到端硬冲突）；K 组＝反例与过度收紧（学科/元学科/无关 tag、坏入参不抛）；E 组＝单点面（别名、词形归一唯一、两个生产者同用）；骨架①枚举完备性 + 骨架②回退实跑 + 双向变异
# 执行：--mutate 时在镜像树里回缺陷（去归一化）/ 过度收紧（前缀放宽）/ 只加壳不接线（别名不走单点），守卫必须按指定项转红
# 验证方式：全部 PASS 即通过（退出码 0）；变异与骨架红项集合须与预期逐项相符
# 不适用条件：不判 `discipline` 的**第三种**语义（学科/学科分类之外的用法，如池化/信任表里的类别名——那些不是节点识别面）；不判纪律节点的**内容合法性**（只判识别）；不判投影节点的落点与生成件新鲜度（另有守卫）；不判 SQLite 侧元学科卡的存储语义（本件只钉「学科 ≠ 纪律」的识别边界）
"""issue #412 守卫：闸门对**真实生产者**恒不命中。

病象（修前）：判据只做「tags 小写后与 DISCIPLINE_TAGS **精确求交**」或「id 以 discipline_/
work_discipline 起」，而真实生产者 scripts/discipline_nodes.py 写的是
tags=["work-discipline", "discipline:N", "harness:all", "v1.1"] 且 id="mem_*"：
  · 连字符 work-discipline ≠ 集合里的下划线 work_discipline；
  · "discipline:N" 是**命名空间**形态，精确相等同样不命中；
  · id 前缀是 mem_，id 腿也不适用。
⇒ 纪律闸对真实生产者**恒不命中**（完全空转）。

**为什么既有守卫一直绿**（本件最值钱的一条）：判据的测试用**自造 id**
（cg.add("discipline_prod", ...)）恰好命中 id 前缀腿 —— 判据只对「测试自己造出来的形态」
命中，对真实生产者不可见。故本守卫的 A 组**必须**跑生产者的真产出、且**三处不匹配各自单列**。

修法：判据收成**单点** —— 词形归一（小写 + 连字符/空格折下划线）落在 `_norm_discipline_token`，
识别落在 `is_discipline_node`；`_is_discipline` 降为**薄别名**（4 个调用点与公开面不动）。
两个生产者与判据**同用**该谓词：投影生产者做**正向** fail-closed 自证（词形再漂移当场炸），
元学科卡生产者做**负向**自证（学科 ≠ 纪律：卡被当纪律会让「学科卡被引用」走硬冲突 REJECT）。
"""
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO not in sys.path:
    sys.path.insert(0, _REPO)
_SCRIPTS = os.path.join(_REPO, "scripts")
if _SCRIPTS not in sys.path:
    sys.path.insert(0, _SCRIPTS)

from md_cg import _guard_kit as GK            # noqa: E402
from md_cg import consistency                 # noqa: E402
from md_cg.mdcos import MdCGOS                # noqa: E402
import discipline_nodes as PD                 # noqa: E402  （真实投影生产者）

FAILS = []
_TMP = tempfile.mkdtemp(prefix="iss412_")
_Q = chr(34)
_PROD_TAGS = ["work-discipline", "discipline:9", "harness:all", "v1.1"]   # 生产者的真实形态


def _check(name, cond, detail=""):
    if cond:
        print("  PASS " + name)
    else:
        print("  FAIL " + name + "  " + str(detail)[:220])
        FAILS.append(name)


def _lib(tag):
    d = os.path.join(_TMP, tag)
    os.makedirs(d, exist_ok=True)
    return d


print("== A 组：正向对齐（三处不匹配各自单列） ==")
_f = consistency.is_discipline_node
_check("A01 连字符形态单独命中：tags=[work-discipline]（修前：集合里只有下划线写法 ⇒ 不命中）",
       _f({"tags": ["work-discipline"]}) is True)
_check("A02 命名空间形态单独命中：tags=[discipline:9]（修前：精确相等 ⇒ 不命中）",
       _f({"tags": ["discipline:9"]}) is True)
_check("A03 id 前缀腿对真实生产者**不适用**（诚实断言）：tags 为空 + id=mem_* ⇒ False"
       "（正向命中只能靠 tags 腿——修前两腿皆空）",
       _f({"tags": []}, "mem_1700000000000009") is False)
_nid, _fm_lines = PD._new_node_fm({"no": 9, "nac": [], "trigger": "t", "sha": "s"},
                                 1700000000000.0)
_tags_line = [l for l in _fm_lines if l.startswith("tags:")][0]
_real_tags = json.loads(_tags_line.split("tags: ", 1)[1])
_check("A04 **跑生产者的真产出**：_new_node_fm 的 tags 行喂进谓词 ⇒ 命中"
       "（防「自造 id 假绿」——本腿即为此设）",
       _f({"tags": _real_tags}) is True and _nid.startswith("mem_"),
       (_nid, _real_tags))
_check("A04b 生产者自证在位：真产出 tags 与常量形态逐位一致（含 discipline:9）",
       _real_tags == _PROD_TAGS, _real_tags)
_root = _lib("e2e")
_cg = MdCGOS(_root)
# 纪律硬冲突路径在现行裁定下只对 **self 层**的纪律节点生效（仓库既有测试即此形态：
# cg.add("discipline_prod", ..., layer="self", tags=["discipline"])）。本腿把**真实生产者的
# 词形**放进该层 ⇒ 断言硬冲突真的发生（修前：词形不被认出 ⇒ 无 discipline 冲突）。
_cg.add("mem_proj_1", "# 功能：生产纪律" + chr(10) + "# 执行：禁止删除生产数据",
        layer="self", tags=list(_PROD_TAGS),
        non_applicable_conditions=["删除生产数据"], importance=0.85)
_cg.flush()
_r = _cg.check_consistency("删除生产数据", layer="self")
_check("A05 端到端：**真实生产者词形**的纪律节点触发 discipline 硬冲突 ⇒ REJECT"
       "（修前：词形不被认出 ⇒ 无 discipline 冲突）",
       _r.get("verdict") == "REJECT"
       and any(c.get("type") == "discipline" for c in (_r.get("conflicts") or [])),
       {k: _r.get(k) for k in ("verdict", "reason")})
_cg.close()
# A06（**独立第二原因**，如实登记，不属本件修复面）：真实生产者把投影节点写在 structural 层，
# 而纪律硬冲突路径在现行裁定下**不覆盖该层**（实测 ACCEPT）——即「词形面」修好后，端到端仍
# 有一条**层路由**的独立原因。本腿把它钉成可测事实，避免两件事被混为一谈。
_cg3 = MdCGOS(os.path.join(_TMP, "e2e_struct"))
_cg3.add("mem_proj_2", "# 功能：生产纪律" + chr(10) + "# 执行：禁止删除生产数据",
         layer="structural", tags=list(_PROD_TAGS),
         non_applicable_conditions=["删除生产数据"], importance=0.85)
_cg3.flush()
_r3 = _cg3.check_consistency("删除生产数据", layer="self")
_check("A06 独立第二原因（层路由，不在本件修复面）：投影节点在 **structural** 层时该冲突路径"
       "不覆盖 ⇒ 非 REJECT（如实登记，供另单处理）",
       _r3.get("verdict") != "REJECT",
       {k: _r3.get(k) for k in ("verdict", "reason")})
_cg3.close()

print("== K 组：反例与过度收紧方向 ==")
_check("K01 学科面 discipline_type 作为 tag **不得**命中（学科 ≠ 纪律）",
       _f({"tags": ["discipline_type"]}) is False)
_check("K02 元学科卡（meta_discipline + node_meta_* id）**不得**命中",
       _f({"tags": ["domain:计算机科学", "level:L4", "status:pending", "subject_card",
              "meta_discipline"]}, "node_meta_123_456") is False)
_check("K03 无关 tag 不得命中（含精确语义：rules/rule_of_thumb ≠ rule）",
       _f({"tags": ["harness:all", "v1.1"]}) is False
       and _f({"tags": ["rules"]}) is False
       and _f({"tags": ["rule_of_thumb"]}) is False)
_check("K04 既有裁定不动：自造 id discipline_prod 仍命中（行为不变；它正是假绿来源，"
       "真实面由 A04/A05 承担）",
       _f({"tags": []}, "discipline_prod") is True
       and _f({"tags": ["discipline"]}) is True
       and _f({"tags": ["纪律"]}) is True and _f({"tags": ["规则"]}) is True)
_check("K05 坏入参不抛：None / 非映射 / tags 含 None 与非字符串 ⇒ False",
       _f(None) is False and _f(object()) is False
       and _f({"tags": [None, 3, ""]}) is False)

print("== E 组：单点面 ==")
_CS = open(os.path.join(_REPO, "md_cg", "consistency.py"), encoding="utf-8").read()
_PD = open(os.path.join(_SCRIPTS, "discipline_nodes.py"), encoding="utf-8").read()
_MW = open(os.path.join(_REPO, "md_cg", "whitebox_kb", "wisdom", "migrate_wisdom.py"),
           encoding="utf-8").read()
_alias = _CS.split("def _is_discipline(fm, node_id):")[1].split(chr(10) + "def ")[0]
_check("E01 _is_discipline 是**薄别名**：其体内只调单点（不内联第二份判定）",
       _alias.count("is_discipline_node(fm, node_id)") == 1
       and "DISCIPLINE_TAGS" not in _alias, _alias.strip()[:120])
_check("E02 词形归一唯一：归一实现与谓词各恰一处定义",
       len(re.findall(r"def _norm_discipline_token", _CS)) == 1
       and len(re.findall(r"def is_discipline_node", _CS)) == 1)
_check("E03 投影生产者同用单点：含谓词引用 + fail-closed 自证，且 tags 字面量**逐位未变**",
       "is_discipline_node" in _PD and "RuntimeError" in _PD
       and _Q + "work-discipline" + _Q in _PD
       and "discipline:%d" in _PD)
_check("E04 元学科卡生产者同用单点做**负向**自证（学科 ≠ 纪律，fail-loud）",
       "_discipline_predicate()" in _MW and "由误判" not in _MW
       and "元学科卡被误判为纪律节点" in _MW)

print("== 骨架①：枚举完备性（纪律识别实现点） ==")


def _discover(texts):
    """守卫自己的枚举：命中「自己写一份纪律词形判定」的函数（未走单点）。"""
    import ast as _ast
    hits = []
    for rel, src in texts.items():
        try:
            tree = _ast.parse(src)
        except SyntaxError:
            continue
        for node in _ast.walk(tree):
            if not isinstance(node, _ast.FunctionDef):
                continue
            seg = _ast.get_source_segment(src, node) or ""
            if "DISCIPLINE_TAGS" not in seg and "纪律" not in seg:
                continue
            if "is_discipline_node" in seg or "_norm_discipline_token" in seg:
                continue
            hits.append((rel, node.lineno))
    return hits


_OLD_IMPL = ("def _is_discipline(fm, node_id):" + chr(10)
            + "    tags = {str(t).lower() for t in (fm.get(" + _Q + "tags" + _Q + ") or [])}" + chr(10)
            + "    if tags & set(DISCIPLINE_TAGS):" + chr(10)
            + "        return True" + chr(10)
            + "    return str(node_id).startswith((" + _Q + "discipline_" + _Q + ", " + _Q + "work_discipline" + _Q + "))")
_NEW_IMPL = ("def _is_discipline(fm, node_id):" + chr(10)
             + "    return is_discipline_node(fm, node_id)")
_ok_e, _det_e = GK.assert_enumeration_complete(
    _discover,
    [("应命中·旧形态（自写一份精确求交判定）", _OLD_IMPL, True, "consistency_old.py"),
     ("不应命中·新形态（薄别名走单点）", _NEW_IMPL, False, "consistency_new.py"),
     ("不应命中·无关函数", "def other():" + chr(10) + "    return 1", False, "x.py")])
_check("E05 骨架①枚举完备性（应命中/不应命中两侧）", _ok_e, _det_e)

print("== 骨架② / 变异 ==")
_NL = "\r\n" if b"\r\n" in open(os.path.join(_REPO, "md_cg", "consistency.py"),
                                   "rb").read()[:8192] else "\n"


def _j(*lines):
    return _NL.join(lines)


_NORM_LINE = "    return str(t or \"\").strip().lower().replace(\"-\", \"_\").replace(\" \", \"_\")"
_NORM_DEAD = "    return str(t or \"\").strip().lower()   # 变异：去归一化（回缺陷）"
_NS_LINE = "        if n in _DISCIPLINE_TAGS_NORM or n.startswith(DISCIPLINE_TAG_NS + \":\"):"
_NS_LOOSE = "        if n in _DISCIPLINE_TAGS_NORM or n.startswith(DISCIPLINE_TAG_NS):  # 变异：过度收紧"
_ALIAS_LINE = "    return is_discipline_node(fm, node_id)"
_ALIAS_OLD = _j("    tags = {str(t).lower() for t in (fm.get(\"tags\") or [])}",
               "    if tags & set(DISCIPLINE_TAGS):",
               "        return True",
               "    return str(node_id).startswith((\"discipline_\", \"work_discipline\"))")
_M1 = ("M1 回缺陷：词形去归一化（连字符不再折下划线）", "md_cg/consistency.py",
       # 实测：真实性还带「discipline:N」命名空间 tag ⇒ 去归一化后**真实生产者仍被认出**；
       # 故本变异只该打红「连字符单独成立」那条腿（A01）——这正是三处不匹配**各自单列**的用处。
       [(_NORM_LINE, _NORM_DEAD)], ("A01",))
_M2 = ("M2 过度收紧：命名空间判断放宽为任意以 discipline 起（学科面也会命中）",
       "md_cg/consistency.py", [(_NS_LINE, _NS_LOOSE)], ("K01",))
_M3 = ("M3 只加壳不接线：别名不走单点（改回自写判定）", "md_cg/consistency.py",
       # 实测：A05 也红 —— 端到端走的是**生产代码里的判据路径**（check_consistency 到 _is_discipline）
       # ⇒ 别名不走单点会真的让真实生产者再次不可见（本腿证明 A05 不是「只调我的谓词」）。
       [(_ALIAS_LINE, _ALIAS_OLD)], ("A05", "E01"))
_MUTATIONS = (_M1, _M2, _M3)


def _mirror_build():
    dst = tempfile.mkdtemp(prefix="iss412_mut_")
    for name in ("md_cg", "scripts", "data"):     # data/ ＝ 判据所需的非 .py 数据面
        src = os.path.join(_REPO, name)
        if os.path.isdir(src):
            shutil.copytree(src, os.path.join(dst, name),
                            ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    for name in sorted(os.listdir(_REPO)):
        p = os.path.join(_REPO, name)
        if os.path.isfile(p) and (name.endswith(".py")
                                  or name in ("README.md", "pyproject.toml")):
            shutil.copy2(p, os.path.join(dst, name))
    return dst


def _run_in(tree):
    env = dict(os.environ)
    env.update({"PYTHONPATH": tree, "PYTHONUTF8": "1",
                "PYTHONDONTWRITEBYTECODE": "1"})
    env.pop("MDCG_ROOT", None)
    pr = subprocess.run([sys.executable, "-X", "utf8", "-m",
                         "md_cg.test_issue412_discipline_producer_parity"],
                        cwd=tree, env=env, capture_output=True, text=True,
                        encoding="utf-8", errors="replace", timeout=1800)
    out = (pr.stdout or "") + (pr.stderr or "")
    reds = [ln.split("FAIL ", 1)[1].strip()
            for ln in out.splitlines() if ln.strip().startswith("FAIL ")]
    return pr.returncode, reds, out


def _mutate():
    tree = _mirror_build()
    bad = []
    try:
        rc, reds, out = _run_in(tree)
        print("  未变异镜像基线：rc=%d 红项=%d（必须 rc=0 且 0 红）" % (rc, len(reds)))
        if rc != 0 or reds:
            print(chr(10).join(out.splitlines()[-20:]))
        for desc, rel, pairs, exp in _MUTATIONS:
            p = os.path.join(tree, rel)
            t = open(p, encoding="utf-8", newline="").read()
            if any(t.count(o) != 1 for o, _n in pairs):
                bad.append("%s 锚点命中 %s" % (desc, [t.count(o) for o, _n in pairs]))
                print("  ANCHOR-MISS " + desc)
                continue
            bak = t
            for o, n in pairs:
                t = t.replace(o, n, 1)
            open(p, "w", encoding="utf-8", newline="").write(t)
            for r, dd, ff in os.walk(tree):
                if os.path.basename(r) == "__pycache__":
                    shutil.rmtree(r, ignore_errors=True)
            rc2, reds2, _o2 = _run_in(tree)
            open(p, "w", encoding="utf-8", newline="").write(bak)
            hit = sorted({r.split(" ")[0] for r in reds2})
            if rc2 != 0 and hit == sorted(exp):
                print("  OK   %s 红项=%d 指定命中=%d/%d" % (desc, len(reds2), len(hit), len(exp)))
            else:
                bad.append(desc)
                print("  MISMATCH %s 实际=%s 期望=%s rc=%d" % (desc, hit, sorted(exp), rc2))
                for r in reds2[:6]:
                    print("        FAIL " + r)
        ok_r, det_r = GK.assert_revert_reddens(
            _mirror_build, [("md_cg/consistency.py", _NORM_LINE, _NORM_DEAD)],
            _run_in, ("A01",), "md_cg/consistency.py")
        print("  骨架②回退即红：%s %s" % ("OK" if ok_r else "MISMATCH",
                                          json.dumps(det_r, ensure_ascii=False)[:200]))
        if not ok_r:
            bad.append("骨架②未按预期转红")
        print("定点变异自证：%s（%d 条不合格）" % ("PASS" if not bad else "FAIL", len(bad)))
        return len(bad)
    finally:
        shutil.rmtree(tree, ignore_errors=True)


shutil.rmtree(_TMP, ignore_errors=True)
print("")
print("issue #412 结果：%s" % ("全部通过" if not FAILS else "%d 失败" % len(FAILS)))


def main():
    _bad = _mutate() if "--mutate" in sys.argv else 0
    return 1 if (FAILS or _bad) else 0


if __name__ == "__main__":
    sys.exit(main())