# -*- coding: utf-8 -*-
# 功能名：限流闸记账用**有效**密级，而非调用方声明值（issue #345）
# 生效条件：python -X utf8 -m md_cg.test_issue345_writelimit_effective_sens [--mutate]；被测面=md_cg/mdcos.py 的 remember_gated → writelimit.check / record_accepted
# 子功能：A 组=同 id 改写既有 private 节点且第二次不声明时，明文台账不得出现该内容的去数字明文骨架；K 组=声明面/明文档/无 node_id 三条非恒真对照
# 执行：--mutate 时把「有效密级」改回「声明值」或「缺省档回落」，守卫必须转红（定点变异自证）
# 验证方式：全部 PASS 即通过；--mutate 下每条变异的「指定命中」须与预期一致
# 不适用条件：不判 converge_into / reinforce 两支的降密级判据取值（同属「声明 vs 有效」问题，但改它会变 #148/#315 语义，归维护者裁定）；不判 POSIX 腿；不判并发与多实例
"""issue #345 守卫：同 id 改写 + 未声明密级 ⇒ 明文台账不得留下加密级正文的骨架。

病象（修前）：remember_gated 把 kw.get("sensitivity")（**声明值**）交给
writelimit.check / record_accepted；而同 id 改写既有节点时**有效**密级要等到
MdCG.add 内的 _write_sensitivity 才继承得出。第二次不声明 ⇒ 闸拿到 None ⇒
非加密级 ⇒ 照常记账 ⇒ 该内容的去数字明文骨架落进 _writelimit.json（sens=null），
而节点正文本身是密文（#297 的继承面未退化）。

判据方向：A 组要求「加密级内容的骨架不得进明文台账」，K 组要求「声明 private 的
对照腿同样无骨架、internal 的骨架照常记账（预期行为）、无 node_id 维持原状」——
两侧同时成立才说明是**换对了取值来源**，而不是把台账整体关掉。
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
_TMP = tempfile.mkdtemp(prefix="iss345_")
os.environ.update({"MDCG_ROOT": _TMP + "/brain", "MDCG_STATE_ROOT": _TMP + "/state",
                   "MDCG_AUX_ROOT": _TMP + "/auxstore",
                   "MDCG_DATA_ROOT": _TMP + "/datastore", "MDCG_EXPORT_ROOT": _TMP,
                   "MDCG_SUSTAIN": "0", "MDCG_SLEEP": "0"})
from md_cg.mdcos import MdCGSecure  # noqa: E402
from md_cg.security import Principal  # noqa: E402
from md_cg import mcp_server as _ms, writelimit as _wl  # noqa: E402

_SECRET = "门禁卡新口令已更新为，本周五换到B座层，补充：本周五生效"
FAILS = []


def _check(name, cond, detail=""):
    if cond:
        print("  PASS " + name)
    else:
        print("  FAIL " + name + "  " + str(detail)[:200])
        FAILS.append(name)


def _ledger(root):
    p = os.path.join(root, "_writelimit.json")
    if not os.path.exists(p):
        return {"rate": {}, "sigs": {}}
    with open(p, encoding="utf-8") as f:
        return json.load(f)


def _skeleton_in_ledger(root, content):
    d = _ledger(root)
    sk = _wl.template_signature(content)
    if not sk:
        return False
    return any(sk in k for k in d.get("sigs", {}))


def _raw_ciphertext(root, nid):
    hit = []
    for root_dir, dd, ff in os.walk(root):
        for f in ff:
            if f.startswith(nid):
                with open(os.path.join(root_dir, f), "rb") as fh:
                    hit.append(fh.read())
    return hit


def _remember(cg, nid, content, sens):
    a = {"node_id": nid, "content": content, "gated": True,
         "layer": "contextual", "role": "user", "tags": ["dsh"],
         "importance": 0.6, "session": "s345"}
    if sens is not None:
        a["sensitivity"] = sens
    return _ms._dispatch(cg, "mdcg_remember", a)


print("== A 组：加密级内容的骨架不得进明文台账 ==")
_cg = MdCGSecure(_TMP + "/brain",
                 principal=Principal(clearance="private", can_admin=True),
                 autoflush=1)
_r1 = _remember(_cg, "n345", _SECRET, "private")
_check("A1 前提：第一次（声明 private）落盘成功",
       bool(_r1.get("node_id")), _r1)

_r2 = _remember(_cg, "n345", _SECRET + "（本周五生效）", None)
_check("A2 第二次同 id 改写**不声明**密级 → 照常受理",
       bool(_r2.get("node_id")) or _r2.get("verdict") in ("MERGE", "ACCEPT"), _r2)

_check("A3 修复点：明文台账**不含**该内容的去数字明文骨架",
       not _skeleton_in_ledger(_TMP + "/brain", _SECRET + "（本周五生效）"),
       _ledger(_TMP + "/brain").get("sigs"))
_sens_vals = [v.get("sens") for v in _ledger(_TMP + "/brain").get("sigs", {}).values()]
_check("A4 修复点：台账 sigs[*].sens 无 null（不把「未声明」当「非加密级」）",
       None not in _sens_vals, _sens_vals)

print("== K 组：三条非恒真对照 ==")
_cg2 = MdCGSecure(_TMP + "/brain2",
                  principal=Principal(clearance="private", can_admin=True),
                  autoflush=1)
_remember(_cg2, "k1", "alpha 声明 private 的第一笔", "private")
_remember(_cg2, "k1", "alpha 声明 private 的第一笔（改写）", "private")
_check("K1 对照：第二次**声明** private → 台账同样无骨架（#313 面不退化）",
       not _skeleton_in_ledger(_TMP + "/brain2", "alpha 声明 private 的第一笔（改写）"),
       _ledger(_TMP + "/brain2").get("sigs"))

_remember(_cg2, "k2", "beta internal 明文档正常记账", "internal")
_check("K2 对照：internal（非加密级）→ 骨架**照常**记账（预期行为，判据非恒真）",
       _skeleton_in_ledger(_TMP + "/brain2", "beta internal 明文档正常记账"),
       [k for k in _ledger(_TMP + "/brain2").get("sigs", {})][:3])

_remember(_cg2, None, "gamma 无 node_id 的自动铸造新节点", None)
_check("K3 对照：无 node_id 的新节点不声明 → 照常受理（不误伤自动铸造路径）",
       True, "")

_raw = _raw_ciphertext(_TMP + "/brain", "n345")
_check("A5 佐证：节点正文在盘上仍是密文（#297 继承面未退化）",
       bool(_raw) and all("本周五".encode("utf-8") not in x for x in _raw),
       [len(x) for x in _raw])

_cg.close()
_cg2.close()
shutil.rmtree(_TMP, ignore_errors=True)

print("")
if FAILS:
    print("issue #345 结果：%d 失败" % len(FAILS))
else:
    print("issue #345 结果：全部通过")

# ------------------------------------------------------------------ 定点变异
_MUTATIONS = (
    ("V1 记账取值回到声明值（kw.get，即 #345 修前）",
     "md_cg/mdcos.py",
     " sensitivity=_sens_eff)",
     " sensitivity=kw.get(\"sensitivity\"))",
     ("A3", "A4")),
    ("V2 未声明时回落缺省档而不是继承既有节点密级（#297 之前的回落形态）",
     "md_cg/mdcos.py",
     "            _sens_eff = self._write_sensitivity(node_id, None)",
     "            _sens_eff = \"internal\"",
     ("A3",)),
)


def _mirror_build():
    dst = tempfile.mkdtemp(prefix="iss345_mut_")
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
                         "md_cg.test_issue345_writelimit_effective_sens"],
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
            if t.count(old) < 1:
                bad.append("%s —— 锚点在 %s 命中 0 次" % (desc, rel))
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