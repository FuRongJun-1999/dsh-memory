# -*- coding: utf-8 -*-
"""issue #345 守卫：writelimit 记账必须用**有效密级**（声明值或单点继承后的值），不是未解析的声明值。

病象（本机独立复现于真 main c85ac887，探针与 issue 实测同面）：#313 修复给限流闸接上了
sensitivity 形参，但生产调用方传进去的是**声明值** kw.get("sensitivity")。同 node_id 改写
第二次不重传时声明值为 None，而同一次写入的有效密级经下游 MdCGSecure._write_sensitivity
（#297 单点）继承既有节点仍是 private ⇒ 节点正文仍是密文（#297 未退化），闸却按
「非加密级」把去数字明文骨架记进明文台账 _writelimit.json——同一写入、两处判据答案不同。
触发条件：缺省配置、同 id 二次 mdcg_remember，第一次声明 private、第二次不声明。

修法（issue 建议方案①：调用点解析）：remember_gated 在闸前算一次
    _sens_eff = self._write_sensitivity(node_id, kw.get("sensitivity"))
（try/except 包住：解析失败或方法不存在时回落声明值——不改 #297 fail-closed 的下游时序），
check / record_accepted 两处改传 _sens_eff。
**刻意不改的**：converge_into / reinforce 仍传声明值——它们吃的是
security.merge_downgrades(target, declared) 的合并裁决，把 eff 推过去会翻转该裁决面
（public target 合并可能由放行变拒绝），超出本件病灶，在 PR 正文如实声明。

判据组：
  S1 A/B 两腿端到端（A＝两次都声明 private；B＝第二次不声明）——★S1.2 是病灶本体；
  S2 _write_sensitivity 三态解析契约 + ★S2.4 源码面 try/except 回落声明值；
  S3 反过度封：internal 未声明照旧记账、原语签名不变、直接调原语传 None 照旧记账（#313 K8 同向）；
  S4 mdcos.py 内 writelimit.check / record_accepted 每个调用点的 sensitivity 实参都是 Name _sens_eff。

运行：python -X utf8 -m md_cg.test_issue345_writelimit_effective [--mutate]
退出码：0 全绿；1 有红；2 变异锚点未命中（ANCHOR-MISS）。
"""
from __future__ import annotations

import ast
import io
import os
import shutil
import sys
import tempfile

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO not in sys.path:
    sys.path.insert(0, _REPO)

from md_cg.test_issue313_writelimit_sensitivity import _Env  # noqa: E402  隔离库根复用

#: 夹具：无 ASCII 数字 ⇒ template_signature 即原文（骨架=原文，可直接子串断言）
C1 = "门禁卡新口令已更新为，本周五换到B座层"
C2 = C1 + "，补充：本周五生效"
#: internal 对照：未声明的**新**节点回落默认档，骨架应当照常记账（防「全禁」式修法）
INTERNAL_FIXTURE = "内部门禁卡新口令已更新为，下周一换到C座层"

_RESULTS = []


def _check(name, cond, detail=""):
    _RESULTS.append((bool(cond), name, detail))
    print(("  PASS " if cond else "  FAIL ") + name
          + ("" if cond else ("  ← " + repr(detail)[:220])))


def _mdcos_src():
    return io.open(os.path.join(_REPO, "md_cg", "mdcos.py"),
                   encoding="utf-8", newline="").read()


# ---------------------------------------------------------------- S1 行为面
def s1():
    print("== S1 行为面：A/B 两腿端到端（同 id 二次写，只差第二次带不带 sensitivity）==")
    with _Env() as e:
        r1 = e.write("n345a", C1, "private")
        r2 = e.write("n345a", C2, "private")
        sigs = e.sigs()
        _check("S1.1 A 腿（两次都声明 private）：台账无明文骨架",
               not any(C1 in k or C2 in k for k in sigs), sorted(sigs))
        _check("S1.5a A 腿两次写均 ACCEPT（写入语义未破坏）",
               r1.get("verdict") == "ACCEPT" and r2.get("verdict") == "ACCEPT",
               (r1.get("verdict"), r2.get("verdict")))
    with _Env() as e:
        e.write("n345b", C1, "private")
        r2 = e.write("n345b", C2, None)
        sigs = e.sigs()
        _check("S1.2 ★ B 腿（第二次不声明）：台账无明文骨架——病灶本体",
               not any(C1 in k or C2 in k for k in sigs), sorted(sigs))
        _check("S1.3 B 腿 sigs 整体为空（有效密级=private ⇒ 签名不落账）",
               sigs == {}, sorted(sigs))
        nf = e.node_files()
        ct = (all("<!-- mdcg-enc:v1:" in io.open(f, encoding="utf-8",
                                                  errors="replace").read()
                  for f in nf) if nf else None)
        _check("S1.4 B 腿节点正文仍密文（修法未把内容降明文）", ct is True, ct)
        _check("S1.5b B 腿两次写均 ACCEPT（写入语义未破坏）",
               r2.get("verdict") == "ACCEPT", r2.get("verdict"))


# ---------------------------------------------------------------- S2 解析面
def s2():
    print("== S2 解析面：_write_sensitivity 三态 + 源码面回落 ==")
    with _Env() as e:
        e.write("n345c", C1, "private")
        got = e.cg._write_sensitivity("n345c", None)
        _check("S2.1 未声明 + 既有 private 节点 ⇒ 解析得 private（D1 同机复算）",
               got == "private", got)
        got2 = e.cg._write_sensitivity("n345-does-not-exist-345", None)
        _check("S2.2 未声明 + 新节点 ⇒ 回落默认档 internal",
               got2 == "internal", got2)
        got3 = e.cg._write_sensitivity("n345-does-not-exist-345", "secret")
        _check("S2.3 显式声明原样透传（不被解析改写）",
               got3 == "secret", got3)
    src = _mdcos_src()
    n_res = src.count("_sens_eff = self._write_sensitivity(")
    n_fb = src.count('_sens_eff = kw.get("sensitivity")')
    i_t = src.find("_sens_eff = self._write_sensitivity(")
    i_f = src.find('_sens_eff = kw.get("sensitivity")')
    win = src[max(0, i_f - 48):i_f] if i_f > 0 else ""
    _check("S2.4 ★ 源码面：解析包 try/except 且回落声明值（fail-closed 时序不变）",
           n_res == 1 and n_fb == 1 and 0 <= i_t < i_f
           and "except Exception:" in win,
           {"resolve": n_res, "fallback": n_fb,
            "window": win[-40:] if i_f > 0 else ""})


# ---------------------------------------------------------------- S3 反过度封
def s3():
    print("== S3 反过度封面：internal 照旧记账 + 原语面不被本修扩散 ==")
    with _Env() as e:
        e.write("n345d", INTERNAL_FIXTURE, None)
        sigs = e.sigs()
        hit = [((v or {}).get("sens")) for k, v in sigs.items()
               if INTERNAL_FIXTURE in k]
        _check("S3.1 ★ 新节点未声明（internal）：骨架照常记账（防「全禁」式修法）",
               bool(hit), list(sigs))
        _check("S3.1b 落账密级 = internal（有效密级真的流到了闸）",
               bool(hit) and all(s == "internal" for s in hit), hit)
    from md_cg import writelimit as _wl
    import inspect as _insp
    pc = _insp.signature(_wl.check).parameters
    pr = _insp.signature(_wl.record_accepted).parameters
    _check("S3.2 原语签名仍带 sensitivity 形参（#313 面未被本修重写）",
           "sensitivity" in pc and "sensitivity" in pr,
           {"check": sorted(pc), "record": sorted(pr)})
    with _Env() as e:
        v = _wl.check(e.cg, "未声明密级的短文本夹具", layer="contextual",
                      role="user", node_id="p345")
        sigs = e.sigs()
        has = any("未声明密级的短文本夹具" in k for k in sigs)
        _check("S3.3 直接调原语传 None 照旧记账（修法只在调用点，不扩散进原语）",
               v is None and has, (v, sorted(sigs)))


# ---------------------------------------------------------------- S4 接线面
def s4():
    print("== S4 接线面：mdcos.py 两个调用点的 sensitivity 实参是 Name _sens_eff ==")
    src = _mdcos_src()
    tree = ast.parse(src)
    for attr, gid in (("check", "S4.1"), ("record_accepted", "S4.2")):
        sites = []
        for n in ast.walk(tree):
            if (isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
                    and n.func.attr == attr
                    and isinstance(n.func.value, ast.Name)
                    and n.func.value.id == "writelimit"):
                kw = {k.arg: k.value for k in n.keywords if k.arg}
                sites.append((n.lineno, kw))
        ok = bool(sites) and all(
            isinstance(kw.get("sensitivity"), ast.Name)
            and kw["sensitivity"].id == "_sens_eff"
            for _l, kw in sites)
        detail = [(l, getattr(kw.get("sensitivity"), "id",
                              type(kw.get("sensitivity")).__name__))
                  for l, kw in sites]
        _check("%s writelimit.%s 在 mdcos.py 内每个调用点的 sensitivity 实参都是 Name _sens_eff（%d 处）"
               % (gid, attr, len(sites)), ok, detail)
    n_res = src.count("_sens_eff = self._write_sensitivity(")
    _check("S4.3 ★ _sens_eff 的单点解析恰 1 处（不另立第二份继承逻辑）",
           n_res == 1, n_res)


# ---------------------------------------------------------------- 定点变异
#: (说明, 相对仓根的路径, 原文({NL}=行尾), 替换, 预期转红的前缀元组)
_MUTATIONS = (
    ("V1 check 调用点退回只传声明值（回到 #345 病灶）",
     "md_cg/mdcos.py",
     "{NL}" + " " * 31 + "sensitivity=_sens_eff)",
     "{NL}" + " " * 31 + 'sensitivity=kw.get("sensitivity"))',
     ("S1.2", "S4.1")),
    ("V2 record 调用点退回只传声明值",
     "md_cg/mdcos.py",
     " " * 47 + "sensitivity=_sens_eff)",
     " " * 47 + 'sensitivity=kw.get("sensitivity"))',
     ("S1.2", "S4.2")),
    ("V3 解析不继承：eff 恒等于声明值（lambda 吞掉单点解析）",
     "md_cg/mdcos.py",
     "_sens_eff = self._write_sensitivity(",
     "_sens_eff = (lambda _n, _d: _d)(",
     ("S1.2", "S4.3")),
    ("V4 回落声明值改成恒 None（源码面回退形态）",
     "md_cg/mdcos.py",
     '_sens_eff = kw.get("sensitivity")',
     "_sens_eff = None",
     ("S2.4",)),
)


def _mirror_build():
    """把仓镜像到临时目录（变异只动镜像，被测树一字不改）。

    根级模块必须一并镜像：mcp_server.py 顶部 from utf8_boot import ensure_utf8
    指向**仓库根**的 utf8_boot.py（不在 md_cg 包内）。只镜像 md_cg/ 会让镜像基线
    直接 ModuleNotFoundError 崩溃——rc≠0 而红项为 0，每条变异都「红项不足」却看不出真因。
    """
    dst = tempfile.mkdtemp(prefix="iss345_mut_")
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
    """在镜像树里跑本守卫，返回 (rc, 红项名列表, 输出尾部)。"""
    import subprocess
    env = dict(os.environ)
    env["PYTHONPATH"] = tree
    env["PYTHONUTF8"] = "1"
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    pr = subprocess.run([sys.executable, "-X", "utf8", "-m",
                         "md_cg.test_issue345_writelimit_effective"],
                        capture_output=True, text=True, encoding="utf-8",
                        errors="replace", cwd=tree, env=env, timeout=1800)
    out = (pr.stdout or "") + (pr.stderr or "")
    reds = [ln.split("FAIL ", 1)[1].strip()
            for ln in out.splitlines() if "FAIL " in ln]
    return pr.returncode, reds, out


def _mutate():
    print("!! 定点变异自证：逐条把判据改回改动前形态，守卫必须转红")
    tree = _mirror_build()
    anchor_miss = []
    try:
        rc, reds, out = _run_in(tree)
        print("  未变异镜像基线：rc=%d 红项=%d（必须 rc=0 且 0 红）" % (rc, len(reds)))
        if rc != 0 or reds:
            print(chr(10).join(out.splitlines()[-25:]))
        ok = 0
        bad = []
        for desc, rel, old_t, new_t, exp in _MUTATIONS:
            p = os.path.join(tree, rel)
            t = io.open(p, encoding="utf-8", newline="").read()
            nl = chr(13) + chr(10) if (chr(13) + chr(10)) in t else chr(10)
            old = old_t.replace("{NL}", nl)
            new = new_t.replace("{NL}", nl)
            if t.count(old) != 1:
                anchor_miss.append(desc)
                print("  ANCHOR-MISS %s —— 锚点在 %s 里命中 %d 次"
                      % (desc, rel, t.count(old)))
                continue
            bak = t
            io.open(p, "w", encoding="utf-8", newline="").write(
                t.replace(old, new, 1))
            # 同一秒内同字节长度的改写会让 CPython 复用上一版 .pyc ⇒ 每次清缓存
            for root, _dd, ff in os.walk(tree):
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
                print("  MISMATCH %s  红项=%d 指定命中=%d/%d"
                      % (desc, len(reds2), len(hit), len(exp)))
                for r in reds2[:6]:
                    print("        FAIL " + r[:150])
                if not reds2:
                    print(chr(10).join(("        | " + x)
                                       for x in out2.splitlines()[-10:]))
        print("定点变异自证：%s（%d 条不合格）"
              % ("PASS" if not bad else "FAIL", len(bad)))
        if anchor_miss:
            return 2
        return 0 if not bad else 1
    finally:
        shutil.rmtree(tree, ignore_errors=True)


def main():
    if "--mutate" in sys.argv:
        return _mutate()
    s1()
    s2()
    s3()
    s4()
    bad = [n for ok, n, _d in _RESULTS if not ok]
    print("")
    print("issue #345 结果：%d 通过 / %d 失败"
          % (len(_RESULTS) - len(bad), len(bad)))
    for n in bad:
        print("    红: " + n)
    return 0 if not bad else 1


if __name__ == "__main__":
    raise SystemExit(main())
