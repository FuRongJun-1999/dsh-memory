# -*- coding: utf-8 -*-
# 功能名：k 预算分配守卫（H10 修订）——负覆盖提示条**永不得挤占真实命中**
# 生效条件：md_cg/mdcg.py 的 `_emit` 里「真实命中数 n_real = min(max(0,k), scored 中
#           s>0 的条数) → 提示条数 = min(NEG_COVERAGE_MAX, max(0, k − n_real)) →
#           主结果 = scored[:max(0, k − 提示数)]」三者按此口径配对时成立；
#           沙箱条件：所有库根一律 tempfile.mkdtemp，绝不触在役库/在役服务。
# 子功能：
#   A 缺陷复现与修复（(a) 判据）：负覆盖在场且 k=1/2/3 时，最高分真实命中必须出现在
#     返回里且在首位（改前 k ≤ 提示数 → 主结果配额被算成 0，一条真命中都不返回——
#      把「读不到」读成「不存在」）
#   B k 预算（(b)(c) 判据）：真命中已用满 k（真实命中数 ≥ k）时不发提示条；
#     任何 k（含 0/1 边界）下 len(返回条目) ≤ k（H10② 的成果不回退）
#   C 信号不丢（(d) 判据）：无真实命中时提示条仍出现并填满 min(NEG_COVERAGE_MAX, k)；
#     提示条为 0 时该信号仍可从**既有**统计/审计面读到（meta["covered_neg"] 恒为
#     全部被覆盖路径、门控开启时 stat["gates"]["s5"]["neg"] 同值）——不新增协议字段
#   D 单点与既有属性：`_neg_tail`/`_primary_slots` 在 mdcg.py 内各恰一处调用（都在
#     `_emit` 内）、生产路径 MdCGOS 不覆写 `_emit`（route/read/search 三处 result 面
#     共用这一处）、提示三项既有属性（哨兵分 0.0 / 尾部 / 独立字段 negative_coverage）
#     与 NEG_COVERAGE_MAX=3 一字不动
# 执行：python -X utf8 -m md_cg.test_neg_coverage_budget
#       python -X utf8 -m md_cg.test_neg_coverage_budget --mutate=all
#       python -X utf8 -m md_cg.test_neg_coverage_budget --mutate=neg-budget-revert
# 验证方式：本文件自跑（自带断言计数与退出码 rc=0/1）；`--mutate` = **定点变异自证**
#           ——把待验修复**在临时副本的源码文本上**逐点抽回改前语义（在役工作树只读、
#           字节不变，变异结束用 md5 复核「复原后哈希一致」），再以子进程实跑本守卫：
#           必须 rc=1 且打红**预期断言集合**；随后在役树原样复跑必须转绿（无残余）。
# 不适用条件：情感交互｜闲聊｜纯查询无改动；负覆盖条目在 MCP 结果面的**渲染**
#           （`_node_view` 只透 id/path/frontmatter/content）不属本文件面内；
#           search_rrf 路径不产负覆盖尾条目（无 negative_coverage 面），不在本文件面内。
import hashlib
import os
import re
import shutil
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from md_cg import mdcg as _mdcg                     # noqa: E402
from md_cg.mdcg import MdCG                         # noqa: E402
from md_cg.mdcos import MdCGOS                      # noqa: E402

PASS = 0
FAIL = 0
FAILS = []
_RUN = [0]
_SANDBOX = tempfile.mkdtemp(prefix="mdcg_neg_budget_")
_HERE = os.path.dirname(os.path.abspath(__file__))
_REPO = os.path.dirname(_HERE)

#: 复现用查询（题面现场：真实命中 2 条 + 负覆盖 3 条）
Q = "理论推理层 激活协议 四条规则 状态暴露 边界声明"
REAL_A = ("# 功能名：理论推理层激活协议\n"
          "# 生效条件：理论推理层\n# 子功能：四条规则 状态暴露\n"
          "# 执行：按四条规则暴露状态\n# 验证方式：test\n"
          "# 不适用条件：无\n\n"
          "理论推理层 激活协议 四条规则 状态暴露 边界声明\n")
REAL_B = ("# 功能名：推理层边界声明\n"
          "# 生效条件：理论推理层\n# 子功能：激活协议 状态暴露\n"
          "# 执行：核对边界声明\n# 验证方式：test\n"
          "# 不适用条件：无\n\n"
          "理论推理层 激活协议 四条规则 状态暴露\n")
#: 与本查询无词面/索引键交集的样本（T3 全量兜底里 score == 0 的候选）
FILLER = "# 功能名：无关样本%d\n# 正文：蜂群调度 节点 %d\n"


def check(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print("  OK   %s" % name)
    else:
        FAIL += 1
        FAILS.append(name)
        print("  FAIL %s  %s" % (name, detail))


def check_exc(name, fn):
    """fn() → (cond, detail)。抛异常记为该断言失败（变异运行不得因崩溃丢红项读数）。"""
    try:
        cond, detail = fn()
    except Exception as e:                        # noqa: BLE001
        cond, detail = False, "EXC %s: %s" % (type(e).__name__, e)
    check(name, cond, detail)


def _mk(tag, cls=MdCG):
    return cls(os.path.join(_SANDBOX, "lib_%s_r%d" % (tag, _RUN[0])), autoflush=0)


def _neg_tail(res):
    return [r for r in res if (r[2] or {}).get("negative_coverage")]


def _prim(res):
    return [r for r in res if not (r[2] or {}).get("negative_coverage")]


def _repro_lib(tag):
    """题面复现现场：2 条真实命中（含查询词）+ 3 条负覆盖（含查询词）。"""
    cg = _mk(tag)
    cg.add("real_a", REAL_A, layer="knowledge", verification_basis="test")
    cg.add("real_b", REAL_B, layer="knowledge", verification_basis="test")
    for j in range(3):
        cg.add("rej_%d" % j,
               "# 假设：%s 第 %d 号\n# 否决原因：与既有验证结论冲突\n" % (Q, j),
               layer="rejected", verification_basis="test")
    cg.flush()
    return cg


def _empty_lib(tag, n=8):
    """T3 全量兜底现场：正层全是**零分**候选（词面与查询无交集）+ 3 条负覆盖。

    `len(scored) = n ≥ k` 而真实命中数 = 0——「提示填满 min(3,k)」与「len ≤ k」
    两条判据的判别力都在这个形态上（T2 LIKE 阶段无命中 → 走 T3 全量兜底）。
    """
    cg = _mk(tag)
    for i in range(n):
        cg.add("mem_%03d" % i, FILLER % (i, i), layer="knowledge")
    for j in range(3):
        cg.add("rej_%d" % j,
               "# 假设：%s 第 %d 号\n# 否决原因：与既有验证结论冲突\n" % (Q, j),
               layer="rejected", verification_basis="test")
    cg.flush()
    return cg


# ------------------------------------------------------------------ A 组（(a)）
def group_a():
    print("\n[A] 缺陷复现与修复：k=1/2/3 时最高分真实命中必在返回里（(a) 判据）")
    cg = _repro_lib("repro")
    # 对照基准：走**无负覆盖**的路径（include_neg=False → 不产提示条）取最高分真命中
    ref, _mr = cg.search(Q, k=20, include_neg=False, record=False)
    top_real = ref[0][0].get("id") if ref else None
    real_ids = [r[0].get("id") for r in ref]
    res8, meta8 = cg.search(Q, k=8, record=False)
    check_exc("A1 前置复现：库内 ≥2 条真命中且负覆盖恰 3 条（题面现场）",
              lambda: (len(real_ids) >= 2 and top_real
                       and len(meta8.get("covered_neg") or []) == 3,
                       "real=%s top=%s covered_neg=%s"
                       % (real_ids, top_real, meta8.get("covered_neg"))))
    rows = {}
    for k in (1, 2, 3):
        rows[k] = cg.search(Q, k=k, record=False)
    check_exc("A2 (a) k=1/2/3 时最高分真实命中必出现在返回里**且在首位**"
              "（改前 k ≤ 提示数 → 主结果配额 0：k=2/3 全是 rej_*，读成「库里没有」）",
              lambda: (all(rows[k][0] and rows[k][0][0][0].get("id") == top_real
                           for k in (1, 2, 3)),
                       "; ".join("k=%d → %s" % (k, [x[0].get("id")
                                                    for x in rows[k][0]])
                                 for k in (1, 2, 3))))
    check_exc("A2b (a) k=2/3 时**全部**真命中都在返回里（真命中数 2 ≤ k）",
              lambda: (all(set(real_ids) <= {x[0].get("id") for x in rows[k][0]}
                           for k in (2, 3)),
                       "; ".join("k=%d → %s" % (k, [x[0].get("id")
                                                    for x in rows[k][0]])
                                 for k in (2, 3))))
    cg.close()


# ------------------------------------------------------------------ B 组（(b)(c)）
def group_b():
    print("\n[B] k 预算：(b) 真命中用满 k 时不发提示、(c) 任何 k 下 len ≤ k")
    cg = _repro_lib("budget")
    ref, _mr = cg.search(Q, k=20, include_neg=False, record=False)
    n_real = len(ref)                       # 该库真实命中数（题面：2）
    check_exc("B0 前置：真实命中数 2（< k 时才有尾条目，= k 时提示必须让位）",
              lambda: (n_real == 2, "n_real=%d" % n_real))

    def _no_tail_when_full():
        detail = []
        ok = True
        for k in range(1, n_real + 1):
            r, m = cg.search(Q, k=k, record=False)
            nt = len(_neg_tail(r))
            b = m.get("k_budget")
            detail.append("k=%d len=%d neg=%d k_budget=%s" % (k, len(r), nt, b))
            if nt != 0 or b is not None:
                ok = False
            if len(_prim(r)) != min(k, n_real):
                ok = False
        return ok, "; ".join(detail)

    check_exc("B1 (b) 真实命中数 ≥ k ⇒ 不发提示条（k=1/2 尾条为 0、"
              "meta.k_budget 不落键——「产生信息才落键」），且主结果恰 min(k, 真命中数) 条",
              _no_tail_when_full)

    def _tail_budget():
        detail = []
        ok = True
        # 真命中用满 k 后，余下的位子才给提示，且不超过 NEG_COVERAGE_MAX
        for k in range(n_real, 9):
            r, m = cg.search(Q, k=k, record=False)
            nt = len(_neg_tail(r))
            want = min(_mdcg.NEG_COVERAGE_MAX, max(0, k - n_real))
            detail.append("k=%d neg=%d want=%d" % (k, nt, want))
            if nt != want:
                ok = False
        return ok, "; ".join(detail)

    check_exc("B2 k ≥ 真命中数时提示条数 ＝ min(NEG_COVERAGE_MAX, k − 真命中数)"
              "（k=2 → 0、k=3 → 1、k=5 → 3）", _tail_budget)

    def _le_k():
        detail = []
        ok = True
        for k in range(0, 9):
            r, _m = cg.search(Q, k=k, record=False)
            detail.append("k=%d len=%d" % (k, len(r)))
            if len(r) > k:
                ok = False
        return ok, "; ".join(detail)

    check_exc("B3 (c) 复现库：任何 k（含 k=0/1 边界）下 len(返回条目) ≤ k"
              "（H10② 消除 k+3 超发的成果不回退）", _le_k)

    def _le_k_scan():
        e = _empty_lib("le_k")
        detail = []
        ok = True
        for k in range(0, 9):
            r, _m = e.search(Q, k=k, record=False)
            detail.append("k=%d len=%d" % (k, len(r)))
            if len(r) > k:
                ok = False
        e.close()
        return ok, "; ".join(detail)

    check_exc("B3b (c) T3 全量兜底现场（len(scored)=8 ≥ k 而真命中 0）："
              "任何 k 下 len ≤ k（提示只能填 k 以内的位子）", _le_k_scan)
    cg.close()


# ------------------------------------------------------------------ C 组（(d)）
def group_c():
    print("\n[C] 信号不丢：(d) 无真命中时提示仍出现；提示为 0 时信号仍在统计/审计面")
    e = _empty_lib("d_signal")

    def _fill():
        detail = []
        ok = True
        for k in (1, 2, 3, 5):
            r, m = e.search(Q, k=k, record=False)
            nt = len(_neg_tail(r))
            want = min(_mdcg.NEG_COVERAGE_MAX, k)
            detail.append("k=%d neg=%d want=%d len=%d" % (k, nt, want, len(r)))
            # 提示条恰填 min(3,k)；且主结果里**没有**真命中（本库真命中数为 0，
            # 主结果里的零分候选（若有）不冒充命中——按分数如实为 0.0）
            if nt != want or any(x[1] > 0 for x in _prim(r)):
                ok = False
            if nt and (m.get("k_budget") or {}).get("neg_tail") != nt:
                ok = False
        return ok, "; ".join(detail)

    check_exc("C1 (d) 无真实命中 ⇒ 提示条填满 min(NEG_COVERAGE_MAX, k) 条"
              "（k=1/2/3 → 1/2/3；k=5 → 3，不超发）", _fill)

    def _tail_shape():
        r, _m = e.search(Q, k=3, record=False)
        nt = _neg_tail(r)
        # 位置＝尾部：提示全在末尾（最后一条是提示，且前面没有任何提示）
        tail_only = bool(r) and bool((r[-1][2] or {}).get("negative_coverage")) \
            and _neg_tail(r[:len(r) - len(nt)]) == []
        # 只钉三项属性（哨兵分/位置/独立字段）；总数由 B 组钉（避免同一条口径
        # 在两个断言里重复，使定点变异的红项集合不可分辨）
        return (len(nt) == 3
                and all(x[1] == _mdcg.NEG_COVERAGE_SCORE == 0.0 for x in nt)
                and all((x[0].get("negative_coverage") is True
                         and (x[2] or {}).get("negative_coverage") is True
                         and x[0].get("neg_layer") in ("rejected", "unresolved"))
                        for x in nt)
                and tail_only,
                "nt=%d r=%d scores=%s" % (len(nt), len(r), [x[1] for x in nt]))

    check_exc("C2 提示三项既有属性不动：哨兵分 0.0 / 位置在尾部 / 负性走独立字段"
              "negative_coverage（+ neg_layer）", _tail_shape)
    e.close()

    cg = _repro_lib("signal_audit")
    r2, m2 = cg.search(Q, k=2, record=False)          # 真命中用满 k → 零提示条
    check_exc("C3 提示条为 0 时负覆盖信号仍从**既有**统计面读到："
              "meta.covered_neg 恒为全部被覆盖路径（无需新协议字段）",
              lambda: (not _neg_tail(r2)
                       and len(m2.get("covered_neg") or []) == 3,
                       "neg=%d covered_neg=%s"
                       % (len(_neg_tail(r2)), m2.get("covered_neg"))))
    os.environ["MDCG_RETRIEVAL_PIPELINE"] = "1"
    os.environ["MDCG_GATE_S5_NEG"] = "1"
    try:
        _r3, m3 = cg.search(Q, k=2, record=False)
        s5 = (m3.get("gates") or {}).get("s5") or {}
    finally:
        os.environ.pop("MDCG_RETRIEVAL_PIPELINE", None)
        os.environ.pop("MDCG_GATE_S5_NEG", None)

    def _s5():
        return (int(s5.get("neg") or 0) == 3,
                "gates.s5=%s" % s5)

    check_exc("C4 门控开启时同一计数在既有审计面可达（gates.s5.neg == 覆盖数 3）"
              "——两处既有面皆非本次新增", _s5)
    cg.close()


# ------------------------------------------------------------------ D 组（单点）
def group_d():
    print("\n[D] 单点与调用方：三处 result 面共用 `_emit` 内的这一处裁决")
    src = open(os.path.join(_HERE, "mdcg.py"), encoding="utf-8").read()
    check_exc("D1 `_neg_tail`/`_primary_slots` 在 mdcg.py 内各**恰 1 处**调用"
              "（都在 `_emit` 内）——k 预算的裁决单点",
              lambda: (src.count("self._neg_tail(") == 1
                       and src.count("self._primary_slots(") == 1,
                       "neg_tail=%d primary_slots=%d"
                       % (src.count("self._neg_tail("),
                          src.count("self._primary_slots("))))
    check_exc("D2 生产路径（MdCGOS）不覆写 `_emit`/`_neg_tail`/`_primary_slots`"
              "——基类与生产路径同口径，非各写一份",
              lambda: (not any(n in MdCGOS.__dict__
                               for n in ("_emit", "_neg_tail", "_primary_slots")),
                       "os_dict=%s" % [n for n in ("_emit", "_neg_tail",
                                                   "_primary_slots")
                                       if n in MdCGOS.__dict__]))

    def _mcp_ops():
        p = os.path.join(_HERE, "mcp_server.py")
        s = open(p, encoding="utf-8").read()
        out = {}
        for op in ("route", "read"):
            i = s.find('if op == "%s":' % op)
            if i < 0:
                out[op] = None
                continue
            j = s.find('\n    if op == "', i + 1)
            seg = s[i:j if j > 0 else len(s)]
            out[op] = ("cg.search(" in seg)
        return (out.get("route") is True and out.get("read") is True, str(out))

    check_exc("D3 MCP 的 route/read 两处 result 面都经 `cg.search`（+ MCP search 同库层出口）"
              "——故本次修复三处同时受益", _mcp_ops)


_GROUPS = (group_a, group_b, group_c, group_d)


def _run_all():
    global PASS, FAIL, FAILS
    _RUN[0] += 1
    PASS, FAIL, FAILS = 0, 0, []
    for g in _GROUPS:
        g()
    return PASS, list(FAILS)


# ------------------------------------------------------------- 定点变异（自证）
#: 每项 = (文件, 正则, 替换, 期望转红的断言 id, 说明)。正则在**临时副本**的源码文本上
#: 命中恰好 1 处（命中数 ≠1 视为变异未生效，直接判红），把该处修复抽回改前语义。
_MUTATIONS = {
    "neg-budget-revert": (
        "mdcg.py",
        r"(?m)^\s*_neg_tail = self\._neg_tail\(neg_coverage, max\(0, int\(k\) - _n_real\)\)\s*$",
        "        _neg_tail = self._neg_tail(neg_coverage, k)",
        ["A2", "A2b", "B1", "B2", "C3"],
        "提示条数上界退回 min(NEG_COVERAGE_MAX, k)（改前：提示先占满 k，真命中归零）"),
    "primary-slots-no-budget": (
        "mdcg.py",
        r"(?m)^\s*return max\(0, int\(k\) - int\(n_tail\)\)\s*$",
        "        return max(0, int(k))",
        ["B3b"],
        "主结果退回 scored[:k]（尾巴在 k 之外 → len > k）"),
    "neg-tail-never": (
        "mdcg.py",
        r"(?m)^\s*_n_real = min\(max\(0, int\(k\)\), sum\(1 for _, s in scored if s > 0\)\)\s*$",
        "        _n_real = max(0, int(k))",
        ["B2", "C1", "C2"],
        "真实命中数恒取 k（提示条恒不出现——负覆盖信号静默失传）"),
}

_ASSERT_RE = re.compile(r"^\s*(?:\[FAIL\]|FAIL)\s+(\S+)")


def _reds(stdout):
    out = []
    for line in (stdout or "").splitlines():
        m = _ASSERT_RE.match(line)
        if m:
            out.append(m.group(1))
    return out


def _md5(path):
    with open(path, "rb") as f:
        return hashlib.md5(f.read()).hexdigest()


def _run_guard(cwd):
    env = dict(os.environ)
    env["PYTHONUTF8"] = "1"
    env["PYTHONPATH"] = cwd
    return subprocess.run(
        [sys.executable, "-X", "utf8", "-m", "md_cg.test_neg_coverage_budget"],
        cwd=cwd, env=env, capture_output=True, text=True,
        encoding="utf-8", errors="replace")


def _mutate_mode(which):
    names = list(_MUTATIONS) if which == "all" else [which]
    for n in names:
        if n not in _MUTATIONS:
            print("未知变异 %r（可选：%s）" % (n, sorted(_MUTATIONS)))
            return 2
    files = sorted({_MUTATIONS[n][0] for n in names})
    before = {f: _md5(os.path.join(_HERE, f)) for f in files}
    rc = 0
    print("\n=== 定点变异自证（在**临时副本**源码上抽掉修复 → 本守卫必红 → "
          "在役树复跑必绿）===")
    print("  基准在役树：%s" % ", ".join("%s=%s" % (f, before[f]) for f in files))
    for name in names:
        fname, pat, sub, want, note = _MUTATIONS[name]
        tmp = tempfile.mkdtemp(prefix="neg_budget_mut_")
        try:
            shutil.copytree(_HERE, os.path.join(tmp, "md_cg"),
                            ignore=shutil.ignore_patterns("__pycache__"))
            path = os.path.join(tmp, "md_cg", fname)
            with open(path, encoding="utf-8") as f:
                src = f.read()
            hits = len(re.findall(pat, src))
            if hits != 1:
                print("  FAIL 变异 %s 未生效：源码命中 %d 处（期望 1）" % (name, hits))
                rc = 1
                continue
            with open(path, "w", encoding="utf-8", newline="") as f:
                f.write(re.sub(pat, sub, src, count=1))
            r = _run_guard(tmp)
            reds = _reds(r.stdout)
            missed = [w for w in want if w not in reds]
            extra = [x for x in reds if x not in want]
            summary = [l for l in (r.stdout or "").splitlines()
                       if l.startswith("====")]
            print("  [%s] %s" % (name, note))
            print("     基准副本 %s（抽掉修复的那份）" % path)
            print("     rc=%d 红项 %d 个：%s" % (r.returncode, len(reds),
                                                " ".join(reds) or "（无）"))
            print("     %s" % (summary[-1] if summary else "（无汇总行）"))
            if r.returncode != 1 or not reds:
                print("  FAIL 变异 %s 未打红（rc=%d，红项 0）——守卫对该修复无判别力"
                      % (name, r.returncode))
                print("     stderr: %s" % (r.stderr or "")[-400:])
                rc = 1
            elif missed or extra:
                print("  FAIL 变异 %s 命中集合不符：未打中 %s；连带红项 %s"
                      % (name, missed or "（无）", extra or "（无）"))
                rc = 1
            else:
                print("  ok   变异 %s 恰好打中预期断言 %d 项、零连带" % (name, len(want)))
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
    after = {f: _md5(os.path.join(_HERE, f)) for f in files}
    if before != after:
        print("  FAIL 在役源码 md5 与基准不同——本驱动不写在役树，"
              "若确有差异即为**并发改动**落在同一工作树。")
        rc = 1
    else:
        print("  ok   复原核对：变异只在临时副本内（已 rmtree），在役树字节不变、"
              "哈希一致：%s" % ", ".join("%s=%s" % (f, after[f]) for f in files))
    r0 = _run_guard(_REPO)
    reds0 = _reds(r0.stdout)
    tail0 = [l for l in (r0.stdout or "").splitlines() if l.startswith("====")]
    print("  [恢复] 在役树原样复跑：rc=%d 红项=%d  %s"
          % (r0.returncode, len(reds0), tail0[-1] if tail0 else ""))
    if r0.returncode != 0 or reds0:
        print("  FAIL 恢复后未转绿，残余红项：%s" % (reds0 or "rc≠0"))
        rc = 1
    else:
        print("  ok   无残余红项")
    return rc


def main(argv):
    which = None
    for a in argv:
        if a.startswith("--mutate"):
            which = a.split("=", 1)[1] if "=" in a else "all"
    if which is not None:
        return _mutate_mode(which)
    ok, bad = _run_all()
    print("\n==== k 预算分配守卫（H10 修订）：%d 通过 / %d 失败%s ===="
          % (ok, len(bad), ("：" + "; ".join(bad)) if bad else ""))
    return 1 if bad else 0


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    try:
        _rc = main(sys.argv[1:])
    finally:
        shutil.rmtree(_SANDBOX, ignore_errors=True)
    sys.exit(_rc)
