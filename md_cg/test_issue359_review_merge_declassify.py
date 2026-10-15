# -*- coding: utf-8 -*-
# 功能名：审核 merge 不得降低提案密级或替裁决者读不可见提案（issue #359）
# 生效条件：python -X utf8 -m md_cg.test_issue359_review_merge_declassify [--mutate]
# 子功能：A 缺陷面；K 非恒真对照；E 合并落盘 AST 清单
# 执行：临时库行为断言；--mutate 仅改临时镜像，单行锚点兼容 CRLF
# 验证方式：普通跑全部 PASS；镜像基线全绿且四条变异逐个指定红项命中
# 不适用条件：#69 inbox 明文、pid 的取得渠道、真实 CLI/stdio 由独立 repro 覆盖；tidy 闸属独立 #360
"""#359：拒绝整次 merge，不静默剔除正文、不改目标密级、不关闭提案。

E 组列全五个已知正文合并落点。独立 main+#359 分支中 tidy 仍是 #360
已知遗留，必须显式报告而非把 #360 混入本 PR 或声称五个闸都已补齐。
"""
from __future__ import annotations

import ast
from contextlib import contextmanager
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

_REPO = Path(__file__).resolve().parent.parent
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))
_RESULTS = []
MARK = "PRIVATE_REVIEW_359_739154"


def _check(name, cond, detail=""):
    _RESULTS.append((bool(cond), name))
    print(("  PASS " if cond else "  FAIL ") + name
          + ("" if cond else " " + repr(detail)[:250]))


def _principal(role):
    from md_cg.security import Principal
    from md_cg import tokens
    sp = tokens.role_spec(role)
    return Principal(actor="iss359-" + role, role=role,
                     clearance=sp["clearance_cap"], can_write=sp["can_write"],
                     can_admin=sp["can_admin"], layers_allow=sp["layers_allow"],
                     ops_allow=sp["ops_allow"])


@contextmanager
def _env():
    with tempfile.TemporaryDirectory(prefix="iss359_") as tmp:
        saved = {k: v for k, v in os.environ.items() if k.startswith("MDCG_")}
        for key in saved:
            os.environ.pop(key, None)
        os.environ.update({"MDCG_ROOT": tmp + "/brain",
                           "MDCG_STATE_ROOT": tmp + "/state",
                           "MDCG_AUX_ROOT": tmp + "/auxstore",
                           "MDCG_TOKEN_FILE": tmp + "/auxstore/tokens.json",
                           "MDCG_DATA_ROOT": tmp + "/data",
                           "MDCG_EXPORT_ROOT": tmp,
                           "MDCG_SUSTAIN": "0", "MDCG_SLEEP": "0"})
        from md_cg import crypto
        os.environ[crypto.MASTER_ENV] = "ab" * 32
        from md_cg.mdcos import MdCGSecure
        handles = []

        def open_as(role):
            cg = MdCGSecure(tmp + "/brain", principal=_principal(role), autoflush=1)
            handles.append(cg)
            return cg

        try:
            yield open_as, Path(tmp + "/brain")
        finally:
            for cg in reversed(handles):
                cg.close()
            for key in list(os.environ):
                if key.startswith("MDCG_"):
                    os.environ.pop(key, None)
            os.environ.update(saved)


def _body(cg, nid):
    return (cg.get(nid) or {}).get("content") or ""


def _disk(root, nid):
    paths = list(root.rglob(nid + ".md"))
    if len(paths) != 1:
        raise AssertionError((nid, paths))
    return paths[0].read_bytes()


def a_group():
    with _env() as (open_as, root):
        owner = open_as("designer")
        owner.add("target", "internal 目标原文", layer="contextual", sensitivity="internal")
        pid = owner.propose("proposal", MARK, layer="contextual", sensitivity="private")
        before = _disk(root, "target")
        _check("A0 private 提案真实可见且目标非空", bool(pid)
               and any(r["pid"] == pid for r in owner.review_list())
               and "目标原文" in _body(owner, "target"))
        r = owner.review_decide(pid, "merge", merge_into="target")
        _check("A1 private→internal 明确拒绝并报告双方密级",
               r.get("ok") is False and r.get("error") == "merge_downgrade_refused"
               and r.get("target_sensitivity") == "internal"
               and r.get("incoming_sensitivity") == "private", r)
        _check("A2 拒绝后目标文件逐字节不变且无 private 串",
               _disk(root, "target") == before and MARK.encode() not in _disk(root, "target"))
        guest = open_as("guest")
        _check("A3 internal 读者仍读到原文但读不到 private 串",
               "目标原文" in _body(guest, "target") and MARK not in _body(guest, "target"))
        _check("A4 拒绝后提案仍 pending（没有假装裁决成功）",
               any(row["pid"] == pid for row in owner.review_list()))

    with _env() as (open_as, root):
        owner = open_as("designer")
        owner.add("scratch", "orchestr 草稿", layer="contextual", sensitivity="internal")
        pid = owner.propose("hidden", MARK + "_B", layer="contextual", sensitivity="private")
        orch = open_as("orchestr")
        _check("A5 前提：orchestr 看不到 private 提案且可读目标",
               not any(row["pid"] == pid for row in orch.review_list())
               and bool(_body(orch, "scratch")))
        before = _disk(root, "scratch")
        r = orch.review_decide(pid, "merge", merge_into="scratch")
        _check("A6 不可见提案凭 pid merge 返回 proposal_not_visible",
               r.get("ok") is False and r.get("error") == "proposal_not_visible", r)
        _check("A7 拒绝后盘面不变且 orchestr 未读到 private 串",
               before == _disk(root, "scratch") and MARK not in _body(orch, "scratch"))


def k_group():
    for label, incoming, target, role in (
            ("K1", "internal", "internal", "designer"),
            ("K2", "internal", "private", "designer"),
            ("K3", "internal", "internal", "orchestr")):
        with _env() as (open_as, root):
            owner = open_as("designer")
            owner.add("target", "合法目标原文", layer="contextual", sensitivity=target)
            pid = owner.propose("allowed", MARK, layer="contextual", sensitivity=incoming)
            reviewer = owner if role == "designer" else open_as(role)
            r = reviewer.review_decide(pid, "merge", merge_into="target")
            _check(label + " 合法方向放行且正文真实追加（" + role + "）",
                   r.get("ok") is True and MARK in _body(reviewer, "target")
                   and "合法目标原文" in _body(reviewer, "target"), r)
            # private 目标是加密落盘；读回而非要求磁盘出现明文。
            _check(label + "b 目标密级不变且提案已出 pending",
                   (reviewer.get("target")["frontmatter"].get("sensitivity") or "internal") == target
                   and not any(row["pid"] == pid for row in owner.review_list()))


def _calls(node, name):
    return [n for n in ast.walk(node) if isinstance(n, ast.Call)
            and ((isinstance(n.func, ast.Attribute) and n.func.attr == name)
                 or (isinstance(n.func, ast.Name) and n.func.id == name))]


def e_group():
    # 清单包含写正文的函数而非仅 grep 注释；branches 经本模块适配器复用单点。
    inventory = (("writelimit.py", "converge_into"), ("forgetting.py", "reinforce"),
                 ("branches.py", "merge"), ("mdcos.py", "review_decide"),
                 ("writelimit.py", "tidy_contextual"))
    for i, (rel, name) in enumerate(inventory, 1):
        tree = ast.parse((_REPO / "md_cg" / rel).read_text(encoding="utf-8"))
        # branches.merge 是替换回写而非拼接，实际 sink 为 cg.add → _write_node。
        sink = "add" if rel == "branches.py" else "_write_node"
        functions = [n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)
                     and n.name == name and _calls(n, sink)]
        _check("E%d 清单落点存在且确有写入 sink：%s.%s" % (i, rel, name),
               len(functions) == 1)
        if not functions:
            continue
        fn = functions[0]
        guards = _calls(fn, "_merge_downgrades")
        if name == "tidy_contextual":
            print("  INVENTORY tidy_contextual: " + ("已接单点" if guards else "KNOWN GAP #360（独立 PR，不冒称已修）"))
            continue
        _check("E%db 正文写盘前调用 merge_downgrades" % i,
               bool(guards) and min(n.lineno for n in guards)
               < max(n.lineno for n in _calls(fn, sink)))
        imports = [n for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)
                   and n.module == "security" and any(a.name == "merge_downgrades" for a in n.names)]
        _check("E%dc 单点源自 security（不自造密级判据）" % i, bool(imports))


# 所有锚点都单行、不含换行：维护者 CRLF 检出与 LF 检出同口径。
_MUTATIONS = (
    ("V1 移除 review 降密级闸", "md_cg/mdcos.py",
     "            if _merge_downgrades(_tgt_sens, _in_sens):",
     "            if False:  # mutant V1", ("A1 ", "A2 ", "A3 ")),
    ("V2 移除裁决者可见性闸", "md_cg/mdcos.py",
     '            _rd = getattr(self, "_readable", None)',
     "            _rd = None  # mutant V2", ("A6 ",)),
    ("V3 incoming 密级被架空为 None", "md_cg/mdcos.py",
     "            if _merge_downgrades(_tgt_sens, _in_sens):",
     "            if _merge_downgrades(_tgt_sens, None):", ("A1 ", "A2 ", "A3 ")),
    ("V4 单点比较方向写反", "md_cg/security.py",
     "    return new > tgt", "    return new < tgt", ("A1 ", "A2 ", "K2 ")),
)


def _mirror_build():
    dst = Path(tempfile.mkdtemp(prefix="iss359_mut_"))
    for name in ("md_cg", "scripts"):
        shutil.copytree(_REPO / name, dst / name,
                        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    for p in _REPO.iterdir():
        if p.is_file() and (p.suffix == ".py" or p.name in
                            ("README.md", "pyproject.toml", "package.json")):
            shutil.copy2(p, dst / p.name)
    return dst


def _run_in(tree):
    env = dict(os.environ, PYTHONPATH=str(tree), PYTHONUTF8="1",
               PYTHONIOENCODING="utf-8", PYTHONDONTWRITEBYTECODE="1")
    pr = subprocess.run([sys.executable, "-X", "utf8", "-m",
                         "md_cg.test_issue359_review_merge_declassify"],
                        cwd=tree, env=env, capture_output=True, text=True,
                        encoding="utf-8", errors="replace", timeout=1800)
    out = pr.stdout + pr.stderr
    reds = [line.split("FAIL ", 1)[1].strip() for line in out.splitlines() if "FAIL " in line]
    return pr.returncode, reds, out


def _mutate():
    tree = _mirror_build()
    try:
        rc, reds, out = _run_in(tree)
        print("镜像基线：rc=%d 红项=%d" % (rc, len(reds)))
        if rc or reds:
            print(out)
            return 1
        passed = 0
        for desc, rel, old, new, expected in _MUTATIONS:
            assert "\n" not in old and "\r" not in old
            p = tree / rel
            with p.open(encoding="utf-8", newline="") as f:
                original = f.read()
            if original.count(old) != 1:
                print("  ANCHOR-MISS " + desc)
                continue
            try:
                with p.open("w", encoding="utf-8", newline="") as f:
                    f.write(original.replace(old, new, 1))
                for cache in list(tree.rglob("__pycache__")):
                    shutil.rmtree(cache)
                rc2, reds2, out2 = _run_in(tree)
                # 每个指定前缀都必须命中；多条红项不能掩盖某个指定项没红。
                hit = [prefix for prefix in expected if any(r.startswith(prefix) for r in reds2)]
                good = rc2 == 1 and len(hit) == len(expected)
                passed += int(good)
                print(("  OK " if good else "  MISMATCH ") + desc
                      + " 指定命中=%d/%d rc=%d" % (len(hit), len(expected), rc2))
                if not good:
                    print(out2[-5000:])
            finally:
                with p.open("w", encoding="utf-8", newline="") as f:
                    f.write(original)
        print("定点变异：%d/%d" % (passed, len(_MUTATIONS)))
        return 0 if passed == len(_MUTATIONS) else 1
    finally:
        shutil.rmtree(tree)


def main():
    if "--mutate" in sys.argv:
        return _mutate()
    a_group()
    k_group()
    e_group()
    bad = sum(not ok for ok, _ in _RESULTS)
    print("issue #359 结果：%d/%d 通过" % (len(_RESULTS) - bad, len(_RESULTS)))
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
