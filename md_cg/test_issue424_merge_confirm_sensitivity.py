# -*- coding: utf-8 -*-
# 功能名：confirm 档 B 类合并/汇流变更单的密级必须取**源写入有效密级**（issue #424）
# 生效条件：python -X utf8 -m md_cg.test_issue424_merge_confirm_sensitivity [--mutate]；
#           被测面＝md_cg/mdcos.py::MdCGOS._autonomy_gate_merge 的出单密级与 remember_gated 两处调用点
# 子功能：A 组＝MERGE（private 源 → internal 目标）出单密级与 accept 降密级闸；B 组＝CONVERGE（restricted 源）；
#         K 组＝非恒真对照（显式声明路径照旧、internal→internal 继承不误伤）；E 组＝AST 钉子
# 执行：--mutate 时就地短路一条判据（闸内回缺陷 / 恒取最高档 / 两处调用点各撤参），指定断言须**恰好**转红
# 不适用条件：不判 plan 档（B 合并在 plan 档 FORBID，走不到出单）；不判 secret 源（同构，报告自陈未跑）；不判多进程
"""issue #424 守卫：@BT@#397 修复未闭环@BT@——confirm 档 B 类变更单的密级取自**合并目标**。

病象（修前）：`remember_gated` 在 :4911 已解析**源写入有效密级** `_sens_eff`（声明值 ∨ 继承源节点
密级），但 `_autonomy_gate_merge` 出单时仍传 `kw.get("sensitivity")`。缺省 confirm 档下
MERGE / CONVERGE 都先出 B 类变更单，出单时的声明值为 None ⇒ `MdCGSecure.propose` 按**合并目标**
id 继承密级（internal）；accept 后 `_mutation_execute` 重放 `reinforce` / `converge_into` 时带
internal ⇒ 降密级闸按同档放行，private / restricted 正文以聚合行明文并入 internal 节点，
无令牌访客可读。

修复语义：两处调用点把 `_sens_eff` 传入 `_autonomy_gate_merge`，闸内出单用它（缺省回落声明值——
保持「无源节点 id」的既有行为）；其余判定、资格探针、载荷与重放路径不动。
"""
from __future__ import annotations

import ast
import io
import os
import re
import shutil
import subprocess
import sys
import tempfile

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_SELF = os.path.abspath(__file__)
if _REPO not in sys.path:
    sys.path.insert(0, _REPO)

#: 夹具模板逐字取自 md_cg/test_issue397_sens_eff_wiring.py（复用口径，不另造）。
TPL = ("灵枢运维记录：本次把门禁卡新口令已更新为 {N}，并同步更新了值班手册与交接清单；"
       "后续把预热检查加进值班流程，把巡检脚本的日志目录改到 D 盘，确认备份窗口在凌晨三点，"
       "网络抖动期间不要触发重建；以上变更已在预发环境验证通过，观察一周无异常后同步到生产。"
       "另外记录三件待办：其一，把缓存预热脚本的并发度从四调到八并观察一周；其二，巡检告警的"
       "阈值按上周的基线重算，避免夜间误报；其三，把交接文档里的联系人表补齐并同步到共享盘。")
SECRET = "424MARK私密备用金藏在书架第三格"
SECRET_RES = "424MARK受限封条编号乙七三"
ANCHOR_N = "739155"
_CHECKS = []
FAILS = []


def _check(name, cond, detail=""):
    if name not in _CHECKS:
        _CHECKS.append(name)
    if cond:
        print("  PASS " + name)
    else:
        print("  FAIL " + name + "  " + str(detail)[:200])
        FAILS.append(name)


class _Env:
    """隔离库根 + confirm 档（issue #424 的触发前提＝确认档）。"""

    def __init__(self, clearance="secret", confirm=True):
        self.dir = tempfile.mkdtemp(prefix="iss424_")
        self.clearance = clearance
        self.confirm = confirm
        self.saved = {}

    def __enter__(self):
        from md_cg import autonomy_modes as _am
        from md_cg import crypto
        mode = _am.MODE_CONFIRM
        if not self.confirm:
            # full 档（B_MERGE=ALLOW）：从矩阵推导档名，不写档位字面量
            mode = next(m for m in _am.AUTONOMY_MODES
                        if (_am.MATRIX.get(m) or {}).get(_am.B_MERGE) == _am.ALLOW)
        env = {"MDCG_ROOT": self.dir + "/brain",
               "MDCG_STATE_ROOT": self.dir + "/state",
               "MDCG_AUX_ROOT": self.dir + "/auxstore",
               "MDCG_DATA_ROOT": self.dir + "/data",
               "MDCG_EXPORT_ROOT": self.dir,
               "MDCG_TOKEN_FILE": self.dir + "/auxstore/tokens.json",
               "MDCG_SUSTAIN": "0", "MDCG_SLEEP": "0",
               _am.AUTONOMY_ENV_KEYS["mode"]: mode,
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

    def write(self, nid, content, sens=None):
        """工具面入口：mdcg_remember(gated=True)。sens 为 None 即「不重传 sensitivity」。"""
        from md_cg import mcp_server
        kw = {"layer": "contextual", "role": "user", "gated": True,
              "verification_basis": "test"}
        if sens:
            kw["sensitivity"] = sens
        return mcp_server._dispatch(self.cg, "mdcg_remember",
                                    dict(kw, node_id=nid, content=content))

    def read(self, nid, clearance="internal"):
        """以**另一档 clearance** 的读者读同一库根（谁能读到）。"""
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

    def item(self, pid):
        for x in (self.cg.review_list() or []):
            if x.get("pid") == pid:
                return x
        return None


def _assertions():
    print("== A 组：confirm 档 MERGE（private 源 → internal 目标，不重传 sensitivity） ==")
    with _Env() as e:
        A = TPL.format(N=ANCHOR_N)
        B = TPL.format(N=ANCHOR_N) + " 私密补充：" + SECRET
        _check("A01 前提：internal 目标节点写入成功",
               e.write("t_merge", A, "internal").get("verdict") == "ACCEPT")
        _check("A02 前提：private 源节点以 private 创建成功",
               e.write("s_merge", "私密草稿：仅本人可见的初始正文。", "private").get("verdict") == "ACCEPT")
        r = e.write("s_merge", B)
        gate = r.get("gate") or {}
        _check("A03 前提：本次改写被判 MERGE 并出确认单",
               r.get("verdict") == "CONFIRM" and gate.get("verdict") == "MERGE",
               (r.get("verdict"), gate.get("verdict")))
        pid = r.get("pid") or ""
        it = e.item(pid) or {}
        _check("A04 ★行：变更单密级＝源有效密级 private（不取合并目标 internal）",
               it.get("sensitivity") == "private", it.get("sensitivity"))
        _check("A05 ★行：extra.sensitivity 同步 private",
               (it.get("extra") or {}).get("sensitivity") == "private",
               (it.get("extra") or {}).get("sensitivity"))
        dec = e.cg.review_decide(pid, "accept", reason="issue424 守卫") or {}
        det = dec.get("detail") or {}
        _check("A06 ★行：accept 被降密级闸 fail-closed（incoming private > target internal）",
               dec.get("ok") is False and det.get("error") == "merge_downgrade_refused"
               and det.get("incoming_sensitivity") == "private"
               and det.get("target_sensitivity") == "internal", dec)
        _check("A07 ★行：internal 档读者读回的正文**不含** private 独有串",
               SECRET not in e.read("t_merge", clearance="internal"),
               SECRET in e.read("t_merge", clearance="internal"))
        _check("A08 ★行：磁盘面（t_merge 节点文件）同样不含 private 独有串",
               SECRET not in e.disk_text("t_merge"),
               SECRET in e.disk_text("t_merge"))
        _check("A09 ★行：执行失败后提案保持 pending（裁决未落盘）",
               e.item(pid) is not None)

    print("== B 组：confirm 档 CONVERGE（restricted 源 → internal 目标，同标题模板） ==")
    with _Env() as e:
        TITLE = "# 功能名：批次424收官记忆"
        c1 = TITLE + chr(10) + "正文甲：本次盘点把三条待办收敛成一条。" * 3
        c2 = TITLE + chr(10) + "正文乙：补充说明 " + SECRET_RES + "。" * 3
        _check("B01 前提：internal 目标节点写入成功",
               e.write("c_t1", c1, "internal").get("verdict") == "ACCEPT")
        _check("B02 前提：restricted 源节点以 restricted 创建成功",
               e.write("r_res", "受限草稿：仅限受限范围可见的初始正文。", "restricted").get("verdict") == "ACCEPT")
        r2 = e.write("r_res", c2)
        g2 = r2.get("gate") or {}
        _check("B03 前提：本次改写被判 CONVERGE 并出确认单",
               r2.get("verdict") == "CONFIRM" and g2.get("verdict") == "CONVERGE",
               (r2.get("verdict"), g2.get("verdict")))
        pid2 = r2.get("pid") or ""
        it2 = e.item(pid2) or {}
        _check("B04 ★行：变更单密级＝源有效密级 restricted",
               it2.get("sensitivity") == "restricted", it2.get("sensitivity"))
        dec2 = e.cg.review_decide(pid2, "accept", reason="issue424 守卫") or {}
        det2 = dec2.get("detail") or {}
        _check("B05 ★行：accept 被降密级闸 fail-closed（incoming restricted > target internal）",
               dec2.get("ok") is False and det2.get("error") == "merge_downgrade_refused"
               and det2.get("incoming_sensitivity") == "restricted", dec2)
        _check("B06 ★行：internal 档读者读回的正文**不含** restricted 独有串",
               SECRET_RES not in e.read("c_t1", clearance="internal"),
               SECRET_RES in e.read("c_t1", clearance="internal"))
        _check("B07 ★行：执行失败后提案保持 pending",
               e.item(pid2) is not None)

    print("== K 组：非恒真对照（显式声明照旧；internal→internal 继承不误伤） ==")
    with _Env() as e:
        A = TPL.format(N=ANCHOR_N)
        B = TPL.format(N=ANCHOR_N) + " 私密补充：" + SECRET
        e.write("t_k1", A, "internal")
        e.write("s_k1", "私密草稿：仅本人可见的初始正文。", "private")
        r3 = e.write("s_k1", B, "private")               # 显式声明（旧路径）
        it3 = e.item(r3.get("pid") or "") or {}
        _check("K01 显式声明 private 改写 ⇒ 出单密级仍为 private（既有路径逐位不变）",
               r3.get("verdict") == "CONFIRM" and it3.get("sensitivity") == "private",
               (r3.get("verdict"), it3.get("sensitivity")))
    with _Env() as e:
        A = TPL.format(N=ANCHOR_N)
        B = TPL.format(N=ANCHOR_N) + " 内部补充：无密级串。"
        e.write("t_k2", A, "internal")
        e.write("s_k2", "内部草稿：初始正文。", "internal")
        r4 = e.write("s_k2", B)                          # 不重传 ⇒ 继承 internal
        it4 = e.item(r4.get("pid") or "") or {}
        _check("K02 ★过度收紧对照：未声明改写既有 internal 节点 ⇒ 出单密级为 internal",
               r4.get("verdict") == "CONFIRM" and it4.get("sensitivity") == "internal",
               (r4.get("verdict"), it4.get("sensitivity")))
        dec4 = e.cg.review_decide(r4.get("pid") or "", "accept", reason="K02") or {}
        _check("K03 ★过度收紧对照：internal→internal 照常合并落盘",
               bool(dec4.get("ok")) and "内部补充" in e.read("t_k2", clearance="internal"),
               dec4)

    print("== E 组：AST 钉子（两处调用点 + 闸内有效密级单点） ==")

    def _fn(name):
        with io.open(os.path.join(_REPO, "md_cg/mdcos.py"), encoding="utf-8") as f:
            tree = ast.parse(f.read())
        for n in ast.walk(tree):
            if isinstance(n, ast.FunctionDef) and n.name == name:
                return n
        return None

    fn = _fn("_autonomy_gate_merge")
    rg = _fn("remember_gated")
    sens_args = [(ast.unparse(c.func), ast.unparse(k.value), k.value.lineno)
                 for c in (ast.walk(fn) if fn else []) if isinstance(c, ast.Call)
                 for k in c.keywords if k.arg == "sensitivity"]
    calls = [c for c in (ast.walk(rg) if rg else []) if isinstance(c, ast.Call)
             and isinstance(c.func, ast.Attribute)
             and c.func.attr == "_autonomy_gate_merge"]
    fn_src = ast.unparse(fn) if fn else ""
    _check("E01 闸内确有 sensitivity 形参（有效密级入口）",
           bool(fn) and "sensitivity" in [a.arg for a in fn.args.args],
           [a.arg for a in fn.args.args] if fn else None)
    _check("E02 ★钉子：闸内 propose_mutation 的 sensitivity 实参来自 sens_eff（非 kw.get）",
           any(f.endswith("propose_mutation") and v == "sens_eff" for f, v, _l in sens_args),
           sens_args)
    _check("E03 闸内保留「未传则回落声明值」分支（非恒取高/低）",
           "sensitivity is not None" in fn_src, "")
    _check("E04 调用点恰 2 处（CONVERGE 与 MERGE/reinforce）", len(calls) == 2, len(calls))
    _check("E05 ★钉子：两处调用点均传 sensitivity=_sens_eff",
           len(calls) == 2 and all(any(k.arg == "sensitivity"
                                       and ast.unparse(k.value) == "_sens_eff"
                                       for k in c.keywords) for c in calls),
           [[(k.arg, ast.unparse(k.value)) for k in c.keywords] for c in calls])


def _run_assertions():
    global FAILS
    FAILS = []
    del _CHECKS[:]
    _assertions()
    print("通过 %d / 失败 %d" % (len(_CHECKS) - len(FAILS), len(FAILS)))
    return len(FAILS)


def _subprocess_fail_names():
    r = subprocess.run([sys.executable, "-X", "utf8", _SELF, "--assert-only"],
                       capture_output=True, text=True, encoding="utf-8",
                       errors="replace", cwd=_REPO, timeout=600)
    names = set(re.findall(r"(?m)^\s*FAIL\s+([A-Z]\d+)", r.stdout or ""))
    return names, (r.stdout or "") + (r.stderr or "")


_SENS_BLOCK = chr(10).join([
    "        # issue #424：声明值（kw.get）只是**入口**；这里必须用源写入的有效密级。",
    "        sens_eff = (sensitivity if sensitivity is not None",
    "                    else kw.get(\"sensitivity\"))",
])
_ARMS = {
    "M1": (
        _SENS_BLOCK + chr(10) +
        "        pr = _am.propose_mutation(self, _am.B_MERGE, tgt, payload=pay," + chr(10) +
        "                                  layer=tlayer," + chr(10) +
        "                                  sensitivity=sens_eff, info=True)",
        "        pr = _am.propose_mutation(self, _am.B_MERGE, tgt, payload=pay," + chr(10) +
        "                                  layer=tlayer," + chr(10) +
        "                                  sensitivity=kw.get(\"sensitivity\"), info=True)",
        {"A04", "A05", "A06", "A07", "A08", "A09",
         "B04", "B05", "B06", "B07", "E02", "E03"},
    ),
    "M2": (
        _SENS_BLOCK,
        "        sens_eff = \"secret\"",
        {"A04", "A05", "A06", "B04", "B05", "K01", "K02", "K03", "E03"},
    ),
    "M3": (
        "                                               gate=lim," + chr(10) +
        "                                               # issue #424：出单密级＝源写入有效密级，" + chr(10) +
        "                                               # 不取声明值（同 id 改写常态为 None）。" + chr(10) +
        "                                               sensitivity=_sens_eff)",
        "                                               gate=lim)",
        {"B04", "B05", "B06", "B07", "E05"},
    ),
    "M4": (
        "                                                gate=verdict," + chr(10) +
        "                                                # issue #424：同 CONVERGE 支。" + chr(10) +
        "                                                sensitivity=_sens_eff)",
        "                                                gate=verdict)",
        {"A04", "A05", "A06", "A07", "A08", "A09", "E05"},
    ),
}


def _mutate(argv):
    want = ""
    for a in argv:
        if a == "--mutate":
            want = want or "ALL"
        elif a.startswith("--mutate="):
            want = a.split("=", 1)[1]
    if not want:
        return 0
    ids = sorted(_ARMS) if want == "ALL" else [want]
    target = os.path.join(_REPO, "md_cg", "mdcos.py")
    with open(target, "rb") as fh:
        orig = fh.read()
    red = 0
    try:
        for mid in ids:
            if mid not in _ARMS:
                print("[ANCHOR-MISS] %s：未登记该变异臂" % mid)
                return 2
            old, new, expect = _ARMS[mid]
            text = orig.decode("utf-8")
            nl = "\r\n" if "\r\n" in text else "\n"
            norm = text.replace("\r\n", "\n")
            if norm.count(old) != 1:
                print("[ANCHOR-MISS] %s：锚点命中 %d 次（期望 1）⇒ 无法变异，判据失效"
                      % (mid, norm.count(old)))
                return 2
            with open(target, "wb") as fh:
                fh.write(norm.replace(old, new).replace("\n", nl).encode("utf-8"))
            actual, out = _subprocess_fail_names()
            if actual == expect:
                print("[MUTATE-OK]   %s：指定断言转红 %s" % (mid, sorted(actual)))
            else:
                print("[MUTATE-FAIL] %s：期望红 %s，实际红 %s"
                      % (mid, sorted(expect), sorted(actual)))
                for line in out.splitlines():
                    if line.strip().startswith("FAIL"):
                        print("    " + line)
                red += 1
    finally:
        with open(target, "wb") as fh:
            fh.write(orig)
    print("反证结果：%d 条变异，%s" % (len(ids), "全部恰好命中" if red == 0 else "%d 条未命中" % red))
    return 1 if red else 0


if __name__ == "__main__":
    _f = _run_assertions()
    if "--assert-only" in sys.argv:
        sys.exit(1 if _f else 0)
    _m = _mutate(sys.argv[1:])
    sys.exit(1 if (_f or _m) else 0)
