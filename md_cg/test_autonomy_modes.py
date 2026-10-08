# -*- coding: utf-8 -*-
"""md_cg · 三档自治「档位单一入口」守卫（设计 v0.2 §三/§四/§五 · 批次②）

覆盖（设计 §十一 验收判据在本批的落点）：
  · **逐格矩阵**（3 档 × 5 动作类 A/B/C/D/E）＋ 缺省档 = confirm（裁定①）；
  · 非法 env 值 fail-closed（报错 + hint 列合法值，**不**静默降级）；
  · plan 档最小语义：无计划时「须命中计划步骤」的 A/B/E 一律 forbid
    （计划输入面待后续批次；硬约束③ 计划外零变更）；
  · **B/C/D 出单**（三条热路径各一：写链覆写 C / 遗忘与限流合并 B / 工具面删除 D）
    —— 出单且**不落盘**，载荷含动作类·目标·后像·理由；
  · **accept 执行**（B/C/D 三种动作各一）＋ **reject 不执行**（原样留痕）；
  · edit/merge/noop 对变更单 fail-closed（不静默当已处理）；
  · 幂等：同（动作类+目标+后像）不长第二条；不同目标**不撞键**；
  · 存量兼容：旧条目无 `kind` 键一律视为 proposal（零迁移），accept 路径逐位不变；
  · **不动面对拍**（设计 §十一）：
      ① full 档下闸门对全部动作类返回 allow ⇒ 与改动前**同一条链**（构造性等价
         ——本基线**不绑 git HEAD**，本仓已有两次教训）；
      ② confirm 档下 A 新增 / E 权重 的动作面读数与 full 档**逐位相等**；
      ③ 库层（`MdCG.add` / `_write_node` / `MdCGOS.forget`）与合并原语
         （`forgetting.reinforce` / `writelimit.converge_into`）源码里**不得**出现
         档位判据——「直调库层不接线」是 accept 执行桥「越过确认判定」的机制前提。

**补强批次（2026-10-02）新增 I/J 两组**（独立复核三条未收口 + 容器栈一门禁红）：
  · I 组 **gated 面**（`remember_gated` 的 ACCEPT 分支 = 插件主写入通道）：
      - C 覆写（既有 node_id）：confirm/plan 档出变更单且不落盘、full 档照旧直落；
        资格在先——受保护节点覆写在 `write_qualify` 处当场拦（不静默入队）；
      - A 新增（node_id 不存在）：confirm/full 档**逐位零变化**（返回体与落盘节点
        都对拍），plan 档 fail-closed（`autonomy_forbidden`，带 hint）；
      - 链面（`op=write` + `gated=true`，`_gate_gated`）与 MCP 工具面
        （`mdcg_remember(gated=true)`）同判据——插件主通道不再旁路确认档；
      - 执行桥 C：目标在 accept 前消失 ⇒ `target_missing` 且**不重建**节点
        （对照片：目标在位时照旧执行）；
  · J 组 **容器栈一 SHIM-MISS 修复面**：`test_policy_required_ccg` 的 `_SHIMS`
    登记（writepipe 档位闸的相对 import）+ 该腿 `--head-baseline` 整腿 PASS +
    **负对照**（子进程内把 `_SHIMS` 去掉 `autonomy_modes` ⇒ 必须 SHIM-MISS
    非零退出——J3 的绿不是空转）。

**批次③（2026-10-02）新增 K 组**（设计 §四 变更单三字段 · 本批扩展）：
  · K 组 **变更单字段完备**：载荷在（动作类/目标/后像/理由/primitive/meta）之上
    的 `before`（前像）/`impact`（影响面）/`rollback`（回滚命令）三键——
    提议时点恒在且占位（None/None/""）、**执行时点**补全（before 指向执行前一刻
    的盘面：第三方改动被保留）、impact 三面（边/索引/聚合行）齐备、
    rollback 为可执行命令串（含 `md_cg.rollback_cli` 与 pid）、decisions.jsonl
    的 `rec["mutation"]` 落盘。深度回滚演练见 `md_cg/test_mutation_rollback.py`。

**批次④（2026-10-02）新增 L 组**（设计 §六/§七 准入闸 · 本批扩展）：
  · L 组 **准入闸生效面**：`env MDCG_AUTONOMY=full` 而 R1–R4 读数不满足 ⇒
    `settle()` 的实际生效档位回落 confirm 且 `alerts` 逐条报「缺哪条读数」
    （不静默降级）；full+满足 ⇒ full（与改动前逐位一致）；plan/confirm
    不受读数影响（零 IO 零告警）；非法 env 仍 fail-closed；未结算 = 旧行为
    （对拍）；读数缓存 TTL 内不重扫（「不得让每次 decide 都全库扫描」）；
    只读（结算前后库指纹逐位相同）。四条读数本身的深度判据（门槛边界 /
    窗口边界 3 天·30 天）见独立守卫 `md_cg/test_autonomy_admission.py`。

**收官批次（步骤⑤，2026-10-03）新增 M 组**（设计 §十三.5 步骤⑤ / §十一 验收）：
  · M 组 **覆盖矩阵未覆盖格补缺**——（a）plan 档热路径四面：写链 C 覆写 /
    gated 面 B 合并（MERGE 落点）/ 限流闸 CONVERGE 落点 / 工具面 D 删除
    （此前 plan 档只有 decide 级判据与 gated A 新增）；（b）**E 分数类在档位面**
    的行为读数。
    confirm/full 两档的 A/E 逐位对拍、与旧基线的 `git archive` oracle 对拍、
    端到端回滚演练（跨写链/插件面/执行桥/回滚 CLI）在独立守卫
    `md_cg/test_mode_parity.py`（收官批次另立；覆盖矩阵见收官报告）。

**补强批次（v1.2，2026-10-03）扩展 M 组**（独立复核 DEFER 的解除项 U1/U2 ＋ E 面接线）：
  · **M1e 直写面三档**（U1）：`mdcg_remember` **非 gated 直写分支**
    （`mcp_server.py:3373` 的自注「热写入路径的第二落点」）——plan/confirm 两档
    C 覆写**出单且不落盘**、full 档**直落**（此前该分支两档均无行为断言，复核
    V4' 注入 0 红存活）；
  · **M2 按标题意图重编码**：E 面**已接线**（`autonomy_modes.e_gate` 接在
    `weights.recalc` / `freshness.recalc` / `lifecycle.set_state` /
    `lifecycle.backfill` 的 apply 路径）⇒ 断言由「plan 与 confirm 逐位相等
    （现状钉、非背书）」重编码为「**plan 被拦（fail-closed、零写盘）＋
    confirm/full 逐位相等**」——**断言意图不变**（同 issue50-a 的 E1 先例：
    改的是判据编码，不是判据意图）。

定点变异自证（`--mutate`，与 `md_cg/test_neg_condition_hits.py` 同口径）：
表内每项 = (说明, 目标, 锚点原文, 替换文, 预期红项数)。锚点须**逐字**出现在目标
函数源码里；漂移即 ANCHOR-MISS（fail-closed，exit 2）。红项数与实测**逐一相符**
才算通过——不符即 FAIL（多红=断言越界、少红=该判据无判别力）。
目标形态三种：`("mod", 模块, 函数名)` / `("cls", 类, 方法名)` 走**源码替换 + exec**
重装；`("attr", 模块, 属性名)` 是**常量型变异**（把属性换成 `替换文` 求值出的新值，
用于 `_SHIMS` 这类「判据是数据不是函数体」的落点）。

**F1 收口（2026-10-03）——防误删自检**：变异表第③条（矩阵整表坍缩）曾在工作树
被删（仅剩注释；删除原因无留痕、不归因）；本批自 `git show HEAD:` 取回、按现行树
勘定锚点并实测校准红项数。新增**变异表完整性自检**（`_table_gaps` /
`_table_integrity_check`：编号无缺口 ＋ 表长与显式声明 `_MUTATION_IDS` 一致；
缺项 ⇒ fail-closed 退出码 2 并报缺口编号）——今后删条目即机械报错，不再靠人工
发现；「24 处」由此获得**自动核验载体**（每次运行 F1③ 测例自动核验）。自检的
判别力由合成源自证测例（F1①–④）＋ 内置判别力钉 `_SELFCHECK_MUTATION`
（剥掉自检开关 ⇒ 自证测例转红 **3**；不占表内编号——表长与声明恒等）钉死。
三级判据（注释被覆盖 / 序列缺编号 / 表长不符）分别对应删元组留注释、
注释与元组同删、编号齐而条目缺三种删法。

运行：
  python -X utf8 -m md_cg.test_autonomy_modes              # 正常跑
  python -X utf8 -m md_cg.test_autonomy_modes --mutate     # 定点变异自证

沙箱（硬约束）：一切读写都在 tempfile.mkdtemp 内（含 MDCG_AUX_ROOT / 主密钥——
crypto 在导入期求值 MASTER_FILE，故必须在任何 md_cg 子模块 import **之前**设好）；
跑完 rmtree。**绝不碰在役数据根**。档位 env 由夹具按需设置并在 finally 还原。
边界（如实，2026-10-02 补强批次实测）：`rmtree(..., ignore_errors=True)` 在 Windows 上
可能被未释放的锁句柄挡住，每次跑约残留 1 个**空壳**沙箱目录（实测内容仅
`<lib>/_index.json` 与 `.lock` 两个文件，全为合成库、零真实数据）；补强批次已清理
本会话累积的 30 个，清理逻辑未改（根因未定，留池登记）。
"""
from __future__ import annotations

import contextlib
import inspect
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time

# ---- 沙箱：必须在任何 md_cg 子模块 import 之前 ------------------------------
_SANDBOX = tempfile.mkdtemp(prefix="autonomy_modes_sandbox_")
os.environ["MDCG_AUX_ROOT"] = _SANDBOX
os.environ["MDCG_ROOT"] = os.path.join(_SANDBOX, "root")
os.environ["MDCG_MASTER_KEY"] = os.urandom(32).hex()
os.environ.pop("MDCG_TEST_LIVE_ROOT", None)
_OLD_POLICY = os.environ.pop("MDCG_POLICY_FILE", None)

from . import autonomy_modes, forgetting, writelimit, writepipe   # noqa: E402
from . import freshness                                            # noqa: E402
from . import weights                                              # noqa: E402
from . import lifecycle as _lc                                     # noqa: E402
from . import mcp_server                                           # noqa: E402
from . import nodefile as _nf                                      # noqa: E402
from . import mdcos                                                # noqa: E402
from . import test_policy_required_ccg as _tpc                      # noqa: E402
from .mdcos import MdCGOS, MdCGSecure                              # noqa: E402
from .mdcg import MdCG                                             # noqa: E402
from .security import Principal                                    # noqa: E402

#: 档位 env 键名——**不写字面量**：从真源表取（全仓唯一字面量落点在本模块之外的
#: autonomy_modes.AUTONOMY_ENV_KEYS，G 组把它 grep 钉死）。夹具因此不构成第二处
#: 字面量，守卫的 grep 判据得以保持严格。
_ENV_MODE = autonomy_modes.AUTONOMY_ENV_KEYS["mode"]

_PASS = []
_FAIL = []
_RUN = [0]


def ok(cond, msg, extra=""):
    (_PASS if cond else _FAIL).append(msg)
    print(("  PASS " if cond else "  FAIL ") + msg
          + (("  ← " + str(extra)) if (extra and not cond) else ""))


def _policy():
    """审计闸要一份可用规则库（required 命中即 ACCEPT，同 test_writepipe 口径）。"""
    path = os.path.join(_SANDBOX, "policy.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"forbidden": ["FORBIDDEN_WORD"], "required": ["PASSED"]}, f)
    os.environ["MDCG_POLICY_FILE"] = path
    return path


def _lib(tag="lib"):
    """独立合成库（每轮独立子根：变异模式连跑多轮，共用目录会读到上一轮盘面）。"""
    return MdCGOS(os.path.join(_SANDBOX, "%s_r%d" % (tag, _RUN[0])), autoflush=0)


@contextlib.contextmanager
def _mode(m):
    """按需设档位，退出还原（夹具专用；不在生产码里读/写档位）。"""
    old = os.environ.get(_ENV_MODE)
    os.environ[_ENV_MODE] = m
    try:
        yield m
    finally:
        if old is None:
            os.environ.pop(_ENV_MODE, None)
        else:
            os.environ[_ENV_MODE] = old


@contextlib.contextmanager
def _no_mode():
    """清掉档位 env（考「缺省 = confirm」）。"""
    old = os.environ.pop(_ENV_MODE, None)
    try:
        yield
    finally:
        if old is not None:
            os.environ[_ENV_MODE] = old


def _pipe():
    """新建默认链（档位闸是注册期绑定，故每组现建，变异才对写链生效）。"""
    return writepipe.install_default_gates(writepipe.WritePipeline())


#: 对拍要剔除的**时钟面/耗时面**键（两次运行必然不同，与档位无关——剔除不算
#: 放水：对拍的判据是「档位有没有改变行为」，不是「时间戳/耗时是否相同」）。
#: 收官批次（步骤⑤）追加三项，均为同一族：`batch`（strftime 派生的批号）、
#: `note`（文案里内嵌 batch 的提示句，与 batch 同源）、`elapsed_ms`
#: （运行耗时读数，性能面——M 组 E 分数类对拍用）。
_VOLATILE = ("t", "created_at", "last_access", "time_window", "last_merge_at",
             "batch", "note", "elapsed_ms")


def _strip(d):
    """递归剔除时钟面键，返回可逐位比较的结构。"""
    if isinstance(d, dict):
        return {k: _strip(v) for k, v in d.items() if k not in _VOLATILE}
    if isinstance(d, list):
        return [_strip(x) for x in d]
    return d


BODY = ("# 功能名：部署面端口约定\n"
        "# 生效条件：载体/位置：prod 集群；时间：2026-09-30 起；方法：部署清单核对；约束：无\n"
        "# 子功能：登记各服务监听端口\n"
        "# 执行：核对 manifest 的 ports 段\n"
        "# 验证方式：test\n"
        "# 不适用条件：无\n"
        "\n网关监听端口 8080/HTTP；管理面监听端口 8081/HTTP；"
        "指标面监听端口 %s/HTTP；日志面监听端口 9091/HTTP\n")
PLAIN = "PASSED 探针正文 %s"


# =============================================================== A 组：矩阵
def g_a():
    print("== A 组：裁决矩阵逐格（3 档 × 5 动作类）==")
    want = {
        "plan":    {"A": "forbid", "B": "forbid", "C": "confirm",
                    "D": "confirm", "E": "forbid"},      # 无计划 ⇒ 须计划步骤者 forbid
        "confirm": {"A": "allow", "B": "confirm", "C": "confirm",
                    "D": "confirm", "E": "allow"},       # 设计 §三 缺省列
        "full":    {"A": "allow", "B": "allow", "C": "allow",
                    "D": "allow", "E": "allow"},
    }
    for m in autonomy_modes.AUTONOMY_MODES:
        for a in autonomy_modes.ACTION_CLASSES:
            d = autonomy_modes.decide(a, mode_explicit=m)
            ok(d["decision"] == want[m][a] and d["mode"] == m
               and d["action"] == a,
               "A 矩阵格 %s×%s → %s" % (m, a, want[m][a]), d)
    # 矩阵真源 = MATRIX 表（逐格与上表同源，防「表改了判据没改」）
    for m in autonomy_modes.AUTONOMY_MODES:
        for a in autonomy_modes.ACTION_CLASSES:
            cell = autonomy_modes.MATRIX[m][a]
            ok(cell in (autonomy_modes.ALLOW, autonomy_modes.CONFIRM,
                        autonomy_modes.PLAN_STEP),
               "A 表内格 %s×%s 是合法格值（%s）" % (m, a, cell), cell)
    d = autonomy_modes.decide("B", mode_explicit="confirm")
    ok(bool(d["hint"]) and "变更单" in d["hint"],
       "A confirm 判定带可读 hint（出变更单 + 裁决入口）", d["hint"][:40])
    with _no_mode():
        ok(autonomy_modes.mode() == "confirm",
           "A 缺省档 = confirm（env 未设）", autonomy_modes.mode())
    ok(autonomy_modes.DEFAULT_MODE == "confirm"
       and autonomy_modes.AUTONOMY_ENV_DEFAULTS["mode"] == "confirm",
       "A 缺省真源 = confirm（表与具名常量同源）")
    with _mode("bogus"):
        try:
            autonomy_modes.mode()
            ok(False, "A 非法 env fail-closed（未报错）")
        except autonomy_modes.AutonomyModeError as e:
            ok("bogus" in str(e) and "plan" in str(e) and "confirm" in str(e)
               and "full" in str(e),
               "A 非法 env fail-closed：报错 + hint 列合法值", str(e)[:50])
    with _mode("  FULL  "):
        ok(autonomy_modes.mode() == "full",
           "A 档位名去空白/大小写不敏感（归一后合法即生效）")
    # plan 档：有计划且命中 ⇒ allow；有计划未命中 ⇒ forbid（计划外零变更）
    d = autonomy_modes.decide("B", mode_explicit="plan", plan=["B", "A"])
    ok(d["decision"] == "allow", "A plan 档命中计划步骤 → allow", d)
    d = autonomy_modes.decide("A", mode_explicit="plan", plan={"steps": [{"action": "B"}]})
    ok(d["decision"] == "forbid" and "计划外零变更" in d["hint"],
       "A plan 档未命中计划步骤 → forbid（计划外零变更）", d)
    d = autonomy_modes.decide("A", mode_explicit="plan")
    ok(d["decision"] == "forbid" and "计划输入面待后续批次" in d["hint"],
       "A plan 档无计划 → forbid 且 hint 说明计划输入面待后续批次", d["hint"][:50])
    try:
        autonomy_modes.decide("Z", mode_explicit="confirm")
        ok(False, "A 未知动作类未拒")
    except ValueError:
        ok(True, "A 未知动作类 fail-closed（ValueError）")


# =============================================================== B 组：C 改写
def g_b():
    print("== B 组：写链 C 改写（cg(op=write) 同 id 覆写）==")
    _policy()
    pipe = _pipe()
    with _mode("confirm"):
        cg = _lib("c")
        nid = "c_b1"
        o1 = pipe.execute(cg, {"content_kind": "text",
                               "content": PLAIN % "初版", "layer": "knowledge",
                               "node_id": nid})
        ok(o1.get("committed") is True, "B 首次写入（A 新增）直落不拦", o1)
        o2 = pipe.execute(cg, {"content_kind": "text",
                               "content": PLAIN % "改写版", "layer": "knowledge",
                               "node_id": nid})
        ok(o2.get("moved_to") == "review_queue"
           and o2.get("committed") is False and bool(o2.get("pid")),
           "B C 改写出变更单且不落盘", {k: o2.get(k) for k in
                                        ("moved_to", "committed", "pid")})
        ok("初版" in (cg.get(nid) or {}).get("content", "")
           and "改写版" not in (cg.get(nid) or {}).get("content", ""),
           "B 出单时目标节点正文**未被改写**（逐字比对）")
        pay = o2.get("mutation") or {}
        ok(pay.get("action") == "C" and pay.get("target") == nid
           and pay.get("after") == (PLAIN % "改写版")
           and bool(pay.get("reason")) and pay.get("primitive") == "add",
           "B 载荷齐备：动作类 C · 目标 id · 后像正文 · 理由 · 复现原语", pay)
        rec = [r for r in cg.review_list() if r.get("pid") == (o2.get("pid") or "")]
        ok(len(rec) == 1 and autonomy_modes.order_kind(rec[0]) == "mutation"
           and rec[0].get("id") == nid,
           "B 队列条目 kind=mutation 且 id=目标节点（既有读取面可见）",
           rec[0] if rec else None)
        r = cg.review_decide(o2.get("pid") or "", "accept", reason="守卫")
        ok(r.get("ok") is True, "B accept 返回 ok", r)
        ok("改写版" in (cg.get(nid) or {}).get("content", ""),
           "B accept **执行**改写：覆写落盘走既有 add")
        # 前像式核对：accept 前盘面 == 旧正文（内容级「前像」由出单不落盘保证）
        ok((cg.get(nid) or {}).get("content", "").count("改写版") == 1,
           "B 改写只发生一次（幂等落盘）")
        # full 档：直落（对拍锚：与改动前同一条路）
        with _mode("full"):
            o3 = pipe.execute(cg, {"content_kind": "text",
                                   "content": PLAIN % "完全访问版",
                                   "layer": "knowledge", "node_id": nid})
        ok(o3.get("committed") is True and o3.get("moved_to") is None
           and "完全访问版" in (cg.get(nid) or {}).get("content", ""),
           "B full 档 C 改写直落（无单、无 extra 键）", o3)
        # plan 档：A 新增 fail-closed（写链面）
        with _mode("plan"):
            o4 = pipe.execute(cg, {"content_kind": "text",
                                   "content": PLAIN % "计划档", "layer": "knowledge",
                                   "node_id": "c_plan_new"})
        ok(o4.get("moved_to") == "autonomy_forbidden"
           and o4.get("committed") is False
           and cg.get("c_plan_new") is None,
           "B plan 档 A 新增 fail-closed（未落盘、未出单）", o4)
        cg.close()


# =============================================================== C 组：B 合并
def g_c():
    print("== C 组：B 合并（遗忘闸 MERGE + 限流闸 CONVERGE 两落点）==")
    with _mode("confirm"):
        cg = _lib("m")
        cg.add("m_t1", BODY % "9090", layer="knowledge", verification_basis="test")
        cg.flush()
        r1 = cg.remember_gated("m_n1", BODY % "9595", layer="knowledge")
        ok(r1.get("verdict") == "CONFIRM" and r1.get("moved_to") == "review_queue"
           and bool(r1.get("pid")),
           "C 遗忘闸 MERGE → 出变更单且不合并", {k: r1.get(k) for k in
                                            ("verdict", "moved_to", "pid")})
        t = cg.get("m_t1")
        ok("9595" not in (t or {}).get("content", "")
           and not ((t or {}).get("frontmatter") or {}).get("merge_count"),
           "C 出单时目标未被合并（新值与 merge_count 都不动）")
        pay = r1.get("mutation") or {}
        ok(pay.get("action") == "B" and pay.get("target") == "m_t1"
           and pay.get("after") == (BODY % "9595")
           and pay.get("primitive") == "reinforce",
           "C 载荷：动作类 B · 目标 · 后像 · 原语 reinforce", pay)
        r = cg.review_decide(r1.get("pid") or "", "accept", reason="守卫")
        ok(r.get("ok") is True, "C accept 返回 ok", r)
        t = cg.get("m_t1")
        ok("9595" in (t or {}).get("content", "")
           and ((t or {}).get("frontmatter") or {}).get("merge_count") == 1,
           "C accept **执行**合并：reinforce 原语落盘（新值可检索）")
        # reject 不执行
        r2 = cg.remember_gated("m_n2", BODY % "7070", layer="knowledge")
        r = cg.review_decide(r2.get("pid") or "", "reject", reason="守卫：不执行")
        ok(r.get("ok") is True and "7070" not in
           (cg.get("m_t1") or {}).get("content", ""),
           "C reject **不执行**（原样留痕、目标未被改）")
        # edit 对变更单 fail-closed
        r3 = cg.remember_gated("m_n3", BODY % "6060", layer="knowledge")
        r = cg.review_decide(r3.get("pid") or "", "edit", edits={"content": "x"}, reason="守卫")
        ok(r.get("ok") is False and r.get("error") == "mutation_decision_unsupported"
           and bool(r.get("hint")),
           "C edit 对变更单 fail-closed（带 hint，不静默当已处理）", r)
        ok(any(x.get("pid") == (r3.get("pid") or "") for x in cg.review_list()),
           "C 未被自理的变更单仍在 pending（未被静默关闭）")
        # CONVERGE 落点（限流闸 → converge_into）
        r4 = cg.remember_gated("m_x1", "批次107 收官：指标面 9090 正常",
                               layer="contextual")
        r5 = cg.remember_gated("m_x2", "批次108 收官：指标面 9595 正常",
                               layer="contextual")
        ok(r4.get("verdict") == "ACCEPT", "C CONVERGE 前置：首条 ACCEPT", r4.get("verdict"))
        ok(r5.get("verdict") == "CONFIRM"
           and (r5.get("mutation") or {}).get("primitive") == "converge_into"
           and (r5.get("mutation") or {}).get("target") == "m_x1",
           "C 限流闸 CONVERGE → 出变更单（原语 converge_into、目标=既有节点）",
           r5.get("mutation"))
        ok("9595" not in (cg.get("m_x1") or {}).get("content", ""),
           "C CONVERGE 出单时未并入")
        r = cg.review_decide(r5.get("pid") or "", "accept", reason="守卫")
        ok(r.get("ok") is True and "9595" in (cg.get("m_x1") or {}).get("content", ""),
           "C accept **执行** CONVERGE：converge_into 落盘")
        cg.close()


# =============================================================== D 组：D 删除
def g_d():
    print("== D 组：D 删除（MCP 工具面 forget_gated）==")
    with _mode("confirm"):
        cg = _lib("d")
        cg.add("d_1", BODY % "9090", layer="knowledge", verification_basis="test")
        cg.add("d_prot", BODY % "8080", layer="self", verification_basis="test")
        cg.flush()
        r1 = cg.forget_gated("d_1", reason="守卫删除")
        ok(r1.get("ok") is True and r1.get("deleted") is False
           and r1.get("moved_to") == "review_queue" and bool(r1.get("pid")),
           "D 删除出变更单且不软删（deleted=False 明示）",
           {k: r1.get(k) for k in ("ok", "deleted", "moved_to", "pid")})
        ok(cg.get("d_1") is not None, "D 出单后节点原样在位")
        pay = r1.get("mutation") or {}
        ok(pay.get("action") == "D" and pay.get("target") == "d_1"
           and pay.get("after") == "" and pay.get("primitive") == "forget",
           "D 载荷：动作类 D · 目标 · 后像为空 · 原语 forget", pay)
        r = cg.review_decide(r1.get("pid") or "", "accept", reason="守卫")
        ok(r.get("ok") is True and cg.get("d_1") is None,
           "D accept **执行**软删（trash + 删除清单，既有 forget 原语）")
        # 资格闸先于档位（纯加严）：受保护节点在资格闸就被拦，出单都轮不到
        try:
            cg.forget_gated("d_prot", reason="受保护")
            ok(False, "D 受保护节点未被拦（纯加严被破坏）")
        except Exception as exc:                          # noqa: BLE001
            ok(type(exc).__name__ in ("ProtectionError", "AccessDenied"),
               "D 受保护节点在资格闸就被拦（档位不参与资格判定、不放宽）",
               type(exc).__name__)
        ok(cg.get("d_prot") is not None, "D 受保护节点仍在位")
        # 资格闸不过时不出单（not_found 原样返回）
        r3 = cg.forget_gated("d_ghost", reason="不存在")
        ok(r3 == {"ok": False, "error": "not_found"},
           "D 资格闸未过 → 原样返回 not_found（不出单）", r3)
        cg.flush()
        # 库层不接线：直调 forget 不受档位影响（脚本通道现状逐位不变）
        cg.add("d_2", BODY % "7070", layer="knowledge", verification_basis="test")
        cg.flush()
        dr = cg.forget("d_2", reason="库层直调")
        ok(dr.get("ok") is True and bool(dr.get("tombstone"))
           and cg.get("d_2") is None,
           "D 库层 forget 直调不受档位影响（软删照旧成功）", dr)
        cg.close()
    # 安全层管理闸在**档位路径**同样生效（本批实修：档位路径曾直调 _forget_apply，
    # 把 `MdCGSecure.forget` 的 can_admin 要求整个跳过——MDCG_CAN_ADMIN=0 的身份
    # 经 mdcg_forget 能把节点删掉；test_p2_mcp §9 实测抓到，见报告）。
    cg_ro = MdCGSecure(os.path.join(_SANDBOX, "ro_r%d" % _RUN[0]),
                       principal=Principal(tenant="default", actor="ro",
                                           role="reader", can_write=True,
                                           can_admin=False))
    with _mode("confirm"):
        cg_ro.add("ro_1", BODY % "4040", layer="knowledge",
                  verification_basis="test")
        cg_ro.flush()
        try:
            cg_ro.forget_gated("ro_1", reason="守卫：无 can_admin")
            ok(False, "D 无 can_admin 的身份经档位路径删除被拒（未报错）")
        except Exception as exc:        # noqa: BLE001
            ok(type(exc).__name__ == "AccessDenied"
               and cg_ro.get("ro_1") is not None,
               "D 无 can_admin 的身份经档位路径删除被拒（AccessDenied，节点在位）",
               type(exc).__name__)
        try:
            cg_ro.forget("ro_1", reason="守卫：库层同拒")
            ok(False, "D 无 can_admin 的身份直调库层 forget 同样被拒")
        except Exception as exc:        # noqa: BLE001
            ok(type(exc).__name__ == "AccessDenied",
               "D 无 can_admin 的身份直调库层 forget 同样被拒（两入口同一闸）",
               type(exc).__name__)
    cg_ro.close()


# =============================================================== E 组：幂等
def g_e():
    print("== E 组：变更单幂等（同动作+目标+后像不长第二条）==")
    with _mode("confirm"):
        cg = _lib("idem")
        cg.add("e_1", BODY % "9090", layer="knowledge", verification_basis="test")
        cg.add("e_2", BODY % "8080", layer="knowledge", verification_basis="test")
        cg.flush()
        k1 = autonomy_modes.mutation_dedup_key("C", "e_1", "X")
        ok(k1 == autonomy_modes.mutation_dedup_key("C", "e_1", "X")
           and k1 != autonomy_modes.mutation_dedup_key("C", "e_2", "X")
           and k1 != autonomy_modes.mutation_dedup_key("B", "e_1", "X")
           and k1 != autonomy_modes.mutation_dedup_key("C", "e_1", "Y"),
           "E 幂等键：同三元恒同、动作/目标/后像任一不同即不同")
        p1 = autonomy_modes.propose_mutation(
            cg, "C", "e_1", after="X", reason="幂等探针", info=True)
        p2 = autonomy_modes.propose_mutation(
            cg, "C", "e_1", after="X", reason="幂等探针", info=True)
        ok(p2.get("dedup") is True and p2.get("pid") == p1.get("pid"),
           "E 同（动作+目标+后像）重复提议不长第二条（幂等返回既有 pid）", p2)
        p3 = autonomy_modes.propose_mutation(
            cg, "C", "e_2", after="X", reason="幂等探针", info=True)
        ok(p3.get("dedup") is not True and p3.get("pid") != p1.get("pid"),
           "E 换目标即长第二条（内容签名不带目标 ⇒ 必须覆盖对账键）", p3)
        pend = [r for r in cg.review_list()
                if autonomy_modes.order_kind(r) == "mutation"]
        ok(len(pend) == 2, "E 三次提议（2 唯一键）→ 队列恰 2 条", len(pend))
        cg.close()


# =============================================================== F 组：存量兼容
def g_f():
    print("== F 组：存量兼容（缺 kind = proposal，接受路径逐位不变）==")
    with _mode("confirm"):
        cg = _lib("legacy")
        rec = {"pid": "prop_legacy_1", "id": "f_1", "content": "老提案正文",
               "layer": "knowledge", "tags": [], "payload_hash": "h1",
               "extra": {}}
        ok(autonomy_modes.order_kind(rec) == "proposal"
           and autonomy_modes.mutation_view(rec) is None,
           "F 缺 kind 键 ⇒ proposal（零迁移）", autonomy_modes.order_kind(rec))
        pr = cg.propose("f_1", "老提案正文", layer="knowledge", info=True)
        item = [r for r in cg.review_list() if r.get("pid") == pr["pid"]][0]
        ok("kind" not in item,
           "F 普通提案的 rec 形状零变化（不落 kind 键）", sorted(item))
        r = cg.review_decide(pr["pid"], "accept", reason="守卫")
        ok(r.get("ok") is True and r.get("node_id") == "f_1"
           and "老提案正文" in (cg.get("f_1") or {}).get("content", ""),
           "F proposal 的 accept 原路径逐位不变（落盘成功）", r)
        # noop/merge 对 proposal 亦不变
        pr2 = cg.propose("f_2", "老提案正文二", layer="knowledge", info=True)
        r = cg.review_decide(pr2["pid"], "noop", reason="守卫")
        ok(r.get("ok") is True and cg.get("f_2") is None,
           "F proposal 的 noop 仍只留痕不落盘", r)
        cg.close()


# =============================================================== G 组：单点结构
def _repo_root():
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _tracked_rels():
    """git 追踪面（仓根相对 · posix 分隔）集合；git 不可用/非仓 ⇒ None（调用方降级）。

    G 组判据面须锚在**追踪面**而非文件系统面：本地工作树的 gitignore 产物
    （`.tmp/` 草稿、`_md_cg_p*/` 运行库、构建残留）不在 CI 干净克隆里，用文件
    系统面判定会让「本地红 / CI 绿」分裂（本件实证：`.tmp/` 下草稿曾被判为
    第二处档位 env 字面量）。`.tmp` 只是当前最大污染源，故按「是否被 git 追踪」
    这个**性质**判，不逐个硬编码排除目录。
    """
    try:
        proc = subprocess.run(["git", "-C", _repo_root(), "ls-files", "-z"],
                              capture_output=True, check=True)
    except Exception:                                  # noqa: BLE001 —— 兜底见下
        return None
    return {p.replace("\\", "/") for p in
            proc.stdout.decode("utf-8", "replace").split("\0") if p}


def _py_files():
    """全仓 .py 的判据面 = 文件系统走查 ∩ **git 追踪面**（非追踪件不入面）。

    降级（明示，非静默改语义）：git 不可用或非仓环境 ⇒ 退化为原文件系统走查，
    并打印 `[降级]` 一行——此时扫描面可能与 CI 干净克隆不一致，读数须按降级看待。
    """
    root = _repo_root()
    tracked = _tracked_rels()
    if tracked is None:
        print("  [降级] git 不可用：G 组扫描面退化为文件系统走查"
              "（可能与 CI 干净克隆不一致）")
    out = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames
                       if d not in (".git", "__pycache__", "node_modules",
                                    ".venv", "target", "lib")]
        for fn in filenames:
            if not fn.endswith(".py"):
                continue
            p = os.path.join(dirpath, fn)
            if tracked is not None:
                rel = os.path.relpath(p, root).replace("\\", "/")
                if rel not in tracked:
                    continue        # 非追踪件不入判据面（保留原目录排除语义）
            out.append(p)
    return out


def g_g():
    print("== G 组：单点结构（全仓只有 autonomy_modes 读档位 env）==")
    lit = '"%s"' % _ENV_MODE
    hits = []
    for p in _py_files():
        try:
            with open(p, encoding="utf-8") as f:
                src = f.read()
        except OSError:
            continue
        if lit in src or ("'%s'" % _ENV_MODE) in src:
            hits.append(os.path.relpath(p, _repo_root()).replace("\\", "/"))
    ok(hits == ["md_cg/autonomy_modes.py"],
       "G 全仓 .py 里带引号的档位 env 字面量只出现在唯一入口模块", hits)
    # 库层不接线（accept 执行桥「直越确认判定」的机制前提）
    for owner, name in ((MdCG, "add"), (MdCG, "_write_node"),
                        (MdCGOS, "forget")):
        src = inspect.getsource(getattr(owner, name))
        code = "\n".join(l for l in src.splitlines()
                         if not l.strip().startswith("#"))
        ok("autonomy_modes" not in code,
           "G 库层 %s.%s 不含档位判据（保持库层语义不变）"
           % (owner.__name__, name), [l for l in code.splitlines()
                                      if "autonomy_modes" in l])
    for mod, name in ((forgetting, "reinforce"), (writelimit, "converge_into")):
        src = inspect.getsource(getattr(mod, name))
        code = "\n".join(l for l in src.splitlines()
                         if not l.strip().startswith("#"))
        ok("autonomy_modes" not in code,
           "G 合并原语 %s.%s 不含档位判据（执行桥直调原语即越过判定）"
           % (mod.__name__, name))
    # 接线点仍在（防「档位不生效」的静态退化）
    wsrc = inspect.getsource(writepipe.install_default_gates)
    ok('"autonomy"' in wsrc or "'autonomy'" in wsrc,
       "G 写链默认链仍注册档位闸（链尾）")
    ok("_gate_autonomy" in inspect.getsource(writepipe)
       and "_autonomy_gate_merge" in inspect.getsource(mdcos),
       "G 档位闸的接线单点存在（写链 + 合并两落点）")
    ok("forget_gated" in inspect.getsource(mdcos)
       and "forget_gated" in open(
           os.path.join(_repo_root(), "md_cg", "mcp_server.py"),
           encoding="utf-8").read(),
       "G 删除档位路径（forget_gated）在库层与 MCP 工具面都在位")
    # 管理闸单点（本批实修：档位路径曾绕过 MdCGSecure 的 can_admin 要求）
    ok("def _forget_admin" in inspect.getsource(mdcos.MdCGSecure)
       and "self._forget_admin()" in inspect.getsource(mdcos.MdCGSecure.forget)
       and "self._forget_admin()"
       in inspect.getsource(mdcos.MdCGSecure.forget_gated),
       "G 管理闸单点：MdCGSecure 的 forget 与 forget_gated 都过 _forget_admin")


# =============================================================== H 组：不动面对拍
def g_h():
    print("== H 组：不动面对拍（full 档全动作 / confirm 档 A·E）==")
    for a in autonomy_modes.ACTION_CLASSES:
        d = autonomy_modes.decide(a, mode_explicit="full")
        ok(d["decision"] == "allow" and d["hint"] == "",
           "H full 档 %s → allow 且无 hint（闸放行 = 与改动前同一条链）" % a, d)
    for a in ("A", "E"):
        d = autonomy_modes.decide(a, mode_explicit="confirm")
        ok(d["decision"] == autonomy_modes.decide(a, mode_explicit="full")["decision"]
           and d["hint"] == "",
           "H confirm 档 %s 的动作面读数与 full 档逐位相等（不阻塞）" % a, d)
    _policy()
    runs = {}
    for m in ("confirm", "full"):
        with _mode(m):
            cg = _lib("pair_" + m)
            pipe = _pipe()
            out = pipe.execute(cg, {"content_kind": "text",
                                    "content": PLAIN % "对拍", "layer": "knowledge",
                                    "node_id": "h_1"})
            node = cg.get("h_1") or {}
            runs[m] = (out, node)
            cg.close()
    oc, of = _strip(runs["confirm"][0]), _strip(runs["full"][0])
    ok(oc == of, "H A 新增：confirm 档返回体与 full 档**逐位相等**（时钟面除外）",
       {"confirm": oc, "full": of})
    nc, nf = _strip(runs["confirm"][1]), _strip(runs["full"][1])
    ok(nc == nf, "H A 新增：两档落盘节点（含正文与 fm，时钟面除外）逐位相等",
       {"confirm": nc, "full": nf})
    # full 档三动作真执行（与改动前同）：C 覆写 / B 合并 / D 软删
    with _mode("full"):
        cg = _lib("full_drive")
        cg.add("f_a", BODY % "9090", layer="knowledge", verification_basis="test")
        cg.flush()
        rc = cg.remember_gated("f_b", BODY % "9595", layer="knowledge")
        ok(rc.get("verdict") == "MERGE"
           and "9595" in (cg.get("f_a") or {}).get("content", ""),
           "H full 档 B 合并直落（无单、verdict=MERGE 与改动前同）",
           rc.get("verdict"))
        dd = cg.forget_gated("f_a", reason="full 档")
        ok(dd.get("ok") is True and dd.get("deleted") is not False
           and dd.get("moved_to") is None and dd.get("tombstone"),
           "H full 档 D 删除直删（无单、带 tombstone 与改动前同）", dd)
        ok(len([r for r in cg.review_list()
                if autonomy_modes.order_kind(r) == "mutation"]) == 0,
           "H full 档全程零变更单（队列无 mutation 条目）")
        cg.close()


# =============================================================== I 组：gated 面
#: gated 面覆写探针正文：与库内既有正文**同族但不同值**（`assess` 的 redundancy
#: 对同 id 自排除 ⇒ 判 ACCEPT 且带 overwrite 读数），故能走到 ACCEPT 分支的档位判定。
def _mut_entries(recs):
    return [x for x in recs if autonomy_modes.order_kind(x) == "mutation"]


def _submit(script, args, drop_shim=False):
    """子进程跑 `test_policy_required_ccg` 整腿（隔离：其 sys.path/sys.modules 污染不外溢）。

    drop_shim=True = 该处判据的**定点变异**，且必须放在「读文件的那一侧」才生效：
    在子进程内先把 `_SHIMS` 去掉 `autonomy_modes`（＝未登记的形态），该腿必须
    SHIM-MISS 非零退出——正/负对照成对，证明 J3 的绿不是空转。
    """
    import subprocess
    code = ("import sys; from md_cg import test_policy_required_ccg as t; "
            + ('t._SHIMS = tuple(x for x in t._SHIMS'
               ' if x != "autonomy_modes"); ' if drop_shim else "")
            + "sys.exit(t.main())")
    p = subprocess.run([sys.executable, "-X", "utf8", "-c", code] + list(args),
                       capture_output=True, text=True, encoding="utf-8",
                       errors="replace", cwd=_repo_root(),
                       env=dict(os.environ, PYTHONUTF8="1"))
    return {"rc": p.returncode, "out": (p.stdout or "") + (p.stderr or "")}


def g_i():
    print("== I 组：gated 面 C 改写 / A 新增 + 执行桥 C 目标消失（补强批次）==")
    # 每个场景**独立合成库**：遗忘闸的 redundancy 是全库比对（只排除本次 node_id），
    # 同库多节点会把「新写入」判成 MERGE/DEFER 而走不到 ACCEPT 分支的档位判定——
    # 场景隔离是让每条断言确实命中目标分支的前提（不是放水）。
    _policy()

    # ---- ① confirm 档：C 覆写出单且不落盘 ----
    with _mode("confirm"):
        cg = _lib("gated_c")
        cg.add("i_1", BODY % "9090", layer="knowledge", verification_basis="test")
        cg.flush()
        r1 = cg.remember_gated("i_1", BODY % "9595", layer="knowledge")
        ok(r1.get("verdict") == "CONFIRM"
           and r1.get("moved_to") == "review_queue"
           and r1.get("committed") is False and bool(r1.get("pid")),
           "I gated C 覆写（confirm 档）出变更单且明示未落盘（moved_to=review_queue）",
           {k: r1.get(k) for k in ("verdict", "ok", "committed", "moved_to", "pid")})
        t = cg.get("i_1") or {}
        ok("9090" in t.get("content", "") and "9595" not in t.get("content", ""),
           "I gated C 出单时目标节点正文**未被覆写**（逐字比对）")
        pay = r1.get("mutation") or {}
        ok(pay.get("action") == "C" and pay.get("target") == "i_1"
           and pay.get("after") == (BODY % "9595")
           and pay.get("primitive") == "add" and bool(pay.get("reason")),
           "I gated C 载荷齐备：动作类 C · 目标 · 后像 · 理由 · 复现原语 add", pay)
        rec = [x for x in cg.review_list()
               if x.get("pid") == (r1.get("pid") or "")]
        ok(len(rec) == 1 and autonomy_modes.order_kind(rec[0]) == "mutation"
           and rec[0].get("id") == "i_1",
           "I gated C 队列条目 kind=mutation 且 id=目标（既有读取面可见）",
           rec[0] if rec else None)
        # accept 执行 / reject 不执行
        rr = cg.review_decide(r1.get("pid") or "", "accept", reason="守卫")
        ok(rr.get("ok") is True
           and "9595" in (cg.get("i_1") or {}).get("content", ""),
           "I gated C accept **执行**覆写（走既有 add，正文已换）", rr)
        r_rej = cg.remember_gated("i_1", BODY % "6060", layer="knowledge")
        cg.review_decide(r_rej.get("pid") or "", "reject", reason="守卫：不执行")
        ok("6060" not in (cg.get("i_1") or {}).get("content", ""),
           "I gated C reject **不执行**（目标未被改）")
        cg.close()

    # ---- ② 资格在先（纯加严）：受保护节点覆写在 write_qualify 处当场拦 ----
    with _mode("confirm"):
        cg = _lib("gated_prot")
        cg.add("i_prot", BODY % "8080", layer="self", verification_basis="test")
        cg.flush()
        try:
            cg.remember_gated("i_prot", BODY % "7070", layer="knowledge")
            ok(False, "I gated C 受保护节点覆写未被资格闸拦（纯加严被破坏）")
        except Exception as exc:                          # noqa: BLE001
            ok(type(exc).__name__ in ("ProtectionError", "AccessDenied"),
               "I gated C 受保护节点在 write_qualify 处当场被拦（资格先于档位、"
               "不静默入队）", type(exc).__name__)
        ok(cg.get("i_prot") is not None and len(_mut_entries(cg.review_list())) == 0,
           "I 受保护覆写零出单（队列无变更单，未被静默入队）")
        cg.close()

    # ---- ③ plan 档：C 覆写出单（与 confirm 同格） ----
    with _mode("plan"):
        cg = _lib("gated_plan")
        cg.add("i_p", BODY % "9090", layer="knowledge", verification_basis="test")
        cg.flush()
        r = cg.remember_gated("i_p", BODY % "9595", layer="knowledge")
        ok(r.get("verdict") == "CONFIRM" and r.get("moved_to") == "review_queue"
           and bool(r.get("pid"))
           and "9595" not in (cg.get("i_p") or {}).get("content", ""),
           "I gated C 覆写（plan 档）出变更单且不落盘（C 在 plan/confirm 同语义）",
           {k: r.get(k) for k in ("verdict", "moved_to", "pid")})
        cg.close()

    # ---- ④ plan 档：A 新增 fail-closed（独立库：不得被同库近重复判成 MERGE） ----
    with _mode("plan"):
        cg = _lib("gated_plan_a")
        r2 = cg.remember_gated("i_new", BODY % "7777", layer="knowledge")
        ok(r2.get("verdict") == "FORBID" and r2.get("ok") is False
           and r2.get("moved_to") == "autonomy_forbidden"
           and r2.get("error") == "autonomy_forbid"
           and "计划" in str(r2.get("hint") or "")
           and cg.get("i_new") is None
           and len(_mut_entries(cg.review_list())) == 0,
           "I gated A 新增（plan 档）fail-closed 带 hint、未落盘、未出单",
           {k: r2.get(k) for k in ("verdict", "ok", "moved_to", "error")})
        cg.close()

    # ---- ⑤ full 档：C 覆写照旧直落（零变更单） ----
    with _mode("full"):
        cg = _lib("gated_full")
        cg.add("i_f", BODY % "9090", layer="knowledge", verification_basis="test")
        cg.flush()
        r = cg.remember_gated("i_f", BODY % "9595", layer="knowledge")
        ok(r.get("verdict") == "ACCEPT" and r.get("written") == "i_f"
           and "9595" in (cg.get("i_f") or {}).get("content", "")
           and len(_mut_entries(cg.review_list())) == 0,
           "I gated C 覆写（full 档）照旧直落：verdict=ACCEPT、正文已换、零变更单",
           {k: r.get(k) for k in ("verdict", "written")})
        cg.close()

    # ---- ⑥ A 新增：confirm/full 两档**逐位一致**（不动面对拍） ----
    runs = {}
    for m in ("confirm", "full"):
        with _mode(m):
            cg = _lib("gated_pair_" + m)
            r = cg.remember_gated("i_a", PLAIN % "对拍", layer="knowledge")
            runs[m] = (r, _strip(cg.get("i_a") or {}))
            cg.close()
    ok(runs["confirm"][0].get("verdict") == "ACCEPT"
       and runs["full"][0].get("verdict") == "ACCEPT"
       and _strip(runs["confirm"][0]) == _strip(runs["full"][0]),
       "I gated A 新增：confirm 档返回体与 full 档逐位相等（时钟面除外）",
       {"confirm": _strip(runs["confirm"][0]),
        "full": _strip(runs["full"][0])})
    ok(runs["confirm"][1] == runs["full"][1],
       "I gated A 新增：两档落盘节点（正文与 fm）逐位相等（A 面零变化）")

    # ---- ⑦ 写链面（op=write + gated=true）与 MCP 工具面（插件主写入通道） ----
    with _mode("confirm"):
        cg = _lib("gated_chain")
        pipe = _pipe()
        o1 = pipe.execute(cg, {"content_kind": "text", "content": PLAIN % "甲",
                               "layer": "knowledge", "node_id": "i_ch",
                               "gated": True})
        ok(o1.get("committed") is True,
           "I gated 链面：A 新增（confirm 档）直落不拦（行为零变化）", o1)
        o2 = pipe.execute(cg, {"content_kind": "text", "content": PLAIN % "乙",
                               "layer": "knowledge", "node_id": "i_ch",
                               "gated": True})
        ok(o2.get("moved_to") == "review_queue" and o2.get("committed") is False
           and bool((o2.get("gate") or {}).get("pid")),
           "I gated 链面：C 覆写出单且不落盘（_gate_gated 透出 review_queue+pid）",
           {k: o2.get(k) for k in ("moved_to", "committed")})
        ok("甲" in (cg.get("i_ch") or {}).get("content", "")
           and "乙" not in (cg.get("i_ch") or {}).get("content", ""),
           "I gated 链面：出单时链上目标未被覆写（替代执行路径已改判出单）")
        from .mcp_server import _dispatch
        rm = _dispatch(cg, "mdcg_remember",
                       {"content": PLAIN % "丙", "node_id": "i_ch",
                        "gated": True, "layer": "knowledge"})
        ok(rm.get("moved_to") == "review_queue" and bool(rm.get("pid"))
           and rm.get("committed") is False
           and "丙" not in (cg.get("i_ch") or {}).get("content", ""),
           "I MCP 面 mdcg_remember(gated=true)：C 覆写出单且不落盘（插件主通道"
           "不再旁路确认档）",
           {k: rm.get(k) for k in ("verdict", "ok", "moved_to", "pid")})
        cg.close()

    # ---- ⑧ 执行桥：C 目标在 accept 前消失 ----
    with _mode("confirm"):
        cg = _lib("gated_bridge")
        cg.add("i_b", BODY % "9090", layer="knowledge", verification_basis="test")
        cg.flush()
        rb = cg.remember_gated("i_b", BODY % "9595", layer="knowledge")
        ok(rb.get("verdict") == "CONFIRM" and bool(rb.get("pid")),
           "I 执行桥前置：C 覆写已出单", rb.get("verdict"))
        cg.forget("i_b", reason="守卫：目标消失")
        cg.flush()
        rr = cg.review_decide(rb.get("pid") or "", "accept", reason="守卫")
        ok(rr.get("ok") is False and rr.get("error") == "target_missing"
           and cg.get("i_b") is None and bool(rr.get("hint")),
           "I 执行桥 C 目标消失 → target_missing 且**不重建**节点（fail-closed）",
           {k: rr.get(k) for k in ("ok", "error")})
        ok(any(x.get("pid") == rb.get("pid") for x in cg.review_list()),
           "I 目标消失的单仍在 pending（未被静默记 accepted）")
        cg.add("i_b2", BODY % "9090", layer="knowledge", verification_basis="test")
        cg.flush()
        rb2 = cg.remember_gated("i_b2", BODY % "9595", layer="knowledge")
        rr2 = cg.review_decide(rb2.get("pid") or "", "accept", reason="守卫")
        ok(rr2.get("ok") is True
           and "9595" in (cg.get("i_b2") or {}).get("content", ""),
           "I 对照：目标在位时 accept 照旧执行覆写（判据不是「一律拒」）", rr2)
        cg.close()


# =============================================================== J 组：SHIM 修复面
def g_j():
    print("== J 组：容器栈一 SHIM-MISS 修复面（test_policy_required_ccg）==")
    from . import test_policy_required_ccg as _tpc_g
    ok(_tpc_g is _tpc and "autonomy_modes" in _tpc._SHIMS,
       "J SHIM 登记：autonomy_modes 在 _SHIMS（writepipe 档位闸的相对 import "
       "已覆盖）", list(_tpc._SHIMS))
    try:
        _tpc._check_shim_coverage(_tpc._baseline_sources())
        ok(True, "J 基线源相对 import 全覆盖：SHIM-MISS 判据不抛（变异锚点亦在位）")
    except SystemExit as exc:                             # noqa: BLE001
        ok(False, "J 基线源相对 import 全覆盖：SHIM-MISS 判据不抛（fail-closed）",
           exc)
    got = _submit("md_cg/test_policy_required_ccg.py", ["--head-baseline"])
    ok(got["rc"] == 0 and "红基线符合预期" in got["out"],
       "J --head-baseline 整腿 PASS（退出码 0、红项集合 == 预期 11 项）",
       {"rc": got["rc"], "tail": got["out"][-160:]})
    got2 = _submit("md_cg/test_policy_required_ccg.py", ["--head-baseline"],
                   drop_shim=True)
    ok(got2["rc"] != 0 and "SHIM-MISS" in got2["out"],
       "J 负对照（同处定点变异：_SHIMS 去掉 autonomy_modes）⇒ 该腿 SHIM-MISS "
       "非零退出——J3 的绿有判别力", {"rc": got2["rc"]})


# =============================================================== K 组：变更单字段
def g_k():
    print("== K 组：变更单三字段（前像=执行时点 · 影响面 · 回滚命令）==")
    with _mode("confirm"):
        cg = _lib("fields")
        # 边影响面：本节点 part_of → k_p（父）——C 覆写的 add 全量重建 fm 会把
        # 声明式 edges 清空（既有行为），前像/影响面据此可判别。
        cg.add("k_1", PLAIN % "初版", layer="knowledge",
               verification_basis="test",
               edges=[{"target": "k_p", "relation_type": "part_of"}])
        cg.add("k_p", PLAIN % "父", layer="knowledge",
               verification_basis="test")
        cg.flush()
        pay0 = autonomy_modes.mutation_payload("C", "k_1", after=PLAIN % "改写版",
                                               reason="字段完备探针",
                                               primitive="add")
        ok(pay0.get("before") is None and pay0.get("impact") is None
           and pay0.get("rollback") == "",
           "K 提议时点载荷三键恒在且占位（before/impact=None、rollback=''）",
           {k: pay0.get(k) for k in ("before", "impact", "rollback")})
        pr = autonomy_modes.propose_mutation(cg, "C", "k_1", payload=pay0,
                                             layer="knowledge", info=True)
        rec0 = [x for x in cg.review_list() if x.get("pid") == pr["pid"]]
        view0 = autonomy_modes.mutation_view(rec0[0]) if rec0 else None
        ok(view0 is not None and view0.get("before") is None
           and view0.get("impact") is None and view0.get("rollback") == "",
           "K 队列条目的 mutation_view 同口径三键（提议时点占位）", view0)
        # 提议→accept 之间：第三方覆写（前像必须=执行时点=该版本）。
        # 第三方自己也带同一条声明式边（add 全量重建 fm 的既有语义：不带即清空）
        # ——使「执行时点影响面」的边读数在案、判据可评估。
        cg.add("k_1", PLAIN % "第三方版", layer="knowledge",
               verification_basis="test",
               edges=[{"target": "k_p", "relation_type": "part_of"}])
        third_p = os.path.join(cg.root, cg.index["nodes"]["k_1"]["path"])
        with open(third_p, "rb") as f:
            third_bytes = f.read()
        r = cg.review_decide(pr["pid"], "accept", reason="K：执行")
        m = r.get("mutation") or {}
        ok(r.get("ok") is True and isinstance(m, dict),
           "K accept 执行返回补全载荷（dict）", {k: r.get(k) for k in
                                          ("ok", "error")})
        pre_rel = m.get("before") or ""
        pre_p = os.path.join(cg.root, pre_rel.replace("/", os.sep)) if pre_rel else ""
        ok(bool(pre_rel) and os.path.isfile(pre_p),
           "K before 非空且指向已落盘快照（执行时点前像）", pre_rel)
        snap_bytes = None
        if pre_p and os.path.isfile(pre_p):
            with open(pre_p, "rb") as f:
                snap_bytes = f.read()
        # 前像缺失（变异「不拍前像」）时这里不 skip——None != third_bytes 即红，
        # 「前像=执行时点」这条判据必须有判别力（不是空转的前提断言）。
        ok(snap_bytes == third_bytes,
           "K 前像=**执行时点**盘面（第三方改动被保留=逐字节等于 accept 前盘面）",
           "前像字节与 accept 前盘面%s" % ("相同" if snap_bytes == third_bytes
                                     else "不同/前像缺失"))
        snap_text = (open(pre_p, encoding="utf-8").read()
                     if (pre_p and os.path.isfile(pre_p)) else "")
        ok("第三方版" in snap_text and "初版" not in snap_text,
           "K 前像不是提议时点版本（含第三方版、不含出单前初版）",
           repr(snap_text[-60:]))
        imp = m.get("impact")
        ok(isinstance(imp, dict)
           and {"edges", "index", "agg_lines"} <= set(imp),
           "K impact 三面齐备（边/索引条目/聚合行）", imp)
        ok(isinstance(imp, dict)
           and (imp.get("edges") or {}).get("parents") == ["k_p"],
           "K impact·边 = 执行时点读数（part_of 父边 k_p 在案）",
           (imp or {}).get("edges"))
        ok(isinstance(imp, dict)
           and isinstance(imp.get("index"), dict)
           and imp["index"].get("present") is True
           and isinstance(imp.get("agg_lines"), list),
           "K impact·索引条目在案 + 聚合行为列表", (imp or {}).get("index"))
        cmd = m.get("rollback") or ""
        ok(isinstance(cmd, str) and "md_cg.rollback_cli" in cmd
           and pr["pid"] in cmd and "utf8" in cmd,
           "K rollback = 可执行回滚命令串（rollback_cli + pid + utf8）", cmd)
        recs = [x for x in cg.decisions() if x.get("pid") == pr["pid"]]
        rex = recs[-1] if recs else {}
        ok(isinstance(rex.get("mutation"), dict)
           and rex["mutation"].get("before") == pre_rel
           and rex["mutation"].get("rollback") == cmd
           and rex["mutation"].get("action") == "C",
           "K 执行记录 rec['mutation'] 落盘（before/rollback/action 与返回体一致）",
           sorted((rex.get("mutation") or {}).keys()))
        ok(isinstance(rex.get("mutation"), dict)
           and rex["mutation"].get("executed") is True
           and rex["mutation"].get("impact") == imp,
           "K rec['mutation'] 亦带 executed 与影响面（同一份补全形态）")
        cg.close()


# =============================================================== L 组：准入闸（批次④）
def g_l():
    """批次④（设计 §六/§七）：准入闸生效面——full 经 R1–R4 读数、回落不静默。

    深度判据（R1–R4 四条读数本身、门槛边界、窗口边界）见独立守卫
    `md_cg/test_autonomy_admission.py`；本组只钉**生效面接线**：
    full+满足 ⇒ full（逐位一致）/ full+不满足 ⇒ confirm + alerts 报缺 /
    plan·confirm 不受影响（零 IO 零告警）/ 非法 env fail-closed /
    未结算 = 旧行为（对拍）/ 缓存频度 / 只读。
    """
    print("== L 组：准入闸（full 经读数 / plan·confirm 不受影响 / 回落不静默）==")
    from . import admission as _adm_mod
    from . import nodefile as _nf

    def _lroot(tag):
        p = os.path.join(_SANDBOX, "l_%s_r%d" % (tag, _RUN[0]))
        os.makedirs(p, exist_ok=True)
        return p

    def _lwr(root, rel, rows):
        p = os.path.join(root, rel)
        d = os.path.dirname(p)
        if d:
            os.makedirs(d, exist_ok=True)
        with open(p, "w", encoding="utf-8") as f:
            for r in rows:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")

    def _lmd(root, layer, nid, created_at):
        p = os.path.join(root, layer, nid + ".md")
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "w", encoding="utf-8") as f:
            f.write(_nf.dumps({"id": nid, "layer": layer,
                               "created_at": created_at}, "# 探针节点\n"))

    def _sat(tag):
        """四条读数全满足的合成库（窗口数据用字面量天，不引用被测常量）。"""
        r = _lroot(tag)
        now = time.time()
        _lwr(r, _adm_mod.FORGETTING_LOG, [
            {"t": now - 3600, "verdict": "DROP"},
            {"t": now - 3600, "verdict": "MERGE"},
            {"t": now - 3600, "verdict": "DEFER"}])
        _lmd(r, "rejected", "rej_1", now - 3600)
        _lmd(r, "unresolved", "unr_1", now - 3600)
        _lwr(r, _adm_mod.DEVICE_AUDIT, [
            {"t": now - 7200, "op": "forget", "id": "z_1"},
            {"t": now - 3600, "op": "restore", "id": "z_1", "forced": True}])
        rows = []
        for k, n_rej in ((1, 1), (2, 3), (3, 4)):
            mid = now - (k - 0.5) * 10 * 86400.0
            rows += [{"t": mid, "decision": "reject"} for _ in range(n_rej)]
            rows += [{"t": mid, "decision": "accept"} for _ in range(10 - n_rej)]
        _lwr(r, _adm_mod.DECISIONS_LOG, rows)
        return r

    try:
        empty, sat = _lroot("empty"), _sat("sat")
        # L1 full + 读数满足 ⇒ full（改动前行为逐位一致）
        with _mode("full"):
            autonomy_modes.reset_settlement()
            st = autonomy_modes.settle(root=sat, force=True)
            ok(st["effective"] == "full" and st["alerts"] == []
               and autonomy_modes.mode() == "full",
               "L1 full+读数满足 ⇒ 生效档位 full、零告警（与改动前逐位一致）",
               st["effective"])
        # L2 full + 读数不满足 ⇒ 回落 confirm + 报缺哪条（不静默降级）
        with _mode("full"):
            autonomy_modes.reset_settlement()
            st = autonomy_modes.settle(root=empty, force=True)
            ok(st["effective"] == "confirm" and st["configured"] == "full"
               and st["settled"] is True,
               "L2 full+读数不满足 ⇒ 实际生效档位回落 confirm（配置仍记 full）",
               st["effective"])
            miss = (st.get("admission") or {}).get("missing") or []
            ok(bool(miss) and [a["reading"] for a in st["alerts"]] == miss,
               "L2a 不静默降级：alerts 逐条报缺哪条读数（与读数 missing 一致）",
               st["alerts"])
            ok(autonomy_modes.mode() == "confirm"
               and autonomy_modes.decide("D")["decision"] == "confirm",
               "L2b 回落贯通判定链：mode() 与 decide(D) 同步 confirm",
               {"mode": autonomy_modes.mode(), "dec": autonomy_modes.decide("D")["decision"]})
        # L3 plan/confirm 不受读数影响（零 IO 零告警）
        autonomy_modes.reset_settlement()
        for m in ("confirm", "plan"):
            with _mode(m):
                n0 = _adm_mod.cache_stats()["checks"]
                st = autonomy_modes.settle(root=empty, force=True)
                ok(st["effective"] == m and st["admission"] is None
                   and st["alerts"] == []
                   and _adm_mod.cache_stats()["checks"] == n0,
                   "L3 %s 档不受读数影响（零告警、零读数扫描）" % m,
                   st["effective"])
        # L4 非法 env 仍 fail-closed
        with _mode("bogus-x"):
            try:
                autonomy_modes.settle(root=empty, force=True)
                ok(False, "L4 非法 env settle 未报错")
            except autonomy_modes.AutonomyModeError:
                ok(True, "L4 非法 env fail-closed（settle 抛 AutonomyModeError）")
        # L5 未结算 = 旧行为（对拍）
        autonomy_modes.reset_settlement()
        with _mode("full"):
            ok(autonomy_modes.mode() == "full" and autonomy_modes.admission_state()["settled"] is False,
               "L5 未结算时 mode() 返回配置档位（生效面未启用 = 改动前逐位一致）")
        # L6 缓存频度（「不得让每次 decide 都全库扫描」）
        autonomy_modes.reset_settlement()
        _adm_mod.reset_cache()
        with _mode("full"):
            autonomy_modes.settle(root=empty, force=True, ttl=60)
            autonomy_modes.settle(root=empty, ttl=60)
            autonomy_modes.settle(root=empty, ttl=60)
            ok(_adm_mod.cache_stats()["checks"] == 1,
               "L6 读数缓存：TTL 内重复结算不重扫（热路径零 IO）",
               _adm_mod.cache_stats())
        # L7 只读（只告警不改数据）
        fp0 = _adm_mod._fingerprint(sat)
        autonomy_modes.reset_settlement()
        with _mode("full"):
            autonomy_modes.settle(root=sat, force=True)
        ok(_adm_mod._fingerprint(sat) == fp0 and len(fp0) > 0,
           "L7 只告警不改数据：结算前后库指纹逐位相同", len(fp0))
        # L8 结算态可查（含 alerts）
        autonomy_modes.reset_settlement()
        with _mode("full"):
            autonomy_modes.settle(root=empty, force=True)
            ok(autonomy_modes.admission_state()["effective"] == "confirm"
               and autonomy_modes.admission_state()["alerts"] != [],
               "L8 结算态可查：admission_state() 返回回落体与 alerts")
    finally:
        autonomy_modes.reset_settlement()


# =============================================================== M 组：收官补缺
def g_m():
    """收官批次（步骤⑤）：覆盖矩阵**未覆盖格**补缺（plan 档热路径 + E 分数类）。

    覆盖矩阵（3 档 × A–E × 四套守卫）清点见
    `docs/eval/三档自治_步骤⑤收官与全链验收_落码记录_v1.0.md`；本组补的是矩阵
    里此前**无断言**的格：

      · plan 档热路径四面：写链 C 覆写（非 gated）／gated 面 B 合并（MERGE
        落点）／限流闸 CONVERGE 落点／工具面 D 删除——此前 plan 档只有
        decide 级判据（A 组）与 gated A 新增（I 组 ④）；
      · E 分数类（权重/生命周期）在档位面的**行为读数**。
    补强批次（v1.2）扩展：
      · **M1e**：`mdcg_remember` **非 gated 直写分支**（`mcp_server.py:3373`）
        三档行为——复核 U1 的解除项（此前 plan/confirm 两档均无断言）；
      · **M2 重编码**：E 面已接档位闸（`e_gate` 接在四处 apply 写盘路径）
        ⇒ 判据由「plan≡confirm（现状钉）」改为「plan 被拦 ＋ confirm/full
        逐位相等」（**意图不变**，同 issue50-a 的 E1 先例）。

    边界（如实：设计内语义 vs 留池缺口分列，不混淆）：
      · plan 档 **C/D 与 confirm 同格**（需确认 ⇒ 出单，非 forbid）——设计 §三
        矩阵逐格如此，M1/M1d 钉的就是「出单且不落盘」；
      · plan 档 **A/B/E 无计划输入即 forbid**（设计 §三 硬约束③）——属设计内
        语义，**不并入** confirm↔full 不动面对拍范围（对拍锚只含 confirm/full）；
      · **E 面档位闸已接线**（补强批次 v1.2）：plan 档 E 类动作
        （`freshness.recalc` / `weights.recalc` / `lifecycle.set_state` /
        `lifecycle.backfill` 的 **apply 路径**）fail-closed 且零写盘；
        confirm/full 两档原链原样（逐位不变）。**未接**的三处入口及理由见
        `autonomy_modes.e_gate()` docstring（`lifecycle.stamp` 属 B 链／库层
        `require_transition` 禁接线／分数类回滚面待裁）——**计划输入面**仍留池：
        现状 `plan=None` ⇒ plan 档 E 一律 fail-closed，「命中计划步骤」的
        allow 分支待计划输入面接线（`autonomy_modes` 模块 docstring「本批不做」）。

    confirm/full 两档的 A/E 逐位对拍、与旧基线的 oracle 对拍、端到端回滚演练
    （跨写链/插件面/执行桥/回滚 CLI）在独立守卫 `md_cg/test_mode_parity.py`。
    """
    print("== M 组：收官补缺（plan 档热路径四面 + E 分数类在档位面）==")
    from . import freshness as _fresh
    # ---- M1 写链 C 覆写（plan 档，非 gated 面）----
    with _mode("plan"):
        cg = _lib("m_plan_c")
        cg.add("mp_c", PLAIN % "初版", layer="knowledge",
               verification_basis="test")
        cg.flush()
        o = _pipe().execute(cg, {"content_kind": "text", "content": PLAIN % "改写版",
                                 "layer": "knowledge", "node_id": "mp_c"})
        pay = o.get("mutation") or {}
        ok(o.get("moved_to") == "review_queue" and o.get("committed") is False
           and bool(o.get("pid")) and pay.get("action") == "C"
           and pay.get("target") == "mp_c",
           "M1 写链 C 覆写（plan 档）出变更单且不落盘（C 在 plan/confirm 同格，"
           "此前写链面 plan 档无断言）",
           {k: o.get(k) for k in ("moved_to", "committed", "pid")})
        ok("改写版" not in (cg.get("mp_c") or {}).get("content", "")
           and "初版" in (cg.get("mp_c") or {}).get("content", ""),
           "M1 出单时目标正文**未被覆写**（逐字比对）")
        cg.close()

    # ---- M1b gated 面 B 合并（plan 档，MERGE 落点）----
    with _mode("plan"):
        cg = _lib("m_plan_b")
        cg.add("mp_b", BODY % "9090", layer="knowledge",
               verification_basis="test")
        cg.flush()
        r = cg.remember_gated("mp_bn", BODY % "9595", layer="knowledge")
        ok(r.get("verdict") == "FORBID"
           and r.get("moved_to") == "autonomy_forbidden"
           and r.get("merged_into") == "mp_b"
           and "计划" in str(r.get("hint") or ""),
           "M1b gated 面 B 合并（plan 档·MERGE 落点）fail-closed：verdict=FORBID "
           "+ 计划外零变更 hint（此前无断言）",
           {k: r.get(k) for k in ("verdict", "moved_to", "merged_into")})
        t = cg.get("mp_b") or {}
        ok("9595" not in (t.get("content") or "")
           and not ((t.get("frontmatter") or {}).get("merge_count"))
           and len(_mut_entries(cg.review_list())) == 0,
           "M1b 未合并：目标正文/merge_count 不动、零变更单（未落盘、未出单）",
           (t.get("frontmatter") or {}).get("merge_count"))
        cg.close()

    # ---- M1c 限流闸 CONVERGE 落点（plan 档；锚点须在允许档先落）----
    cg = _lib("m_plan_cv")
    with _mode("confirm"):
        r1 = cg.remember_gated("mp_x1", "批次107 收官：指标面 9090 正常",
                               layer="contextual")
    with _mode("plan"):
        r2 = cg.remember_gated("mp_x2", "批次108 收官：指标面 9595 正常",
                               layer="contextual")
        ok(r1.get("verdict") == "ACCEPT" and r2.get("verdict") == "FORBID"
           and r2.get("moved_to") == "autonomy_forbidden",
           "M1c 限流闸 CONVERGE（plan 档）fail-closed：verdict=FORBID、"
           "moved_to=autonomy_forbidden（锚点在 confirm 档落盘、切 plan 后"
           "第二篇被拦——此前无断言）",
           {"r1": r1.get("verdict"), "r2": r2.get("verdict")})
        ok("9595" not in ((cg.get("mp_x1") or {}).get("content") or ""),
           "M1c CONVERGE 未并入：目标正文不含新值（合并原语未被调用）")
    cg.close()

    # ---- M1d 工具面 D 删除（plan 档）----
    with _mode("plan"):
        cg = _lib("m_plan_d")
        cg.add("mp_d", BODY % "9090", layer="knowledge",
               verification_basis="test")
        cg.flush()
        r = cg.forget_gated("mp_d", reason="守卫：plan 档删除")
        ok(r.get("moved_to") == "review_queue" and r.get("deleted") is False
           and (r.get("mutation") or {}).get("action") == "D"
           and cg.get("mp_d") is not None,
           "M1d 工具面 D 删除（plan 档）出变更单且不软删（deleted=False 明示、"
           "节点原样在位——此前无断言）",
           {k: r.get(k) for k in ("moved_to", "deleted", "ok")})
        cg.close()

    # ---- M1e 直写面（mdcg_remember 非 gated）三档：plan/confirm 出单、full 直落 ----
    # U1 解除项：`mcp_server.py:3373` 的 `_dec = _am.decide(_action)` 所在分支
    # （`_dispatch` 的 `mdcg_remember` 非 gated 直写面）此前 **plan 与 confirm
    # 两档均无行为断言**（复核 V4' 注入 0 红存活、不限档位摘除变体亦全绿）；
    # 本组形态同 M1（写链面）：出单且不落盘 / 正文逐字未动 / 队列计数 + full 直落。
    def _direct_probe(mode, tag):
        with _mode(mode):
            cg = _lib(tag)
            cg.add("ud_c", PLAIN % "初版", layer="knowledge",
                   verification_basis="test")
            cg.flush()
            o = mcp_server._dispatch(cg, "mdcg_remember",
                                     {"content": PLAIN % "改写版",
                                      "node_id": "ud_c", "layer": "knowledge"})
            body = (cg.get("ud_c") or {}).get("content") or ""
            orders = _mut_entries(cg.review_list())
            cg.close()
            return o, body, orders

    o_p, b_p, m_p = _direct_probe("plan", "m_direct_plan")
    ok(o_p.get("moved_to") == "review_queue" and o_p.get("committed") is False
       and bool(o_p.get("pid"))
       and (o_p.get("mutation") or {}).get("action") == "C"
       and (o_p.get("mutation") or {}).get("target") == "ud_c",
       "M1e① 直写面 C 覆写（plan 档·mdcg_remember 非 gated）出变更单且不落盘"
       "（moved_to=review_queue、committed=False、单载荷 action=C/target 齐"
       "——复核 U1：此前该分支 plan 档无行为断言）",
       {k: o_p.get(k) for k in ("moved_to", "committed", "pid")})
    ok("改写版" not in b_p and "初版" in b_p and len(m_p) == 1,
       "M1e② plan 档出单时目标正文**未被覆写**（逐字比对）且队列恰 1 张",
       {"orders": len(m_p), "body": b_p[:24]})
    o_c, b_c, m_c = _direct_probe("confirm", "m_direct_confirm")
    ok(o_c.get("moved_to") == "review_queue" and o_c.get("committed") is False
       and bool(o_c.get("pid"))
       and (o_c.get("mutation") or {}).get("action") == "C"
       and "改写版" not in b_c and "初版" in b_c and len(m_c) == 1,
       "M1e③ 直写面 C 覆写（confirm 档）出变更单且不落盘（正文未改、队列 1 张"
       "——复核 U1：此前该分支 confirm 档亦无断言）",
       {k: o_c.get(k) for k in ("moved_to", "committed", "pid")})
    o_f, b_f, m_f = _direct_probe("full", "m_direct_full")
    ok(o_f.get("ok") is True and o_f.get("moved_to") is None
       and o_f.get("overwrite_of") == "ud_c" and "改写版" in b_f
       and "初版" not in b_f,
       "M1e④ 直写面 C 覆写（full 档）**直落**：ok=True、无单、正文已换"
       "（overwrite_of 读数齐）",
       {k: o_f.get(k) for k in ("ok", "moved_to", "overwrite_of")})
    ok(len(m_f) == 0,
       "M1e⑤ full 档同面零变更单（直落面不产单——与 confirm 链的分界）",
       len(m_f))

    # ---- M2 E 分数类在档位面（补强批次 v1.2：按标题意图重编码，意图不变）----
    # 重编码的根据：E 面**已接档位闸**（autonomy_modes.e_gate 接在
    # weights.recalc / freshness.recalc / lifecycle.set_state / lifecycle.backfill
    # 的 apply 写盘路径）。故 M2 的判据由「plan≡confirm（现状钉、非背书）」改为
    # 「**plan 被拦 ＋ confirm/full 逐位相等**」——断言意图（E 在 plan 档须受
    # 计划约束、confirm/full 不阻塞）一字未改，改的是编码（同 issue50-a 的 E1
    # 先例）。**本组不再钉「E 面无接线」**：那正是补强批次要消灭的留池项。
    def _e_fresh(mode, tag):
        with _mode(mode):
            cg = _lib(tag)
            cg.add("me_1", BODY % "9090", layer="knowledge",
                   verification_basis="test", importance=0.4)
            cg.add("me_2", PLAIN % "被引", layer="knowledge",
                   verification_basis="test",
                   edges=[{"target": "me_1", "relation_type": "part_of"}])
            cg.flush()
            out = _fresh.recalc(cg, apply=True, min_delta=0.0001,
                                now=1700000000.0)
            fm = dict(((cg.get("me_1") or {}).get("frontmatter") or {}))
            cg.close()
            return out, fm

    op_, fp = _e_fresh("plan", "m_e_plan")
    oc, fc = _e_fresh("confirm", "m_e_conf")
    of, ff = _e_fresh("full", "m_e_full")
    ok(op_.get("ok") is False and op_.get("error") == "autonomy_forbidden"
       and "计划" in str(op_.get("hint") or "")
       and op_.get("written") == 0,
       "M2① E 面 plan 档**被拦**：freshness.recalc(apply=True) fail-closed"
       "（ok=False/error=autonomy_forbidden/带「计划外零变更」hint/written=0）",
       {k: op_.get(k) for k in ("ok", "error", "written")})
    ok(fp.get("freshness_weight") is None
       and fp.get("freshness_source") is None,
       "M2② plan 档**零写盘**：盘面无 freshness_weight/freshness_source"
       "（与 confirm 档对照——fail-closed 不是「报错但仍写」）",
       {k: fp.get(k) for k in ("freshness_weight", "freshness_source")})
    ok(oc.get("ok") is True and int(oc.get("written") or 0) >= 1
       and fc.get("freshness_weight") is not None,
       "M2③ confirm 档**照落**：written≥1 且 freshness_weight 已写盘"
       "（E 列 confirm = 允许，分数类不阻塞）",
       {k: oc.get(k) for k in ("ok", "written", "error")})
    ok(_strip(oc) == _strip(of) and _strip(fc) == _strip(ff)
       and ff.get("freshness_weight") is not None,
       "M2④ E 接线**只在 plan 档生效**：confirm 与 full 两档输出**逐位相等**、"
       "落盘 fm（剔除时钟面）逐位相等（「confirm/full 全线逐位不变」硬约束的"
       "E 面锚）",
       {"out_same": _strip(oc) == _strip(of),
        "fm_diff": [k for k in set(fc) | set(ff)
                    if _strip(fc).get(k) != _strip(ff).get(k)]})
    with _mode("plan"):
        cg = _lib("m_e_dry")
        cg.add("me_1", BODY % "9090", layer="knowledge",
               verification_basis="test", importance=0.4)
        cg.flush()
        dr = _fresh.recalc(cg, apply=False, min_delta=0.0001, now=1700000000.0)
        cg.close()
    ok(dr.get("ok") is True and dr.get("dry_run") is True
       and int(dr.get("changed") or 0) >= 1,
       "M2⑤ 闸只在 **apply 路径**：plan 档预演（apply=False）照旧出报表"
       "（零写盘面不接闸——接线面即「变更」面）",
       {k: dr.get(k) for k in ("ok", "dry_run", "changed")})

    def _e_weights(mode, tag):
        with _mode(mode):
            cg = _lib(tag)
            cg.add("mw_1", BODY % "9090", layer="knowledge",
                   verification_basis="test", importance=0.4)
            cg.add("mw_2", PLAIN % "被引", layer="knowledge",
                   verification_basis="test",
                   edges=[{"target": "mw_1", "relation_type": "part_of"}])
            cg.flush()
            out = weights.recalc(cg, apply=True, min_delta=0.0001)
            fm = dict(((cg.get("mw_1") or {}).get("frontmatter") or {}))
            cg.close()
            return out, fm

    wp, fwp = _e_weights("plan", "m_w_plan")
    wc, fwc = _e_weights("confirm", "m_w_conf")
    ok(wp.get("ok") is False and wp.get("error") == "autonomy_forbidden"
       and fwp.get("importance") == 0.4,
       "M2⑥ weights.recalc（第二写盘入口）plan 档被拦且 importance 盘面未改"
       "（接线前实测 0.5→0.57 已写盘——本条即该缺口的机械钉）",
       {k: wp.get(k) for k in ("ok", "error")})
    ok(wc.get("ok") is True and int(wc.get("written") or 0) >= 1
       and fwc.get("importance") != 0.4,
       "M2⑦ weights.recalc confirm 档照落（importance 已重算写盘）",
       {"written": wc.get("written"), "imp": fwc.get("importance")})

    def _e_state(mode, tag):
        with _mode(mode):
            cg = _lib(tag)
            cg.add("ml_1", BODY % "9090", layer="knowledge",
                   verification_basis="test")
            cg.flush()
            out = _lc.set_state(cg, "ml_1", "converged", reason="守卫",
                                actor="guard")
            fm = dict(((cg.get("ml_1") or {}).get("frontmatter") or {}))
            cg.close()
            return out, fm

    sp, fsp = _e_state("plan", "m_l_plan")
    sc, fsc = _e_state("confirm", "m_l_conf")
    ok(sp.get("ok") is False and sp.get("error") == "autonomy_forbidden"
       and sp.get("changed") is False
       and fsp.get(_lc.STATE_FIELD) == "active",
       "M2⑧ lifecycle.set_state（第三写盘入口）plan 档被拦：ok=False + 状态未推进"
       "（盘面仍 active；资格面在前——非法迁移仍走自己的 code）",
       {k: sp.get(k) for k in ("ok", "error", "changed", "code")})
    ok(sc.get("ok") is True and sc.get("changed") is True
       and fsc.get(_lc.STATE_FIELD) == "converged",
       "M2⑨ lifecycle.set_state confirm 档照落（状态推进 = converged）",
       {"changed": sc.get("changed"), "state": fsc.get(_lc.STATE_FIELD)})

    def _e_backfill(mode, tag):
        """盘面直造**缺 lifecycle_state** 的节点（backfill 的「缺字段」前提）。"""
        with _mode(mode):
            cg = _lib(tag)
            p = os.path.join(cg.root, "knowledge", "ml_bare.md")
            os.makedirs(os.path.dirname(p), exist_ok=True)
            with open(p, "w", encoding="utf-8") as f:
                f.write(_nf.dumps({"id": "ml_bare", "layer": "knowledge",
                                   "created_at": 1700000000.0}, "# 探针节点\n"))
            cg.rebuild_index()
            out = _lc.backfill(cg, apply=True)
            fm = dict(((cg.get("ml_bare") or {}).get("frontmatter") or {}))
            cg.close()
            return out, fm

    bp, fbp = _e_backfill("plan", "m_b_plan")
    bc, fbc = _e_backfill("confirm", "m_b_conf")
    ok(bp.get("ok") is False and bp.get("error") == "autonomy_forbidden"
       and bp.get("backfilled") == 0 and bp.get("missing") == 1
       and fbp.get(_lc.STATE_FIELD) is None,
       "M2⑩ lifecycle.backfill（第四写盘入口）plan 档被拦：盘点出 1 个缺字段节点"
       "仍 fail-closed、零回填（盘面仍无 state 键）",
       {k: bp.get(k) for k in ("ok", "error", "missing", "backfilled")})
    ok(bc.get("ok") is True and bc.get("backfilled") == 1
       and fbc.get(_lc.STATE_FIELD) == "active",
       "M2⑪ lifecycle.backfill confirm 档照落（缺字段节点显式回填 active）",
       {k: bc.get(k) for k in ("ok", "backfilled")})
    ok(autonomy_modes.decide("A", mode_explicit="plan")["decision"] == "forbid"
       and autonomy_modes.decide("E", mode_explicit="plan")["decision"] == "forbid",
       "M2⑫ 设计内语义单独钉：plan 档 A/E 无计划即 forbid（计划输入面留池）"
       "——**不并入** confirm↔full 不动面对拍范围")

    # ---- F1 收口自证（2026-10-03）：防误删自检的判别力 ----
    # （合成源三形态 + 真实表对照；判别力钉＝`_SELFCHECK_MUTATION`，不占表内编号）
    # 合成源＝表体最小形态（编号用真实字符）；删法各一 + 真实表对照 + 表长兜底。
    _S_DROP_TUPLE = ("x\n_SRC_MUTATIONS = (\n"
                     "    # ① 甲\n    (\"a\",),\n"
                     "    # ② 乙\n"                # ← ② 删元组留注释（F1 原形）
                     "    # ③ 丙\n    (\"c\",),\n)\n")
    _S_DROP_BOTH = ("x\n_SRC_MUTATIONS = (\n"
                    "    # ① 甲\n    (\"a\",),\n"
                    "    # ③ 丙\n    (\"c\",),\n)\n")   # ← ② 注释+元组同删
    _self_src = io.open(os.path.abspath(__file__), encoding="utf-8").read()
    ok(_table_gaps(_S_DROP_TUPLE, 2, ("①", "②", "③")) == ["②", "len:2≠3"],
       "F1① 防误删自检判别力：删元组留注释（F1 原形）⇒ 报缺口编号 ②"
       "（表长兜底随报——此前该形态无任何机械载体）",
       _table_gaps(_S_DROP_TUPLE, 2, ("①", "②", "③")))
    ok(_table_gaps(_S_DROP_BOTH, 2, ("①", "②", "③")) == ["②", "len:2≠3"],
       "F1② 防误删自检判别力：注释与元组同删 ⇒ 仍报缺口编号 ②（编号序列比对"
       "判据）",
       _table_gaps(_S_DROP_BOTH, 2, ("①", "②", "③")))
    ok(_table_integrity_check() == [],
       "F1③ 真实表完好（**自动核验载体**）：编号 ①–㉔ 无缺口、表长 %d = 声明"
       "——「24 处」不再只是文档声称，而是每次运行自动核验" % len(_MUTATION_IDS),
       _table_integrity_check())
    _n1, _n2 = len(_SRC_MUTATIONS) - 1, len(_SRC_MUTATIONS)
    ok(_table_gaps(_self_src, _n1) == ["len:%d≠%d" % (_n1, _n2)],
       "F1④ 表长判据兜底：真实源 + 表长-1 ⇒ 报「len:%d≠%d」（防「编号齐但"
       "条目缺」的边角形态）" % (_n1, _n2),
       _table_gaps(_self_src, _n1))


_GROUPS = (g_a, g_b, g_c, g_d, g_e, g_f, g_g, g_h, g_i, g_j, g_k, g_l, g_m)


def _run_groups():
    """跑全部断言组（静默），返回失败数——供变异自证复用。"""
    _PASS.clear()
    _FAIL.clear()
    for g in _GROUPS:
        g()
    return len(_FAIL)


# =============================================================== 定点变异自证
# 表内每项 = (说明, 目标, 锚点原文, 替换文, 预期红项数)。锚点须**逐字**出现在
# 目标函数源码里；漂移即 ANCHOR-MISS（fail-closed，exit 2）。
# 目标 = ("mod", 模块对象, 函数名) 或 ("cls", 类对象, 方法名)。
#
#: 本守卫模块对象——「防误删自检」的判别力钉（`_SELFCHECK_MUTATION`）以本模块为属主
#: （`sys.modules[__name__]` 是同一对象的现取形态，不写第二处名字字面量；
#: 同 `md_cg/test_mode_parity.py` 的 `_SELF` 先例）。
_THIS = sys.modules[__name__]
_SRC_MUTATIONS = (
    # ①「档位不生效」——env 读取口恒返回真源缺省（confirm）：全档位退化成一个档。
    # 锚点（批次④改）：env 解析单点从 mode() 抽到 _configured_mode()（settle() 与
    # mode() 共用；表达式文字逐字不变）——变异目标随之挪到该单点。
    # 红 27（实测 2026-10-03 补强批次 v1.2 校准 20→27）：20（收官批次）＝9 条
    # （A 组非法值/归一两条 + full 档直落三条（B/H）+ plan 档 fail-closed 一条
    # + full 档零变更单一条 + I 组两条）+ L 组 8 条（L1 full+满足失效、L2 结算体
    # 形状、L2a 缺项告警、L3 plan 档（配置恒 confirm ⇒ plan 也退化）、L4 非法值
    # fail-closed 失效、L5 未结算对拍、L6 缓存零 IO、L8 结算态——L2b 与 L7 语义
    # 相符仍绿）+ 收官 M 组 3（M1b「MERGE 落点 FORBID」两条 + M1c「CONVERGE 落点
    # FORBID」第一条；M1（C 覆写）与 M1d（D 删除）在 plan/confirm 同格 ⇒ 相符仍绿）；
    # 补强批次 v1.2 +7 = M1e④⑤（full 臂退化 ⇒ 直写面不再直落：出单且不落盘、
    # 非零变更单）+ M2①（plan 档 E 被拦判据失效——退化后照落）+ M2②（plan 零写盘）
    # + M2⑥（weights plan 被拦）+ M2⑧（set_state plan 被拦）+ M2⑩（backfill plan
    # 被拦）。M2⑤（预演不接闸）与 M2③④⑦⑨⑪⑫ 语义相符仍绿。
    ("档位不生效（配置档位恒返回表内缺省）", "mod", autonomy_modes,
     "_configured_mode",
     '    raw = autonomy_env("mode", environ)', '    raw = DEFAULT_MODE', 27),
    # ②「confirm 也直落」——矩阵的 confirm 格被当成放行（确认形同虚设）。
    # 红 46（实测 2026-10-03 补强批次 v1.2 校准 43→46）：43（收官批次）＝
    # 原 40（批次④）＝A 组 6 条矩阵/hint 判据 + B/C/D/E 组全部「出单/不落盘/
    # 载荷/accept 执行/幂等」判据（确认路径整体消失）+ 补强批次 I 组 14 条 +
    # L 组 L2b，＋收官 M 组 3（M1 两条：写链 C 覆写 plan 档不再出单——直落且正文
    # 被覆写 + M1d：工具面 D 删除不再出单、直接软删；M1b/M1c 走 FORBID 格而非
    # CONFIRM 格，相符仍绿）；补强批次 +3 = M1e①②③（**plan 档 C 的矩阵格也是
    # CONFIRM** ⇒ 该格被当放行后直写面 plan/confirm 两臂全部直落：plan 两条
    # 「出单/正文未改」+ confirm 一条同形）。M2 各条走 PLAN_STEP/ALLOW 格，
    # 语义相符仍绿。
    ("confirm 也直落（decide 把 confirm 格判成 allow）", "mod", autonomy_modes,
     "decide", '    if cell == CONFIRM:', '    if False:', 46),
    # ③ 矩阵整表坍缩成 full 列——「档位不生效」的真源版（判据被绕过、表仍在）。
    # 红 63（实测 2026-10-03 补强批次 v1.2 校准 55→63）：55（收官批次）＝
    # 原 47（批次④）＝A 组 15 格 + confirm/plan 相关判据 + 三个落点的出单判据 +
    # 补强批次 I 组 15 + L 组 L2b，＋收官 M 组 8（M1 两条 + M1b 两条 + M1c 两条
    # （CONVERGE 直接合并）+ M1d 一条 + M2 第三条（plan 档 A/E 的 forbid 语义消失））；
    # 补强批次 +8 = M1e①②③（全档坍缩 full ⇒ 直写面 plan/confirm 也直落：出单/
    # 正文未改/队列计数三条判据全失）+ M2① ② ⑥ ⑧ ⑩（plan 档 E 五处判据——
    # 坍缩后 E 直接允许、照落写盘）。M2⑤（预演不接闸）与 M2③④⑦⑨⑪⑫ 相符仍绿。
    # F1 收口（2026-10-03，本批）：本元组曾在工作树被删（仅剩注释，红 63 的形态
    # 与注释都在、元组没了——删除原因无留痕、不归因）；自 `git show HEAD:` 取回
    # （原 expect 47 = 历史值），按现行树勘定锚点、预期红项数按现行树实测校准。
    ("矩阵整表坍缩成 full（档位不生效·真源版）", "mod", autonomy_modes, "decide",
     '    cell = MATRIX[m][act]',
     '    cell = MATRIX["full"][act]', 63),
    # ④ 写链档位闸空转——C 改写不再出单（直接覆写）。
    # 红 8（实测 2026-10-03 收官批次校准 6→8）：原 6（批次②）＝B 组 C 改写 5 条
    # （出单/未改写/载荷/队列/accept）+ plan 档 A 新增 fail-closed 一条；
    # 收官批次 +2 = M 组 M1 两条（plan 档写链 C 覆写的出单与「未覆写」判据）。
    ("写链档位闸不生效（_gate_autonomy 恒放行）", "mod", writepipe,
     "_gate_autonomy", '    prior = _forgetting.prior_node(cg, nid)',
     '    return None\n    prior = _forgetting.prior_node(cg, nid)', 8),
    # ⑤ 合并档位闸空转——B 立即合并（MERGE/CONVERGE 两落点同闸失效）。
    # 红 14（实测 2026-10-03 收官批次校准 10→14）：原 10（批次②）＝C 组 MERGE
    # 出单 4 条 + C 组 CONVERGE 出单 3 条 + H 组 full 档合并对拍 + F/E 相关 2 条；
    # 收官批次 +4 = M 组 M1b 两条（plan 档 MERGE 落点的 FORBID 与「未合并」判据）
    # + M1c 两条（plan 档 CONVERGE 落点的 FORBID 与「未并入」判据）。
    ("合并档位闸不生效（_autonomy_gate_merge 恒放行）", "cls", mdcos.MdCGOS,
     "_autonomy_gate_merge", '        dec = _am.decide(_am.B_MERGE)',
     '        return None\n        dec = _am.decide(_am.B_MERGE)', 14),
    # ⑥ 删除档位闸空转——D 立即软删（工具面档位形同虚设）。
    # 红 5（实测 2026-10-03 收官批次校准 4→5）：原 4（批次②）＝D 组出单/在位/
    # 载荷/accept 四条；收官批次 +1 = M 组 M1d（plan 档工具面删除的出单/不软删）。
    ("删除档位闸不生效（forget_gated 直调软删）", "cls", mdcos.MdCGOS,
     "forget_gated", '        dec = autonomy_modes.decide(autonomy_modes.D_DELETE)',
     '        return self._forget_apply(node_id, e, reason)\n'
     '        dec = autonomy_modes.decide(autonomy_modes.D_DELETE)', 5),
    # ⑦ 执行桥空转——accept「成功了」但动作没做（最危险的形态：汇报不实）。
    # 锚点（批次③改）：提前 return 插在**前像拍摄之前**——空转形态同时废掉
    # 「执行时点前像/补全」（K 组一并红）。
    # 红 18（实测 2026-10-02 批次③）：B 组 2（accept 执行/幂等）＋ C 组 2
    # （MERGE/CONVERGE 执行）＋ D 组 1 ＋ I 组 3 ＋ K 组 10（前像/影响面/
    # 命令串/执行记录——K 的提议时点占位与 mutation_view 两条在空转下仍绿，
    # 语义相符）。
    ("accept 不执行（执行桥空转）", "cls", mdcos.MdCGOS, "_mutation_execute",
     '            pre = _rb.preimage(self, act, tgt, pid=item.get("pid"),',
     '            return {"ok": True, "node_id": tgt}\n'
     '            pre = _rb.preimage(self, act, tgt, pid=item.get("pid"),', 18),
    # ⑧ 幂等键丢掉目标（退回内容签名）——不同目标的同内容变更单撞成一条。
    # 红 4（实测 2026-10-02 补强批次复测；批次②当时 3）：E 组三条幂等判据；
    # 补强批次 +1 = I 组「对照：目标在位 accept 照旧执行」——执行桥两张
    # 同内容不同目标的 C 单撞键后，第二张的裁决落到已关闭的 pid 上。
    ("幂等键丢掉目标（内容签名回归）", "mod", autonomy_modes,
     "mutation_dedup_key",
     '    text = "%s\\x1f%s\\x1f%s" % (act, tgt, after if after is not None else "")',
     '    text = "%s" % (after if after is not None else "")', 4),
    # ⑨ 类型字段不落 rec——变更单退化成提案（accept 会把它当新写入落盘）。
    # 红 22（实测 2026-10-03 补强批次 v1.2 校准 20→22）：20（批次③）＝B 组队列
    # kind 一条 + C 组 3 条 + D 组 accept 一条 + E 组队列计数一条 + I 组 4 条
    # （gated C 队列条目/目标消失/pending/对照）+ 批次③ K 组字段判据 10（kind 缺
    # ⇒ order_kind 判 proposal ⇒ mutation_view 返回 None、accept 走 proposal 链）；
    # 补强批次 +2 = M1e②③（出单条目因缺 kind 被 `order_kind` 判成 proposal ⇒
    # `_mut_entries` 计数 0≠1——队列计数判据的机械钉）。
    ("kind 不落 rec（变更单退化成提案）", "cls", mdcos.MdCGOS, "propose",
     '            if kind:\n                rec["kind"] = str(kind)',
     '            if False:\n                rec["kind"] = str(kind)', 22),
    # ⑩ 档位路径绕过 can_admin 闸——**本批实修缺陷的原形态**（MdCGSecure.forget
    # 的管理闸原先不在档位路径上；test_p2_mcp §9 实测抓到）。红 2（实测
    # 2026-10-02）：D 组「无 can_admin 经档位路径删除被拒」+ G 组「管理闸单点」。
    ("档位路径绕过 can_admin 闸（实修缺陷形态）", "cls", mdcos.MdCGSecure,
     "forget_gated", '        self._forget_admin()\n'
     '        return super().forget_gated(node_id, reason, override=override)',
     '        return super().forget_gated(node_id, reason, override=override)', 2),
    # ⑪ gated 面档位闸空转——`gated=true` 的 C 覆写照旧直接覆写（复核发现 1 的
    # 原形态：插件主写入通道旁路确认档；I 组 C 面/链面/MCP 面判据整体失效）。
    ("gated 面档位闸不生效（_autonomy_gate_rewrite 恒放行）", "cls", mdcos.MdCGOS,
     "_autonomy_gate_rewrite",
     '        prior = forgetting.prior_node(self, node_id)',
     '        return None\n        prior = forgetting.prior_node(self, node_id)', 15),
    # ⑫ gated 面档位闸丢掉资格探针——受保护/越权覆写从「当场拒」变成「静默入队」
    # （放宽既有判据，纯加严被破坏）。
    ("gated 面档位闸跳过资格探针（write_qualify 摘除）", "cls", mdcos.MdCGOS,
     "_autonomy_gate_rewrite",
     '            self.write_qualify(node_id, target_layer=layer,\n'
     '                               override=bool(override), actor=self.actor)',
     '            pass', 2),
    # ⑬ 执行桥 C 目标消失判据摘除——回到 `self.add` 的 upsert（复核观察 3 的原形态：
    # 「改写」静默落成「新增同 id 节点」并记 accepted）。
    ("执行桥 C 目标消失判据摘除（upsert 回归）", "cls", mdcos.MdCGOS,
     "_mutation_execute",
     '                if forgetting.prior_node(self, tgt) is None:',
     '                if False:', 3),
    # ⑭ SHIM 登记丢失（**常量型变异**，kind="attr"）——baseline 假包缺
    # autonomy_modes（补强一 的原形态：容器栈一 37/1 的那条红）。
    # 锚点随 _SHIMS 文本演进同步（2026-10-05 A2：_SHIMS 尾部新增 ghostref）。
    ("SHIM 登记丢失（_SHIMS 去掉 autonomy_modes）", "attr", _tpc, "_SHIMS",
     '"autonomy_modes", "ghostref")',
     'tuple(x for x in _SHIMS if x != "autonomy_modes")', 2),
    # ⑮ 执行桥不拍前像（批次③）——三字段的「执行时点」半支失效：before 空、
    # rollback 空，回滚句柄不存在、影响面缺失。
    # 红 8（实测）：K 组前像 3 条 + impact 3 条 + rollback 1 条 + 记录落盘 1 条
    # （K 的「executed 与影响面同形态」一条在 pre=None 时仍绿——mutation_executed
    # 保留原占位，语义相符）。
    ("执行桥不拍前像（执行时点前像整支失效）", "cls", mdcos.MdCGOS,
     "_mutation_execute",
     '            pre = _rb.preimage(self, act, tgt, pid=item.get("pid"),\n'
     '                               reason="变更单执行时点前像（%s→%s，pid=%s）"\n'
     '                                      % (act, tgt, item.get("pid") or "?"))',
     '            pre = None', 8),
    # ⑯ 执行时点补全摘除（批次③）——accept 返回/落盘的都是提议时点占位载荷
    # （三字段保持 None/""，executed/kind 也不补）。
    # 红 9（实测）：K 组字段判据除「提议时点三键占位」外整体红（语义相符）。
    ("执行时点补全摘除（mutation_executed 空转）", "mod", autonomy_modes,
     "mutation_executed",
     '    out = dict(payload or {})\n    out["kind"] = KIND_MUTATION',
     '    return dict(payload or {})\n'
     '    out = dict(payload or {})\n    out["kind"] = KIND_MUTATION', 9),
    # ⑰ 补强批次 v1.2·U1——**直写面档位闸摘除**（不限档位放行）：`mdcg_remember`
    # 非 gated 直写分支的档位判定被短路 ⇒ plan/confirm 两档 C 覆写从「出单且
    # 不落盘」变「直落且正文被覆写」（复核 V4' 的**摘除形态**；接入前该注入在
    # 现行树 0 红存活——M1e 即为解除项）。
    # 红 3（实测）：M1e①②（plan 档：出单体 + 正文未改/队列 1 张，直落后两条皆
    # 不成立）+ M1e③（confirm 档同形）。M1e④⑤（full 直落）语义相符仍绿。
    ("直写面档位闸摘除（mdcg_remember 非 gated 分支放行）", "mod", mcp_server,
     "_dispatch",
     '        _dec = _am.decide(_action)\n'
     '        if _dec["decision"] != _am.ALLOW:',
     '        _dec = {"mode": "", "action": _action, "action_name": "",\n'
     '                "decision": _am.ALLOW, "hint": ""}\n'
     '        if False:', 3),
    # ⑱ 补强批次 v1.2·U1——**直写面 plan 档旁路**（复核 V4' 的**追加式注入形态**，
    # 逐字复刻其 payload）：判据行之后追加「plan 档 C 覆写放行」——只有 plan 档
    # 转红（confirm 档不受影响）。两条形态成对：⑰ 证「闸在，不限档位摘除必红」，
    # ⑱ 证「plan 档单点放行必红」。
    # 红 2（实测）：M1e①②。
    ("直写面 plan 档旁路（复核 V4' 注入形态）", "mod", mcp_server, "_dispatch",
     '        _dec = _am.decide(_action)',
     '        _dec = _am.decide(_action)\n'
     '        if _am.mode() == "plan" and _action == _am.C_REWRITE '
     'and _dec["decision"] == _am.CONFIRM:\n'
     '            _dec = dict(_dec, decision=_am.ALLOW)', 2),
    # ⑲ 补强批次 v1.2·E 面——**闸无差别阻塞**（「E 接线只在 plan 档生效」的反向
    # 形态）：`e_gate` 恒判 FORBID ⇒ confirm/full 两档的 E 写盘一并被拦。
    # 红 5（实测）：M2③（confirm 照落）+ M2④（confirm↔full 对拍）+ M2⑦（weights
    # confirm）+ M2⑨（set_state confirm）+ M2⑪（backfill confirm）；plan 档判据
    # （M2①②⑥⑧⑩）语义相符仍绿——**这一分布就是「只在 plan 档生效」的机械证据**。
    ("E 面闸无差别阻塞（confirm/full 也被拦）", "mod", autonomy_modes, "e_gate",
     '    return decide(E_WEIGHT, plan=plan, environ=environ)',
     '    return dict(decide(E_WEIGHT, plan=plan, environ=environ),\n'
     '                decision=FORBID)', 5),
    # ⑳ 补强批次 v1.2·E 面——**接线摘除·freshness.recalc**（apply 路径的档位闸
    # 短路）⇒ plan 档 E 照跑写盘（即复核实测的 importance/freshness 写盘形态）。
    # 红 2（实测）：M2①②。
    ("E 面接线摘除·freshness.recalc", "mod", freshness, "recalc",
     '        from . import autonomy_modes as _am\n'
     '        _dec = _am.e_gate()\n'
     '        if _dec["decision"] != _am.ALLOW:\n'
     '            return _am.forbidden_result(_dec, action="freshness", '
     'dry_run=False,\n'
     '                                        written=0, batch=batch)',
     '        pass', 2),
    # ㉑ 补强批次 v1.2·E 面——**接线摘除·weights.recalc**（第二写盘入口）。
    # 红 1（实测）：M2⑥。
    ("E 面接线摘除·weights.recalc", "mod", weights, "recalc",
     '        from . import autonomy_modes as _am\n'
     '        _dec = _am.e_gate()\n'
     '        if _dec["decision"] != _am.ALLOW:\n'
     '            return _am.forbidden_result(_dec, action="importance", '
     'dry_run=False,\n'
     '                                        written=0, batch=batch)',
     '        pass', 1),
    # ㉒ 补强批次 v1.2·E 面——**接线摘除·lifecycle.set_state**（唯一推进入口，
    # 含 `MdCG.set_state` 委托面）。
    # 红 1（实测）：M2⑧。
    ("E 面接线摘除·lifecycle.set_state", "mod", _lc, "set_state",
     '    from . import autonomy_modes as _am\n'
     '    _dec = _am.e_gate()\n'
     '    if _dec["decision"] != _am.ALLOW:\n'
     '        out = _am.forbidden_result(_dec, node_id=node_id, changed=False)\n'
     '        out.update({"from": src, "to": dst, "code": "autonomy_forbidden"})\n'
     '        return out',
     '    pass', 1),
    # ㉓ 补强批次 v1.2·E 面——**接线摘除·lifecycle.backfill**（第二写盘入口）。
    # 红 1（实测）：M2⑩。
    ("E 面接线摘除·lifecycle.backfill", "mod", _lc, "backfill",
     '    from . import autonomy_modes as _am\n'
     '    _dec = _am.e_gate()\n'
     '    if _dec["decision"] != _am.ALLOW:\n'
     '        return _am.forbidden_result(_dec, dry_run=False, scanned=len(nodes),\n'
     '                                    missing=len(missing), backfilled=0)',
     '    pass', 1),
    # ㉔ 补强批次 v1.2·E 面——**闸越过 apply 边界**（接在预演面之前）：在
    # `freshness.recalc` 函数体首行插入同一判定 ⇒ plan 档**预演**（apply=False）
    # 也被拦——「闸只在 apply 路径」这条判据（M2⑤）的判别形态。
    # 红 1（实测）：M2⑤（apply 路径的 plan 判据仍绿——注入块与真闸的返回体同形，
    # 语义相符）。
    ("E 面闸越过 apply 边界（预演面也被拦）", "mod", freshness, "recalc",
     '    nodes = (getattr(cg, "index", None) or {}).get("nodes") or {}',
     '    from . import autonomy_modes as _am\n'
     '    _dec0 = _am.e_gate()\n'
     '    if _dec0["decision"] != _am.ALLOW:\n'
     '        return _am.forbidden_result(_dec0, action="freshness",\n'
     '                                    dry_run=not apply, written=0)\n'
     '    nodes = (getattr(cg, "index", None) or {}).get("nodes") or {}', 1),
)

#: 「防误删自检」的判别力钉（F1 收口，2026-10-03）——**不占表内编号**：表长恒 =
#: `_MUTATION_IDS` 的长度（复核口径「24 处」与实存一致）；它是自检体系的判别力
#: 证明，形态与表内条目**同口径**：源码替换 + exec 重装 + 红项数比照，锚点同样
#: 过 `_anchor_check`（漂移即 ANCHOR-MISS、fail-closed）。
#: 剥掉 `_table_gaps` 的自检开关（恒判「完好」）⇒ 三条合成源自证测例（F1①②④）
#: 转红——证明「删条目即机械报错」不是空转。红 3（实测）；F1③（真实表期望 []）
#: 语义相符仍绿。
_SELFCHECK_MUTATION = (
    "防误删自检开关剥除（_table_gaps 恒判完好）", "mod", _THIS, "_table_gaps",
    'def _table_gaps(text, entries_count, ids=_MUTATION_IDS):\n'
    '    """变异表完整性判定（纯函数）：返回缺口说明列表（空 = 完好）。',
    'def _table_gaps(text, entries_count, ids=_MUTATION_IDS):\n'
    '    return []\n'
    '    """变异表完整性判定（纯函数）：返回缺口说明列表（空 = 完好）。', 3)


# ---- 变异表完整性自检（F1 收口：防误删，2026-10-03）------------------------
# 由来：F1 复查发现第③条元组被删（仅剩注释）而无人察觉（数字只存文档/注释、
# 无自动核验载体）——本自检把「编号无缺口 + 表长与显式声明一致」变成机械判据：
# 缺项 ⇒ fail-closed 退出码 2 并报缺口编号（不再靠人工发现）。与 `_anchor_check`
# 同层接入（正常运行与 --mutate 均先行执行），配判别力钉 `_SELFCHECK_MUTATION`
# （剥掉自检开关 ⇒ 合成源自证测例转红 3）证明它有判别力。
# 基线源＝**当前工作区文件**，不绑 git HEAD。
#
# 判据（`_table_gaps`，纯函数——自证测例以合成源调它）：
#   a. 编号注释被下一**不同**编号注释覆盖（= 删元组留注释，F1 原形）⇒ 报该编号
#      （同编号在块内的复提不算——⑱ 块先例）；
#   b. 编号注释序列与声明不一致（缺/重复；含「注释与元组同删」的真删形态）⇒
#      报缺者；
#   c. len(_SRC_MUTATIONS) ≠ 声明长度 ⇒ 报「len:23≠24」兜底（防共用注释等边角）。
_MUTATION_IDS = ("①", "②", "③", "④", "⑤", "⑥", "⑦", "⑧", "⑨", "⑩",
                 "⑪", "⑫", "⑬", "⑭", "⑮", "⑯", "⑰", "⑱", "⑲", "⑳",
                 "㉑", "㉒", "㉓", "㉔")

_ANNOT_RE = re.compile(r"^    # ([①-⑳㉑-㉔])")


def _table_lines(text):
    """取 `_SRC_MUTATIONS = (` 到首个独立 `)` 行之间的表体行（当前源，非 git 基线）。"""
    out, on = [], False
    for line in text.split("\n"):
        if not on:
            if line.startswith("_SRC_MUTATIONS = ("):
                on = True
            continue
        if line.rstrip() == ")":
            break
        out.append(line)
    return out


def _table_gaps(text, entries_count, ids=_MUTATION_IDS):
    """变异表完整性判定（纯函数）：返回缺口说明列表（空 = 完好）。"""
    annot, gaps, pending = [], [], None
    for line in _table_lines(text):
        m = _ANNOT_RE.match(line)
        if m:
            nid = m.group(1)
            if pending is None:
                pending = nid
                annot.append(nid)
            elif nid != pending:
                gaps.append(pending)      # a. 上一编号注释未被元组消费
                pending = nid
                annot.append(nid)
            # nid == pending：同一条目注释块内的复提（如 ⑱ 块内「⑱ 证…」行）——
            # 不构成新条目注释、不覆盖 pending（否则会把该块判成「缺条目」）。
            continue
        if pending is not None and line.startswith("    ("):
            pending = None                # 元组消费其上最近的编号注释
    if pending is not None:
        gaps.append(pending)              # 表尾仍有未消费的编号注释
    for i in ids:
        if i not in annot:
            gaps.append(i)                # b. 编号缺（含注释与元组同删的形态）
        elif annot.count(i) > 1:
            gaps.append(i)                # b. 编号重复
    if entries_count != len(ids):
        gaps.append("len:%d≠%d" % (entries_count, len(ids)))   # c. 表长兜底
    seen, uniq = set(), []
    for g in gaps:
        if g not in seen:
            seen.add(g)
            uniq.append(g)
    return uniq


def _table_integrity_check():
    """变异表完整性自检（真实表/当前工作区源）：返回缺口说明列表（空 = 完好）。"""
    with io.open(os.path.abspath(__file__), encoding="utf-8") as f:
        text = f.read()
    return _table_gaps(text, len(_SRC_MUTATIONS))


def _fn_src(target):
    """变异锚点所在源码：`mod`/`cls` = 目标函数源码；`attr` = 属主源码（模块整体）。"""
    kind, owner, name = target
    if kind == "attr":
        return inspect.getsource(owner)
    return inspect.getsource(getattr(owner, name))


def _strip_indent(text: str, n: int) -> str:
    """按 n 列去缩进（首 n 列全空白的行才截，其余行 lstrip——防把空行/续行搞错）。"""
    if not n:
        return text
    out = []
    for line in text.split("\n"):
        if line[:n].strip() == "":
            out.append(line[n:])
        else:
            out.append(line.lstrip())
    return "\n".join(out)


def _anchor_check():
    """返回 ANCHOR-MISS 说明列表（空 = 全部在位）——含自检判别力钉。"""
    bad = []
    for name, _kind, owner, fname, old, _new, _n in (_SRC_MUTATIONS
                                                     + (_SELFCHECK_MUTATION,)):
        if old not in _fn_src((_kind, owner, fname)):
            bad.append("变异锚点缺失：%r @%s.%s" % (old[:40], owner.__name__, fname))
    return bad


@contextlib.contextmanager
def _patched(target, old, new):
    """把目标函数按字面替换变异后安装/还原（不落盘、不改源文件）。

    接线点一律经**模块属性/类属性**在调用时解析（`_am.decide(...)` /
    `self._autonomy_gate_merge(...)`），故 setattr 后全部出口同闸生效；
    写链的档位闸是注册期绑定，故夹具每组现建 pipeline（见 `_pipe`）。
    """
    kind, owner, name = target
    if kind == "attr":
        # 常量型变异：把属主（模块/类）的该属性换成 `new` 求值出的新值。
        # 为什么需要它：SHIM 登记（`_SHIMS` 元组）是**数据**不是函数体，源码替换
        # 无从下手；而「登记丢失」正是补强批次修的那处判据，必须有定点变异钉死。
        live = getattr(owner, name)
        setattr(owner, name, eval(new, dict(vars(owner))))    # noqa: S307
        try:
            yield
        finally:
            setattr(owner, name, live)
        return
    # 方法源码自带类内缩进（def 行 4 空格、体内 8 空格）→ 必须先按 def 行的缩进
    # 整块去缩进才可在模块级 exec；锚点/替换文按**同一**缩进量规整后匹配，
    # 故表里写的是「源码原文形态」（与 _anchor_check 的判据同一份字面量）。
    src = _fn_src(target)
    cut = len(src) - len(src.lstrip(" "))
    src2 = _strip_indent(src, cut)
    old2 = _strip_indent(old, cut)
    new2 = _strip_indent(new, cut)
    if old2 not in src2:
        raise AssertionError("变异锚点在去缩进后仍不匹配：%r" % old[:40])
    src = src2.replace(old2, new2)
    if kind == "mod":
        ns = dict(vars(owner))
        ns["__name__"] = owner.__name__
    else:
        ns = dict(vars(sys.modules[owner.__module__]))
        ns["__name__"] = owner.__module__
    exec(compile(src, "am_mut.py", "exec"), ns)
    live = getattr(owner, name)
    setattr(owner, name, ns[name])
    try:
        yield
    finally:
        setattr(owner, name, live)


def _run_one_mutation(item):
    """执行单条定点变异并比照红项数；返回 None（命中预期）或条目名（不符）。"""
    name, kind, owner, fname, old, new, expect = item
    _RUN[0] += 1
    try:
        with _patched((kind, owner, fname), old, new), \
                contextlib.redirect_stdout(io.StringIO()):
            fails = _run_groups()
    except Exception as exc:        # noqa: BLE001 —— 变异把路径打断也算「红」
        fails = -1
        print("  变异「%s」→ 断言链抛异常 %s: %s（判 FAIL）"
              % (name, type(exc).__name__, str(exc)[:80]))
    verdict = ("命中预期" if fails == expect
               else "**红项数不符（预期 %d）**" % expect)
    print("  变异「%s」→ 红项=%d  %s" % (name, fails, verdict))
    for f in _FAIL[:6]:
        print("      红:", f)
    if len(_FAIL) > 6:
        print("      …（余 %d 项）" % (len(_FAIL) - 6))
    return None if fails == expect else name


def _mutate_mode():
    bad = []
    anchor_bad = _anchor_check()
    gap_bad = _table_integrity_check()
    if anchor_bad or gap_bad:
        for b in anchor_bad:
            print("  ANCHOR-MISS " + b)
        for b in gap_bad:
            print("  变异表缺口：" + b)
        print("\n锚点/完整性自检：FAIL（fail-closed，exit 2）")
        return 2
    with contextlib.redirect_stdout(io.StringIO()):
        clean = _run_groups()
    print("  未变异基线：红项=%d%s"
          % (clean, "" if clean == 0 else "  ← 基线即红，变异核验无意义"))
    if clean:
        bad.append("未变异基线即失败")
    _RUN[0] = 10 ** 6      # 变异轮用独立子根（防读到上一轮盘面/限流状态）
    print("  表内条目：%d 处（编号 %s–%s；防误删自检保证无缺口、表长与声明一致）"
          % (len(_SRC_MUTATIONS), _MUTATION_IDS[0], _MUTATION_IDS[-1]))
    for item in _SRC_MUTATIONS:
        r = _run_one_mutation(item)
        if r:
            bad.append(r)
    # 防误删自检的判别力钉（不占表内编号——表长与声明恒等，见 _SELFCHECK_MUTATION）
    r = _run_one_mutation(_SELFCHECK_MUTATION)
    if r:
        bad.append(r)
    print("\n定点变异自证：%s"
          % ("PASS（每处判据都有变异钉死，且红项数逐处吻合）" if not bad
             else "FAIL —— " + "、".join(bad)))
    return 0 if not bad else 1


def _print_reds():
    for f in _FAIL:
        print("    红:", f)


def main() -> int:
    src = os.path.basename(os.path.abspath(__file__))
    if "--mutate" in sys.argv:
        print("!! 定点变异模式：逐个变异判据，套件应转红且红项数吻合\n")
        try:
            return _mutate_mode()
        finally:
            shutil.rmtree(_SANDBOX, ignore_errors=True)
    anchor_bad = _anchor_check()
    gap_bad = _table_integrity_check()
    if anchor_bad or gap_bad:
        for b in anchor_bad:
            print("  ANCHOR-MISS " + b)
        for b in gap_bad:
            print("  变异表缺口：" + b)
        print("\n锚点/完整性自检：FAIL（fail-closed，exit 2）"
              "——实现/变异表改了请同步")
        return 2
    print("锚点自检：PASS（%s；不以 git HEAD 为基线源）" % src)
    print("变异表完整性自检：PASS（编号 %s–%s 无缺口、表长 %d = 声明——"
          "删条目即 fail-closed，F1 收口）"
          % (_MUTATION_IDS[0], _MUTATION_IDS[-1], len(_MUTATION_IDS)))
    try:
        for g in _GROUPS:
            g()
    finally:
        _RUN[0] += 1
    print("\n三档自治档位守卫：%d 通过，%d 失败" % (len(_PASS), len(_FAIL)))
    if _FAIL:
        _print_reds()
    return 0 if not _FAIL else 1


if __name__ == "__main__":
    try:
        rc = main()
    finally:
        shutil.rmtree(_SANDBOX, ignore_errors=True)
        os.environ.pop("MDCG_POLICY_FILE", None)
        if _OLD_POLICY is not None:
            os.environ["MDCG_POLICY_FILE"] = _OLD_POLICY
        os.environ.pop(_ENV_MODE, None)
    sys.exit(rc)
