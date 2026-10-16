# -*- coding: utf-8 -*-
# 功能名：consolidate 归纳池过滤接入既有保护规则 + _link_concept 成员写盘点补双闸（issue #432）
# 生效条件：python -X utf8 -m md_cg.test_issue432_induce_protected_pool [--mutate]；被测面＝md_cg/consolidate.py::induce_memories 候选池与 _link_concept 成员写盘 + md_cg/protect.py::is_protected_entry 单点 + freshness 载体上收
# 子功能：A 组＝#432 正题（self/anchor 层未打位节点不入池、apply 零写零快照零审计、显式位支照旧、正常路径不误伤、_link_concept 受保护成员硬拒）；K 组＝非恒真对照（条目单点与权威 is_protected 逐节点一致、heuristic 高分不认回、hint 高分认、空条目不误判、dry-run 读数一致、skipped_protected 只计源层）；E 组＝接线单点存在性（池接线 / 写盘点闸门紧邻 / 单点转发 / freshness 载体上收）
# 执行：--mutate 时在镜像树里逐条把判据改回改动前形态 / 摘掉写盘点闸门 / 把单点改回只读位，守卫必须按指定项转红
# 验证方式：全部 PASS 即通过（退出码 0）；--mutate 下每条变异的红项集合须与预期**逐项相符**（多红/少红皆不合格）
# 不适用条件：不判概念节点自身的生成质量与密级面（#164 / test_p6 已盖）；不判 admin 闸与 MCP 工具面分发（op_table / mcp_server 既有守卫）；不判 freshness 衰减公式（test_issue378 专属）；不判 promote/contextualize 兄弟路径（无成员写盘点）
"""issue #432 守卫：归纳候选池必须与**既有保护规则**同源；成员写盘点必须过双闸。

病象（修前，issue 原文 + 本仓复现探针）：
  · `induce_memories` 候选池过滤只读 `and not (e or {}).get("protected")` 一位
    ⇒ 6 个 self 层模板节点（fm.protected 全 None、权威 `protect.is_protected`
    全 True）在 `source_layer='self'` 下全部入池（nodes_scanned=6）；
  · `apply=True` 后每个成员被写 `induced_concept` / `consolidated_into` /
    `consolidated_at` / `edges` 四字段——`_link_concept` 成员写盘点直调
    `cg._write_node`，不经 `guard_overwrite`，`_protected_history` 快照数 0、
    `_protected_audit` 行数 0（无痕、无回滚句柄）；对照 `protect.guard_overwrite`
    对同一节点是 ProtectionError（硬拒）；
  · 位支正常（`protect.mark` 打位的 contextual 节点被正确排除）、默认
    `source_layer='contextual'` 不触发——缺陷需显式指 self/anchor 层（admin 面
    `consolidate_run(action="induce")` 与 sleep 固化第②步均可达）。

修法（与 #377/#378 的 D1/D2 同源）：
  1. 抽 `protect.is_protected_entry(e)` 单点（条目形态探针，判据本体仍是
     `protect.is_protected` 的三条真源：层保护 self/anchor ∪ 显式 protected 位
     ∪ 按分保护 ≥0.70 且来源缺省/hint）；freshness 的 #378 载体上收为转发，
     不再自复制第二份探针；
  2. 池过滤改走该单点（位支是三真源之一，短路语义不变 ⇒ 超集，既有判定
     一字不减），rep 记 `skipped_protected`；
  3. `_link_concept` 成员写盘点补 `protect.guard_overwrite`（层闸 + 保护闸，
     层/敏感度取成员 fm 真值，顺序紧邻 `_write_node`——#416 写点纪律），
     受保护成员抛 ProtectionError 不落盘。
"""
import inspect
import os
import shutil
import subprocess
import sys
import tempfile

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO not in sys.path:
    sys.path.insert(0, _REPO)

from md_cg import consolidate as C    # noqa: E402
from md_cg import freshness as FR     # noqa: E402
from md_cg import protect as P        # noqa: E402
from md_cg.consolidate import _link_concept  # noqa: E402
from md_cg.mdcos import MdCGOS        # noqa: E402

FAILS = []


def _check(name, cond, detail=""):
    if cond:
        print("  PASS " + name)
    else:
        print("  FAIL " + name + "  " + str(detail)[:220])
        FAILS.append(name)


#: 与生产归纳夹具同口径：正文带「生效条件」行（common_pos 判据）+ 高相似
#: bigram 载荷（jaccard≥0.30、min_cluster=3 可满足）。
BODY = ("# 功能名：自我层复盘模板\n"
        "# 生效条件：每日复盘\n"
        "固定动作：写日志、列任务、清空收件箱，保持节奏\n")

MEMBER_FIELDS = ("consolidated_into", "consolidated_at", "induced_concept")


def _audit_lines(root):
    p = os.path.join(root, P.AUDIT_FILE)
    if not os.path.exists(p):
        return 0
    with open(p, encoding="utf-8") as f:
        return len([ln for ln in f.read().splitlines() if ln.strip()])


def _mk_cg(tag, spec):
    """spec = [(layer, n, importance)] → 返回 (root, cg)；节点 id = {layer}_{i}。"""
    root = tempfile.mkdtemp(prefix="iss432_%s_" % tag)
    cg = MdCGOS(root)
    for layer, n, imp in spec:
        for i in range(1, n + 1):
            cg.add("%s_%d" % (layer, i), BODY, layer=layer,
                   importance=(imp if imp is not None else 0.5))
    cg.flush()
    return root, cg


print("== A 组：#432 正题——池过滤三真源 + 成员写盘点双闸 ==")
root, cg = _mk_cg("a", [("self", 6, None)])
try:
    _check("A01 修前病象腿：self 层未打位节点不入池（issue 实测修前 nodes_scanned=6）",
           C.induce_memories(cg, source_layer="self", apply=False)
           ["nodes_scanned"] == 0, "nodes_scanned 应为 0")
    rep = C.induce_memories(cg, source_layer="self", apply=False)
    _check("A02 池读数记 skipped_protected=6（保护面可观测，不是静默消失）",
           rep.get("skipped_protected") == 6, str(rep.get("skipped_protected")))
    # 池过滤是第一道闸；若池判据回缺陷，apply 会撞上 _link_concept 的第二道闸
    # （成员写盘 guard_overwrite → ProtectionError 崩溃式拒写）——两道闸是纵深
    # 关系，本断言钉住「池必须在第一道收口，不得靠第二道兜底才算修好」。
    _crash = None
    try:
        rep3 = C.induce_memories(cg, source_layer="self", apply=True)
    except P.ProtectionError as ex:      # noqa: F841 —— 池回缺陷时的崩溃即红项
        rep3, _crash = None, ex
    _check("A03 apply=True 零归纳且不撞闸（clusters=0 / written=0，无 ProtectionError）",
           _crash is None and rep3["clusters"] == 0 and rep3["written"] == 0,
           "crash=%s clusters=%s written=%s"
           % (type(_crash).__name__ if _crash else None,
              (rep3 or {}).get("clusters"), (rep3 or {}).get("written")))
    fm = (cg.get("self_1") or {}).get("frontmatter") or {}
    _check("A04 成员四字段零写入（修前被写 consolidated_into/induced_concept 等）",
           not any(fm.get(k) for k in MEMBER_FIELDS)
           and not (fm.get("edges") or []), str({k: fm.get(k) for k in MEMBER_FIELDS}))
    _check("A05 无痕面闭合：_protected_history 快照数 0 且 _protected_audit 零行"
           "（修前同样零快照零审计——但成员已被改写；修后根本不写）",
           len(P.history(cg, "self_1")) == 0 and _audit_lines(root) == 0,
           (len(P.history(cg, "self_1")), _audit_lines(root)))
finally:
    cg.close()
    shutil.rmtree(root, ignore_errors=True)

root, cg = _mk_cg("anchor", [("anchor", 4, None)])
try:
    _r = C.induce_memories(cg, source_layer="anchor", apply=False)
    _check("A06 layer=anchor 同腿（不是 self 特例）",
           _r["nodes_scanned"] == 0 and _r.get("skipped_protected") == 4,
           "scanned=%s skipped=%s" % (_r["nodes_scanned"], _r.get("skipped_protected")))
finally:
    cg.close()
    shutil.rmtree(root, ignore_errors=True)

# 位支（修前即正常）：显式 protected 位照旧排除——超集修复不改变既有判定。
root, cg = _mk_cg("bit", [("contextual", 4, None)])
try:
    P.mark(cg, "contextual_1", "iss432 位支")
    P.mark(cg, "contextual_2", "iss432 位支")
    cg.flush()
    _r = C.induce_memories(cg, source_layer="contextual", apply=False)
    _check("A07 位支照旧：mark 打位的 2 节点被排除且计入 skipped_protected",
           _r["nodes_scanned"] == 2 and _r.get("skipped_protected") == 2,
           "scanned=%s skipped=%s" % (_r["nodes_scanned"], _r.get("skipped_protected")))
finally:
    cg.close()
    shutil.rmtree(root, ignore_errors=True)

# 不误伤：正常 contextual 节点照常归纳、成员照常写盘（闸门不得拦合法面）。
root, cg = _mk_cg("happy", [("contextual", 4, None)])
try:
    _r = C.induce_memories(cg, source_layer="contextual", apply=True)
    fm = (cg.get("contextual_1") or {}).get("frontmatter") or {}
    _check("A08 正常路径不误伤：4 节点全入池、归纳落库、成员四字段写入",
           _r["nodes_scanned"] == 4 and _r.get("skipped_protected") == 0
           and _r["clusters"] == 1 and _r["written"] == 1
           and bool(fm.get("consolidated_into"))
           and len(fm.get("edges") or []) == 1, str({_k: _r.get(_k) for _k in
                                                     ("nodes_scanned", "clusters",
                                                      "written", "skipped_protected")}))
finally:
    cg.close()
    shutil.rmtree(root, ignore_errors=True)

# _link_concept 成员写盘点（修前直调 cg._write_node 无闸；修后硬拒）。
root, cg = _mk_cg("link", [("self", 2, None), ("contextual", 1, None)])
try:
    _raised = False
    try:
        _link_concept(cg, "concept_probe_zzz", ["self_1"], "iss432", "probe", "b0")
    except P.ProtectionError:
        _raised = True
    fm = (cg.get("self_1") or {}).get("frontmatter") or {}
    _check("A09 _link_concept 受保护成员 → ProtectionError 且盘面未写"
           "（对照修前：直写 consolidated_into，对照 guard_overwrite 同判硬拒）",
           _raised and not any(fm.get(k) for k in MEMBER_FIELDS),
           "raised=%s fm=%s" % (_raised, {k: fm.get(k) for k in MEMBER_FIELDS}))
    _out = _link_concept(cg, "concept_probe_zzz", ["contextual_1"], "iss432",
                         "probe", "b0")
    fm2 = (cg.get("contextual_1") or {}).get("frontmatter") or {}
    _check("A10 _link_concept 未受保护成员照常写（闸门不误伤合法写）",
           _out.get("members") == ["contextual_1"]
           and bool(fm2.get("consolidated_into")), str(_out))
finally:
    cg.close()
    shutil.rmtree(root, ignore_errors=True)

print("== K 组：非恒真对照（单点一致性 + 边界不翻转 + 读数口径） ==")
# K01：条目单点与权威判据在真实库上逐节点同判（同 corpus 覆盖层保护/位/分数各腿）。
root, cg = _mk_cg("parity", [("self", 2, None), ("anchor", 1, None),
                             ("contextual", 2, 0.9), ("knowledge", 2, 0.4)])
try:
    P.mark(cg, "contextual_1", "iss432 位支")
    cg.flush()
    _bad = []
    for nid, e in list((((cg.index or {}).get("nodes") or {})).items()):
        if P.is_protected_entry(e)[0] != P.is_protected(cg, nid)[0]:
            _bad.append(nid)
    _check("K01 is_protected_entry 与权威 is_protected 逐节点同判（单点不漂移）",
           not _bad, str(_bad))
finally:
    cg.close()
    shutil.rmtree(root, ignore_errors=True)

_check("K02 heuristic 高分不认回（issue50-e 边界不被本修复翻转）",
       P.is_protected_entry({"importance": 0.9,
                             "importance_source": "heuristic"})[0] is False, "")
_check("K03 hint 高分认保护（边界另一侧；缺省来源同腿由 K01 corpus 的 0.9 节点覆盖）",
       P.is_protected_entry({"importance": 0.9,
                             "importance_source": "hint"})[0] is True, "")
_check("K04 空条目 / None / 非映射不误判（一律未受保护）",
       P.is_protected_entry({})[0] is False
       and P.is_protected_entry(None)[0] is False
       and P.is_protected_entry("not-a-dict")[0] is False, "")

root, cg = _mk_cg("dryrun", [("self", 3, None), ("contextual", 3, None)])
try:
    _dry = C.induce_memories(cg, source_layer="self", apply=False)
    try:
        _app = C.induce_memories(cg, source_layer="self", apply=True)
    except P.ProtectionError:
        _app = {"skipped_protected": -1, "nodes_scanned": -1}
    _check("K05 dry-run 与 apply 的池读数一致（预演面不骗人）",
           _dry.get("skipped_protected") == _app.get("skipped_protected") == 3
           and _dry["nodes_scanned"] == _app["nodes_scanned"] == 0,
           "dry=%s app=%s" % (_dry.get("skipped_protected"),
                              _app.get("skipped_protected")))
    _r2 = C.induce_memories(cg, source_layer="contextual", apply=False)
    _check("K06 skipped_protected 只计源层内（self 层受保护节点不污染 contextual 读数）",
           _r2["nodes_scanned"] == 3 and _r2.get("skipped_protected") == 0,
           "scanned=%s skipped=%s" % (_r2["nodes_scanned"],
                                      _r2.get("skipped_protected")))
finally:
    cg.close()
    shutil.rmtree(root, ignore_errors=True)

print("== E 组：接线单点存在性 ==")
_src_i = inspect.getsource(C.induce_memories)
_check("E01 induce_memories 池过滤经 protect.is_protected_entry 接入（接线未脱焊）",
       "protect.is_protected_entry(e)" in _src_i,
       [ln for ln in _src_i.splitlines() if "is_protected_entry" in ln])
_src_l = inspect.getsource(C._link_concept)
_check("E02 _link_concept 成员写盘点过 protect.guard_overwrite 且紧邻 _write_node"
       "（#416 写点纪律）",
       "protect.guard_overwrite(cg, m," in _src_l
       and "override=False, actor=actor)\n        cg._write_node(m," in _src_l, "")
_check("E03 protect.is_protected_entry 转发权威判据（规则单点，条目形态零规则载体）",
       "is_protected(_EntryProbe(e), _ENTRY_PROBE_ID)"
       in inspect.getsource(P.is_protected_entry), "")
_src_f = inspect.getsource(FR)
_check("E04 freshness 载体上收（#378 的 _is_protected_entry 转发单点，不再自复制探针）",
       "protect.is_protected_entry(entry)"
       in inspect.getsource(FR._is_protected_entry)
       and "class _EntryProbe" not in _src_f, "")

print("")
if FAILS:
    print("issue #432 结果：%d 失败" % len(FAILS))
else:
    print("issue #432 结果：全部通过")


_MUTATIONS = (
    # 锚点一律**单行**（仓库源文件是 CRLF 行尾，多行锚点跨行尾即失配）。
    ("M1 回缺陷：池过滤只读 protected 一位", "md_cg/consolidate.py",
     ("        if protect.is_protected_entry(e)[0]:",
      "        if (e or {}).get(\"protected\"):"),
     # 机制：旧判据只认显式位 ⇒ 层保护/按分保护两腿断：self/anchor 层重新入池
     # （A01/A02/A06）、skipped_protected 读数归零（K05）、接线形态脱焊（E01）；
     # apply 腿撞上 _link_concept 的第二道闸崩溃式拒写（A03 记红——两道闸是
     # 纵深关系，成员并未被无痕写，但池必须在第一道收口）。
     ("A01", "A02", "A03", "A06", "E01", "K05")),
    ("M2 成员写盘点摘闸（guard_overwrite 换 no-op 直通）", "md_cg/consolidate.py",
     ("        protect.guard_overwrite(cg, m, layer=fm.get(\"layer\"),",
      "        (lambda *a, **k: None)(cg, m, layer=fm.get(\"layer\"),"),
     # 机制：闸门变 no-op ⇒ 受保护成员重新直写（A09）、写点接线形态脱焊（E02）；
     # 合法写不受影响（A10 照绿——判别力集中在保护腿）。
     ("A09", "E02")),
    ("M3 单点回缺陷：is_protected_entry 只读 protected 位", "md_cg/protect.py",
     ("    return is_protected(_EntryProbe(e), _ENTRY_PROBE_ID)",
      "    return (isinstance(e, dict) and e.get(\"protected\") is True,\n"
      "            \"显式保护标记\")"),
     # 机制：条目单点退化成位判 ⇒ 层保护/按分保护两腿断（A01/A02/A03/A06）、
     # 与权威 is_protected 逐节点失配（K01）、hint 高分认保护的边界翻转（K03）、
     # skipped_protected 读数归零（K05）、单点转发形态脱焊（E03）。
     ("A01", "A02", "A03", "A06", "E03", "K01", "K03", "K05")),
)


def _mirror_build():
    dst = tempfile.mkdtemp(prefix="iss432_mut_")
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
    env.pop("MDCG_ROOT", None)
    pr = subprocess.run([sys.executable, "-X", "utf8", "-m",
                         "md_cg.test_issue432_induce_protected_pool"],
                        capture_output=True, text=True, encoding="utf-8",
                        errors="replace", cwd=tree, env=env, timeout=1800)
    out = (pr.stdout or "") + (pr.stderr or "")
    reds = [ln.split("FAIL ", 1)[1].strip()
            for ln in out.splitlines() if ln.strip().startswith("FAIL ")]
    return pr.returncode, reds, out


def _mutate():
    print("!! 定点变异自证：逐条把判据改回改动前形态 / 摘闸 / 单点退化，守卫必须按指定项转红")
    tree = _mirror_build()
    try:
        rc, reds, out = _run_in(tree)
        print("  未变异镜像基线：rc=%d 红项=%d（必须 rc=0 且 0 红）" % (rc, len(reds)))
        if rc != 0 or reds:
            print(chr(10).join(out.splitlines()[-25:]))
        bad = []
        for desc, rel, (old, new), exp in _MUTATIONS:
            p = os.path.join(tree, rel)
            t = open(p, encoding="utf-8", newline="").read()
            if t.count(old) != 1:
                bad.append("%s —— 锚点在 %s 里命中 %d 次" % (desc, rel, t.count(old)))
                print("  ANCHOR-MISS " + desc)
                continue
            bak = t
            open(p, "w", encoding="utf-8", newline="").write(t.replace(old, new, 1))
            for root_, dd, ff in os.walk(tree):
                if os.path.basename(root_) == "__pycache__":
                    shutil.rmtree(root_, ignore_errors=True)
            rc2, reds2, out2 = _run_in(tree)
            open(p, "w", encoding="utf-8", newline="").write(bak)
            hit = sorted({r.split(" ")[0] for r in reds2})
            if rc2 != 0 and hit == sorted(exp):
                print("  OK   %s  红项=%d 指定命中=%s" % (desc, len(reds2), hit))
            else:
                bad.append(desc)
                print("  MISMATCH %s  实际红项=%s 期望=%s rc=%d"
                      % (desc, hit, sorted(exp), rc2))
                for r in reds2[:10]:
                    print("        FAIL " + r)
        print("定点变异自证：%s（%d 条不合格）"
              % ("PASS" if not bad else "FAIL", len(bad)))
        for b in bad:
            print("  不合格：" + b)
        return len(bad)
    finally:
        shutil.rmtree(tree, ignore_errors=True)


def main():
    _bad = _mutate() if "--mutate" in sys.argv else 0
    return 1 if (FAILS or _bad) else 0


if __name__ == "__main__":
    sys.exit(main())
