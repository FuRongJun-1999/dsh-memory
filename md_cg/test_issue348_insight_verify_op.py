# -*- coding: utf-8 -*-
# 功能名：cg(op=insight, action=verify) 须持 verify op（issue #348-A）
# 生效条件：python -X utf8 -m md_cg.test_issue348_insight_verify_op [--mutate]；被测面=md_cg/mcp_server.py 的 _insight_call
# 子功能：A 组=无 verify op 的角色（record）不得自证/判伪，有 verify op 的角色照常；K 组=record 的 record/list 等非裁决动作不受影响
# 执行：--mutate 时把新增的 require_op("verify") 改回无（即 #348-A 修前），守卫必须转红
# 验证方式：全部 PASS 即通过；--mutate 下变异的「指定命中」须与预期一致
# 不适用条件：不判 verified 支置保护位与否、属主改判 falsified 后要不要撤 0.9 与保护位（保护语义设计裁定，报告明示本补丁不碰）；不判库层 MdCGSecure.insight 直调面（N197 守卫 1f/1h 语义不变）；不覆盖真 stdio / POSIX 腿
"""issue #348-A 守卫：insight 的 verify 是裁决动作，须持 verify op。

病象（修前）：_insight_call 的 verify 动作只查 can_write——record/reflect/sustain
（ops_allow 含 insight、无 verify op、forbidden 明列「裁决与删除」）可以给自己写的
洞见定案 verified（importance 保底 0.9 + protected=True），也能把属主的洞见判
falsified；而同一令牌调 mdcg_verify 被 AccessDenied。#320 在 insight 面的相邻出口。
"""
import os
import shutil
import sys
import tempfile

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _REPO)
_TMP = tempfile.mkdtemp(prefix="iss348a_")
os.environ.update({"MDCG_ROOT": _TMP + "/brain", "MDCG_STATE_ROOT": _TMP + "/state",
                   "MDCG_AUX_ROOT": _TMP + "/auxstore",
                   "MDCG_DATA_ROOT": _TMP + "/datastore", "MDCG_EXPORT_ROOT": _TMP,
                   "MDCG_SUSTAIN": "0", "MDCG_SLEEP": "0"})
from md_cg.mdcos import MdCGSecure  # noqa: E402
from md_cg.security import Principal  # noqa: E402
from md_cg import tokens as _tk, mcp_server as _ms  # noqa: E402

FAILS = []


def _check(name, cond, detail=""):
    if cond:
        print("  PASS " + name)
    else:
        print("  FAIL " + name + "  " + str(detail)[:200])
        FAILS.append(name)


def _mk(role):
    sp = _tk.role_spec(role)
    return MdCGSecure(_TMP + "/brain",
                      principal=Principal(role=role, clearance=sp["clearance_cap"],
                                          can_write=sp["can_write"],
                                          can_admin=sp["can_admin"],
                                          ops_allow=sp["ops_allow"]),
                      autoflush=1)


def _call(cg, args):
    try:
        return _ms._dispatch(cg, "cg", args)
    except Exception as e:                      # noqa: BLE001
        return {"_exc": type(e).__name__ + ":" + str(e)[:110]}


_owner = _mk("designer")
_rec = _mk("record")
_ver = _mk("verify")

print("== 前提 ==")
_r0 = _call(_rec, {"op": "insight", "action": "record", "node_id": "ins348a",
                   "statement": "生产库端口为 9090（record 写的假洞见）",
                   "category": "ops"})
_check("P1 前提：record 能记洞见（insight record 本就允许）",
       _r0.get("ok") is True and "AccessDenied" not in str(_r0), str(_r0)[:140])

print("== A 组：无 verify op 不得裁决洞见 ==")
_a1 = _call(_rec, {"op": "insight", "action": "verify", "node_id": "ins348a",
                   "verdict": "verified"})
_check("A1 record 给自己的洞见定案 verified → 拒（#348-A 收口）",
       "AccessDenied" in str(_a1), str(_a1)[:160])
_a2 = _call(_owner, {"op": "insight", "action": "record", "node_id": "ins_truth",
                     "statement": "生产库端口为 8080（属主记录）", "category": "ops"})
_a3 = _call(_rec, {"op": "insight", "action": "verify", "node_id": "ins_truth",
                   "verdict": "falsified"})
_check("A2 record 把属主的洞见判 falsified → 拒",
       "AccessDenied" in str(_a3), str(_a3)[:160])

_fm = ((_call(_owner, {"op": "read", "node_id": "ins348a"}) or {}).get("frontmatter") or {})
_check("A3 盘面：insight_state 未被置 verified（无副作用）",
       _fm.get("insight_state") != "verified",
       {k: _fm.get(k) for k in ("insight_state", "importance", "protected")})

_a4 = _call(_rec, {"op": "insight", "action": "verify", "node_id": "ins348a",
                   "evidence": "x", "v_types": ["v1"]})
_check("A4 证据路径（只给 v_types 不给 verdict）→ 同样拒",
       "AccessDenied" in str(_a4), str(_a4)[:160])

print("== K 组：非恒真对照 ==")
_k1 = _call(_ver, {"op": "insight", "action": "verify", "node_id": "ins348a",
                   "verdict": "verified"})
_check("K1 verify 角色（有 verify op）→ 放行（合法路径不误拒）",
       "AccessDenied" not in str(_k1), str(_k1)[:160])
_k2 = _call(_rec, {"op": "insight", "action": "record", "node_id": "ins348a_b",
                   "statement": "record 再记一条", "category": "ops"})
_check("K2 record 的 record 动作 → 仍放行（只收口 verify，不扩大）",
       _k2.get("ok") is True and "AccessDenied" not in str(_k2), str(_k2)[:160])
_k3 = _call(_rec, {"op": "insight", "action": "list"})
_check("K3 record 的 list（只读）→ 仍放行",
       "AccessDenied" not in str(_k3), str(_k3)[:160])

print("")
if FAILS:
    print("issue #348-A 结果：%d 失败" % len(FAILS))
else:
    print("issue #348-A 结果：全部通过")

# ------------------------------------------------------------------ 定点变异
_MUTATIONS = (
    ("V1 摘掉新增的 require_op(verify)（回到只查 can_write，即 #348-A 修前）",
     "md_cg/mcp_server.py",
     "    if (principal is not None and act == \"verify\"",
     "    if False and (principal is not None and act == \"verify\"",
     ("A1", "A2", "A4")),
)


def _mirror_build():
    dst = tempfile.mkdtemp(prefix="iss348a_mut_")
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
                         "md_cg.test_issue348_insight_verify_op"],
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
            t = open(p, encoding="utf-8", newline="").read()
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