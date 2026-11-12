# -*- coding: utf-8 -*-
"""issue #313 守卫：加密级正文的**明文骨架**不得落 `_writelimit.json`，且生产调用方必须把密级传进限流闸。

病象（报告逐字复核）：`writelimit.check` / `record_accepted` 的形参表里**有** `sensitivity`
（`#148` 修复建议第 1 条加的），但唯一的生产调用方 `mdcos.remember_gated` 从未传值 ⇒
  ① 台账 `sigs[*]["sens"]` 恒为 `null`（该字段无任何读取方）；
  ② `sigs[*]["sk"]` 仍是 **private / secret 正文的去数字明文骨架**，而同一内容的节点
     正文在盘上是密文（`<!-- mdcg-enc:v1:…`）——密级越高的内容越不该以明文形式躺进
     明文台账。

修法（两半，缺一不可）：
  · 接线：`remember_gated` 的两处调用点补 `sensitivity=kw.get("sensitivity")`；
  · 收口：`writelimit._is_encrypted_level`（判据 = `crypto.ENCRYPTED_LEVELS`，与
    `forgetting.py` 的既有用法同源）为真时**不落签名**——频率限流照常。

★ 与 #315 的耦合（本守卫最要紧的一条，实测踩到）：只做「跳过签名」这一半，会**新开**
一条泄漏路——加密级不再被 `writelimit` 的 CONVERGE 先拦下，同一个近重复写入便直接
落到 `forgetting.assess` 的 MERGE 支；而 MERGE 支的 `reinforce` 若不传密级，
`security.merge_downgrades(target, None)` 恒 False ⇒ 判据放行、private 明文并入
internal 节点。故 A 组同时钉住「台账无骨架」与「#315 的 MERGE 支被挡住」两件事。

用法：python -X utf8 -m md_cg.test_issue313_writelimit_sensitivity [--mutate]
"""
from __future__ import annotations

import ast
import io
import json
import os
import shutil
import sys
import tempfile

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO not in sys.path:
    sys.path.insert(0, _REPO)

#: 夹具正文：无标题、< MAX_CONTENT(200) ⇒ template_signature 非空（骨架可算）
SECRET = "门禁卡新口令已更新为，本周五换到B座层"
SECRET_HEAD = SECRET[:12]
#: internal 对照：同形但非加密级 ⇒ 骨架**应当**照常记账（预期行为，不是缺陷）
CONTROL = "内部门禁卡新口令已更新为，下周一换到C座层"

_RESULTS = []


def _check(name, cond, detail=""):
    _RESULTS.append((bool(cond), name, detail))
    print(("  PASS " if cond else "  FAIL ") + name
          + ("" if cond else ("  \u2190 " + repr(detail)[:220])))


class _Env:
    """隔离的库根 + 加密级可用所需的主密钥（不碰 ~/.mdcg、不碰真实库）。"""

    def __init__(self):
        self.dir = tempfile.mkdtemp(prefix="iss313_")
        self.saved = {}

    def __enter__(self):
        from md_cg import autonomy_modes as _am
        from md_cg import crypto
        # 档位字面量不入本文件（test_autonomy_modes G 组是全仓反漂移守卫）：
        # 取 MATRIX 里「B 合并判 ALLOW」的那一档，等价于文档里的 full 档。
        self.mode = next(m for m in _am.AUTONOMY_MODES
                         if (_am.MATRIX.get(m) or {}).get(_am.B_MERGE)
                         == _am.ALLOW)
        env = {"MDCG_ROOT": self.dir + "/brain",
               "MDCG_STATE_ROOT": self.dir + "/state",
               "MDCG_AUX_ROOT": self.dir + "/auxstore",
               "MDCG_DATA_ROOT": self.dir + "/data",
               "MDCG_EXPORT_ROOT": self.dir,
               "MDCG_TOKEN_FILE": self.dir + "/auxstore/tokens.json",
               "MDCG_SUSTAIN": "0", "MDCG_SLEEP": "0",
               _am.AUTONOMY_ENV_KEYS["mode"]: self.mode,
               crypto.MASTER_ENV: "ab" * 32}
        for k, v in env.items():
            self.saved[k] = os.environ.get(k)
            os.environ[k] = v
        from md_cg.mdcos import MdCGSecure
        from md_cg.security import Principal
        self.cg = MdCGSecure(os.environ["MDCG_ROOT"],
                             principal=Principal(clearance="secret",
                                                 can_admin=True),
                             autoflush=1)
        self.ledger = os.path.join(os.environ["MDCG_ROOT"], "_writelimit.json")
        return self

    def __exit__(self, *exc):
        try:
            self.cg.close()
        except Exception:                               # noqa: BLE001
            pass
        for k, v in self.saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        shutil.rmtree(self.dir, ignore_errors=True)
        return False

    # ---- 读数 ----
    def ledger_text(self):
        if not os.path.exists(self.ledger):
            return ""
        return io.open(self.ledger, encoding="utf-8", errors="replace").read()

    def sigs(self):
        t = self.ledger_text()
        if not t:
            return {}
        try:
            return json.loads(t).get("sigs") or {}
        except Exception:                               # noqa: BLE001
            return {}

    def node_files(self):
        out = []
        for root, _dd, ff in os.walk(os.environ["MDCG_ROOT"]):
            for f in ff:
                if f.endswith(".md"):
                    out.append(os.path.join(root, f))
        return out

    def write(self, nid, content, sens, role="user"):
        from md_cg import mcp_server
        kw = {"node_id": nid, "content": content, "layer": "contextual",
              "role": role, "gated": True, "verification_basis": "test"}
        if sens:
            kw["sensitivity"] = sens
        return mcp_server._dispatch(self.cg, "mdcg_remember", kw)


# ------------------------------------------------------------------ 源码清单
def _call_sites(rel, attr):
    """AST 取 `X.<attr>(...)` 调用点的 (行号, 关键字实参集合)——不读码、不猜。"""
    p = os.path.join(_REPO, rel)
    tree = ast.parse(io.open(p, encoding="utf-8").read())
    out = []
    for n in ast.walk(tree):
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) \
                and n.func.attr == attr:
            out.append((n.lineno, {k.arg for k in n.keywords if k.arg}))
    return out

# ------------------------------------------------------------------ A 组：缺陷面
def a_group():
    print("== A 组：加密级正文的明文骨架不得落台账（端到端）==")
    with _Env() as e:
        r = e.write("sec313", SECRET, "private")
        _check("A0 前提：private 写入成功落盘", r.get("ok") is True, r)
        txt = e.ledger_text()
        _check("A1 台账已建立（限流闸确实跑过）", bool(txt), e.ledger)
        _check("A2 台账**不含** private 正文的明文骨架",
               SECRET_HEAD not in txt, txt[:200])
        _check("A3 加密级不落签名（sigs 里无该条目）",
               not any("门禁卡新口令" in k for k in e.sigs()),
               sorted(e.sigs()))
        # 前提复核：正文本该是密文——若这条不成立，「台账里躺明文骨架」的对比就
        # 无从谈起（说明本机没配主密钥），必须先排除这种解释。
        enc = [f for f in e.node_files()
               if "<!-- mdcg-enc:v1:" in io.open(f, encoding="utf-8",
                                                 errors="replace").read()]
        _check("A4 前提：private 节点正文在盘上是密文（加密级确实生效）",
               len(enc) == 1, [os.path.basename(f) for f in e.node_files()])
        # 与 #315 的耦合：跳过签名后 CONVERGE 不再兜底，MERGE 支必须自己挡住。
        r2 = e.write("sec313b", SECRET + "，另加一句用于制造同模板第二次写入",
                     "private")
        _check("A5 二次同模板写入不把明文追加进任何低密级节点",
               all(SECRET_HEAD not in io.open(f, encoding="utf-8",
                                             errors="replace").read()
                   for f in e.node_files() if "enc" not in f), r2.get("verdict"))


# ------------------------------------------------------------------ K 组：保持不变面
def k_group():
    print("== K 组：非加密级与限流语义必须逐位不变 ==")
    with _Env() as e:
        e.write("int313", CONTROL, "internal")
        txt = e.ledger_text()
        _check("K1 internal 级骨架**照常**记账（预期行为，未被本修波及）",
               CONTROL[:12] in txt, txt[:200])
        _check("K2 internal 级的 sens 记录为声明值",
               any(v.get("sens") == "internal" for v in e.sigs().values()),
               e.sigs())

    with _Env() as e:
        # 限流（步骤 1）必须对加密级照常生效：超过 RATE_MAX 条后转 DEFER。
        from md_cg import writelimit as _wl
        vds = [e.write("rl%d" % i, "限流夹具 %d：这是一条用于触发频率限制的短文本" % i,
                       "private").get("verdict") for i in range(_wl.RATE_MAX + 3)]
        _check("K3 加密级的频率限流照常生效（跳过签名 ≠ 跳过限流）",
               "DEFER" in vds, vds)
        _check("K4 限流窗口仍按 (layer, role) 记账",
               bool((json.loads(e.ledger_text()).get("rate") or {})),
               e.ledger_text()[:160])

    with _Env() as e:
        from md_cg import writelimit as _wl
        # check 的返回值面：加密级仍「放行」（None），不因跳过签名而改判。
        v = _wl.check(e.cg, SECRET, layer="contextual", role="user",
                      node_id="p1", sensitivity="private")
        _check("K5 加密级 check 仍返回 None（放行；不新造裁决）", v is None, v)
        _check("K6 判据单一：template_signature 对加密级仍可算（只是不落盘）",
               bool(_wl.template_signature(SECRET)), _wl.template_signature(SECRET))
        _check("K7 非加密级 check 行为不变（返回 None）",
               _wl.check(e.cg, CONTROL, layer="contextual", role="user",
                         node_id="p2", sensitivity="internal") is None)
        _check("K8 未声明密级时行为不变（None 非加密级 ⇒ 照旧记账）",
               _wl.check(e.cg, "未声明密级的短文本夹具", layer="contextual",
                         role="user", node_id="p3") is None)
        # K9 是**源码面**判据（判「真源唯一」而非行为）——硬编码一份 ("private",
        # "secret") 也能让 K10 全绿，却是在立第二份真源（纪律 #12）。
        _wl_src = io.open(os.path.join(_REPO, "md_cg/writelimit.py"),
                          encoding="utf-8").read()
        # 安全重构 P1：真源由「常量 ENCRYPTED_LEVELS」收口为「唯一谓词
        # crypto.is_encrypted_level」——判据仍是「不另立第二份真源」，只是锚到谓词。
        _check("K9 加密级判据同源于 crypto.is_encrypted_level（不另立第二份真源）",
               "from .crypto import is_encrypted_level" in _wl_src
               and '("private", "secret")' not in _wl_src,
               [x for x in _wl_src.splitlines() if "ENCRYPTED_LEVELS" in x])
        _check("K10 判据行为面：private/secret 为真，internal/None/非串为假",
               _wl._is_encrypted_level("private")
               and _wl._is_encrypted_level("secret")
               and not _wl._is_encrypted_level("internal")
               and not _wl._is_encrypted_level(None)
               and not _wl._is_encrypted_level(123), "判据面")


# ------------------------------------------------------------------ E 组：接线清单
def e_group():
    print("== E 组：生产调用方必须把密级传进限流闸（落盘点清单）==")
    for attr, must in (("check", "sensitivity"), ("record_accepted", "sensitivity")):
        sites = _call_sites("md_cg/mdcos.py", attr)
        _check("E1 %s 在 mdcos.py 内的每个调用点都传 %s（%d 处）"
               % (attr, must, len(sites)),
               bool(sites) and all(must in k for _l, k in sites),
               [(l, sorted(k)) for l, k in sites])
    sig = _call_sites("md_cg/mdcos.py", "prefeed")
    _check("E2 prefeed 入口在 mdcos.py 内有调用点（清单非空 = 判据有效）",
           bool(sig), sig)
    src = io.open(os.path.join(_REPO, "md_cg/mdcos.py"), encoding="utf-8").read()
    _check("E3 prefeed 形参表补了 sensitivity 槽",
           "write=False, tags=None, conditions=None, sensitivity=None)" in src)
    with _Env() as e:
        from md_cg import mcp_server
        r = mcp_server._dispatch(e.cg, "mdcg_remember", {
            "node_id": "e2e313", "content": SECRET, "layer": "contextual",
            "role": "user", "sensitivity": "private", "gated": True,
            "verification_basis": "test"})
        _check("E4 端到端（公开工具面）：台账里 sens 不再是 null 且无明文骨架",
               r.get("ok") is True and SECRET_HEAD not in e.ledger_text(), r)

# ------------------------------------------------------------------ 定点变异
#: (说明, 相对仓根的路径, 原文, 替换, 预期转红的前缀元组)
_MUTATIONS = (
    ("V1 check 不再跳过加密级签名（回到 #313 修前形态）",
     "md_cg/writelimit.py",
     "    if sig and not _is_encrypted_level(sensitivity):",
     "    if sig:",
     ("A2", "A3")),
    ("V2 record_accepted 不再跳过（ACCEPT 回填又把骨架写回台账）",
     "md_cg/writelimit.py",
     "    if not sig or _is_encrypted_level(sensitivity):",
     "    if not sig:",
     ("A2",)),
    ("V3 加密级判据恒假（形同虚设）",
     "md_cg/writelimit.py",
     "    return _iel(sensitivity)",
     "    return False",
     ("A2", "A3")),
    ("V4 生产调用方把 None 传进 check（等价于不传密级，回到 #313 病象）",
     "md_cg/mdcos.py",
     # 锚点随 #345（86b052e0）迁移：check 的实参已由 kw.get(...) 改为单点解析出的 _sens_eff；
     # 旧锚点自那以后命中 0 次，本条变异形同虚设（安全重构 P5 修复）。
     "\r\n" + " " * 31 + "sensitivity=_sens_eff)",
     "\r\n" + " " * 31 + "sensitivity=None)",
     ("A2", "A3", "E4")),
    ("V5 record_accepted 收到 None（等价于不传密级，ACCEPT 回填又把骨架写回台账）",
     "md_cg/mdcos.py",
     " " * 47 + "sensitivity=_sens_eff)",
     " " * 47 + "sensitivity=None)",
     ("A2", "A3", "E4")),
    ("V6 prefeed 的 sensitivity 槽被摘掉",
     "md_cg/mdcos.py",
     "                write=False, tags=None, conditions=None, sensitivity=None):",
     "                write=False, tags=None, conditions=None):",
     ("E3",)),
    ("V7 加密级判据另立第二份真源（硬编码字面量）",
     "md_cg/writelimit.py",
     "        from .crypto import is_encrypted_level as _iel",
     '        _iel = lambda s: isinstance(s, str) and s in ("private", "secret")',
     ("K9",)),
    ("V8 加密级判据写反：非加密级反而跳过签名",
     "md_cg/writelimit.py",
     "    if sig and not _is_encrypted_level(sensitivity):",
     "    if sig and _is_encrypted_level(sensitivity):",
     ("A2", "A3", "E4")),
)


def _mirror_build():
    """把仓镜像到临时目录（变异只动镜像，被测树一字不改）。

    根级模块必须一并镜像：`mcp_server.py` 顶部 `from utf8_boot import ensure_utf8`
    指向**仓库根**的 utf8_boot.py（不在 md_cg 包内）。只镜像 md_cg/ 会让镜像基线
    直接 ModuleNotFoundError 崩溃——rc≠0 而红项为 0，每条变异都「红项不足」却看不出真因。
    """
    dst = tempfile.mkdtemp(prefix="iss313_mut_")
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
                         "md_cg.test_issue313_writelimit_sensitivity"],
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
        print("  未变异镜像基线：rc=%d 红项=%d（必须 rc=0 且 0 红）" % (rc, len(reds)))
        if rc != 0 or reds:
            print(chr(10).join(out.splitlines()[-25:]))
        ok = 0
        bad = []
        for desc, rel, old, new, exp in _MUTATIONS:
            p = os.path.join(tree, rel)
            t = io.open(p, encoding="utf-8", newline="").read()
            if t.count(old) != 1:
                bad.append("%s —— 锚点在 %s 里命中 %d 次" % (desc, rel, t.count(old)))
                print("  ANCHOR-MISS " + desc)
                continue
            bak = t
            io.open(p, "w", encoding="utf-8", newline="").write(
                t.replace(old, new, 1))
            # 同一秒内同字节长度的改写会让 CPython 复用上一版 .pyc ⇒ 每次清缓存
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
                print("  MISMATCH %s  红项=%d 指定命中=%d/%d"
                      % (desc, len(reds2), len(hit), len(exp)))
                for r in reds2[:6]:
                    print("        FAIL " + r[:150])
                if not reds2:
                    print(chr(10).join(("        | " + x)
                                       for x in out2.splitlines()[-10:]))
        print("定点变异自证：%s（%d 条不合格）"
              % ("PASS" if not bad else "FAIL", len(bad)))
        return 0 if not bad else 1
    finally:
        shutil.rmtree(tree, ignore_errors=True)


def main():
    if "--mutate" in sys.argv:
        return _mutate()
    a_group()
    k_group()
    e_group()
    bad = [n for okk, n, _d in _RESULTS if not okk]
    print(chr(10) + "issue #313 结果：%d 通过 / %d 失败"
          % (len(_RESULTS) - len(bad), len(bad)))
    for n in bad:
        print("    红: " + n)
    return 0 if not bad else 1


if __name__ == "__main__":
    raise SystemExit(main())