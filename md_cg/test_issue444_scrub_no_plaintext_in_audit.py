# -*- coding: utf-8 -*-
# 功能名：scrub 矛盾证据串不得携带正文原文与键名明文（issue #444 / #448 审①②③）
# 生效条件：python -X utf8 -m md_cg.test_issue444_scrub_no_plaintext_in_audit [--mutate]；被测面=md_cg/scrub.py 的 _contradiction 两个 why 构造（同键不同值 / 极性相反且共享内容）与 _fp/_fp_salt 指纹面
# 子功能：A 组=private 正文标记不得落任何明文面（①_trust.jsonl ②internal 节点 md 与低 clearance 读回 ③private 节点 md ④报告串 ⑤全库扫描）；K 组=internal↔internal 矛盾照常处置（键名+值均指纹）+ 极性相反分支只留计数 + 密级闸对照 + 指纹可比对/加盐可变/已知碰撞对不复现 + 每库同盐；E 组=单点（AST 判据：字符串构造面 f-string/+/%/.join/.format 中出现未消毒的内容源变量即红——值/键/词面三种泄漏形态全覆盖，字面 grep 已废）
# 执行：--mutate 时把 why/_fp 改回修前或绕过形态（原值直拼 / 键名明文 / 大小写分隔符 join / % 格式化 / sha1[:8] 无盐），守卫必须转红并点名
# 验证方式：全部 PASS 即通过；--mutate 下变异的「指定命中」须与预期一致（不多不少）
# 不适用条件：不判 export_* 显式导出面（issue 明示不主张）；不判 sweep/sustain/工具面调度（与 decontaminate 同一 _weaken 单点）；不判 expired/not_yet 等 fm 值证据（fm 本就是明文面，非正文）；不覆盖 secret 档（机制同一）
"""issue #444 守卫：_contradiction 的 why 拼正文原值 ⇒ private 正文进明文审计面。

病象（修前）：同键不同值的 why =「键=本端原值 vs 对端原值」，经 audit detail →
_weaken → verify 的 evidence 落进**两个**节点的 frontmatter 与 _trust.jsonl
（fm 加密只作用于正文，两处都是明文面）；scrub 双方各判一次，private 节点正文
由此被写进 internal 对端节点——internal 身份合规读对端（get 拿得到）即取回
private 正文（密级闸本身没坏：get(priv1) 恒 None）。极性相反分支把共享
bigram 词面写进 why，同族。修后：why 只留键名指纹 + 值短指纹（同键不同值）/
只留计数（极性相反且共享内容）——记「谁处置了谁」，不复制被处置内容。

#448 审返工三修（2026-10-16）：
① 键名 k 原样进 why 也是泄漏（键来自 private 正文，2–12 字符动态键）——键名
   同走 _fp（K1 改形态全匹配断言）；
② sha1[:8]＝32bit 可穷举＋实测碰撞（v17961/v65193→2ce8ed4b，20 万样本 0.1s
   内命中）——改 sha256[:16]＋每库随机盐（盐存库根本地、不进审计面），措辞
   从「不可逆」改为诚实表述（K4/K5/K6 钉住）；
③ E2/E3 字面 grep 可被 %／任意分隔符 join 绕过——改 AST 判据：字符串构造面
   （f-string / BinOp+ / BinOp% / .join / .format）中出现未消毒（不在
   len()/_fp() 之下）的内容源变量即红，三种变异形态都须转红。
"""
import ast
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
_check("K1 internal↔internal 矛盾照常处置，判据仍可解释（键指纹+值指纹，#448 审①）",
       _dec2["applied"] >= 2 and _det2
       and all(d and re.fullmatch(r"同键不同值：[0-9a-f]{16}"
                                  r"（本端 [0-9a-f]{16} / 对端 [0-9a-f]{16}）", d)
               for d in _det2 if d is not None)
       and all("公开甲" not in (d or "") and "公开乙" not in (d or "")
               and "正文" not in (d or "")          # 键名同样不回明文（#448 审①）
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
_check("K4 指纹可比对：同值同指纹 / 异值异指纹 / 定长 16 位十六进制（#448 审②）",
       _fp("甲") == _fp("甲") and _fp("甲") != _fp("乙")
       and re.fullmatch(r"[0-9a-f]{16}", _fp("甲")) is not None, _fp("甲"))
_check("K5 #448 审②：加盐即变纹（同值异盐异纹）+ sha1[:8] 已知碰撞对"
       "（值守实测 v17961/v65193→2ce8ed4b）不再碰撞",
       _fp("甲", "s1") != _fp("甲", "s2") and _fp("甲", "") != _fp("甲", "x")
       and _fp("v17961") != _fp("v65193"),
       (_fp("甲", "s1"), _fp("甲", "s2"),
        _fp("v17961"), _fp("v65193")))
_check("K6 #448 审②：每库同盐——_fp_salt 同库两次取值一致、长度合规，"
       "盐文件在库根本地（不进审计面）",
       scrub._fp_salt(_cg) == scrub._fp_salt(_cg)
       and len(scrub._fp_salt(_cg)) >= 16
       and os.path.isfile(os.path.join(_cg.root, scrub._FP_SALT_FILE)),
       (len(scrub._fp_salt(_cg)), scrub._FP_SALT_FILE))

# ---------------------------------------------------------------- E 组单点
print("== E 组：单点（AST 判据，#448 审③）==")
_SRC = __import__("inspect").getsource(scrub._contradiction)
_check("E1 _contradiction 键名与两侧值均走 _fp 指纹单点（#448 审①）",
       "_fp(k, salt)" in _SRC and "_fp(kv_a[k], salt)" in _SRC
       and "_fp(kv_b[k], salt)" in _SRC)


def _leaky_builders(fn_src, banned):
    """AST 判据（#448 审③）：字符串构造面出现未消毒的内容源变量 ⇒ 泄漏。

    构造面 = f-string（JoinedStr）/ BinOp(Add) / BinOp(Mod) / `.join` /
    `.format`——覆盖字面 grep 时代的三种绕过形态（% 格式化、+ 拼接、任意
    分隔符 join）。消毒 = 该 Name 节点位于 `len(...)`（计数）或 `_fp(...)`
    （指纹）调用子树内，二者产物都不是词面/明文。逐 **Name 节点**判定：
    同名变量在 len 下出现不豁免它在别处的裸用。
    """
    tree = ast.parse(fn_src)
    safe = set()
    for n in ast.walk(tree):
        if (isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
                and n.func.id in ("len", "_fp")):
            for x in ast.walk(n):
                if isinstance(x, ast.Name):
                    safe.add(id(x))
    hits = set()
    for n in ast.walk(tree):
        builder = (isinstance(n, ast.JoinedStr)
                   or (isinstance(n, ast.BinOp)
                       and isinstance(n.op, (ast.Add, ast.Mod)))
                   or (isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
                       and n.func.attr in ("join", "format")))
        if not builder:
            continue
        for x in ast.walk(n):
            if isinstance(x, ast.Name) and x.id in banned and id(x) not in safe:
                hits.add(x.id)
    return sorted(hits)


# 内容源变量：kv 分支（键 k 与两侧值 dict）与极性分支（共享词面集与正文串）。
_KV_SRC = {"k", "kv_a", "kv_b"}
_POL_SRC = {"shared", "bg_a", "bg_b", "content", "oc"}
_check("E2 AST：kv 分支字符串构造面（f-string/+/%/.join/.format）不得携带"
       "未消毒的键名/原值变量（字面 grep 判据废——%格式化与任意 join 同样拦）",
       not _leaky_builders(_SRC, _KV_SRC), _leaky_builders(_SRC, _KV_SRC))
_check("E3 AST：极性分支字符串构造面不得携带未消毒的共享词面/正文变量",
       not _leaky_builders(_SRC, _POL_SRC), _leaky_builders(_SRC, _POL_SRC))
# 判据自证（防 AST 判据自身空转）：修前/绕过形态必须被同一条判据命中。
_OLD_KV = ('def _s():\n'
           '    return {"with": oid, "via": r.get("via"),\n'
           '            "why": f"同键不同值：{k}={kv_a[k]} vs {kv_b[k]}"}\n')
_OLD_POL_PCT = ('def _s():\n'
                '    return {"with": oid, "via": r.get("via"),\n'
                '            "why": "极性相反且共享内容：%s"\n'
                '                    % "|".join(sorted(shared)[:5])}\n')
_OLD_POL_PLUS = ('def _s():\n'
                 '    return {"with": oid, "via": r.get("via"),\n'
                 '            "why": "极性相反且共享内容："\n'
                 '                    + "、".join(sorted(shared)[:5])}\n')
_OLD_POL_JOIN = ('def _s():\n'
                 '    return {"with": oid, "via": r.get("via"),\n'
                 '            "why": f"极性相反且共享内容：'
                 "{'|'.join(sorted(shared)[:5])}"
                 '"}\n')
_check("E4 AST 判据自证：修前/绕过形态（直拼/%/+/.join 四样本）喂同一条判据必须全红",
       _leaky_builders(_OLD_KV, _KV_SRC) == ["k", "kv_a", "kv_b"]
       and _leaky_builders(_OLD_POL_PCT, _POL_SRC) == ["shared"]
       and _leaky_builders(_OLD_POL_PLUS, _POL_SRC) == ["shared"]
       and _leaky_builders(_OLD_POL_JOIN, _POL_SRC) == ["shared"],
       [_leaky_builders(_OLD_KV, _KV_SRC),
        _leaky_builders(_OLD_POL_PCT, _POL_SRC),
        _leaky_builders(_OLD_POL_PLUS, _POL_SRC),
        _leaky_builders(_OLD_POL_JOIN, _POL_SRC)])

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
    ("V1 同键不同值 why 改回键名+正文原值直拼（回到 #444 修前）",
     "md_cg/scrub.py",
     '                        "why": f"同键不同值：{_fp(k, salt)}"'
     + chr(10)
     + '                               f"（本端 {_fp(kv_a[k], salt)}"'
     + chr(10)
     + '                               f" / 对端 {_fp(kv_b[k], salt)}）"}',
     '                        "why": f"同键不同值：{k}={kv_a[k]} vs {kv_b[k]}"}',
     ("A1", "A2", "A3", "A4", "A5", "A6", "K1", "E1", "E2")),
    ("V2 #448 审③-+：极性 why 改回共享 bigram 词面 join（+ 拼接形态）",
     "md_cg/scrub.py",
     '                        "why": f"极性相反且共享内容：共享 bigram {len(shared)} 个"'
     + chr(10) + '                               f" / 重合率 {ratio:.0%}"}',
     '                        "why": "极性相反且共享内容：" + "、".join(' + chr(10)
     + '                            sorted(shared)[:5])}',
     ("K2", "E3")),
    ("V3 #448 审③-%：极性 why 改 % 格式化 + 任意分隔符 join（字面 grep 零告警形态）",
     "md_cg/scrub.py",
     '                        "why": f"极性相反且共享内容：共享 bigram {len(shared)} 个"'
     + chr(10) + '                               f" / 重合率 {ratio:.0%}"}',
     '                        "why": "极性相反且共享内容：%s" % "|".join(' + chr(10)
     + '                            sorted(shared)[:5])}',
     ("K2", "E3")),
    ("V4 #448 审③-join：极性 why 改 f-string 内嵌 join（旧 E3 仅认「、」分隔符的绕过形态）",
     "md_cg/scrub.py",
     '                        "why": f"极性相反且共享内容：共享 bigram {len(shared)} 个"'
     + chr(10) + '                               f" / 重合率 {ratio:.0%}"}',
     '                        "why": f"极性相反且共享内容：{\'|\'.join(' + chr(10)
     + '                            sorted(shared)[:5])}"}',
     ("K2", "E3")),
    ("V5 #448 审②：_fp 回退 sha1[:8] 无盐（可穷举＋已知碰撞对回归）",
     "md_cg/scrub.py",
     '    return hashlib.sha256((salt + str(s)).encode("utf-8")).hexdigest()[:16]',
     '    return hashlib.sha1(str(s).encode("utf-8")).hexdigest()[:8]',
     ("K1", "K4", "K5")),
    ("V6 #448 审①：键名单独回退明文（值仍指纹——键名泄漏独立成罪）",
     "md_cg/scrub.py",
     'f"同键不同值：{_fp(k, salt)}"',
     'f"同键不同值：{k}"',
     ("K1", "E1", "E2")),
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
