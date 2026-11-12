#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# 功能名：readcache 装配面下沉到基类 MdCG（issue #370：基类直接使用者全走无缓存路径，4.9×）
# 生效条件：python -X utf8 -m md_cg.test_issue370_readcache_assembly [--mutate]；被测面＝md_cg/mdcg.py 的 MdCG.__init__ 装配调用、md_cg/mdcos.py 的同入口调用、md_cg/readcache.py 的 install_default/enabled/install 契约（含 AST 源码面）
# 子功能：A 组＝基类装配在位 + 查询读数改善（结构性命中计数 + 相对判据）；K 组＝非恒真对照（env 关闭不装配、退出阀真关、缓存不改结果、写后不陈旧、外部直改+rebuild 可见、装配入口幂等）；E 组＝源码面装配单点（定义恰一处 / 调用点枚举 / env 门在入口内 / 调用晚于 _dirty 建立）；M 组＝--mutate 定点变异（还原方向 / 过度装配方向 / 单点分裂方向 / 幂等缺口方向）
# 执行：--mutate 时在镜像树里逐条改源，守卫必须按指定项转红（多红/少红皆不合格）
# 验证方式：全部 PASS 即通过（退出码 0）；--mutate 下每条变异的红项集合须与预期逐项相符，锚点未命中即 fail-closed（打印 ANCHOR-MISS 并计入不合格）
# 不适用条件：① 性能断言**不写绝对 ms**（同一份码本机 33.1→4.8 ms/查询、报告机 30.6/6.2，比值 9.9× vs 4.9×）——绝对读数只打印不作门；门的只有结构性判据（装配态 + nodefile.loads 命中计数）与相对判据（基类/MdCGOS 同库同查询耗时比值区间）；
#   ② 内存代价**不设门、只登记读数**（Lead 裁定要求量化）：读缓存无淘汰面——五类缓存 2000 节点深度体量 13.6MB（6.97 KB/节点，其中 _norm_bigrams_cache 3.63、_read_cache 2.54），进程 RSS 增量 8.3~16.3 KB/节点（跨进程波动，对照组 ≈0）；5000 节点 RSS 增量 74.3MB（15.2 KB/节点）。大库（≥10 万节点，外推 RSS ~1.5GB）或内存受限的长跑 CLI 应显式 MDCG_READ_CACHE=0（opt-out 退出阀）——这是 #31 已在生产检索入口接受的同一取舍，本次只是对齐到基类，不新增量级；
#   ③ 跨进程一致性边界**按实例级缓存语义**判为无夹具受影响：缓存挂在实例上，md_cg/ 下「同实例先读 → 另一进程改写 → 同实例再读同节点」的夹具只 test_bm25.py::test_rebuild_and_other_process_reload 一例，且它用 MdCGSecure（修复前就已装配），失效走 rebuild_index/compact_index（broad_gen 推进）与 _maybe_reload_index（签名变化 → readcache.clear）——K6 用**基类实例**同款钉住；「新建第二实例去读」不受影响（各持快照）；
#   ④ 不判 MdCGSecure 的密钥/锁定面（readcache.clear 的既有接线另有守卫）；⑤ 不判「外部直改 .md 后不 rebuild/reload」——那是 readcache 既有的诚实边界（进程内一致性不保证），非本次范围。
"""#370 守卫：readcache 装配点覆盖基类（装配面单点）。

病象（修前，A 组逐条复现）：装配点只有 `MdCGOS.__init__` ⇒ 以 `MdCG(root)`
直接打开的库（backfill_bigdomain / backfill_bucket_zh / build_postings /
migrate 等全库扫描 CLI）每次查询对每个候选 open+read+parse。本机实测
（500 节点合成库、20 次查询）：`MdCG` 33.1 ms/查询、`nodefile.loads` 500 次/
查询、无 `_read_cache`；`MdCGOS` 3.3 ms/查询、0 次、已装配（报告机 30.6 vs
6.2 ms，4.9×）。

修法（Lead 裁定 2026-10-16）：装配**下沉到基类**，且装配面必须是**单点**——
`readcache.install_default(cg)`（env 门 + 幂等）是自动装配的唯一入口，
`MdCG.__init__` 末尾（`_dirty` 建立之后）与 `MdCGOS.__init__` 各调一次，
`install()` 只被该入口与显式重装的调用方调用（语义未变）。落点理由：失效
判据（`_DirtyDict` 脏集）与组装面（`_read_status`/`_read`/四个派生钩子）
**都在基类**，装配点与它们同层；不对称只有历史原因，无正确性理由。

本守卫的判别力来自非恒真对照，而不是「修完就绿」：
  K1/K2 —— `MDCG_READ_CACHE=0` 必须**不**装配且二次检索仍逐节点重解析
            （防「无条件装配、忽略 env 开关」的过度装配方向）；
  K3    —— 开/关同库同 query 结果 id 序逐位一致（缓存只改速度不改结果）；
  K4/K5 —— 写后不陈旧（新增节点 + 覆写既有节点）；
  K6    —— 外部直改 .md + rebuild_index 后基类实例可见新正文；
  K7    —— 装配入口幂等：二次调用返回 False 且**不换**缓存对象；
  E1-E4 —— 源码面：`install_default` 定义恰一处、自动装配调用点恰两处且
            无旁路 `install()`、env 门在入口内、调用晚于 `_dirty` 建立。
"""
from __future__ import annotations

import ast
import os
import shutil
import subprocess
import sys
import tempfile
import time

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO not in sys.path:
    sys.path.insert(0, _REPO)

from md_cg import nodefile                        # noqa: E402
from md_cg import readcache as _RC                # noqa: E402
from md_cg.mdcg import MdCG                       # noqa: E402
from md_cg.mdcos import MdCGOS                    # noqa: E402

POOL = 240            # 合成库节点数（够出读数、构造成本可控）
QUERIES = 20          # 每组计时/计数的查询次数
REPS = 3              # 计时重复数（取中位，抗单次尖峰）
Q = "装配探针"
RATIO_LO, RATIO_HI = 0.25, 3.0   # 基类/MdCGOS 同库同查询耗时比值区间（修前本机 9.9×、报告机 4.9×；修后 ~1.4×）

PASSED, FAILS = [], []


def _check(name, cond, detail=""):
    if cond:
        print("  PASS " + name)
        PASSED.append(name)
    else:
        print("  FAIL " + name + "  " + str(detail)[:240])
        FAILS.append(name)


def _note(text):
    print("  NOTE " + text)


def _envi(**kw):
    """env 上下文：None 值=pop。"""
    class _C:
        def __enter__(self):
            self.old = {k: os.environ.get(k) for k in kw}
            for k, v in kw.items():
                if v is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = v

        def __exit__(self, *a):
            for k, v in self.old.items():
                if v is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = v
            return False
    return _C()


def _count_loads(fn):
    """打桩 nodefile.loads 计数（节点文件解析的唯一入口，_read_status 内调用）。"""
    box = {"n": 0}
    real = nodefile.loads

    def _spy(*a, **kw):
        box["n"] += 1
        return real(*a, **kw)

    nodefile.loads = _spy
    try:
        return fn(), box["n"]
    finally:
        nodefile.loads = real


def _build(root, n=POOL):
    cg = MdCG(root)
    for i in range(n):
        cg.add("asm_%04d" % i,
               "# 功能名：装配样本 %d\n# 正文：%s 关键词%d\n" % (i, Q, i % 17),
               layer="knowledge")
    cg.flush()
    cg.close()
    return root


def _time_queries(cg, n=QUERIES):
    cg.search(Q, k=10, record=False)                  # 预热（首查装载）
    t0 = time.perf_counter()
    meta = None
    for _ in range(n):
        _res, meta = cg.search(Q, k=10, record=False)
    return (time.perf_counter() - t0) / n * 1000.0, meta


def _ids(cg, q=Q):
    res, _meta = cg.search(q, k=50, record=False)
    return [r[0].get("id") for r in res]


# ==================================================== A 组：基类装配在位 + 读数
def group_a(tmp):
    print("== A 组：基类装配在位 + 查询读数改善（结构性 + 相对判据）==")
    root = os.path.join(tmp, "a")
    with _envi(MDCG_READ_CACHE=None):
        _build(root)
        cg = MdCG(root)
        cg.search(Q, k=10, record=False)
        _check("A1 基类构造即装配读缓存（hasattr _read_cache）",
               hasattr(cg, "_read_cache"),
               "keys=%s" % sorted(vars(cg).keys())[:12])
        _check("A1b 三态读面被包装（_read_status_uncached 在位）",
               hasattr(cg, "_read_status_uncached"))
        _res, n1 = _count_loads(lambda: cg.search("关键词3", k=10, record=False))
        _check("A2a 冷查装载 ≤ 池节点数（O(装载一次)）", n1 <= POOL,
               "loads=%d pool=%d" % (n1, POOL))
        _res, n2 = _count_loads(lambda: cg.search("关键词3", k=10, record=False))
        _check("A2b 二次检索零重解析（loads==0，结构化命中计数）", n2 == 0,
               "loads=%d" % n2)
        total = n1 + n2
        for _ in range(3):
            _res, n3 = _count_loads(lambda: cg.search(Q, k=10, record=False))
            total += n3
        _check("A3 5 次检索累计装载 ≤ 池节点数（旧形态为 5×池）", total <= POOL,
               "total=%d pool=%d" % (total, POOL))
        base_ms = []
        for _ in range(REPS):
            ms, meta_b = _time_queries(cg)
            base_ms.append(ms)
        base_ms.sort()
        ms_base = base_ms[len(base_ms) // 2]
        scan_b = meta_b.get("scanned")
        cg.close()

        cg2 = MdCGOS(root)
        os_ms = []
        for _ in range(REPS):
            ms, _meta_o = _time_queries(cg2)
            os_ms.append(ms)
        os_ms.sort()
        ms_os = os_ms[len(os_ms) // 2]
        ratio = ms_base / ms_os if ms_os else float("inf")
        _note("读数（只登记不作门）：MdCG 基类 %.1f ms/查询  scanned=%s  cache=%s | "
              "MdCGOS %.1f ms/查询  cache=%s | 比值 %.2fx"
              % (ms_base, scan_b, hasattr(cg, "_read_cache"), ms_os,
                 hasattr(cg2, "_read_cache"), ratio))
        _check("A4 基类/MdCGOS 同库同查询耗时比值落入区间（相对判据，不写绝对 ms）",
               RATIO_LO <= ratio <= RATIO_HI,
               "ratio=%.2f band=[%s,%s]" % (ratio, RATIO_LO, RATIO_HI))
        ids_base = _ids(cg2)
        cg2.close()
        cg3 = MdCG(root)
        ids_b = _ids(cg3)
        cg3.close()
        _check("A5 基类与 MdCGOS 同库同 query 结果 id 序逐位相同", ids_base == ids_b,
               "base=%s os=%s" % (ids_b[:3], ids_base[:3]))


# ==================================================== K 组：非恒真对照
def group_k(tmp):
    print("== K 组：非恒真对照（env 开关 / 结果一致 / 写后不陈旧 / 幂等）==")
    root = os.path.join(tmp, "k")
    with _envi(MDCG_READ_CACHE=None):
        _build(root)
        cg = MdCG(root)                                   # 开态（同库）
        cg.search(Q, k=10, record=False)
        ids_on = _ids(cg)
        with _envi(MDCG_READ_CACHE="0"):
            off = MdCG(root)                              # 关态：**同一个库**
            _check("K1 MDCG_READ_CACHE=0 → 基类不装配（开关语义不变）",
                   not hasattr(off, "_read_cache"))
            ids_off = _ids(off)
            off.search(Q, k=10, record=False)             # 预热（无缓存）
            _res, n_off = _count_loads(lambda: off.search(Q, k=10, record=False))
            _check("K2 退出阀真关：关态二次检索仍逐节点重解析（loads>0）",
                   n_off > 0, "loads=%d" % n_off)
            off.close()
        _check("K3 缓存不改结果：开/关同库同 query 的 id 序逐位一致",
               ids_on == ids_off, "on=%s off=%s" % (ids_on[:3], ids_off[:3]))

        cg.add("k_new", "# 正文：%s 写后独有标记ZZZ\n" % Q, layer="knowledge")
        cg.flush()
        hit_new = [r[0].get("id") for r in cg.search("写后独有标记ZZZ", k=5,
                                                     record=False)[0]]
        _check("K4 写后不陈旧（新增节点立即可检索）", "k_new" in hit_new,
               "ids=%s" % hit_new[:3])

        nid = ids_on[0]
        cg.add(nid, "# 正文：%s 覆写后独有标记WWW\n" % Q, layer="knowledge",
               override=True)
        cg.flush()
        hit_w = [r[0].get("id") for r in cg.search("覆写后独有标记WWW", k=5,
                                                   record=False)[0]]
        _check("K5 写后不陈旧（覆写既有节点：新正文可见）", nid in hit_w,
               "nid=%s ids=%s" % (nid, hit_w[:3]))

        e = cg.index["nodes"][nid]
        p = cg._node_disk_path(e)
        with open(p, encoding="utf-8") as f:
            fm, _body = nodefile.loads(f.read())
        with open(p, "w", encoding="utf-8") as f:
            f.write(nodefile.dumps(fm, "# 正文：%s 外部直改标记EEE\n" % Q))
        cg.rebuild_index()
        hit_e = [r[0].get("id") for r in cg.search("外部直改标记EEE", k=5,
                                                   record=False)[0]]
        _check("K6 外部直改 .md + rebuild_index → 基类实例可见新正文（非合作写者兜底面在位）",
               nid in hit_e, "nid=%s ids=%s" % (nid, hit_e[:3]))

        saved = getattr(cg, "_read_cache", None)
        again = _RC.install_default(cg)
        _check("K7 装配入口幂等：二次装配返回 False 且不换缓存对象（不丢弃已装条目）",
               again is False and getattr(cg, "_read_cache", None) is saved,
               "ret=%r same=%s" % (again, cg._read_cache is saved))
        cg.close()


# ==================================================== E 组：源码面装配单点
def _md_cg_sources():
    out = []
    d = os.path.join(_REPO, "md_cg")
    for fn in sorted(os.listdir(d)):
        if not fn.endswith(".py") or fn.startswith("test_") or fn.startswith("bench_"):
            continue
        out.append((fn, os.path.join(d, fn)))
    return out


def _ast_of(path):
    with open(path, encoding="utf-8") as f:
        return ast.parse(f.read(), path)


def _call_sites():
    """全仓（md_cg 非测试源）里对 install / install_default 的**调用点**。"""
    sites = {"install_default": [], "install": []}
    for fn, path in _md_cg_sources():
        for node in ast.walk(_ast_of(path)):
            if not isinstance(node, ast.Call):
                continue
            f = node.func
            name = getattr(f, "attr", None) or getattr(f, "id", None)
            if name in sites:
                sites[name].append((fn, node.lineno))
    return sites


def _install_default_defs():
    out = []
    for fn, path in _md_cg_sources():
        for node in ast.walk(_ast_of(path)):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) \
                    and node.name == "install_default":
                out.append((fn, node))
    return out


def group_e(tmp):
    print("== E 组：源码面装配单点（定义唯一 / 调用点枚举 / env 门在入口内）==")
    defs = _install_default_defs()
    _check("E1 install_default 定义全仓恰一处（md_cg 非测试源）",
           len(defs) == 1 and defs[0][0] == "readcache.py",
           "defs=%s" % [(f, n.lineno) for f, n in defs])
    sites = _call_sites()
    id_calls = sorted(sites["install_default"])
    inst_calls = sorted(sites["install"])
    _check("E2a 自动装配调用点恰两处：基类 __init__ + MdCGOS.__init__（唯一入口）",
           [f for f, _ in id_calls] == ["mdcg.py", "mdcos.py"],
           "sites=%s" % id_calls)
    _check("E2b 无旁路：install( 调用点只在 readcache.py 内（装配面单点）",
           [f for f, _ in inst_calls] == ["readcache.py"],
           "install sites=%s" % inst_calls)
    fn_read, node_read = defs[0]
    names = {getattr(n.func, "attr", None) or getattr(n.func, "id", None)
             for n in ast.walk(node_read) if isinstance(n, ast.Call)}
    _check("E3 env 门在唯一入口内（install_default 内调 enabled()，调用点不各写一份）",
           "enabled" in names, "calls=%s" % sorted(x for x in names if x))
    mdcg_path = os.path.join(_REPO, "md_cg", "mdcg.py")
    cls = None
    for node in ast.walk(_ast_of(mdcg_path)):
        if isinstance(node, ast.ClassDef) and node.name == "MdCG":
            cls = node
    init = None
    if cls is not None:
        for node in cls.body:
            if isinstance(node, ast.FunctionDef) and node.name == "__init__":
                init = node
    call_ln = [n.lineno for n in ast.walk(init) if isinstance(n, ast.Call)
               and (getattr(n.func, "attr", None) or getattr(n.func, "id", None))
               == "install_default"] if init else []
    dirty_ln = [n.lineno for n in ast.walk(init)
                if isinstance(n, ast.Assign)
                and any(isinstance(t, ast.Attribute) and t.attr == "_dirty"
                        for t in n.targets)] if init else []
    _check("E4 装配调用晚于 self._dirty 建立（失效判据先于消费面）",
           bool(call_ln) and bool(dirty_ln) and min(call_ln) > max(dirty_ln),
           "install_default@%s _dirty@%s" % (call_ln, dirty_ln))


def _guard_group(tag, fn, tmp):
    """组内异常 fail-closed：异常即红（否则后续断言会被静默跳过 = 假绿）。"""
    try:
        fn(tmp)
    except Exception as exc:                      # noqa: BLE001
        import traceback
        _check("%s0 组内异常（fail-closed：异常即红）" % tag, False,
               "%s: %s" % (type(exc).__name__, exc))
        traceback.print_exc()


def main():
    os.environ.pop("MDCG_READ_CACHE", None)   # 环境清场：A 组默认态前置
    tmp = tempfile.mkdtemp(prefix="iss370_")
    try:
        _guard_group("A", group_a, tmp)
        _guard_group("K", group_k, tmp)
        _guard_group("E", group_e, tmp)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    print("=" * 68)
    print("#370 装配面守卫：%d 通过，%d 失败" % (len(PASSED), len(FAILS)))
    for f in FAILS:
        print("  红项：" + f)
    _bad = _mutate() if "--mutate" in sys.argv else 0
    return 1 if (FAILS or _bad) else 0


# ==================================================== M 组：定点变异自证
_MUTATIONS = (
    ("M1 还原方向：撤掉基类装配调用（#370 修前形态：装配点回到只有 MdCGOS）",
     "md_cg/mdcg.py",
     (("        from . import readcache as _readcache" + chr(10)
       + "        _readcache.install_default(self)",
       "        pass  # M1 撤装配"),),
     ("A1", "A1b", "A2b", "A3", "A4", "K7", "E2a", "E4")),
    ("M2 过度装配方向：install_default 忽略 env 开关（无条件装配）",
     "md_cg/readcache.py",
     (("    if not enabled():" + chr(10) + "        return False",
       "    if False and not enabled():" + chr(10) + "        return False"),),
     ("K1", "K2")),
    ("M3 单点分裂方向：mdcos 侧绕过 install_default 直调 install（装配面两处实现）",
     "md_cg/mdcos.py",
     (("        _rc.install_default(self)", "        _rc.install(self)"),),
     ("E2a", "E2b")),
    ("M4 幂等缺口：install_default 丢掉「已装配不叠加」判据（二次装配换缓存对象）",
     "md_cg/readcache.py",
     (("    if getattr(cg, \"_read_cache\", None) is not None:" + chr(10)
       + "        return False" + chr(10),
       ""),),
     ("K7",)),
)


def _mirror_build():
    """镜像树：**绝不在真实工作树里改源**（写面纪律）。"""
    dst = tempfile.mkdtemp(prefix="iss370_mut_")
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
              "MDCG_EXPORT_ROOT", "MDCG_INGEST_ROOT", "MDCG_READ_CACHE"):
        env.pop(k, None)
    pr = subprocess.run([sys.executable, "-X", "utf8", "-m",
                         "md_cg.test_issue370_readcache_assembly"],
                        capture_output=True, text=True, encoding="utf-8",
                        errors="replace", cwd=tree, env=env, timeout=1800)
    out = (pr.stdout or "") + (pr.stderr or "")
    reds = [ln.split("FAIL ", 1)[1].strip()
            for ln in out.splitlines() if ln.strip().startswith("FAIL ")]
    return pr.returncode, reds, out


def _apply_text(text, rel, pairs):
    """按目标文件**实际行尾**折算锚点后逐条替换；任一锚点命中数 != 1 返回 (None, 原因)。"""
    eol = (chr(13) + chr(10)) if (chr(13) + chr(10)) in text else chr(10)
    for old, new in pairs:
        o = old.replace(chr(10), eol)
        n = new.replace(chr(10), eol)
        if text.count(o) != 1:
            return None, "锚点在 %s 里命中 %d 次" % (rel, text.count(o))
        text = text.replace(o, n, 1)
    return text, ""


def _mutate():
    print("!! 定点变异自证：撤装配／过度装配／单点分裂／幂等缺口，守卫必须按指定项转红")
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
        print("定点变异自证：%s（%d 条不合格）"
              % ("PASS" if not bad else "FAIL", len(bad)))
        for b in bad:
            print("  不合格：" + b)
        return len(bad)
    finally:
        shutil.rmtree(tree, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
