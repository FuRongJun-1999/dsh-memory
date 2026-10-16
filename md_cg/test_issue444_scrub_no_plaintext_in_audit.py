# -*- coding: utf-8 -*-
# 功能名：scrub 矛盾证据串不得携带正文原文（issue #444）
# 生效条件：python -X utf8 -m md_cg.test_issue444_scrub_no_plaintext_in_audit [--mutate]；被测面=md_cg/scrub.py 的 _contradiction 两个 why 构造（同键不同值 / 极性相反且共享内容）
# 子功能：A 组=private 正文标记不得落任何明文面（①_trust.jsonl ②internal 节点 md 与低 clearance 读回 ③private 节点 md ④报告串 ⑤全库扫描）；K 组=internal↔internal 矛盾照常处置 + 极性相反分支只留计数 + 密级闸对照 + 指纹可比对；E 组=单点（原值直拼与词面 join 不得回到 _contradiction）
# 执行：--mutate 时把 why 改回修前形态（正文原值直拼 / bigram 词面 join），守卫必须转红并点名
# 验证方式：全部 PASS 即通过；--mutate 下变异的「指定命中」须与预期一致（不多不少）
# 不适用条件：不判 export_* 显式导出面（issue 明示不主张）；不判 sweep/sustain/工具面调度（与 decontaminate 同一 _weaken 单点）；不判 expired/not_yet 等 fm 值证据（fm 本就是明文面，非正文）；不覆盖 secret 档（机制同一）
"""issue #444 守卫：_contradiction 的 why 拼正文原值 ⇒ private 正文进明文审计面。

病象（修前）：同键不同值的 why =「键=本端原值 vs 对端原值」，经 audit detail →
_weaken → verify 的 evidence 落进**两个**节点的 frontmatter 与 _trust.jsonl
（fm 加密只作用于正文，两处都是明文面）；scrub 双方各判一次，private 节点正文
由此被写进 internal 对端节点——internal 身份合规读对端（get 拿得到）即取回
private 正文（密级闸本身没坏：get(priv1) 恒 None）。极性相反分支把共享
bigram 词面写进 why，同族。修后：why 只留键名 + sha1 前 8 位不可逆指纹
（同键不同值）/ 只留计数（极性相反且共享内容）——记「谁处置了谁」，
不复制被处置内容。
"""
import os
import re
import shutil
import sys
import tempfile

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _REPO)
_TMP = tempfile.mkdtemp(prefix="iss444_")
os.environ.update({"MDCG_ROOT": _TMP + "/brainroot", "MDCG_STATE_ROOT": _TMP + "/state",
                   "MDCG_AUX_ROOT": _TMP + "/auxstore",
                   "MDCG_DATA_ROOT": _TMP + "/datastore", "MDCG_EXPORT_ROOT": _TMP,
                   "MDCG_SUSTAIN": "0", "MDCG_SLEEP": "0",
                   "MDCG_MASTER_KEY": "dd" * 32})
from md_cg.mdcos import MdCGSecure  # noqa: E402
from md_cg.security import Principal  # noqa: E402
from md_cg import scrub  # noqa: E402

_MARK = "PLAINSEC7F3A9Q2"
_FAILS = []


def _check(name, cond, detail=""):
    if cond:
        print("  PASS " + name)
    else:
        print("  FAIL " + name + "  " + str(detail)[:200])
        _FAILS.append(name)


def _designer(sub):
    root = os.path.join(_TMP, sub)
    return MdCGSecure(root,
                      principal=Principal(role="designer", clearance="private",
                                          can_write=True, can_admin=True),
                      autoflush=1)


def _reader(sub):
    """低 clearance 身份（issue ③：role=record / internal / 非管理员）。"""
    return MdCGSecure(os.path.join(_TMP, sub),
                      principal=Principal(role="record", clearance="internal",
                                          can_write=False, can_admin=False),
                      autoflush=1)


def _read(p):
    try:
        return open(p, "r", encoding="utf-8", errors="replace").read()
    except OSError:
        return ""


def _node_path(cg, nid):
    return os.path.join(cg.root, cg.index["nodes"][nid]["path"])


# ---------------------------------------------------------------- A 组场景
print("== A 组：private 正文不得落任何明文面 ==")
_cg = _designer("brainA")
_cg.add("pub1", "# 功能名：口令\n# 执行：set\n\n正文：公开内容 与私密无关",
        layer="contextual", sensitivity="internal")
_cg.add("priv1", "# 功能名：口令\n# 执行：set\n\n正文：绝密口令 " + _MARK
        + " 只应存在于密文里", layer="contextual", sensitivity="private")

_rep = scrub.audit(_cg, ["pub1", "priv1"])            # 只读体检面（报告串）
_dec = scrub.decontaminate(_cg, ["pub1", "priv1"], dry_run=False)

_fm_txt = {n: _read(_node_path(_cg, n)) for n in ("pub1", "priv1")}
_trust_txt = _read(os.path.join(_cg.root, "_trust.jsonl"))
_details = ([i.get("detail") for i in _rep["issues"]]
            + [a.get("detail") for a in _dec["actions"]])
_hits = []
for _dp, _ds, _fs in os.walk(_TMP + "/brainA"):
    for _fn in _fs:
        if _MARK in _read(os.path.join(_dp, _fn)):
            _hits.append(os.path.relpath(os.path.join(_dp, _fn), _cg.root))

_check("A0 前提：矛盾双方都被处置且证据确实落盘（非空转）",
       _dec["applied"] >= 2
       and "scrub:contradiction:" in _fm_txt["pub1"]
       and "scrub:contradiction:" in _trust_txt,
       {"applied": _dec["applied"], "trust": _trust_txt[-160:]})
_check("A1 修复点①：_trust.jsonl 不含 private 正文标记",
       _MARK not in _trust_txt, _trust_txt[-200:])
_check("A2 修复点②a：internal 节点 .md 不含标记",
       _MARK not in _fm_txt["pub1"], _fm_txt["pub1"][-200:])
_check("A3 修复点③：private 节点 .md（密文面）不含标记",
       _MARK not in _fm_txt["priv1"], _fm_txt["priv1"][-200:])
_node = _reader("brainA").get("pub1")                 # 合规读 internal 节点
_check("A4 修复点②b：低 clearance 身份 get(pub1) 返回体不含标记",
       _node is not None and _MARK not in repr(_node),
       repr(_node)[-200:] if _node else "None")
_check("A5 修复点④：报告串（audit issues / decontaminate actions）不含标记",
       all(_MARK not in (d or "") for d in _details), _details)
_check("A6 全库扫描：库根内零明文落点", not _hits, _hits)

# ---------------------------------------------------------------- K 组对照
print("== K 组：非恒真对照（不误伤） ==")
_cg2 = _designer("brainK1")
_cg2.add("i1", "# 功能名：口径\n# 执行：set\n\n正文：公开甲 一号口径",
         layer="contextual", sensitivity="internal")
_cg2.add("i2", "# 功能名：口径\n# 执行：set\n\n正文：公开乙 二号口径",
         layer="contextual", sensitivity="internal")
_dec2 = scrub.decontaminate(_cg2, ["i1", "i2"], dry_run=False)
_det2 = [a.get("detail") for a in _dec2["actions"]]
_check("K1 internal↔internal 矛盾照常处置，判据仍可解释（键名+指纹）",
       _dec2["applied"] >= 2 and _det2
       and all(d and "正文" in d and re.search(r"[0-9a-f]{8}", d)
               for d in _det2 if d is not None)
       and all("公开甲" not in (d or "") and "公开乙" not in (d or "")
               for d in _det2),
       _det2)

_cg3 = _designer("brainK2")
_cg3.add("p1", "发布前应当跑全量回归 黑名单接口一律走灰度发布通道甲",
         layer="contextual", sensitivity="internal")
_cg3.add("p2", "发布前禁止跑全量回归 黑名单接口一律走灰度发布通道乙",
         layer="contextual", sensitivity="internal")
_rep3 = scrub.audit(_cg3, ["p1", "p2"])
_pol = [i.get("detail") for i in _rep3["issues"]
        if i["kind"] == "contradiction" and i.get("detail")
        and "极性相反" in (i.get("detail") or "")]
_check("K2 极性相反分支仍命中且 why 只留计数（共享 bigram/重合率）",
       bool(_pol) and all("共享 bigram" in d and "重合率" in d for d in _pol),
       [i.get("detail") for i in _rep3["issues"]])
_check("K2b 极性相反 why 不含正文词面（4 字以上不可复原自 bigram join）",
       all("黑名单接口" not in d and "全量回归" not in d for d in _pol), _pol)

_check("K3 密级闸对照：internal 身份读 private 节点恒 None（闸本身正常）",
       _reader("brainA").get("priv1") is None)
_fp = scrub._fp
_check("K4 指纹可比对：同值同指纹 / 异值异指纹 / 定长 8 位十六进制",
       _fp("甲") == _fp("甲") and _fp("甲") != _fp("乙")
       and re.fullmatch(r"[0-9a-f]{8}", _fp("甲")) is not None, _fp("甲"))

# ---------------------------------------------------------------- E 组单点
print("== E 组：单点 ==")
_src = __import__("inspect").getsource(scrub._contradiction)
_check("E1 _contradiction 两侧值均走 _fp 指纹单点",
       "_fp(kv_a[k])" in _src and "_fp(kv_b[k])" in _src)
_check("E2 原值直拼形态（{kv_a[k]}…）不得回到 _contradiction",
       "kv_a[k]}" not in _src and "kv_b[k]}" not in _src)
_check("E3 共享 bigram 词面 join 不得回到 _contradiction",
       '、".join' not in _src)

for _c in (_cg, _cg2, _cg3):
    _c.close()
shutil.rmtree(_TMP, ignore_errors=True)

print("")
if _FAILS:
    print("issue #444 结果：%d 失败" % len(_FAILS))
else:
    print("issue #444 结果：全部通过")

# ---------------------------------------------------------------- 定点变异
# 锚点按换行符构造，_mutate 里按目标文件实际行尾折算。
_MUTATIONS = (
    ("V1 同键不同值 why 改回正文原值直拼（回到 #444 修前）",
     "md_cg/scrub.py",
     '                        "why": f"同键不同值：{k}"' + chr(10)
     + '                               f"（本端 {_fp(kv_a[k])} / 对端 {_fp(kv_b[k])}）"}',
     '                        "why": f"同键不同值：{k}={kv_a[k]} vs {kv_b[k]}"}',
     ("A1", "A2", "A3", "A4", "A5", "A6", "K1", "E1", "E2")),
    ("V2 极性相反 why 改回共享 bigram 词面（回到 #444 修前）",
     "md_cg/scrub.py",
     '                        "why": f"极性相反且共享内容：共享 bigram {len(shared)} 个"'
     + chr(10) + '                               f" / 重合率 {ratio:.0%}"}',
     '                        "why": "极性相反且共享内容：" + "、".join(' + chr(10)
     + '                            sorted(shared)[:5])}',
     ("K2", "E3")),
)


def _mirror_build():
    dst = tempfile.mkdtemp(prefix="iss444_mut_")
    for name in ("md_cg", "scripts"):
        src = os.path.join(_REPO, name)
        if os.path.isdir(src):
            shutil.copytree(src, os.path.join(dst, name),
                            ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    for name in sorted(os.listdir(_REPO)):
        p = os.path.join(_REPO, name)
        if os.path.isfile(p) and (name.endswith(".py")
                                  or name in ("README.md", "pyproject.toml",
                                              "package.json")):
            shutil.copy2(p, os.path.join(dst, name))
    return dst


def _run_in(tree):
    import subprocess
    env = dict(os.environ)
    env["PYTHONPATH"] = tree
    env["PYTHONUTF8"] = "1"
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    pr = subprocess.run([sys.executable, "-X", "utf8", "-m",
                         "md_cg.test_issue444_scrub_no_plaintext_in_audit"],
                        capture_output=True, text=True, encoding="utf-8",
                        errors="replace", cwd=tree, env=env, timeout=1200)
    out = (pr.stdout or "") + (pr.stderr or "")
    reds = [ln.split("FAIL ", 1)[1].strip()
            for ln in out.splitlines() if "FAIL " in ln]
    return pr.returncode, reds, out


def _mutate():
    print("!! 定点变异自证：把 why 改回改动前形态，守卫必须转红")
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
            if rc2 != 0 and len(hit) == len(exp) and len(hit) == len(reds2):
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
    return 0 if not _FAILS else 1


if __name__ == "__main__":
    sys.exit(main())
