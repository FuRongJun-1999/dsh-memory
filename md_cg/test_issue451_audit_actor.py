# -*- coding: utf-8 -*-
# 功能名：受保护/不可篡改节点被 override 覆写时审计行必须记执行者（issue #451）
# 生效条件：python -u -X utf8 -m md_cg.test_issue451_audit_actor [--mutate]；被测面＝md_cg/protect.py 的 _audit（经 _actor_of 单点）+ _allow 三条出口（override_write / override_forget / override_move）
# 子功能：A 组＝正向腿（三条出口的审计行 actor 非 null 且 == 库实例身份；盘上审计文件同款）；K 组＝反向腿①（显式 actor 优先；无 .actor 载体仍 null —— 不凭空造身份）；E 组＝源码面（_actor_of 定义唯一、三处同语义表达已收口、_audit 经它取 actor）；M 组＝反向腿②（--mutate，红项严格相等且不重叠）
# 执行：--mutate 时在镜像树里逐条撤兜底／改成恒取实例身份，守卫必须按指定项转红
# 验证方式：全部 PASS 即通过（退出码 0）；--mutate 下每条变异的红项集合须与预期逐项相符，锚点未命中即 fail-closed
# 不适用条件：① **腿看不见「actor 值是否*是*真正的那一方」**——本仓无独立身份源，只保证「非 null 且等于库实例身份」（与 §5.2 P1 C4 行的可判性边界同口径）；② **不覆盖无身份载体的部署**——裸 MdCG 无 `.actor` 属性，审计行仍为 null（K2 正是钉这条「不凭空造身份」，不许去掉）；③ 不覆盖审计行的**轮转/上限**（属 U13）；④ 不判 `actor` 的取值合法性（本层不做白名单）。
"""issue #451 守卫：override_* 审计行不得 `actor: null`（同一出口两种口径）。

病象（修前）：`_allow` → `_audit` 把 actor **原样**透传，而三守卫经 mdcg 写面调用时
都不传 actor ⇒ `override_write` / `override_forget` / `override_move` 三类审计行
`actor: null`；同一出口的 `snapshot` / `preimage` 两行却都有 actor（`protect.py` 里
已经有两处同语义表达：`:295` 用 `getattr(cg,"actor",None)`、`:342` 用
`actor if actor is not None else getattr(cg,"actor",None)`）。
修法（**单点收口**，issue「单点，二选一，别两处都改」取①）：新增 `_actor_of(cg, actor)`
一个真源（= `:342` 的既有口径），`_audit` 与 `:295`/`:342` 全部改走它；
**两处调用点（mdcg 的写面）不动**。

方法（本波通行，Lead 采纳）：**变异打行为面 + 源码面钉接线**——行为腿只钉一处
（`_audit`，A1–A4），`:295`/`:342` 两站点由**源码面 E3** 钉住。这样避免「同一点被
两处断言重复钉死」导致变异红项重叠（已在 U05c 与本批连续两次有效）。

形态名（供按名检索）：③ 「**名字打偏**」——把模块名/符号名拼错（如本批我误用
`test_n204_layer_protect_stamp`，真名 `test_n204_n205_n226_n227_n228_n229_exit_gates`），
跑出来 rc=1 看着像红，其实是「模块不存在」**假红**；与「判据被被测物里的说明文字骗」
同族（都是判据/调用面自身的错，不是被测物的缺陷）。**核名先行**：跑之前先确认名字存在。
"""
from __future__ import annotations

import ast
import json
import os
import shutil
import subprocess
import sys
import tempfile

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO not in sys.path:
    sys.path.insert(0, _REPO)

_TMP = tempfile.mkdtemp(prefix="iss451_")
os.environ.update({"MDCG_ROOT": _TMP + "/brain", "MDCG_STATE_ROOT": _TMP + "/state",
                   "MDCG_AUX_ROOT": _TMP + "/auxstore", "MDCG_DATA_ROOT": _TMP + "/datastore",
                   "MDCG_EXPORT_ROOT": _TMP, "MDCG_SUSTAIN": "0", "MDCG_SLEEP": "0"})
os.environ.pop("MDCG_READ_CACHE", None)

from md_cg import protect as _p                      # noqa: E402
from md_cg import tokens as _tk                       # noqa: E402
from md_cg.mdcos import MdCGSecure                    # noqa: E402
from md_cg.mdcg import MdCG                           # noqa: E402
from md_cg.security import Principal                  # noqa: E402

PASSED, FAILS = [], []
ACTR = "auditor451"


def _check(name, cond, detail=""):
    if cond:
        print("  PASS " + name)
        PASSED.append(name)
    else:
        print("  FAIL " + name + "  " + str(detail)[:240])
        FAILS.append(name)


def _ccg(v):
    return ("# 功能名：锚点" + v + chr(10) + "# 生效条件：任何会话" + chr(10)
            + "# 子功能：" + v + chr(10) + "# 执行：" + v + chr(10)
            + "# 验证方式：外部裁决" + chr(10) + "# 不适用条件：无")


def _cg(root, actor=ACTR):
    sp = _tk.role_spec("designer")
    return MdCGSecure(root, principal=Principal(
        actor=actor, clearance="secret", can_write=sp["can_write"], can_admin=True,
        role="designer", layers_allow=sp["layers_allow"], ops_allow=sp["ops_allow"]),
        autoflush=1)


def _proto(root, nid="g1"):
    """anchor 层节点 ⇒ is_immutable 与 is_protected 同时为真（三条出口都能触发）。"""
    cg = _cg(root)
    cg.add(nid, _ccg(nid), layer="anchor")
    cg.flush()
    return cg


def _audit_rows(root):
    p = os.path.join(root, _p.AUDIT_FILE)
    if not os.path.exists(p):
        return []
    with open(p, encoding="utf-8") as f:
        return [json.loads(ln) for ln in f if ln.strip()]


def group_a(tmp):
    print("== A 组：正向腿——三条 override 出口的审计行都要记执行者 ==")
    root = os.path.join(tmp, "a")
    cg = _proto(root)
    r1 = _p.guard_write(cg, "g1", override=True)
    _check("A1 override_write：审计行 actor 非 null 且 == 库实例身份",
           ((r1 or {}).get("audit") or {}).get("actor") == ACTR, "rec=%r" % (r1 or {}).get("audit"))
    r2 = _p.guard_forget(cg, "g1", override=True)
    _check("A2 override_forget：同款",
           ((r2 or {}).get("audit") or {}).get("actor") == ACTR, "rec=%r" % (r2 or {}).get("audit"))
    r3 = _p.guard_move(cg, "g1", "contextual", override=True)
    _check("A3 override_move：同款",
           ((r3 or {}).get("audit") or {}).get("actor") == ACTR, "rec=%r" % (r3 or {}).get("audit"))
    rows = _audit_rows(root)
    acts = {r.get("action"): r.get("actor") for r in rows}
    _check("A4 盘上审计文件三行同款（不是只在返回值里）",
           acts.get("override_write") == ACTR and acts.get("override_forget") == ACTR
           and acts.get("override_move") == ACTR, "rows=%s" % acts)
    _check("A5 三条出口的 action 名未变（口径没被顺手改）",
           set(acts) >= {"override_write", "override_forget", "override_move"}, "rows=%s" % acts)
    cg.close()


def group_k(tmp):
    print("== K 组：反向腿①——显式优先 / 无身份载体仍 null ==")
    root = os.path.join(tmp, "k")
    cg = _proto(root)
    r = _p.guard_write(cg, "g1", override=True, actor="explicit_who")
    _check("K1 显式传入的 actor 仍优先（不被实例身份覆盖）",
           ((r or {}).get("audit") or {}).get("actor") == "explicit_who", "rec=%r" % (r or {}).get("audit"))
    cg.close()
    root2 = os.path.join(tmp, "k_bare")
    bare = MdCG(root2)                       # 裸 MdCG：无 .actor 属性
    bare.add("g2", _ccg("g2"), layer="anchor")
    bare.flush()
    _check("K2 前置：裸 MdCG 确无 .actor 属性", not hasattr(bare, "actor"))
    r2 = _p.guard_write(bare, "g2", override=True)
    _check("K2 无身份载体 ⇒ 审计行仍为 null（**不凭空造身份**，不许去掉）",
           ((r2 or {}).get("audit") or {}).get("actor") is None, "rec=%r" % (r2 or {}).get("audit"))
    bare.close()


def _src(rel):
    with open(os.path.join(_REPO, rel), encoding="utf-8") as f:
        return f.read()


def _fn(tree, cls, name):
    for node in ast.walk(tree):
        if cls and isinstance(node, ast.ClassDef) and node.name == cls:
            for sub in node.body:
                if isinstance(sub, ast.FunctionDef) and sub.name == name:
                    return sub
        if not cls and isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    return None


def _calls(fn, name):
    out = []
    for node in ast.walk(fn) if fn is not None else []:
        if isinstance(node, ast.Call):
            f = node.func
            if (getattr(f, "attr", None) or getattr(f, "id", None)) == name:
                out.append(node)
    return out


def group_e(tmp):
    print("== E 组：源码面——单点收口在位 ==")
    src = _src("md_cg/protect.py")
    tree = ast.parse(src, "protect.py")
    defs = [n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == "_actor_of"]
    _check("E1 _actor_of 定义恰一处（单点真源）", len(defs) == 1, "defs=%d" % len(defs))
    # AST 口径：只数代码里的 getattr(*, "actor", ...) 调用——文本口径会被**注释/文档串**
    # 骗（我自己在 `生效条件` 与 docstring 里就写了这个表达式；同 #439 E2b 的形态）。
    n_getattr = 0
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            f = node.func
            if (getattr(f, "id", None) == "getattr" and len(node.args) >= 2
                    and isinstance(node.args[1], ast.Constant)
                    and node.args[1].value == "actor"):
                n_getattr += 1
    _check("E2 同语义旧表达已收口：protect.py 内 getattr(*, \"actor\") 调用恰一处（helper 内）",
           n_getattr == 1, "calls=%d" % n_getattr)
    for name in ("_audit", "snapshot", "snapshot_preimage"):
        fn = _fn(tree, None, name)
        got = len(_calls(fn, "_actor_of"))
        _check("E3 %s 经 _actor_of 取 actor（恰一处）" % name, got == 1, "calls=%d" % got)


def _guard_group(tag, fn, tmp):
    try:
        fn(tmp)
    except Exception as exc:                              # noqa: BLE001
        import traceback
        _check("%s0 组内异常（fail-closed：异常即红）" % tag, False,
               "%s: %s" % (type(exc).__name__, exc))
        traceback.print_exc()


def main():
    print("== #451 override_* 审计 actor 守卫 ==")
    _guard_group("A", group_a, _TMP)
    _guard_group("K", group_k, _TMP)
    _guard_group("E", group_e, _TMP)
    print("=" * 68)
    print("#451 守卫：%d 通过，%d 失败" % (len(PASSED), len(FAILS)))
    for f in FAILS:
        print("  红项：" + f)
    _bad = _mutate() if "--mutate" in sys.argv else 0
    return 1 if (FAILS or _bad) else 0


_MUTATIONS = (
    ("M1 撤 _audit 的兜底（回到 #451 病象：actor 原样透传）",
     "md_cg/protect.py",
     (("           \"reason\": reason, \"actor\": _actor_of(cg, actor), \"snapshot\": snapshot}",
       "           \"reason\": reason, \"actor\": actor, \"snapshot\": snapshot}"),),
     ("A1", "A2", "A3", "A4", "E3")),
    ("M2 _actor_of 改成恒取实例身份（忽略显式传入）",
     "md_cg/protect.py",
     (("    return actor if actor is not None else getattr(cg, \"actor\", None)",
       "    return getattr(cg, \"actor\", None)"),),
     ("K1",)),
)


def _mirror_build():
    dst = tempfile.mkdtemp(prefix="iss451_mut_")
    for name in ("md_cg", "lib"):
        src = os.path.join(_REPO, name)
        if os.path.isdir(src):
            shutil.copytree(src, os.path.join(dst, name),
                            ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    for name in sorted(os.listdir(_REPO)):
        p = os.path.join(_REPO, name)
        if os.path.isfile(p) and name.endswith(".py"):
            shutil.copy2(p, os.path.join(dst, name))
    return dst


def _run_in(tree):
    env = dict(os.environ)
    env["PYTHONPATH"] = tree
    env["PYTHONUTF8"] = "1"
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    for k in ("MDCG_ROOT", "MDCG_STATE_ROOT", "MDCG_AUX_ROOT", "MDCG_DATA_ROOT",
              "MDCG_EXPORT_ROOT", "MDCG_INGEST_ROOT", "MDCG_TOKEN", "MDCG_TOKEN_FILE"):
        env.pop(k, None)
    pr = subprocess.run([sys.executable, "-u", "-X", "utf8", "-m",
                         "md_cg.test_issue451_audit_actor"],
                        capture_output=True, text=True, encoding="utf-8",
                        errors="replace", cwd=tree, env=env, timeout=1800)
    out = (pr.stdout or "") + (pr.stderr or "")
    reds = [ln.split("FAIL ", 1)[1].strip()
            for ln in out.splitlines() if ln.strip().startswith("FAIL ")]
    return pr.returncode, reds, out


def _apply_text(text, rel, pairs):
    eol = (chr(13) + chr(10)) if (chr(13) + chr(10)) in text else chr(10)
    for old, new in pairs:
        o = old.replace(chr(10), eol)
        n = new.replace(chr(10), eol)
        if text.count(o) != 1:
            return None, "锚点在 %s 里命中 %d 次" % (rel, text.count(o))
        text = text.replace(o, n, 1)
    return text, ""


def _mutate():
    print("!! 反向腿②：撤兜底／改成恒取实例身份，守卫必须按指定项转红")
    tree = _mirror_build()
    bad = []
    try:
        rc, reds, out = _run_in(tree)
        print("  未变异镜像基线：rc=%d 红项=%d（必须 rc=0 且 0 红）" % (rc, len(reds)))
        if rc != 0 or reds:
            bad.append("未变异镜像基线即红")
            print(chr(10).join(out.splitlines()[-20:]))
        for desc, rel, pairs, exp in _MUTATIONS:
            p = os.path.join(tree, rel)
            with open(p, encoding="utf-8", newline="") as f:
                bak = f.read()
            mut, why = _apply_text(bak, rel, pairs)
            if mut is None:
                bad.append("%s —— %s" % (desc, why))
                print("  ANCHOR-MISS " + desc + "  " + why)
                continue
            with open(p, "w", encoding="utf-8", newline="") as f:
                f.write(mut)
            for root, _dd, _ff in os.walk(tree):
                if os.path.basename(root) == "__pycache__":
                    shutil.rmtree(root, ignore_errors=True)
            rc2, reds2, out2 = _run_in(tree)
            with open(p, "w", encoding="utf-8", newline="") as f:
                f.write(bak)
            hit = sorted({r.split(" ")[0] for r in reds2})
            if rc2 != 0 and hit == sorted(exp):
                print("  OK   %s  红项=%d 指定命中=%s" % (desc, len(reds2), hit))
            else:
                bad.append(desc)
                print("  MISMATCH %s  实际红项=%s  期望=%s  rc=%d"
                      % (desc, hit, sorted(exp), rc2))
                for r in reds2[:10]:
                    print("        FAIL " + r)
        print("反向腿②：%s（%d 条不合格）" % ("PASS" if not bad else "FAIL", len(bad)))
        return len(bad)
    finally:
        shutil.rmtree(tree, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
