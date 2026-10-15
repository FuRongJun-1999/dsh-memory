# -*- coding: utf-8 -*-
# 功能名：加密档节点不得把「不适用条件」抽进明文 frontmatter 与 _index.json（issue #348-C）
# 生效条件：python -X utf8 -m md_cg.test_audit_20261015_b_private_na_plaintext [--mutate]；被测面=md_cg/mdcg.py 的 MdCG.add 抽取段与 MdCG.judge_qualification 的 REJECT 段
# 子功能：C 组=private/secret 节点盘面 fm 与 _index.json 均无条件原文；K 组=加密档 REJECT 语义仍在 + internal 照旧抽 + 访客仍读不到（非恒真对照）
# 执行：--mutate 时把 add 的抽取判据改回无条件、或摘掉 judge_qualification 的现抽，守卫必须转红
# 验证方式：全部 PASS 即通过；--mutate 下变异的「指定命中」须与预期一致
# 不适用条件：不判 verify 证据原文的落点（issue #348-C 后半段，等维护者选口径）；不判调用方**显式**传 non_applicable_conditions 的路径（那是调用方自己声明要明文存）；不判已有存量数据的迁移
"""issue #348-C 守卫：加密档节点的「不适用条件」被抽进明文 frontmatter 与索引。

病象（修前）：属主写一条带「# 不适用条件：」行的 private/secret 六要素记忆，正文按密级
密封了，但 MdCG.add 把这一行从**明文正文**里抽出来写进 frontmatter 的
non_applicable_conditions；frontmatter 恒为明文，rejection_index_terms 再把它切词写进
_index.json 的 rejection_terms。属主对 private 节点做读取、备份、打包时明文泄露。

MCP 读面无出口（访客 mdcg_get 回 not_found），所以只在盘面判：盘面 fm 与 _index.json。
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _REPO)
_TMP = tempfile.mkdtemp(prefix="iss348c_")
os.environ.update({"MDCG_ROOT": _TMP + "/brainroot", "MDCG_STATE_ROOT": _TMP + "/state",
                   "MDCG_AUX_ROOT": _TMP + "/auxstore",
                   "MDCG_DATA_ROOT": _TMP + "/datastore", "MDCG_EXPORT_ROOT": _TMP,
                   "MDCG_SUSTAIN": "0", "MDCG_SLEEP": "0",
                   "MDCG_MASTER_KEY": "aa" * 32})
from md_cg.mdcos import MdCGSecure  # noqa: E402
from md_cg.mdcg import MdCG  # noqa: E402
from md_cg.security import Principal  # noqa: E402
from md_cg import crypto as _crypto  # noqa: E402
from md_cg import nodefile as _nf  # noqa: E402

NA = "NAC_SECRET 住院精神科期间"
BODY = ("# 功能名：用药\n# 生效条件：每晚睡前\n# 子功能：提醒\n# 执行：服用舍曲林50mg\n"
        "# 验证方式：用户自述\n# 不适用条件：" + NA + "；孕期")
FAILS = []


def _check(name, cond, detail=""):
    if cond:
        print("  PASS " + name)
    else:
        print("  FAIL " + name + "  " + str(detail)[:300])
        FAILS.append(name)


def _mk(role="designer", clearance="secret"):
    return MdCGSecure(_TMP + "/brainroot",
                      principal=Principal(role=role, clearance=clearance,
                                          can_write=(role != "guest"),
                                          can_admin=(role == "designer")),
                      autoflush=1)


print("== P 组：前提 ==")
_cg = _mk()
_cg.add("na_priv", BODY, layer="knowledge", sensitivity="private")
_cg.add("na_sec", BODY, layer="knowledge", sensitivity="secret")
_cg.add("na_int", BODY, layer="knowledge", sensitivity="internal")
_cg.flush()
# _index.json 只在 compact 时固化（flush 只追加 _index_log 分片），
# 与 MCP 面收尾同口径：读盘面前先 compact。
_cg.compact_index()
_raw_p = open(os.path.join(_TMP, "brainroot", _cg.index["nodes"]["na_priv"]["path"]),
              encoding="utf-8").read()
_fm_p, _body_p = _nf.loads(_raw_p)
_check("P1 前提：private 节点正文在盘面已密封", _crypto.is_encrypted(_body_p),
       _body_p[:40])
_idx = open(os.path.join(_TMP, "brainroot", "_index.json"), encoding="utf-8").read()
_check("P2 前提：internal 对照节点的条件原文确实进了索引（说明索引面确实会落这一列）",
       NA.split()[0] in _idx, [ln for ln in _idx.splitlines() if "rejection" in ln][:2])

print("== C 组：加密档不得把条件原文抽进明文面 ==")
for _nid, _label in (("na_priv", "private"), ("na_sec", "secret")):
    _n = _cg.get(_nid) or {}
    _fm = _n.get("frontmatter") or {}
    _raw = open(os.path.join(_TMP, "brainroot", _cg.index["nodes"][_nid]["path"]),
                encoding="utf-8").read()
    _check("C1 %s 节点：fm.non_applicable_conditions 不落条件原文（盘面明文面）" % _label,
           not (_fm.get("non_applicable_conditions") or [])
           and "NAC_SECRET" not in _raw.split("\n---", 1)[0],
           _fm.get("non_applicable_conditions"))
# 按**条目**判（不按整份文件判）：同一库里 internal 对照节点的正文是明文，
# 它的 rejection_terms 本来就该含条件原文——整文件判会被对照组打红。
for _nid, _label in (("na_priv", "private"), ("na_sec", "secret")):
    _e = _cg.index["nodes"][_nid]
    _check("C2 %s 节点：索引条目不含条件原文（rejection_terms 面）" % _label,
           "NAC_SECRET" not in json.dumps(_e, ensure_ascii=False),
           _e.get("rejection_terms"))
_cg2 = _cg  # 同一身份复用；下面换一个只含 private 节点的隔离根，判整份 _index.json
_solo = MdCGSecure(_TMP + "/soloroot",
                   principal=Principal(role="designer", clearance="secret",
                                       can_write=True, can_admin=True), autoflush=1)
_solo.add("solo_priv", BODY, layer="knowledge", sensitivity="private")
_solo.flush()
_solo.compact_index()
_idx2 = open(os.path.join(_TMP, "soloroot", "_index.json"), encoding="utf-8").read()
_check("C3 只含一个 private 节点的库：_index.json 全文不含条件原文",
       "NAC_SECRET" not in _idx2,
       [ln for ln in _idx2.splitlines() if "rejection" in ln][:2])
_solo.close()

print("== K 组：非恒真对照 ==")
_priv = _cg.get("na_priv") or {}
_q = MdCG.judge_qualification({"frontmatter": _priv.get("frontmatter") or {},
                               "content": _priv.get("content") or ""},
                              "NAC_SECRET 住院精神科期间能吃舍曲林吗", None)
_check("KC1 private 节点读回后 judge_qualification 仍判 REJECT（现抽承接，语义未丢）",
       _q.get("state") == "REJECT", _q)
_int = _cg.get("na_int") or {}
_ifm = _int.get("frontmatter") or {}
_check("KC2 internal 节点照旧把条件抽进 fm（不误伤）",
       "NAC_SECRET" in "；".join(_ifm.get("non_applicable_conditions") or []),
       _ifm.get("non_applicable_conditions"))
_guest = _mk(role="guest", clearance="internal")
try:
    _g = _guest.get("na_priv")
except Exception as _e:                                    # noqa: BLE001
    _g = "RAISED:" + type(_e).__name__
_check("KC3 无写权访客仍读不到 private 节点（既有密级隔离不变）",
       _g is None or (isinstance(_g, str) and _g.startswith("RAISED:")), _g)
_guest.close()

print("== E 组：单点 ==")
_check("E1 写入抽取与资格现抽共用单点 _na_from_body",
       "_na_from_body" in MdCG.add.__code__.co_names
       and "_na_from_body" in MdCG.judge_qualification.__code__.co_names,
       (MdCG.add.__code__.co_names.count("_na_from_body"),
        MdCG.judge_qualification.__code__.co_names.count("_na_from_body")))

_cg.close()
shutil.rmtree(_TMP, ignore_errors=True)

print("")
if FAILS:
    print("issue #348-C 结果：%d 失败" % len(FAILS))
else:
    print("issue #348-C 结果：全部通过")

# ------------------------------------------------------------------ 定点变异
_MUTATIONS = (
    ("V1 把 add 的抽取判据改回无条件（回到 #348-C 修前）",
     "md_cg/mdcg.py",
     "        if (not fm.get(\"non_applicable_conditions\")" + chr(10)
     + "                and not _is_encrypted_level(fm.get(\"sensitivity\"))):" + chr(10),
     "        if not fm.get(\"non_applicable_conditions\"):" + chr(10),
     ("C1", "C2", "C3")),
    ("V2 摘掉 judge_qualification 的加密档现抽（REJECT 语义随明文落点一起消失）",
     "md_cg/mdcg.py",
     "        if not neg and _is_encrypted_level(fm.get(\"sensitivity\")):" + chr(10)
     + "            neg = _na_from_body(content)" + chr(10),
     "",
     # E1 断言「两处都走 _na_from_body」：现抽被摘掉时这条单点断言一并转红。
     ("E1", "KC1")),
)


def _mirror_build():
    dst = tempfile.mkdtemp(prefix="iss348c_mut_")
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
                         "md_cg.test_audit_20261015_b_private_na_plaintext"],
                        capture_output=True, text=True, encoding="utf-8",
                        errors="replace", cwd=tree, env=env, timeout=900)
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
            # 断言名可能多行同前缀（C1 有 private/secret 两条），故按**前缀集合**判命中。
            got = sorted({r.split(" ", 1)[0] for r in reds2})
            if rc2 != 0 and got == sorted(set(exp)):
                ok += 1
                print("  OK   %s  红项=%d 指定命中=%s" % (desc, len(reds2), got))
            else:
                bad.append(desc)
                print("  MISMATCH %s  红项=%d 期望前缀=%s 实得前缀=%s rc=%d"
                      % (desc, len(reds2), sorted(set(exp)), got, rc2))
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
