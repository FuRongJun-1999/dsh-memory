# -*- coding: utf-8 -*-
# 功能名：scrub 的矛盾证据串不得携带正文原文/词面（issue #444，P0 密级泄漏）
# 生效条件：python -u -X utf8 -m md_cg.test_issue444_scrub_evidence_plaintext [--mutate]；被测面＝md_cg/scrub.py 的 _contradiction（两支产串）+ _weaken（用串落盘）
# 子功能：A 组＝正向腿（证据串只含键名+不可逆摘要；四类明文面均不含 private 正文标记；工具面 internal 身份读不到）；K 组＝反向腿①（internal↔internal 的矛盾仍被正常处置，防一刀切）；E 组＝源码面（两支判据在位）；M 组＝反向腿②（--mutate，红项严格相等且不重叠）
# 执行：--mutate 时在镜像树里逐条把判据改回缺陷形态，守卫必须按指定项转红
# 验证方式：全部 PASS 即通过（退出码 0）；--mutate 下每条变异的红项集合须与预期逐项相符，锚点未命中即 fail-closed
# 不适用条件：① 腿看不见「该不该把这对节点判为矛盾」——只看见「证据串里有没有正文原文/词面」；② 不覆盖 verify 证据原文经**其它**通道的落点（#348-C 的未决口径，另一件）；③ 不覆盖 scrub 其它 add(...) 支的 detail（expired/not_yet 传的是键名与日期类短值，**不含正文**；如需一律摘要化属另一件）；④ 本腿的 fixture 走「同键不同值」支；「极性相反」支只做**源码面**断言（不在本腿构造极性语料——避免把两条判据混成一条）。
"""issue #444 守卫：矛盾证据串不得携带正文原文（P0：private 正文进明文面）。

病象（修前）：`_contradiction` 把**两端正文原值**（同键不同值）或**共享 bigram 词面**
（极性相反）拼进 `why`；该串经 `add("contradiction", why)` → `_weaken` → `cg.verify(...,
"weakened")` 成为 verify 的 **evidence**，落进 (a) 节点 frontmatter、(b) 对端节点自己的 .md、
(c) `_trust.jsonl` —— 三处都是**明文面**（加密只作用于正文）⇒ `internal` 身份经 `mdcg_get`
即可读到 private 正文。
修法：正文原值与词面一律不进证据串——只留**键名 + 不可逆摘要（8 位）**（同键支）与
**计数 + 占比**（极性支）。
"""
from __future__ import annotations

import ast
import os
import shutil
import subprocess
import sys
import tempfile

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO not in sys.path:
    sys.path.insert(0, _REPO)

_TMP = tempfile.mkdtemp(prefix="iss444_")
os.environ.update({"MDCG_ROOT": _TMP + "/brain", "MDCG_STATE_ROOT": _TMP + "/state",
                   "MDCG_AUX_ROOT": _TMP + "/auxstore", "MDCG_DATA_ROOT": _TMP + "/datastore",
                   "MDCG_EXPORT_ROOT": _TMP, "MDCG_SUSTAIN": "0", "MDCG_SLEEP": "0"})
os.environ.pop("MDCG_READ_CACHE", None)

from md_cg import mcp_server as _ms                   # noqa: E402
from md_cg import scrub as _sc                        # noqa: E402
from md_cg import tokens as _tk                       # noqa: E402
from md_cg.mdcos import MdCGSecure                    # noqa: E402
from md_cg.security import Principal                  # noqa: E402

PASSED, FAILS = [], []
MARK = "MARK444X7Q2"                     # 只在 private 正文里出现的唯一标记
KEY = "口令"                             # 非 CCG 标记键（_kv_pairs 只抽 2–12 字的非结构键）


def _check(name, cond, detail=""):
    if cond:
        print("  PASS " + name)
        PASSED.append(name)
    else:
        print("  FAIL " + name + "  " + str(detail)[:240])
        FAILS.append(name)


def _mk(role, clearance):
    sp = _tk.role_spec(role)
    return Principal(clearance=clearance, can_write=sp["can_write"], can_admin=sp["can_admin"],
                     role=role, layers_allow=sp["layers_allow"], ops_allow=sp["ops_allow"])


def _cg(root, role="designer", clearance="secret"):
    return MdCGSecure(root, principal=_mk(role, clearance), autoflush=1)


def _raw(root, rel):
    with open(os.path.join(root, rel), encoding="utf-8", errors="replace") as f:
        return f.read()


def _build(root):
    """private 节点 + internal 矛盾对端（同键不同值 ⇒ 走 _contradiction 第一支）。"""
    cg = _cg(root)
    cg.add("priv1", "# 功能名：私密记录" + chr(10) + KEY + "：" + MARK + chr(10)
           + "# 不适用条件：无", layer="contextual", sensitivity="private")
    cg.add("pub1", "# 功能名：公开记录" + chr(10) + KEY + "：公开内容无关" + chr(10)
           + "# 不适用条件：无", layer="contextual", sensitivity="internal")
    cg.flush()
    return cg


def group_a(tmp):
    print("== A 组：正向腿——证据串不得携带 private 正文 ==")
    root = os.path.join(tmp, "a")
    cg = _build(root)
    priv = (cg.get("priv1") or {}).get("content") or ""
    bad = _sc._contradiction(cg, priv, [{"node_id": "pub1", "via": "same_family"}])
    _check("A1 前置：同键不同值被判为矛盾（对端可读）", bool(bad), "bad=%r" % (bad,))
    why = (bad or {}).get("why") or ""
    _check("A2 证据串不含正文原文（只有键名 + 不可逆摘要）",
           MARK not in why and KEY in why and "公开内容无关" not in why, "why=%r" % why)
    _sc._weaken(cg, "priv1", "contradiction", why)
    _sc._weaken(cg, "pub1", "contradiction", why)
    cg.flush()
    trust = _raw(root, "_trust.jsonl") if os.path.exists(os.path.join(root, "_trust.jsonl")) else ""
    _check("A3 _trust.jsonl 不含 private 正文标记", MARK not in trust, "hit=%s" % (MARK in trust))
    pub_rel = "contextual/pub1.md"
    pub_raw = _raw(root, pub_rel) if os.path.exists(os.path.join(root, pub_rel)) else ""
    _check("A4 对端 internal 节点 .md 不含 private 正文标记", MARK not in pub_raw)
    cg.close()
    reader = _cg(root, role="record", clearance="internal")
    g = _ms._cg_dispatch(reader, {"op": "read", "node_id": "pub1"})
    _check("A5 工具面：internal 身份读 internal 节点读不到 private 正文",
           MARK not in str(g), "体=%s" % str(g)[-80:])
    reader.close()
    priv_rel = "contextual/priv1.md"
    priv_raw = _raw(root, priv_rel) if os.path.exists(os.path.join(root, priv_rel)) else ""
    _check("A6 private 自身 .md 不含明文标记（密文面未退化）", MARK not in priv_raw)


def group_k(tmp):
    print("== K 组：反向腿①——同密级之间的矛盾仍被正常处置（防一刀切）==")
    root = os.path.join(tmp, "k")
    cg = _cg(root)
    cg.add("k_a", "# 功能名：甲" + chr(10) + KEY + "：三千" + chr(10) + "# 不适用条件：无",
           layer="contextual", sensitivity="internal")
    cg.add("k_b", "# 功能名：乙" + chr(10) + KEY + "：五千" + chr(10) + "# 不适用条件：无",
           layer="contextual", sensitivity="internal")
    cg.flush()
    content = (cg.get("k_a") or {}).get("content") or ""
    bad = _sc._contradiction(cg, content, [{"node_id": "k_b", "via": "same_family"}])
    _check("K1 同密级矛盾仍被判出（未因摘要化而失去判别力）",
           bool(bad) and KEY in ((bad or {}).get("why") or ""), "bad=%r" % (bad,))
    _sc._weaken(cg, "k_a", "contradiction", (bad or {}).get("why") or "")
    cg.flush()
    st = ((cg.get("k_a") or {}).get("frontmatter") or {}).get("verification_state")
    _check("K2 处置仍发生（节点验证态由 weakened 路径推进）",
           st in ("doubted", "weakened", "demoted", "unverified"), "state=%r" % st)
    cg.close()


def _src(rel):
    with open(os.path.join(_REPO, rel), encoding="utf-8") as f:
        return f.read()


def _contra_src():
    tree = ast.parse(_src("md_cg/scrub.py"), "scrub.py")
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "_contradiction":
            import ast as _a
            return _a.get_source_segment(_src("md_cg/scrub.py"), node) or ""
    return ""


def group_e(tmp):
    print("== E 组：源码面——两支判据在位 ==")
    seg = _contra_src()
    _check("E1a 同键支：产串用不可逆摘要（_h()），不再直接拼 {kv_a[k]}/{kv_b[k]}",
           "_h(" in seg and "={kv_a[k]}" not in seg and "vs {kv_b[k]}" not in seg)
    _check("E1b 极性支：不再拼共享词面（无 sorted(shared) 进串）",
           "sorted(shared)" not in seg and "共享片段" in seg)


def _guard_group(tag, fn, tmp):
    try:
        fn(tmp)
    except Exception as exc:                              # noqa: BLE001
        import traceback
        _check("%s0 组内异常（fail-closed：异常即红）" % tag, False,
               "%s: %s" % (type(exc).__name__, exc))
        traceback.print_exc()


def main():
    print("== #444 scrub 证据串明文面守卫 ==")
    _guard_group("A", group_a, _TMP)
    _guard_group("K", group_k, _TMP)
    _guard_group("E", group_e, _TMP)
    print("=" * 68)
    print("#444 守卫：%d 通过，%d 失败" % (len(PASSED), len(FAILS)))
    for f in FAILS:
        print("  红项：" + f)
    _bad = _mutate() if "--mutate" in sys.argv else 0
    return 1 if (FAILS or _bad) else 0


_MUTATIONS = (
    ("M1 同键支改回正文原值（回到 #444 缺陷形态）",
     "md_cg/scrub.py",
     (("        return hashlib.sha1(str(v).encode(\"utf-8\")).hexdigest()[:8]",
       "        return str(v)  # M1 撤摘要"),),
     ("A2", "A3", "A4", "A5", "A6")),
    ("M2 极性支改回共享词面",
     "md_cg/scrub.py",
     (("                        \"why\": f\"极性相反且共享内容：共享片段 {len(shared)} 个\"" + chr(10)
       + "                               f\"（占比 {ratio:.2f}），词面不入证据串\"}",
       "                        \"why\": \"极性相反且共享内容：\" + \"、\".join(sorted(shared)[:5])}"),),
     ("E1b",)),
)


def _mirror_build():
    dst = tempfile.mkdtemp(prefix="iss444_mut_")
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
                         "md_cg.test_issue444_scrub_evidence_plaintext"],
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
    print("!! 反向腿②：把两支判据改回缺陷形态，守卫必须按指定项转红")
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
