# -*- coding: utf-8 -*-
# 功能名：近重复合并的「新行是否已存在」判据守卫——段边界对齐取代子串判据（issue #323）
# 生效条件：python -X utf8 -m md_cg.test_issue323_aggregate_segment_boundary [--mutate]；被测面=md_cg/forgetting.py 的 aggregate_line（MERGE/CONVERGE 共用的唯一聚合点）
# 子功能：A 组=更正必须追加（前缀/内部/后缀片段式）；K 组=非泄漏方向逐位不变（幂等、真新信息、返回三元组）；E 组=单点与判据形状
# 执行：--mutate 时逐条把判据改回改动前形态，守卫必须转红（定点变异自证）
# 验证方式：全部 PASS 即通过；--mutate 下每条变异的「指定命中」须与预期一致
# 不适用条件：不判相似度（assess 的 redundancy）、不判该不该合并（gate 层）；不覆盖 POSIX 腿
"""issue #323 守卫：aggregate_line 不得用子串判据吞掉「片段式更正」。

病象（修前）：判「目标里已有这行」用的是 s in have（子串）。旧正文
「报销上限 15000 元」+ 更正值「报销上限 1500」时它判「已存在」，新行一字不
追加，而 reinforce 照常把 importance +0.05、merge_count +1 写盘 ⇒ 回执说已
合并、库里留下并**强化**的是过时值。触发面不止前缀：任何「新值恰为旧正文
连续片段」的更正（v3.10→v3.1、8080→808、2026-10-15→2026-10-1）同病。

判据方向：A 组要求「更正被追加」，K 组要求「幂等与真新信息语义逐位不变」——
两侧同时成立才说明判据是**段边界对齐**而不是把判据放宽成「什么都追加」。
"""
import ast
import io
import os
import shutil
import sys
import tempfile

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FAILS = []


def _check(name, cond, detail=""):
    if cond:
        print("  PASS " + name)
    else:
        print("  FAIL " + name + "  " + str(detail)[:200])
        FAILS.append(name)


sys.path.insert(0, _REPO)
from md_cg import forgetting, autonomy_modes  # noqa: E402

_STAMP = "10-14 22:00"


def _agg(body, content):
    return forgetting.aggregate_line(body, content, stamp=_STAMP)


def _appended(body, content):
    nb, line, ln = _agg(body, content)
    return nb is not None and line is not None and content.splitlines()[0].strip() in line


print("== A 组：片段式更正必须追加（判据方向）==")

_PREFIX_CASES = [
    ("A1 前缀式更正 15000→1500", "报销上限 15000 元", "报销上限 1500"),
    ("A2 前缀式更正 v3.10→v3.1", "版本 v3.10", "版本 v3.1"),
    ("A3 前缀式更正 8080→808", "端口 8080", "端口 808"),
    ("A4 前缀式更正 2026-10-15→2026-10-1", "截止 2026-10-15", "截止 2026-10-1"),
]
for _n, _b, _c in _PREFIX_CASES:
    _nb, _ln, _ = _agg(_b, _c)
    _check(_n + " 必须追加（旧子串判据在此吞掉更正）",
           _appended(_b, _c), (_nb, _ln))

_nb5, _ln5, _ = _agg("报销上限 15000 元", "上限 1500")
_check("A5 内部片段式更正（左右两侧都非段边界）必须追加",
       _appended("报销上限 15000 元", "上限 1500"), (_nb5, _ln5))

_nb6, _ln6, _ = _agg("上限15000元", "5000元")
_check("A6 后缀片段式更正（左非边界、右为串端）必须追加",
       _appended("上限15000元", "5000元"), (_nb6, _ln6))

print("== K 组：非泄漏方向逐位不变（幂等 / 真新信息 / 返回形状）==")

_check("K1 同文重写零追加（B3 的原目标，幂等）",
       _agg("甲", "甲") == (None, None, None), _agg("甲", "甲"))

_check("K2 聚合行次段再写零追加（左边界是「；」）",
       _agg("- 【聚合 10-14 21:00】甲；乙", "乙") == (None, None, None),
       _agg("- 【聚合 10-14 21:00】甲；乙", "乙"))

_check("K3 段内含「；」的单段内容再写零追加（左边界是「】」）",
       _agg("- 【聚合 10-14 21:00】a；b", "a；b") == (None, None, None),
       _agg("- 【聚合 10-14 21:00】a；b", "a；b"))

_nb4, _ln4, _ = _agg("甲", "丙")
_check("K4 真新信息照常追加（判据非恒假）",
       _nb4 is not None and _ln4 is not None and "丙" in _ln4, (_nb4, _ln4))

_check("K5 空 content 返回三元组 None",
       _agg("甲", "") == (None, None, None), _agg("甲", ""))

_nb6b, _ln6b, _lnn6b = _agg("甲", "丙")
_check("K6 返回行号 = 追加后正文的行数",
       _lnn6b == len(_nb6b.splitlines()), (_lnn6b, len(_nb6b.splitlines())))

_check("K7 聚合行格式未变（前缀「- 【聚合 <stamp>】」+ 段以「；」连接）",
       _ln6b.startswith("- 【" + forgetting.AGG_MARK + " " + _STAMP + "】")
       and _nb6b == "甲" + chr(10) + _ln6b, (_ln6b, _nb6b))

_nb8, _ln8, _ = _agg("甲", "丙" + chr(10) + "丁")
_check("K8 多行 content 逐段追加且以「；」连接",
       _ln8 is not None and _ln8.endswith("丙；丁"), _ln8)

print("== E 组：单点、判据形状与端到端 ==")

_FSRC = io.open(os.path.join(_REPO, "md_cg", "forgetting.py"),
                encoding="utf-8", newline="").read()
_WSRC = io.open(os.path.join(_REPO, "md_cg", "writelimit.py"),
                encoding="utf-8", newline="").read()
_check("E1 聚合行仍是单点：writelimit 委托 forgetting.aggregate_line",
       "forgetting.aggregate_line" in _WSRC, "")

_FTREE = ast.parse(_FSRC)
_fn = None
for _node in ast.walk(_FTREE):
    if isinstance(_node, ast.FunctionDef) and _node.name == "aggregate_line":
        _fn = _node
        break
_ins = []
if _fn is not None:
    for _st in ast.walk(_fn):
        if isinstance(_st, ast.Compare) and any(
                isinstance(_op, ast.In) for _op in _st.ops):
            _left = _st.left
            if (isinstance(_left, ast.Name) and _left.id == "s"
                    and any(isinstance(_c, ast.Name) and _c.id == "have"
                            for _c in _st.comparators)):
                _ins.append(ast.dump(_st)[:80])
_check("E2 子串判据 s in have 已不在 aggregate_line 体内（AST 面；s in seen 属正当去重，不判红）",
       _fn is not None and not _ins, _ins)

_check("E3 段边界字符集含段连接符「；」与聚合行前缀结束符「】」",
       "；" in forgetting._SEG_BOUNDARY
       and "】" in forgetting._SEG_BOUNDARY, forgetting._SEG_BOUNDARY)
# issue #347：空白**不得**再是段边界（否则去掉首尾整词的更正被判已覆盖）。
_check("E5 段边界集不含空格/制表符，且含行界「\\n」（#347 收口方向）",
       " " not in forgetting._SEG_BOUNDARY
       and chr(9) not in forgetting._SEG_BOUNDARY
       and chr(10) in forgetting._SEG_BOUNDARY, repr(forgetting._SEG_BOUNDARY))

_check("E4 段边界判据是独立单点函数（_segment_covered 可被直接调用）",
       callable(getattr(forgetting, "_segment_covered", None)), "")

# ---------------------------------------------------------------- issue #347
# 去掉首尾整词的更正（尤以去掉否定词最危险：语义正好相反）。修前（#323 那版把
# 空白也当段边界 + 正文按空格拼成一行）这类更正左右都落在空格上 ⇒ 判已覆盖 ⇒
# 一字不追加，而 reinforce 照常 +0.05 / merge_count +1，同一更正说三遍就把错误
# 事实推过 AUTO_PROTECT_IMPORTANCE=0.70 的保护线。
print("== W 组（#347）：去掉首尾整词的更正必须被追加 ==")
_w_cases = (
    ("W1 去掉开头否定词",
     "do not deploy the billing service on Friday",
     "deploy the billing service on Friday"),
    ("W2 去掉结尾限定词",
     "run the migration only on staging",
     "run the migration"),
    ("W3 中英混排去掉开头整词",
     "禁止 restart gateway 服务",
     "restart 服务"),
)
for _nm, _old, _new in _w_cases:
    _nb, _ln, _ct = forgetting.aggregate_line(_old, _new)
    _check(_nm + " → 追加（修前被判 already_covered 而一字不加）",
           _nb is not None and _ln is not None and _new in _nb,
           (_nb, _ln))
    # 同一条更正再写第二次必须零追加（幂等不退化）——由「】」边界守住
    if _nb is not None:
        _nb2, _ln2, _ = forgetting.aggregate_line(_nb, _new)
        _check(_nm + " · 更正再写第二次 → 零追加（幂等仍在）",
               _ln2 is None and _nb2 is None, (_nb2, _ln2))

print("== K 组（#347）：多行正文的行界语义 ==")
_multi = "alpha one\nbeta two\ngamma three"
_k9a, _k9b, _ = forgetting.aggregate_line(_multi, "beta two")
_check("K9 旧正文的**整行**再写 → 零追加（行界仍是段界）",
       _k9a is None and _k9b is None, (_k9a, _k9b))
_k10a, _k10b, _ = forgetting.aggregate_line(_multi, "beta")
_check("K10 旧正文某行内的**真子串** → 追加（子串不算整段）",
       _k10b is not None and "beta" in _k10b, (_k10a, _k10b))

print("== A7 端到端：MERGE 后更正落进目标正文且可检索 ==")
_d = tempfile.mkdtemp(prefix="iss323_e2e_")
try:
    # G 组反漂移（md_cg/test_autonomy_modes.py）：档位 env 的字面量只许出现在
    # 唯一入口模块 autonomy_modes.py——守卫里写带引号的档位 env 名会被判红。
    # 故键取 AUTONOMY_ENV_KEYS，档名从 MATRIX 推（不硬编码字面量）。
    from md_cg import autonomy_modes as _am
    _FULL = next(_m for _m in _am.AUTONOMY_MODES
                 if (_am.MATRIX.get(_m) or {}).get(_am.B_MERGE) == _am.ALLOW)
    os.environ.update({"MDCG_ROOT": _d + "/brain",
        "MDCG_STATE_ROOT": _d + "/state", "MDCG_AUX_ROOT": _d + "/auxstore",
        "MDCG_DATA_ROOT": _d + "/datastore", "MDCG_EXPORT_ROOT": _d,
        "MDCG_TOKEN_FILE": _d + "/auxstore/tokens.json",
        "MDCG_SUSTAIN": "0", "MDCG_SLEEP": "0",
        _am.AUTONOMY_ENV_KEYS["mode"]: _FULL})
    from md_cg.mdcos import MdCGSecure
    from md_cg.security import Principal
    from md_cg import mcp_server
    _cg = MdCGSecure(os.environ["MDCG_ROOT"],
                     principal=Principal(clearance="secret", can_admin=True),
                     autoflush=1)

    def _w(nid, content):
        return mcp_server._dispatch(_cg, "mdcg_remember", {
            "node_id": nid, "content": content, "layer": "contextual",
            "role": "user", "sensitivity": "internal", "gated": True,
            "verification_basis": "test"})

    _ra = _w("n_e2e", "报销上限 15000 元")
    _rb = _w("n_e2e2", "报销上限 1500")
    _sink = ((_rb.get("reinforced") or {}).get("content_sink") or {})
    _body = ((_cg.get("n_e2e") or {}).get("content") or "")
    _check("A7a 端到端：更正值被判 MERGE 并入既有节点",
           _rb.get("verdict") == "MERGE", _rb.get("verdict"))
    _check("A7b 端到端：content_sink.action == appended（不再是 already_covered）",
           _sink.get("action") == "appended", _sink)
    _check("A7c 端到端：目标正文含聚合行且更正值原样落盘",
           forgetting.AGG_MARK in _body and "报销上限 1500" in _body,
           _body[-120:])
    _check("A7d 端到端：更正值在库中可检索（非仅 inbox 留痕）",
           "报销上限 1500" in _body, _body[-120:])
    _cg.close()
finally:
    shutil.rmtree(_d, ignore_errors=True)

print("")
if FAILS:
    print("issue #323 结果：%d 失败" % len(FAILS))
else:
    print("issue #323 结果：全部通过")


# ---------------------------------------------------------------- 定点变异

_MUTATIONS = (
    ("V1 判据回到子串形态（s in have，即 #323 修前）",
     "md_cg/forgetting.py",
     "if not s or s in seen or _segment_covered(s, have):",
     "if not s or s in seen or s in have:",
     ("A1", "A2", "A3", "A4", "A5", "A6")),
    ("V2 右边界恒真（只判左边界，前缀式更正又被吞）",
     "md_cg/forgetting.py",
     "        right = j == len(hay) or hay[j] in _SEG_BOUNDARY",
     "        right = True",
     ("A1", "A2", "A3", "A4")),
    ("V3 左边界恒真（只判右边界，后缀片段式更正又被吞）",
     "md_cg/forgetting.py",
     "        left = i == 0 or hay[i - 1] in _SEG_BOUNDARY",
     "        left = True",
     ("A6",)),
    # 锚点跟随 issue #347 的新字面量（边界集从「；】空白制表」改为「；】行界」）。
    ("V4 段边界集丢掉「；」与「】」（幂等退化：聚合行再写会重复追加）",
     "md_cg/forgetting.py",
     "_SEG_BOUNDARY = \"；】\\n\"",
     "_SEG_BOUNDARY = \"\\n\"",
     ("K2", "K3")),
    ("V5 段边界集丢掉「】」（聚合行首段再写重复追加）",
     "md_cg/forgetting.py",
     "_SEG_BOUNDARY = \"；】\\n\"",
     "_SEG_BOUNDARY = \"；\\n\"",
     ("K3",)),
    # ---- issue #347 新增两条反向变异 ----
    ("V6 空白回到段边界集（去掉首尾整词的更正又被判已覆盖，即 #347 修前）",
     "md_cg/forgetting.py",
     "_SEG_BOUNDARY = \"；】\\n\"",
     "_SEG_BOUNDARY = \"；】 \\t\\n\"",
     ("E5", "W1", "W2")),
    ("V7 正文按空格拼成一行（行界消失，整词更正又被吞）",
     "md_cg/forgetting.py",
     "    have = \"\\n\".join(\" \".join(l.split()) for l in (body or \"\").splitlines())",
     "    have = \" \".join((body or \"\").split())",
     ("K9",)),
)


def _mirror_build():
    dst = tempfile.mkdtemp(prefix="iss323_mut_")
    for name in ("md_cg", "scripts"):
        src = os.path.join(_REPO, name)
        if os.path.isdir(src):
            shutil.copytree(src, os.path.join(dst, name),
                            ignore=shutil.ignore_patterns("__pycache__",
                                                         "*.pyc"))
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
                         "md_cg.test_issue323_aggregate_segment_boundary"],
                        capture_output=True, text=True, encoding="utf-8",
                        errors="replace", cwd=tree, env=env, timeout=1800)
    out = (pr.stdout or "") + (pr.stderr or "")
    reds = [ln.split("FAIL ", 1)[1].strip()
            for ln in out.splitlines() if "FAIL " in ln]
    return pr.returncode, reds, out


def _mutate():
    print("!! 定点变异自证：逐条把判据改回改动前形态，守卫必须转红")
    tree = _mirror_build()
    try:
        rc, reds, out = _run_in(tree)
        print("  未变异镜像基线：rc=%d 红项=%d（必须 rc=0 且 0 红）"
              % (rc, len(reds)))
        if rc != 0 or reds:
            print(chr(10).join(out.splitlines()[-25:]))
        ok, bad = 0, []
        for desc, rel, old, new, exp in _MUTATIONS:
            p = os.path.join(tree, rel)
            t = io.open(p, encoding="utf-8", newline="").read()
            if t.count(old) != 1:
                bad.append("%s —— 锚点在 %s 里命中 %d 次"
                           % (desc, rel, t.count(old)))
                print("  ANCHOR-MISS " + desc)
                continue
            bak = t
            io.open(p, "w", encoding="utf-8", newline="").write(
                t.replace(old, new, 1))
            for root, dd, ff in os.walk(tree):
                if os.path.basename(root) == "__pycache__":
                    shutil.rmtree(root, ignore_errors=True)
            rc2, reds2, out2 = _run_in(tree)
            io.open(p, "w", encoding="utf-8", newline="").write(bak)
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
