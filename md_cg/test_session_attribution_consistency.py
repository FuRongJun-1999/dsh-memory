# -*- coding: utf-8 -*-
"""md_cg · 会话归因口径一致性守卫（三处缺口：②session_note 漏 sens / ③审计面未接三态 / ④review_cli 双副本）
⑤（同族补齐，2026-10-07）：`session_note` 漏转发**显式 session** 给 add——显式档下
返回体 / tag / 审计 = 该显式值，而 fm.session 落单点值（未声明档 'unattributed'、
声明档权威值）⇒ 同一写入四处分叉。守卫 A3/A4 两输入（共享 / 绑定）。
⑥（同族补齐，2026-10-07）：**op=add 审计行不读写入时显式传入的 `session` kw**
（`MdCGSecure._audit` 恒取三态单点）——`add(session='X')` 下 fm.session / 索引
落 'X' 而审计行落单点值（未声明档 'unattributed'／绑定档进程随机）⇒ 同一写入
两处分叉。覆盖面含 `session_note` / `session_compact` 的**内层 add 事件**（A5-A7）
与纯 `MdCGOS` 日期兜底档（D）。

契约（2026-10-07 设计者「会话身份三态」的收口不变量）
------------------------------------------------------
**同一写入在「审计记录 / 节点 fm.session / 节点 tag」三处口径必须一致**——
未声明档三处同为 `UNATTRIBUTED_SESSION='unattributed'`；授权绑定档（sens 达
private 含 secret）三处同为该进程的随机 session。解析单点 =
`MdCGSecure._attributed_session`（三态：env → 请求声明 → unattributed；绑定档
豁免保持进程随机，见 test_session_identity_tristate 的 D 组）。

覆盖
----
  A session_note 三处口径（缺口②）：返回体 / 节点 fm.session / 节点 session
    标签 / 审计记录 —— 未声明档同为 unattributed；绑定档同为进程随机；
    **显式 session 档（同族补齐）**：未声明档 + 显式 session='X'（共享 / 绑定
    两输入）时各处同为该显式值（`session_note` 经 add(session=session) 转发）；
    并钉**内层 add 事件**那一行（A5/A6：一次 session_note 留 op=session_note ＋
    op=add 两条审计行）与 **session_compact 路径**（A7：compact→note→add 落库）。
  B 写面审计同 sens（缺口③）：add / propose 的审计记录 session 与同次写入面
    （节点 fm.session / 入队 rec.session）同口径同值；**显式 session kw 维**
    （B5/B6，2026-10-07 输入空间补齐）：`add(session='X')`（共享／绑定两输入）
    的审计行 == fm.session == 索引条目 == 'X'（`docindex.ingest_transcript`
    的 `add(..., session=<派生 token>)` 即此形态）。
  C review_cli 双副本（缺口④）：`scripts/review_cli.py` 是**薄壳**——与
    `md_cg/review_cli.py` 共用同一 `main`（运行时同一对象、无自带实现）、
    `autoflush=1` 生效、`--session` 帮助文本为三态口径、端到端可跑。
  D 纯 `MdCGOS`（无 `self.session`、无三态钩子）日期兜底路径（D1：各处同为
    `YYYYMMDD` 那个日期串）＋显式 session（D2）＋皆无（D3：各处同为空值）。

运行：python -m md_cg.test_session_attribution_consistency
      python -m md_cg.test_session_attribution_consistency --self-proof
退出码：0 全绿 ｜ 1 断言失败 ｜ 2 ANCHOR-MISS（锚点漂移，fail-closed）

变异自证的基线 = **运行中的实现源码**（`inspect.getsource` 就地变异、就地复原），
不读 git；④ 的 scripts 源文本走内存 override 变异（绝不写盘）。
"""
from __future__ import annotations

import argparse
import ast
import contextlib
import importlib.util
import inspect
import io
import os
import shutil
import sys
import tempfile
import textwrap

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from md_cg import nodefile
from md_cg import review_cli as _rv_pkg
from md_cg.mdcos import MdCGOS, MdCGSecure, UNATTRIBUTED_SESSION
from md_cg.security import Principal

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPTS_CLI = os.path.join(REPO, "scripts", "review_cli.py")

PASS = FAIL = 0
FAILS = []


def check(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  [PASS] {name}" + (f"  · {detail}" if detail else ""))
    else:
        FAIL += 1
        FAILS.append(name)
        print(f"  [FAIL] {name}  · {str(detail)[:240]}")


def _setenv(**kw):
    old = {k: os.environ.get(k) for k in kw}
    for k, v in kw.items():
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v
    return old


def _restore(old):
    for k, v in old.items():
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v


def _cg_no_decl(root):
    """未声明进程形态：自动随机会话的 principal（session=None）。"""
    return MdCGSecure(root, principal=Principal(
        actor="attrcons", clearance="secret", can_write=True, can_admin=True,
        role="designer"), autoflush=1)


def _fm_disk(cg, nid):
    """直读节点文件 frontmatter（不经读闸——守卫只看归因字段）。"""
    e = (cg.index.get("nodes") or {}).get(nid)
    if not e:
        return None
    with open(os.path.join(cg.root, e["path"]), encoding="utf-8") as f:
        fm, _c = nodefile.loads(f.read())
    return fm


def _audit_of(cg, op, nid):
    recs = [r for r in cg.audit_records()
            if r.get("op") == op and r.get("id") == nid]
    return recs[-1] if recs else None


def _inbox_last(root):
    path = os.path.join(root, "hippocampus", "inbox.jsonl")
    last = {}
    if os.path.exists(path):
        with open(path, encoding="utf-8") as fh:
            for line in fh:
                if line.strip():
                    last = __import__("json").loads(line)
    return last


# ----------------------------------------------------------------------
# 组
# ----------------------------------------------------------------------

def _group_a():
    print("\n[A] session_note 三处口径（返回体 / fm.session / tag / 审计）——缺口②")
    root = tempfile.mkdtemp(prefix="attrcons_a_")
    cg = _cg_no_decl(root)
    try:
        # A1 未声明档（默认 internal）→ 返回/fm.session/tag/审计 同为 unattributed
        n1 = cg.session_note("A1 未声明档会话要点")
        fm1 = _fm_disk(cg, n1["id"]) or {}
        tags1 = fm1.get("tags") or []
        au1 = _audit_of(cg, "session_note", n1["id"])
        check("A1 未声明档：返回 == fm.session == tag == 审计 == unattributed",
              n1.get("session") == fm1.get("session") == UNATTRIBUTED_SESSION
              and f"session:{UNATTRIBUTED_SESSION}" in tags1
              and bool(au1) and au1.get("session") == UNATTRIBUTED_SESSION,
              f"ret={n1.get('session')!r} fm={fm1.get('session')!r} "
              f"tags={tags1} audit={(au1 or {}).get('session')!r}")

        # A2 绑定档（sensitivity=private）→ 四处同为进程随机（== principal.session）
        exp2 = cg.principal.session
        n2 = cg.session_note("A2 绑定档会话要点", sensitivity="private")
        fm2 = _fm_disk(cg, n2["id"]) or {}
        tags2 = fm2.get("tags") or []
        au2 = _audit_of(cg, "session_note", n2["id"])
        check("A2 绑定档 private：返回 == fm.session == tag == 审计 == 进程随机",
              str(exp2).startswith("sess_")
              and n2.get("session") == fm2.get("session") == exp2
              and f"session:{exp2}" in tags2
              and bool(au2) and au2.get("session") == exp2,
              f"ret={n2.get('session')!r} fm={fm2.get('session')!r} "
              f"tags={tags2} audit={(au2 or {}).get('session')!r} 期望={exp2!r}")

        # A3 显式 session 档（同族补齐）：未声明进程 + 显式 'X'（共享档）→ 四处同 'X'
        #   修前 = 返回体 / tag / 审计 均为 'X' 而 fm.session 落单点值 'unattributed'
        #   （`session_note` 从不把显式 session 转发给 add）——同一写入四处分叉。
        n3 = cg.session_note("A3 显式会话档（共享）", session="X")
        fm3 = _fm_disk(cg, n3["id"]) or {}
        tags3 = fm3.get("tags") or []
        au3 = _audit_of(cg, "session_note", n3["id"])
        check("A3 显式 session='X'（共享档）：返回 == fm.session == tag == 审计 == 'X'",
              n3.get("session") == fm3.get("session") == "X"
              and "session:X" in tags3
              and bool(au3) and au3.get("session") == "X",
              f"ret={n3.get('session')!r} fm={fm3.get('session')!r} "
              f"tags={tags3} audit={(au3 or {}).get('session')!r}")

        # A4 显式 session 档 × 绑定档：未声明进程 + private + 显式 'X' → 四处同 'X'
        #   （显式声明优先于绑定档豁免——与 D 组「私档 + 显式 session → 原值」同口径；
        #    修前 fm.session 落进程随机、与其余三处 'X' 分叉。）
        n4 = cg.session_note("A4 显式会话档（绑定）", session="X",
                             sensitivity="private")
        fm4 = _fm_disk(cg, n4["id"]) or {}
        tags4 = fm4.get("tags") or []
        au4 = _audit_of(cg, "session_note", n4["id"])
        check("A4 显式 session='X' + private：返回 == fm.session == tag == 审计 == 'X'",
              n4.get("session") == fm4.get("session") == "X"
              and "session:X" in tags4
              and bool(au4) and au4.get("session") == "X",
              f"ret={n4.get('session')!r} fm={fm4.get('session')!r} "
              f"tags={tags4} audit={(au4 or {}).get('session')!r}")

        # A5/A6 显式 session 档 × **内层 add 事件**（同族补齐，2026-10-07）：一次
        #   session_note 写入留**两条审计行**（op=session_note ＋ 内层 op=add），
        #   两行都必须为该显式值。修前 A3/A4 只钉了 op=session_note 行——内层
        #   op=add 行仍取三态单点（未声明档 'unattributed'／绑定档进程随机），与
        #   同一节点的 fm.session（'X'）字面分叉：审计面的另一半在守卫之外。
        au3b = _audit_of(cg, "add", n3["id"])
        check("A5 显式 session='X'（共享档）：内层 add 审计行 == fm.session == 'X'",
              n3.get("session") == fm3.get("session") == "X"
              and bool(au3b) and au3b.get("session") == "X",
              f"ret={n3.get('session')!r} fm={fm3.get('session')!r} "
              f"add_audit={(au3b or {}).get('session')!r}")
        au4b = _audit_of(cg, "add", n4["id"])
        check("A6 显式 session='X' + private：内层 add 审计行 == fm.session == 'X'",
              n4.get("session") == fm4.get("session") == "X"
              and bool(au4b) and au4b.get("session") == "X",
              f"ret={n4.get('session')!r} fm={fm4.get('session')!r} "
              f"add_audit={(au4b or {}).get('session')!r}")

        # A7 session_compact 路径（第三处消费 session_note 的入口，同受该审计）：
        #   显式 session 经 session_compact → session_note → add 落库，落库节点的
        #   fm / tag / 两条审计行必须同值。
        cg.remember_event("user", "A7 会话事件一（用于压缩输入）", window=200)
        cg.remember_event("user", "A7 会话事件二（用于压缩输入）", window=200)
        rc7 = cg.session_compact(session="X", note=True)
        wid7 = rc7.get("written_id")
        fm7 = _fm_disk(cg, wid7) or {}
        tags7 = fm7.get("tags") or []
        au7a = _audit_of(cg, "add", wid7)
        au7b = _audit_of(cg, "session_note", wid7)
        check("A7 session_compact(显式 session) 落库节点：fm == tag == 两条审计行 == 'X'",
              bool(wid7) and fm7.get("session") == "X"
              and "session:X" in tags7
              and bool(au7a) and au7a.get("session") == "X"
              and bool(au7b) and au7b.get("session") == "X",
              f"wid={wid7!r} fm={fm7.get('session')!r} tags={tags7} "
              f"add_audit={(au7a or {}).get('session')!r} "
              f"note_audit={(au7b or {}).get('session')!r}")
    finally:
        cg.close()
        shutil.rmtree(root, ignore_errors=True)


def _group_b():
    print("\n[B] 写面审计同 sens（add / propose 审计 == 同次写入面）——缺口③")
    root = tempfile.mkdtemp(prefix="attrcons_b_")
    cg = _cg_no_decl(root)
    try:
        # B1 未声明档 add（默认 internal）→ 审计 == fm.session == unattributed
        cg.add("b_int", "B1", layer="contextual")
        fm1 = _fm_disk(cg, "b_int") or {}
        au1 = _audit_of(cg, "add", "b_int")
        check("B1 未声明档 add：审计 == fm.session == unattributed",
              fm1.get("session") == UNATTRIBUTED_SESSION
              and bool(au1) and au1.get("session") == UNATTRIBUTED_SESSION,
              f"fm={fm1.get('session')!r} audit={(au1 or {}).get('session')!r}")

        # B2 绑定档 add（private）→ 审计 == fm.session == 进程随机
        exp2 = cg.principal.session
        cg.add("b_priv", "B2", layer="contextual", sensitivity="private")
        fm2 = _fm_disk(cg, "b_priv") or {}
        au2 = _audit_of(cg, "add", "b_priv")
        check("B2 绑定档 add(private)：审计 == fm.session == 进程随机",
              fm2.get("session") == exp2
              and bool(au2) and au2.get("session") == exp2,
              f"fm={fm2.get('session')!r} audit={(au2 or {}).get('session')!r} "
              f"期望={exp2!r}")

        # B3 未声明档 propose（internal）→ 审计 == 入队 rec.session == unattributed
        cg.propose("b_prop", "B3", sensitivity="internal")
        rec3 = _inbox_last(root)
        au3 = _audit_of(cg, "propose", "b_prop")
        check("B3 未声明档 propose：审计 == 入队 rec.session == unattributed",
              rec3.get("session") == UNATTRIBUTED_SESSION
              and bool(au3) and au3.get("session") == UNATTRIBUTED_SESSION,
              f"rec={rec3.get('session')!r} audit={(au3 or {}).get('session')!r}")

        # B4 已声明档（env/显式构造）→ 审计与 fm.session 同为该声明值（三态不误伤声明）
        root4 = tempfile.mkdtemp(prefix="attrcons_b4_")
        cg4 = MdCGSecure(root4, principal=Principal(
            actor="attrcons", clearance="secret", can_write=True,
            can_admin=True, role="designer", session="sess_decl_b4"),
            autoflush=1)
        try:
            cg4.add("b_decl", "B4", layer="contextual")
            fm4 = _fm_disk(cg4, "b_decl") or {}
            au4 = _audit_of(cg4, "add", "b_decl")
            check("B4 声明档（env/显式）：审计 == fm.session == 声明值",
                  fm4.get("session") == "sess_decl_b4"
                  and bool(au4) and au4.get("session") == "sess_decl_b4",
                  f"fm={fm4.get('session')!r} audit={(au4 or {}).get('session')!r}")
        finally:
            cg4.close()
            shutil.rmtree(root4, ignore_errors=True)

        # B5/B6 **显式 session kw 维**（输入空间补齐，2026-10-07）：`add(session='X')`
        #   直接传参（不经 session_note；如 `docindex.ingest_transcript` 的
        #   `add(..., session=<派生 token>)`）——写面 fm.session/索引条目落 'X'
        #   （`_attribution` 的 setdefault 不覆盖显式值），审计行必须同取该值。
        #   修前审计行仍取三态单点：未声明档 'unattributed'（共享）/ 进程随机
        #   （绑定档 private 豁免）⇒ 同一写入两处字面分叉。
        cg.add("b_expl", "B5 显式会话（共享档）", layer="contextual",
               session="X")
        fm5 = _fm_disk(cg, "b_expl") or {}
        e5 = (cg.index.get("nodes") or {}).get("b_expl") or {}
        au5 = _audit_of(cg, "add", "b_expl")
        check("B5 add(session='X')（未声明进程）：审计 == fm.session == 索引 == 'X'",
              fm5.get("session") == "X" and e5.get("session") == "X"
              and bool(au5) and au5.get("session") == "X",
              f"fm={fm5.get('session')!r} index={e5.get('session')!r} "
              f"audit={(au5 or {}).get('session')!r}")

        cg.add("b_expl_priv", "B6 显式会话（绑定档）", layer="contextual",
               session="X", sensitivity="private")
        fm6 = _fm_disk(cg, "b_expl_priv") or {}
        au6 = _audit_of(cg, "add", "b_expl_priv")
        check("B6 add(session='X', sensitivity='private')：审计 == fm.session == 'X'",
              fm6.get("session") == "X"
              and bool(au6) and au6.get("session") == "X",
              f"fm={fm6.get('session')!r} audit={(au6 or {}).get('session')!r}")
    finally:
        cg.close()
        shutil.rmtree(root, ignore_errors=True)


# ---- C：review_cli 双副本（缺口④） ----

#: scripts 源文本的内存 override（只供 --self-proof 的文本变异用，绝不写盘）
_SCRIPTS_SRC_OVERRIDE = None


def _scripts_src():
    if _SCRIPTS_SRC_OVERRIDE is not None:
        return _SCRIPTS_SRC_OVERRIDE
    with open(SCRIPTS_CLI, encoding="utf-8") as f:
        return f.read()


def _scripts_is_thin(src):
    """薄壳判据（AST）：模块级 `from md_cg.review_cli import main` 且**无**自带
    模块级 `def main`。只看语义节点，docstring 里的字样不算。"""
    tree = ast.parse(src)
    imports_shared = any(
        isinstance(n, ast.ImportFrom) and n.module == "md_cg.review_cli"
        and any(a.name == "main" for a in n.names) for n in tree.body)
    own_main = any(isinstance(n, ast.FunctionDef) and n.name == "main"
                   for n in tree.body)
    return imports_shared and not own_main


def _load_scripts_module():
    """载入 scripts/review_cli.py 为模块；若有内存源 override（变异用）
    则 exec 该源文本——使 C2/C5 与 C1 同受变异影响，与磁盘级变异行为一致。"""
    if _SCRIPTS_SRC_OVERRIDE is not None:
        import types as _t
        ns = {"__name__": "_attrcons_review_cli", "__file__": SCRIPTS_CLI}
        exec(compile(_SCRIPTS_SRC_OVERRIDE, SCRIPTS_CLI, "exec"), ns)
        return _t.SimpleNamespace(**ns)
    spec = importlib.util.spec_from_file_location("_attrcons_review_cli",
                                                  SCRIPTS_CLI)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _group_c():
    print("\n[C] review_cli 双副本：共用同一 main + autoflush 生效 ——缺口④")
    # C1 源码级：scripts 版是薄壳（AST）
    src = _scripts_src()
    check("C1 scripts/review_cli.py 为薄壳（AST：导入共用 main 且无自带 def main）",
          _scripts_is_thin(src), "src[:120]=%r" % src[:120])

    # C2 运行时同一对象：scripts.main is md_cg.review_cli.main
    try:
        smod = _load_scripts_module()
        same = smod.main is _rv_pkg.main
    except Exception as exc:                              # noqa: BLE001
        same = False
        print("    （载入 scripts 模块异常：%s）" % exc)
    check("C2 scripts.main 与 md_cg.review_cli.main 是同一对象", same)

    # C3 autoflush 生效：共用 main 的构造路径 _cg → autoflush == 1
    root = tempfile.mkdtemp(prefix="attrcons_c_")
    cg = None
    try:
        cg = _rv_pkg._cg(argparse.Namespace(root=root))
        check("C3 共用 main 的 _cg 构造 autoflush == 1（scripts 版由此获得）",
              cg.autoflush == 1, str(cg.autoflush))
    finally:
        if cg is not None:
            cg.close()
        shutil.rmtree(root, ignore_errors=True)

    # C4 帮助文本为三态口径（不再有陈旧的「随机会话」措辞）
    msrc = inspect.getsource(_rv_pkg.main)
    check("C4 --session 帮助为三态口径（含 'unattributed'、无 '随机会话'）",
          "仍无则落 'unattributed'" in msrc and "随机会话" not in msrc)

    # C5 端到端：scripts 薄壳的 main 可跑（list → rc 0）
    root2 = tempfile.mkdtemp(prefix="attrcons_c5_")
    try:
        smod = _load_scripts_module()
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = smod.main(["list", "--root", root2])
        check("C5 薄壳端到端：scripts.main(['list',...]) → 退出码 0",
              rc == 0 and "审核队列" in buf.getvalue(),
              "rc=%s out=%r" % (rc, buf.getvalue()[:80]))
    finally:
        shutil.rmtree(root2, ignore_errors=True)


# ---- D：纯 MdCGOS（无 self.session、无三态钩子）→ 日期兜底路径 ----

def _group_d():
    print("\n[D] 纯 MdCGOS（无 self.session）：日期兜底路径各处同值 —— 输入空间补齐")
    root = tempfile.mkdtemp(prefix="attrcons_d_")
    cg = MdCGOS(root, autoflush=1)
    try:
        # D1 连实例归属都没有（`_attribution_session_of` 无钩子 → None）→
        #    `session_note` 落**日期兜底** YYYYMMDD：返回体 / fm.session / tag /
        #    两条审计行必须同为那个日期串。修前 op=add 审计行落 None 而其余各处
        #    落日期串（同一写入两处字面分叉）——该路径此前无任何测试覆盖。
        n1 = cg.session_note("D1 纯 MdCGOS 日期兜底要点")
        fm1 = _fm_disk(cg, n1["id"]) or {}
        tags1 = fm1.get("tags") or []
        au1a = _audit_of(cg, "add", n1["id"])
        au1b = _audit_of(cg, "session_note", n1["id"])
        day = n1.get("session")
        check("D1 纯 MdCGOS session_note()：fm == tag == 两条审计行 == 返回体 == 日期兜底",
              bool(day) and len(str(day)) == 8 and str(day).isdigit()
              and fm1.get("session") == day
              and f"session:{day}" in tags1
              and bool(au1a) and au1a.get("session") == day
              and bool(au1b) and au1b.get("session") == day,
              f"ret={day!r} fm={fm1.get('session')!r} tags={tags1} "
              f"add_audit={(au1a or {}).get('session')!r} "
              f"note_audit={(au1b or {}).get('session')!r}")

        # D2 纯 MdCGOS ＋ 显式 session（无三态钩子）→ 各处同为该显式值。
        cg.add("d_expl", "D2 纯 MdCGOS 显式会话", layer="contextual", session="Y")
        fm2 = _fm_disk(cg, "d_expl") or {}
        au2 = _audit_of(cg, "add", "d_expl")
        check("D2 纯 MdCGOS add(session='Y')：审计 == fm.session == 'Y'",
              fm2.get("session") == "Y"
              and bool(au2) and au2.get("session") == "Y",
              f"fm={fm2.get('session')!r} audit={(au2 or {}).get('session')!r}")

        # D3 纯 MdCGOS ＋ 无显式 session（也无实例归属）→ 各处同为同一空值；
        #    审计记录**带 session 键**、值为 None（形状不变，不是丢键）。
        cg.add("d_none", "D3 纯 MdCGOS 无归属", layer="contextual")
        fm3 = _fm_disk(cg, "d_none") or {}
        au3 = _audit_of(cg, "add", "d_none")
        check("D3 纯 MdCGOS add()：fm.session 与审计行为同一空值",
              fm3.get("session") is None
              and bool(au3) and "session" in au3 and au3.get("session") is None,
              f"fm={fm3.get('session')!r} audit={(au3 or {}).get('session')!r}")
    finally:
        cg.close()
        shutil.rmtree(root, ignore_errors=True)


# ----------------------------------------------------------------------
# 定点变异自证（锚点 = 去缩进后的运行中源码；命中 ≠1 → ANCHOR-MISS）
# ----------------------------------------------------------------------

def _src_of(fn):
    return textwrap.dedent(inspect.getsource(fn))


# 锚点 = 变异点**邻行**的稳定串（不与被抽回的表达式重叠）：这样磁盘级抽回
# 修复后 preflight 仍过、红项落在断言上（而非 ANCHOR-MISS）；锚点漂移则说明
# 变异点已搬家，变异表失效（fail-closed rc=2）。
_ANCHORS = (
    (lambda: _src_of(MdCGOS.session_note),
     'session = ((session or "").strip()'),
    (lambda: _src_of(MdCGOS.add),
     'session=kw.get("session"))'),
    (lambda: _src_of(MdCGSecure._attribution),
     'kw.setdefault("session", self._attributed_session(sens))'),
    (lambda: _src_of(MdCGSecure._audit),
     'meta.setdefault("tenant", self.principal.tenant)'),
    (lambda: _src_of(_rv_pkg._cg),
     'session = _session_of(args)'),
)


def _anchor_preflight():
    bad = []
    for get_src, anchor in _ANCHORS:
        n = get_src().count(anchor)
        if n != 1:
            bad.append((anchor, n))
    if not bad:
        return 0
    for anchor, n in bad:
        print("  ANCHOR-MISS 锚点漂移（命中 %d 次，期望恰好 1）：%r"
              % (n, anchor[:70]))
    print("  => 实现已漂移，变异表失效：退出码 2（fail-closed）")
    return 2


def _run_all():
    global PASS, FAIL
    PASS = FAIL = 0
    del FAILS[:]
    old = _setenv(MDCG_SESSION=None, DSH_SESSION_ID=None)
    try:
        _group_a()
        _group_b()
        _group_c()
        _group_d()
    finally:
        _restore(old)
    return ({n.split(" ", 1)[0] for n in FAILS}, PASS, FAIL)


# 变异表：每条 (标签, 名, 宿主函数或 None, old, new, 期望红项集合)。
# 宿主函数为 None → 文本变异（走 _SCRIPTS_SRC_OVERRIDE，只改内存源文本）。
_MUTATIONS = (
    ("$②", "session_note 漏传 sens（退回 _attribution_session_of(self)）",
     MdCGOS.session_note,
     'or (_attribution_session_of(self, sensitivity) or "").strip()',
     'or (_attribution_session_of(self) or "").strip()',
     {"A2"}),
    # ⑤ 同族补齐点：抽回「显式 session 转发」→ 显式档诸腿（A3 共享 / A4 绑定 /
    #    A5-A6 内层 add 审计行 / A7 session_compact / D1 纯 MdCGOS 日期兜底——该档
    #    的 fm 归属也只经这条转发）转红，默认档（A1）与绑定档无显式（A2）不牵连。
    ("$⑤", "session_note 不转发显式 session 给 add（抽回同族补齐）",
     MdCGOS.session_note,
     'sensitivity=sensitivity, session=session)',
     'sensitivity=sensitivity)',
     {"A3", "A4", "A5", "A6", "A7", "D1"}),
    # ⑥ 同族补齐点（本批新增）：抽回「写面把有效会话传给审计」→ op=add 审计行退回
    #    三态单点。显式档诸腿（A5-A7 内层 add 行 / B5-B6 add 直传 / D1-D2 纯 MdCGOS）
    #    转红；无显式档（A1-A4、B1-B4、D3）不牵连（零连带：单点值与写面值本就同值）。
    ("$⑥", "add 的审计行退回三态单点（抽回写面传值）",
     MdCGOS.add,
     'session=kw.get("session"))',
     ')',
     {"A5", "A6", "A7", "B5", "B6", "D1", "D2"}),
    # ⑦（重定位）：写面 `_attribution` 不再经三态单点（直接取 self.session）→
    #    未声明进程的 add 落进程随机而非 'unattributed'（B1 转红）。它原由 ③ 承担，
    #    本批后 ③ 已不触达 add（写面传值优先，见实现注释），故把 B1 的判别腿重定位到
    #    写面单点这一处；A2/B4（声明档/绑定档）与其余各组不牵连。
    ("$⑦", "_attribution 不经三态单点（写面退回 self.session）",
     MdCGSecure._attribution,
     'kw.setdefault("session", self._attributed_session(sens))',
     'kw.setdefault("session", self.session)',
     {"B1"}),
    # ③（覆盖面收缩说明，2026-10-07）：本批后 `add` 的审计行不再取自本 setdefault
    #    （写面显式传值优先），故该变异只再触达**未传写面会话**的 op（propose → B3）；
    #    B1 的判别腿改由 ⑦ 承担（断言字面与强度未变，非放宽）。
    ("$③", "审计面退回原始 principal.session（不接三态）",
     MdCGSecure._audit,
     'meta.setdefault("session", self._attributed_session(sens))',
     'meta.setdefault("session", self.principal.session)',
     {"B3"}),
    ("$④b", "去掉 review_cli._cg 的 autoflush=1",
     _rv_pkg._cg,
     'return MdCGSecure(_root(args), principal=p, autoflush=1)',
     'return MdCGSecure(_root(args), principal=p)',
     {"C3"}),
    # ④a：让 scripts 版再自带实现（不再是薄壳）→ C1 应红（文本变异）
    ("$④a", "让 scripts 版再自带实现（不再是薄壳）",
     None,
     "from md_cg.review_cli import main  # noqa: E402",
     "from md_cg.review_cli import _root, _session_of  # noqa: E402\n\n\n"
     "def main(argv=None):\n"
     "    return _root, _session_of\n",
     {"C1", "C2", "C5"}),
)


def _mutate_and_run(ns_mod, host_fn, old, new):
    """就地变异 host_fn 后跑全套，finally 复原。

    类方法走「类体内 exec」——直接 exec 一个裸 `def` 会丢掉编译器为类体语境生成的
    `__class__` 空位，使零参 `super()` 报 RuntimeError；故把变异源贴进一个同名基类的临时类体
    里 exec（造出 `__class__` cell），再把该 cell 指回**真类**——这样 `super()` 仍相对真类的 MRO
    解析（与原方法同路）。
    """
    src = _src_of(host_fn)
    mutated = src.replace(old, new)
    qn = getattr(host_fn, "__qualname__", host_fn.__name__)
    ns = dict(vars(ns_mod))
    short = qn.split(".")[-1]
    if "." in qn:                        # 类方法
        cls = ns_mod.__dict__[qn.split(".")[0]]
        base = cls.__bases__[0]
        wrapper = ("class _Mut(" + base.__name__ + "):" + chr(10)
                   + textwrap.indent(mutated, "    "))
        exec(compile(wrapper, "<attrcons-mutated>", "exec"), ns)
        fn = ns["_Mut"].__dict__[short]
        free = fn.__code__.co_freevars
        if "__class__" in free:
            fn.__closure__[free.index("__class__")].cell_contents = cls
        orig = cls.__dict__[short]
        setattr(cls, short, fn)
        try:
            with contextlib.redirect_stdout(io.StringIO()):
                red, _, _ = _run_all()
            return red
        finally:
            setattr(cls, short, orig)
    exec(compile(mutated, "<attrcons-mutated>", "exec"), ns)
    orig = getattr(ns_mod, short)
    setattr(ns_mod, short, ns[short])
    try:
        with contextlib.redirect_stdout(io.StringIO()):
            red, _, _ = _run_all()
        return red
    finally:
        setattr(ns_mod, short, orig)


def _mutate_scripts_and_run(old, new):
    global _SCRIPTS_SRC_OVERRIDE
    _SCRIPTS_SRC_OVERRIDE = _scripts_src().replace(old, new)
    try:
        with contextlib.redirect_stdout(io.StringIO()):
            red, _, _ = _run_all()
        return red
    finally:
        _SCRIPTS_SRC_OVERRIDE = None


def _self_proof():
    rc = _anchor_preflight()
    if rc:
        return rc
    print("!! 定点变异自证：就地变异运行中的实现源码（不读 git / 不写盘），"
          "逐条要求**恰好**命中期望红项\n")
    with contextlib.redirect_stdout(io.StringIO()):
        base_red, _, _ = _run_all()
    print("  未变异基线：红项 %d %s" % (len(base_red),
                                        "（应为 0）" if base_red else ""))
    bad = []
    if base_red:
        bad.append("未变异基线即转红：%s" % sorted(base_red))
    for tag, name, host_fn, old, new, expect in _MUTATIONS:
        try:
            if host_fn is None:                            # 文本变异（内存源）
                red = _mutate_scripts_and_run(old, new)
            else:
                red = _mutate_and_run(sys.modules[host_fn.__module__],
                                      host_fn, old, new)
        except Exception as exc:                          # noqa: BLE001
            red = {"<变异体运行异常:%s>" % type(exc).__name__}
        hit = red == expect
        if not hit:
            bad.append("变异%s：红项 %s ≠ 期望 %s"
                       % (tag, sorted(red), sorted(expect)))
        print("  %-4s %-44s 红项 %d（期望 %d）%s"
              % (tag, name, len(red), len(expect),
                 "PASS" if hit else "**FAIL** 实=%s 期=%s" % (sorted(red),
                                                              sorted(expect))))
    argv_bak = list(sys.argv)
    sys.argv[:] = [a for a in argv_bak if a != "--self-proof"]
    _buf = io.StringIO()
    try:
        with contextlib.redirect_stdout(_buf):
            full_rc = main()
    finally:
        sys.argv[:] = argv_bak
    print("  复原后重跑全套（A–D）：退出码 %d %s"
          % (full_rc, "（全绿）" if full_rc == 0 else "**非全绿**"))
    if full_rc:
        for _ln in _buf.getvalue().splitlines():
            if "[FAIL]" in _ln:
                print("    复原重跑红：%s" % _ln.strip()[:120])
        bad.append("复原后全套非全绿（rc=%d）" % full_rc)
    print("\n变异自证：%s"
          % ("PASS（%d 条腿逐条恰好命中期望红项；复原后全绿）" % len(_MUTATIONS)
             if not bad
             else "FAIL —— " + "；".join(bad)))
    return 0 if not bad else 1


def main():
    global PASS, FAIL
    if "--self-proof" in sys.argv:
        return _self_proof()
    _rc = _anchor_preflight()
    if _rc:
        return _rc
    PASS = FAIL = 0
    del FAILS[:]
    old = _setenv(MDCG_SESSION=None, DSH_SESSION_ID=None)
    try:
        _group_a()
        _group_b()
        _group_c()
        _group_d()
    finally:
        _restore(old)
    print("\n" + "=" * 68)
    print(f"通过 {PASS} / 失败 {FAIL}")
    if FAILS:
        print("失败项：" + "，".join(FAILS))
    print("=" * 68)
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    _rc = main()
    sys.exit(_rc if _rc in (0, 2) else 1)
