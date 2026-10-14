# -*- coding: utf-8 -*-
"""issue #193 守卫：写入面的冲突比对范围必须并入 EXTRA_SCOPE 层。

缺陷（9c5d946a 复现 2/2）：写入路径把「写到哪层」当成了「只和哪层比」。
contextual 是 gated 写入的缺省层——同层无节点即判 BLINDSPOT「既有节点均未
声明条件」、同层只有无关节点即判 ACCEPT「无冲突」，而同一内容写 knowledge
层判 DEFER。同条件同结论槽的矛盾取值因此被静默放过。

用法：python -X utf8 -m md_cg.test_issue193_write_scope [--mutate]
"""
import os
import shutil
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

_OK = 0
_FAIL = 0
_MSGS = []


def ok(cond, msg, extra=None):
    global _OK, _FAIL
    if cond:
        _OK += 1
        print("  PASS " + msg)
    else:
        _FAIL += 1
        print("  FAIL " + msg)
        if extra is not None:
            print("       " + repr(extra)[:220])


def ccg(fn, sub, exe, cond="生产环境"):
    return ("# 功能名：%s\n# 生效条件：%s\n# 子功能：%s\n"
            "# 执行：%s\n# 验证方式：test\n# 不适用条件：无\n") % (fn, cond, sub, exe)


class _Env(object):
    """隔离根：每个用例一套临时 MDCG_* 根，互不污染。"""

    def __init__(self):
        self.d = tempfile.mkdtemp(prefix="iss193_")
        self.env = {
            "MDCG_ROOT": os.path.join(self.d, "brain"),
            "MDCG_STATE_ROOT": os.path.join(self.d, "state"),
            "MDCG_AUX_ROOT": os.path.join(self.d, "auxstore"),
            "MDCG_DATA_ROOT": os.path.join(self.d, "data"),
            "MDCG_EXPORT_ROOT": self.d,
            "MDCG_TOKEN_FILE": os.path.join(self.d, "auxstore", "tokens.json"),
            "MDCG_SUSTAIN": "0", "MDCG_SLEEP": "0"}
        self._old = {}

    def __enter__(self):
        for k, v in self.env.items():
            self._old[k] = os.environ.get(k)
            os.environ[k] = v
        from md_cg.mdcos import MdCGOS
        self.cg = MdCGOS(self.env["MDCG_ROOT"], autoflush=1)
        return self

    def __exit__(self, *a):
        try:
            self.cg.close()
        except Exception:  # noqa: BLE001
            pass
        for k, v in self._old.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        shutil.rmtree(self.d, ignore_errors=True)
        return False


KB = ccg("缓存端口", "连接配置", "Redis 端口是 6379")
KB2 = ccg("缓存端口", "连接配置", "Redis 端口是 6380")
OTHER = ccg("日志保留", "日志策略", "保留 7 天")


def _write(cg, nid, content, layer):
    return cg.add(nid, content, layer=layer, content_kind="text",
                  verification_basis="test", on_conflict="record")


def _vd(cg, content, layer, write_scope, nid="probe"):
    return cg.check_consistency(content, layer=layer, exclude=nid,
                                auto_flywheel=False, log_write=False,
                                write_scope=write_scope)


# ---------------------------------------------------------------- 缺陷面
def a_group():
    print("== A 组：写入面必须并入 knowledge 候选（缺陷面）==")
    with _Env() as e:
        _write(e.cg, "kb_port", KB, "knowledge")
        # A1：contextual 层内空 → 修前 BLINDSPOT
        r1 = _vd(e.cg, KB2, "contextual", True)
        ok(r1["verdict"] == "DEFER",
           "A1 contextual 写入面的矛盾取值判 DEFER（修前 BLINDSPOT）", r1["verdict"])
        ok(r1.get("scope_layers") == ["contextual", "knowledge"],
           "A1 scope_layers 报出实际比对层", r1.get("scope_layers"))
        # A2：contextual 层内有一条无关节点 → 修前 ACCEPT
        _write(e.cg, "ctx_other", OTHER, "contextual")
        r2 = _vd(e.cg, KB2, "contextual", True)
        ok(r2["verdict"] == "DEFER",
           "A2 同层有无关节点时仍判 DEFER（修前 ACCEPT「无冲突」）", r2["verdict"])
        ok(any(c.get("with") == "kb_port" for c in r2.get("conflicts") or []),
           "A2 冲突条目点名 knowledge 节点 kb_port",
           [c.get("with") for c in r2.get("conflicts") or []])
        # A3：对照——同内容写 knowledge 层本来判 DEFER（行为不得回退）
        r3 = _vd(e.cg, KB2, "knowledge", True)
        ok(r3["verdict"] == "DEFER", "A3 对照：写 knowledge 层判 DEFER", r3["verdict"])
        ok(r3.get("scope_layers") == ["knowledge"],
           "A3 同层写入 scope_layers 仍是单层", r3.get("scope_layers"))


# ---------------------------------------------------------------- 保持不变面
def k_group():
    print("== K 组：只读面与其它路径必须逐位不变 ==")
    with _Env() as e:
        _write(e.cg, "kb_port", KB, "knowledge")
        # K1：只读 check 面（write_scope=False）——BLINDSPOT 照旧
        r = _vd(e.cg, KB2, "contextual", False)
        ok(r["verdict"] == "BLINDSPOT",
           "K1 只读 check 面（write_scope=False）仍判 BLINDSPOT，不扩面", r["verdict"])
        ok(r.get("scope_layers") == ["contextual"],
           "K1 只读面 scope_layers 仍报单层", r.get("scope_layers"))
        # K2：写入面但新内容**未声明条件**（自由正文 #68）→ 不扩面
        # 实测：自由正文 _new_terms pos/neg 皆空 ⇒ no_terms 闸生效。此面读数
        # 必须与只读面**逐位相同**（含 comparable）——扩面会让 scope_layers
        # 多一层、comparable 从 0 变 1，是「不扩面」的可观测判据。
        FT = "今天天气不错，随手记一笔。"
        r2a = _vd(e.cg, FT, "contextual", False)
        r2 = _vd(e.cg, FT, "contextual", True)
        ok(r2.get("scope_layers") == ["contextual"],
           "K2 未声明条件的自由正文不扩面（no_terms 闸：scope_layers 仍单层）",
           r2.get("scope_layers"))
        ok((r2["verdict"], r2.get("comparable"))
           == (r2a["verdict"], r2a.get("comparable")),
           "K2 自由正文写入面与只读面读数逐位相同（不扩面）",
           (r2["verdict"], r2.get("comparable"),
            r2a["verdict"], r2a.get("comparable")))
        # K3：未传 layer → 不扩面（无写入层可言）
        r3 = e.cg.check_consistency(KB2, layer=None, auto_flywheel=False,
                                    log_write=False, write_scope=True)
        ok(r3.get("scope_layers") is None,
           "K3 未传 layer 时 scope_layers 为 None", r3.get("scope_layers"))
        # K4：方向单向——knowledge 写入不看 contextual
        _write(e.cg, "ctx_port", KB2, "contextual")
        r4 = _vd(e.cg, KB, "knowledge", True)
        ok(r4.get("scope_layers") == ["knowledge"],
           "K4 knowledge 写入不并入 contextual（方向单向）", r4.get("scope_layers"))
        # K5：structural/anchor 不纳入
        from md_cg import consistency as _c
        ok(set(_c.EXTRA_SCOPE) == {"contextual"},
           "K5 EXTRA_SCOPE 只登记 contextual 一个来源层", sorted(_c.EXTRA_SCOPE))
        ok("structural" not in _c.EXTRA_SCOPE.get("contextual", ())
        and "anchor" not in _c.EXTRA_SCOPE.get("contextual", ()),
           "K5 目标层不含 structural/anchor（层权限语义不同，不混比）")
        # K6：同层检出逐位不变——knowledge 写 knowledge 的读数与只读面一致
        a = _vd(e.cg, KB, "knowledge", False, nid="kb_port")
        b = _vd(e.cg, KB, "knowledge", True, nid="kb_port")
        ok(a["verdict"] == b["verdict"] and a["conflict_strength"] == b["conflict_strength"],
           "K6 同层路径下 write_scope 不改变读数", (a["verdict"], b["verdict"]))
        # K7：不新增 REJECT（合法写入不得被误拦）
        r7 = _vd(e.cg, KB2, "contextual", True)
        ok(r7["verdict"] != "REJECT", "K7 写入面不产生 REJECT", r7["verdict"])


# ---------------------------------------------------------------- 端到端
def e_group():
    print("== E 组：两条写入出口的传参面（writepipe / MdCG.add / mdcos）==")
    from md_cg import writepipe as _wp
    with _Env() as e:
        _write(e.cg, "kb_port", KB, "knowledge")
        # E1：写链出口（cg(op=write) 的冲突闸）——端到端读数
        ctx = {"a": {"content": KB2, "layer": "contextual", "gated": True},
               "cg": e.cg, "nid": "ctx_port"}
        _wp._gate_consistency(ctx)
        cvd = ctx.get("cvd") or {}
        ok(cvd.get("verdict") == "DEFER",
           "E1 写链冲突闸：contextual 的矛盾取值判 DEFER（修前 BLINDSPOT）",
           cvd.get("verdict"))
        ok(cvd.get("scope_layers") == ["contextual", "knowledge"],
           "E1 写链冲突闸 scope_layers 含 knowledge", cvd.get("scope_layers"))

        # E2：MdCG.add 出口——直接捕获传给 consistency.check 的 write_scope
        seen = {}
        from md_cg import consistency as _c2
        _orig = _c2.check
        def _spy(cg, content, **kw):
            seen.update(kw)
            return {"verdict": "ACCEPT", "reason": "", "conflicts": [],
                    "conflict_strength": 0.0, "emotional": {}, "missing": [],
                    "scanned": 0, "kept": 0, "truncated": False}
        _c2.check = _spy
        try:
            e.cg.add("ctx_port2", KB2, content_kind="text",
                     verification_basis="test", layer="contextual",
                     consistency=True, on_conflict="record")
        finally:
            _c2.check = _orig
        ok(seen.get("write_scope") is True,
           "E2 MdCG.add 出口传 write_scope=True（修前不传 ⇒ 只比同层）",
           seen.get("write_scope"))

        # E3：mdcos.check_consistency 透传面
        seen2 = {}
        _orig2 = _c2.check
        def _spy2(cg, content, **kw):
            seen2.update(kw)
            return {"verdict": "ACCEPT", "reason": "", "conflicts": [],
                    "conflict_strength": 0.0, "emotional": {}, "missing": [],
                    "scanned": 0, "kept": 0, "truncated": False}
        _c2.check = _spy2
        try:
            e.cg.check_consistency(KB2, layer="contextual", write_scope=True,
                                   auto_flywheel=False, log_write=False)
        finally:
            _c2.check = _orig2
        ok(seen2.get("write_scope") is True,
           "E3 mdcos.check_consistency 透传 write_scope", seen2.get("write_scope"))
        ok(seen2.get("layer") == "contextual",
           "E3 透传面 layer 未被吞掉", seen2.get("layer"))


def main():
    print("issue #193 守卫：写入面冲突比对范围（EXTRA_SCOPE）")
    a_group()
    k_group()
    e_group()
    print("")
    print("issue #193 结果：%d 通过 / %d 失败" % (_OK, _FAIL))
    return 1 if _FAIL else 0


_MUTATIONS = (
    ("V1 EXTRA_SCOPE 退回空表：层外候选不再并入（回到「只比同层」）",
     "md_cg/consistency.py",
     'EXTRA_SCOPE = {"contextual": ("knowledge",)}',
     "EXTRA_SCOPE = {}",
     ("A1", "A2")),
    ("V2 write_scope 形同虚设：extra_layers 恒空",
     "md_cg/consistency.py",
     "                    if (write_scope and layer and not no_terms) else ())",
     "                    if False else ())",
     ("A1", "A2")),
    ("V3 no_terms 闸失效：未声明条件的自由正文也扩面",
     "md_cg/consistency.py",
     "                    if (write_scope and layer and not no_terms) else ())",
     "                    if (write_scope and layer) else ())",
     ("K2",)),
    # V4 的锚点必须**唯一**：「    scan_face += [(t[3], t[4]) for t in」在
    # consistency.py 里出现两次（保底面那行 + #193 的层外并入行），单行锚点
    # 会被 replace(...,1) 命中先出现的那条——实测本变异「红项=0」正是踩了
    # 这个坑（改的是保底面，不是 #193 的并入行）。跨行锚点在本仓还会踩
    # CRLF（表里的 \n 拼不出 \r\n）⇒ 改用**单行且唯一**的 sorted 行。
    ("V4 层外候选不并入精比面：收集了却不用",
     "md_cg/consistency.py",
     "                  sorted(extra_cand, key=lambda t: (-t[0], -t[1], str(t[3])))[:lim]]",
     "                  [][:0]]",
     ("A1", "A2", "E1")),
    ("V5 writepipe 写链出口不再传 write_scope",
     "md_cg/writepipe.py",
     "        write_scope=True,",
     "        write_scope=False,",
     ("E1",)),
    ("V6 MdCG.add 写入出口不再传 write_scope",
     "md_cg/mdcg.py",
     "                             write_scope=True,",
     "                             write_scope=False,",
     ("E2",)),
    ("V7 mdcos 不再透传 write_scope（写入面全丢）",
     "md_cg/mdcos.py",
     "            write_scope=write_scope,",
     "            write_scope=False,",
     ("E3",)),
    ("V8 目标层扩到 structural（层权限语义混比）",
     "md_cg/consistency.py",
     'EXTRA_SCOPE = {"contextual": ("knowledge",)}',
     'EXTRA_SCOPE = {"contextual": ("knowledge", "structural")}',
     ("K5",)),
)

def _mirror_build():
    """把仓库源码镜像到临时区（排除 .git 与 __pycache__），供变异跑。"""
    src = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    dst = tempfile.mkdtemp(prefix="iss193_mut_")
    for name in ("md_cg", "scripts"):
        shutil.copytree(os.path.join(src, name), os.path.join(dst, name),
                        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    # 根级模块必须一并镜像：mcp_server.py 顶部 `from utf8_boot import
    # ensure_utf8` 指向**仓库根**的 utf8_boot.py（不在 md_cg 包内）。只镜像
    # md_cg/ 会让镜像基线直接 ModuleNotFoundError 崩溃，rc≠0 而红项为 0——
    # 这种静默崩溃会让每条变异都「红项不足」而看不出真因。
    for name in sorted(os.listdir(src)):
        p = os.path.join(src, name)
        if not os.path.isfile(p):
            continue
        if name.endswith(".py") or name in ("README.md", "pyproject.toml",
                                            "package.json"):
            shutil.copy2(p, os.path.join(dst, name))
    return dst


def _reds_in(base):
    import subprocess
    env = dict(os.environ)
    env["PYTHONPATH"] = base
    env["PYTHONUTF8"] = "1"
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    p = subprocess.run([sys.executable, "-X", "utf8", "-m",
                        "md_cg.test_issue193_write_scope"],
                       capture_output=True, text=True, encoding="utf-8",
                       errors="replace", cwd=base, env=env, timeout=900)
    out = (p.stdout or "") + (p.stderr or "")
    reds = [l.strip() for l in out.splitlines()
            if l.strip().startswith("FAIL ") or l.strip().startswith("ANCHOR-MISS")]
    return p.returncode, reds, out


def _mutate_mode():
    print("!! 定点变异自证：逐条把判据改回改动前形态，守卫必须转红\n")
    base = _mirror_build()
    try:
        rc0, reds0, out0 = _reds_in(base)
        print("  未变异镜像基线：rc=%d 红项=%d（必须 rc=0 且 0 红）"
              % (rc0, len(reds0)))
        bad = []
        if rc0 != 0 or reds0:
            bad.append("镜像基线非绿")
            for l in (out0 or "").splitlines()[-14:]:
                print("      | " + l)
        for name, rel, old, new, exp in _MUTATIONS:
            p = os.path.join(base, rel)
            with open(p, encoding="utf-8", newline="") as f:
                original = f.read()
            if old not in original:
                print("  ANCHOR-MISS %s —— 锚点在 %s 里找不到" % (name, rel))
                bad.append(name + " ANCHOR-MISS")
                continue
            with open(p, "w", encoding="utf-8", newline="") as f:
                f.write(original.replace(old, new, 1))
            try:
                rc2, reds2, out2 = _reds_in(base)
            finally:
                with open(p, "w", encoding="utf-8", newline="") as f:
                    f.write(original)
            hit = [r for r in reds2 if any(e in r for e in exp)]
            crashed = "Traceback (most recent call last)" in (out2 or "")
            good = bool(hit) and not crashed
            print("  %s %s  红项=%d 指定命中=%d/%d"
                  % ("OK  " if good else "MISMATCH", name, len(reds2),
                     len(hit), len(exp)))
            for r in reds2[:4]:
                print("        " + r[:140])
            if not good:
                bad.append(name)
                if crashed:
                    print("        ——变异后崩溃——")
                    for l in (out2 or "").splitlines()[-10:]:
                        print("        | " + l)
        print("")
        if bad:
            print("定点变异自证：FAIL（%d 条不合格）" % len(bad))
            return 1
        print("定点变异自证：%d/%d PASS" % (len(_MUTATIONS), len(_MUTATIONS)))
        return 0
    finally:
        shutil.rmtree(base, ignore_errors=True)


if __name__ == "__main__":
    if "--mutate" in sys.argv:
        raise SystemExit(_mutate_mode())
    raise SystemExit(main())
