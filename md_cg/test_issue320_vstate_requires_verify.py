# -*- coding: utf-8 -*-
# 功能名：写入面自带的验证态声明必须持 verify op（issue #320）
# 生效条件：python -X utf8 -m md_cg.test_issue320_vstate_requires_verify [--mutate]；被测面=md_cg/mcp_server.py 的 _cg_dispatch(op=write) + _require_verify_for_vstate
# 子功能：A 组=权限面判据（无 verify op 不得声明非中性验证态，且中性值/合法角色不被误拒）；E 组=单点存在性
# 执行：--mutate 时逐条把判据改回改动前形态，守卫必须转红（定点变异自证）
# 验证方式：全部 PASS 即通过；--mutate 下每条变异的「指定命中」须与预期一致
# 不适用条件：不判 trust 状态机合法性（属 trust.require_transition）；不覆盖「入队→accept」通道（accept 的裁决权在 admin）；不覆盖真实 stdio/令牌签发；不覆盖 POSIX 腿
"""issue #320 守卫：op=write 的参数面不得成为「无裁决权却自证已验证」的口子。

病象（修前）：verification_state 是 op=write 的公开参数，而 _cg_dispatch 只
require_op("write")。record 角色的 ops_allow 不含 verify（条约「不得自证」），
却能声明 verification_state="verified" 直接落盘：回执「✓ 已验证（方式=…）」、
importance≥0.7 触发不可遗忘保护、只读召回居首；而同一令牌调 mdcg_verify 被
AccessDenied。库层只校验状态机迁移是否合法，不看写的人有没有裁决权。
"""
import inspect
import os
import shutil
import subprocess
import sys
import tempfile

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _REPO)
from md_cg.security import Principal, AccessDenied  # noqa: E402
from md_cg import tokens as _tk  # noqa: E402
from md_cg import trust  # noqa: E402  （#528：落盘验证态断言需要）

FAILS = []


def _check(name, cond, detail=""):
    if cond:
        print("  PASS " + name)
    else:
        print("  FAIL " + name + "  " + str(detail)[:200])
        FAILS.append(name)


def _ccg(port):
    return chr(10).join(["# 功能名：生产端口 " + port, "# 生效条件：服务启动时读取",
                         "# 子功能：监听", "# 执行：绑定 " + port,
                         "# 验证方式：外部裁决", "# 不适用条件：无"])


def _mk(role):
    sp = _tk.role_spec(role)
    return Principal(clearance=sp["clearance_cap"], can_write=sp["can_write"],
                     can_admin=sp["can_admin"], role=role,
                     layers_allow=sp["layers_allow"], ops_allow=sp["ops_allow"])


_TMP = tempfile.mkdtemp(prefix="iss320_")
os.environ.update({"MDCG_ROOT": _TMP + "/brain", "MDCG_STATE_ROOT": _TMP + "/state",
                   "MDCG_AUX_ROOT": _TMP + "/auxstore",
                   "MDCG_DATA_ROOT": _TMP + "/datastore",
                   "MDCG_EXPORT_ROOT": _TMP, "MDCG_SUSTAIN": "0", "MDCG_SLEEP": "0"})
from md_cg.mdcos import MdCGSecure  # noqa: E402
from md_cg import mcp_server as _ms  # noqa: E402


def _try_write(role, nid, layer="knowledge", **extra):
    """返回 (ok, 出错类型/None, 盘面是否有该节点)。"""
    cg = MdCGSecure(_TMP + "/brain", principal=_mk(role), autoflush=1)
    a = {"op": "write", "node_id": nid, "content": _ccg(nid),
         "content_kind": "text", "layer": layer, "role": "user",
         "sensitivity": "internal", "importance": 0.95, "gated": False}
    a.update(extra)
    try:
        r = _ms._dispatch(cg, "cg", a)
        err = None
        ok = bool(r.get("ok") and r.get("committed"))
    except AccessDenied as e:
        ok, err = False, "AccessDenied:" + str(e)[:70]
    except Exception as e:                      # noqa: BLE001
        ok, err = False, type(e).__name__ + ":" + str(e)[:70]
    on_disk = (cg.get(nid) or {}).get("frontmatter") is not None
    cg.close()
    return ok, err, on_disk


# #528：取「**落盘后**的验证态」——照 _try_write:78 的既成取法（`(cg.get(nid) or {}).get("frontmatter")`），
# **不改 _try_write 的返回元组**（那会让 A1–A6 六处解包 ValueError）。
# ★ 新函数先自证（见 A 组后的 V 组），再用于 A7/A8 —— 「先证工具可用、再证被测物」。
def _vstate_after(role, nid):
    """写入后落盘的验证态（`trust.state_of` 对缺字段按 unverified）。"""
    cg = MdCGSecure(_TMP + "/brain", principal=_mk(role), autoflush=1)
    fm = (cg.get(nid) or {}).get("frontmatter") or {}
    cg.close()
    return trust.state_of(fm)


print("== A 组：权限面判据 ==")
_ok1, _e1, _d1 = _try_write("record", "n_a1", verification_state="verified")
_check("A1 record（无 verify op）声明 verified → 拒（AccessDenied）",
       (not _ok1) and _e1 and _e1.startswith("AccessDenied"), (_ok1, _e1))
_check("A2 同上：被拒后盘面无该节点（不落半条）", _d1 is False, _d1)

_ok3, _e3, _d3 = _try_write("record", "n_a3", verification_state="unverified")
_check("A3 record 显式声明**中性值** unverified → 放行（不误拦存量调用）",
       _ok3, (_ok3, _e3, _d3))
_ok4, _e4, _d4 = _try_write("record", "n_a4")
_check("A4 record 不带该参数 → 放行", _ok4, (_ok4, _e4, _d4))
_ok5, _e5, _d5 = _try_write("record", "n_a5", verification_state="doubted")
_check("A5 record 声明 doubted（非中性、非 verified）→ 同样拒",
       (not _ok5) and _e5 and _e5.startswith("AccessDenied"), (_ok5, _e5))
_ok6, _e6, _d6 = _try_write("record", "n_a6", verification_state="whatever")
_check("A6 record 声明未知取值 → 同样拒（fail-closed，不依赖库层兜底）",
       (not _ok6) and _e6 and _e6.startswith("AccessDenied"), (_ok6, _e6))

# verify 角色的 layers_allow 只有 rejected/contextual（不得改被验证内容），
# 故本腿用 contextual —— 否则会撞层闸、把「层不允许」误读成「参数面拦住」。
_ok7, _e7, _d7 = _try_write("verify", "n_a7", layer="contextual",
                            verification_state="verified")
_check("A7 verify 角色（有 verify op）声明 verified → 放行（合法路径不误拒）",
       _ok7, (_ok7, _e7, _d7))
# #528：**数据面**补一条 —— 「放行」是权限面事实，「落盘真的 verified」是数据面事实，两者不同。
#   本条防 `#320` 那类库层覆盖：若 `mdcg.add` 忽略 verification_state（如加 want_vstate=None）⇒ 本条红。
_vs7 = _vstate_after("verify", "n_a7")
_check("A7b 且**落盘**也是 verified（#528：防库层一律忽略）",
       _vs7 == "verified", _vs7)
_ok8, _e8, _d8 = _try_write("designer", "n_a8", verification_state="verified")
_check("A8 designer 声明 verified → 放行", _ok8, (_ok8, _e8, _d8))
_vs8 = _vstate_after("designer", "n_a8")
_check("A8b 且**落盘**也是 verified（#528：防库层一律忽略）",
       _vs8 == "verified", _vs8)

print("== V 组：新探针自证（先证工具可用、再证被测物）==")
_check("V1 _vstate_after 对「未传该字段」的节点返 unverified（防它恒返某值）",
       _vstate_after("designer", "n_a8") == "verified"
       and _vstate_after("designer", "n_a4") == "unverified",
       (_vstate_after("designer", "n_a8"), _vstate_after("designer", "n_a4")))

print("== E 组：单点存在性 ==")
_check("E1 _require_verify_for_vstate 是模块级可调用单点",
       callable(getattr(_ms, "_require_verify_for_vstate", None)), "")
_src = inspect.getsource(_ms._cg_dispatch)
_check("E2 _cg_dispatch 体内仍在 op=write 分支调用该单点（接线点未脱焊）",
       "_require_verify_for_vstate(_p, a)" in _src
       and 'op == "write"' in _src, [l for l in _src.splitlines()
                                     if "_require_verify_for_vstate" in l])
_hs = inspect.getsource(_ms._require_verify_for_vstate)
_check("E3 单点内要求的是 verify（而不是 write 等粗粒度词）",
       'require_op("verify")' in _hs, [l for l in _hs.splitlines()
                                       if "require_op" in l])

shutil.rmtree(_TMP, ignore_errors=True)

print("")
if FAILS:
    print("issue #320 结果：%d 失败" % len(FAILS))
else:
    print("issue #320 结果：全部通过")


_MUTATIONS = (
    ("V1 去掉 _cg_dispatch 里的参数面调用（回到只查 op 名）",
     "md_cg/mcp_server.py",
     chr(13) + chr(10) + "        _require_verify_for_vstate(_p, a)",
     chr(13) + chr(10) + "        pass  # 变异：接线脱焊（留 pass 保语法，否则 if 体只剩注释 = IndentationError）",
     ("A1", "A5", "A6")),
    ("V2 要求写成粗粒度 write（record 有 write ⇒ 形同虚设）",
     "md_cg/mcp_server.py",
     '    p.require_op("verify")',
     '    p.require_op("write")',
     ("A1", "A5", "A6")),
    ("V3 只拦 verified 字面量（丢掉「非中性一律」的普适性）",
     "md_cg/mcp_server.py",
     "    if not _raw or _raw == _neutral:",
     '    if _raw != "verified":',
     ("A5", "A6")),
    ("V4 中性值也被拦（过度收紧，存量调用被误伤）",
     "md_cg/mcp_server.py",
     "    if not _raw or _raw == _neutral:",
     "    if not _raw:",
     ("A3",)),
)


def _mirror_build():
    dst = tempfile.mkdtemp(prefix="iss320_mut_")
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
    env = dict(os.environ)
    env["PYTHONPATH"] = tree
    env["PYTHONUTF8"] = "1"
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    pr = subprocess.run([sys.executable, "-X", "utf8", "-m",
                         "md_cg.test_issue320_vstate_requires_verify"],
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
            t = open(p, encoding="utf-8", newline="").read()
            if t.count(old) != 1:
                bad.append("%s —— 锚点在 %s 里命中 %d 次" % (desc, rel, t.count(old)))
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