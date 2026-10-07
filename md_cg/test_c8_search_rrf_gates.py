# -*- coding: utf-8 -*-
"""C-8 守卫：RRF 读路径的门控状态**逐路断言**（search / search_rrf / MdCGSecure.search_rrf）。

病灶（C-8 清单；本守卫作者按清单要求独立复现过一次，见 P3 的实测数字）：
  `apply_retrieval_gates`（md_cg/mdcg.py）自称「两份 search 的唯一实现」，但
  `MdCGOS.search_rrf` → `MdCGSecure.search_rrf`（两条生产读路径，均在 mdcos.py）
  **整段不含门控**——meta 连 gates 键都没有、scanned 恒全表。同一开关下两条
  **生产读路径**的候选面分裂：
      cg(op=read, query)           → MdCGSecure.search      → 收敛（S1 实测 38→23）
      cg(op=read, budget_tokens=…) → MdCGSecure.search_rrf  → 恒 38（不收敛）
  既有守卫 `test_retr_gates_prodpath.py` 只覆盖 search 一路（其 P1/P3 皆调
  cg.search）——「只覆盖一路」正是缺口本体：另两路即便完全不过门控也无红灯。

本守卫的判据面（三路 = 三个入口，逐路断言，不靠读码）：
  P1 库面元数据就位：桶 / big_domain / observation_position 确实落盘（否则后续断言无意义）
  P2 默认零变更：总开关未设 → 三路 meta 均无 gates 键；且与「总开关开 + 子门控全关」
     逐位同结果（零变更的另一半：未显式开门的开关保持原语义）
  P3 逐路门控生效：总开关开 → 三路各自 gates 出现、scanned 真实收敛
     （**修前 search_rrf 两路必红**：gates=None、scanned=38）
  P4 三路审计**逐位相同**（同一实现 ⇒ 同一审计块）——即「两条路逐位一致」的可判定形态
  P5 候选面对照（开门 vs 关门，机械可判定）：结果 id 集合逐路比对，
     被门控剔除的组（域外 / 异桶 / 观测位不符）可点名
  P6 结构守卫：三个入口的源码同引共享实现；且门控实现只有一份

运行：
  python -X utf8 -m md_cg.test_c8_search_rrf_gates            # 正向（P1–P6）
  python -X utf8 -m md_cg.test_c8_search_rrf_gates --mutate   # 定点变异自证
  python -X utf8 -m md_cg.test_c8_search_rrf_gates --mutate --list   # 只列变异表

退出码（fail-closed）：
  0 = 全绿；1 = 有断言失败 / 变异未按预期条数转红 / 基线非 0 红；
  2 = **ANCHOR-MISS**（变异锚点在当前源码里找不到唯一命中——实现改了却没同步
  本表，本表就是判据，锚点漂移必须硬失败，不得静默跳过）。

**基线纪律（--mutate）**：变异**不在工作区落盘**——先在系统临时目录建最小镜像树
（`md_cg/` 副本 + `data/policy.json`，只读复制），再对镜像树的源文件做定点文本替换，
每次变异前从工作区重新取原始副本（保证逐次独立）。工作区只读，绝不写入。
变异覆盖的是 C-8 接线点本身（`MdCGOS.search_rrf` 的门控调用、`MdCGSecure` 的委托、
以及共享实现的存在性），故「C-8 回退即红」可被后人一键复跑。
"""
import inspect
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import unicodedata

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from md_cg import routing                                    # noqa: E402
from md_cg.mdcg import MdCG                                  # noqa: E402
from md_cg.mdcos import MdCGSecure, MdCGOS                    # noqa: E402

PASS = 0
FAIL = 0
FAILS = []

#: 库面规模（三组节点 + 一组域内异桶）：A 15 / B 15 / C 3 / D 5 = 38
#: A=域内主桶（S1 保留、S1b 保留）；B=域外异桶（S1 靶）；
#: C=域内主桶但观测位不符（S2 靶）；D=域内异桶（S1b 靶）
QUERY = "记忆 认知 学习"
CTX = {"observation_position": "实验室", "domain": "认知心理"}
A_IDS = {"mem_%03d" % i for i in range(0, 15)}
B_IDS = {"mem_%03d" % i for i in range(15, 30)}
C_IDS = {"mem_%03d" % i for i in range(30, 33)}
D_IDS = {"mem_%03d" % i for i in range(33, 38)}
ALL_IDS = A_IDS | B_IDS | C_IDS | D_IDS
N_ALL = len(ALL_IDS)

#: 影响门控口径的进程级开关（逐条清理，防宿主环境的残留值改变本次实测口径）。
#: MDCG_HOTCACHE 显式置 0：query 结果缓存键（hotcache._ENV_SWITCHES）只认总开关，
#: 不含 S1/S1b/S2/S4 子开关——缓存命中会让「开/关对照」读到上一口径的结果。
GATE_ENV = ("MDCG_RETRIEVAL_PIPELINE", "MDCG_GATE_S1_DOMAIN",
            "MDCG_GATE_S1B_BUCKET", "MDCG_GATE_S2_COND", "MDCG_GATE_S4_LAYER",
            "MDCG_GATE_S3_SPREAD", "MDCG_GATE_S7_POSTINGS",
            "MDCG_BUCKET_TOPK", "MDCG_BUCKET_MIN_SIM", "MDCG_HOTCACHE")


def check(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  OK   {name}")
    else:
        FAIL += 1
        FAILS.append(name)
        print(f"  FAIL {name}  {detail}")


class _Env:
    """临时设置进程级开关：进入先清 GATE_ENV 全量，再按需置值；退出逐键还原。"""

    def __init__(self, **kv):
        self.kv = kv
        self.old = {}

    def __enter__(self):
        self.old = {k: os.environ.get(k) for k in GATE_ENV}
        for k in GATE_ENV:
            os.environ.pop(k, None)
        os.environ["MDCG_HOTCACHE"] = "0"
        for k, v in self.kv.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        return self

    def __exit__(self, *_exc):
        for k, v in self.old.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        return False


def build_lib(root):
    """确定性小库（建库期开总开关：门控元数据只在开关开时落索引）。

    域标签经 add(big_domain=…) 显式给出、桶经 tags 的 `domain:` 前缀路由。
    **建库必须开 MDCG_RETRIEVAL_PIPELINE**：`_strip_empty_gate_fields`
    （mdcg.py:685）的既有纪律是「总开关未设 → big_domain / observation_position
    两键一律不落条目」——这正是生产序列（开关打开后新写入的节点才带域标签，
    历史节点由 `backfill_big_domain` 补齐），故本库按该序列构造；否则索引里
    无域标签，S1/S2 无靶可打（守卫将退化为自证同义）。
    """
    with _Env(MDCG_RETRIEVAL_PIPELINE="1"):
        cg = MdCGSecure(root)
        for i in range(15):      # A：域内（心理）+ 主桶（认知心理）
            cg.add("mem_%03d" % i,
                   "# 功能名：认知心理样本 %d\n# 正文：记忆 认知 学习 心理 情感 性格 %d" % (i, i),
                   "knowledge", tags=["domain:认知心理"], big_domain="心理")
        for i in range(15, 30):  # B：域外（物理）+ 异桶，但词面同样命中查询
            cg.add("mem_%03d" % i,
                   "# 功能名：力学物理样本 %d\n# 正文：记忆 物理 力学 电磁 量子 能量 %d" % (i, i),
                   "knowledge", tags=["domain:力学物理"], big_domain="物理")
        for i in range(30, 33):  # C：域内主桶，但观测位与情境不符（S2 靶）
            cg.add("mem_%03d" % i,
                   "# 功能名：认知心理野外样本 %d\n# 正文：记忆 认知 学习 心理 野外 观测 %d" % (i, i),
                   "knowledge", tags=["domain:认知心理"], big_domain="心理",
                   condition_space={"observation_position": "野外"})
        for i in range(33, 38):  # D：域内（心理）但异桶（S1b 靶）
            cg.add("mem_%03d" % i,
                   "# 功能名：记忆研究样本 %d\n# 正文：记忆 认知 学习 心理 研究 %d" % (i, i),
                   "knowledge", tags=["domain:记忆研究"], big_domain="心理")
        cg.flush()
        cg.close()


#: 本次进程建过的实验库根（系统临时目录）；退出时统一清理——守卫跑一次建若干个
#: （每个开关态一个独立根），不清理会在 %TEMP% 里线性积压。
_TEMP_ROOTS = []


# 生效条件：始终在系统临时目录（tempfile.mkdtemp，前缀 mdcg_c8_）新建一个空目录并返回其 NFC 归一化绝对路径；目录登记进 _TEMP_ROOTS 供退出时清理。不触碰任何在役数据根。
def fresh_root():
    d = unicodedata.normalize("NFC", tempfile.mkdtemp(prefix="mdcg_c8_"))
    _TEMP_ROOTS.append(d)
    return d


# 生效条件：把本进程建过的实验库根逐一 rmtree（不抛）；可在任何退出路径调用，重复调用为空操作。先 gc.collect() 再最多重试 3 轮（每轮间隔 0.2s）——Windows 上 main() 刚返回时仍有未释放的文件句柄，单次 rmtree 会静默失败（实测 7 个根漏 5 个），重试后收敛为 0。
def _cleanup():
    import gc
    gc.collect()
    while _TEMP_ROOTS:
        path = _TEMP_ROOTS.pop()
        for _try in range(3):
            shutil.rmtree(path, ignore_errors=True)
            if not os.path.exists(path):
                break
            time.sleep(0.2)


def measure(env, ctx):
    """在给定开关态下取三路读数：结果 id 集合 / scanned / gates 审计块。

    三路（同一库、同一 query、同一开关）：
      search      —— MdCGSecure.search（生产链 mcp_server → MdCGSecure → MdCGOS）
      secure_rrf  —— MdCGSecure.search_rrf（mdcg_recall / cg(op=read, budget_tokens=…)）
      os_rrf      —— MdCGOS.search_rrf（基类实现；bench/eval 侧入口）
    **每个开关态一个独立库根**：索引快照是派生物，跨态复用会让「带标签/不带
    标签」的条目形状随快照写入顺序漂移（实测：总开关关时落下的快照不带域标签，
    被后续开关态复用则 S1/S2 无靶可打）——独立根消除该串扰。
    """
    root = fresh_root()
    build_lib(root)
    with _Env(**env):
        cg = MdCGSecure(root)
        base = MdCGOS(root)
        try:
            rs, ms = cg.search(QUERY, k=40, judge=False, record=False, context=ctx)
            rr, mr = cg.search_rrf(QUERY, k=40, judge=False, record=False, context=ctx)
            rb, mb = base.search_rrf(QUERY, k=40, judge=False, record=False, context=ctx)
        finally:
            cg.close()
            base.close()
    return {
        "root": root,
        "search": {"gates": ms.get("gates"), "scanned": ms.get("scanned"),
                   "ids": sorted(x[0]["id"] for x in rs)},
        "secure_rrf": {"gates": mr.get("gates"), "scanned": mr.get("scanned"),
                       "ids": sorted(x[0]["id"] for x in rr)},
        "os_rrf": {"gates": mb.get("gates"), "scanned": mb.get("scanned"),
                   "ids": sorted(x[0]["id"] for x in rb)},
    }


def _gates_json(reading):
    return json.dumps(reading["gates"], ensure_ascii=False, sort_keys=True,
                      default=str)


# ===================== 定点变异自证（--mutate） =====================

#: 工作区根（本文件位于 <repo>/md_cg/）——镜像树从这里只读取材。
_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# 生效条件：--mutate 模式下，逐条对镜像树的 rel 文件做 old→new 的**唯一**文本替换（命中数必须为 1，否则 ANCHOR-MISS），随后跑本守卫正向面，比对该条应被打红的项数 expect。old 里的 \n 按目标文件实际换行（CRLF/LF）还原。
_MUTATIONS = (
    ("C8-M1 断线：search_rrf 不再调用共享门控（退回 C-8 病态：无 gates 键、恒全表）",
     "md_cg/mdcos.py",
     "        entries, gates = apply_retrieval_gates(\n"
     "            entries, terms, big_domain, context, 1)\n",
     "        gates = {}\n", 26),
    ("C8-M2 域信号断供：search_rrf 传 big_domain=None（S1 退化 no_domain_signal）",
     "md_cg/mdcos.py",
     "            entries, terms, big_domain, context, 1)\n",
     "            entries, terms, None, context, 1)\n", 11),
    ("C8-M3 ctx 断供：search_rrf 传 context=None（S2 硬槽在 RRF 路失效）",
     "md_cg/mdcos.py",
     "            entries, terms, big_domain, context, 1)\n",
     "            entries, terms, big_domain, None, 1)\n", 6),
    ("C8-M4 第三份实现：RRF 入口自建 gates[\"s1b\"] 审计块（破坏「唯一实现」）",
     "md_cg/mdcos.py",
     "        _gates_meta = {\"gates\": gates} if gates else {}\n",
     "        gates[\"s1b\"] = {\"third\": \"copy\"}\n"
     "        _gates_meta = {\"gates\": gates} if gates else {}\n", 11),
    ("C8-M5 委托断裂：MdCGSecure.search_rrf 不再走 super()（父类接线被绕过）",
     "md_cg/mdcos.py",
     "        res, meta = super().search_rrf(*a, **kw)\n",
     "        return [], {\"tier\": \"RRF\"}\n", 21),
    ("C8-M6 门控错位：search_rrf 传 min_results=10**9（S1 恒回退不收敛）",
     "md_cg/mdcos.py",
     "            entries, terms, big_domain, context, 1)\n",
     "            entries, terms, big_domain, context, 10**9)\n", 16),
    ("C8-M7 零变更破坏：RRF 入口 meta 恒落 gates 键（默认态也落）",
     "md_cg/mdcos.py",
     "        _gates_meta = {\"gates\": gates} if gates else {}\n",
     "        _gates_meta = {\"gates\": gates}\n", 4),
    ("C8-M8 结构：MdCG.search 不再引用共享门控（共享实现被抄散）",
     "md_cg/mdcg.py",
     "        entries, gates = apply_retrieval_gates(\n"
     "            entries, terms, big_domain, context, min_results)\n",
     "        entries, gates = entries, {}\n", 1),
)


# 生效条件：在系统临时目录建最小镜像树——只读复制 <repo>/md_cg（排除 __pycache__）与 <repo>/data/policy.json（写入闸门的 fail-closed 依赖它）；返回镜像根。工作区不被写入。
def _overlay_build():
    root = unicodedata.normalize("NFC", tempfile.mkdtemp(prefix="mdcg_c8_mut_"))
    shutil.copytree(os.path.join(_REPO, "md_cg"), os.path.join(root, "md_cg"),
                    ignore=shutil.ignore_patterns("__pycache__"))
    os.makedirs(os.path.join(root, "data"), exist_ok=True)
    _pol = os.path.join(_REPO, "data", "policy.json")
    if os.path.exists(_pol):
        shutil.copy2(_pol, os.path.join(root, "data", "policy.json"))
    return root


#: 变异表涉及的文件集合（每次变异前逐一路从工作区重取原始副本，保证逐次独立）。
_MUT_FILES = tuple(sorted({rel for _n, rel, _o, _x, _e in _MUTATIONS}))


def _run_guard_in(cwd):
    """在 cwd 里跑本守卫**正向面**（不带 --mutate，无递归），返回 (rc, 红项列表)。"""
    p = subprocess.run([sys.executable, "-X", "utf8", "-m",
                        "md_cg.test_c8_search_rrf_gates"],
                       cwd=cwd, capture_output=True, text=True,
                       encoding="utf-8", errors="replace", timeout=900)
    out = (p.stdout or "") + (p.stderr or "")
    reds = [l.strip()[5:].strip() for l in out.splitlines()
            if l.strip().startswith("FAIL ")]
    return p.returncode, reds, out


def _mutate_mode(list_only=False):
    print("!! C-8 定点变异自证：逐条把接线退回病态，套件必须按预期条数转红\n")
    if list_only:
        for name, rel, _o, _n, exp in _MUTATIONS:
            print("  %-54s %-14s expect_red=%d" % (name[:54], rel, exp))
        return 0

    overlay = _overlay_build()
    anchor_miss, bad = [], []
    try:
        rc, reds, _out = _run_guard_in(overlay)
        print("  未变异基线（临时镜像树）：红项=%d（必须为 0）、rc=%d"
              % (len(reds), rc))
        if reds or rc != 0:
            bad.append("未变异基线即失败（红=%d rc=%d）" % (len(reds), rc))
        for name, rel, old, new, expect in _MUTATIONS:
            path = os.path.join(overlay, *rel.split("/"))
            # 每次变异前把**变异表涉及的每个文件**都从工作区重取：逐次独立
            # （只还原当前文件会让上一处变异在别的文件上残留、污染本次读数——
            # 本表实测踩过：M7 留在 mdcos.py 的改动使 M8 多红 4 项），且绝不写工作区
            for _r in _MUT_FILES:
                shutil.copy2(os.path.join(_REPO, *_r.split("/")),
                             os.path.join(overlay, *_r.split("/")))
            data = open(path, "rb").read()
            _nl = "\r\n" if b"\r\n" in data else "\n"
            _o = old.replace("\n", _nl).encode("utf-8")
            _n = new.replace("\n", _nl).encode("utf-8")
            if data.count(_o) != 1:
                print("  ANCHOR-MISS %s —— 锚点在 %s 当前源码里命中 %d 次"
                      "（本表就是判据，漂移必须硬失败）"
                      % (name, rel, data.count(_o)))
                anchor_miss.append(name)
                continue
            open(path, "wb").write(data.replace(_o, _n))
            rc, reds, _out = _run_guard_in(overlay)
            mark = "OK  " if len(reds) == expect else "MISMATCH"
            verdict = "红" if reds else "**仍全绿 = 该判据空转**"
            print("  %s %-54s 红项=%d 预期=%d rc=%d  %s"
                  % (mark, name[:54], len(reds), expect, rc, verdict))
            for r in reds:
                print("        " + r)
            if len(reds) != expect:
                bad.append("%s（红=%d 预期=%d）" % (name, len(reds), expect))
    finally:
        shutil.rmtree(overlay, ignore_errors=True)

    if anchor_miss:
        print("\nANCHOR-MISS：%s" % "、".join(anchor_miss))
        print("退出码 2（fail-closed）：变异表锚点漂移即判失败，不得静默跳过")
        return 2
    print("\nC-8 定点变异自证：%s"
          % ("PASS（每处接线都被打红且恰好命中预期项数）" if not bad
             else "FAIL —— " + "、".join(bad)))
    return 0 if not bad else 1


def main():
    # ---------------- P1 库面元数据就位 ----------------
    print("== P1 库面元数据就位（桶 / 域 / 观测位）==")
    root = fresh_root()
    print("root =", root)
    build_lib(root)
    cg = MdCGSecure(root)
    idx = cg.index["nodes"]
    n_all = len(idx)
    b_ok = {}
    for nid in sorted(ALL_IDS):
        e = idx.get(nid) or {}
        b_ok[nid] = (routing.bucket_key_readable(e.get("bucket") or ""),
                     e.get("big_domain"), e.get("observation_position"))
    cg.close()
    check("P1a 节点数与分组一致", n_all == N_ALL, f"index={n_all} expect={N_ALL}")
    check("P1b A 组桶/域落盘",
          all(b_ok[i][0] == "认知心理" and b_ok[i][1] == "心理" for i in sorted(A_IDS)),
          str(sorted(b_ok.items())[:3]))
    check("P1c B 组桶/域落盘",
          all(b_ok[i][0] == "力学物理" and b_ok[i][1] == "物理" for i in sorted(B_IDS)),
          str(sorted(b_ok.items())[15:18]))
    check("P1d C 组观测位落盘（S2 靶）",
          all(b_ok[i][2] == "野外" for i in sorted(C_IDS)), str(sorted(C_IDS)))
    check("P1e D 组域内异桶落盘（S1b 靶）",
          all(b_ok[i][0] == "记忆研究" and b_ok[i][1] == "心理" for i in sorted(D_IDS)),
          str(sorted(b_ok.items())[33:36]))

    # ---------------- P2 默认零变更 ----------------
    print("== P2 默认零变更（总开关未设 / 总开关开但子门控全关）==")
    off = measure({}, None)
    alloff = measure({"MDCG_RETRIEVAL_PIPELINE": "1",
                            "MDCG_GATE_S1_DOMAIN": "0",
                            "MDCG_GATE_S2_COND": "0"}, None)
    for path in ("search", "secure_rrf", "os_rrf"):
        o, a = off[path], alloff[path]
        check(f"P2a {path} 总开关未设 → meta 无 gates 键",
              o["gates"] is None, str(o["gates"])[:120])
        check(f"P2b {path} 子门控全关 ≡ 未设（结果逐位一致、无 gates 键）",
              o["ids"] == a["ids"] and o["scanned"] == a["scanned"]
              and a["gates"] is None,
              f"off={len(o['ids'])}/{o['scanned']} alloff={len(a['ids'])}/{a['scanned']}"
              f" gates={a['gates']}")
    check("P2c 默认态三路候选面 = 全库（不收敛）",
          all(off[p]["ids"] == sorted(ALL_IDS) and off[p]["scanned"] == N_ALL
              for p in ("search", "secure_rrf", "os_rrf")),
          json.dumps({p: [len(off[p]["ids"]), off[p]["scanned"]]
                      for p in ("search", "secure_rrf", "os_rrf")},
                     ensure_ascii=False))

    # ---------------- P3 逐路门控生效 ----------------
    print("== P3 逐路门控生效（总开关=1，S1 未设=开）==")
    p1 = measure({"MDCG_RETRIEVAL_PIPELINE": "1"}, None)
    for path in ("search", "secure_rrf", "os_rrf"):
        g = p1[path]["gates"] or {}
        check(f"P3a {path} gates 审计出现（修前 rrf 两路必红：gates=None）",
              "s1" in g, str(p1[path]["gates"])[:160])
        check(f"P3b {path} scanned 真实收敛（{N_ALL} → 23）",
              p1[path]["scanned"] == 23, f"scanned={p1[path]['scanned']}")
    s1b_off = measure({"MDCG_RETRIEVAL_PIPELINE": "1",
                             "MDCG_GATE_S1B_BUCKET": "1",
                             "MDCG_BUCKET_TOPK": "1"}, None)
    for path in ("search", "secure_rrf", "os_rrf"):
        g = (s1b_off[path]["gates"] or {}).get("s1b") or {}
        check(f"P3c {path} S1b 显式开门 → 桶收敛（23 → 18、键=认知心理）",
              routing.bucket_key_readable((g.get("keys") or [""])[0]) == "认知心理"
              and g.get("out") == 18 and s1b_off[path]["scanned"] == 18,
              json.dumps(g, ensure_ascii=False)[:160])
    s2 = measure({"MDCG_RETRIEVAL_PIPELINE": "1", "MDCG_GATE_S1_DOMAIN": "0",
                        "MDCG_GATE_S2_COND": "1"}, CTX)
    for path in ("search", "secure_rrf", "os_rrf"):
        g = (s2[path]["gates"] or {}).get("s2") or {}
        check(f"P3d {path} S2 硬槽门控（观测位不符剔除恰 3 条）",
              g.get("dropped") == 3 and s2[path]["scanned"] == N_ALL - 3,
              json.dumps(g, ensure_ascii=False)[:160])
    s4 = measure({"MDCG_RETRIEVAL_PIPELINE": "1", "MDCG_GATE_S4_LAYER": "1"}, None)
    for path in ("search", "secure_rrf", "os_rrf"):
        g = s4[path]["gates"] or {}
        check(f"P3e {path} S4 层级审计（显式 =1 才落键）",
              "s4" in g and g["s4"].get("layers"),
              json.dumps(g, ensure_ascii=False)[:160])

    # ---------------- P4 三路审计逐位相同 ----------------
    print("== P4 三路审计逐位相同（同一实现 ⇒ 同一审计块）==")
    for label, reading in (("S1", p1), ("S1b", s1b_off), ("S2", s2), ("S4", s4)):
        gs = {p: _gates_json(reading[p]) for p in ("search", "secure_rrf", "os_rrf")}
        check(f"P4 {label} 配置下三路 gates 逐位相同",
              gs["search"] == gs["secure_rrf"] == gs["os_rrf"],
              json.dumps(gs, ensure_ascii=False)[:300])

    # ---------------- P5 候选面对照（开门 vs 关门）----------------
    print("== P5 候选面对照（机械可判定：结果 id 集合逐路比对）==")
    for path in ("search", "secure_rrf", "os_rrf"):
        ids = set(p1[path]["ids"])
        check(f"P5a {path} S1 开门：域外 B 组被剔除、域内保留",
              ids == (A_IDS | C_IDS | D_IDS) and not (ids & B_IDS),
              f"n={len(ids)} extra={sorted(ids - (A_IDS|C_IDS|D_IDS))[:5]}"
              f" missing={sorted((A_IDS|C_IDS|D_IDS) - ids)[:5]}")
        check(f"P5b {path} S1 开门结果 ⊆ 关门结果（收敛只减不增）",
              ids <= set(off[path]["ids"]), f"n={len(ids)}")
        ids1b = set(s1b_off[path]["ids"])
        check(f"P5c {path} S1b 开门：异桶 D 组再被剔除（保 orphan 兜底语义不变）",
              ids1b == (A_IDS | C_IDS) and not (ids1b & (B_IDS | D_IDS)),
              f"n={len(ids1b)} extra={sorted(ids1b - (A_IDS|C_IDS))[:5]}")
        ids2 = set(s2[path]["ids"])
        check(f"P5d {path} S2 开门：观测位不符的 C 组被剔除",
              not (ids2 & C_IDS) and ids2 == (ALL_IDS - C_IDS),
              f"n={len(ids2)} C剩余={sorted(ids2 & C_IDS)[:5]}")
        # 三条路在同一开关态下候选面一致（search 与 rrf 的**排序判据**不同是设计，
        # 但门控后的**候选面**必须同一 —— 分裂病灶的可判定形态）
        check(f"P5e {path} 关门态候选面 = 全库（对照基线成立）",
              set(off[path]["ids"]) == ALL_IDS, f"n={len(off[path]['ids'])}")
        check(f"P5f {path} 开门/关门对照非空（差异确实发生，不是自证同义）",
              set(off[path]["ids"]) - ids == B_IDS,
              f"diff={sorted(set(off[path]['ids']) - ids)[:5]}")

    print("== P5-2 三路候选面互相一致（同一库同一开关）==")
    for label, reading in (("默认", off), ("S1", p1), ("S1b", s1b_off),
                           ("S2", s2), ("S4", s4)):
        sets = {p: tuple(reading[p]["ids"]) for p in ("search", "secure_rrf", "os_rrf")}
        check(f"P5-2 {label} 三路结果 id 序列逐位一致",
              sets["search"] == sets["secure_rrf"] == sets["os_rrf"],
              f"len={[len(v) for v in sets.values()]}")

    # ---------------- P6 结构守卫（防第三份实现）----------------
    print("== P6 结构守卫（共享实现唯一）==")
    src = {}
    for mod, path in ((MdCG, os.path.join(os.path.dirname(__file__), "mdcg.py")),
                      (MdCGOS, os.path.join(os.path.dirname(__file__), "mdcos.py"))):
        with io.open(path, encoding="utf-8") as f:
            src[mod] = f.read()
    for name, fn in (("MdCG.search", MdCG.search), ("MdCGOS.search", MdCGOS.search),
                     ("MdCGOS.search_rrf", MdCGOS.search_rrf)):
        check(f"P6a {name} 源码引用共享门控 apply_retrieval_gates",
              "apply_retrieval_gates" in inspect.getsource(fn))
    check("P6b MdCGSecure.search_rrf 经 super().search_rrf 委托（不自建门控）",
          "super().search_rrf" in inspect.getsource(MdCGSecure.search_rrf))
    check("P6c 门控实现只有一份（gates[\"s1b\"] 仅出现在 mdcg.py）",
          'gates["s1b"]' in src[MdCG] and 'gates["s1b"]' not in src[MdCGOS])

    print()
    if FAILS:
        print(f"FAILED: {len(FAILS)} 项 → {', '.join(FAILS)}")
        return 1
    print(f"ALL OK: {PASS} 项（C-8 三路门控守卫全绿）")
    return 0


if __name__ == "__main__":
    try:
        if "--mutate" in sys.argv:
            sys.exit(_mutate_mode("--list" in sys.argv))
        sys.exit(main())
    finally:
        _cleanup()
