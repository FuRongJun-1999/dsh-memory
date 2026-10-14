# -*- coding: utf-8 -*-
# 功能名：imgskill 幂等复用面（_find_reuse）不得信任台账里的 output_path（issue #325）
# 生效条件：python -X utf8 -m md_cg.test_issue325_audit_poison [--mutate]；被测面=md_cg/imgskill.py 的 _find_reuse
# 子功能：A 组=投毒台账不得被复用（.. 穿越 / 绝对路径 / 混合三种形态）+ 坏条目不得让整表拒服务；K 组=合法台账仍复用（判据非恒真）
# 执行：--mutate 时逐条把判据改回改动前形态，守卫必须转红（定点变异自证）
# 验证方式：全部 PASS 即通过；--mutate 下每条变异的「指定命中」须与预期一致
# 不适用条件：不判台账完整性（HMAC/签名，属纵深防御）；不判台账落点搬迁；不覆盖 POSIX 腿
"""issue #325 守卫：台账是沙箱根内**可写**的，其 output_path 必须过 safe_join。

病象（修前）：_find_reuse 从 .imgskill/audit.jsonl 取 output_path 后直接
os.path.join(root, ...)，未过 safe_join。投毒台账（一次 open+write、零 imgskill
调用）即可让复用面读到沙箱根外任意可读文件、把它的完整 SHA-256 回带出去。

判据方向：A 组要求「越界条目一律不复用」，K 组要求「合法条目仍复用、坏条目
不影响后续好条目」——两侧同时成立才说明处置是「跳过该条」而不是「整表拒服务」
或「什么都放行」。
"""
import hashlib
import inspect
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

_Q = chr(34)
_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _REPO)
from md_cg import imgskill as _ik  # noqa: E402

FAILS = []


def _check(name, cond, detail=""):
    if cond:
        print("  PASS " + name)
    else:
        print("  FAIL " + name + "  " + str(detail)[:200])
        FAILS.append(name)


def _sha(b):
    return hashlib.sha256(b).hexdigest()


_TMP = tempfile.mkdtemp(prefix="iss325_")
ROOT = os.path.join(_TMP, "sandbox")
OUT = os.path.join(_TMP, "outside")
os.makedirs(ROOT)
os.makedirs(os.path.join(ROOT, "out"))
os.makedirs(OUT)
_SECRET = b"SECRET-OUTSIDE-CONTENT-325" + bytes([10])
open(os.path.join(OUT, "secret.bin"), "wb").write(_SECRET)
_OKBODY = b"legit-artifact" + bytes([10])
open(os.path.join(ROOT, "out", "ok.bin"), "wb").write(_OKBODY)

KEY = "k325"
OP = "resize"
INSHA = "a" * 64
NP = {}
_TRAV = ".." + os.sep + "outside" + os.sep + "secret.bin"
_MIX = "." + os.sep + ".." + os.sep + "outside" + os.sep + "secret.bin"
_ABS = os.path.join(OUT, "secret.bin")


def _rec(out_path, out_sha):
    return {"idempotency_key": KEY, "ok": True, "op": OP,
            "input_sha256": INSHA, "params": NP,
            "output_path": out_path, "output_sha256": out_sha}


def _write_ledger(recs):
    p = _ik.audit_path(ROOT)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with io.open(p, "w", encoding="utf-8", newline="") as f:
        for r in recs:
            f.write(json.dumps(r, ensure_ascii=False) + chr(10))


def _find():
    try:
        return _ik._find_reuse(ROOT, KEY, OP, INSHA, NP)
    except Exception as e:                      # noqa: BLE001
        return "EXC:" + type(e).__name__ + ":" + str(e)[:60]


_LEGIT = _rec("out/ok.bin", _sha(_OKBODY))
_POISON = _rec(_TRAV, _sha(_SECRET))

print("== K 组：合法台账仍复用（判据非恒真 / 不误伤）==")
_write_ledger([_LEGIT])
_k1 = _find()
_check("K1 合法台账（根内产物、哈希相符）→ 仍复用",
       isinstance(_k1, dict) and _k1.get("output_path") == "out/ok.bin", _k1)
_write_ledger([_rec("out/ok.bin", "0" * 64)])
_k2 = _find()
_check("K2 哈希不符 → 不复用（既有判据未丢）", _k2 is None, _k2)

print("== A 组：投毒台账一律不复用 ==")
_trav = (("A1 .. 穿越", _TRAV), ("A2 绝对路径", _ABS), ("A3 混合形态", _MIX))
for _name, _path in _trav:
    _write_ledger([_rec(_path, _sha(_SECRET))])
    _got = _find()
    _check(_name + " → 不复用（返回 None，不是异常也不是命中）", _got is None, _got)

print("== A 组（续）：坏条目不得让整表拒服务 ==")
_write_ledger([_LEGIT, _POISON])
_a4 = _find()
_check("A4 投毒条目排在**最后**（先被遍历）时，前面的合法条目仍可复用",
       isinstance(_a4, dict) and _a4.get("output_path") == "out/ok.bin", _a4)

print("== E 组：单点 ==")
_src = inspect.getsource(_ik._find_reuse)
_check("E1 _find_reuse 体内对台账 output_path 调用了 safe_join",
       "safe_join(" in _src, [l for l in _src.splitlines() if "output_path" in l][:3])
_check("E2 越界处置是 continue（跳过该条）而非 raise（整表拒服务）",
       "continue" in _src, [l for l in _src.splitlines() if "continue" in l][:2])

shutil.rmtree(_TMP, ignore_errors=True)

print("")
if FAILS:
    print("issue #325 结果：%d 失败" % len(FAILS))
else:
    print("issue #325 结果：全部通过")

# ------------------------------------------------------------------ 定点变异
# 锚点一律用 chr(34) 拼引号，避免转义层级；每条的「期望红项」= 该变异真正打掉的判据。
_A_JOIN = (chr(10) + "                p = safe_join(root, rec[" + _Q + "output_path" + _Q + "],"
           + chr(10) + "                              what=" + _Q + "audit.output_path" + _Q + ")")
_A_PLAIN = chr(10) + "                p = os.path.join(root, rec[" + _Q + "output_path" + _Q + "])"
_E_CONT = chr(10) + "            except SkillError:" + chr(10) + "                continue"
_E_RAISE = chr(10) + "            except SkillError:" + chr(10) + "                raise"
_E_TRY = (chr(10) + "            try:" + chr(10) + _A_JOIN.lstrip(chr(10)) + chr(10)
          + "            except SkillError:" + chr(10) + "                continue")
_E_ABS = (chr(10) + "            if os.path.isabs(rec[" + _Q + "output_path" + _Q + "]):"
          + chr(10) + "                continue" + chr(10) + _A_PLAIN.lstrip(chr(10)))

_MUTATIONS = (
    ("V1 抽掉 safe_join（回到 os.path.join，即 #325 修前）",
     "md_cg/imgskill.py", _A_JOIN, _A_PLAIN, ("A1", "A2", "A3")),
    ("V2 越界条目 raise 而非 continue（坏条目让整次 run 失败）",
     "md_cg/imgskill.py", _E_CONT, _E_RAISE, ("A4",)),
    ("V3 只对绝对路径设防（.. 穿越与混合形态照旧放行）",
     "md_cg/imgskill.py", _E_TRY, _E_ABS, ("A1", "A3")),
)


def _mirror_build():
    dst = tempfile.mkdtemp(prefix="iss325_mut_")
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
    env = dict(os.environ)
    env["PYTHONPATH"] = tree
    env["PYTHONUTF8"] = "1"
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    pr = subprocess.run([sys.executable, "-X", "utf8", "-m",
                         "md_cg.test_issue325_audit_poison"],
                        capture_output=True, text=True, encoding="utf-8",
                        errors="replace", cwd=tree, env=env, timeout=1200)
    out = (pr.stdout or "") + (pr.stderr or "")
    reds = [ln.split("FAIL ", 1)[1].strip()
            for ln in out.splitlines() if "FAIL " in ln]
    return pr.returncode, reds, out


def _mutate():
    print("!! 定点变异自证：逐条把判据改回改动前形态，守卫必须转红")
    tree = _mirror_build()
    try:
        rc, reds, out = _run_in(tree)
        print("  未变异镜像基线：rc=%d 红项=%d（必须 rc=0 且 0 红）" % (rc, len(reds)))
        if rc != 0 or reds:
            print(chr(10).join(out.splitlines()[-25:]))
        ok, bad = 0, []
        for desc, rel, old, new, exp in _MUTATIONS:
            p = os.path.join(tree, rel)
            t = open(p, encoding="utf-8", newline="").read()
            if t.count(old) != 1:
                bad.append("%s —— 锚点在 %s 命中 %d 次" % (desc, rel, t.count(old)))
                print("  ANCHOR-MISS " + desc)
                continue
            bak = t
            open(p, "w", encoding="utf-8", newline="").write(t.replace(old, new, 1))
            for root, dd, ff in os.walk(tree):
                if os.path.basename(root) == "__pycache__":
                    shutil.rmtree(root, ignore_errors=True)
            rc2, reds2, out2 = _run_in(tree)
            open(p, "w", encoding="utf-8", newline="").write(bak)
            hit = [r for r in reds2 if r.startswith(exp)]
            if rc2 != 0 and len(hit) == len(exp):
                ok += 1
                print("  OK   %s  红项=%d 指定命中=%d/%d" % (desc, len(reds2), len(hit), len(exp)))
            else:
                bad.append(desc)
                print("  MISMATCH %s  红项=%d 指定命中=%d/%d rc=%d"
                      % (desc, len(reds2), len(hit), len(exp), rc2))
                for r in reds2[:8]:
                    print("        FAIL " + r)
        print("定点变异自证：%s（%d 条不合格）" % ("PASS" if not bad else "FAIL", len(bad)))
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