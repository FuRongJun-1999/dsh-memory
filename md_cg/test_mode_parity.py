# -*- coding: utf-8 -*-
"""md_cg · 三档自治「不动面对拍 ＋ 端到端回滚演练」守卫（设计 v0.2 §十一 · 收官批次⑤）

本守卫承载设计 §十一 验收判据的**两路对拍**与**跨面回滚演练**（§十三.5 步骤⑤）：

  **P 组 · 切档对拍（同一合成库 confirm↔full）**——非破坏性动作 **A 新增**
  （写链面）与 **E 权重与生命周期**（`freshness.recalc` / `weights.recalc`，批
  ③留池第 7 条「E 分数类」在档位面的行为读数）在切档前后输出**逐位不变**：
    · A：两臂各写两次**首写（A 新增，不同新 id、同正文）**——第一次都在 confirm
      （两臂同起点锚），第二次分属 full（切档臂）与 confirm（对照臂）：比的就是
      「同一无歧义操作在切档前后是否同值」。**同 id 重放不比较**（第二次是覆写，
      confirm/full 语义本就分叉，不属 A/E 对拍范围）；
    · E：同一库里「落 → **既有 rollback**（设计 §四 第 4 条：分数类用各模块
      既有 rollback）→ 切档 → 再落」两轮读数与落盘 fm 逐位相等；
    · 「切档本身零写入」：库盘面指纹（全文件 sha256）跨 env 切换逐位相同；
    · 「切档锚不空转」：切到目标档后 `autonomy_modes.mode()` 读回该档（防
      「切了个寂寞」——定点变异①实测打红的就是这条（full 臂）+ R4 四条直落判据）。
  **plan 档不并入本对拍**（无计划时 A/E 的 forbid 是设计内语义，单独钉在
  `test_autonomy_modes.g_m` 的 M2 组）。

  **Q 组 · 与改动前基线的 oracle 对拍（`git archive HEAD` 只读导出）**——
  步骤③ 复核同款装置：把 HEAD 树只读导出到系统临时目录作 oracle，同一观测
  脚本（`_RUNNER`，守卫生成）对**两棵树**各跑一遍，**A/E 全线 ＋ full 档全线**
  逐位比对，打印 SAME/DIFF 清单（报告引用）。
    · **基线口径（防「基线绑提交即失效」，本仓已有两次教训）**：oracle 是
      **每次运行现导出**的 HEAD 树（参照物），本守卫**不含任何某一提交派生的
      字面量期望值**——判据是「同一脚本在两棵树上的输出是否逐位一致」，两棵树
      都由 git 与工作区现状现取；
    · **判别力＝负对照**：对导出的 HEAD 树副本**定点注入**写链 A 面差异（把
      A 新增也判成需确认），对拍必须报 DIFF **且 DIFF 项恰好命中预期集合**
      （SAME 集合不变）——对拍机制不空转的机械证明；
    · git 不可用 / 导出失败 / 导出树缺 md_cg ⇒ `ORACLE-MISS` 打印后退出码
      **2**（fail-closed，不静默跳过）。

  **R 组 · 端到端回滚演练（跨面，含子进程 CLI 实测）**——不是守卫级单呼：
    · confirm 档三条链各一遍（**三个不同入口面**）：C 改写经**写链**
      （`cg(op=write)`）/ B 合并经**插件面**（`mdcg_remember(gated=true)`）/
      D 删除经**工具面**（`cg(op=forget)`）——每条链「出单 → 裁决 accept
      （**执行桥**）→ 回滚 **`md_cg.rollback_cli` 子进程**实测 → 逐字节比对
      前像 → 残差核对（索引/边/聚合行三面）＋索引条目与前像重算逐位对拍」；
    · full 档三条链各一遍：**直落**（无单、零变更单）→ 统一回滚入口回滚 →
      逐字节比对前像 + 残差三面；
    · **空池口径（补强批次 v1.2·U2 收口）**：一切「逐字节 == 前像」判据一律
      **非空前置**（`bool(pre_b)` 门槛）——两侧皆空（`b""`）时**判红、不静默
      判绿**（与 `_bytes` 的「缺失 ⇒ 判不相等」声明一字一致）；R4 三条 full 链
      另加**执行时点前像 ＋ 盘面快照双非空取证**（收口前复核探针实测「R 组红 3 /
      绿 30」——R2、R3-逐字节、R4 三条的第三合取项在两侧皆空时静默判绿）。
      判别力由定点变异「`_bytes` 恒空」承担（收口后这些判据必须全部转红）。
    · 边界（如实登记，非背书）：full 档直落**不产变更单、不自动拍前像**
      ——设计 §六 义务①「一切破坏性动作先留前像」在 full 直落路径**未接线**
      （留池；收官报告登记）。故 full 档链的「回滚」＝演练侧按执行时点拍前像
      （`protect.snapshot_preimage` 单点，与执行桥同一函数）后走统一回滚入口
      ——证明**回滚原语对 full 档直落形态可用**；生产全自动前像待接线。

定点变异自证（`--mutate`，与 `md_cg/test_neg_condition_hits.py` 同口径）：表内
每项 = (说明, 目标, 锚点原文, 替换文, 预期红项数)。锚点须**逐字**出现在目标函数
源码里；漂移即 ANCHOR-MISS（fail-closed，exit 2）。红项数与实测**逐一相符**才算
通过——不符即 FAIL（多红=断言越界、少红=该判据无判别力）。

**F1 收口（2026-10-03）——防误删自检**（与 `md_cg/test_autonomy_modes.py`
**两守卫对齐**）：新增**变异表完整性自检**（`_table_gaps` /
`_table_integrity_check`：编号无缺口 ＋ 表长与显式声明 `_MUTATION_IDS` 一致；
缺项 ⇒ fail-closed 退出码 2 并报缺口编号）——今后删条目即机械报错，不再靠人工
发现。判别力由 G 组 `g_s` 合成源自证测例（F1①–④，随 `--mutate` 每轮同跑）＋
内置判别力钉 `_SELFCHECK_MUTATION`（剥掉自检开关 ⇒ 自证测例转红 3）钉死。

沙箱（硬约束）：一切读写都在 tempfile.mkdtemp 内（含 MDCG_AUX_ROOT / 主密钥 /
policy——crypto 在导入期求值 MASTER_FILE，故必须在任何 md_cg 子模块 import
**之前**设好）；oracle 导出树、观测脚本、合成库全在系统临时区；跑完 rmtree。
**绝不碰在役数据根**。档位 env 由夹具按需设置并在 finally 还原。

运行：
  python -X utf8 -m md_cg.test_mode_parity              # 正常跑（含 oracle 路由）
  python -X utf8 -m md_cg.test_mode_parity --no-oracle   # 跳过 oracle 路由（本地调试）
  python -X utf8 -m md_cg.test_mode_parity --mutate      # 定点变异自证
"""
from __future__ import annotations

import contextlib
import hashlib
import inspect
import io
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import tarfile
import tempfile
import time

# ---- 沙箱：必须在任何 md_cg 子模块 import 之前 ------------------------------
_SANDBOX = tempfile.mkdtemp(prefix="mode_parity_sandbox_")
os.environ["MDCG_AUX_ROOT"] = _SANDBOX
os.environ["MDCG_ROOT"] = os.path.join(_SANDBOX, "root")
os.environ["MDCG_MASTER_KEY"] = os.urandom(32).hex()
os.environ.pop("MDCG_TEST_LIVE_ROOT", None)
_OLD_POLICY = os.environ.pop("MDCG_POLICY_FILE", None)

from . import autonomy_modes, forgetting, nodefile, protect, rollback  # noqa: E402
from . import writepipe, freshness, weights                            # noqa: E402
from . import mcp_server                                               # noqa: E402
from .mdcos import MdCGOS                                              # noqa: E402

_ENV_MODE = autonomy_modes.AUTONOMY_ENV_KEYS["mode"]

_PASS = []
_FAIL = []
_RUN = [0]


def ok(cond, msg, extra=""):
    (_PASS if cond else _FAIL).append(msg)
    print(("  PASS " if cond else "  FAIL ") + msg
          + (("  ← " + str(extra)) if (extra and not cond) else ""))


def _policy():
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
    old = os.environ.get(_ENV_MODE)
    os.environ[_ENV_MODE] = m
    try:
        yield m
    finally:
        if old is None:
            os.environ.pop(_ENV_MODE, None)
        else:
            os.environ[_ENV_MODE] = old


def _pipe():
    return writepipe.install_default_gates(writepipe.WritePipeline())


def _repo_root():
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _pre_path(cg, rel):
    return os.path.join(cg.root, str(rel).replace("/", os.sep))


def _bytes(path):
    """读字节：路径缺失/不可读 ⇒ `b""`（判据按「不相等」处理，**不抛**——
    定点变异会把前像/落点打断，判红由断言承担，不让异常打断整组）。"""
    if not path:
        return b""
    try:
        with open(path, "rb") as f:
            return f.read()
    except OSError:
        return b""


def _disk_path(cg, nid):
    """节点盘面绝对路径；条目缺失 ⇒ None（同一 fail-closed 口径，不抛）。"""
    e = ((getattr(cg, "index", None) or {}).get("nodes") or {}).get(nid) or {}
    p = e.get("path")
    return os.path.join(cg.root, p) if p else None


def _refresh(cg):
    cg._maybe_reload_index()


def _run_cli(cmd):
    """**实测演练回滚命令串**（子进程 CLI）：切分 → `python` 换本进程解释器。

    shlex 用 posix=False（Windows 路径的反斜杠在 posix 模式会被当转义字符）；
    只替换首令牌 `python`，其余令牌逐字来自字段（演练的是字段里的那条串）。
    """
    argv = shlex.split(cmd, posix=False)
    argv = [a[1:-1] if len(a) >= 2 and a[0] == a[-1] == '"' else a for a in argv]
    if not argv:
        return {"rc": -1, "out": "", "err": "empty rollback command", "json": None}
    if argv[0] == "python":
        argv[0] = sys.executable
    p = subprocess.run(argv, capture_output=True, text=True, encoding="utf-8",
                       errors="replace", cwd=_repo_root(),
                       env=dict(os.environ, PYTHONUTF8="1"))
    try:
        out_json = json.loads((p.stdout or "").strip().splitlines()[-1])
    except Exception:                                          # noqa: BLE001
        out_json = None
    return {"rc": p.returncode, "out": p.stdout or "", "err": p.stderr or "",
            "json": out_json}


def _fingerprint(root):
    """库盘面指纹：root 下全部文件 (相对路径, sha256)——「零写入」判据的单点。"""
    out = {}
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d != "__pycache__"]
        for fn in filenames:
            p = os.path.join(dirpath, fn)
            rel = os.path.relpath(p, root).replace("\\", "/")
            try:
                with open(p, "rb") as f:
                    out[rel] = hashlib.sha256(f.read()).hexdigest()
            except OSError:
                out[rel] = "<unreadable>"
    return out


def _entry_from_preimage(cg, nid, rel):
    """按前像文件重算索引条目（与 _node_entry 同源）——回滚后索引对拍的基准。

    前像缺失/不可读 ⇒ None（调用方判 False ⇒ 红；不抛——变异场景专用口径）。
    """
    if not rel or not _disk_path(cg, nid):
        return None
    try:
        with open(_pre_path(cg, rel), encoding="utf-8") as f:
            fm, c = nodefile.loads(f.read())
    except OSError:
        return None
    return cg._node_entry(_disk_path(cg, nid), str(fm.get("layer") or "knowledge"),
                          fm, c)


def _mut_entries(cg):
    return [r for r in cg.review_list()
            if autonomy_modes.order_kind(r) == "mutation"]


def _pims(cg, nid):
    """protect 审计面里某节点的 `action=="preimage"` 行（只读，不抛）。"""
    p = os.path.join(cg.root, protect.AUDIT_FILE)
    out = []
    try:
        with open(p, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    r = json.loads(line)
                except ValueError:
                    continue
                if r.get("action") == "preimage" and r.get("node_id") == nid:
                    out.append(r)
    except OSError:
        return []
    return out


#: 对拍要剔除的**时钟面/耗时面**键——两次运行必然不同，与档位/版本无关。
#: 剔除不算放水：对拍的判据是「档位（或版本）有没有改变行为」，不是「时间戳
#: 与耗时是否相同」。与 `test_autonomy_modes._VOLATILE` 同族同口径。
_VOLATILE = ("t", "created_at", "last_access", "time_window", "last_merge_at",
             "batch", "note", "elapsed_ms", "updated_at")
#: 聚合行的时间戳标记（`- 【聚合 月-日 时:分】…`，`forgetting.aggregate_line`
#: 生成）——同一族的时钟面文本，跨运行必然不同，比对前掩码为 `<ts>`。
_AGG_RE = re.compile(r"【聚合 [^】]*】")
#: 提案 id 的**熵面**掩码：`propose` 的 pid ＝ `prop_` + 内容签名(node_id ＋
#: `time.time()` ＋ `uuid4().hex`)（`mdcos.propose` 实读）——含时钟与随机熵，
#: 两次运行必然不同（`test_review_conformance【8】` 以「20 条互异」钉它）。
#: pid 是**身份面**不是行为面：对拍比的是「档位/版本有没有改变行为」，故掩码。
_PID_RE = re.compile(r"prop_[0-9a-f]{8,}")


def _strip(d):
    """递归剔除时钟面键 + 掩码聚合行时间戳/pid 熵面，返回可逐位比较的结构。"""
    if isinstance(d, dict):
        return {k: _strip(v) for k, v in d.items() if k not in _VOLATILE}
    if isinstance(d, list):
        return [_strip(x) for x in d]
    if isinstance(d, str):
        return _PID_RE.sub("prop_<id>", _AGG_RE.sub("【聚合 <ts>】", d))
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


# =========================================== P 组：切档对拍（同库 confirm↔full）
def g_p():
    print("== P 组：切档对拍（同一合成库 confirm↔full · 非破坏性动作 A/E）==")
    _policy()
    # ---- P1 A 新增：切档臂（confirm→full） vs 同档对照臂（confirm→confirm）----
    # 两臂各写两次**首写**（不同新 id、同正文）：第一次都在 confirm（两臂同
    # 起点锚），第二次分属 full（切档臂）与 confirm（对照臂）——比的就是「同一
    # 无歧义操作（A 新增）在切档前后是否同值」。**不比较同 id 重放**：同 id
    # 第二次是覆写（C 改写），confirm/full 语义本就分叉，不属本对拍范围。
    arms = {}
    for tag, second in (("p_no2full", "full"), ("p_no2no", "confirm")):
        cg = _lib(tag)
        pipe = _pipe()
        with _mode("confirm"):
            o1 = pipe.execute(cg, {"content_kind": "text", "content": PLAIN % "对拍",
                                   "layer": "knowledge", "node_id": "p_a1"})
            fp_run = _fingerprint(cg.root)
        with _mode(second):
            fp_sw = _fingerprint(cg.root)
            ok(fp_run == fp_sw,
               "P 切档本身零写入：库盘面指纹跨 confirm→%s 切换逐位相同"
               "（%d 文件）" % (second, len(fp_run)),
               sorted(set(fp_run) ^ set(fp_sw))[:4])
            ok(autonomy_modes.mode() == second,
               "P 切档锚不空转：切到 %s 后 mode() 读回 %s（命中控值）"
               % (second, second), autonomy_modes.mode())
            o2 = pipe.execute(cg, {"content_kind": "text", "content": PLAIN % "对拍",
                                   "layer": "knowledge", "node_id": "p_a2"})
            node = _strip(cg.get("p_a2") or {})
        arms[tag] = (_strip(o1), _strip(o2), node)
        cg.close()
    ok(arms["p_no2full"][0] == arms["p_no2no"][0],
       "P1 两臂同起点锚：confirm 档首写（A 新增）读数**逐位相等**"
       "（两库结构等价 ⇒ 后续比对可比）",
       {"switch": arms["p_no2full"][0].get("committed"),
        "control": arms["p_no2no"][0].get("committed")})
    ok(arms["p_no2full"][1] == arms["p_no2no"][1],
       "P1 A 新增（切档核心判据）：**full 档**首写读数（切档臂）与 **confirm 档**"
       "首写读数（对照臂）逐位相等——切档前后 A 逐位不变")
    ok(arms["p_no2full"][2] == arms["p_no2no"][2],
       "P1 落盘节点（正文与 fm，时钟面除外）：切档臂与对照臂逐位相等")

    # ---- P2 E 权重与生命周期：落 → 既有 rollback → 切档 → 再落 ----
    for name, mod, kw in (("freshness", freshness, {"now": 1700000000.0}),
                          ("weights", weights, {})):
        cg = _lib("p_e_" + name)
        with _mode("confirm"):
            cg.add("pe_1", BODY % "9090", layer="knowledge",
                   verification_basis="test", importance=0.4)
            cg.add("pe_2", PLAIN % "被引", layer="knowledge",
                   verification_basis="test",
                   edges=[{"target": "pe_1", "relation_type": "part_of"}])
            cg.flush()
            r1 = mod.recalc(cg, apply=True, min_delta=0.0001, **kw)
            fm1 = _strip(dict((cg.get("pe_1") or {}).get("frontmatter") or {}))
            rb = mod.rollback(cg)           # 既有回滚（设计 §四 第 4 条）
        fp_run = _fingerprint(cg.root)
        with _mode("full"):
            fp_sw = _fingerprint(cg.root)
            r2 = mod.recalc(cg, apply=True, min_delta=0.0001, **kw)
            fm2 = _strip(dict((cg.get("pe_1") or {}).get("frontmatter") or {}))
        ok(rb.get("ok") is True,
           "P2 %s 前置：既有 rollback 生效（两轮同起点；reverted=%s）"
           % (name, rb.get("reverted")), rb)
        ok(fp_run == fp_sw,
           "P2 %s 切档本身零写入：库盘面指纹跨切换逐位相同" % name)
        ok(_strip(r1) == _strip(r2),
           "P2 %s 读数：confirm 档与 full 档**逐位相等**（E 分数类不阻塞——"
           "设计 §三 confirm/full 列 E=允许）" % name, _strip(r1).get("written"))
        ok(fm1 == fm2,
           "P2 %s 落盘 fm（剔除时钟面）：confirm 档与 full 档逐位相等" % name,
           {k: (fm1.get(k), fm2.get(k)) for k in sorted(set(fm1) | set(fm2))
            if fm1.get(k) != fm2.get(k)})
        cg.close()


# ================================== Q 组：与改动前基线的 oracle 对拍（HEAD 导出）
#: 观测脚本（**守卫生成、跑在系统临时区**）：对给定源码树跑固定场景，输出
#: 规范化 JSON。同一份脚本跑「HEAD 导出树」与「工作树」两遍，逐项对拍。
_RUNNER = r'''# -*- coding: utf-8 -*-
"""对拍观测脚本（守卫生成，非仓内文件）：argv = 源码树 库根 输出JSON。"""
import json
import os
import re
import sys
import time

REPO, LIB, OUT = sys.argv[1], sys.argv[2], sys.argv[3]
SB = os.path.dirname(os.path.abspath(LIB))
os.environ["MDCG_AUX_ROOT"] = SB
os.environ["MDCG_ROOT"] = os.path.join(SB, "root")
os.environ["MDCG_MASTER_KEY"] = "0" * 64
os.environ.pop("MDCG_TEST_LIVE_ROOT", None)
_POL = os.path.join(SB, "policy.json")
with open(_POL, "w", encoding="utf-8") as f:
    json.dump({"forbidden": ["FORBIDDEN_WORD"], "required": ["PASSED"]}, f)
os.environ["MDCG_POLICY_FILE"] = _POL
sys.path.insert(0, REPO)

import md_cg  # noqa: E402
from md_cg import autonomy_modes as am, writepipe, forgetting, nodefile  # noqa: E402
from md_cg import freshness, weights                                      # noqa: E402
from md_cg import mcp_server                                              # noqa: E402
from md_cg.mdcos import MdCGOS                                            # noqa: E402

ENV = am.AUTONOMY_ENV_KEYS["mode"]
VOL = ("t", "created_at", "last_access", "time_window", "last_merge_at",
       "batch", "note", "elapsed_ms", "updated_at")
AGG = re.compile(r"【聚合 [^】]*】")
PID = re.compile(r"prop_[0-9a-f]{8,}")   # pid 含时钟+随机熵（身份面，掩码）
TS0 = 1700000000.0          # 固定观测时刻（E 分数类确定性的锚）
BODY = ("# 功能名：部署面端口约定\n"
        "# 生效条件：载体/位置：prod 集群；时间：2026-09-30 起；方法：部署清单核对；约束：无\n"
        "# 子功能：登记各服务监听端口\n"
        "# 执行：核对 manifest 的 ports 段\n"
        "# 验证方式：test\n"
        "# 不适用条件：无\n"
        "\n网关监听端口 8080/HTTP；管理面监听端口 8081/HTTP；"
        "指标面监听端口 %s/HTTP；日志面监听端口 9091/HTTP\n")
PLAIN = "PASSED 探针正文 %s"


def strip(d):
    if isinstance(d, dict):
        return {k: strip(v) for k, v in d.items() if k not in VOL}
    if isinstance(d, list):
        return [strip(x) for x in d]
    if isinstance(d, str):
        return PID.sub("prop_<id>", AGG.sub("【聚合 <ts>】", d))
    return d


def pipe():
    return writepipe.install_default_gates(writepipe.WritePipeline())


def lib(tag):
    return MdCGOS(os.path.join(LIB, tag), autoflush=0)


def mk_node(root, layer, nid, extra=None, content=None):
    """直写节点盘面（fm 时刻为**字面量**——E 分数类跨运行确定性的前提）。"""
    d = os.path.join(root, layer)
    os.makedirs(d, exist_ok=True)
    fm = {"id": nid, "layer": layer, "created_at": TS0 - 86400.0,
          "last_access": TS0 - 7200.0, "access_count": 3, "importance": 0.4}
    fm.update(extra or {})
    with open(os.path.join(d, nid + ".md"), "w", encoding="utf-8") as f:
        f.write(nodefile.dumps(fm, content if content is not None
                               else ("# 探针节点\n\n" + nid + "\n")))
    return root


# 档位 env 清场：键名经**真源表**取（`autonomy_modes.AUTONOMY_ENV_KEYS`），
# 不引第二处字面量——`test_autonomy_modes` G 组把这条钉死（首轮实测踩中）。
os.environ.pop(am.AUTONOMY_ENV_KEYS["mode"], None)

items = {}
prov = {"md_cg": os.path.dirname(os.path.abspath(md_cg.__file__))}
if os.path.abspath(prov["md_cg"]) != os.path.abspath(os.path.join(REPO, "md_cg")):
    raise SystemExit("观测脚本 import 到了非目标树的 md_cg：%s" % prov["md_cg"])

# 0. 纯函数面：缺省档 / 矩阵 / plan 档判定
os.environ.pop(ENV, None)
items["mode_default"] = {"mode": am.mode()}
items["matrix"] = {m: {a: am.MATRIX[m][a] for a in am.ACTION_CLASSES}
                   for m in am.AUTONOMY_MODES}
items["plan_decide"] = {a: am.decide(a, mode_explicit="plan")["decision"]
                        for a in am.ACTION_CLASSES}

# 1. A 新增（confirm 档写链面）
os.environ[ENV] = "confirm"
cg = lib("a")
out = pipe().execute(cg, {"content_kind": "text", "content": PLAIN % "对拍",
                          "layer": "knowledge", "node_id": "q_a"})
items["A_add"] = {"out": strip(out), "node": strip(cg.get("q_a") or {})}
cg.close()

# 2. 插件面 A 新增（mdcg_remember gated=true）
cg = lib("plg")
rm = mcp_server._dispatch(cg, "mdcg_remember",
                          {"content": PLAIN % "插件面", "node_id": "q_pl",
                           "gated": True, "layer": "knowledge"})
items["plg_A"] = {"out": strip(rm), "node": strip(cg.get("q_pl") or {})}
cg.close()

# 3. E 权重与生命周期（confirm 档：weights.recalc / freshness.recalc）
cg = lib("ew")
mk_node(cg.root, "knowledge", "e_a", {"verification_basis": "test"})
mk_node(cg.root, "knowledge", "e_b",
        {"verification_basis": "test",
         "edges": [{"target": "e_a", "relation_type": "part_of"}]})
cg.flush()
rw = weights.recalc(cg, apply=True, min_delta=0.0001)
items["E_weights"] = {"report": strip(rw),
                      "fm": strip(dict((cg.get("e_a") or {}).get("frontmatter") or {}))}
cg.close()

cg = lib("ef")
mk_node(cg.root, "knowledge", "f_a", {"verification_basis": "test"})
cg.flush()
rf = freshness.recalc(cg, apply=True, min_delta=0.0001, now=TS0)
items["E_fresh"] = {"report": strip(rf),
                    "fm": strip(dict((cg.get("f_a") or {}).get("frontmatter") or {}))}
cg.close()

# 4. full 档全线：A 新增（独立库）/ C 覆写 · B 合并 · D 删除（另一独立库——
#    负对照注入的写链 A 面差异不会级联到本库，DIFF 集合才可精确断言）
os.environ[ENV] = "full"
cg = lib("full_a")
items["full_A"] = {"out": strip(pipe().execute(cg, {
    "content_kind": "text", "content": PLAIN % "全访问A", "layer": "knowledge",
    "node_id": "fa"}))}
cg.close()

cg = lib("full_bcd")
pa = pipe()
cg.add("fc", PLAIN % "初版", layer="knowledge", verification_basis="test")
cg.flush()
items["full_C"] = {"out": strip(pa.execute(cg, {
    "content_kind": "text", "content": PLAIN % "全访问C", "layer": "knowledge",
    "node_id": "fc"})),
    "content": strip((cg.get("fc") or {}).get("content"))}
cg.add("fb", BODY % "9090", layer="knowledge", verification_basis="test")
cg.flush()
rb = cg.remember_gated("fb_n", BODY % "9595", layer="knowledge")
items["full_B"] = {"verdict": rb.get("verdict"),
                   "content": strip((cg.get("fb") or {}).get("content")),
                   "merge_count": ((cg.get("fb") or {}).get("frontmatter")
                                   or {}).get("merge_count")}
rd = cg.forget_gated("fb", reason="对拍探针")
items["full_D"] = {"out": strip(rd), "gone": cg.get("fb") is None,
                   "tombstoned": cg.is_tombstoned("fb"),
                   "trash": os.path.isfile(os.path.join(cg.root, "trash", "fb.md")),
                   "mut_orders": len([r for r in cg.review_list()
                                      if am.order_kind(r) == "mutation"])}
cg.close()

cg = lib("full_ew")
mk_node(cg.root, "knowledge", "g_a", {"verification_basis": "test"})
cg.flush()
items["full_E_weights"] = {"report": strip(weights.recalc(cg, apply=True,
                                                          min_delta=0.0001)),
                           "fm": strip(dict((cg.get("g_a") or {}).get("frontmatter")
                                            or {}))}
cg.close()
cg = lib("full_ef")
mk_node(cg.root, "knowledge", "h_a", {"verification_basis": "test"})
cg.flush()
items["full_E_fresh"] = {"report": strip(freshness.recalc(cg, apply=True,
                                                          min_delta=0.0001,
                                                          now=TS0)),
                         "fm": strip(dict((cg.get("h_a") or {}).get("frontmatter")
                                          or {}))}
cg.close()

# 5. plan 档热路径四面（读数面——对拍口径下两棵树必须一致）
os.environ[ENV] = "plan"
cg = lib("plan")
cg.add("pn", PLAIN % "初版", layer="knowledge", verification_basis="test")
cg.flush()
items["plan_C"] = {"out": strip(pipe().execute(cg, {
    "content_kind": "text", "content": PLAIN % "改写版", "layer": "knowledge",
    "node_id": "pn"})),
    "content": strip((cg.get("pn") or {}).get("content"))}
items["plan_D"] = {"out": strip(cg.forget_gated("pn", reason="对拍探针")),
                   "in_place": cg.get("pn") is not None}
cg.close()

with open(OUT, "w", encoding="utf-8") as f:
    json.dump({"provenance": prov, "items": items}, f, ensure_ascii=False,
              sort_keys=True)
print("RUNNER-OK", len(items))
'''


def _git_archive_head(dest):
    """`git archive HEAD` 只读导出整树到 dest（返回 None 成功 / 错误串失败）。"""
    try:
        p = subprocess.run(["git", "archive", "--format=tar", "HEAD"],
                           capture_output=True, cwd=_repo_root(),
                           env=dict(os.environ, PYTHONUTF8="1"))
    except OSError as exc:                                     # noqa: BLE001
        return "git 不可用：%s" % exc
    if p.returncode != 0:
        return "git archive 失败（rc=%s）：%s" % (
            p.returncode, (p.stderr or b"").decode("utf-8", "replace")[:200])
    os.makedirs(dest, exist_ok=True)
    try:
        with tarfile.open(fileobj=io.BytesIO(p.stdout)) as tf:
            try:
                tf.extractall(dest, filter="data")
            except TypeError:                  # Python < 3.12 无 filter 形参
                tf.extractall(dest)
    except (tarfile.TarError, OSError) as exc:                 # noqa: BLE001
        return "解包失败：%s" % exc
    if not os.path.isfile(os.path.join(dest, "md_cg", "mdcos.py")):
        return "导出树缺 md_cg/mdcos.py（非自洽树）"
    return None


def _run_scenario(repo, tag):
    """对给定源码树跑观测脚本，返回 (items, provenance)；失败返回 (None, 错误串)。"""
    lib_root = os.path.join(_SANDBOX, "scn_%s_r%d" % (tag, _RUN[0]))
    out_json = os.path.join(_SANDBOX, "scn_%s_r%d.json" % (tag, _RUN[0]))
    script = os.path.join(_SANDBOX, "parity_runner.py")
    with open(script, "w", encoding="utf-8") as f:
        f.write(_RUNNER)
    env = {k: v for k, v in os.environ.items()
           if not k.startswith("MDCG_")}
    env.update({"PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8"})
    p = subprocess.run([sys.executable, "-X", "utf8", script, repo, lib_root,
                        out_json],
                       capture_output=True, text=True, encoding="utf-8",
                       errors="replace", cwd=_SANDBOX, env=env)
    if p.returncode != 0 or not os.path.isfile(out_json):
        return None, ("rc=%s\n%s\n%s" % (p.returncode, (p.stdout or "")[-400:],
                                        (p.stderr or "")[-800:]))
    with open(out_json, encoding="utf-8") as f:
        blob = json.load(f)
    return blob, ""


#: 负对照的**定点差异**注入（改的是导出树副本，不是工作区）：
#: 把写链 A 新增也判成需确认——若对拍无判别力，这条差异会被漏掉。
_NEG_ANCHOR = "    dec = _am.decide(action)"
_NEG_INJECT = ('    dec = _am.decide(action)\n'
               '    if action == _am.A_ADD:\n'
               '        dec = dict(dec, decision=_am.CONFIRM)')


def g_q():
    print("== Q 组：与改动前基线的 oracle 对拍（git archive HEAD 只读导出）==")
    head_tree = os.path.join(_SANDBOX, "tree_head")
    err = _git_archive_head(head_tree)
    if err:
        print("  ORACLE-MISS " + err)
        print("\noracle 自检：FAIL（fail-closed，exit 2）")
        raise SystemExit(2)
    ok(True, "Q oracle 装置：git archive HEAD 只读导出到系统临时区（%s）"
       % ("md_cg/mdcos.py 在位"))

    cur, e1 = _run_scenario(_repo_root(), "cur")
    ok(cur is not None, "Q 观测脚本对**工作树**跑通（同一脚本、同一场景）", e1)
    ora, e2 = _run_scenario(head_tree, "head")
    ok(ora is not None, "Q 观测脚本对 **HEAD 导出树**跑通（同款装置，步骤③同口径）", e2)
    if cur is None or ora is None:
        print("\noracle 对拍：FAIL（观测脚本未跑通，fail-closed）")
        raise SystemExit(2)
    ok(ora["provenance"]["md_cg"].replace("\\", "/")
       .endswith("tree_head/md_cg"),
       "Q 探针自证：HEAD 路确实 import 了导出树（不是工作树）",
       ora["provenance"])
    names = sorted(cur["items"])
    same, diff = [], []
    for n in names:
        (same if cur["items"][n] == ora["items"][n] else diff).append(n)
    print("   SAME(%d): %s" % (len(same), "、".join(same)))
    print("   DIFF(%d): %s" % (len(diff), "、".join(diff) or "（无）"))
    ok(diff == [],
       "Q 不动面对拍：A/E 全线 + full 档全线 + plan 档读数——工作树与改动前"
       "基线（HEAD 导出树）**逐位一致**（%d 项 SAME / %d 项 DIFF）"
       % (len(same), len(diff)), diff)
    ok(len(names) >= 10,
       "Q 对拍项覆盖：A/E 全线（A_add/plg_A/E_weights/E_fresh）+ full 档全线"
       "（full_A/full_C/full_B/full_D/full_E_weights/full_E_fresh）+ 矩阵/缺省/"
       " plan 面，共 %d 项" % len(names), names)

    # ---- 负对照（定点差异注入：判据必须报 DIFF 且恰好命中预期项）----
    wf = os.path.join(head_tree, "md_cg", "writepipe.py")
    src = open(wf, encoding="utf-8").read()
    if _NEG_ANCHOR not in src:
        print("  ANCHOR-MISS 负对照锚点缺失：%r" % _NEG_ANCHOR)
        print("\noracle 自检：FAIL（fail-closed，exit 2）")
        raise SystemExit(2)
    with open(wf, "w", encoding="utf-8") as f:
        f.write(src.replace(_NEG_ANCHOR, _NEG_INJECT, 1))
    mut, e3 = _run_scenario(head_tree, "mut")
    ok(mut is not None, "Q 负对照观测脚本跑通（导出树副本内注入 A 面差异）", e3)
    if mut is not None:
        nd = sorted(n for n in names
                    if mut["items"][n] != ora["items"][n])
        ok(nd == ["A_add", "full_A"],
           "Q 负对照（对拍有判别力）：导出树副本内定点注入「写链 A 新增也需"
           "确认」⇒ DIFF 项**恰好**为写链 A 面两项（A_add / full_A）",
           nd)


# ==================================== R 组：端到端回滚演练（跨面 · 含子进程 CLI）
def g_r():
    print("== R 组：端到端回滚演练（confirm 出单链 / full 直落链 · 跨面）==")
    _policy()
    drill = {}          # 动作类 → 读数（跨面证据的汇总面）

    # ---- R1 confirm 档 C 改写：写链面 → 执行桥 → 回滚 CLI 子进程 ----
    with _mode("confirm"):
        cg = _lib("e2e_c")
        cg.add("rc_1", PLAIN % "初版", layer="knowledge",
               verification_basis="test", tags=["e2e"],
               edges=[{"target": "rc_p", "relation_type": "part_of"}])
        cg.add("rc_p", PLAIN % "父", layer="knowledge",
               verification_basis="test")
        cg.flush()
        o = _pipe().execute(cg, {"content_kind": "text", "content": PLAIN % "改写版",
                                 "layer": "knowledge", "node_id": "rc_1"})
        ok(o.get("moved_to") == "review_queue" and bool(o.get("pid")),
           "R1 写链面出单（C 改写）：moved_to=review_queue + pid",
           {k: o.get(k) for k in ("moved_to", "pid")})
        d = cg.review_decide(o["pid"], "accept", reason="演练")
        m = d.get("mutation") or {}
        ok(d.get("ok") is True and bool(m.get("before")) and bool(m.get("rollback"))
           and bool(m.get("impact")),
           "R1 执行桥 accept：前像/影响面/回滚命令三字段补全",
           {k: m.get(k) for k in ("before", "rollback")})
        ok("改写版" in (cg.get("rc_1") or {}).get("content", ""),
           "R1 落：覆写生效（正文已换）")
        pre_rel = m.get("before") or ""
        pre_b = _bytes(_pre_path(cg, pre_rel))
        got = _run_cli(m.get("rollback") or "")
        _refresh(cg)
        out = got.get("json") or {}
        ok(got["rc"] == 0 and out.get("ok") is True
           and out.get("bytes_equal_preimage") is True,
           "R1 回滚 CLI 子进程实测：rc=0、ok=True、逐字节比对前像=True",
           {"rc": got["rc"], "err": (got.get("err") or "")[-160:]})
        ok(bool(pre_b) and _bytes(_disk_path(cg, "rc_1")) == pre_b,
           "R1 回滚后盘面逐字节 == 前像（第三方改动面由前像时点语义保证）")
        res = out.get("residual") or {}
        ok(res.get("index_restored") is True and res.get("edges_restored") is True
           and res.get("agg_lines_restored") is True,
           "R1 残差核对三面全回（索引/边/聚合行）", res)
        ok(_entry_from_preimage(cg, "rc_1", pre_rel) is not None
           and cg.index["nodes"].get("rc_1")
           == _entry_from_preimage(cg, "rc_1", pre_rel),
           "R1 索引条目回齐：回滚后条目 == 前像重算条目（逐位）")
        # CLI 腿负对照（输入侧判别力）：不存在的 pid ⇒ fail-closed 非零退出
        bad = _run_cli(rollback.command_for(cg.root, "prop_deadbeef"))
        bout = bad.get("json") or {}
        ok(bad["rc"] == 1 and bout.get("ok") is False
           and bout.get("error") == "decision_not_found",
           "R1 CLI 负对照：不存在的 pid ⇒ rc=1 + decision_not_found"
           "（CLI 腿不是无脑报成功）", {"rc": bad["rc"], "json": bout})
        ok(rollback.collect_impact(cg, "rc_1")["edges"]["parents"] == ["rc_p"],
           "R1 边回齐：声明式 part_of 父边回案")
        drill["C"] = {"face": "写链(cg op=write)", "cli_rc": got["rc"],
                      "bytes": bool(pre_b)
                      and _bytes(_disk_path(cg, "rc_1")) == pre_b,
                      "residual": res}

    # ---- R2 confirm 档 B 合并：插件面（mdcg_remember gated）→ 回滚 CLI ----
    with _mode("confirm"):
        cg = _lib("e2e_b")
        cg.add("rb_t", BODY % "8081", layer="knowledge",
               verification_basis="test")
        cg.flush()
        pre_b = _bytes(_disk_path(cg, "rb_t"))
        rb = mcp_server._dispatch(cg, "mdcg_remember",
                                  {"content": BODY % "9595", "node_id": "rb_n",
                                   "gated": True, "layer": "knowledge"})
        ok(rb.get("verdict") == "CONFIRM" and rb.get("moved_to") == "review_queue"
           and bool(rb.get("pid")),
           "R2 插件面出单（B 合并）：verdict=CONFIRM + review_queue + pid",
           {k: rb.get(k) for k in ("verdict", "moved_to", "pid")})
        d = cg.review_decide(rb["pid"], "accept", reason="演练")
        m = d.get("mutation") or {}
        ok(d.get("ok") is True
           and forgetting.AGG_MARK in (cg.get("rb_t") or {}).get("content", "")
           and ((cg.get("rb_t") or {}).get("frontmatter") or {})
               .get("merge_count") == 1,
           "R2 落：聚合行已追加、merge_count=1（reinforce 原语）")
        got = _run_cli(m.get("rollback") or "")
        _refresh(cg)
        out = got.get("json") or {}
        ok(got["rc"] == 0 and out.get("ok") is True
           and out.get("bytes_equal_preimage") is True,
           "R2 回滚 CLI 子进程实测：rc=0、ok=True、逐字节比对前像=True",
           {"rc": got["rc"], "err": (got.get("err") or "")[-160:]})
        ok(bool(pre_b) and _bytes(_disk_path(cg, "rb_t")) == pre_b,
           "R2 回滚后盘面逐字节 == 前像（合并前正文；**非空前置**——两侧皆空"
           "不再静默判绿，U2 收口）", {"pre_b_len": len(pre_b)})
        ok(forgetting.AGG_MARK not in (cg.get("rb_t") or {}).get("content", "")
           and not ((cg.get("rb_t") or {}).get("frontmatter") or {})
               .get("merge_count"),
           "R2 聚合行/merge_count 不残留（定向剥离 + fm 全量取前像）")
        res = out.get("residual") or {}
        ok(res.get("index_restored") is True and res.get("edges_restored") is True
           and res.get("agg_lines_restored") is True,
           "R2 残差核对三面全回（索引/边/聚合行）", res)
        drill["B"] = {"face": "插件面(mdcg_remember gated)", "cli_rc": got["rc"],
                      "bytes": bool(pre_b)
                      and _bytes(_disk_path(cg, "rb_t")) == pre_b,
                      "residual": res}

    # ---- R3 confirm 档 D 删除：工具面（cg op=forget）→ 回滚 CLI ----
    with _mode("confirm"):
        cg = _lib("e2e_d")
        cg.add("rd_1", PLAIN % "初版", layer="knowledge",
               verification_basis="test", tags=["e2e"], importance=0.62)
        cg.flush()
        pre_b = _bytes(_disk_path(cg, "rd_1"))
        r3 = mcp_server._dispatch(cg, "cg", {"op": "forget", "node_id": "rd_1",
                                             "reason": "演练"})
        ok(r3.get("moved_to") == "review_queue" and r3.get("deleted") is False
           and bool(r3.get("pid")),
           "R3 工具面出单（D 删除）：review_queue + deleted=False + pid",
           {k: r3.get(k) for k in ("moved_to", "deleted", "pid")})
        d = cg.review_decide(r3["pid"], "accept", reason="演练")
        m = d.get("mutation") or {}
        ok(d.get("ok") is True and cg.get("rd_1") is None
           and cg.is_tombstoned("rd_1"),
           "R3 落：软删生效（节点离位 + 删除清单在案）")
        got = _run_cli(m.get("rollback") or "")
        _refresh(cg)
        out = got.get("json") or {}
        ok(got["rc"] == 0 and out.get("ok") is True
           and out.get("bytes_equal_preimage") is True,
           "R3 回滚 CLI 子进程实测：rc=0、ok=True、逐字节比对前像=True",
           {"rc": got["rc"], "calibrated": out.get("calibrated"),
            "err": (got.get("err") or "")[-160:]})
        ok(bool(pre_b) and _bytes(_disk_path(cg, "rd_1")) == pre_b,
           "R3 回滚后盘面逐字节 == 前像（restore + 前像校准；**非空前置**——"
           "同 R1/R3-节点复位口径，U2 收口）", {"pre_b_len": len(pre_b)})
        res = out.get("residual") or {}
        ok(res.get("index_restored") is True and res.get("edges_restored") is True
           and res.get("agg_lines_restored") is True,
           "R3 残差核对三面全回（索引/边/聚合行）", res)
        ok(bool(pre_b) and cg.index["nodes"].get("rd_1") is not None
           and _bytes(_disk_path(cg, "rd_1")) == pre_b,
           "R3 节点复位：索引条目在案且盘面 == 前像（逐字节）")
        drill["D"] = {"face": "工具面(cg op=forget)", "cli_rc": got["rc"],
                      "bytes": bool(pre_b)
                      and _bytes(_disk_path(cg, "rd_1")) == pre_b,
                      "residual": res}

    # ---- R4 full 档直落链：B/C/D 各一遍（直落 → 统一回滚入口 → 逐字节）----
    with _mode("full"):
        cg = _lib("e2e_full")
        # C 改写（写链面直落）
        cg.add("fc_1", PLAIN % "初版", layer="knowledge",
               verification_basis="test",
               edges=[{"target": "fc_p", "relation_type": "part_of"}])
        cg.add("fc_p", PLAIN % "父", layer="knowledge",
               verification_basis="test")
        cg.add("fb_t", BODY % "9090", layer="knowledge",
               verification_basis="test")
        cg.add("fd_1", PLAIN % "初版", layer="knowledge",
               verification_basis="test")
        cg.flush()
        # 演练侧按**执行时点**拍前像（与执行桥同一单点 protect.snapshot_preimage）
        pre_c = protect.snapshot_preimage(cg, "fc_1", action="C", pid="drill_c")
        imp_c = rollback.collect_impact(cg, "fc_1")
        pre_b = _bytes(_disk_path(cg, "fc_1"))
        pre_blob = _bytes(_pre_path(cg, pre_c)) if pre_c else b""
        ok(bool(pre_c) and bool(pre_blob) and bool(pre_b),
           "R4 前置取证·C 链：执行时点前像**与**盘面快照均非空（前像 %d 字节、"
           "盘面 %d 字节）——「空池静默判绿」的同族缺口一并收口（U2）"
           % (len(pre_blob), len(pre_b)),
           {"pre_c": pre_c, "pre_b_len": len(pre_b)})
        o_c = _pipe().execute(cg, {"content_kind": "text",
                                   "content": PLAIN % "全访问版",
                                   "layer": "knowledge", "node_id": "fc_1"})
        ok(o_c.get("committed") is True and o_c.get("moved_to") is None
           and "全访问版" in (cg.get("fc_1") or {}).get("content", ""),
           "R4 full 档 C 直落（写链面）：无单、committed=True、正文已换",
           {k: o_c.get(k) for k in ("committed", "moved_to")})
        rr_c = rollback.rollback_mutation(
            cg, {"action": "C", "target": "fc_1", "before": pre_c,
                 "impact": imp_c, "rollback": ""}, reason="演练", actor="drill")
        ok(bool(pre_b) and rr_c.get("ok") is True
           and rr_c.get("bytes_equal_preimage") is True
           and _bytes(_disk_path(cg, "fc_1")) == pre_b,
           "R4 full 档 C 回滚（统一回滚入口）：逐字节 == 执行时点前像"
           "（**非空前置**——U2 收口）",
           {k: rr_c.get(k) for k in ("ok", "bytes_equal_preimage", "error")})
        ok((rr_c.get("residual") or {}).get("index_restored") is True
           and (rr_c.get("residual") or {}).get("edges_restored") is True,
           "R4 full 档 C 残差核对：索引/边回齐", rr_c.get("residual"))
        # B 合并（插件面直落）
        pre_m = protect.snapshot_preimage(cg, "fb_t", action="B", pid="drill_b")
        imp_m = rollback.collect_impact(cg, "fb_t")
        pre_mb = _bytes(_disk_path(cg, "fb_t"))
        pre_blob = _bytes(_pre_path(cg, pre_m)) if pre_m else b""
        ok(bool(pre_m) and bool(pre_blob) and bool(pre_mb),
           "R4 前置取证·B 链：执行时点前像**与**盘面快照均非空（前像 %d 字节、"
           "盘面 %d 字节）——「空池静默判绿」的同族缺口一并收口（U2）"
           % (len(pre_blob), len(pre_mb)),
           {"pre_m": pre_m, "pre_mb_len": len(pre_mb)})
        r_m = mcp_server._dispatch(cg, "mdcg_remember",
                                   {"content": BODY % "9595", "node_id": "fb_n",
                                    "gated": True, "layer": "knowledge"})
        ok(r_m.get("verdict") == "MERGE" and r_m.get("moved_to") is None
           and forgetting.AGG_MARK in (cg.get("fb_t") or {}).get("content", ""),
           "R4 full 档 B 直落（插件面）：verdict=MERGE、聚合行已追加、无单",
           r_m.get("verdict"))
        rr_m = rollback.rollback_mutation(
            cg, {"action": "B", "target": "fb_t", "before": pre_m,
                 "impact": imp_m, "rollback": ""}, reason="演练", actor="drill")
        ok(bool(pre_mb) and rr_m.get("ok") is True
           and rr_m.get("bytes_equal_preimage") is True
           and _bytes(_disk_path(cg, "fb_t")) == pre_mb,
           "R4 full 档 B 回滚（定向剥离）：逐字节 == 执行时点前像"
           "（**非空前置**——U2 收口）",
           {k: rr_m.get(k) for k in ("ok", "bytes_equal_preimage", "method")})
        ok((rr_m.get("residual") or {}).get("agg_lines_restored") is True
           and (rr_m.get("residual") or {}).get("index_restored") is True,
           "R4 full 档 B 残差核对：聚合行/索引回齐", rr_m.get("residual"))
        # D 删除（工具面直落）
        pre_d = protect.snapshot_preimage(cg, "fd_1", action="D", pid="drill_d")
        imp_d = rollback.collect_impact(cg, "fd_1")
        pre_db = _bytes(_disk_path(cg, "fd_1"))
        pre_blob = _bytes(_pre_path(cg, pre_d)) if pre_d else b""
        ok(bool(pre_d) and bool(pre_blob) and bool(pre_db),
           "R4 前置取证·D 链：执行时点前像**与**盘面快照均非空（前像 %d 字节、"
           "盘面 %d 字节）——「空池静默判绿」的同族缺口一并收口（U2）"
           % (len(pre_blob), len(pre_db)),
           {"pre_d": pre_d, "pre_db_len": len(pre_db)})
        r_d = mcp_server._dispatch(cg, "cg", {"op": "forget", "node_id": "fd_1",
                                              "reason": "演练"})
        ok(r_d.get("ok") is True and r_d.get("moved_to") is None
           and r_d.get("deleted") is not False and cg.get("fd_1") is None,
           "R4 full 档 D 直落（工具面）：软删生效、无单",
           {k: r_d.get(k) for k in ("ok", "deleted", "moved_to")})
        rr_d = rollback.rollback_mutation(
            cg, {"action": "D", "target": "fd_1", "before": pre_d,
                 "impact": imp_d, "rollback": ""}, reason="演练", actor="drill")
        ok(bool(pre_db) and rr_d.get("ok") is True
           and rr_d.get("bytes_equal_preimage") is True
           and _bytes(_disk_path(cg, "fd_1")) == pre_db,
           "R4 full 档 D 回滚（restore + 前像校准）：逐字节 == 执行时点前像"
           "（**非空前置**——U2 收口）",
           {k: rr_d.get(k) for k in ("ok", "bytes_equal_preimage", "method")})
        ok((rr_d.get("residual") or {}).get("index_restored") is True
           and (rr_d.get("residual") or {}).get("edges_restored") is True
           and (rr_d.get("residual") or {}).get("agg_lines_restored") is True,
           "R4 full 档 D 残差核对三面全回", rr_d.get("residual"))
        ok(len(_mut_entries(cg)) == 0,
           "R4 full 档全程零变更单（直落面不产单——与 confirm 链的分界）",
           len(_mut_entries(cg)))
        # 边界**现状钉**（留池项，非背书）：full 档直落路径不自动拍前像——
        # 三节点的 preimage 审计行各**恰好 1 条且均来自演练侧**（pid=drill_*）。
        # 若将来把「一切破坏性动作先留前像」（设计 §六 义务①）接到 full 直落
        # 路径，本断言转红、须随之更新（这正是接线批次的入口判据）。
        pims = {n: _pims(cg, n) for n in ("fc_1", "fb_t", "fd_1")}
        ok(all(len(v) >= 1 and all("drill_" in str(r.get("reason")) for r in v)
               for v in pims.values()),
           "R4 现状钉：full 档 C/B/D 直落路径**不自动**拍前像——三节点的 "
           "preimage 审计行全部来自演练侧（pid=drill_*）；设计 §六 义务① 在 "
           "full 直落路径未接线（留池，非背书）：若将来接线，本断言转红、"
           "须随之更新", {n: len(v) for n, v in pims.items()})
        cg.close()

    # ---- R5 跨面汇总面（三条链 × 两个档位齐备）----
    faces = {k: v["face"] for k, v in drill.items()}
    ok(sorted(drill) == ["B", "C", "D"]
       and len(set(faces.values())) == 3
       and all(v["cli_rc"] == 0 and v["bytes"] is True
               and all(v["residual"].values()) for v in drill.values()),
       "R5 跨面演练齐备：C/B/D 三条链各经**不同入口面**（写链/插件面/工具面）"
       "+ 执行桥 + 回滚 CLI 子进程，逐字节与残差三面全真",
       {"faces": faces,
        "readings": {k: {"rc": v["cli_rc"], "bytes": v["bytes"]}
                     for k, v in drill.items()}})


def g_s():
    """F1 收口（2026-10-03）：变异表完整性自检的判别力自证（合成源）。

    与 `md_cg/test_autonomy_modes.py` 的 F1 组**两守卫对齐**（同款判据、同款
    测例形态）；真实表断言即「表长 8 = 声明」的**自动核验载体**。
    """
    _S_DROP_TUPLE = ("x\n_SRC_MUTATIONS = (\n"
                     "    # ① 甲\n    (\"a\",),\n"
                     "    # ② 乙\n"                # ← ② 删元组留注释（F1 原形）
                     "    # ③ 丙\n    (\"c\",),\n)\n")
    _S_DROP_BOTH = ("x\n_SRC_MUTATIONS = (\n"
                    "    # ① 甲\n    (\"a\",),\n"
                    "    # ③ 丙\n    (\"c\",),\n)\n")   # ← ② 注释+元组同删
    _self_src = io.open(os.path.abspath(__file__), encoding="utf-8").read()
    ok(_table_gaps(_S_DROP_TUPLE, 2, ("①", "②", "③")) == ["②", "len:2≠3"],
       "F1① 防误删自检判别力（mp）：删元组留注释 ⇒ 报缺口编号 ②"
       "（表长兜底随报）",
       _table_gaps(_S_DROP_TUPLE, 2, ("①", "②", "③")))
    ok(_table_gaps(_S_DROP_BOTH, 2, ("①", "②", "③")) == ["②", "len:2≠3"],
       "F1② 防误删自检判别力（mp）：注释与元组同删 ⇒ 仍报缺口编号 ②",
       _table_gaps(_S_DROP_BOTH, 2, ("①", "②", "③")))
    ok(_table_integrity_check() == [],
       "F1③ 真实表完好（**自动核验载体**，mp）：编号 ①–%s 无缺口、表长 %d = 声明"
       % (_MUTATION_IDS[-1], len(_MUTATION_IDS)),
       _table_integrity_check())
    _n1, _n2 = len(_SRC_MUTATIONS) - 1, len(_SRC_MUTATIONS)
    ok(_table_gaps(_self_src, _n1) == ["len:%d≠%d" % (_n1, _n2)],
       "F1④ 表长判据兜底（mp）：真实源 + 表长-1 ⇒ 报「len:%d≠%d」" % (_n1, _n2),
       _table_gaps(_self_src, _n1))


_GROUPS = (g_p, g_q, g_r, g_s)


def _run_groups():
    """跑全部断言组（静默），返回失败数——供变异自证复用。"""
    _PASS.clear()
    _FAIL.clear()
    for g in _GROUPS:
        g()
    return len(_FAIL)


# =============================================================== 定点变异自证
#: 本守卫模块对象——`_bytes` 这类**守卫自身**的判据也须有定点变异（补强批次
#: v1.2·U2 的「空池注入」），故变异表允许以本模块为属主（`sys.modules[__name__]`
#: 是同一对象的现取形态，不写第二处名字字面量）。
_SELF = sys.modules[__name__]

# 表内每项 = (说明, 目标, 锚点原文, 替换文, 预期红项数)。锚点须**逐字**出现在
# 目标函数源码里；漂移即 ANCHOR-MISS（fail-closed，exit 2）。
# 目标形态：("mod", 模块, 函数名) / ("cls", 类, 方法名)。
_SRC_MUTATIONS = (
    # ①「档位不生效」——env 读取口恒返回真源缺省（confirm）：切档锚与
    #   full 档直落面同时失效（设计 §十一 明文「注入『档位不生效』必红」）。
    # 红 5（实测 2026-10-03）：P 组「切档锚不空转·full」（切了 full 但 mode()
    # 读回 confirm）+ R4 四条（full 档 C/B/D 直落三条——退化后变出单/入库形态
    # + R4「全程零变更单」）。对照臂（confirm→confirm）与 P 组对拍本体在退化下
    # 双臂同值（语义相符，不红）；E 面无档位判据 ⇒ P2 不受影响（同因）。
    ("档位不生效（配置档位恒返回表内缺省）", "mod", autonomy_modes,
     "_configured_mode",
     '    raw = autonomy_env("mode", environ)', '    raw = DEFAULT_MODE', 5),
    # ② 执行桥空转——accept「成功了」但动作没做（汇报不实的最危险形态）：
    #   三条 confirm 链的「落」判据与回滚面整体失效。
    # 红 13（实测 2026-10-03）：R1 六条（前像补全/落/CLI 读数/逐字节/残差/
    # 索引条目）+ R2 三条（落/CLI 读数/残差）+ R3 三条（落/CLI 读数/残差）
    # + R5 跨面汇总（读数面按实测值断言，不写死）。语义相符仍绿：R1「边回齐」
    # （边本就未动）、R1 CLI 负对照（期望失败）、R2/R3「回滚后盘面逐字节 ==
    # 前像」（未发生变更 ⇒ 与前像同值）。
    ("accept 不执行（执行桥空转）", "cls", MdCGOS, "_mutation_execute",
     '            pre = _rb.preimage(self, act, tgt, pid=item.get("pid"),',
     '            return {"ok": True, "node_id": tgt}\n'
     '            pre = _rb.preimage(self, act, tgt, pid=item.get("pid"),', 13),
    # ③ 回滚不落盘（_land 空转）——回滚「报成功了」但盘面没回。
    # 红 5（实测 2026-10-03）：**只有 R4 五条**（进程内统一回滚入口的 C/B/D
    # 逐字节与 C/B 残差）。R1/R2/R3（confirm 链）不受影响——回滚经 **CLI 子进程**
    # 执行，进程内变异不跨进程到达子进程（如实登记：CLI 腿的判别力由 ②/④ 这类
    # **状态面**变异与 R1 的 CLI 负对照承担，不由本变异承担）。
    ("回滚不落盘（_land 空转）", "mod", rollback, "_land",
     '    cg._write_node(node_id, path, fm, content)', '    return', 5),
    # ④ 执行记录不落 mutation（rec["mutation"] 摘除）——回滚 CLI 读不到载荷
    #   （「回滚命令」的读取源断链）：confirm 三条链的 CLI 后置判据整体失效。
    # 红 14（实测 2026-10-03）：R1 五条（CLI 读数/逐字节/残差/索引条目/边回齐）
    # + R2 四条（CLI 读数/逐字节/聚合行不残留/残差）+ R3 四条（CLI 读数/逐字节/
    # 残差/节点复位）+ R5 跨面汇总。R4（进程内入口直接持有载荷）与 CLI 负对照
    # 不受影响。
    ("执行记录不落 mutation（rec['mutation'] 摘除）", "cls", MdCGOS,
     "_record_decision",
     '        _mut = result.get("mutation")\n'
     '        if isinstance(_mut, dict):\n'
     '            rec["mutation"] = _mut',
     '        _mut = result.get("mutation")\n'
     '        if False:\n'
     '            rec["mutation"] = _mut', 14),
    # ⑤ 写链「full 档放行分支」失效（full 档 A/C 也出单）——切档对拍必须
    #   抓住它（若对拍无判别力，这条差异会被漏掉）。
    # 红 4（实测 2026-10-03）：P1 两条（切档核心判据「full 首写 == confirm 首写」
    # + 落盘节点对拍）+ R4 两条（full 档 C 直落无单/正文已换 + 全程零变更单）。
    ("写链 full 档放行分支失效（full 也出单）", "mod", writepipe,
     "_gate_autonomy",
     '    if dec["decision"] == _am.ALLOW:\n        return None',
     '    if dec["decision"] == _am.ALLOW and dec["mode"] != "full":\n'
     '        return None', 4),
    # ⑥ E 分数类被档位闸阻塞（freshness 面）——「非破坏性动作 E 不阻塞」的
    #   反向形态：E 类动作路径被塞进档位判据，**full 档**分支被拦 ⇒ P2 的
    #   confirm↔full 两轮读数与落盘 fm 分叉。（注：E 面在 confirm/full 的
    #   矩阵格都是「允许」，故注入须按**档名**分叉才能在同档对比中显形——
    #   这正是「无档位判据」判据的判别形态。）
    # 红 2（实测 2026-10-03）：P2 freshness 的读数对拍 + 落盘 fm 对拍。
    ("E 面被档位闸阻塞（freshness.recalc 按档名分叉）", "mod",
     freshness, "recalc",
     '    ref = freshness_now() if now is None else float(now)',
     '    from . import autonomy_modes as _am\n'
     '    if _am.mode() == "full":\n'
     '        return {"ok": False, "error": "mode_blocked"}\n'
     '    ref = freshness_now() if now is None else float(now)', 2),
    # ⑦ E 分数类被档位闸阻塞（weights 面）——同上，另一族（importance 轴）。
    # 红 2（实测 2026-10-03）：P2 weights 的读数对拍 + 落盘 fm 对拍。
    ("E 面被档位闸阻塞（weights.recalc 按档名分叉）", "mod",
     weights, "recalc",
     '    nodes = (getattr(cg, "index", None) or {}).get("nodes") or {}\n'
     '    indeg = coverage_index(cg)',
     '    from . import autonomy_modes as _am\n'
     '    if _am.mode() == "full":\n'
     '        return {"ok": False, "error": "mode_blocked"}\n'
     '    nodes = (getattr(cg, "index", None) or {}).get("nodes") or {}\n'
     '    indeg = coverage_index(cg)', 2),
    # ⑧ 补强批次 v1.2·U2——**空池注入**（复核探针形态）：守卫的字节读取单点
    #    `_bytes` 恒返回空字节 ⇒ 一切「逐字节比对前像」的合取项两侧皆空。
    #    U2 收口前（复核探针实测「R 组红 3 / 绿 30」）：R1-逐字节与 R3-节点复位
    #    因带 `bool(pre_b)` 门槛判红，而 **R2「回滚后盘面逐字节」、R3 首个逐字节、
    #    R4 三条的第三合取项**在两侧皆空时**静默判绿**——同组两种口径并存。
    #    收口后（非空前置统一 + R4 三条非空取证）⇒ **红 11**（实测 2026-10-03）：
    #    = R1-逐字节 + R2-逐字节 + R3-逐字节 + R3-节点复位 + R4 C/B/D 三条
    #      + R4 C/B/D 三条前置取证 + R5 跨面汇总（drill 读数面按实测值断言）。
    ("空池注入（_bytes 恒返回空字节·U2 判别力）", "mod", _SELF, "_bytes",
     '        with open(path, "rb") as f:\n            return f.read()',
     '        return b""', 11),
)

#: 「防误删自检」的判别力钉（F1 收口，2026-10-03）——**不占表内编号**：表长恒 =
#: `_MUTATION_IDS` 的长度（复核口径与实存一致）；它是自检体系的判别力证明，
#: 形态与表内条目**同口径**：源码替换 + exec 重装 + 红项数比照，锚点同样过
#: `_anchor_check`（漂移即 ANCHOR-MISS、fail-closed）。与
#: `md_cg/test_autonomy_modes.py` 的同名钉**两守卫对齐**。
#: 剥掉 `_table_gaps` 的自检开关（恒判「完好」）⇒ 三条合成源自证测例（F1①②④）
#: 转红。红 3（实测）；F1③（真实表期望 []）语义相符仍绿。
_SELFCHECK_MUTATION = (
    "防误删自检开关剥除（_table_gaps 恒判完好）", "mod", _SELF, "_table_gaps",
    'def _table_gaps(text, entries_count, ids=_MUTATION_IDS):\n'
    '    """变异表完整性判定（纯函数）：返回缺口说明列表（空 = 完好）。',
    'def _table_gaps(text, entries_count, ids=_MUTATION_IDS):\n'
    '    return []\n'
    '    """变异表完整性判定（纯函数）：返回缺口说明列表（空 = 完好）。', 3)


# ---- 变异表完整性自检（F1 收口：防误删，2026-10-03）------------------------
# 与 `md_cg/test_autonomy_modes.py` 同款（两守卫对齐）：把「编号无缺口 ＋ 表长与
# 显式声明一致」变成机械判据——缺项 ⇒ fail-closed 退出码 2 并报缺口编号，不再
# 靠人工发现。与 `_anchor_check` 同层接入（正常运行与 --mutate 均先行执行），
# 配内置判别力钉 `_SELFCHECK_MUTATION`（剥掉自检开关 ⇒ 自证测例转红）。
# 基线源＝**当前工作区文件**，不绑 git HEAD（本仓已有两次教训）。
#
# 判据（`_table_gaps`，纯函数——自证测例以合成源调它）：
#   a. 编号注释被下一**不同**编号注释覆盖（= 删元组留注释，F1 原形）⇒ 报该编号
#      （同编号在块内的复提不算）；
#   b. 编号注释序列与声明不一致（缺/重复；含「注释与元组同删」的真删形态）⇒
#      报缺者；
#   c. len(_SRC_MUTATIONS) ≠ 声明长度 ⇒ 报「len:N≠M」兜底。
_MUTATION_IDS = ("①", "②", "③", "④", "⑤", "⑥", "⑦", "⑧")

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
            # nid == pending：同一条目注释块内的复提——不覆盖 pending。
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
    kind, owner, name = target
    return inspect.getsource(getattr(owner, name))


def _strip_indent(text, n):
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
    bad = []
    for name, _kind, owner, fname, old, _new, _n in (_SRC_MUTATIONS
                                                     + (_SELFCHECK_MUTATION,)):
        if old not in _fn_src((_kind, owner, fname)):
            bad.append("变异锚点缺失：%r @%s.%s" % (old[:40], owner.__name__, fname))
    return bad


@contextlib.contextmanager
def _patched(target, old, new):
    kind, owner, name = target
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
        try:
            ns = dict(vars(sys.modules[owner.__module__]))
            ns["__name__"] = owner.__module__
        except KeyError:
            ns = dict(vars(owner))
    exec(compile(src, "mp_mut.py", "exec"), ns)
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
    except SystemExit as exc:      # oracle 路由 fail-closed：算「红」但报明
        fails = -1
        print("  变异「%s」→ oracle 路由 fail-closed（exit %s），判 FAIL"
              % (name, getattr(exc, "code", "?")))
    except Exception as exc:                                # noqa: BLE001
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
    _RUN[0] = 10 ** 6      # 变异轮用独立子根（防读到上一轮盘面）
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
    print("锚点自检：PASS（%s；不以 git HEAD 为冻结基线——oracle 每次现导出）"
          % src)
    print("变异表完整性自检：PASS（编号 %s–%s 无缺口、表长 %d = 声明——"
          "删条目即 fail-closed，F1 收口）"
          % (_MUTATION_IDS[0], _MUTATION_IDS[-1], len(_MUTATION_IDS)))
    groups = _GROUPS
    if "--no-oracle" in sys.argv:
        groups = tuple(g for g in _GROUPS if g is not g_q)
        print("（--no-oracle：跳过 oracle 对拍路由——本地调试用，不构成验收读数）")
    try:
        for g in groups:
            g()
    finally:
        _RUN[0] += 1
    print("\n不动面对拍与回滚演练守卫：%d 通过，%d 失败" % (len(_PASS), len(_FAIL)))
    if _FAIL:
        for f in _FAIL:
            print("    红:", f)
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
