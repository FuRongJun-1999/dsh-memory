# -*- coding: utf-8 -*-
# 功能名：索引判据必须**先探活**——依赖闸不得因陈旧条目硬拒合法写入（issue #415）
# 生效条件：python -X utf8 -m md_cg.test_issue415_deps_gate_probe [--mutate]；被测面＝md_cg/writepipe.py::_gate_deps（E051 依赖存在性判据）+ md_cg/protect.py::known_nodes（集合形态的探活单点）+ md_cg/forgetting.py::prior_node（同族 T1 站点）
# 子功能：A 组＝两实例陈旧索引端到端（修前硬拒 E051 / 修后放行 + 探活计数）+ prior_node 同族腿；K 组＝非恒真（真不存在仍拒、E050 不变、一次判定只探活一次）；E 组＝判据单点与族清单（T1 面读索引必过单点）；变异双向 + _guard_kit 两骨架
# 执行：--mutate 时在镜像树里回缺陷（裸读索引）/ 过度（单点恒空）/ 只加壳不接线（摘掉探活调用），守卫必须按指定项转红
# 验证方式：全部 PASS 即通过（退出码 0）；变异与骨架红项集合须与预期逐项相符
# 不适用条件：不判 T2/T3 档（族清单已逐条登记为「写后只读 / 读面报表」，本批不接线）；不判他进程间的**真并发**窗口（本守卫用「先开实例、后他实例写」构造同一落盘态，属可控近似）；不判其它 E 码闸（ccgc._check_deps 等各闸自守）；不测写入吞吐（只断言探活次数，不测墙钟）
"""issue #415 守卫：判据读的不是当下的真值 —— 依赖闸同族。

病象（修前）：writepipe._gate_deps 判「依赖目标是否存在」时**裸读**
set((getattr(cg, "index", None) or {}).get("nodes") or {})，判前**无** _maybe_reload_index
探活（实测该函数体内探活 0 次）。他进程（serve 常驻 / 另一实例）刚建的依赖目标在**陈旧
条目**里查不到 ⇒ **合法写入被硬拒** E051「依赖目标不存在」。与 #403「陈旧 ⇒ 误放行覆写」
**同族、后果相反**（那边静默放过，这边把正确的事拒掉）。

修法：#415 与 #403 同款——判前探活**收成必经单点**，而不是「记得在每个判据前调一次」：
· protect._probe(cg)：探活的**唯一实现**；
· protect.known_nodes(cg)（集合形态）与既有 protect._entry(cg, id)（单条目形态）**同形同实现**：
  一次探活 + 返回同一数据面；
· writepipe._gate_deps 与同族站点 forgetting.prior_node 都改调它。

**族清单（T1/T2/T3 三档，本批只接线 T1）**：
· **T1（判据决定一次盘面写入/删除 ⇒ 必须接线）**：writepipe._gate_deps（本件）、
  forgetting.prior_node（本件；它是 rollback.preimage_for 的前置闸，误判会让执行时点前像
  整个不拍、回滚载荷为空——**实测已推翻**其旧注释「最坏只漏标一次提示」）。
  其余 T1 候选（ccgc._check_deps、branches.merge/discard、consolidate.rollback_*、
  mdcos._autonomy_gate_merge、trust.propagate/backfill）**本批未接线**，如实登记为待办。
· **T2（写后只读 / 单进程 CLI 面）**：backfill.*、migrate*、crosscheck.*、*_rollback 等。
· **T3（读面 / 报表 / 诊断）**：sustain.diagnose、subgraph.*、refindex.*、export.* 等。
"""
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO not in sys.path:
    sys.path.insert(0, _REPO)

from md_cg import _guard_kit as GK          # noqa: E402
from md_cg import forgetting, nodefile, protect, writepipe   # noqa: E402
from md_cg.mdcos import MdCGOS              # noqa: E402

FAILS = []
_TMP = tempfile.mkdtemp(prefix="iss415_")
_MARK = nodefile.DEP_REF_MARK
_DEP = chr(10).join(["# 功能名：被依赖节点", "# 生效条件：本地合成库", "# 子功能：无",
                     "# 执行：无", "# 验证方式：test", "# 不适用条件：无",
                     "# 正文：地基正文"])


def _code_only(src):
    """去掉注释/文档字符串（ast.unparse 只留代码）——注释里引用旧形态不算残留。"""
    import ast as _a
    import textwrap as _t
    return _a.unparse(_a.parse(_t.dedent(src)))

def _body(name, dep):
    return chr(10).join(["# 功能名：" + name, "# 生效条件：本地合成库",
                         "# 子功能：" + _MARK + dep,
                         "# 执行：无", "# 验证方式：test", "# 不适用条件：无",
                         "# 正文：" + name + "正文"])


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
    cg.flush()
    cg.close()
    return d


def _counting_probe(cg):
    """给实例挂计数包装（探活次数可观测）。"""
    box = {"n": 0}
    orig = cg._maybe_reload_index

    def _w(*a, **kw):
        box["n"] += 1
        return orig(*a, **kw)
    cg._maybe_reload_index = _w
    return box


print("== A 组：两实例陈旧索引（#415 正题） ==")
_root = _lib("stale")
_writer = MdCGOS(_root)
_gate = MdCGOS(_root)                     # 闸方**先开** ⇒ 索引停在 dep_x 之前
_check("A01 构造成立：闸方索引里查无 dep_x（陈旧条目）",
       "dep_x" not in tuple((_gate.index.get("nodes") or {})))
_writer.add("dep_x", _DEP, layer="knowledge")
_writer.flush()
_check("A02 写方落盘后，闸方**仍**看不到 dep_x（陈旧未自动过期）",
       "dep_x" not in tuple((_gate.index.get("nodes") or {})))
_box = _counting_probe(_gate)
_known = protect.known_nodes(_gate)
_check("A03 修后单点判据：探活一次后 dep_x **可见**（修前裸读判据为 False）",
       "dep_x" in _known and _box["n"] == 1, (_box["n"], sorted(_known)[:5]))
_pipe = writepipe.install_default_gates(writepipe.WritePipeline())
_o1 = _pipe.execute(_gate, {"content_kind": "text", "content": _body("依赖方", "dep_x"),
                            "layer": "knowledge", "node_id": "d_n",
                            "depends_on": ["dep_x"]})
_check("A04 修后端到端：合法写入**放行**（ok=True / error=None；修前 = E051 硬拒）",
       _o1.get("ok") is True and _o1.get("error") is None,
       {k: _o1.get(k) for k in ("ok", "error", "missing")})
_check("A05 同族站点 prior_node 已接线：陈旧实例上仍认得 dep_x（修前 None ⇒ 前像不拍、回滚载荷为空）",
       forgetting.prior_node(_gate, "dep_x") == "dep_x",
       forgetting.prior_node(_gate, "dep_x"))
_writer.close()
_gate.close()

# A06（**直调判据腿**）：端到端反而**掩盖**本缺陷——全链里靠前的闸会先探活，等轮到 _gate_deps
# 时索引已被刷新（M1 变异实测：A04 仍绿）。故本腿**直调判据**，让陈旧读可观测：
# 修后 = 探活后可见 ⇒ 放行（None）；修前 = 裸读判据 ⇒ E051 硬拒。
_box4 = _counting_probe(_gate2) if False else None
_root_s = _lib("direct")
_w2 = MdCGOS(_root_s)
_g2 = MdCGOS(_root_s)                     # 闸方先开 ⇒ 陈旧
_w2.add("dep_y", _DEP, layer="knowledge")
_w2.flush()
_box_s = _counting_probe(_g2)
_ctx_s = {"a": {"content": _body("依赖方5", "dep_y"), "depends_on": ["dep_y"]},
          "cg": _g2, "nid": "s_n", "verdict": {}}
_gout_s = writepipe._gate_deps(_ctx_s)
_check("A06 直调判据腿：陈旧实例上依赖目标**探活后可见** ⇒ 放行（修前裸读 ⇒ E051 硬拒）",
       _gout_s is None and _box_s["n"] == 1,
       (_gout_s, _box_s["n"]))
_w2.close()
_g2.close()

print("== K 组：非恒真对照 ==")
_root_k = _lib("k")
_cgk = MdCGOS(_root_k)
_cgk.add("dep_ok", _DEP, layer="knowledge")
_cgk.flush()
_box2 = _counting_probe(_cgk)
_pipe2 = writepipe.install_default_gates(writepipe.WritePipeline())
_o2 = _pipe2.execute(_cgk, {"content_kind": "text", "content": _body("依赖方2", "no_such_dep"),
                             "layer": "knowledge", "node_id": "k_m",
                             "depends_on": ["no_such_dep"]})
_check("K01 反向腿：目标**真不存在** ⇒ 仍须硬拒 E051（探活不放宽判据）",
       _o2.get("ok") is False and _o2.get("error") == "E051"
       and _o2.get("missing") == ["no_such_dep"], _o2.get("error"))
_o3 = _pipe2.execute(_cgk, {"content_kind": "text", "content": _body("依赖方3", "dep_ok"),
                             "layer": "knowledge", "node_id": "k_p",
                             "depends_on": ["dep_ok"]})
_check("K02 目标齐备 ⇒ 放行（原判据的正常路径不受扰）", _o3.get("ok") is True,
       {k: _o3.get(k) for k in ("ok", "error")})
_nodep = chr(10).join(["# 功能名：无依赖声明", "# 生效条件：本地合成库",
                        "# 子功能：无", "# 执行：无", "# 验证方式：test",
                        "# 不适用条件：无", "# 正文：无依赖正文"])
_o4 = _pipe2.execute(_cgk, {"content_kind": "text", "content": _nodep,
                             "layer": "knowledge", "node_id": "k_q"})
_check("K03 无依赖声明 ⇒ 照旧放行（E050 语义未被扰动）", _o4.get("ok") is True,
       {k: _o4.get(k) for k in ("ok", "error")})
_box3 = _counting_probe(_cgk)
_ctx = {"a": {"content": _body("依赖方4", "dep_ok"), "depends_on": ["dep_ok"]},
        "cg": _cgk, "nid": "k_r", "verdict": {}}
_gout = writepipe._gate_deps(_ctx)
_check("K04 单点语义：一次判定只探活**一次**（多 dep 共用；非每 dep 一次）",
       _gout is None and _box3["n"] == 1, (_gout, _box3["n"]))
_cgk.close()

print("== E 组：判据单点与族清单 ==")
_W = open(os.path.join(_REPO, "md_cg", "writepipe.py"), encoding="utf-8").read()
_P = open(os.path.join(_REPO, "md_cg", "protect.py"), encoding="utf-8").read()
_F = open(os.path.join(_REPO, "md_cg", "forgetting.py"), encoding="utf-8").read()
_GD = _W.split("def _gate_deps(ctx):")[1].split(chr(10) + "def ")[0]
_Q = chr(34)
# 代码级口径：注释里引用了旧形态**不算残留**（本文件注释就是要交代被替换成什么）——
# 故先经 ast.unparse 去注释/文档串再断言；_GD 是 def 行之后的正文，须补回 def 才能 parse。
_GD_CODE = _code_only("def _gate_deps(ctx):" + _GD)
_E01_A = "protect.known_nodes(cg)" in _GD_CODE
_E01_B = "set((getattr(cg, " + _Q + "index" + _Q not in _GD_CODE
_check("E01 _gate_deps 经单点取判据面（known_nodes），且**代码里无裸读残留**",
       _E01_A and _E01_B,
       (_E01_A, _E01_B, _GD_CODE.count("known_nodes")))
_check("E02 单点唯一：探活实现 _probe 全仓恰一处定义",
       len(re.findall(r"def _probe\(cg\):", _P)) == 1)
_check("E03 两种形态共用同一探活实现（_entry 与 known_nodes 都调 _probe，未内联第二份）",
       "_probe(cg)" in _P and _P.count("def _probe(cg):") == 1
       and "getattr(cg, " + _Q + "_maybe_reload_index" + _Q + ", None)" in _P)
_check("E04 同族站点 prior_node 亦经单点（T1 接线）",
       "protect.known_nodes(cg)" in _F)
_check("E05 #413 定稿面未被扰动：_preimage_name 定义 1 处、两侧调用仍在",
       len(re.findall(r"def _preimage_name\(", _P)) == 1
       and "_preimage_name(d)" in _P
       and "_preimage_name(d, " + _Q + "-%06d" + _Q in _P)
_check("E06 导入面：writepipe 已引 protect（同包内，无环）",
       re.search(r"from \. import protect", _W) is not None)

print("== 骨架①：枚举完备性（T1 面「读索引判据」的两种形态） ==")


def _discover(texts):
    """守卫自己的枚举：命中「读索引 nodes 却未经探活单点」的判据函数。"""
    import ast as _ast
    hits = []
    for rel, src in texts.items():
        try:
            tree = _ast.parse(src)
        except SyntaxError:
            continue
        for node in _ast.walk(tree):
            if not isinstance(node, _ast.FunctionDef):
                continue
            seg = _ast.get_source_segment(src, node) or ""
            if _Q + "nodes" + _Q not in seg or "index" not in seg:
                continue
            if ("known_nodes" in seg or "_probe(" in seg
                    or "_maybe_reload_index" in seg):
                continue
            hits.append((rel, node.lineno))
    return hits


_OLD = ("def _gate_deps(ctx):" + chr(10) + "    cg = ctx[" + _Q + "cg" + _Q + "]" + chr(10)
        + "    known = set((getattr(cg, " + _Q + "index" + _Q + ", None) or {}).get("
        + _Q + "nodes" + _Q + ") or {})" + chr(10) + "    return known")
_NEW = ("def _gate_deps(ctx):" + chr(10) + "    cg = ctx[" + _Q + "cg" + _Q + "]" + chr(10)
        + "    known = protect.known_nodes(cg)" + chr(10) + "    return known")
_ok_e, _det_e = GK.assert_enumeration_complete(
    _discover,
    [("应命中·旧形态（裸读索引判据）", _OLD, True, "writepipe_old.py"),
     ("不应命中·新形态（经探活单点）", _NEW, False, "writepipe_new.py"),
     ("不应命中·无关函数", "def other():" + chr(10) + "    return 1", False, "x.py")])
_check("E07 骨架①枚举完备性（应命中/不应命中两侧）", _ok_e, _det_e)

print("== 骨架② / 变异 ==")
_NL = "\r\n" if b"\r\n" in open(os.path.join(_REPO, "md_cg", "writepipe.py"),
                                   "rb").read()[:8192] else "\n"


def _j(*lines):
    return _NL.join(lines)


_RAW = ("    known = set((getattr(cg, " + _Q + "index" + _Q + ", None) or {}).get("
        + _Q + "nodes" + _Q + ") or {})")
_GOOD = "    known = protect.known_nodes(cg)"
_RET_LINE = "        return (getattr(cg, " + _Q + "index" + _Q + ", None) or {}).get(" + _Q + "nodes" + _Q + ") or {}"
_PROT_NL = chr(10)   # protect.py 是 LF（writepipe 是 CRLF）——锚点行尾按**目标文件**取，
                     # 用错行尾会 ANCHOR-MISS（实测踩过）
_PROBE_PAIR = _PROT_NL.join(["    _probe(cg)", "    try:"])
_M1 = ("M1 回缺陷：依赖闸改回裸读索引（判前不探活）", "md_cg/writepipe.py",
       [(_GOOD, _RAW)],
       # A04（端到端）**不参与判别**：全链前序闸已探活并把索引刷新 ⇒ 掩盖本缺陷
       ("A06", "E01", "K04"))
_M2 = ("M2 过度：单点恒空（判据失去事实来源 ⇒ 合法写入被误拒）", "md_cg/protect.py",
       [(_RET_LINE, "        return {}")], ("A03", "A04", "A05", "A06", "K02", "K04"))
_M3 = ("M3 只加壳不接线：known_nodes 摘掉探活调用", "md_cg/protect.py",
       [(_PROBE_PAIR, "    try:")], ("A03", "A04", "A05", "A06", "K04"))
_MUTATIONS = (_M1, _M2, _M3)


def _mirror_build():
    dst = tempfile.mkdtemp(prefix="iss415_mut_")
    # data/ = **判据所需的非 .py 数据面**（audit 的包内默认策略 <根>/data/policy.json）：
    # 漏拷会让所有走 writepipe 的腿在镜像里恒 policy_unavailable ⇒ 镜像基线假红（实测踩过）。
    for name in ("md_cg", "scripts", "data"):
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
                         "md_cg.test_issue415_deps_gate_probe"],
                        cwd=tree, env=env, capture_output=True, text=True,
                        encoding="utf-8", errors="replace", timeout=1800)
    out = (pr.stdout or "") + (pr.stderr or "")
    reds = [ln.split("FAIL ", 1)[1].strip()
            for ln in out.splitlines() if ln.strip().startswith("FAIL ")]
    return pr.returncode, reds, out


def _mutate():
    tree = _mirror_build()
    bad = []
    try:
        rc, reds, out = _run_in(tree)
        print("  未变异镜像基线：rc=%d 红项=%d（必须 rc=0 且 0 红）" % (rc, len(reds)))
        if rc != 0 or reds:
            print(chr(10).join(out.splitlines()[-20:]))
        for desc, rel, pairs, exp in _MUTATIONS:
            p = os.path.join(tree, rel)
            t = open(p, encoding="utf-8", newline="").read()
            if any(t.count(o) != 1 for o, _n in pairs):
                bad.append("%s 锚点命中 %s" % (desc, [t.count(o) for o, _n in pairs]))
                print("  ANCHOR-MISS " + desc)
                continue
            bak = t
            for o, n in pairs:
                t = t.replace(o, n, 1)
            open(p, "w", encoding="utf-8", newline="").write(t)
            for r, dd, ff in os.walk(tree):
                if os.path.basename(r) == "__pycache__":
                    shutil.rmtree(r, ignore_errors=True)
            rc2, reds2, _o2 = _run_in(tree)
            open(p, "w", encoding="utf-8", newline="").write(bak)
            hit = sorted({r.split(" ")[0] for r in reds2})
            if rc2 != 0 and hit == sorted(exp):
                print("  OK   %s 红项=%d 指定命中=%d/%d" % (desc, len(reds2), len(hit), len(exp)))
            else:
                bad.append(desc)
                print("  MISMATCH %s 实际=%s 期望=%s rc=%d" % (desc, hit, sorted(exp), rc2))
                for r in reds2[:6]:
                    print("        FAIL " + r)
        ok_r, det_r = GK.assert_revert_reddens(
            _mirror_build, [("md_cg/writepipe.py", _GOOD.replace("\r\n", "\n"),
                             _RAW.replace("\r\n", "\n"))],
            _run_in, ("A06", "E01", "K04"), "md_cg/writepipe.py")
        print("  骨架②回退即红：%s %s" % ("OK" if ok_r else "MISMATCH",
                                          json.dumps(det_r, ensure_ascii=False)[:200]))
        if not ok_r:
            bad.append("骨架②未按预期转红")
        print("定点变异自证：%s（%d 条不合格）" % ("PASS" if not bad else "FAIL", len(bad)))
        return len(bad)
    finally:
        shutil.rmtree(tree, ignore_errors=True)


shutil.rmtree(_TMP, ignore_errors=True)
print("")
print("issue #415 结果：%s" % ("全部通过" if not FAILS else "%d 失败" % len(FAILS)))


def main():
    _bad = _mutate() if "--mutate" in sys.argv else 0
    return 1 if (FAILS or _bad) else 0


if __name__ == "__main__":
    sys.exit(main())