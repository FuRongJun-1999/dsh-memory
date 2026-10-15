# -*- coding: utf-8 -*-
# 功能名：tidy_contextual 不得把更高密级成员的正文摘录写进保留节点（issue #360）
# 生效条件：python -X utf8 -m md_cg.test_issue360_tidy_private_excerpt [--mutate]；被测面=md_cg/writelimit.py 的 tidy_contextual 成员循环
# 子功能：A 组=private 成员正文不得进保留节点；K 组=同档成员摘录照常写（不误伤）+ 未记录密级成员行为不变
# 执行：--mutate 时摘掉 merge_downgrades 跳过判据（即 #360 修前），守卫必须转红
# 验证方式：全部 PASS 即通过；--mutate 下变异的「指定命中」须与预期一致
# 不适用条件：不判 _demote 的降级语义；不判 sustain auto_tidy 调度（只判库层单点）；不覆盖 POSIX 腿
"""issue #360 守卫：整理不看成员密级 ⇒ private 正文前 48 字明文进 internal 保留节点。

病象（修前）：同组 contextual 节点里只要有一条 private，tidy 会把它解密后的正文
前 48 字以明文追加进组内最早的保留节点（密级沿用保留节点的 internal）——internal
身份直接 get 那条 private 节点得到 None，但读保留节点就能看到其内容。sustain 缺省
auto_tidy=True，无需人工触发。
"""
import os
import shutil
import sys
import tempfile

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _REPO)
_TMP = tempfile.mkdtemp(prefix="iss360_")
os.environ.update({"MDCG_ROOT": _TMP + "/brainroot", "MDCG_STATE_ROOT": _TMP + "/state",
                   "MDCG_AUX_ROOT": _TMP + "/auxstore",
                   "MDCG_DATA_ROOT": _TMP + "/datastore", "MDCG_EXPORT_ROOT": _TMP,
                   "MDCG_SUSTAIN": "0", "MDCG_SLEEP": "0",
                   "MDCG_MASTER_KEY": "aa" * 32})
from md_cg.mdcos import MdCGSecure  # noqa: E402
from md_cg.security import Principal  # noqa: E402
from md_cg import writelimit as _wl  # noqa: E402

_SECRET = "门禁口令已更新为 7319846"
FAILS = []


def _check(name, cond, detail=""):
    if cond:
        print("  PASS " + name)
    else:
        print("  FAIL " + name + "  " + str(detail)[:200])
        FAILS.append(name)


def _mk():
    return MdCGSecure(_TMP + "/brainroot",
                      principal=Principal(role="designer", clearance="private",
                                          can_write=True, can_admin=True),
                      autoflush=1)


print("== 前提 ==")
_cg = _mk()
# 三条同签名（同模板、仅数字不同）的 contextual 节点，第三条 private
_cg.add("n1", "# 功能名：门禁口令已更新为 1111111", layer="contextual",
        sensitivity="internal")
_cg.add("n2", "# 功能名：门禁口令已更新为 2222222", layer="contextual",
        sensitivity="internal")
_cg.add("n3", "# 功能名：" + _SECRET, layer="contextual",
        sensitivity="private")
_sig = _wl.template_signature("# 功能名：门禁口令已更新为 1111111")
_check("P1 前提：三条成员同签名（会被分到一组）",
       bool(_sig) and _sig == _wl.template_signature("# 功能名：" + _SECRET),
       _sig)

print("== A 组：private 成员正文不得进保留节点 ==")
_out = _wl.tidy_contextual(_cg, apply=True, min_group=3)
_check("A1 前提：tidy 确实应用了（有 applied 组）",
       bool(_out.get("applied")), _out)
_keep_id = (_out["applied"][0]["keep"] if _out.get("applied") else "n1")
_keep = _cg.get(_keep_id) or {}
_ktxt = _keep.get("content") or ""
_check("A2 修复点：保留节点正文**不含** private 成员的正文片段",
       "7319846" not in _ktxt, _ktxt[-160:])
_check("A3 保留节点密级仍为 internal（未被抬高，也未被污染）",
       (_keep.get("frontmatter") or {}).get("sensitivity") == "internal",
       (_keep.get("frontmatter") or {}).get("sensitivity"))

print("== K 组：非恒真对照 ==")
_check("K1 同档（internal）成员的摘录**照常**写入（不误伤）",
       "1111111" in _ktxt or "2222222" in _ktxt, _ktxt[-200:])
_n3 = _cg.get("n3") or {}
_check("K2 private 成员未被跳过式降级（正文仍在、可被属主读回）",
       "7319846" in (_n3.get("content") or ""),
       (_n3.get("content") or "")[:40])

print("== E 组：单点 ==")
_src = __import__("inspect").getsource(_wl.tidy_contextual)
_check("E1 tidy_contextual 体内复用 merge_downgrades 单点",
       "merge_downgrades" in _src, [l for l in _src.splitlines()
                                    if "merge_downgrades" in l][:2])

_cg.close()
shutil.rmtree(_TMP, ignore_errors=True)

print("")
if FAILS:
    print("issue #360 结果：%d 失败" % len(FAILS))
else:
    print("issue #360 结果：全部通过")

# ------------------------------------------------------------------ 定点变异
# 锚点按换行符构造，_mutate 里按目标文件实际行尾折算。
_MUTATIONS = (
    ("V1 摘掉密级跳过判据（回到 #360 修前：private 摘录照写）",
     "md_cg/writelimit.py",
     "            if _md360(_ksens, mfm.get(\"sensitivity\")):" + chr(10)
     + "                continue" + chr(10),
     "",
     ("A2",)),
)


def _mirror_build():
    dst = tempfile.mkdtemp(prefix="iss360_mut_")
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
    pr = subprocess.run([sys.executable, "-X", "utf8", "-m",
                         "md_cg.test_issue360_tidy_private_excerpt"],
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