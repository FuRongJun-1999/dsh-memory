# -*- coding: utf-8 -*-
# 功能名：兄弟写入口的密级继承（issue #439：add_goal/add_rejected/add_unresolved 未声明即静默降 internal）+ 目标密级转发与登记（issue #426-H，随本批同修）
# 生效条件：python -u -X utf8 -m md_cg.test_issue439_sibling_sensitivity_inherit [--mutate]；被测面＝md_cg/mdcos.py 三入口的 _write_sensitivity 接线 + md_cg/mdcg.py 的 id 单点 helper + md_cg/mcp_server.py 的 goal/add 转发 + md_cg/op_table.py 的 goal params 登记
# 子功能：A 组＝正向腿（三入口「未声明改写既有 restricted」必须继承；#426-H 显式声明必须落到盘上）；K 组＝反向腿①（新节点回落 internal / 显式优先 / 越权仍拒 / **幂等重入不写索引**）；E 组＝源码面（三入口接线、id 单点唯一、基类不再内联 sha1、登记与转发两半在位、幂等收窄在位）；M 组＝反向腿②（--mutate，红项严格相等且互不重叠）
# 执行：--mutate 时在镜像树里逐条撤继承／撤转发／撤幂等收窄，守卫必须按指定项转红（多红/少红皆不合格）
# 验证方式：全部 PASS 即通过（退出码 0）；--mutate 下每条变异的红项集合须与预期逐项相符，锚点未命中即 fail-closed（打印 ANCHOR-MISS 并计入不合格）
# 不适用条件：① 腿看不见「密级判定算法是否正确」——只看见「未声明 ⇒ 既有密级是否保住 / 显式声明是否落到盘上」（§5.2 可判性边界）；② 不覆盖令牌实签与跨进程越权端到端（#426-B 面，属另一入口）；③ 不覆盖 add_rejected/add_unresolved 的**正文刷新**语义（#426 之外的既有面，本批只碰密级与幂等副作用）；④ 不覆盖 op_table 之外的 schema 面（实核：sensitivity 已在 schema.properties，无需新登记）；⑤ **本腿各入口各自独立库**（同 #346 不适用条件⑥：共库时前一面可达会钝化后一面的闸）。
# 形态名（供按名检索）：「**显式声明静默失效**」——调用方显式传了某个参数、服务端收下、然后静默丢掉（#426-H：cg(op=goal, action=add, sensitivity=private) 落 internal 明文）。与 #186 / #294 同族，也与本会话「写了却没生效」的判据面缺陷同族。
"""issue #439 守卫：兄弟写入口的密级继承 + #426-H 的转发与登记。

病象（修前）：#297 把「未声明 ⇒ 继承既有节点密级」接到 `add`/`propose` 两个入口；
三个兄弟入口 `add_goal`/`add_rejected`/`add_unresolved` 仍写 `sensitivity or DEFAULT_SENSITIVITY`
——`or DEFAULT` 在**继承判定之前**就把「未声明 + 有既有节点」钉死成 internal，
`_write_sensitivity` 的继承分支**永不触发**：改写既有 restricted/private 节点时静默降级。
`add_rejected` 尤其隐蔽：基类幂等短路时正文不变、密级却被降。
#426-H 是同一入口的另一半：分派层 `cg.add_goal(...)` 不转发 `sensitivity`，而 `op_table`
的 goal params 也没登记它 ⇒「显式声明静默失效」。

修法：三入口先按**基类单点**算 id（`_rejected_nid`/`_unresolved_nid`/`_goal_nid`，
口径与基类幂等键逐字一致，不在安全层复制 sha1 写法），再过 `_write_sensitivity`；
并按幂等语义把 `_index_sensitivity` **限定在实际落盘分支**（幂等重入不产生任何副作用）；
#426-H 的两半同批补（mcp_server 转发 + op_table 登记）。
"""
from __future__ import annotations

import ast
import os
import shutil
import subprocess
import sys
import tempfile

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO not in sys.path:
    sys.path.insert(0, _REPO)

_TMP = tempfile.mkdtemp(prefix="iss439_")
os.environ.update({"MDCG_ROOT": _TMP + "/brain", "MDCG_STATE_ROOT": _TMP + "/state",
                   "MDCG_AUX_ROOT": _TMP + "/auxstore", "MDCG_DATA_ROOT": _TMP + "/datastore",
                   "MDCG_EXPORT_ROOT": _TMP, "MDCG_SUSTAIN": "0", "MDCG_SLEEP": "0",
                   "MDCG_AUTONOMY": "confirm"})
os.environ.pop("MDCG_READ_CACHE", None)

from md_cg import mcp_server as _ms                   # noqa: E402
from md_cg import op_table as _ot                     # noqa: E402
from md_cg import security as _sec                    # noqa: E402
from md_cg import tokens as _tk                       # noqa: E402
from md_cg.mdcos import MdCGSecure                    # noqa: E402
from md_cg.security import AccessDenied, Principal    # noqa: E402

PASSED, FAILS = [], []
LOW, HIGH = "internal", "restricted"      # 相邻两档（security.SENSITIVITY_ORDER）


def _check(name, cond, detail=""):
    if cond:
        print("  PASS " + name)
        PASSED.append(name)
    else:
        print("  FAIL " + name + "  " + str(detail)[:240])
        FAILS.append(name)


def _mk(role, clearance=None):
    sp = _tk.role_spec(role)
    return Principal(clearance=clearance or sp["clearance_cap"], can_write=sp["can_write"],
                     can_admin=sp["can_admin"], role=role,
                     layers_allow=sp["layers_allow"], ops_allow=sp["ops_allow"])


def _cg(root, role="designer", clearance="secret"):
    return MdCGSecure(root, principal=_mk(role, clearance), autoflush=1)


def _try(fn):
    try:
        return True, fn(), None
    except AccessDenied:
        return False, None, "AccessDenied"
    except Exception as exc:                              # noqa: BLE001
        return False, None, type(exc).__name__


def _sens_of(cg, nid):
    return ((cg.index.get("nodes") or {}).get(nid) or {}).get("sensitivity")


# ================================================= A 组：正向腿（四路）
def _case_goal(tmp, tag):
    root = os.path.join(tmp, "a_" + tag)
    cg = _cg(root)
    gid = cg.add_goal("目标 %s：季度预算上限 12 万" % tag, sensitivity=HIGH)
    cg.flush()
    before = _sens_of(cg, gid)
    gid2 = cg.add_goal("目标 %s：季度预算上限 12 万" % tag)      # 未声明
    cg.flush()
    return gid, before, _sens_of(cg, gid2), cg


def _case_rejected(tmp, tag):
    root = os.path.join(tmp, "a_" + tag)
    cg = _cg(root)
    nid = cg.add_rejected("假设 %s：缓存命中率 92%%" % tag, "反例三例", sensitivity=HIGH)
    cg.flush()
    before = _sens_of(cg, nid)
    nid2 = cg.add_rejected("假设 %s：缓存命中率 92%%" % tag, "反例三例")   # 未声明 + 幂等重入
    cg.flush()
    return nid, before, _sens_of(cg, nid2), cg


def _case_unresolved(tmp, tag):
    root = os.path.join(tmp, "a_" + tag)
    cg = _cg(root)
    nid = cg.add_unresolved("问题 %s：32 位还是 64 位" % tag, "线索：两条取值",
                            topic="主题 %s" % tag, sensitivity=HIGH)
    cg.flush()
    before = _sens_of(cg, nid)
    nid2 = cg.add_unresolved("问题 %s：32 位还是 64 位" % tag, "线索：两条取值",
                             topic="主题 %s" % tag)                  # 未声明 + 幂等重入
    cg.flush()
    return nid, before, _sens_of(cg, nid2), cg


def group_a(tmp):
    print("== A 组：正向腿——三入口未声明改写既有节点必须继承；#426-H 显式声明必须落地 ==")
    _check("A0 前置：密级梯度就位（security.SENSITIVITY_ORDER 含 internal < restricted）",
           _sec.SENSITIVITY_ORDER.index(LOW) < _sec.SENSITIVITY_ORDER.index(HIGH))
    gid, b1, a1, cg1 = _case_goal(tmp, "goal")
    _check("A1 add_goal：未声明重写既有 %s 目标 ⇒ 密级仍 %s（修前 internal）" % (HIGH, HIGH),
           b1 == HIGH and a1 == HIGH, "before=%r after=%r" % (b1, a1))
    cg1.close()
    nid2, b2, a2, cg2 = _case_rejected(tmp, "rej")
    _check("A2 add_rejected：未声明重入既有 %s 负记忆 ⇒ 密级仍 %s（修前 internal）" % (HIGH, HIGH),
           b2 == HIGH and a2 == HIGH, "before=%r after=%r" % (b2, a2))
    cg2.close()
    nid3, b3, a3, cg3 = _case_unresolved(tmp, "unr")
    _check("A3 add_unresolved：未声明重入既有 %s 工单 ⇒ 密级仍 %s（修前 internal）" % (HIGH, HIGH),
           b3 == HIGH and a3 == HIGH, "before=%r after=%r" % (b3, a3))
    cg3.close()
    # A4 #426-H：分派层显式声明必须落到盘上
    root = os.path.join(tmp, "a_h")
    cg4 = _cg(root)
    r = _ms._cg_dispatch(cg4, {"op": "goal", "action": "add",
                               "goal": "H 秘密计划：下月跳槽 谈薪底线 80 万",
                               "sensitivity": "private"})
    cg4.flush()
    hid = (r or {}).get("id")
    _check("A4 #426-H：cg(op=goal, action=add, sensitivity=private) 的密级落到盘上",
           bool(hid) and _sens_of(cg4, hid) == "private",
           "r=%r sens=%r" % (r, _sens_of(cg4, hid)))
    guest = MdCGSecure(root, principal=Principal(
        role="guest", clearance="internal", can_write=False, can_admin=False,
        layers_allow=_tk.role_spec("guest")["layers_allow"],
        ops_allow=_tk.role_spec("guest")["ops_allow"], auth_mode="anonymous"), autoflush=1)
    g = _ms._cg_dispatch(guest, {"op": "read", "node_id": hid}) if hid else {}
    _check("A4b #426-H 后果：访客读不到该目标（修前 internal 明文可读）",
           "H 秘密计划" not in str(g), "guest=%r" % str(g)[:80])
    guest.close()
    cg4.close()


# ================================================= K 组：反向腿①
def group_k(tmp):
    print("== K 组：反向腿①——零变更 / 显式优先 / 越权仍拒 / 幂等重入零副作用 ==")
    root = os.path.join(tmp, "k")
    cg = _cg(root)
    gid = cg.add_goal("K 新目标：把发布周期压到两周")
    cg.flush()
    _check("K1 零变更：新目标未声明 ⇒ 回落 DEFAULT_SENSITIVITY(%s)" % _sec.DEFAULT_SENSITIVITY,
           _sens_of(cg, gid) == _sec.DEFAULT_SENSITIVITY, "sens=%r" % _sens_of(cg, gid))
    gid2 = cg.add_goal("K 显式目标：并购意向书阶段", sensitivity=HIGH)
    cg.flush()
    _check("K2 显式声明优先：新目标显式 %s ⇒ 落 %s（不被回落覆盖）" % (HIGH, HIGH),
           _sens_of(cg, gid2) == HIGH, "sens=%r" % _sens_of(cg, gid2))
    cg.close()
    low = _cg(root, role="record", clearance=LOW)
    ok, _r, err = _try(lambda: low.add_goal("K 越权目标：机密收购", sensitivity="private"))
    _check("K3 越权仍拒：clearance=%s 显式传 private ⇒ AccessDenied（防一刀切之后仍 fail-closed）" % LOW,
           (not ok) and err == "AccessDenied", "ok=%s err=%s" % (ok, err))
    low.close()
    # K4 幂等重入不写索引（Lead 追加要求①：幂等收窄的腿）
    root4 = os.path.join(tmp, "k4")
    cg4 = _cg(root4)
    hid = cg4.add_rejected("K4 幂等假设：写入放大约 3 倍", "反例两例", sensitivity=HIGH)
    cg4.flush()
    gen0 = cg4._dirty.write_gen
    cg4.add_rejected("K4 幂等假设：写入放大约 3 倍", "反例两例")      # 幂等重入（未声明）
    _check("K4a 幂等重入不写索引：add_rejected 重入后 write_gen 不变且该 id 未标脏",
           cg4._dirty.write_gen == gen0 and hid not in cg4._dirty,
           "gen %s->%s dirty=%s" % (gen0, cg4._dirty.write_gen, hid in cg4._dirty))
    uid = cg4.add_unresolved("K4 幂等问题：哪条路径更短", topic="K4 幂等主题", sensitivity=HIGH)
    cg4.flush()
    gen1 = cg4._dirty.write_gen
    cg4.add_unresolved("K4 幂等问题：哪条路径更短", topic="K4 幂等主题")
    _check("K4b 幂等重入不写索引：add_unresolved 同输入重入后 write_gen 不变且未标脏",
           cg4._dirty.write_gen == gen1 and uid not in cg4._dirty,
           "gen %s->%s dirty=%s" % (gen1, cg4._dirty.write_gen, uid in cg4._dirty))
    cg4.close()


# ================================================= E 组：源码面
def _ast(rel):
    with open(os.path.join(_REPO, rel), encoding="utf-8") as f:
        return ast.parse(f.read(), rel)


def _fn(rel, cls, name):
    for node in ast.walk(_ast(rel)):
        if isinstance(node, ast.ClassDef) and node.name == cls:
            for sub in node.body:
                if isinstance(sub, ast.FunctionDef) and sub.name == name:
                    return sub
    return None


def _calls(fn, name):
    out = []
    for node in ast.walk(fn) if fn is not None else []:
        if isinstance(node, ast.Call):
            f = node.func
            if (getattr(f, "attr", None) or getattr(f, "id", None)) == name:
                out.append(node)
    return out


def _src(rel):
    with open(os.path.join(_REPO, rel), encoding="utf-8") as f:
        return f.read()


def group_e(tmp):
    print("== E 组：源码面——三入口接线 / id 单点 / 登记与转发两半 / 幂等收窄 ==")
    e1 = {"add_goal": "E1a", "add_rejected": "E1b", "add_unresolved": "E1c"}
    for name, tag in e1.items():
        fn = _fn("md_cg/mdcos.py", "MdCGSecure", name)
        got = len(_calls(fn, "_write_sensitivity"))
        _check("%s MdCGSecure.%s 经 _write_sensitivity 解析密级（恰一处）" % (tag, name),
               got == 1, "calls=%d" % got)
    helpers = {"_rejected_nid": 0, "_unresolved_nid": 0, "_goal_nid": 0, "_node_exists": 0}
    for node in ast.walk(_ast("md_cg/mdcg.py")):
        if isinstance(node, ast.FunctionDef) and node.name in helpers:
            helpers[node.name] += 1
    _check("E2 id/幂等判据单点：四个 helper 在 md_cg/mdcg.py 各定义恰一处",
           all(v == 1 for v in helpers.values()), "defs=%s" % helpers)
    dup = []
    for name in ("add_goal", "add_rejected", "add_unresolved"):
        fn = _fn("md_cg/mdcos.py", "MdCGSecure", name)
        n_hash = len(_calls(fn, "sha1")) + len(_calls(fn, "hexdigest"))
        lits = []
        for node in ast.walk(fn) if fn is not None else []:
            if isinstance(node, ast.JoinedStr):
                for part in node.values:
                    if (isinstance(part, ast.Constant)
                            and isinstance(part.value, str)
                            and part.value[:5] in ("rej_", "unr_", "goal_")):
                        lits.append(part.value)
        if n_hash or lits:
            dup.append((name, n_hash, lits))
    _check("E2b 安全层不复制 id 口径：三入口体内无 sha1/hexdigest 调用、无 id 字面量前缀（AST 口径，不吃注释）",
           dup == [], "dup=%s" % dup)
    for rel, cls, name, helper in (("md_cg/mdcg.py", "MdCG", "add_rejected", "_rejected_nid"),
                                   ("md_cg/mdcg.py", "MdCG", "add_unresolved", "_unresolved_nid"),
                                   ("md_cg/mdcg.py", "MdCG", "add_goal", "_goal_nid")):
        fn = _fn(rel, cls, name)
        n_sha1 = len(_calls(fn, "sha1")) + len(_calls(fn, "hexdigest"))
        n_h = len(_calls(fn, helper))
        _check("E3 基类 %s 不再内联 sha1（helper 调用恰一处）" % name,
               n_sha1 == 0 and n_h == 1, "sha1/hexdigest=%d helper=%d" % (n_sha1, n_h))
    _check("E4a 登记面：#426-H 的 goal params 含 sensitivity（op_table 唯一真源）",
           "sensitivity" in _ot.params_of("goal"), "params=%s" % (_ot.params_of("goal"),))
    _check("E4b 转发面：#426-H 的分派层 goal/add 分支转发 sensitivity",
           "sensitivity=a.get(\"sensitivity\")" in _src("md_cg/mcp_server.py"))
    for name, tag in (("add_rejected", "E5a"), ("add_unresolved", "E5b")):
        fn = _fn("md_cg/mdcos.py", "MdCGSecure", name)
        guarded = False
        for node in ast.walk(fn) if fn is not None else []:
            if isinstance(node, ast.If):
                dump = ast.dump(node.test)
                if "_wrote" in dump and _calls(node, "_index_sensitivity"):
                    guarded = True
        _check("%s 幂等收窄在位：%s 的 _index_sensitivity 在 if _wrote 之内" % (tag, name), guarded)


def _guard_group(tag, fn, tmp):
    try:
        fn(tmp)
    except Exception as exc:                              # noqa: BLE001
        import traceback
        _check("%s0 组内异常（fail-closed：异常即红）" % tag, False,
               "%s: %s" % (type(exc).__name__, exc))
        traceback.print_exc()


def main():
    print("== #439 + #426-H 守卫 ==")
    _guard_group("A", group_a, _TMP)
    _guard_group("K", group_k, _TMP)
    _guard_group("E", group_e, _TMP)
    print("=" * 68)
    print("#439/#426-H 守卫：%d 通过，%d 失败" % (len(PASSED), len(FAILS)))
    for f in FAILS:
        print("  红项：" + f)
    _bad = _mutate() if "--mutate" in sys.argv else 0
    return 1 if (FAILS or _bad) else 0


# ================================================= M 组：反向腿②（定点变异）
# 每条 = **整站点还原**（#439 原形态）：继承线 + 幂等收窄线一起退回——二者在
# add_rejected/add_unresolved 上**耦合**：只退继承线时重入仍被收窄挡住不写索引，
# 行为面观察不到（只剩源码面 E1b/E1c 红）；只退收窄线只红 K4a/K4b。故还原形态必须
# 是整站点，红项集合才与站点一一对应、两两不重叠（实测见 --mutate 输出）。
_MUTATIONS = (
    ("M1 撤继承：add_goal 退回 sensitivity or DEFAULT_SENSITIVITY（#439 原形态）",
     "md_cg/mdcos.py",
     (("        gid = self._goal_nid(goal)" + chr(10)
       + "        sens = self._write_sensitivity(gid, sensitivity)",
       "        gid = self._goal_nid(goal)" + chr(10)
       + "        sens = sensitivity or DEFAULT_SENSITIVITY"),),
     ("A1", "E1a")),
    ("M2 整站点还原：add_rejected 退回「or DEFAULT + 无条件写索引」（#439 原形态）",
     "md_cg/mdcos.py",
     (("        nid = self._rejected_nid(hypothesis)" + chr(10)
       + "        sens = self._write_sensitivity(nid, sensitivity)",
       "        nid = self._rejected_nid(hypothesis)" + chr(10)
       + "        sens = sensitivity or DEFAULT_SENSITIVITY"),
      ("        _wrote = not self._node_exists(nid)" + chr(10)
       + "        out = super().add_rejected(hypothesis, reason, sensitivity=sens, **kw)" + chr(10)
       + "        if _wrote:" + chr(10)
       + "            self._index_sensitivity(out, sens)",
       "        out = super().add_rejected(hypothesis, reason, sensitivity=sens, **kw)" + chr(10)
       + "        self._index_sensitivity(out, sens)")),
     ("A2", "E1b", "K4a", "E5a")),
    ("M3 整站点还原：add_unresolved 退回「or DEFAULT + 无条件写索引」（#439 原形态）",
     "md_cg/mdcos.py",
     (("        nid = self._unresolved_nid(question, kw.get(\"topic\"))" + chr(10)
       + "        sens = self._write_sensitivity(nid, sensitivity)",
       "        nid = self._unresolved_nid(question, kw.get(\"topic\"))" + chr(10)
       + "        sens = sensitivity or DEFAULT_SENSITIVITY"),
      ("        _wrote = not self._node_exists(nid)" + chr(10)
       + "        out = super().add_unresolved(question, known_clues, goal, sensitivity=sens, **kw)" + chr(10)
       + "        if _wrote:" + chr(10)
       + "            self._index_sensitivity(out, sens)",
       "        out = super().add_unresolved(question, known_clues, goal, sensitivity=sens, **kw)" + chr(10)
       + "        self._index_sensitivity(out, sens)")),
     ("A3", "E1c", "K4b", "E5b")),
    ("M4 撤转发：分派层不再转发 sensitivity（#426-H 的行为半）",
     "md_cg/mcp_server.py",
     (("                              status=a.get(\"goal_status\") or \"active\"," + chr(10)
       + "                              sensitivity=a.get(\"sensitivity\"))",
       "                              status=a.get(\"goal_status\") or \"active\")"),),
     ("A4", "A4b")),
)


def _mirror_build():
    """镜像树：**绝不在真实工作树里改源**（写面纪律）。"""
    dst = tempfile.mkdtemp(prefix="iss439_mut_")
    for name in ("md_cg", "lib"):
        src = os.path.join(_REPO, name)
        if os.path.isdir(src):
            shutil.copytree(src, os.path.join(dst, name),
                            ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    for name in sorted(os.listdir(_REPO)):
        p = os.path.join(_REPO, name)
        if os.path.isfile(p) and name.endswith(".py"):
            shutil.copy2(p, os.path.join(dst, name))
    return dst


def _run_in(tree):
    env = dict(os.environ)
    env["PYTHONPATH"] = tree
    env["PYTHONUTF8"] = "1"
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    for k in ("MDCG_ROOT", "MDCG_STATE_ROOT", "MDCG_AUX_ROOT", "MDCG_DATA_ROOT",
              "MDCG_EXPORT_ROOT", "MDCG_INGEST_ROOT", "MDCG_TOKEN", "MDCG_TOKEN_FILE"):
        env.pop(k, None)
    pr = subprocess.run([sys.executable, "-u", "-X", "utf8", "-m",
                         "md_cg.test_issue439_sibling_sensitivity_inherit"],
                        capture_output=True, text=True, encoding="utf-8",
                        errors="replace", cwd=tree, env=env, timeout=1800)
    out = (pr.stdout or "") + (pr.stderr or "")
    reds = [ln.split("FAIL ", 1)[1].strip()
            for ln in out.splitlines() if ln.strip().startswith("FAIL ")]
    return pr.returncode, reds, out


def _apply_text(text, rel, pairs):
    eol = (chr(13) + chr(10)) if (chr(13) + chr(10)) in text else chr(10)
    for old, new in pairs:
        o = old.replace(chr(10), eol)
        n = new.replace(chr(10), eol)
        if text.count(o) != 1:
            return None, "锚点在 %s 里命中 %d 次" % (rel, text.count(o))
        text = text.replace(o, n, 1)
    return text, ""


def _mutate():
    print("!! 反向腿②：逐条撤继承／撤转发／撤幂等收窄，守卫必须按指定项转红（集合严格相等）")
    tree = _mirror_build()
    bad = []
    try:
        rc, reds, out = _run_in(tree)
        print("  未变异镜像基线：rc=%d 红项=%d（必须 rc=0 且 0 红）" % (rc, len(reds)))
        if rc != 0 or reds:
            bad.append("未变异镜像基线即红")
            print(chr(10).join(out.splitlines()[-25:]))
        for desc, rel, pairs, exp in _MUTATIONS:
            p = os.path.join(tree, rel)
            with open(p, encoding="utf-8", newline="") as f:
                bak = f.read()
            mut, why = _apply_text(bak, rel, pairs)
            if mut is None:
                bad.append("%s —— %s" % (desc, why))
                print("  ANCHOR-MISS " + desc + "  " + why)
                continue
            with open(p, "w", encoding="utf-8", newline="") as f:
                f.write(mut)
            for root, _dd, _ff in os.walk(tree):
                if os.path.basename(root) == "__pycache__":
                    shutil.rmtree(root, ignore_errors=True)
            rc2, reds2, out2 = _run_in(tree)
            with open(p, "w", encoding="utf-8", newline="") as f:
                f.write(bak)
            hit = sorted({r.split(" ")[0] for r in reds2})
            if rc2 != 0 and hit == sorted(exp):
                print("  OK   %s  红项=%d 指定命中=%s" % (desc, len(reds2), hit))
            else:
                bad.append(desc)
                print("  MISMATCH %s  实际红项=%s  期望=%s  rc=%d"
                      % (desc, hit, sorted(exp), rc2))
                for r in reds2[:12]:
                    print("        FAIL " + r)
                if rc2 == 0:
                    print(chr(10).join(out2.splitlines()[-15:]))
        print("反向腿②：%s（%d 条不合格）" % ("PASS" if not bad else "FAIL", len(bad)))
        for b in bad:
            print("  不合格：" + b)
        return len(bad)
    finally:
        shutil.rmtree(tree, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
