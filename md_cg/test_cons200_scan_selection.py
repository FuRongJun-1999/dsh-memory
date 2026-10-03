# -*- coding: utf-8 -*-
"""cons200 守卫：consistency.check 的选面（相关性预筛 + 保底面 + 超限可观测）。

背景（设计稿签收点 5，第二实现批；2026-10-03 使用者签收）：
`md_cg/consistency.py::check` 旧选面＝`for nid, e in list(nodes.items())`
**索引序前 MAX_SCAN=200** 并静默 break——与 issue #52 同族（按索引序截断 +
静默）：在役库 17882 节点 ⇒ 检测面 ≈1.1%，且 id 字典序最前的 `code_*` 索引
节点占满名额，真正相关的记忆节点（`mem_*` 在字典序后段）几乎从不进入比对
面。写链三处（`writepipe._gate_consistency` / `mdcos.check_consistency` /
`mcp_server._consistency_call`）全走同一入口，缺陷面即全写入面。

本批修法（契约，不得偏离的三条硬线）：MAX_SCAN 数值**不动**（200）、检出集
**修后 ⊇ 修前**、预筛**不读盘**（快照级）。落地形态：
  · 预筛（`_sift_score`，快照级）+ 唯一剔除档＝「新节点未声明可展开条件
    （tw_pos/tw_neg 皆空）时的非纪律候选」（可证无产出）；
  · 精比面＝相关面前 limit ∪ 保底面（过滤后索引序前 limit ∩ 候选）——
    保底面即修前扫描面，逐位保留是「修后 ⊇ 修前」的结构性保证；
  · 读数 scanned（预筛后候选数）/kept（实际精比数）/truncated（scanned>kept）
    超限附 hint。

收口轮①（2026-10-03 复核 DEFER 后，设计侧裁决修法）：剔除档加**面内例外**
——剔除**永不触及修前扫描面**（过滤后索引序前 limit 内候选一律保留进候选面、
落保底面通道）：「修后检出 ⊇ 修前」由此**与「条目 tags 与盘面 fm.tags
同源」无关**（预筛读条目快照、精比读盘面；非同源形态下面内候选仍进精比面、
由盘面判据裁决）。面外非同源残余如实为已声明边界（见 G6/F2 与 `check`
docstring 诚实边界：修前亦检不出，不构成回归）。另修夹具收尾脏留问题：
`_Fixtures.close` 改为「从 `mdcg._LIVE_CGS` 摘除 + 优雅 close + 删临时目录」
——原版删目录后被进程退出兜底（`_atexit_flush_all`）写回 `_index.json`/
`.lock`，每次运行残留一个 `mdcg_cons200_*` 目录。

断言分组（每处判据都有定点变异把它打红，见 `_MUTATIONS`）：
  G1 选面：冲突对落索引尾也能检出（c1 面 + discipline 面）；多层（layer）；
     索引序选面回退即红（变异①重建修前选面，G1 的核心断言转红）。
  G2 对拍：legacy（修前选面，运行时源码重建）vs 修后——修后检出集 ⊇ 修前，
     且新增检出**只能来自原被切面**（不在修前扫描面内的节点，逐条核验）；
     修前扫描面内的检出（保底面）修后仍在。
  G3 可观测：truncated/scanned/kept 口径（kept≤候选数、truncated⟺cand>kept、
     超限附 hint 且含「细化生效条件/不适用条件」「条件索引」语义）；未超限
     不标记不附 hint；MCP 面（`_consistency_call`）同批读数透传。
  G4 成本：预筛为**不读盘**的快照级操作——用读盘计数（包装 cg.get）断言
     「读盘数＝kept」（预筛阶段零读盘）、「无条件内容读盘数降到纪律面
     （1）而非修前 200」、相关候选全部进面（kept≥3）。
  G5 语义红线：MAX_SCAN==200（数值红线）；面内例外不误伤判定（无条件内容下
     面内声明候选与纪律候选仍比对）；exclude 自排除语义保持；小库（未超限）
     四态照旧。（收口轮①同步：D3/E4 因「面内例外」语义变化改写数值与文案。）
  G6 收口轮缺口闭合（复核 DEFER 两条件的守卫侧钉）：F1 非同源形态（内存
     条目 tags 置空＋盘面 tags=[discipline]＋落修前扫描面内）无词面输入仍
     REJECT（面内例外转正；去掉面内例外即红）；F2 面外非同源残余与修前形态
     同判（均不检出，不构成回归，已声明边界）；F3 无词面口径定点（scanned
     ＝面内候选＋面外纪律候选、kept＝scanned、truncated=False、不附 hint）；
     F4 结构保证（无词面输入下面内候选**逐位**进入精比面/读盘面）。

判别力自证（与 `md_cg/test_neg_condition_hits.py` / `test_issue52_*` 同口径）：
  · `--branch-baseline`：逐处**定点变异**（①选面回索引序截断 ②去掉 truncated
    上报 ③预筛把真冲突候选剔掉（假阴性）④MAX_SCAN 数值偷调大（契约禁止面）
    ⑤剔除档失效 ⑥去掉修前扫描面例外（收口轮①面内例外失效——F1/F3 必红））
    ——每处必须**恰好**打红预期条数的断言（多一条少一条都报红），且**所有**
    断言至少被一处变异打红（一条都没被打红的＝空转，判 FAIL）。
    锚点漂移报 ANCHOR-MISS 且**退出码 2**（fail-closed，不静默失效）。
  · **防误删自检（收口轮增补，对齐姊妹守卫 test_mode_parity / test_autonomy_modes）**：
    `_mutation_table_gaps` 按编号钉 `_MUTATION_PINS`（①–⑥）核验表长与编号——
    删条目/改名/重排 ⇒ 三入口（main / --branch-baseline / --legacy-baseline）
    打印 TABLE-GAPS 并 **fail-closed 退出码 2**（此前删⑥为静默 rc=0，复核
    uncovered 第 3 条）。复现（机械可跑）：内存
    `G._MUTATIONS = G._MUTATIONS[:-1]` 后 `G._mutation_table_gaps()` 必报
    `len:5≠6` 与 `缺: ⑥`；经 `G.main()` / `G._branch_baseline` 入口得 rc=2。
  · `--legacy-baseline`：把「修前形态」（索引序前 limit 选面）在运行时源码上
    重建，核心断言必须转红——证明本守卫抓得住 cons200 这个缺陷本身。注意
    收口轮①后：F1 在 legacy 形态下**绿**（HEAD 读盘面本就判 REJECT——F1 的
    红项钉是变异⑥，它不是「索引序截断」面的缺陷）；F3 在 legacy 形态下红
    （新口径为修后形态所定义）。legacy 判据仍是核心三条 A1/B2/B5 全红
    （不要求恰好条数）。
  · 基线源＝**运行时源码**（`inspect.getsource(consistency)`），**不是 git
    HEAD**——基线绑提交即失效（本仓已有两次教训）；锚点都写在 `_MUTATIONS`
    里，实现改动致锚点漂移时会当场报 ANCHOR-MISS。
  · 诚实边界（已知盲区，不假装覆盖）：`rejection_terms` 只覆盖负条件面；
    「旧节点仅声明生效条件（正文 `# 生效条件：` 行）、无任何负条件迹象」的
    结点在快照里**无字段可判**，其与新内容负条件的冲突（c2/c3 面）在候选
    超限且该节点既不落修前扫描面、也不落相关面时可能不被精比——由
    truncated 可观测（hint 给方向），不作「已覆盖」断言；**面外非同源形态
    残余**（F2）同为已声明边界（修前亦检不出，不构成回归）。

运行：python -X utf8 -m md_cg.test_cons200_scan_selection
      python -X utf8 -m md_cg.test_cons200_scan_selection --branch-baseline
      python -X utf8 -m md_cg.test_cons200_scan_selection --legacy-baseline
"""
from __future__ import annotations

import contextlib
import inspect
import io
import os
import shutil
import sys
import tempfile
import time
import types

from . import consistency as _cons
from . import mdcg as _mdcg_mod          # 进程退出兜底登记（_LIVE_CGS）摘除用
from .mdcos import MdCGOS

S = _cons                    # 当前被测模块（变异模式 = exec 出的变异体命名空间）
_CUR_SRC = None              # 变异模式下当前的变异体源码
_PASS = []
_FAIL = []


def ok(cond, label, extra=""):
    (_PASS if cond else _FAIL).append(label)
    print(("  PASS " if cond else "  FAIL ") + label +
          (("  ← " + str(extra)[:200]) if (extra and not cond) else ""))


@contextlib.contextmanager
def _quiet():
    with contextlib.redirect_stdout(io.StringIO()):
        yield


# ---------------------------------------------------------------- 合成库（系统临时目录）
# 硬边界：不动任何在役数据根——库建在 tempfile.mkdtemp 下，用完即删。

def _mk_main(root, n_fill=260):
    """264 节点：`a_conf` 索引序首位（修前扫描面**内**的冲突对）＋ n_fill 条
    填充（无声明；session 多值＝多会话形态）＋索引序尾部的三个目标节点：
      · zz_offline：负条件「生产环境」（c1 面冲突对，尾部）；
      · zz_disc   ：纪律节点（tags=discipline，禁令「删除生产数据」，尾部）；
      · b_ctx     ：contextual 层（layer 面）。
    候选数 = 1 + n_fill + 2 = n_fill+3 > MAX_SCAN(200) ⇒ 截断场景成立。
    """
    cg = MdCGOS(os.path.join(root, "main"))
    cg.add("a_conf", "# 功能名：前置冲突\n# 生效条件：前置环境\n"
                     "# 不适用条件：生产环境\n",
           layer="knowledge", non_applicable_conditions=["生产环境"],
           session="sess_front")
    for i in range(n_fill):
        cg.add("f%04d" % i,
               "# 功能名：填充 %d\n正文：填充节点 %d\n" % (i, i),
               layer="knowledge", session=("sess_a" if i % 2 else "sess_b"))
    cg.add("zz_offline", "# 功能名：离线批处理\n# 生效条件：离线环境\n"
                         "# 不适用条件：生产环境\n",
           layer="knowledge", non_applicable_conditions=["生产环境"],
           session="sess_tail")
    cg.add("zz_disc", "# 功能名：生产纪律\n# 执行：禁止删除生产数据\n",
           layer="knowledge", tags=["discipline"],
           non_applicable_conditions=["删除生产数据"], session="sess_tail")
    cg.add("b_ctx", "# 功能名：语境节点\n# 生效条件：语境残留时\n"
                    "# 不适用条件：语境残留\n",
           layer="contextual", non_applicable_conditions=["语境残留"],
           session="sess_ctx")
    cg.flush()
    return cg


def _mk_small(root):
    """8 节点小库：一条有条件冲突对（未超限路径）。"""
    cg = MdCGOS(os.path.join(root, "small"))
    for i in range(6):
        cg.add("s%02d" % i, "# 功能名：小填充 %d\n正文：小填充 %d\n" % (i, i),
               layer="knowledge", session="sess_s")
    cg.add("s_off", "# 功能名：小冲突\n# 不适用条件：生产环境\n",
           layer="knowledge", non_applicable_conditions=["生产环境"])
    cg.add("s_oth", "# 功能名：小另层\n# 不适用条件：生产环境\n",
           layer="contextual", non_applicable_conditions=["生产环境"])
    cg.flush()
    return cg


def _mk_gapface(root):
    """收口轮 G6 专用小库（非同源形态 · 面内）：`q_ns`＝非合作写者形态节点
    ——盘面 fm.tags=[discipline]＋禁令「删除生产数据」（cg.add 正常写入），
    运行时把**内存索引条目** tags 置空（模拟条目陈化/非合作写者直改 .md 不
    重建索引）；小库（7 节点 ≤ limit）⇒ 该节点必在修前扫描面**内**。
    条目改动由调用方 finally 还原（共享 fixture 不残留）。"""
    cg = MdCGOS(os.path.join(root, "gapface"))
    for i in range(5):
        cg.add("g%02d" % i, "# 功能名：面内填充 %d\n正文：填充 %d\n" % (i, i),
               layer="knowledge", session="sess_g")
    cg.add("q_ns", "# 功能名：生产纪律（非合作写者形态）\n"
                   "# 执行：禁止删除生产数据\n",
           layer="knowledge", tags=["discipline"],
           non_applicable_conditions=["删除生产数据"], session="sess_g")
    cg.add("q_fill", "# 功能名：尾部填充\n正文：填充\n",
           layer="knowledge", session="sess_g")
    cg.flush()
    return cg


def _mk_tail_residual(root):
    """收口轮 G6 专用库（非同源形态 · 面外）：261 节点；`t_ns`＝非合作写者
    形态节点（盘面 discipline、条目 tags 置空）落**修前扫描面外**——钉住
    「面外残余」：修前形态亦检不出（不构成回归）。"""
    cg = MdCGOS(os.path.join(root, "tailns"))
    for i in range(260):
        cg.add("t%04d" % i, "# 功能名：填充 %d\n正文：填充 %d\n" % (i, i),
               layer="knowledge", session="sess_t")
    cg.add("t_ns", "# 功能名：生产纪律（面外非合作写者形态）\n"
                   "# 执行：禁止删除生产数据\n",
           layer="knowledge", tags=["discipline"],
           non_applicable_conditions=["删除生产数据"], session="sess_t")
    cg.flush()
    return cg


class _Fixtures:
    """一次构建、多轮复用（变异核验要重跑 N 轮）——库面与变异面正交。"""

    def __init__(self):
        self.tmp = tempfile.mkdtemp(prefix="mdcg_cons200_")
        self.main = _mk_main(self.tmp)
        self.small = _mk_small(self.tmp)
        self.gapface = _mk_gapface(self.tmp)      # G6/F1：非同源·面内
        self.tail = _mk_tail_residual(self.tmp)   # G6/F2：非同源·面外残余

    def close(self):
        """收口轮①（2026-10-03）补：先优雅关闭各 fixture 实例并**从 md_cg 的
        进程退出兜底登记（`mdcg._LIVE_CGS`）摘除**，再删临时目录。

        为什么必须摘除：实例存活时，进程退出会触发 `mdcg._atexit_flush_all`
        → 对每个存活实例 `close()` → compact/rebuild 把 `_index.json`（含
        `.lock`）**写回刚被删掉的临时根**（makedirs 重建目录）——实测每次
        运行残留一个 `mdcg_cons200_*` 目录（每库 2 个文件）；摘除后退出兜底
        不再写，删目录才真正干净（本修复实测三连跑零残留）。"""
        for name in ("main", "small", "gapface", "tail"):
            cg = getattr(self, name, None)
            if cg is None:
                continue
            live = getattr(_mdcg_mod, "_LIVE_CGS", None)
            try:
                if live is not None:
                    live.discard(cg)
            except Exception:                     # noqa: BLE001  兜底路径不该再抛
                pass
            try:
                cg.close()
            except Exception:                     # noqa: BLE001  同款：清理不该再抛
                pass
        for _ in range(3):
            shutil.rmtree(self.tmp, ignore_errors=True)
            if not os.path.exists(self.tmp):
                break
            time.sleep(0.05)


# ---------------------------------------------------------------- 场景集与检出集

_CASES = (
    # (名, layer, 待检内容, 期望检出节点)
    ("P1", "knowledge", "# 功能名：生产批处理\n# 生效条件：生产环境\n",
     "zz_offline"),
    ("P2", "knowledge", "删除生产数据", "zz_disc"),
    ("P3", "contextual", "# 功能名：语境待检\n# 生效条件：语境残留\n",
     "b_ctx"),
)
_CASE_LAYER = {c[0]: c[1] for c in _CASES}


def _detect(mod, cg):
    """跑场景集，返回检出集 {(case, with_id, type)}（with 为空的自否定不计）。"""
    out = set()
    for name, layer, content, _exp in _CASES:
        r = mod.check(cg, content, layer=layer, depth=0)
        for c in (r.get("conflicts") or []):
            if c.get("with"):
                out.add((name, str(c["with"]), str(c.get("type"))))
    return out


def _pre_face(cg, layer, limit=None):
    """修前扫描面（**与修前实现逐位同口径**）：exclude/layer 过滤后的索引序
    前 limit 名。守卫据此核验「新增检出只能来自原被切面」。"""
    lim = int(_cons.MAX_SCAN if limit is None else limit)
    face = []
    for nid, e in list((cg.index.get("nodes") or {}).items()):
        if layer and e.get("layer") != layer:
            continue
        if len(face) >= lim:
            break
        face.append(nid)
    return face


def _face_and_disc(cg, layer=None):
    """独立重算（不依赖被测实现）：过滤后索引序前 limit 内候选数 face_n，
    与面外条目中 `_is_discipline` 判真者数 disc_out——无词面（no_terms）输入的
    候选面口径＝face_n＋disc_out（收口轮①面内例外：面内一律保留、面外仅纪律）。"""
    lim = int(_cons.MAX_SCAN)
    face_n = disc_out = seen = 0
    # H-4(a)：从 cg.index 取 nodes 先取快照（与守卫全域纪律一致）
    for nid, e in list((cg.index.get("nodes") or {}).items()):
        if layer and e.get("layer") != layer:
            continue
        if seen < lim:
            face_n += 1
        elif _cons._is_discipline({"tags": e.get("tags")}, nid):
            disc_out += 1
        seen += 1
    return face_n, disc_out


def _clear_entry_tags(cg, nid):
    """把内存索引条目的 tags 置空（模拟**非同源形态**：盘面有、条目没有），
    返回原值供还原。"""
    e = cg.index["nodes"].get(nid) or {}
    old = e.get("tags")
    e["tags"] = []
    return old


def _restore_entry_tags(cg, nid, old):
    e = cg.index["nodes"].get(nid) or {}
    if old is None:
        e.pop("tags", None)
    else:
        e["tags"] = old


class _CountGet:
    """读盘计数器：转发一切到真库，给 cg.get 计数并记 id（成本/结构断言用）。"""

    def __init__(self, cg):
        d = self.__dict__
        d["_cg"] = cg
        d["gets"] = 0
        d["ids"] = []

    def __getattr__(self, k):
        return getattr(self.__dict__["_cg"], k)

    def get(self, nid):
        self.__dict__["gets"] += 1
        self.__dict__["ids"].append(nid)
        return self.__dict__["_cg"].get(nid)


# ---------------------------------------------------------------- G1 选面
def g1_selection(fx):
    print("== G1 选面：冲突对落索引尾也能检出（相关面）==")
    r1 = S.check(fx.main, _CASES[0][2], layer="knowledge", depth=0)
    got1 = {str(c["with"]) for c in r1.get("conflicts") or [] if c.get("with")}
    ok("zz_offline" in got1,
       "A1 索引序尾部的冲突对（c1 面）被检出（修前扫描面读不到它；回退即红）",
       (sorted(got1), r1.get("verdict")))
    ok(r1.get("verdict") == "DEFER" and r1.get("conflict_strength", 0) >= 0.6,
       "A2 尾部冲突对使判定进入 DEFER/强度 ≥ CLASH_HIGH（修前为 BLINDSPOT/0）",
       (r1.get("verdict"), r1.get("conflict_strength")))

    r2 = S.check(fx.main, _CASES[1][2], layer="knowledge", depth=0)
    got2 = {str(c["with"]) for c in r2.get("conflicts") or [] if c.get("with")}
    ok("zz_disc" in got2 and r2.get("verdict") == "REJECT",
       "A3 索引序尾部的纪律节点（discipline 面）被检出（REJECT）",
       (sorted(got2), r2.get("verdict")))

    r3 = S.check(fx.main, _CASES[2][2], layer="contextual", depth=0)
    got3 = {str(c["with"]) for c in r3.get("conflicts") or [] if c.get("with")}
    ok("b_ctx" in got3,
       "A4 layer 面：contextual 层冲突对在层过滤后照常检出",
       (sorted(got3), r3.get("verdict")))


# ---------------------------------------------------------------- G2 对拍
def g2_parity(fx):
    print("== G2 对拍：修后检出集 ⊇ 修前（legacy 形态运行时重建）==")
    mod, raw_ns, src = _build_mutant(_LEGACY_REPLS)
    if mod is None:
        # 锚点已不在（如变异①下当前形态即修前形态）：修前检出集＝当前形态
        r_old = _detect(S, fx.main)
    else:
        saved = _activate(mod, raw_ns, src)
        try:
            r_old = _detect(S, fx.main)      # S 已是 legacy 形态
        finally:
            _deactivate(saved)
    r_new = _detect(S, fx.main)              # 当前（修后）形态
    ok(r_old and r_old <= r_new,
       "B1 修后检出集 ⊇ 修前（legacy 重建：索引序前 limit 选面）",
       (sorted(r_old), sorted(r_new)))
    new_items = sorted(r_new - r_old)
    ok(bool(new_items),
       "B2 修复有效：存在「修前漏检、修后检出」的新增检出", new_items)
    bad = []
    for case, wid, _typ in new_items:
        face = _pre_face(fx.main, _CASE_LAYER.get(case))
        if wid in face:
            bad.append((case, wid))
    ok(bool(new_items) and not bad,
       "B3 新增检出非空且**只能来自原被切面**（逐条核验：不在修前扫描面内）",
       (new_items, bad))
    ok(bool(r_old) and all(item in r_new for item in r_old),
       "B4 修前扫描面内的检出（保底面）修后逐条仍在", sorted(r_old))
    ok(("P1", "zz_offline", "condition_clash") in r_new
       and ("P1", "zz_offline", "condition_clash") not in r_old,
       "B5 尾部冲突对：修前漏检、修后检出（缺陷取证的守卫内复现）",
       (sorted(r_old), sorted(r_new)))


# ---------------------------------------------------------------- G3 可观测
def g3_reads(fx):
    print("== G3 可观测：truncated/scanned/kept/hint 与 MCP 透传 ==")
    r = S.check(fx.main, _CASES[0][2], layer="knowledge", depth=0)
    scanned, kept, trunc = r.get("scanned"), r.get("kept"), r.get("truncated")
    ok(trunc is True,
       "C1 候选超限 ⇒ truncated=True（修前无任何标记）", trunc)
    ok(isinstance(scanned, int) and isinstance(kept, int)
       and scanned > kept,
       "C2 口径：scanned>kept（scanned=预筛后候选数、kept=实际精比数）",
       (scanned, kept))
    ok(isinstance(kept, int) and kept >= 3
       and kept <= 2 * _cons.MAX_SCAN,
       "C3 kept 覆盖全部相关候选（≥3：a_conf/zz_offline/zz_disc）且 ≤2×MAX_SCAN",
       (kept, _cons.MAX_SCAN))
    hint = r.get("hint") or ""
    ok(bool(hint) and "细化生效条件" in hint and "不适用条件" in hint
       and "条件索引" in hint,
       "C4 截断附可操作 hint（细化生效条件/不适用条件 or 建立条件索引）", hint)

    rs = S.check(fx.small, "# 功能名：小批处理\n# 生效条件：生产环境\n",
                 layer="knowledge", depth=0)
    ok(rs.get("truncated") is False and "hint" not in rs
       and rs.get("scanned") == rs.get("kept"),
       "C5 未超限：truncated=False、不附 hint、scanned==kept（口径自洽）",
       {k: rs.get(k) for k in ("scanned", "kept", "truncated")})

    from .mcp_server import _consistency_call
    mcp = _consistency_call(fx.main, {"action": "check",
                                      "content": _CASES[0][2],
                                      "layer": "knowledge", "depth": 0})
    ok(mcp.get("truncated") is True and isinstance(mcp.get("kept"), int)
       and isinstance(mcp.get("scanned"), int) and bool(mcp.get("hint")),
       "C6 MCP 面（_consistency_call）同批读数随返回体透传（旧调用方不读新键不受影响）",
       {k: mcp.get(k) for k in ("scanned", "kept", "truncated")})


# ---------------------------------------------------------------- G4 成本
def g4_cost(fx):
    print("== G4 成本：预筛不读盘（读盘计数断言，不用时间阈值）==")
    c1 = _CountGet(fx.main)
    r1 = S.check(c1, _CASES[0][2], layer="knowledge", depth=0)
    ok(c1.gets == r1.get("kept") and c1.gets < len(fx.main.index["nodes"]),
       "D1 读盘数＝kept（预筛/选面阶段零读盘；未全量读盘）",
       (c1.gets, r1.get("kept"), len(fx.main.index["nodes"])))
    ok(isinstance(r1.get("kept"), int) and r1.get("kept") >= 3,
       "D2 相关候选（a_conf/zz_offline/zz_disc）全部进入精比面（kept≥3）",
       r1.get("kept"))

    c2 = _CountGet(fx.main)
    r2 = S.check(c2, _CASES[1][2], layer="knowledge", depth=0)
    fn, dout = _face_and_disc(fx.main, "knowledge")
    ok(c2.gets == r2.get("kept") == r2.get("scanned") == fn + dout
       and r2.get("truncated") is False,
       "D3 无条件内容：剔除档只剔**面外**非纪律候选（面内一律保留——收口轮①"
       "面内例外；读盘＝kept＝scanned＝%d＝面内 %d＋面外纪律 %d；修前为 200 次"
       "且面外纪律漏检）——纪律候选（zz_disc）保留" % (fn + dout, fn, dout),
       (c2.gets, r2.get("kept"), r2.get("scanned")))

    c3 = _CountGet(fx.small)
    r3 = S.check(c3, "# 功能名：小批处理\n# 生效条件：生产环境\n",
                 layer="knowledge", depth=0)
    ok(c3.gets == r3.get("kept") and c3.gets <= len(fx.small.index["nodes"]),
       "D4 小库溯源：读盘数＝kept 且不超过全库节点数（快照级候选面）",
       (c3.gets, r3.get("kept"), len(fx.small.index["nodes"])))


# ---------------------------------------------------------------- G5 语义红线
def g5_redlines(fx):
    print("== G5 语义红线：MAX_SCAN / 剔除档安全 / exclude / 四态 ==")
    ok(_cons.MAX_SCAN == 200,
       "E1 MAX_SCAN==200 一字未动（契约禁止面：数值放大不是修法）",
       _cons.MAX_SCAN)

    r = S.check(fx.main, _CASES[0][2], layer="knowledge", depth=0,
                exclude="zz_offline")
    got = {str(c["with"]) for c in r.get("conflicts") or [] if c.get("with")}
    ok("zz_offline" not in got and "a_conf" in got,
       "E2 exclude 自排除语义保持（被排除节点不检出不比对；其余照常）",
       sorted(got))

    rs = S.check(fx.small, "# 功能名：无冲突小批\n# 生效条件：完全无关条件\n",
                 layer="knowledge", depth=0)
    ok(rs.get("verdict") == "ACCEPT" and rs.get("conflict_strength") == 0.0,
       "E3 四态照旧：无关条件 → ACCEPT/0.0（小库未超限路径）",
       (rs.get("verdict"), rs.get("conflict_strength")))

    rn = S.check(fx.main, "这是一条无条件的普通记录", layer="knowledge",
                 depth=0)
    fn, dout = _face_and_disc(fx.main, "knowledge")
    ok(rn.get("verdict") == "ACCEPT" and rn.get("comparable") == 2
       and rn.get("scanned") == fn + dout,
       "E4 面内例外不误伤：无条件内容下面内声明候选与纪律候选仍比对"
       "（comparable=2：a_conf/zz_disc）、判定 ACCEPT 不误报 BLINDSPOT；"
       "scanned＝面内＋面外纪律（收口轮①口径）",
       (rn.get("verdict"), rn.get("comparable"), rn.get("scanned")))


# ---------------------------------------------------------------- G6 收口轮缺口闭合
def g6_gapfix(fx):
    print("== G6 收口轮缺口闭合：面内例外（F1）＋面外残余（F2）＋口径（F3）＋结构保证（F4）==")
    # ---- F1 转正：非同源形态（条目 tags 置空＋盘面 discipline）落修前扫描面内 ----
    old1 = _clear_entry_tags(fx.gapface, "q_ns")
    try:
        r1 = S.check(fx.gapface, "删除生产数据", layer="knowledge", depth=0)
    finally:
        _restore_entry_tags(fx.gapface, "q_ns", old1)
    got1 = {str(c["with"]) for c in r1.get("conflicts") or [] if c.get("with")}
    ok("q_ns" in got1 and r1.get("verdict") == "REJECT",
       "F1 面内例外转正（非同源形态）：条目 tags 置空＋盘面 tags=[discipline]＋"
       "落修前扫描面内 ⇒ 无词面输入下仍检出 REJECT（收口轮①；变异⑥去面内"
       "例外即红）",
       (sorted(got1), r1.get("verdict")))

    # ---- F2 面外残余：与修前形态（legacy 重建）同判（不构成回归，已声明边界） ----
    old2 = _clear_entry_tags(fx.tail, "t_ns")
    drift = False
    try:
        r_new = S.check(fx.tail, "删除生产数据", layer="knowledge", depth=0)
        mod, raw_ns, src = _build_mutant(_LEGACY_REPLS)
        if mod is None:
            # 未变异上下文里重建失败＝锚点漂移（实现改了、变异表未同步）：
            # 记 drift 使本断言转红（fail-closed）；变异①下 _CUR_SRC 非空
            # （当前形态即修前形态）属预期回落，不算漂移。
            drift = _CUR_SRC is None
            r_old = r_new
        else:
            saved = _activate(mod, raw_ns, src)
            try:
                r_old = S.check(fx.tail, "删除生产数据", layer="knowledge",
                                depth=0)
            finally:
                _deactivate(saved)
    finally:
        _restore_entry_tags(fx.tail, "t_ns", old2)
    got_n = {str(c["with"]) for c in r_new.get("conflicts") or []
             if c.get("with")}
    got_o = {str(c["with"]) for c in r_old.get("conflicts") or []
             if c.get("with")}
    ok((not drift) and "t_ns" not in got_n and "t_ns" not in got_o
       and got_n == got_o,
       "F2 面外非同源残余：修后与修前形态同判（均不检出——修前亦检不出，"
       "不构成回归；预筛读条目快照、协作写者协议下同源），已声明边界"
       "（修前形态重建锚点漂移 ⇒ 本断言转红，fail-closed）",
       (sorted(got_n), sorted(got_o), "drift" if drift else "ok"))

    # ---- F3 无词面口径定点（收口轮②） ----
    fn, dout = _face_and_disc(fx.main, "knowledge")
    c3 = _CountGet(fx.main)
    r3 = S.check(c3, _CASES[1][2], layer="knowledge", depth=0)
    ok(r3.get("scanned") == fn + dout and r3.get("kept") == r3.get("scanned")
       and r3.get("truncated") is False and "hint" not in r3
       and c3.gets == r3.get("kept"),
       "F3 无词面口径定点：scanned＝面内候选＋面外纪律候选（独立重算 %d＋%d）、"
       "kept＝scanned、truncated=False、不附 hint、读盘＝kept" % (fn, dout),
       {k: r3.get(k) for k in ("scanned", "kept", "truncated")})

    # ---- F4 结构保证：面内候选逐位进入精比面（读盘 id 集合 ⊇ 面内集合） ----
    face_ids = _pre_face(fx.main, "knowledge")
    c4 = _CountGet(fx.main)
    S.check(c4, _CASES[1][2], layer="knowledge", depth=0)
    ok(bool(face_ids) and set(c4.ids) >= set(face_ids),
       "F4 结构保证：无词面输入下修前扫描面（%d 名）逐位进入精比面/读盘面"
       "——与「条目/盘面同源」无关的结构保证（收口轮①）" % len(face_ids),
       (len(set(c4.ids)), len(face_ids)))


_GROUPS = (g1_selection, g2_parity, g3_reads, g4_cost, g5_redlines, g6_gapfix)


def _run_groups(fx) -> list:
    """跑全部分组，返回失败标签列表（静默模式复用；单组异常记为 EXC 标签）。"""
    _PASS.clear()
    _FAIL.clear()
    for g in _GROUPS:
        try:
            g(fx)
        except Exception as e:                     # noqa: BLE001  变异可能炸——记标签不中断
            label = "EXC:%s:%s" % (g.__name__, type(e).__name__)
            _FAIL.append(label)
            print("  FAIL " + label + "  ← " + str(e)[:160])
    return list(_FAIL)


# ---------------------------------------------------------------- 定点变异表
# 每条 = (名字, [(旧源码, 新源码), ...], 预期打红条数)。
# 锚点缺失 ⇒ ANCHOR-MISS + 退出码 2（fail-closed）；预期条数不符 ⇒ 报红（「恰好」语义）。
# 预期值为 2026-10-03 实测校准（六处变异各自恰好命中、无空转断言；收口轮①
# 新增 ⑥「去掉修前扫描面例外」并把 ①–⑤ 的预期值按新增/改写断言重校）。
_LEGACY_REPLS = [
    ("    scan_face = [(t[3], t[4]) for t in rel]\n"
     "    scan_face += [(t[3], t[4]) for t in cand if t[2] and t[3] not in rel_ids]\n",
     "    scan_face = [(t[3], t[4]) for t in cand if t[2]]\n"),
]
_M2 = [
    ('"missing": missing, "scanned": scanned, "kept": kept,\n'
     '           "truncated": truncated, "comparable": comparable,\n',
     '"missing": missing, "scanned": scanned, "comparable": comparable,\n'),
    ('    if truncated:\n        rec["hint"] = _SCAN_HINT % (scanned, lim, kept)\n',
     '    pass  # 变异：去掉 hint 上报\n'),
]
_M3 = [
    ("        if no_terms and not disc and not in_before:\n            continue\n",
     "        if not disc:\n            continue\n"),
]
#: 收口轮①的判别力钉：去掉面内例外（回到首轮形态）——F1/F3 断言必红。
_M6 = [
    ("        if no_terms and not disc and not in_before:\n            continue\n",
     "        if no_terms and not disc:\n            continue\n"),
]

#: 变异表完整性自检的编号钉（收口轮增补，对齐姊妹守卫 test_mode_parity /
#: test_autonomy_modes）：表长/编号与其不一致 ⇒ TABLE-GAPS + fail-closed 退出码 2。
_MUTATION_PINS = ("①", "②", "③", "④", "⑤", "⑥")


# 生效条件：entries 为形如 _MUTATIONS 的序列（(名字, 替换式, 预期红项数)，名字以编号打头）或缺省（取本模块 _MUTATIONS）时，按 _MUTATION_PINS 逐位核验长度与编号（缺/重复/顺序错位），返回缺口说明列表（空=完好）；只判「表被删改」，不判锚点漂移（后者归 _build_mutant 的 ANCHOR-MISS）。
def _mutation_table_gaps(entries=None):
    """变异表完整性自检（收口轮增补）：防「删条目/改名/重排」静默降级。

    由来（第一轮复核 uncovered 第 3 条）：内存删除一条变异（⑥）时 rc=0 不转红
    ——其余变异覆盖了其标签，删条目无人察觉；姊妹守卫 test_mode_parity /
    test_autonomy_modes 均有防误删自检，本守卫原缺。本判据把它变成机械铆钉：
    表长/编号与 `_MUTATION_PINS` 不一致 ⇒ 入口处打印 TABLE-GAPS 并
    **fail-closed 退出码 2**（三个入口 main / _branch_baseline / _legacy_baseline
    同层接入）。判别力自证（可复跑，见 docstring「防误删自检」节）：
    `G._MUTATIONS = G._MUTATIONS[:-1]` 后调本函数必报缺口。
    """
    es = _MUTATIONS if entries is None else entries
    gaps = []
    if len(es) != len(_MUTATION_PINS):
        gaps.append("len:%d≠%d" % (len(es), len(_MUTATION_PINS)))
    for i, (e, pid) in enumerate(zip(es, _MUTATION_PINS)):
        if not str(e[0]).startswith(pid):
            gaps.append("序%d 编号不符: %r ≠ %s…" % (i, str(e[0])[:12], pid))
    seen = []
    for e in es:
        for pid in _MUTATION_PINS:
            if str(e[0]).startswith(pid) and pid not in seen:
                seen.append(pid)
    for pid in _MUTATION_PINS:
        if pid not in seen:
            gaps.append("缺: %s" % pid)
    return gaps


_MUTATIONS = (
    ("①选面回索引序截断（修前形态）", _LEGACY_REPLS, 8),
    ("②去掉 truncated/kept 上报与 hint", _M2, 11),
    ("③预筛把真冲突候选剔掉（假阴性）", _M3, 19),
    ("④MAX_SCAN 数值偷调大（契约禁止面）",
     [("MAX_SCAN = 200", "MAX_SCAN = 2000")], 10),
    ("⑤剔除档失效（预筛退化，读盘面回到全候选）",
     [("        if no_terms and not disc and not in_before:\n            continue\n",
       "        if False:\n            continue\n")], 4),
    ("⑥去掉修前扫描面例外（收口轮①面内例外失效）", _M6, 5),
)


def _build_mutant(replacements):
    """在**运行时源码**上做替换并 exec 成模块命名空间。

    返回 (attr_ns, raw_ns, src)；锚点缺失返回 (None, None, None)。
    """
    src = _CUR_SRC if _CUR_SRC is not None else inspect.getsource(_cons)
    for old, new in replacements:
        if old not in src:
            return None, None, None
        src = src.replace(old, new)
    ns = {"__name__": "md_cg.consistency_mutant", "__package__": "md_cg",
          "__file__": getattr(_cons, "__file__", "<consistency>")}
    exec(compile(src, "<consistency-mutant>", "exec"), ns)   # noqa: S102  测试内变异自证
    return types.SimpleNamespace(**ns), ns, src


def _activate(mod, raw_ns, src):
    """把变异体的可调用面临时挂上真源模块（mdcos/mcp_server 经模块属性取用）。"""
    global S, _CUR_SRC
    saved = {}
    for k in list(_cons.__dict__):
        if k.startswith("__") or k not in raw_ns:
            continue
        saved[k] = _cons.__dict__[k]
        setattr(_cons, k, raw_ns[k])
    S = mod
    _CUR_SRC = src
    return saved


def _deactivate(saved):
    global S, _CUR_SRC
    for k, v in saved.items():
        setattr(_cons, k, v)
    S = _cons
    _CUR_SRC = None


def _branch_baseline(fx) -> int:
    print("!! 定点变异自证：逐处变异，断言须**恰好**打红预期条数；锚点漂移=ANCHOR-MISS+退出码 2\n")
    gaps = _mutation_table_gaps()
    if gaps:
        print("  TABLE-GAPS —— 变异表完整性自检未过（防误删）：%s" % "、".join(gaps))
        return 2
    # 锚点预检（fail-closed，收口轮①补）：修前形态锚点必须能在**当前源码**上重建
    # ——否则是「实现改了、变异表未同步」的锚点漂移：若不做预检，干净基线的
    # g2 会先把它吞成 B2 红（rc=1）而非 ANCHOR-MISS（rc=2），漂移被误报为
    # 「修复无效」。故先于一切断言直接判漂移。
    if _build_mutant(_LEGACY_REPLS)[0] is None:
        print("  ANCHOR-MISS 修前形态重建锚点（_LEGACY_REPLS）——实现改了却没同步变异表")
        return 2
    with _quiet():
        clean_red = _run_groups(fx)
    all_labels = set(_PASS) | set(_FAIL)
    if clean_red:
        print("  未变异基线即失败：%s" % clean_red)
        return 1
    print("  未变异基线：%d 条断言全绿" % len(all_labels))
    reddened = set()
    bad = []
    for name, repls, expect in _MUTATIONS:
        mod, raw_ns, src = _build_mutant(repls)
        if mod is None:
            print("  ANCHOR-MISS %s —— 变异锚点漂移（实现改了却没同步 _MUTATIONS）" % name)
            return 2
        saved = _activate(mod, raw_ns, src)
        try:
            with _quiet():
                reds = _run_groups(fx)
        finally:
            _deactivate(saved)
        reddened |= set(reds)
        hit = len(reds) == expect
        print("  变异「%s」→ 打红 %d 条（预期 %d）%s"
              % (name, len(reds), expect, "OK" if hit else "**不符**"))
        if not hit:
            bad.append("%s：红 %d ≠ 预期 %d" % (name, len(reds), expect))
            for r in sorted(reds):
                print("      red: " + r)
    never = sorted(all_labels - reddened)
    if never:
        print("  **空转断言（无任何变异能打红）**：%s" % "、".join(never))
        bad.append("空转断言 %d 条" % len(never))
    print("\n判别力自证：%s" % ("PASS（六处变异各自恰好命中，且无空转断言）"
                             if not bad else "FAIL —— " + "；".join(bad)))
    return 0 if not bad else 1


def _legacy_baseline(fx) -> int:
    print("!! 修前形态重建（索引序前 limit 选面）：核心断言应当转红\n")
    gaps = _mutation_table_gaps()
    if gaps:
        print("  TABLE-GAPS —— 变异表完整性自检未过（防误删）：%s" % "、".join(gaps))
        return 2
    mod, raw_ns, src = _build_mutant(_LEGACY_REPLS)
    if mod is None:
        print("  ANCHOR-MISS —— 修前形态重建的锚点漂移")
        return 2
    saved = _activate(mod, raw_ns, src)
    try:
        with _quiet():
            reds = _run_groups(fx)
    finally:
        _deactivate(saved)
    print("  修前形态下打红 %d 条：%s" % (len(reds), "、".join(sorted(reds))))
    core = {l for l in reds
            if l.startswith("A1 ") or l.startswith("B5 ") or l.startswith("B2 ")}
    miss = {"A1/B2/B5（选面与对拍的核心断言）"} if len(core) < 3 else set()
    print("\n修前形态判定：%s" % ("PASS（核心断言转红——本守卫抓得住 cons200 本身）"
                              if not miss else "FAIL —— 核心断言未转红：%s" % miss))
    return 0 if not miss else 1


def main() -> int:
    gaps = _mutation_table_gaps()
    if gaps:
        print("  TABLE-GAPS —— 变异表完整性自检未过（防误删）：%s" % "、".join(gaps))
        print("  fail-closed 退出码 2（对齐姊妹守卫防误删自检；复现：内存删 "
              "_MUTATIONS 一条后调本入口）")
        return 2
    fx = _Fixtures()
    try:
        if "--branch-baseline" in sys.argv:
            return _branch_baseline(fx)
        if "--legacy-baseline" in sys.argv:
            return _legacy_baseline(fx)
        _run_groups(fx)
    finally:
        fx.close()
    print("\ncons200 守卫：%d 通过，%d 失败" % (len(_PASS), len(_FAIL)))
    return 0 if not _FAIL else 1


if __name__ == "__main__":
    sys.exit(main())
