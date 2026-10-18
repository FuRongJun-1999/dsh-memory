# -*- coding: utf-8 -*-
"""issue #315/#313 sensitivity 全链路透传守卫（PR #316 审阅 B1/B2 返工件）。

# 功能名：sensitivity 透传链守卫（remember_gated / maintain→prefeed / MCP 分派）
# 生效条件：改动 mdcos.remember_gated / mdcos.prefeed / mdcos.maintain /
#           mcp_server._maintain_call / mcp_server mdcg_remember 分派的
#           sensitivity 接线之后必跑
# 子功能：G1 B1 回归锚（形参在场 + 带密级跑通不炸）
#         G2 fail-closed（MERGE/reinforce 支 private→internal 不落盘）
#         G3 防过修（不带 sensitivity 的既有行为零回归，含因果对照腿）
#         G4 透传真实到达（writelimit.check / forgetting.reinforce 收到的
#            是调用方传的值，不是 None；ACCEPT 支密级落进节点 fm）
# 执行：python -X utf8 -m md_cg.test_issue315_sensitivity_passthrough_guard
#       （变异自证：同命令加 --mutate）
# 验证方式：末行「N 通过 / M 失败」；每条给原始读数（返回体/落盘正文/探针实参）
# 不适用条件：只测 **sensitivity 透传链**的接线与方向判据；merge_downgrades
#             单点方向、writelimit 记账面分别由 test_issue148 /
#             test_issue313_writelimit_sensitivity 把守，不在此重复

## 背景（值守审阅 PR #316 的 B1/B2，2026-10-15）
旧分支（fix/sensitivity-passthrough-and-signer-validation @ 2bac760）在
`remember_gated` / `prefeed` 里三处写了 `sensitivity=...`，但该名字**不是形参、
不是局部变量、不是模块级名字**（AST/symtable 证实）⇒ 首次求值即 NameError（B1）。
值守同时指出更深语义缺口：`prefeed` 本身没有 sensitivity 形参，调用方无从声明
密级——**正确落点是给 prefeed 补形参并在 MCP 分派处透传**（本守卫的 G1 锚定的
正是「名字必须绑定为形参」，防旧病复发）。

main @ a15f5f2 已落 mdcos 层（prefeed 形参 + remember_gated 三处 kw.get 透传 +
直调 cg.prefeed 到位），但**生产入口链**仍断在两级：
  · `mcp_server._maintain_call` 不读 `a["sensitivity"]`（MCP 动词面
    cg(op=maintain, action=prefeed) 声明的密级整条丢弃）；
  · `mdcos.maintain` 没有 sensitivity 形参（直调 cg.maintain 的密级落 **extra
    即被丢弃）⇒ MERGE 裁决时 reinforce 收 None，
    `merge_downgrades(target, None)` 恒 False ⇒ 声明 private 的正文以
    **明文聚合行**并入 internal 节点（隔离沙箱实测，本守卫 G2 复现口径）。
"""
from __future__ import annotations

import ast
import io
import os
import shutil
import symtable
import sys
import tempfile

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO not in sys.path:
    sys.path.insert(0, _REPO)

#: 夹具模板：**≥ 200 字**（`writelimit.MAX_CONTENT`）⇒ `template_signature`
#: 返回 None ⇒ remember_gated 路径不走 CONVERGE 闸、直达 assess 的 MERGE 支
#: （与 test_issue315_merge_branch_sensitivity 同款口径）。
TPL = ("灵枢运维记录：本次把门禁卡新口令已更新为 {N}，并同步更新了值班手册与交接清单；"
       "后续把预热检查加进值班流程，把巡检脚本的日志目录改到 D 盘，确认备份窗口在凌晨三点，"
       "网络抖动期间不要触发重建；以上变更已在预发环境验证通过，观察一周无异常后同步到生产。"
       "另外记录三件待办：其一，把缓存预热脚本的并发度从四调到八并观察一周；其二，巡检告警的"
       "阈值按上周的基线重算，避免夜间误报；其三，把交接文档里的联系人表补齐并同步到共享盘。")
ANCHOR_N = "739155"

_RESULTS = []


def _check(name, cond, detail=""):
    _RESULTS.append((bool(cond), name, detail))
    print(("  PASS " if cond else "  FAIL ") + name
          + ("" if cond else ("  \u2190 " + repr(detail)[:220])))


class _Env:
    """一次性隔离沙箱（root/aux/token 全独立，档位取 B_MERGE 即合并的档）。"""

    def __init__(self):
        self.dir = tempfile.mkdtemp(prefix="iss315g_")
        self.saved = {}

    def __enter__(self):
        from md_cg import autonomy_modes as _am
        from md_cg import crypto
        # 档位字面量不入本文件（test_autonomy_modes G 组是全仓反漂移守卫）
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

    # ---- 场景动词 ----
    def seed(self, nid, content, sens="internal"):
        self.cg.add(nid, content, layer="contextual", sensitivity=sens)

    def write_gated(self, nid, content, sens, role="user"):
        from md_cg import mcp_server
        kw = {"node_id": nid, "content": content, "layer": "contextual",
              "role": role, "gated": True, "verification_basis": "test"}
        if sens:
            kw["sensitivity"] = sens
        return mcp_server._dispatch(self.cg, "mdcg_remember", kw)

    def maintain_prefeed(self, content, sens, write=True):
        kw = {"action": "prefeed", "content": content, "write": write}
        if sens:
            kw["sensitivity"] = sens
        return self.cg.maintain(**kw)

    def mcp_maintain_prefeed(self, content, sens, write=True, node_id=None):
        from md_cg import mcp_server
        kw = {"op": "maintain", "action": "prefeed", "content": content,
              "write": write}
        if node_id is not None:
            kw["node_id"] = node_id
        if sens:
            kw["sensitivity"] = sens
        return mcp_server._dispatch(self.cg, "cg", kw)

    def disk_text(self, nid):
        for root, _dd, ff in os.walk(os.environ["MDCG_ROOT"]):
            for f in ff:
                if f.endswith(".md") and f.startswith(nid):
                    return io.open(os.path.join(root, f), encoding="utf-8",
                                   errors="replace").read()
        return ""


class _Spy:
    """探针：包一层模块级函数，记录 kwargs 后照常调用（透传真实到达的读数）。"""

    def __init__(self, module, name):
        self.mod, self.name = module, name
        self.got = {}

    def __enter__(self):
        self.orig = getattr(self.mod, self.name)

        def _wrap(*a, **kw):
            self.got.update(kw)
            return self.orig(*a, **kw)
        setattr(self.mod, self.name, _wrap)
        return self

    def __exit__(self, *exc):
        setattr(self.mod, self.name, self.orig)
        return False


# ===================================================================== G1
def g1_group():
    """B1 回归锚：名字必须绑定为形参（旧分支 NameError 形态的对偶钉死）。"""
    print("== G1：B1 回归锚——sensitivity 是形参，带密级跑通不炸 ==")
    src = io.open(os.path.join(_REPO, "md_cg/mdcos.py"),
                  encoding="utf-8").read()
    st = symtable.symtable(src, "mdcos.py", "exec")

    def _fn(name):
        """递归找名为 name 的 function 作用域（方法在类作用域里，要下钻）。"""
        for ch in st.get_children():
            if ch.get_name() == name and ch.get_type() == "function":
                return ch
            try:
                sub = _fn_in(ch, name)
            except Exception:                           # noqa: BLE001
                sub = None
            if sub is not None:
                return sub
        raise KeyError(name)

    def _fn_in(tbl, name):
        for ch in tbl.get_children():
            if ch.get_name() == name and ch.get_type() == "function":
                return ch
            found = _fn_in(ch, name)
            if found is not None:
                return found
        return None

    for fname in ("prefeed", "maintain", "remember_gated"):
        tbl = _fn(fname)
        if fname == "remember_gated":
            # remember_gated 走 **kw 形态（值守允许的两选一之另一支）：
            # 判据 = 函数体内对 sensitivity 的取用确实来自 kw（AST 读码）。
            tree = ast.parse(src)
            fn = next(n for n in ast.walk(tree)
                      if isinstance(n, ast.FunctionDef) and n.name == fname)

            def _arg0_text(call):
                if call.args and isinstance(call.args[0], ast.Constant):
                    return call.args[0].value
                return None

            hits = [n for n in ast.walk(fn)
                    if isinstance(n, ast.Call)
                    and isinstance(n.func, ast.Attribute)
                    and n.func.attr == "get"
                    and isinstance(n.func.value, ast.Name)
                    and n.func.value.id == "kw"
                    and _arg0_text(n) == "sensitivity"]
            _check("G1-%s：**kw 形态取用 kw.get(\"sensitivity\")（绑定自入参）"
                   % fname, bool(hits), ast.dump(hits[0])[:120] if hits else "")
        else:
            syms = [s for s in tbl.get_symbols() if s.get_name() == "sensitivity"]
            _check("G1-%s：sensitivity 绑定为形参（symtable 实证，旧分支"
                   "NameError 形态的对偶）" % fname,
                   bool(syms) and all(s.is_parameter() for s in syms),
                   [s.get_name() for s in tbl.get_symbols()
                    if "sens" in s.get_name()])

    # 行为腿：两条路径带 sensitivity="private" 跑通不抛（旧分支在此直接炸）。
    with _Env() as e:
        A = TPL.format(N=ANCHOR_N)
        B = TPL.format(N="739900")
        e.seed("anch", A, "internal")
        try:
            r1 = e.cg.remember_gated("n_g1a", B, layer="contextual",
                                     sensitivity="private")
            ok1 = isinstance(r1, dict) and "verdict" in r1
        except (NameError, TypeError) as ex:              # noqa: BLE001
            r1, ok1 = {"exc": repr(ex)}, False
        _check("G1-行为：remember_gated 带 sensitivity 跑通不抛 NameError/TypeError",
               ok1, r1)
        try:
            r2 = e.maintain_prefeed(TPL.format(N="739901"), "private")
            ok2 = isinstance(r2, dict) and "decision" in r2
        except (NameError, TypeError) as ex:              # noqa: BLE001
            r2, ok2 = {"exc": repr(ex)}, False
        _check("G1-行为：prefeed(MERGE) 经 maintain 带 sensitivity 跑通不抛",
               ok2 and r2.get("decision") == "reinforce", r2)


# ===================================================================== G2
def g2_group():
    """B2：MERGE/reinforce 支 sensitivity=private 目标 internal ⇒ fail-closed 不落盘。"""
    print("== G2：fail-closed——private 并入 internal 不落盘（三条入口）==")
    # G2a remember_gated 的 MERGE 支（经 MCP mdcg_remember，生产主通道）
    with _Env() as e:
        A, B = TPL.format(N=ANCHOR_N), TPL.format(N="739902")
        rA = e.write_gated("n_anchor", A, "internal")
        rB = e.write_gated("n_priv", B, "private")
        rein = rB.get("reinforced") or {}
        _check("G2a-1 remember_gated MERGE 支：裁决确为 MERGE",
               (rB.get("gate") or {}).get("verdict") == "MERGE"
               and rA.get("ok") is True, (rB.get("gate"), rA.get("ok")))
        _check("G2a-2 fail-closed：merge_downgrade_refused + 不追加聚合行",
               rein.get("error") == "merge_downgrade_refused"
               and (rein.get("content_sink") or {}).get("action")
               != "appended", rein)
        _check("G2a-3 盘上与正文都不含 private 独有串",
               "739902" not in e.disk_text("n_anchor")
               and "739902" not in ((e.cg.get("n_anchor") or {})
                                    .get("content") or ""), "")

    # G2b maintain→prefeed 的 reinforce 支（直调面，修前实测泄漏路）
    with _Env() as e:
        A, B = TPL.format(N=ANCHOR_N), TPL.format(N="739903")
        e.seed("anch", A, "internal")
        r = e.maintain_prefeed(B, "private")
        rein = r.get("reinforced") or {}
        node = e.cg.get("anch") or {}
        _check("G2b-1 maintain/prefeed：裁决确为 reinforce（走的就是本支）",
               r.get("decision") == "reinforce"
               and r.get("duplicate_with") == "anch", r)
        _check("G2b-2 fail-closed：merge_downgrade_refused + 正文不含 private 串",
               rein.get("error") == "merge_downgrade_refused"
               and "739903" not in (node.get("content") or ""), rein)
        _check("G2b-3 盘上不含 private 独有串（明文未落盘）",
               "739903" not in e.disk_text("anch"), "")

    # G2c 同款经 MCP 动词面（cg op=maintain——本批修的分派点）
    with _Env() as e:
        A, B = TPL.format(N=ANCHOR_N), TPL.format(N="739904")
        e.seed("anch", A, "internal")
        r = e.mcp_maintain_prefeed(B, "private")
        rein = r.get("reinforced") or {}
        node = e.cg.get("anch") or {}
        _check("G2c-1 MCP 面 maintain/prefeed：裁决确为 reinforce",
               r.get("decision") == "reinforce", r)
        _check("G2c-2 fail-closed：merge_downgrade_refused + 正文/盘上无 private 串",
               rein.get("error") == "merge_downgrade_refused"
               and "739904" not in (node.get("content") or "")
               and "739904" not in e.disk_text("anch"), rein)


# ===================================================================== G3
def g3_group():
    """防过修：不带 sensitivity 的既有行为零回归（因果对照腿）。"""
    print("== G3：防过修——不声明密级时既有行为零回归 ==")
    with _Env() as e:
        A, B = TPL.format(N=ANCHOR_N), TPL.format(N="739905")
        e.seed("anch", A, "internal")
        r = e.maintain_prefeed(B, None)               # 不带 sensitivity
        rein = r.get("reinforced") or {}
        node = e.cg.get("anch") or {}
        _check("G3-1 maintain/prefeed 不带密级：照常并入（聚合行追加、无错误）",
               r.get("decision") == "reinforce"
               and rein.get("error") is None
               and "739905" in (node.get("content") or ""), rein)

    with _Env() as e:
        A, B = TPL.format(N=ANCHOR_N), TPL.format(N="739906")
        e.write_gated("n_anchor", A, "internal")
        r = e.write_gated("n_priv", B, "internal")    # 同密级声明照常并入
        rein = r.get("reinforced") or {}
        _check("G3-2 remember_gated 同密级（internal→internal）照常并入",
               (r.get("gate") or {}).get("verdict") == "MERGE"
               and rein.get("error") is None
               and rein.get("merge_count") == 1, rein)


# ===================================================================== G4
def g4_group():
    """透传真实到达：探针断言下游单点收到的是调用方传的值（不是 None）。"""
    print("== G4：透传真实到达（探针实参读数）==")
    from md_cg import forgetting as F
    from md_cg import writelimit as W

    with _Env() as e:                                   # G4a remember 链
        with _Spy(W, "check") as sp:
            e.write_gated("n_p4a", TPL.format(N="739907"), "private")
        _check("G4a mdcg_remember(gated) → writelimit.check 收到 private",
               sp.got.get("sensitivity") == "private", sp.got)

    with _Env() as e:                                   # G4b 直调 prefeed
        e.seed("anch", TPL.format(N=ANCHOR_N), "internal")
        with _Spy(F, "reinforce") as sp:
            e.cg.prefeed(TPL.format(N="739908"), write=True,
                         sensitivity="private")
        _check("G4b cg.prefeed(sensitivity=) → reinforce 收到 private",
               sp.got.get("sensitivity") == "private", sp.got)

    with _Env() as e:                                   # G4c maintain 直调
        e.seed("anch", TPL.format(N=ANCHOR_N), "internal")
        with _Spy(F, "reinforce") as sp:
            e.maintain_prefeed(TPL.format(N="739909"), "private")
        _check("G4c cg.maintain(action=prefeed, sensitivity=) → reinforce 收到 private",
               sp.got.get("sensitivity") == "private", sp.got)

    with _Env() as e:                                   # G4d MCP 动词面
        e.seed("anch", TPL.format(N=ANCHOR_N), "internal")
        with _Spy(F, "reinforce") as sp:
            e.mcp_maintain_prefeed(TPL.format(N="739910"), "private")
        _check("G4d MCP cg(op=maintain,prefeed,sensitivity=) → reinforce 收到 private",
               sp.got.get("sensitivity") == "private", sp.got)

    with _Env() as e:                                   # G4e ACCEPT 全链
        r = e.mcp_maintain_prefeed(TPL.format(N="739911"), "private",
                                   node_id="n_acc")
        fm = ((e.cg.get("n_acc") or {}).get("frontmatter") or {}) \
            if r.get("written") == "n_acc" else {}
        _check("G4e MCP 面 ACCEPT 支全链：written 落盘且节点 fm.sensitivity=private",
               r.get("written") == "n_acc"
               and fm.get("sensitivity") == "private",
               (r.get("written"), fm.get("sensitivity")))


# ===================================================================== 变异
#: (说明, 相对仓根路径, 原文, 替换, 预期转红的判据前缀元组)
#: 三处透传回退（恢复 main @ 0e17513 的断链形态）⇒ G2/G4 必红、G1 仍绿
#: （本实现回退后是「恒 None」而非 NameError——G1 锚定的是透传缺失形态的
#: 对偶：形参在场性，回退只删调用点实参，不动形参）。
_CRLF = "\r\n"
_MUTATIONS = (
    ("M1 mdcos.maintain 不再向 prefeed 转发密级（回到 main 形态）",
     "md_cg/mdcos.py",
     _CRLF + " " * 32 + "sensitivity=sensitivity)",
     _CRLF + " " * 32 + ")",
     ("G2b", "G2c", "G4c", "G4d", "G4e")),
    ("M2 mcp_server._maintain_call 不再透传 a['sensitivity']（回到 main 形态）",
     "md_cg/mcp_server.py",
     " " * 8 + 'sensitivity=a.get("sensitivity"),' + _CRLF
     + " " * 8 + 'min_conf=a.get("min_conf"),',
     " " * 8 + 'min_conf=a.get("min_conf"),',
     ("G2c", "G4d", "G4e")),
    # issue #543（2026-10-17）：本锚点原为 16 空格，而 940c7a69 给 reinforce 调用
    # 套了 `with merge_rmw_lock(self):`（mdcos.py:5511）⇒ 目标行缩进从 16 变 20，
    # 锚点命中 0 次、--mutate 恒 FAIL。改 20 后命中 1 次（M3 报红项 6，前缀命中 5/5）。
    # 教训：**变异锚点依赖缩进，而缩进会随「套一层 with/try」这类无关重构改变** ——
    # 故锚点要么带上下文行定位（不只靠空白），要么在每次改缩进的提交里同步（第 111 条）。
    ("M3 mdcos.prefeed 的 reinforce 支丢密级（a15f5f2 接线点，同族防线）",
     "md_cg/mdcos.py",
     _CRLF + " " * 20 + "sensitivity=sensitivity)",
     _CRLF + " " * 20 + ")",
     ("G2b", "G2c", "G4b", "G4c", "G4d")),
)


def _mirror_build():
    """仓镜像到临时目录（变异只动镜像；根级 utf8_boot.py 必须随行）。"""
    dst = tempfile.mkdtemp(prefix="iss315g_mut_")
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
                         "md_cg.test_issue315_sensitivity_passthrough_guard"],
                        capture_output=True, text=True, encoding="utf-8",
                        errors="replace", cwd=tree, env=env, timeout=1800)
    out = (pr.stdout or "") + (pr.stderr or "")
    reds = [ln.split("FAIL ", 1)[1].strip()
            for ln in out.splitlines() if "FAIL " in ln]
    return pr.returncode, reds, out


def _mutate():
    print("!! 定点变异自证：逐条把透传回退成 main 形态，G2/G4 必红、G1 必绿")
    tree = _mirror_build()
    try:
        rc, reds, out = _run_in(tree)
        print("  未变异镜像基线：rc=%d 红项=%d（必须 rc=0 且 0 红）" % (rc, len(reds)))
        if rc != 0 or reds:
            print(chr(10).join(out.splitlines()[-25:]))
        bad = []
        for desc, rel, old, new, exp in _MUTATIONS:
            p = os.path.join(tree, rel)
            t = io.open(p, encoding="utf-8", newline="").read()
            if t.count(old) != 1:
                bad.append(desc)
                print("  ANCHOR-MISS %s —— 锚点在 %s 里命中 %d 次"
                      % (desc, rel, t.count(old)))
                continue
            bak = t
            io.open(p, "w", encoding="utf-8", newline="").write(
                t.replace(old, new, 1))
            # 同秒同字节长度改写会让 CPython 复用旧 .pyc ⇒ 每次清缓存
            for root, dd, ff in os.walk(tree):
                if os.path.basename(root) == "__pycache__":
                    shutil.rmtree(root, ignore_errors=True)
            rc2, reds2, out2 = _run_in(tree)
            io.open(p, "w", encoding="utf-8", newline="").write(bak)
            hit = [p for p in exp if any(r.startswith(p) for r in reds2)]
            g1_red = [r for r in reds2 if r.startswith("G1")]
            # 判据：每个指定前缀**至少**命中一条红（同前缀多条红都算命中，
            # 如 G2b-2/G2b-3 同属 G2b），且 G1（B1 回归锚）必须保持绿。
            ok = (rc2 != 0 and len(hit) == len(exp) and not g1_red)
            if ok:
                print("  OK   %s  红项=%d 指定前缀命中=%d/%d G1红=%d"
                      % (desc, len(reds2), len(hit), len(exp), len(g1_red)))
            else:
                bad.append(desc)
                print("  MISMATCH %s  红项=%d 指定前缀命中=%d/%d G1红=%d"
                      % (desc, len(reds2), len(hit), len(exp), len(g1_red)))
                for r in reds2[:8]:
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
    g1_group()
    g2_group()
    g3_group()
    g4_group()
    bad = [n for okk, n, _d in _RESULTS if not okk]
    print(chr(10) + "issue #315/#313 sensitivity 透传守卫：%d 通过 / %d 失败"
          % (len(_RESULTS) - len(bad), len(bad)))
    for n in bad:
        print("    红: " + n)
    return 0 if not bad else 1


if __name__ == "__main__":
    raise SystemExit(main())
