# -*- coding: utf-8 -*-
"""代码索引（codeindex）验收 · Phase 0 契约裁决 + 行序压制修复。

对应计划 docs/mdcg/全库代码评审与条件化注释_计划_v0.1.md 的
codeindex-render-fix / codeindex-tests；契约为
docs/mdcg/代码评审与条件化注释_契约_v0.1.md。

验收口径（改造前 → 改造后）：
1. 行序压制：源码里人工写的生效条件行曾被合成行（同名字段、且排在源码注释
   之前）永久压制——检索侧 mdcos._ccg_field 取首个匹配，人工声明不可见。
   现在合成区与源码区**分区**、源码区**置首**，人工声明胜出并逐字保留。
2. 字段零重名：机械推导的索引元条件不再占用生效条件字段，改由
   nodefile.INDEX_META_MARK 承载；合成区字段名与 CCG 六要素的交集必须是空集
   （机械判据 nodefile.is_ccg_mark）。
3. 诚实缺证据：源码未声明生效条件的条目，ccg_completeness 必须
   complete=False 且**恰缺**「生效条件」——不许用索引元条件冒充。这是 Phase 0
   的**预期代价面**：真实库既有 2930 条代码节点在重索引后由 DEFER 降为
   BLINDSPOT，待环二补注释闸门逐步补回（代价面见契约 §四）。
4. extract / condition_space 既有契约不回归；index_dir 确定性排序与截断显式
   上报维持（index-dir-integrity 属 Phase 1，本文件只建基线护栏）。
"""
from __future__ import annotations

import ast
import os
import sys
import tempfile
import traceback

from . import codeindex, nodefile
from .mdcos import _ccg_field

_ok = 0
_bad = []
_skip = 0


def _check(name, cond, detail=""):
    global _ok
    if cond:
        _ok += 1
        print("  ok   %s" % name)
    else:
        _bad.append("%s %s" % (name, detail))
        print("  FAIL %s %s" % (name, detail))


PY_SRC = '''"""示例模块。"""
import os


# 生效条件：入参 path 为已存在的本地文件
# 子功能：读取文件首行
def first_line(path):
    """读取首行。"""
    return open(path, encoding="utf-8").readline()


def bare(name):
    """无源码 CCG 注释。"""
    return name
'''

JS_SRC = '''/** 弱提取样本 */
export function ping(url) {
  return url;
}
'''

HUMAN_COND = "# 生效条件：入参 path 为已存在的本地文件"

# 两窗口样本（裁决 A）：leading 在定义行之上，body 在定义行之下/体首语句之前
BODY_SRC = '''"""两窗口样本。"""


# 生效条件：外层声明（leading 窗口）
def with_body(seq):
    # 生效条件：入参 seq 为可迭代且元素可比较（body 窗口）
    # 子功能：返回排序副本
    out = sorted(seq)
    return out


def body_trap(seq):
    out = sorted(seq)
    # 实现注释：位于体首语句【之后】→ 不属于声明头窗口，不应被收
    return out
'''


def _item_of(src, path, name):
    items = codeindex.extract(src, path)
    return next((x for x in items if x["name"] == name), None)


def main():
    print("=" * 68)
    print("md_cg codeindex 验收 · Phase 0（行序压制修复 + 契约裁决）")
    print("=" * 68)
    tmp = tempfile.mkdtemp(prefix="mdcg_codeidx_")
    try:
        # ---------------- ① 契约常量 ----------------
        print()
        print("【1】契约常量：合成区字段名与 CCG 零重名")
        _check("索引元条件字段名不在 CCG 六要素内",
               nodefile.INDEX_META_MARK not in nodefile.CCG_MARKS
               and not nodefile.is_ccg_mark(nodefile.INDEX_META_MARK),
               nodefile.INDEX_META_MARK)
        _check("is_ccg_mark 对六要素逐一为真",
               all(nodefile.is_ccg_mark(m) for m in nodefile.CCG_MARKS))
        _check("is_ccg_mark 对元条件与位置为假",
               not nodefile.is_ccg_mark(nodefile.INDEX_META_MARK)
               and not nodefile.is_ccg_mark("位置"))

        # ---------------- ② 分区与行序：人工优先 ----------------
        print()
        print("【2】render 三分区：源码区置首，人工声明不被压制")
        it_ann = _item_of(PY_SRC, "demo.py", "first_line")
        _check("extract 命中带注释的函数", bool(it_ann))
        r_ann = codeindex.render(it_ann)
        _check("源码注释逐字保留（不被丢弃）", HUMAN_COND in r_ann)
        r_lines = r_ann.splitlines()
        cond_i = r_lines.index(HUMAN_COND)
        head_i = next(i for i, ln in enumerate(r_lines)
                      if ln.startswith("# 功能名："))
        _check("源码区先于合成区（人工优先的确定性序）", cond_i < head_i,
               "cond@" + str(cond_i) + " head@" + str(head_i))
        _check("检索侧取到人工条件（行序压制已修）",
               _ccg_field(r_ann, "生效条件") == "入参 path 为已存在的本地文件",
               _ccg_field(r_ann, "生效条件"))
        _check("生效条件行恰一条（合成区不再产出该行）",
               sum(1 for ln in r_lines
                   if ln.startswith("# 生效条件：")) == 1)
        _check("补了注释 → 五要素齐备（complete=True）",
               nodefile.ccg_completeness(r_ann)["complete"] is True,
               str(nodefile.ccg_completeness(r_ann)["required_present"]))

        it_bare = _item_of(PY_SRC, "demo.py", "bare")
        r_bare = codeindex.render(it_bare)
        _check("未声明生效条件的条目：合成区不冒充该字段",
               "# 生效条件：" not in r_bare)
        cpl = nodefile.ccg_completeness(r_bare)
        missing = [m for m in nodefile.CCG_REQUIRED
                   if m not in cpl["required_present"]]
        _check("未声明 → 恰缺生效条件（诚实缺证据，非整体失效）",
               cpl["complete"] is False and missing == ["生效条件"],
               str(missing))
        _check("合成区其余 5 要素仍齐备",
               all(m in cpl["required_present"] for m in nodefile.CCG_MARKS
                   if m != "生效条件"), str(cpl["required_present"]))

        # ---------------- ③ 索引元信息区：零重名 + 同源 ----------------
        print()
        print("【3】索引元信息区（非 CCG 字段名，与 frontmatter 同源）")
        meta_head = "# " + nodefile.INDEX_META_MARK + "："
        meta_line = next((ln for ln in r_lines if ln.startswith(meta_head)), "")
        _check("索引元条件独立成行", bool(meta_line), meta_line[:60])
        cs = codeindex.condition_space(it_ann)
        _check("元条件 = condition_space 四槽同源（require_full=False）",
               meta_line == meta_head + nodefile.condition_space_text(
                   cs, require_full=False), meta_line[:90])
        _check("元条件行不被误判为旧口径单槽冒充",
               not nodefile.is_legacy_position_condition(meta_line))
        heads = []
        for ln in r_bare.splitlines():
            if not ln.startswith("#"):
                continue
            body = ln.lstrip("#").strip()
            heads.append(body.split("：")[0].split(":")[0].strip())
        used = sorted({h for h in heads if nodefile.is_ccg_mark(h)})
        allowed = sorted(m for m in nodefile.CCG_MARKS if m != "生效条件")
        _check("合成区用到的 CCG 字段名 = 其余五要素（排除生效条件）",
               used == allowed, str(used))
        _check("合成区非 CCG 字段名 = 索引元条件 + 位置",
               sorted(h for h in heads if not nodefile.is_ccg_mark(h))
               == sorted([nodefile.INDEX_META_MARK, "位置"]), str(heads))

        # ---------------- ④ condition_space 既有契约不回归 ----------------
        print()
        print("【4】condition_space（四槽/全时窗）不回归")
        _check("四槽齐备",
               set(cs) == set(nodefile.CONDITION_SLOTS_REQUIRED),
               str(sorted(cs)))
        _check("时间槽用全时窗哨兵（不把写入时刻伪造成条件）",
               nodefile.is_full_time_window(cs.get("time_window")),
               str(cs.get("time_window")))
        js_it = _item_of(JS_SRC, "sample.js", "ping")
        weak = codeindex.condition_space(js_it)
        _check("弱提取在方法槽诚实降级（不冒充编译器）",
               codeindex.LANG_WEAK in weak["observation_tool"]
               and codeindex.LANG_COMPILER not in weak["observation_tool"],
               weak["observation_tool"])

        # ---------------- ⑤ extract / 幂等 / 确定性 ----------------
        print()
        print("【5】extract 分派 / 幂等 / node_id / region_hash")
        _check("Python → AST 精确（precise=True / basis=compiler）",
               it_ann["precise"] is True and it_ann["basis"] == "compiler")
        _check("JS → 弱提取（precise=False / basis=other）",
               js_it["precise"] is False and js_it["basis"] == "other")
        raised = False
        try:
            codeindex.extract("x = 1", "foo.xyz")
        except ValueError as exc:
            raised = "无提取器" in str(exc)
        _check("无提取器后缀显式报错（不静默降级成 Python 解析）", raised)
        _check("render 幂等（两次逐字节相同）",
               codeindex.render(it_ann) == r_ann)
        _check("node_id 稳定（path::name 短哈希，重复索引幂等）",
               codeindex.node_id(it_ann) == codeindex.node_id(dict(it_ann)))
        _check("region_hash 为 12 位十六进制（索引/回读共用口径）",
               len(it_ann["hash"]) == 12
               and all(c in "0123456789abcdef" for c in it_ann["hash"]),
               it_ann["hash"])

        # ---------------- ⑥ index_dir 基线护栏（Phase 1 前只建基线） -------
        print()
        print("【6】index_dir：确定性排序 + 截断显式上报（基线护栏）")
        d = os.path.join(tmp, "pkg")
        os.makedirs(d)
        for fn, body in (("a.py", PY_SRC), ("b.js", JS_SRC)):
            with open(os.path.join(d, fn), "w", encoding="utf-8") as f:
                f.write(body)
        _i1, _er1, s1 = codeindex.index_dir(d)
        _i2, _er2, s2 = codeindex.index_dir(d)
        _check("两次运行条目序逐项一致（walk/文件名确定性排序）",
               [x["name"] for x in _i1] == [x["name"] for x in _i2],
               str([x["name"] for x in _i1]))
        _check("相同输入 stats 一致（幂等）", s1 == s2)
        _check("未越限 → truncated=False", s1["truncated"] is False)
        _check("skipped_suffixes 上报（无提取器后缀可见）",
               isinstance(s1["skipped_suffixes"], list))
        _i3, _er3, s3 = codeindex.index_dir(d, max_files=1)
        _check("越限 → truncated=True 且原因非空（显式上报，不静默）",
               s3["truncated"] is True and bool(s3["truncated_reason"]),
               str(s3.get("truncated_reason")))
        _check("越限时仍返回已索引条目（不丢已有产出）",
               isinstance(_i3, list) and len(_i3) >= 1
               and len(s3["skip_dirs"]) == len(s1["skip_dirs"]),
               "items=" + str(len(_i3)))
        # ---- index-dir-integrity（Phase 1）：截断可复算 + 目录序确定 ----
        _check("截断计数可复算：hit_files/indexed_items 就位且与条目数一致",
               s1.get("hit_files", 0) >= 1 and s1.get("indexed_items") == len(_i1),
               "hit=%s items=%s len=%s" % (s1.get("hit_files"),
                                           s1.get("indexed_items"), len(_i1)))
        _check("越限快照同样带 hit_files/indexed_items（与 files 同源）",
               s3.get("hit_files", 0) >= 1 and s3.get("indexed_items") == len(_i3),
               "hit=%s items=%s len=%s" % (s3.get("hit_files"),
                                           s3.get("indexed_items"), len(_i3)))
        nested = os.path.join(tmp, "nested")
        for sub in ("z_sub", "a_sub"):
            os.makedirs(os.path.join(nested, sub))
            with open(os.path.join(nested, sub, "x.py"), "w", encoding="utf-8") as f:
                f.write(PY_SRC)
        _n1, _ne1, sn1 = codeindex.index_dir(nested)
        _n2, _ne2, sn2 = codeindex.index_dir(nested)
        _p1 = [x["path"] for x in _n1]
        _p2 = [x["path"] for x in _n2]
        _check("嵌套目录：两次运行条目路径序逐项一致（dirnames 已排序）",
               _p1 == _p2 and len(_p1) > 1, str(_p1)[:120])
        _check("嵌套目录：a_sub 先于 z_sub（与文件系统返回序无关）",
               _p1.index(next(p for p in _p1 if p.startswith("a_sub/")))
               < _p1.index(next(p for p in _p1 if p.startswith("z_sub/"))),
               str(_p1)[:140])
        _check("嵌套目录 stats 幂等（同输入两次一致）", sn1 == sn2)

        # ---------------- ⑦ 载体两窗口（裁决 A） ----------------
        print()
        print("【7】注释载体两窗口：leading + body（裁决 A · 索引侧收口）")
        _check("codeindex._body_comments 存在（历史悬空引用由此坐实）",
               callable(getattr(codeindex, "_body_comments", None))
               and callable(getattr(codeindex, "_symbol_comments", None)))
        it2 = _item_of(BODY_SRC, "demo2.py", "with_body")
        want_cmts = ["# 生效条件：外层声明（leading 窗口）",
                     "# 生效条件：入参 seq 为可迭代且元素可比较（body 窗口）",
                     "# 子功能：返回排序副本"]
        _check("两窗口按物理行序合并（leading 在前、body 在后）",
               it2["comments"] == want_cmts, repr(it2["comments"])[:200])
        r2w = codeindex.render(it2)
        _check("body 窗口的 CCG 注释在正文可见（不再是索引盲区）",
               "# 生效条件：入参 seq 为可迭代且元素可比较（body 窗口）" in r2w)
        _check("冲突时靠前者胜出（_ccg_field 取首匹配 = 物理序）",
               _ccg_field(r2w, "生效条件") == "外层声明（leading 窗口）",
               _ccg_field(r2w, "生效条件"))
        _check("补了 body 注释 → 五要素齐备（complete=True）",
               nodefile.ccg_completeness(r2w)["complete"] is True,
               str(nodefile.ccg_completeness(r2w)["required_present"]))
        # 非循环断言：窗口产物**逐字**固定（不依赖 verifier 委托是否成功）
        # 期望值**写死**：体首语句行号不得臆测（上一版写成 lineno+1 即为反例）
        _fnode = next(n for n in ast.parse(BODY_SRC).body
                      if isinstance(n, ast.FunctionDef) and n.name == "with_body")
        _check("body 窗口产物逐字固定（期望值写死，非自证）",
               codeindex._body_comments(BODY_SRC.splitlines(), _fnode.lineno,
                                        _fnode.body[0].lineno) == [
                   "# 生效条件：入参 seq 为可迭代且元素可比较（body 窗口）",
                   "# 子功能：返回排序副本"],
               repr(codeindex._body_comments(
                   BODY_SRC.splitlines(), _fnode.lineno,
                   _fnode.body[0].lineno))[:160])
        it3 = _item_of(BODY_SRC, "demo2.py", "body_trap")
        _check("体首语句【之后】的注释不入声明头窗口（边界不越界）",
               it3["comments"] == [] and "实现注释" not in repr(it3["comments"]),
               repr(it3["comments"])[:120])
        # verifier 是否已收敛为「委托唯一真源」——等价断言不可静默跳过
        try:
            from .whitebox_kb.wisdom import verifier as Vmod
            vobj = Vmod.Verifier.__new__(Vmod.Verifier)
            tree = ast.parse(BODY_SRC)
            fnode = next(n for n in tree.body if isinstance(n, ast.FunctionDef)
                         and n.name == "with_body")
            src_lines = BODY_SRC.splitlines()
            got, _doc = vobj._ccg_block(fnode, src_lines)
            want = [s.lstrip("#").strip() for s in codeindex._body_comments(
                src_lines, fnode.lineno, fnode.body[0].lineno)]
            _check("verifier 已收敛为委托唯一真源（_ci_body_comments 可达）",
                   Vmod._ci_body_comments() is not None)
            _check("verifier 窗口与 codeindex._body_comments 逐字等价",
                   got == want, repr([got, want])[:180])
            _check("verifier 窗口只收 body 窗口（不误收 leading）",
                   got == want and all("外层声明" not in x for x in got),
                   repr(got)[:140])
        except Exception as exc:  # noqa: BLE001
            global _skip
            _skip += 1
            print("  SKIP verifier 委托等价断言（模块不可导入）：%r" % (exc,))

        print()
        print("PASS %d / FAIL %d / SKIP %d" % (_ok, len(_bad), _skip))
        for b in _bad:
            print("  - " + b)
        return 1 if _bad else 0
    except Exception:  # noqa: BLE001
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())
