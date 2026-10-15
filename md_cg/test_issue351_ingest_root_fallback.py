# -*- coding: utf-8 -*-
# 功能名：ingest dir 的空 path 不得回落记忆库根（issue #351）
# 生效条件：python -X utf8 -m md_cg.test_issue351_ingest_root_fallback [--mutate]；被测面=md_cg/sources.py 的 run(dir) 与 md_cg/mcp_server.py 的 _ingest_call
# 子功能：A 组=空 path 拒（fail-closed）；MDCG_INGEST_ROOT 设置时空 path 用 env 值；K 组=显式 path 照常 / env 值过白名单 / file-jsonl 缺 path 原有语义不变
# 执行：--mutate 时把 dir 空 path 的 fail-closed 改回「回落 cg.root」（即 #351 修前），守卫必须转红
# 验证方式：全部 PASS 即通过；--mutate 下变异的「指定命中」须与预期一致
# 不适用条件：不判 restricted/private 正文切换的端到端内容比读（报告 A/B 两面，需真实多节点库）；不判 report 方所用的 sim 层；不覆盖 POSIX 腿
"""issue #351 守卫：cg(op=ingest, action=dir) 空 path 不得回落记忆库根。

病象（修前）：sources.run 的 dir 分支 `p = kw.get("path") or cg.root`——库根下是
各层节点文件、trash/、_protected_history/，把它们当外部文档切成 doc_ref 节点：
(a) restricted 正文被抄进 internal 节点，无令牌访客可检索；(b) 已 forget 并
accept 删除的节点复活。且空 path 根本不过 MDCG_INGEST_ROOT 白名单检查。
"""
import os
import shutil
import sys
import tempfile

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _REPO)
_TMP = tempfile.mkdtemp(prefix="iss351_")
os.environ.update({"MDCG_ROOT": _TMP + "/brainroot", "MDCG_STATE_ROOT": _TMP + "/state",
                   "MDCG_AUX_ROOT": _TMP + "/auxstore",
                   "MDCG_DATA_ROOT": _TMP + "/datastore", "MDCG_EXPORT_ROOT": _TMP,
                   "MDCG_SUSTAIN": "0", "MDCG_SLEEP": "0"})
os.environ.pop("MDCG_INGEST_ROOT", None)
from md_cg.mdcos import MdCGSecure  # noqa: E402
from md_cg.security import Principal  # noqa: E402
from md_cg import mcp_server as _ms  # noqa: E402

FAILS = []


def _check(name, cond, detail=""):
    if cond:
        print("  PASS " + name)
    else:
        print("  FAIL " + name + "  " + str(detail)[:200])
        FAILS.append(name)


def _mk():
    return MdCGSecure(_TMP + "/brainroot",
                      principal=Principal(role="record", clearance="internal",
                                          can_write=True), autoflush=1)


def _ingest(cg, args):
    try:
        return _ms._dispatch(cg, "cg", dict({"op": "ingest"}, **args))
    except Exception as e:                      # noqa: BLE001
        return {"_exc": type(e).__name__ + ":" + str(e)[:110]}


print("== A 组：空 path 不得回落记忆库根 ==")
_cg = _mk()
_a1 = _ingest(_cg, {"action": "dir"})
_check("A1 空 path dir → 拒（ok=False，error 点名 issue #351）",
       _a1.get("ok") is False and "issue #351" in str(_a1.get("error")), _a1)

_n_before = len(_cg.index.get("nodes") or {})
_ingest(_cg, {"action": "dir"})
_n_after = len(_cg.index.get("nodes") or {})
_check("A2 空 path dir 不产生任何节点（库根未被当外部文档扫描）",
       _n_after == _n_before, (_n_before, _n_after))

print("== K 组：非恒真对照 ==")
_ext = os.path.join(_TMP, "extsrc")
os.makedirs(_ext, exist_ok=True)
with open(os.path.join(_ext, "note.md"), "w", encoding="utf-8") as f:
    f.write("# 功能名：外部文档\n# 生效条件：x\n# 子功能：y\n# 执行：z\n"
            "# 验证方式：w\n# 不适用条件：v\n")

_k1 = _ingest(_cg, {"action": "dir", "path": _ext})
_check("K1 显式 path（白名单外目录，未设 MDCG_INGEST_ROOT）→ 照常工作",
       "AccessDenied" not in str(_k1) and "issue #351" not in str(_k1),
       str(_k1)[:160])

os.environ["MDCG_INGEST_ROOT"] = _ext
_k2 = _ingest(_cg, {"action": "dir"})
_check("K2 设 MDCG_INGEST_ROOT 后空 path → 用 env 值（不再拒，也不再回落库根）",
       "issue #351" not in str(_k2) and "AccessDenied" not in str(_k2),
       str(_k2)[:160])
os.environ["MDCG_INGEST_ROOT"] = _TMP + "/outside nowhere"
_k3 = _ingest(_cg, {"action": "dir"})
_check("K3 env 值越出白名单 → 照过 check_path_root 被拒（白名单不被绕过）",
       "PermissionError" in str(_k3) or "AccessDenied" in str(_k3)
       or _k3.get("ok") is False, str(_k3)[:160])
os.environ.pop("MDCG_INGEST_ROOT", None)

_k4 = _ingest(_cg, {"action": "file"})
_check("K4 file 缺 path → 原有语义不变（ok=False）",
       _k4.get("ok") is False and "path" in str(_k4.get("error")), _k4)

_cg.close()
shutil.rmtree(_TMP, ignore_errors=True)

print("")
if FAILS:
    print("issue #351 结果：%d 失败" % len(FAILS))
else:
    print("issue #351 结果：全部通过")

# ------------------------------------------------------------------ 定点变异
# 锚点取「注释行 + p 行」两行（在 sources.py 里唯一）；行尾按目标文件实际 NL 折算。
_MUTATIONS = (
    ("V1 dir 空 path 回落 cg.root（即 #351 修前：不再 fail-closed）",
     "md_cg/sources.py",
     "        # fail-closed，不猜扫描根。" + chr(10)
     + "        p = kw.get(\"path\")",
     "        p = kw.get(\"path\") or cg.root",
     ("A1",)),
)


def _mirror_build():
    dst = tempfile.mkdtemp(prefix="iss351_mut_")
    for name in ("md_cg", "scripts"):
        src = os.path.join(_REPO, name)
        if os.path.isdir(src):
            shutil.copytree(src, os.path.join(dst, name),
                            ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    for name in sorted(os.listdir(_REPO)):
        p = os.path.join(_REPO, name)
        if os.path.isfile(p) and (name.endswith(".py")
                                  or name in ("README.md", "pyproject.toml", "package.json")):
            shutil.copy2(p, os.path.join(dst, name))
    return dst


def _run_in(tree):
    import subprocess
    env = dict(os.environ)
    env["PYTHONPATH"] = tree
    env["PYTHONUTF8"] = "1"
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env.pop("MDCG_INGEST_ROOT", None)
    pr = subprocess.run([sys.executable, "-X", "utf8", "-m",
                         "md_cg.test_issue351_ingest_root_fallback"],
                        capture_output=True, text=True, encoding="utf-8",
                        errors="replace", cwd=tree, env=env, timeout=1200)
    out = (pr.stdout or "") + (pr.stderr or "")
    reds = [ln.split("FAIL ", 1)[1].strip()
            for ln in out.splitlines() if "FAIL " in ln]
    return pr.returncode, reds, out


def _mutate():
    print("!! 定点变异自证：把判据改回改动前形态，守卫必须转红")
    tree = _mirror_build()
    try:
        rc, reds, out = _run_in(tree)
        print("  未变异镜像基线：rc=%d 红项=%d（必须 rc=0 且 0 红）" % (rc, len(reds)))
        if rc != 0 or reds:
            print(chr(10).join(out.splitlines()[-25:]))
        ok, bad = 0, []
        for desc, rel, old, new, exp in _MUTATIONS:
            p = os.path.join(tree, rel)
            raw = open(p, "rb").read()
            # 锚点按 \n 构造，目标文件可能是 CRLF——按文件实际行尾折算后再比对。
            _nl = "\r\n" if b"\r\n" in raw[:8192] else "\n"
            t = raw.decode("utf-8")
            old = old.replace("\n", _nl)
            new = new.replace("\n", _nl)
            if t.count(old) != 1:
                bad.append("%s —— 锚点命中 %d 次" % (desc, t.count(old)))
                print("  ANCHOR-MISS " + desc)
                continue
            bak = t
            open(p, "w", encoding="utf-8", newline="").write(t.replace(old, new, 1))
            rc2, reds2, out2 = _run_in(tree)
            open(p, "w", encoding="utf-8", newline="").write(bak)
            hit = [r for r in reds2 if r.startswith(exp)]
            if rc2 != 0 and len(hit) == len(exp):
                ok += 1
                print("  OK   %s  红项=%d 指定命中=%d/%d"
                      % (desc, len(reds2), len(hit), len(exp)))
            else:
                bad.append(desc)
                print("  MISMATCH %s  红项=%d 指定命中=%d/%d rc=%d"
                      % (desc, len(reds2), len(hit), len(exp), rc2))
                for r in reds2[:8]:
                    print("        FAIL " + r)
        print("定点变异自证：%s（%d 条不合格）"
              % ("PASS" if not bad else "FAIL", len(bad)))
        for b in bad:
            print("  不合格：" + b)
    finally:
        shutil.rmtree(tree, ignore_errors=True)


def main():
    if "--mutate" in sys.argv:
        _mutate()
    return 0 if not FAILS else 1


if __name__ == "__main__":
    sys.exit(main())