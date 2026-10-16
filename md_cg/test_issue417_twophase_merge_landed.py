# -*- coding: utf-8 -*-
# 功能名：两段式对账不得把「已合并落盘」的 gated MERGE 判成未落盘（issue #417）
# 生效条件：python -X utf8 -m md_cg.test_issue417_twophase_merge_landed [--mutate]；被测面＝md_cg/twophase.py::_judge/_merge_target + md_cg/forgetting.py::reinforce 的 src_id 槽 + md_cg/mdcg.py::_node_entry 的登记
# 子功能：A 组＝崩溃窗口（内容已并入目标、commit 未落账）对账必须判 committed 并带去向；K 组＝非恒真对照（无痕迹仍 interrupted、源已落盘仍 committed、不编造、merge_sources 原样）；E 组＝单点与编制面（判据唯一、来源 id 两侧登记、骨架二则）
# 执行：--mutate 时在镜像树里逐条回退/放宽/收紧，守卫必须按指定项转红；另调 _guard_kit 两骨架（枚举完备性 + 回退实跑）
# 验证方式：全部 PASS 即通过（退出码 0）；变异与两骨架的红项集合须与预期逐项相符
# 覆盖缺口（**如实登记**，fix-354-python 实测报障引出）：本守卫的 A 组**直调**
# forgetting.reinforce，**未覆盖票据链**（gated=True → CONFIRM → accept →
# _mutation_execute → B_MERGE）；mdcos.py 里 src_id 引用未绑定局部名的那次崩溃
# 正是从该缺口逃过的（「声称的面 > 实际的面」）。补该腿需构造能触发 CONFIRM 合并
# 的夹具（test_mode_parity R2 的形态），**下一轮补**，本文件当前如实标记未覆盖。
# 不适用条件：不判「真断电/被杀进程的文件系统语义」（本守卫用「合并已 flush + 不调 commit」构造**同一落盘态**，与臂的 os._exit 等价，属可控近似——如实登记）；不判 writepipe 侧「意图键绑实际写入对象」的方案 B（本批不碰该文件，作为裁定项）；不判 ACCEPT/DROP/DEFER 三态自己的崩溃窗口（只覆盖 MERGE）；不判 source 为空/坏行的账本容错（属既有守卫）
"""issue #417 守卫：对账的**事实来源**必须是盘面，不是「源 id 在不在」的推断。

病象（修前）：MERGE 把内容并入**目标节点**，源 id 本就不会成文；崩溃窗口落在
「内容已落盘、`twophase.commit` 还没落账」之间时，`_judge` 只查源 id ⇒ 判
`interrupted/node_missing`——**与事实相反**（同一事件在正常收尾路径记
`committed/merged_into`），且会诱导重做**不可逆**的 MERGE。

修法：① `forgetting.reinforce` 新增 `src_id` 槽，把**来源节点 id** 记进目标
`fm.merge_source_ids`（有界，复用 MERGE_SOURCES_KEEP）+ 同钩镜像进索引条目 +
在 `_node_entry` 登记（否则新实例扫描面不带该键）；② `twophase._merge_target`
在**盘面**反查该痕迹并回盘复核；③ `_judge` 源缺失时命中痕迹 ⇒ `committed` +
去向，**未命中仍判 interrupted（不放宽）**。

⚠ 事实纠正（本批读码发现）：`fm.merge_sources` 记的是**写入方归属**
（`{session, actor, t}`，`forgetting.note_source`），**不含来源节点 id** ——
拿它反查来源永远查不到（"判据与事实不符"换个地方复发）。故另立 `merge_source_ids`。
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO not in sys.path:
    sys.path.insert(0, _REPO)

from md_cg import _guard_kit as GK        # noqa: E402
from md_cg import forgetting, twophase    # noqa: E402
from md_cg.mdcos import MdCGOS            # noqa: E402

FAILS = []
_TMP = tempfile.mkdtemp(prefix="iss417_")
_CCG = chr(10).join(["# 功能名：目标节点", "# 生效条件：本地合成库", "# 子功能：无",
                     "# 执行：无", "# 验证方式：test", "# 不适用条件：无",
                     "# 正文：目标节点正文"])


def _check(name, cond, detail=""):
    if cond:
        print("  PASS " + name)
    else:
        print("  FAIL " + name + "  " + str(detail)[:220])
        FAILS.append(name)


def _lib(tag):
    d = os.path.join(_TMP, tag)
    os.makedirs(d, exist_ok=True)
    cg = MdCGOS(d)
    cg.add("n_t", _CCG)
    cg.flush()
    cg.close()
    return d


def _crash_window(root, body="PASSED 新增补充。", src="n_x"):
    """构造崩溃窗口的**落盘态**：begin 记意图 → 合并落盘 → **不调 commit**。"""
    cg = MdCGOS(root)
    twophase.begin(cg, src, body, layer="knowledge", actor="writepipe:gated")
    res = forgetting.reinforce(cg, "n_t", content=body, session="s1",
                               actor="writepipe:gated", src_id=src)
    cg.flush()
    cg.close()
    return res


print("== A 组：崩溃窗口的 MERGE 必须判 committed（#417 正题） ==")
_root = _lib("merge")
_res = _crash_window(_root)
_cg = MdCGOS(_root)
_pend = twophase.pending(_cg)
_check("A01 崩溃窗口落盘态成立：有未结清意图 1 条、源 id 未成文",
       len(_pend) == 1 and _cg.get("n_x") is None,
       (_pend, _cg.get("n_x")))
_check("A02 目标盘面留下合并痕迹（fm.merge_source_ids 含来源 id）",
       _pend and _pend[0]["id"] in (((_cg.get("n_t") or {}).get("frontmatter")
                                     or {}).get("merge_source_ids") or []),
       (_cg.get("n_t") or {}).get("frontmatter", {}).get("merge_source_ids"))
_rep = twophase.reconcile(_cg)
_check("A03 对账判 **committed**（修前：interrupted/node_missing）",
       _rep["interrupted"] == 0 and _rep["committed"] == 1, _rep["details"])
_check("A04 判定码带**去向**（merged_into_present:<目标 id>）",
       all(str(d.get("reason", "")).startswith("merged_into_present:")
           for d in _rep["details"]), _rep["details"])
_rows = [r for r in twophase.records(_cg) if r.get("phase") == "outcome"]
_check("A05 账本 outcome 行 = committed（不再给运维报「中断=1」）",
       bool(_rows) and all(r.get("status") == "committed" for r in _rows),
       [{k: r.get(k) for k in ("id", "status", "reason")} for r in _rows])
_check("A06 二次对账幂等（unpaired 归零、结论不变）",
       twophase.reconcile(_cg)["unpaired"] == 0)
_cg.close()

# A07（Lead 指定的「编制面登记」腿）：**删掉索引快照**强制新实例走 _scan_nodes
# 全库重扫 —— 若 merge_source_ids 未在 _node_entry 登记，重扫面就没有该键、
# 判据只在同进程内有效（**重启即失效**，最难发现的假绿形态）。本腿专打这一点。
_root_rescan = _lib("rescan")
_crash_window(_root_rescan)
_snap_p = os.path.join(_root_rescan, "_index.json")
if os.path.exists(_snap_p):
    os.remove(_snap_p)
_cg_r = MdCGOS(_root_rescan)
_rep_r = twophase.reconcile(_cg_r)
_check("A07 编制面登记腿：删快照强制**全库重扫**后新实例仍判 committed（重启不失效）",
       _rep_r["committed"] == 1 and _rep_r["interrupted"] == 0, _rep_r["details"])
_cg_r.close()

# A09（**入口面腿**，补本守卫原来的覆盖缺口）：走**真实票据链** ——
# mdcg_remember(gated=True) → verdict=CONFIRM（出单）→ review_decide(accept)
# → _mutation_execute → B_MERGE → forgetting.reinforce。
# 为什么必须有这条腿（fix-354-python 实测报障）：A 组**直调 reinforce**、绕过票据链 ⇒
# mdcos.py 里 src_id 引用未绑定局部名（UnboundLocalError）那次崩溃逃过了本守卫 ——
# 正是「声称的面 > 实际的面」。夹具**逐字照抄** test_mode_parity R2（:812-819）：
# confirm 档包裹 + 同模板只差一个端口的正文（重叠度够 ⇒ MERGE 提案 ⇒ CONFIRM）。
import contextlib as _ctx              # noqa: E402
from md_cg import autonomy_modes as _am   # noqa: E402
from md_cg import mcp_server as _ms       # noqa: E402
_ENV_MODE = _am.AUTONOMY_ENV_KEYS["mode"]
_R_BODY = ("# 功能名：部署面端口约定" + chr(10)
           + "# 生效条件：载体/位置：prod 集群；时间：2026-09-30 起；方法：部署清单核对；约束：无" + chr(10)
           + "# 子功能：登记各服务监听端口" + chr(10)
           + "# 执行：核对 manifest 的 ports 段" + chr(10)
           + "# 验证方式：test" + chr(10)
           + "# 不适用条件：无" + chr(10) + chr(10)
           + "网关监听端口 8080/HTTP；管理面监听端口 8081/HTTP；"
           + "指标面监听端口 %s/HTTP；日志面监听端口 9091/HTTP" + chr(10))


@_ctx.contextmanager
def _mode(m):
    """照抄 test_mode_parity._mode：临时置档位 env，退出还原。"""
    _old = os.environ.get(_ENV_MODE)
    os.environ[_ENV_MODE] = m
    try:
        yield m
    finally:
        if _old is None:
            os.environ.pop(_ENV_MODE, None)
        else:
            os.environ[_ENV_MODE] = _old


_root_tk = _lib("ticket")
with _mode("confirm"):
    _cgt = MdCGOS(_root_tk, autoflush=0)
    _cgt.add("tk_t", _R_BODY % "8081", layer="knowledge",
             verification_basis="test")
    _cgt.flush()
    _rb = _ms._dispatch(_cgt, "mdcg_remember",
                        {"content": _R_BODY % "9595", "node_id": "tk_n",
                         "gated": True, "layer": "knowledge"})
    _check("A09 票据链①出单：verdict=CONFIRM + moved_to=review_queue + pid",
           _rb.get("verdict") == "CONFIRM"
           and _rb.get("moved_to") == "review_queue" and bool(_rb.get("pid")),
           {k: _rb.get(k) for k in ("verdict", "moved_to", "pid")})
    _dec = (_cgt.review_decide(_rb["pid"], "accept", reason="守卫演练")
            if _rb.get("pid") else {})
    _mut = (_dec or {}).get("mutation") or {}
    _check("A09 票据链②accept 执行成功（修前 UnboundLocalError ⇒ mutation_execute_failed）",
           _dec.get("ok") is True,
           {k: _dec.get(k) for k in ("ok", "error", "detail")})
    _tk_ids = (((_cgt.get("tk_t") or {}).get("frontmatter") or {})
               .get("merge_source_ids") or [])
    _check("A09 票据链③**不得记成目标自己**（本路径无未结清意图 ⇒ 不记；"
           "把目标当来源＝静默错，本腿就是抓这个的）",
           "tk_t" not in _tk_ids, _tk_ids)
    _check("A09 票据链④执行时点回滚载荷完整（rollback 命令非空 ⇒ 回执与盘面同源）",
           bool(str(_mut.get("rollback") or "").strip()),
           {k: str(_mut.get(k))[:60] for k in ("before", "rollback")})
    _cgt.close()

# A10（**真实落点腿**）：`remember_gated` 的 MERGE 支才是 #417 的落点——
# `_gate_gated` 先建意图、合并落盘、再 commit；**崩溃窗口 = 已落盘、未 commit**。
# 本腿直接调 remember_gated（不经过 commit），等于把进程停在该窗口，然后新实例对账。
# （A 组前几条是**直调 reinforce**，只覆盖原语；本腿覆盖**库层入口 + 身份透传**。）
_root_gm = _lib("gatedmerge")
with _mode("full"):                      # full 档：判定即执行（不被出单/变更单截住）
    _cgg = MdCGOS(_root_gm, autoflush=0)
    _cgg.add("gm_t", _R_BODY % "8081", layer="knowledge",
             verification_basis="test")
    _cgg.flush()
    _src = "gm_n"
    twophase.begin(_cgg, _src, _R_BODY % "9595", layer="knowledge",
                   actor="writepipe:gated")           # 模拟 _gate_gated 的先行意图
    _rg = _cgg.remember_gated(_src, _R_BODY % "9595", layer="knowledge")
    _cgg.flush()
    _cgg.close()                                     # 不 commit ⇒ 停在崩溃窗口
_check("A10 库层入口腿①：remember_gated 判 MERGE 且已落盘（merged_into 目标）",
       str(_rg.get("verdict")) == "MERGE" and bool(_rg.get("merged_into")),
       {k: _rg.get(k) for k in ("verdict", "merged_into")})
_cgg2 = MdCGOS(_root_gm)
_gm_ids = (((_cgg2.get("gm_t") or {}).get("frontmatter") or {})
           .get("merge_source_ids") or [])
_check("A10 库层入口腿②：**来源** id 经该落点落盘（src_id=形参 node_id；不是目标）",
       _gm_ids == [_src], _gm_ids)
_rep_gm = twophase.reconcile(_cgg2)
_check("A10 库层入口腿③：新实例对账判 committed（修前 interrupted/node_missing）",
       _rep_gm["committed"] == 1 and _rep_gm["interrupted"] == 0, _rep_gm["details"])
_cgg2.close()
print("== K 组：非恒真对照（新判据只补「已合并」这一种真实情形） ==")
_root_k = _lib("absent")
_cg = MdCGOS(_root_k)
twophase.begin(_cg, "n_never", "从未落盘的正文", layer="knowledge",
               actor="writepipe:gated")
_cg.flush(); _cg.close()
_cg = MdCGOS(_root_k)
_rep_k = twophase.reconcile(_cg)
_check("K01 反向腿：源 id 不在盘上、**无任何合并痕迹** ⇒ 仍须 interrupted/node_missing（不放宽）",
       _rep_k["interrupted"] == 1 and _rep_k["committed"] == 0
       and _rep_k["details"][0]["reason"] == "node_missing", _rep_k["details"])
_cg.close()

_root_d = _lib("direct")
_cg = MdCGOS(_root_d)
twophase.begin(_cg, "n_y", "直接落盘正文", layer="knowledge")
_cg.add("n_y", "直接落盘正文")
_cg.flush(); _cg.close()
_cg = MdCGOS(_root_d)
_rep_d = twophase.reconcile(_cg)
_check("K02 正向腿：源 id 已落盘 ⇒ 仍须 committed/node_present_hash_match（原判据不被扰动）",
       _rep_d["committed"] == 1
       and _rep_d["details"][0]["reason"] == "node_present_hash_match",
       _rep_d["details"])
_cg.close()

_root_n = _lib("noid")
_cg = MdCGOS(_root_n)
forgetting.reinforce(_cg, "n_t", content="补充。", actor="writepipe:gated")
_cg.flush(); _cg.close()
_cg = MdCGOS(_root_n)
_check("K03 不编造：未传 src_id ⇒ merge_source_ids 不出现该来源（缺省不记）",
       not (((_cg.get("n_t") or {}).get("frontmatter") or {})
            .get("merge_source_ids")), 
       (_cg.get("n_t") or {}).get("frontmatter", {}).get("merge_source_ids"))
_check("K04 merge_sources（写入方归属）语义原样保留（{session,actor,t} 三键）",
       all(sorted(s) == sorted(["actor", "session", "t"])
           for s in (((_cg.get("n_t") or {}).get("frontmatter") or {})
                     .get("merge_sources") or [])),
       ((_cg.get("n_t") or {}).get("frontmatter") or {}).get("merge_sources"))
_cg.close()

print("== E 组：判据单点与编制面 ==")
_SRC_T = open(os.path.join(_REPO, "md_cg", "twophase.py"), encoding="utf-8").read()
_SRC_F = open(os.path.join(_REPO, "md_cg", "forgetting.py"), encoding="utf-8").read()
_SRC_M = open(os.path.join(_REPO, "md_cg", "mdcg.py"), encoding="utf-8").read()
_check("E01 _judge 的源缺失分支经 _merge_target 查盘面痕迹（单点，不内联第二套）",
       "_merge_target(cg, nid)" in _SRC_T
       and _SRC_T.count("def _merge_target(") == 1)
_check("E02 未命中仍回 interrupted/node_missing（不放宽的源码面证据）",
       "return STATUS_INTERRUPTED, R_NODE_MISSING" in _SRC_T)
_check("E03 reinforce 有 src_id 形参且写入 fm.merge_source_ids",
       "src_id=None" in _SRC_F.split("def reinforce")[1][:400]
       and "merge_source_ids" in _SRC_F)
_check("E04 写路径同钩镜像 + 编制面登记（不登记则新实例扫描面缺键、判据静默失效）",
       'e["merge_source_ids"] = fm["merge_source_ids"]' in _SRC_F
       and '"merge_source_ids": fm.get("merge_source_ids") or None' in _SRC_M)

print("== 骨架①：枚举完备性自证（_guard_kit.assert_enumeration_complete） ==")


def _discover(texts):
    """守卫自己的枚举逻辑：命中「源缺失分支不查盘面痕迹」的判据实现。"""
    import ast as _ast
    hits = []
    for rel, src in texts.items():
        try:
            tree = _ast.parse(src)
        except SyntaxError:
            continue
        for node in _ast.walk(tree):
            if not isinstance(node, _ast.FunctionDef) or node.name != "_judge":
                continue
            seg = _ast.get_source_segment(src, node) or ""
            if "R_NODE_MISSING" in seg and "_merge_target" not in seg:
                hits.append((rel, node.lineno))
    return hits


_OLD_JUDGE = "def _judge(cg, intent):" + chr(10) + "    if not cg.get(intent['id']):"     + chr(10) + "        return STATUS_INTERRUPTED, R_NODE_MISSING" + chr(10)     + "    return STATUS_COMMITTED, R_NODE_OK"
_NEW_JUDGE = "def _judge(cg, intent):" + chr(10) + "    if not cg.get(intent['id']):"     + chr(10) + "        tgt = _merge_target(cg, intent['id'])" + chr(10)     + "        if tgt:" + chr(10) + "            return STATUS_COMMITTED, 'x'"     + chr(10) + "        return STATUS_INTERRUPTED, R_NODE_MISSING" + chr(10)     + "    return STATUS_COMMITTED, R_NODE_OK"
_ok_e, _det_e = GK.assert_enumeration_complete(
    _discover,
    [("应命中·旧形态（只看源 id）", _OLD_JUDGE, True, "md_cg/twophase_old.py"),
     ("不应命中·新形态（查盘面痕迹）", _NEW_JUDGE, False, "md_cg/twophase_new.py"),
     ("不应命中·无关函数", "def other():" + chr(10) + "    return 1", False,
      "md_cg/other.py")])
_check("E05 骨架①枚举完备性（合成样本含应命中/不应命中两侧）", _ok_e, _det_e)

print("== 骨架② / 变异：回退即红（实跑，不接受推演） ==")
_NL = "\r\n" if b"\r\n" in open(os.path.join(_REPO, "md_cg", "twophase.py"),
                                   "rb").read()[:8192] else "\n"


def _j(*lines):
    return _NL.join(lines)


_MUTATIONS = (
    ("M1 回缺陷：摘掉盘面痕迹反查（回到只看源 id）", "md_cg/twophase.py",
     (_j("        tgt = _merge_target(cg, nid)", "        if tgt:",
         "            return STATUS_COMMITTED, \"%s:%s\" % (R_MERGED_INTO, tgt)"),
      "        pass  # 变异：不查盘面痕迹"),
     ("A03", "A04", "A05", "A07", "A10")),
    ("M2 过度放宽：未命中痕迹也判 committed", "md_cg/twophase.py",
     ("        return STATUS_INTERRUPTED, R_NODE_MISSING",
      "        return STATUS_COMMITTED, R_MERGED_INTO  # 变异：未命中也放行"),
     # E02 是源码形态腿（该行被替换 ⇒ 「不放宽」的源码证据消失，本就该红）
     ("E02", "K01")),
    ("M3 过度收紧：恒判无痕迹（_merge_target 恒 None）", "md_cg/twophase.py",
     ("    nodes = (getattr(cg, \"index\", None) or {}).get(\"nodes\") or {}",
      "    return None  # 变异：恒判无痕迹"),
     ("A03", "A04", "A05", "A07", "A10")),
)


def _mirror_build():
    dst = tempfile.mkdtemp(prefix="iss417_mut_")
    for name in ("md_cg", "scripts"):
        src = os.path.join(_REPO, name)
        if os.path.isdir(src):
            shutil.copytree(src, os.path.join(dst, name),
                            ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    for name in sorted(os.listdir(_REPO)):
        p = os.path.join(_REPO, name)
        if os.path.isfile(p) and (name.endswith(".py")
                                  or name in ("README.md", "pyproject.toml")):
            shutil.copy2(p, os.path.join(dst, name))
    return dst


def _run_in(tree):
    env = dict(os.environ)
    env.update({"PYTHONPATH": tree, "PYTHONUTF8": "1",
                "PYTHONDONTWRITEBYTECODE": "1"})
    env.pop("MDCG_ROOT", None)
    pr = subprocess.run([sys.executable, "-X", "utf8", "-m",
                         "md_cg.test_issue417_twophase_merge_landed"],
                        cwd=tree, env=env, capture_output=True, text=True,
                        encoding="utf-8", errors="replace", timeout=1800)
    out = (pr.stdout or "") + (pr.stderr or "")
    reds = [ln.split("FAIL ", 1)[1].strip()
            for ln in out.splitlines() if ln.strip().startswith("FAIL ")]
    return pr.returncode, reds, out


def _mutate():
    print("!! 定点变异：回缺陷 + 过度放宽 + 过度收紧，守卫必须按指定项转红")
    tree = _mirror_build()
    bad = []
    try:
        rc, reds, out = _run_in(tree)
        print("  未变异镜像基线：rc=%d 红项=%d（必须 rc=0 且 0 红）" % (rc, len(reds)))
        if rc != 0 or reds:
            print(chr(10).join(out.splitlines()[-20:]))
        for desc, rel, (old, new), exp in _MUTATIONS:
            p = os.path.join(tree, rel)
            t = open(p, encoding="utf-8", newline="").read()
            if t.count(old) != 1:
                bad.append("%s 锚点命中 %d 次" % (desc, t.count(old)))
                print("  ANCHOR-MISS " + desc)
                continue
            bak = t
            open(p, "w", encoding="utf-8", newline="").write(t.replace(old, new, 1))
            for r, dd, ff in os.walk(tree):
                if os.path.basename(r) == "__pycache__":
                    shutil.rmtree(r, ignore_errors=True)
            rc2, reds2, o2 = _run_in(tree)
            open(p, "w", encoding="utf-8", newline="").write(bak)
            hit = sorted({r.split(" ")[0] for r in reds2})
            if rc2 != 0 and hit == sorted(exp):
                print("  OK   %s  红项=%d 指定命中=%d/%d"
                      % (desc, len(reds2), len(hit), len(exp)))
            else:
                bad.append(desc)
                print("  MISMATCH %s 实际=%s 期望=%s rc=%d"
                      % (desc, hit, sorted(exp), rc2))
                for r in reds2[:6]:
                    print("        FAIL " + r)

        # 骨架②：回退即红（实跑：把 _judge 的盘面痕迹分支整体回退）
        ok_r, det_r = GK.assert_revert_reddens(
            _mirror_build,
            [("md_cg/twophase.py",
              _j("        tgt = _merge_target(cg, nid)", "        if tgt:",
                  "            return STATUS_COMMITTED, \"%s:%s\" % (R_MERGED_INTO, tgt)"),
              "        pass  # 回退：不查盘面痕迹")],
            _run_in, ("A03", "A04", "A05", "A07", "A10"), "md_cg/twophase.py")
        print("  骨架②回退即红：%s %s" % ("OK" if ok_r else "MISMATCH",
                                          json.dumps(det_r, ensure_ascii=False)[:220]))
        if not ok_r:
            bad.append("骨架②回退未按预期转红")
        print("定点变异自证：%s（%d 条不合格）" % ("PASS" if not bad else "FAIL", len(bad)))
        return len(bad)
    finally:
        shutil.rmtree(tree, ignore_errors=True)


shutil.rmtree(_TMP, ignore_errors=True)
print("")
print("issue #417 结果：%s" % ("全部通过" if not FAILS else "%d 失败" % len(FAILS)))


def main():
    _bad = _mutate() if "--mutate" in sys.argv else 0
    return 1 if (FAILS or _bad) else 0


if __name__ == "__main__":
    sys.exit(main())
