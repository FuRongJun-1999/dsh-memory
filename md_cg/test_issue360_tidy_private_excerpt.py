# -*- coding: utf-8 -*-
# 功能名：tidy 摘录不得把 private 成员降密级（issue #360，#304 已知遗留①）
# 生效条件：python -X utf8 -m md_cg.test_issue360_tidy_private_excerpt [--mutate]
# 子功能：A 私有成员摘录/降权保护；K 同档整理与 #190 幂等；E AST 接线清单
# 执行：临时库行为断言；--mutate 只改临时镜像，单行锚点兼容 CRLF
# 验证方式：普通跑全部 PASS；镜像基线全绿且两条变异逐个指定红项命中
# 不适用条件：#69 inbox 明文、历史摘录清理、计划成员统计语义和独立 #359 review 修复不在范围
"""#360：降密级成员整条跳过，不摘录、不降权、不标 tidy:converged。

所有内容、数字串和主密钥均为人工合成测试夹具。E 组检查 tidy 的真实
成员循环与写入次序，不把独立 #359 的 review 闸混入此分支。
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
import time

_REPO = Path(__file__).resolve().parent.parent
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))
_RESULTS = []
SECRET = "7319846"
IDS = ("n1", "n2", "n3")


def _check(name, cond, detail=""):
    _RESULTS.append((bool(cond), name))
    print(("  PASS " if cond else "  FAIL ") + name
          + ("" if cond else " " + repr(detail)[:250]))


def _principal(role):
    from md_cg.security import Principal
    from md_cg import tokens
    sp = tokens.role_spec(role)
    return Principal(actor="iss360-" + role, role=role,
                     clearance=sp["clearance_cap"], can_write=sp["can_write"],
                     can_admin=sp["can_admin"], layers_allow=sp["layers_allow"],
                     ops_allow=sp["ops_allow"])


@contextmanager
def _env():
    with tempfile.TemporaryDirectory(prefix="iss360_") as tmp:
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


def _seed(cg, private=True):
    for nid, digits in zip(IDS, ("1111", "2222", SECRET)):
        cg.add(nid, "门禁口令已更新为 " + digits, layer="contextual",
               sensitivity="private" if private and nid == "n3" else "internal",
               importance=0.6)
        time.sleep(0.01)  # 让保留节点顺序确定，不依赖文件枚举或时钟同毫秒。


def _disk(root, nid):
    paths = list(root.rglob(nid + ".md"))
    if len(paths) != 1:
        raise AssertionError((nid, paths))
    return paths[0].read_bytes()


def _nodes_snapshot(root):
    return {str(p.relative_to(root)): p.read_bytes() for p in root.rglob("*.md")}


def a_group():
    from md_cg import lifecycle, writelimit as wl
    with _env() as (open_as, root):
        cg = open_as("designer")
        _seed(cg)
        sigs = [wl.template_signature(cg.get(nid)["content"]) for nid in IDS]
        _check("A0 三节点同一非空签名且 private 独有串位于摘录范围",
               bool(sigs[0]) and len(set(sigs)) == 1
               and SECRET in cg.get("n3")["content"][:48]
               and SECRET not in cg.get("n1")["content"], sigs)
        before = _disk(root, "n3")
        old_fm = dict(cg.get("n3")["frontmatter"])
        r = wl.tidy_contextual(cg, apply=True)
        keep = cg.get("n1")
        _check("A1 确实整理本组且只降权合法 internal 成员",
               r.get("applied_count") == 1
               and [p.get("keep") for p in r.get("applied", [])] == ["n1"], r)
        _check("A2 keep 含合法摘录但不含 private 独有串或成员 id",
               "2222" in keep["content"] and SECRET not in keep["content"]
               and "- n3 " not in keep["content"], keep["content"])
        _check("A3 internal keep 盘面无 private 明文副本",
               SECRET.encode() not in _disk(root, "n1"))
        guest = open_as("guest")
        visible = guest.get("n1")
        _check("A4 internal guest 读到合法摘录而非 private 串且不能直接读 n3",
               bool(visible) and "2222" in visible["content"]
               and SECRET not in visible["content"] and guest.get("n3") is None)
        _check("A5 private 成员文件逐字节不变", before == _disk(root, "n3"))
        fm = cg.get("n3")["frontmatter"]
        _check("A6 private importance/tags/生命周期不变且没有 tidy 标记",
               fm.get("importance") == old_fm.get("importance") == 0.6
               and fm.get("tags") == old_fm.get("tags")
               and fm.get(lifecycle.STATE_FIELD) == old_fm.get(lifecycle.STATE_FIELD)
               and wl.TIDY_TAG not in (fm.get("tags") or []), fm)
        allowed = cg.get("n2")["frontmatter"]
        _check("A7 同组合法成员仍按原规则降权并标记 converged",
               allowed.get("importance") == 0.3
               and wl.TIDY_TAG in (allowed.get("tags") or [])
               and allowed.get(lifecycle.STATE_FIELD) == "converged", allowed)


def k_group():
    from md_cg import lifecycle, writelimit as wl
    with _env() as (open_as, root):
        cg = open_as("designer")
        _seed(cg, private=False)
        before = _nodes_snapshot(root)
        dry = wl.tidy_contextual(cg, apply=False)
        _check("K1 全 internal dry-run 有计划且节点文件逐字节不变",
               dry.get("groups") == 1 and bool(dry.get("planned"))
               and dry.get("applied") == [] and before == _nodes_snapshot(root), dry)
        r = wl.tidy_contextual(cg, apply=True)
        keep = cg.get("n1")
        _check("K2 同档整理真实摘录全部成员，不是恒跳过",
               r.get("applied_count") == 2 and "2222" in keep["content"]
               and SECRET in keep["content"] and "- n2 " in keep["content"]
               and "- n3 " in keep["content"], r)
        _check("K3 同档保留节点密级不变且 merge_count 延续原语义",
               (keep["frontmatter"].get("sensitivity") or "internal") == "internal"
               and keep["frontmatter"].get("merge_count") == 2)
        for nid in IDS[1:]:
            fm = cg.get(nid)["frontmatter"]
            _check("K4_" + nid + " 成员降权一次并保留原 tags/生命周期契约",
                   fm.get("importance") == 0.3 and wl.TIDY_TAG in (fm.get("tags") or [])
                   and fm.get(lifecycle.STATE_FIELD) == "converged", fm)
        snapshot = _nodes_snapshot(root)
        for round_no in (2, 3):
            again = wl.tidy_contextual(cg, apply=True)
            _check("K5_%d #190 后续轮无计划、无整理、节点文件逐字节冻结" % round_no,
                   again.get("planned") == [] and again.get("applied") == []
                   and not again.get("applied_count") and again.get("already_tidied") == 2
                   and snapshot == _nodes_snapshot(root), again)
        _check("K6 永不删节点且 guest 可读全部合法摘录",
               all(cg.get(nid) for nid in IDS)
               and SECRET in open_as("guest").get("n1")["content"])


def _calls(node, name):
    return [n for n in ast.walk(node) if isinstance(n, ast.Call)
            and ((isinstance(n.func, ast.Name) and n.func.id == name)
                 or (isinstance(n.func, ast.Attribute) and n.func.attr == name))]


def e_group():
    tree = ast.parse((_REPO / "md_cg" / "writelimit.py").read_text(encoding="utf-8"))
    functions = [n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)
                 and n.name == "tidy_contextual"]
    _check("E1 AST 清单中 tidy_contextual 恰有一个真实写入落点函数",
           len(functions) == 1 and bool(_calls(functions[0], "_write_node")))
    if not functions:
        return
    fn = functions[0]
    imports = [n for n in ast.walk(fn) if isinstance(n, ast.ImportFrom)
               and n.module == "security" and any(a.name == "merge_downgrades"
               and a.asname == "_merge_downgrades" for a in n.names)]
    _check("E2 降密级判据来自 security 单点，不复制规则", bool(imports))
    loops = [n for n in ast.walk(fn) if isinstance(n, ast.For)
             and isinstance(n.target, ast.Name) and n.target.id == "mid"]
    _check("E3 AST 清单定位真实成员循环", len(loops) == 1)
    if not loops:
        return
    loop = loops[0]
    gates = [n for n in loop.body if isinstance(n, ast.If)
             and _calls(n.test, "_merge_downgrades")]
    _check("E4 成员循环的降密级分支整条 continue",
           len(gates) == 1 and len(gates[0].body) == 1
           and isinstance(gates[0].body[0], ast.Continue))
    if not gates:
        return
    gate = gates[0]
    call = _calls(gate.test, "_merge_downgrades")[0]
    _check("E5 参数为保留档和当前成员档，不用 None 架空判据",
           len(call.args) == 2 and ast.unparse(call.args[0]) == "_keep_sens"
           and ast.unparse(call.args[1]) == "mfm.get('sensitivity')")
    excerpts = [n for n in ast.walk(loop) if isinstance(n, ast.Assign)
                and any(isinstance(t, ast.Name) and t.id == "first" for t in n.targets)]
    demotes = _calls(loop, "_demote")
    writes = _calls(fn, "_write_node")
    _check("E6 闸在摘录、降权和保留节点写盘之前",
           bool(excerpts) and bool(demotes) and bool(writes)
           and gate.lineno < min(n.lineno for n in excerpts + demotes + writes))


# 单行锚点：LF/CRLF 检出均命中一次，绝不依赖换行字节。
_MUTATIONS = (
    ("V1 删除降密级跳过判定", "md_cg/writelimit.py",
     '            if _merge_downgrades(_keep_sens, mfm.get("sensitivity")):',
     "            if False:  # mutant V1", ("A2 ", "A4 ", "A5 ", "A6 ")),
    ("V2 incoming 档被架空为 None", "md_cg/writelimit.py",
     '            if _merge_downgrades(_keep_sens, mfm.get("sensitivity")):',
     "            if _merge_downgrades(_keep_sens, None):", ("A2 ", "A4 ", "A5 ", "E5 ")),
)


def _mirror_build():
    dst = Path(tempfile.mkdtemp(prefix="iss360_mut_"))
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
                         "md_cg.test_issue360_tidy_private_excerpt"],
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
    print("issue #360 结果：%d/%d 通过" % (len(_RESULTS) - bad, len(_RESULTS)))
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
