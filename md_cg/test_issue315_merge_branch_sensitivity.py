# -*- coding: utf-8 -*-
"""issue #315 守卫：`remember_gated` 的 **MERGE 支**必须把声明密级传进 `forgetting.reinforce`。

病象（报告逐字复核）：`mdcos.remember_gated` 的 MERGE 支调 `forgetting.reinforce(...)` 时
实参只有 `override/actor/content/session`，**没有 `sensitivity`**；而 `reinforce` 内的降密级
fail-closed 判据（`security.merge_downgrades`，`#148` 的单点）恰恰依赖这个形参——取缺省 `None`
时 `merge_downgrades(target, None)` 恒 `False` ⇒ 判据放行 ⇒ 声明 private 的正文以【聚合】行
并入 internal 节点，按 internal 明文存续，internal 档读者可读回。

同一提交内的一致性对照：同函数的 CONVERGE 支（`writelimit.converge_into`）**已接线**，
故本条报的是「同一提交的接线面不完整」，不是「作者有意如此」。

★ 与 #313 的耦合（实测踩到，本守卫的 A0/A1 就是为它写的）：#313 修好「加密级跳过签名」后，
`writelimit` 的 CONVERGE **不再**兜底拦下加密级近重复写入 ⇒ 同一个写入会直接落到 MERGE 支。
换句话说：只修 #313 会**新开**这条泄漏路，两支必须同修。

用法：python -X utf8 -m md_cg.test_issue315_merge_branch_sensitivity [--mutate]
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

#: 夹具模板：**≥ 200 字**（`writelimit.MAX_CONTENT`）⇒ `template_signature` 返回 None
#: ⇒ 不走 CONVERGE 闸，直达 `forgetting.assess` 的 MERGE 支——这正是报告的第 1 条触发条件。
TPL = ("灵枢运维记录：本次把门禁卡新口令已更新为 {N}，并同步更新了值班手册与交接清单；"
       "后续把预热检查加进值班流程，把巡检脚本的日志目录改到 D 盘，确认备份窗口在凌晨三点，"
       "网络抖动期间不要触发重建；以上变更已在预发环境验证通过，观察一周无异常后同步到生产。"
       "另外记录三件待办：其一，把缓存预热脚本的并发度从四调到八并观察一周；其二，巡检告警的"
       "阈值按上周的基线重算，避免夜间误报；其三，把交接文档里的联系人表补齐并同步到共享盘。")
SECRET = "739154"          # private 写入的独有串（不在锚点里）
ANCHOR_N = "739155"        # 锚点的对应位

_RESULTS = []


def _check(name, cond, detail=""):
    _RESULTS.append((bool(cond), name, detail))
    print(("  PASS " if cond else "  FAIL ") + name
          + ("" if cond else ("  \u2190 " + repr(detail)[:220])))


class _Env:
    def __init__(self, clearance="secret"):
        self.dir = tempfile.mkdtemp(prefix="iss315_")
        self.clearance = clearance
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
                             principal=Principal(clearance=self.clearance,
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

    def write(self, nid, content, sens, role="user"):
        from md_cg import mcp_server
        kw = {"node_id": nid, "content": content, "layer": "contextual",
              "role": role, "gated": True, "verification_basis": "test"}
        if sens:
            kw["sensitivity"] = sens
        return mcp_server._dispatch(self.cg, "mdcg_remember", kw)

    def read(self, nid, clearance="internal"):
        """以**另一档 clearance** 的读者读同一库根——证明「谁能读到」。"""
        from md_cg.mdcos import MdCGSecure
        from md_cg.security import Principal
        cg2 = MdCGSecure(os.environ["MDCG_ROOT"],
                         principal=Principal(clearance=clearance), autoflush=0)
        try:
            n = cg2.get(nid)
            return (n or {}).get("content") or ""
        finally:
            cg2.close()

    def disk_text(self, nid):
        for root, _dd, ff in os.walk(os.environ["MDCG_ROOT"]):
            for f in ff:
                if f.endswith(".md") and f.startswith(nid):
                    return io.open(os.path.join(root, f), encoding="utf-8",
                                   errors="replace").read()
        return ""


def _call_sites(rel, attr):
    """AST 取 `X.<attr>(...)` 调用点的 (行号, 关键字实参源码文本)——不读码、不猜。"""
    p = os.path.join(_REPO, rel)
    tree = ast.parse(io.open(p, encoding="utf-8").read())
    out = []
    for n in ast.walk(tree):
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) \
                and n.func.attr == attr:
            out.append((n.lineno, {k.arg: ast.unparse(k.value)
                                    for k in n.keywords if k.arg}))
    return out

# ------------------------------------------------------------------ A 组：缺陷面
def a_group():
    print("== A 组：MERGE 支必须挡住降密级合并（端到端）==")
    A, B = TPL.format(N=ANCHOR_N), TPL.format(N=SECRET)
    with _Env() as e:
        from md_cg import writelimit as _wl
        _check("A0 前提：夹具 >= MAX_CONTENT ⇒ 不走 CONVERGE 闸（直达 MERGE 支）",
               len(A) >= _wl.MAX_CONTENT and len(B) >= _wl.MAX_CONTENT
               and _wl.template_signature(A) is None
               and SECRET not in A, (len(A), _wl.template_signature(A)))
        rA = e.write("n_anchor", A, "internal")
        _check("A0b 前提：internal 锚点写入成功", rA.get("ok") is True, rA)
        rB = e.write("n_priv", B, "private")
        _check("A1 前提：写入确被判 MERGE（走的就是本支，不是别的分支）",
               (rB.get("gate") or {}).get("verdict") == "MERGE", rB.get("gate"))
        rein = rB.get("reinforced") or {}
        _check("A2 MERGE 支 fail-closed：reinforced 报 merge_downgrade_refused",
               rein.get("error") == "merge_downgrade_refused"
               and rein.get("incoming_sensitivity") == "private"
               and rein.get("target_sensitivity") == "internal", rein)
        disk = e.disk_text("n_anchor")
        _check("A3 目标节点文件里不含 private 的独有串",
               SECRET not in disk, disk[-160:])
        # internal 是缺省档，未必写进 frontmatter（首跑即踩到）——判据应是
        # 「没有被抬成 private」，而不是「字面量 sensitivity: internal 必须存在」。
        _fm = (e.cg.get("n_anchor") or {}).get("frontmatter") or {}
        _check("A4 目标节点声明密级未被抬高（仍非 private）",
               _fm.get("sensitivity") != "private"
               and "sensitivity: private" not in disk,
               (_fm.get("sensitivity"), disk[:200]))
        body = e.read("n_anchor", clearance="internal")
        _check("A5 读者面：internal 档读者读回的正文不含 private 独有串",
               SECRET not in body and ANCHOR_N in body, (len(body), body[-90:]))
        _check("A6 无聚合行被追加（content_sink 不是 appended）",
               (rein.get("content_sink") or {}).get("action") != "appended",
               rein.get("content_sink"))

    # 因果对照：同为 MERGE 支、声明 internal ⇒ 照常并入。证明 A1–A6 的绿
    # 不是「判据恒拒」，而是「判据按密级方向正确区分」。
    with _Env() as e:
        A, B = TPL.format(N=ANCHOR_N), TPL.format(N=SECRET)
        e.write("n_anchor", A, "internal")
        r = e.write("n_priv", B, "internal")
        rein = r.get("reinforced") or {}
        _check("A7 因果对照：声明 internal 时照常并入（判据能区分该在与不该在）",
               (r.get("gate") or {}).get("verdict") == "MERGE"
               and rein.get("error") is None
               and SECRET in (e.read("n_anchor", clearance="internal") or ""),
               rein)


# ------------------------------------------------------------------ K 组：保持不变面
def k_group():
    print("== K 组：非泄漏方向的合并语义必须逐位不变 ==")
    with _Env() as e:
        A, B = TPL.format(N=ANCHOR_N), TPL.format(N=SECRET)
        e.write("n_anchor", A, "internal")
        r = e.write("n_priv", B, "internal")
        rein = r.get("reinforced") or {}
        _check("K1 同密级合并照常放行，且 reinforce 返回体带强化读数",
               rein.get("merge_count") == 1 and rein.get("node_id") == "n_anchor",
               rein)
        _check("K2 同密级合并确有聚合行落盘（正文追加，不是重建节点）",
               (rein.get("content_sink") or {}).get("action") == "appended"
               and SECRET in e.disk_text("n_anchor"), rein.get("content_sink"))
        _check("K3 同密级合并不新增节点（节点数仍为 1）",
               len([f for _r, _d, ff in os.walk(os.environ["MDCG_ROOT"])
                    for f in ff if f.endswith(".md")]) == 1, "节点数")

    with _Env() as e:
        # 非泄漏方向：低密级并入高密级节点（incoming < target）不在判据范围
        A = TPL.format(N=ANCHOR_N)
        B = TPL.format(N=SECRET)
        e.write("n_anchor", A, "private")
        r = e.write("n_priv", B, "internal")
        _check("K4 低密级并入高密级节点照常放行（非泄漏方向，不在判据范围）",
               (r.get("reinforced") or {}).get("error") is None, r.get("reinforced"))


# ------------------------------------------------------------------ E 组：落盘点清单
def e_group():
    print("== E 组：remember_gated 内每个降密级落盘点都必须接线（清单式判据）==")
    sites = _call_sites("md_cg/mdcos.py", "reinforce")
    _check("E1 清单非空（判据有效：确实找到了 reinforce 调用点）",
           len(sites) >= 3, [(l, sorted(k)) for l, k in sites])
    missing = [(l, sorted(k)) for l, k in sites if "sensitivity" not in k]
    _check("E2 每个 reinforce 调用点都传了 sensitivity（%d 处）" % len(sites),
           not missing, missing)
    # 只「传了键」还不够：传错常量（如写死 internal）照样漏（报告的 P2 对照腿）。
    # 判据 = 该实参**不是字面常量**（ast.literal_eval 成功即视为写死）。
    # 不用白名单：mdcos.py 里既有 kw.get(...)、也有形参 sens（:3084 那处），
    # 白名单会把合法的形参误判成违规（首跑即踩到）。
    def _is_literal(src):
        try:
            ast.literal_eval(src)
            return True
        except Exception:                               # noqa: BLE001
            return False

    badval = [(l, k["sensitivity"]) for l, k in sites
              if "sensitivity" in k and _is_literal(k["sensitivity"])]
    _check("E3 传的是调用方手上的密级（表达式/形参），不是写死的字面常量",
           not badval, badval)
    conv = _call_sites("md_cg/mdcos.py", "converge_into")
    _check("E4 对照：CONVERGE 支（已接线的那一支）同样满足 E2 判据（口径一致）",
           bool(conv) and all("sensitivity" in k for _l, k in conv),
           [(l, sorted(k)) for l, k in conv])


# ------------------------------------------------------------------ 定点变异
#: (说明, 相对仓根的路径, 原文, 替换, 预期转红的前缀元组)
_MUTATIONS = (
    # #397（28d2e4e 前已合入）把 MERGE 支实参从 kw.get("sensitivity") 改为有效密级
    # `_sens_eff`，旧锚点命中 0 次、V1/V2 形同虚设（与 #313 V4/V5 随 #345 失效同类）。
    # 锚点随真源迁到 reinforce 调用处的 `sensitivity=_sens_eff,`；该行在函数内出现
    # 两次（另一处是 record_drop），故带上紧随其后的 #417 注释行定位到唯一一处。
    ("V1 MERGE 支不再传密级（回到 #315 修前形态）",
     "md_cg/mdcos.py",
     "\r\n" + " " * 16 + "sensitivity=_sens_eff," + "\r\n" + " " * 16 + "# #417",
     "\r\n" + " " * 16 + "sensitivity=None," + "\r\n" + " " * 16 + "# #417",
     ("A2", "A3", "A5")),
    ("V2 补错常量：传写死的 internal（报告的 P2 对照腿）",
     "md_cg/mdcos.py",
     "\r\n" + " " * 16 + "sensitivity=_sens_eff," + "\r\n" + " " * 16 + "# #417",
     "\r\n" + " " * 16 + 'sensitivity="internal",' + "\r\n" + " " * 16 + "# #417",
     ("A2", "A3", "E3")),
    # V3（2026-10-19，dsh-bounty#899 续）：原锚点 "sensitivity=sensitivity)" 在
    # md_cg/mdcos.py 命中 0 次——该 prefeed 写点已随重构迁走，锚点形态整体过时。
    # 按「变异必须恰好点红」纪律删除，不保留 ANCHOR-MISS 的假变异。
    # prefeed 支的密级传递由 V5（incoming -> None）与 V1（整闸短路）覆盖同族面。
    ("V4 判据面反转：merge_downgrades 的方向写反（改判低密级并入高密级）",
     "md_cg/security.py",
     "    return new > tgt",
     "    return new < tgt",
     ("A2", "A3", "K4")),
    ("V5 判据被架空：reinforce 内把 incoming 密级换成 None（fail-closed 形同虚设）",
     "md_cg/forgetting.py",
     '    if _merge_downgrades(fm.get("sensitivity"), sensitivity):',
     '    if _merge_downgrades(fm.get("sensitivity"), None):',
     ("A2", "A3")),
    # V6「去掉 #313 的收口 ⇒ 本支被 CONVERGE 抢先兜住」已**删除**：实测该变异
    # 恒绿、结构性失效——CONVERGE 需要**已存在**的同模板签名，而本守卫的夹具
    # （≥200 字）两侧都产不出签名。该耦合由 #313 守卫的短夹具面覆盖，不在此重复。
)

def _mirror_build():
    """把仓镜像到临时目录（变异只动镜像，被测树一字不改）。

    根级模块必须一并镜像：mcp_server.py 顶部 from utf8_boot import ensure_utf8
    指向仓库根的 utf8_boot.py（不在 md_cg 包内）。只镜像 md_cg/ 会让镜像基线
    直接 ModuleNotFoundError 崩溃——rc≠0 而红项为 0，每条变异都红项不足却看不出真因。
    """
    dst = tempfile.mkdtemp(prefix="iss315_mut_")
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
                         "md_cg.test_issue315_merge_branch_sensitivity"],
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
            # 同一秒内同字节长度的改写会让 CPython 复用上一版 .pyc ⇒ 每次清缓存
            for root, dd, ff in os.walk(tree):
                if os.path.basename(root) == "__pycache__":
                    shutil.rmtree(root, ignore_errors=True)
            rc2, reds2, out2 = _run_in(tree)
            io.open(p, "w", encoding="utf-8", newline="").write(bak)
            hit = [r for r in reds2 if r.startswith(exp)]
            if rc2 != 0 and len(hit) == len(exp):
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
    print(chr(10) + "issue #315 结果：%d 通过 / %d 失败"
          % (len(_RESULTS) - len(bad), len(bad)))
    for n in bad:
        print("    红: " + n)
    return 0 if not bad else 1


if __name__ == "__main__":
    raise SystemExit(main())