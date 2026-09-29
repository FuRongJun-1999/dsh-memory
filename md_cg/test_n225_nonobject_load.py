# -*- coding: utf-8 -*-
"""md_cg · 非对象形态索引 / 日志守卫（N225：一行 `null` / `[]` / `123` / `"abc"`
崩掉整条装载链）+ **补强批**（深度 2 同族面：排序键坏型 / 载荷坏型）

缺陷（修复前，本守卫红态实抓）：
``json.loads`` 的产物不必是对象——``null`` / ``[]`` / ``123`` / ``"abc"`` 都是
**合法 JSON**。三处裸调 ``.get`` 的判据面因此全线逃逸 AttributeError（而 except
元组只收 ValueError/OSError）：

  · ``mdcg.MdCG._load_index``（mdcg.py:1050 旧行）``d.get("schema")`` ⇒
    **构造即失败**：常驻 MCP 服务的记忆面整个起不来（rc=1），一次性脚本
    （review_cli 等）全崩；而盘上 ``.md`` 真源完好无损——丢的只是派生索引
    这一条腿。实测四形态全部 ``AttributeError: '<type>' object has no
    attribute 'get'``。
  · ``mdcg.MdCG.compact_index``（mdcg.py:1235 旧行）同款 ⇒ 存活实例运行中
    快照被外部写坏一次，``close`` 自动 compact 的收尾路径就再也落不成快照。
  · ``fsutil.ShardedLog.read_all``（fsutil.py:386 旧行）``r.get("_t", 0)`` ⇒
    分片日志里一行非对象记录即让**排序键**抛异常，索引装载与 compact 双断。

深度 2 补充（N225 v1.0 报告 §0「已知缺口」点名的同族面——**行是 dict 不等于
字段可用**，本次补强批收口）：
  · ① **排序键坏型**：``_t`` / ``_s`` 被写成 ``"abc"`` / ``[]`` / ``null`` /
    ``NaN`` ⇒ 旧键 ``(r.get("_t", 0), r.get("_s", 0))`` 在 sort 里抛
    TypeError（``'<' not supported between instances of 'str' and 'float'``，
    实测见 F 组），而 except 面只有 ValueError/OSError ⇒ 与原始缺陷同一条
    断链。收口：单槽归一（数值且非 NaN 原样、其余记 0，与「缺键取 0」同口径），
    记录**不丢**，坏型槽进记账面（``note_bad_sortkey_rows``）。
  · ② **载荷坏型**：分片记录 ``e`` 非 dict 且非 None（``[]`` / ``123`` /
    ``"abc"``）⇒ 旧写法直接 ``nodes[nid] = e``，下游 ``_count_buckets`` 对
    元素裸调 ``.get`` 抛 AttributeError。收口：装载重放与 compact 重放**共用
    同一实现**（``MdCG._apply_log``）——坏载荷跳过 + 记账（与①同一记账面），
    ``e is None`` 的 tombstone 语义一字不改；``_count_buckets`` **不加**类型闸
    （防在上游，不新增第三套判据）。

修复口径（有界，不新增第三套判据）：
  ① 装载面：顶层非对象与 ValueError/OSError **同一降级口径**——视同损坏 ⇒
     走 ``_load_index`` / ``compact_index`` **既有**的「回退全库扫描」路径
     （宁重扫勿清池）。``_maybe_reload_index`` 经 ``_load_index`` 收口后不再
     抛，故未加宽其 except 面（A 组第 5 条钉这一点）。
  ② 日志面：``read_all`` 逐行分流——dict 进回放，非对象行进记账面
     （``note_nonobject_rows``：模块级计数 + 有界样本 + stderr 告警）；
     排序键坏型同面记账（``note_bad_sortkey_rows``）。**容忍 ≠ 静默**。
  ③ 不动 ``read_jsonl`` 的通用契约（其它消费面不在本次范围）；不动 tombstone
     语义（``e is None`` 的删除重放保持原行为）。

守卫构成（A 装载面 / B compact 面 / C 分片日志面 / D stdio 端到端 /
E 载荷坏型收口 / F 排序键健壮化 / G tombstone 语义 / H read_jsonl 通用面）：
  A 四形态 × 5 条（20）：构造不抛 · 确有全库扫描 · 既有节点一个不丢 · 不得退化
    成空池 · 探活重载（``_maybe_reload_index``）不抛且节点仍全
  B 四形态 × 4 条（16）：compact 不抛 · 落盘快照恢复为可再装载 dict · 不清池
    （账本对得上盘面）· 返回值含既有节点
  C 9 条：read_all 不抛 / 只收 dict / 坏行计数可断言 / stderr 告警可观测 /
    tombstone 记录保留在返回列表（e=None 不得当坏行丢掉）/ 排序不崩；重放面：
    构造不抛 / 合法新记录生效
  D 5 条：非对象快照 + 坏分片的临时库上起 ``md_cg.mcp_server`` stdio 主循环 ⇒
    rc=0 · initialize 应答 · tools/list 应答 · 非对象行仍回 -32600 · 攻击行之后
    仍应答（**不是 rc=1 / 进程即死**）
  E 6 条（载荷坏型收口，契约②）：装载不抛 / 坏载荷不进 nodes / 合法 upsert 仍
    生效 / 记账可断言且不静默 / compact 面不抛且快照无坏载荷 id / **两面对同一
    分片的 nodes 逐键相等**（同口径）
  F 5 条（排序键健壮化，契约①）：read_all 不抛**且**旧键直排在同一批记录上必抛
    （fixture 有判别力）/ 合法记录与旧键 oracle **逐位一致（序与内容）** /
    记录一个不丢且按键单调不减 / 坏型键计数可断言 / 不静默
  G 2 条（tombstone 语义）：装载面 e is None ⇒ pop；compact 面同款（删除不复活）
  H 2 条（read_jsonl 通用面）：非对象行仍**原样产出**（类型序列逐位一致）· 产出
    对象与 json.loads 结果同值（不做类型改造）

**上一轮 E 组 5 条「源文本在场」断言已整组删除**（`'isinstance(d, dict) and
d.get("schema") == SCHEMA' in win_load` 这类源码文本级自证：整组换成空组后
``--branch-baseline`` 仍 PASS，零判别力）。其判据面改由行为断言承担，一一对应：
  旧 E1（装载面类型闸在场）→ A 组（行为，变异①钉死）
  旧 E2（compact 面非对象分支在场）→ B 组（行为，变异②钉死）
  旧 E3（read_all 过滤与记账成对在场）→ C 组（行为，变异③钉死）
  旧 E4（read_jsonl 通用契约未改）→ H 组（行为，变异⑧钉死）
  旧 E5（tombstone 语义两处仍在）→ G 组（行为，变异⑤/⑦从两侧钉死）

``--branch-baseline`` 定点变异自证（与 ``test_neg_condition_hits`` 同口径）：
逐个关掉一处判据，守卫**必须转红**且红项**恰好**落在该判据负责的组、数量等于
该组断言数（多一项少一项都报红）；锚点漂移报 ``ANCHOR-MISS`` 并以**退出码 2**
fail-closed 停手。基线源是**工作区源码**（``inspect.getsource`` 取自当前已加载
模块），绝不绑 git HEAD——本仓批次 80/81 两次教训：基线绑提交那一刻即失效。

**组与判据一一对应**（这样「恰好等于该组断言数」才可成立）：每组只放该判据
自己的断言，fixture 只放该判据自己的病理（各组互不交叉），故每处变异只红一组
（装载面/日志面两处变异另红端到端 D 组——D 组的两个病理本就是「非对象快照」与
「非对象行」）。变异表里同一组出现两次（G 组被⑧… 被⑤与⑦从两侧钉死）是刻意的：
口径「过窄」与「过宽」都必须转红。

隔离纪律（与 ``test_n206_stdio_jsonrpc_type`` / ``test_issue39_utf8_stdio`` 同款）：
env 剔净全部 MDCG_*/HIVE_* 注入面，只注入指向临时目录的
``MDCG_ROOT``/``MDCG_AUX_ROOT``/``MDCG_STATE_ROOT``/``MDCG_DATA_ROOT``/
``MDCG_TENANT_REGISTRY``（指向不存在的临时路径=空表回落）/``MDCG_SUSTAIN=0``
（关常驻循环）/``MDCG_LEGACY_ENV_AUTH=1``（既有豁免面，零令牌、不回落真实
`~/.mdcg`）；全部合成库落在 ``tempfile.mkdtemp`` 下，跑完 rmtree。**绝不触在役
活库、真实令牌库与真实 serve。**

运行：
  python -X utf8 -m md_cg.test_n225_nonobject_load
  python -X utf8 -m md_cg.test_n225_nonobject_load --branch-baseline
"""
from __future__ import annotations

import contextlib
import inspect
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import textwrap
from contextlib import redirect_stderr, redirect_stdout

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except AttributeError:
    pass

from . import fsutil as F              # noqa: E402
from . import mdcg as M                # noqa: E402
from .mdcg import MdCG                 # noqa: E402

# 四种「合法 JSON 但非对象」形态（N225 的攻击面全谱）
BODIES = (("null", "null"), ("empty_array", "[]"),
          ("bare_int", "123"), ("bare_str", '"abc"'))

PASS, FAIL = 0, 0
FAILS = []
_CURRENT = ["?"]
_GROUP_FAILS = {}
_TMP_ROOTS = []
_LIVE = []


# 生效条件：把 PASS/FAIL/失败名单/分组失败数全部清零并解除当前组名（每次完整跑套件前调用；--branch-baseline 每个变异轮都要一次干净基线）。
def _reset_counters():
    global PASS, FAIL
    PASS = FAIL = 0
    del FAILS[:]
    _GROUP_FAILS.clear()
    _CURRENT[0] = "?"


# 生效条件：group 为非空字符串时设为当前组名并在 _GROUP_FAILS 里开出该组条目（未开则记 0）；重复调用同名组只是切换当前组，不清零已有计数。
def begin(group: str):
    _CURRENT[0] = group
    _GROUP_FAILS.setdefault(group, 0)


# 生效条件：cond 为真记一条通过并打印；为假把 FAIL 与当前组失败数各 +1、把 name 追加进 FAILS 并打印 detail（detail 为空则只打印名字）。
def check(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print("  [ok] %s" % name)
        return True
    FAIL += 1
    _GROUP_FAILS[_CURRENT[0]] = _GROUP_FAILS.get(_CURRENT[0], 0) + 1
    FAILS.append(name)
    print("  [FAIL] %s  %s" % (name, detail))
    return False


# 生效条件：fn 为无参回调时调用它取条件值——回调抛异常即判红并把异常类型与消息写进 detail（**不中断整组**，保证「变异下红项数 == 该组断言数」这一精确口径成立）；fn 正常返回则按返回值真假记账；detail 传 callable 时在同一保护下求值（detail 自身抛异常也只判红、不外逸）。
def check_fn(name, fn, detail=""):
    if callable(detail):
        try:
            detail = detail()
        except Exception as exc:          # noqa: BLE001
            detail = "detail 求值抛 %s: %s" % (type(exc).__name__, exc)
    try:
        cond = bool(fn())
        extra = detail
    except Exception as exc:              # noqa: BLE001 —— 红态正是抛异常
        cond = False
        extra = "回调抛 %s: %s（%s）" % (type(exc).__name__, exc, detail)
    return check(name, cond, extra)


# 生效条件：新建系统临时目录（prefix 前缀）并把路径登记进 _TMP_ROOTS，供本次运行收尾统一 rmtree；返回该路径。
def _tmpdir(prefix: str) -> str:
    p = tempfile.mkdtemp(prefix=prefix)
    _TMP_ROOTS.append(p)
    return p


# 生效条件：无入参，对 _TMP_ROOTS 里每个目录 rmtree(ignore_errors=True) 并清空清单、对 _LIVE 里每个认知图实例尝试 close()（异常吞掉，收尾不该再抛）；收尾是幂等的。
def _cleanup():
    for cg in _LIVE:
        try:
            cg.close()
        except Exception:                 # noqa: BLE001 —— 收尾路径不再抛
            pass
    del _LIVE[:]
    for p in _TMP_ROOTS:
        shutil.rmtree(p, ignore_errors=True)
    del _TMP_ROOTS[:]


# 生效条件：root 为库根时构造 MdCG(root, autoflush=1)、按 ids 逐条 add 最小节点（layer=knowledge）后 close()（close 落合法快照，使盘面 .md 与快照同源）；返回 root。
def _build_lib(root: str, ids=("n1", "n2")):
    cg = MdCG(root, autoflush=1)
    for nid in ids:
        cg.add(nid, "# 功能名：节点%s\n# 正文：合成节点 %s" % (nid, nid),
               layer="knowledge")
    cg.close()
    return root


# 生效条件：root 下 _index_log/ 已建成目录时，写入一份固定的坏分片 9000-c0ffee00.log——entry 非 None 时首行是一条合法 id=c_new 记录，随后固定四行非对象（null/[]/123/"abc"），末行是 id=n2 的 tombstone（e=None）；返回该分片路径。
def _write_bad_shard(root: str, entry=None) -> str:
    d = os.path.join(root, "_index_log")
    os.makedirs(d, exist_ok=True)
    p = os.path.join(d, "9000-c0ffee00.log")
    rows = []
    if entry is not None:
        rows.append(json.dumps({"id": "c_new", "e": entry,
                                "_t": 1.0, "_s": 1}, ensure_ascii=False))
    rows += ["null", "[]", "123", '"abc"']
    rows.append(json.dumps({"id": "n2", "e": None, "_t": 2.0, "_s": 2},
                           ensure_ascii=False))
    with open(p, "w", encoding="utf-8") as f:
        f.write("\n".join(rows) + "\n")
    return p


# 生效条件：root 下 _index_log/ 已建成目录时，写入坏**载荷**分片 9001-bad0payl.log——三行 e 非 dict 且非 None（[]/123/"abc"，id 为 p_arr/p_int/p_str）+ 一行合法 upsert（id=n1，载荷带 bucket=n225pay，用于证明合法记录未被坏载荷牵连）；该分片**不含**非对象行、不含 e is None 行（组间隔离：另两类病理归 C/G 组）；返回该分片路径。
def _write_payload_shard(root: str) -> str:
    d = os.path.join(root, "_index_log")
    os.makedirs(d, exist_ok=True)
    p = os.path.join(d, "9001-bad0payl.log")
    rows = [
        json.dumps({"id": "p_arr", "e": [], "_t": 1.0, "_s": 1},
                   ensure_ascii=False),
        json.dumps({"id": "p_int", "e": 123, "_t": 2.0, "_s": 2},
                   ensure_ascii=False),
        json.dumps({"id": "p_str", "e": "abc", "_t": 3.0, "_s": 3},
                   ensure_ascii=False),
        json.dumps({"id": "n1", "e": {"path": "knowledge/n1.md",
                                      "layer": "knowledge",
                                      "bucket": "n225pay"},
                    "_t": 4.0, "_s": 4}, ensure_ascii=False),
    ]
    with open(p, "w", encoding="utf-8") as f:
        f.write("\n".join(rows) + "\n")
    return p


# 生效条件：root 下 _index_log/ 已建成目录时，写入 tombstone 分片 9002-tombstn.log——单行 {"id":"n2","e":None,_t=1.0,_s=1}（删除记录）；该分片不含非对象行、不含坏载荷行（组间隔离：另两类病理归 C/E 组）；返回该分片路径。
def _write_tombstone_shard(root: str) -> str:
    d = os.path.join(root, "_index_log")
    os.makedirs(d, exist_ok=True)
    p = os.path.join(d, "9002-tombstn.log")
    with open(p, "w", encoding="utf-8") as f:
        f.write(json.dumps({"id": "n2", "e": None, "_t": 1.0, "_s": 1},
                           ensure_ascii=False) + "\n")
    return p


# 生效条件：path 指向快照/任意文本文件时以 utf-8 覆盖写入 body（非对象快照的注入点）；父目录不存在会抛 OSError。
def _overwrite(path: str, body: str):
    with open(path, "w", encoding="utf-8") as f:
        f.write(body)


# 生效条件：body 为四形态之一的文本时，建库 → 覆盖快照为 body → 带 _scan_nodes 计数桩重开 MdCG，返回上下文 dict（root / cg / scans / error）；任何一步抛异常都收进 ctx["error"] 而不外抛（保证后续逐条断言各自判红）。
def _case_load(body: str) -> dict:
    root = _tmpdir("mdcg_n225_load_")
    ctx = {"root": root, "cg": None, "scans": [0], "error": None}
    try:
        _build_lib(root)
        _overwrite(os.path.join(root, "_index.json"), body)
        orig = MdCG._scan_nodes

        def counted(self):                # noqa: ANN001 —— 计数桩
            ctx["scans"][0] += 1
            return orig(self)

        MdCG._scan_nodes = counted
        try:
            ctx["cg"] = MdCG(root, autoflush=1)
        finally:
            MdCG._scan_nodes = orig
        _LIVE.append(ctx["cg"])
    except Exception as exc:              # noqa: BLE001
        ctx["error"] = exc
    return ctx


# 生效条件：body 为四形态之一的文本时，建库 → 在**合法快照**上构造存活实例（保证构造面不参与本组）→ 把快照覆盖为 body（模拟运行中被外部写坏）→ 调 compact_index()，返回上下文 dict（root / cg / surf / idx / error）；异常收进 ctx["error"]。
def _case_compact(body: str) -> dict:
    root = _tmpdir("mdcg_n225_compact_")
    ctx = {"root": root, "cg": None, "surf": None, "idx": None,
           "error": None}
    try:
        _build_lib(root)
        cg = MdCG(root, autoflush=1)
        ctx["cg"] = cg
        _LIVE.append(cg)
        ctx["surf"] = cg._count_md_files()
        _overwrite(os.path.join(root, "_index.json"), body)
        ctx["idx"] = cg.compact_index()
    except Exception as exc:              # noqa: BLE001
        ctx["error"] = exc
    return ctx


# 生效条件：无入参时建库 → 写坏分片（含合法 c_new 记录 + 四行非对象 + n2 的 tombstone）→ 先重置记账、以 redirect_stderr 捕获 read_all 的告警输出直接调 ShardedLog.read_all，再重开 MdCG 走索引重放；返回上下文 dict（root / recs / stats / stderr / cg / nodes / stats_after / 各阶段 error）。
def _case_shard() -> dict:
    root = _tmpdir("mdcg_n225_shard_")
    ctx = {"root": root, "recs": None, "stats": None, "stderr": "",
           "cg": None, "nodes": None, "stats_after": None,
           "error": None, "error_replay": None, "error0": None}
    try:
        _build_lib(root)
        entry = {"path": "knowledge/c_new.md", "layer": "knowledge",
                 "bucket": "n225"}
        _write_bad_shard(root, entry)
        # ---- ① 分片日志读面（不构造 MdCG，与装载面解耦）----
        F.reset_nonobject_row_stats()
        buf = io.StringIO()
        try:
            with redirect_stderr(buf):
                ctx["recs"] = F.ShardedLog.read_all(
                    os.path.join(root, "_index_log"))
        except Exception as exc:          # noqa: BLE001
            ctx["error"] = exc
        ctx["stderr"] = buf.getvalue()
        ctx["stats"] = F.nonobject_row_stats()
        # ---- ② 索引重放面（合法快照 + 坏分片）----
        try:
            cg = MdCG(root, autoflush=1)
            ctx["cg"] = cg
            _LIVE.append(cg)
            ctx["nodes"] = set(cg.index["nodes"])
        except Exception as exc:          # noqa: BLE001
            ctx["error_replay"] = exc
        ctx["stats_after"] = F.nonobject_row_stats()
    except Exception as exc:              # noqa: BLE001
        ctx["error0"] = exc
    return ctx


# 生效条件：无入参时建库 → 写坏**载荷**分片 → 重置记账 → 构造 MdCG（合法快照基底 + 坏载荷重放）→ 再调同一个实例的 compact_index()（同一批坏载荷走第二次重放）；返回上下文 dict（root / cg / nodes / nodes_after_compact / payload_before / payload_after / stderr / err / err_compact / idx）。
def _case_payload() -> dict:
    root = _tmpdir("mdcg_n225_payload_")
    ctx = {"root": root, "cg": None, "nodes": None, "idx": None,
           "payload_before": None, "payload_after": None, "total_after": None,
           "stderr": "", "err": None, "err_compact": None, "err0": None}
    try:
        _build_lib(root)
        _write_payload_shard(root)
        F.reset_nonobject_row_stats()
        buf = io.StringIO()
        try:
            with redirect_stderr(buf):
                cg = MdCG(root, autoflush=1)
                ctx["cg"] = cg
                _LIVE.append(cg)
                ctx["nodes"] = cg.index["nodes"]
                ctx["payload_before"] = F.bad_payload_row_stats()[0]
                try:
                    ctx["idx"] = cg.compact_index()
                except Exception as exc:  # noqa: BLE001
                    ctx["err_compact"] = exc
                ctx["payload_after"] = F.bad_payload_row_stats()[0]
                ctx["total_after"] = F.nonobject_row_stats()[0]
        except Exception as exc:          # noqa: BLE001
            ctx["err"] = exc
        ctx["stderr"] = buf.getvalue()
    except Exception as exc:              # noqa: BLE001
        ctx["err0"] = exc
    return ctx


# 生效条件：legal(v) 为真当且仅当 v 为 int/float 且 v == v（非 NaN）——即排序键的「合法槽」口径。
def _legal_slot(v) -> bool:
    return isinstance(v, (int, float)) and v == v


# 生效条件：r 为记录时，返回其排序键「坏型槽记 0、合法槽原样」二元组——与实现口径同源的断言侧表达（F3 的单调性判据用；合法记录的**次序证明**不靠它，靠 F2 的旧键 oracle 逐位对照）。
def _norm_key(r):
    return tuple(v if _legal_slot(v) else 0
                 for v in (r.get("_t", 0), r.get("_s", 0)))


# 生效条件：rows 为记录列表时，取其中 _t 与 _s 两槽都合法的记录，按**改前旧键** (r.get("_t", 0), r.get("_s", 0)) 排序后返回——改前行为的独立 oracle（不调用被测实现，只用 Python 内建 sorted）。
def _oracle_legal(rows):
    keep = [r for r in rows
            if _legal_slot(r.get("_t", 0)) and _legal_slot(r.get("_s", 0))]
    return sorted(keep, key=lambda r: (r.get("_t", 0), r.get("_s", 0)))


# 生效条件：d 为分片目录时，按 read_all 的收集序（分片名序 + 文件行序）经 F.read_jsonl 取全部 dict 行返回——oracle 的输入面（不调用 read_all）。
def _collect_rows(d: str):
    out = []
    for fn in sorted(os.listdir(d)):
        if not fn.endswith(".log"):
            continue
        for rec in F.read_jsonl(os.path.join(d, fn)):
            if isinstance(rec, dict):
                out.append(rec)
    return out


# 生效条件：无入参时在临时目录下用**生产写点**（ShardedLog.append，两个写者实例=两个分片，含并列 _t、跨写者重叠 _s、乱序写入）造真实分片记录，再手写一份坏型排序键分片（str/list/None/NaN 四形态 + 一行缺 _t 的合法行）→ 重置记账 → 以 redirect_stderr 捕获告警后调 read_all；返回上下文 dict（root / d / rows / oracle / old_raises / recs / got_legal / sortkey_before / stderr / err）。
def _case_sortkey() -> dict:
    root = _tmpdir("mdcg_n225_sortkey_")
    ctx = {"root": root, "d": os.path.join(root, "shards"), "rows": None,
           "oracle": None, "old_raises": None, "recs": None,
           "got_legal": None, "sortkey_before": None, "stderr": "",
           "err": None, "err0": None}
    try:
        d = ctx["d"]
        os.makedirs(d, exist_ok=True)
        # 写者 A / B（各占一个分片）：真实写点产出的记录（_t 为 time.time 形态、
        # _s 为分片内序号，两个写者的 _s 故意重叠 ⇒ 跨分片合并必须靠 (t, s) 定序）
        lg_a = F.ShardedLog(d)
        for t, s, nid in ((1000.0, 1, "a"), (1000.0, 2, "b"), (999.0, 3, "c"),
                          (1000.0, 4, "d"), (1002.0, 5, "e")):
            lg_a.append({"id": nid, "e": {"path": "knowledge/%s.md" % nid,
                                          "bucket": "k"}, "_t": t, "_s": s})
        lg_a.close()
        lg_b = F.ShardedLog(d)
        for t, s, nid in ((1000.0, 1, "f"), (997.5, 2, "g"), (1000.0, 3, "h")):
            lg_b.append({"id": nid, "e": {"path": "knowledge/%s.md" % nid,
                                          "bucket": "k"}, "_t": t, "_s": s})
        lg_b.close()
        rows = [
            {"id": "s1", "e": {"path": "knowledge/s1.md"}, "_t": "abc",
             "_s": 9},                          # str 槽
            {"id": "s2", "e": {"path": "knowledge/s2.md"}, "_t": 5.0,
             "_s": []},                         # list 槽
            {"id": "s3", "e": {"path": "knowledge/s3.md"}, "_s": 11},  # 缺 _t（合法）
            {"id": "s4", "e": {"path": "knowledge/s4.md"}, "_t": None,
             "_s": None},                       # None 槽
            {"id": "s5", "e": {"path": "knowledge/s5.md"},
             "_t": float("nan"), "_s": 1},      # NaN 槽
        ]
        with open(os.path.join(d, "9999-badkey.log"), "w",
                  encoding="utf-8") as f:
            f.write("\n".join(json.dumps(r, ensure_ascii=False)
                              for r in rows) + "\n")
        ctx["rows"] = _collect_rows(d)
        try:
            sorted(ctx["rows"], key=lambda r: (r.get("_t", 0), r.get("_s", 0)))
            ctx["old_raises"] = False
        except TypeError as exc:
            ctx["old_raises"] = "%s: %s" % (type(exc).__name__, exc)
        ctx["oracle"] = _oracle_legal(ctx["rows"])
        F.reset_nonobject_row_stats()
        buf = io.StringIO()
        try:
            with redirect_stderr(buf):
                ctx["recs"] = F.ShardedLog.read_all(d)
        except Exception as exc:          # noqa: BLE001
            ctx["err"] = exc
        ctx["stderr"] = buf.getvalue()
        if isinstance(ctx["recs"], list):
            ctx["got_legal"] = [r for r in ctx["recs"]
                                if _legal_slot(r.get("_t", 0))
                                and _legal_slot(r.get("_s", 0))]
        ctx["sortkey_before"] = F.bad_sortkey_row_stats()[0]
    except Exception as exc:              # noqa: BLE001
        ctx["err0"] = exc
    return ctx


# 生效条件：无入参时建库 → 写 tombstone 分片（n2 的删除记录）→ 构造 MdCG（合法快照基底 + tombstone 重放）→ 再调同一实例的 compact_index()；返回上下文 dict（root / cg / nodes / idx / err / err_compact / err0）。
def _case_tombstone() -> dict:
    root = _tmpdir("mdcg_n225_tomb_")
    ctx = {"root": root, "cg": None, "nodes": None, "idx": None,
           "err": None, "err_compact": None, "err0": None}
    try:
        _build_lib(root)
        _write_tombstone_shard(root)
        cg = MdCG(root, autoflush=1)
        ctx["cg"] = cg
        _LIVE.append(cg)
        ctx["nodes"] = set(cg.index["nodes"])
        try:
            ctx["idx"] = cg.compact_index()
        except Exception as exc:          # noqa: BLE001
            ctx["err_compact"] = exc
    except Exception as exc:              # noqa: BLE001
        ctx["err"] = exc
    return ctx


# 生效条件：无入参时在临时目录写一份 jsonl（两条合法 dict 行 + 四行非对象行，非对象行夹在中间），直接调 F.read_jsonl 取产出序列；返回上下文 dict（path / got / error）。
def _case_jsonl() -> dict:
    root = _tmpdir("mdcg_n225_jsonl_")
    p = os.path.join(root, "x.jsonl")
    with open(p, "w", encoding="utf-8") as f:
        f.write('{"a":1}\nnull\n[]\n123\n"abc"\n{"a":2}\n')
    ctx = {"path": p, "got": None, "error": None}
    try:
        ctx["got"] = list(F.read_jsonl(p))
    except Exception as exc:              # noqa: BLE001
        ctx["error"] = exc
    return ctx


# 模拟宿主前先把「身份/路径/编码」注入面清干净——子进程只吃临时目录（与 N206 同款）
_DIRTY_KEYS = (
    "MDCG_TOKEN", "MDCG_TOKEN_FILE", "MDCG_MASTER_KEY", "MDCG_CLEARANCE",
    "MDCG_TENANT", "MDCG_TENANT_REGISTRY",
    "MDCG_CAN_ADMIN", "MDCG_CAN_WRITE", "MDCG_LEGACY_ENV_AUTH",
    "MDCG_LEGACY_ENV_ADMIN", "MDCG_SESSION", "DSH_SESSION_ID",
    "MDCG_HARNESS", "MDCG_UNIT", "MDCG_ROOT", "MDCG_STATE_ROOT",
    "MDCG_DATA_ROOT", "MDCG_AUX_ROOT", "MDCG_SUSTAIN", "MDCG_SUSTAIN_NAME",
    "MDCG_MCP_SURFACE", "MDCG_TOOL_FACE", "MDCG_ACTOR",
    "MDCG_VERIFIER_MODULES", "MDCG_HIVE_JOBS",
    "PYTHONUTF8", "PYTHONIOENCODING", "PYTHONLEGACYWINDOWSSTDIO",
)


# 生效条件：tmp 为本次隔离根时，返回剔净 _DIRTY_KEYS 后的 os.environ 副本再注入九个指向 tmp 的覆盖键（MDCG_ROOT / MDCG_TENANT_REGISTRY / MDCG_STATE_ROOT / MDCG_DATA_ROOT / MDCG_AUX_ROOT / MDCG_SUSTAIN / MDCG_LEGACY_ENV_AUTH / MDCG_ACTOR，外加指向临时路径的 MDCG_TOKEN_FILE 与哑主密钥 MDCG_MASTER_KEY）——子进程绝不读真实 ~/.mdcg、真实令牌库与真实密钥面。
def _env(tmp: str) -> dict:
    env = {k: v for k, v in os.environ.items() if k not in _DIRTY_KEYS}
    env["MDCG_ROOT"] = os.path.join(tmp, "cgroot")
    # 登记表指向**不存在**的临时路径 → 空表回落，绝不读真实 ~/.mdcg
    env["MDCG_TENANT_REGISTRY"] = os.path.join(tmp, "_tenants_absent.json")
    env["MDCG_STATE_ROOT"] = os.path.join(tmp, "state")
    env["MDCG_DATA_ROOT"] = os.path.join(tmp, "data")
    # 子目录名不可取 "aux"（Windows 保留设备名，见 test_issue39 头注）
    env["MDCG_AUX_ROOT"] = os.path.join(tmp, "auxroot")
    env["MDCG_TOKEN_FILE"] = os.path.join(tmp, "tokens.json")   # 临时令牌库
    env["MDCG_MASTER_KEY"] = "00" * 32                          # 哑主密钥
    env["MDCG_SUSTAIN"] = "0"              # 关常驻循环（线程面归零）
    env["MDCG_LEGACY_ENV_AUTH"] = "1"      # 既有豁免面：零令牌、无二次开关
    env["MDCG_ACTOR"] = "n225-guard"
    return env


# 当前生效的变异（仅 --branch-baseline 期间非 None）：内存 patch 不跨进程，
# D 组走独立子进程 ⇒ 靠 sitecustomize 把同一处定点变异注入子进程，端到端面
# 才有真正的判别力。注入以 stderr 标记自证，标记缺失即 D 组判红（fail-closed）。
_MUTATION = [None]

_SITECUSTOMIZE_SRC = '''# N225 守卫跨进程变异注入（临时件，随 tmp 目录一并回收）
import os
import sys
import textwrap
import inspect
_repo = os.environ.get("N225_REPO") or ""
if _repo and _repo not in sys.path:
    sys.path.insert(0, _repo)
try:
    from md_cg import mdcg as _M, fsutil as _F
    _which = os.environ["N225_MUT_WHICH"]
    _fname = os.environ["N225_MUT_FUNC"]
    _old = os.environ["N225_MUT_OLD"]
    _new = os.environ["N225_MUT_NEW"]
    if _which == "mdcg":
        _holder, _raw = _M.MdCG, _M.MdCG.__dict__[_fname]
    elif _which == "fsutil":
        _holder, _raw = _F.ShardedLog, _F.ShardedLog.__dict__[_fname]
    else:                                     # fsutil_mod：模块级函数
        _holder, _raw = _F, _F.__dict__[_fname]
    _src = inspect.getsource(getattr(_raw, "__func__", _raw))
    _src = textwrap.dedent(_src[_src.index("def %s(" % _fname):])
    _ns = dict(vars(_M if _which == "mdcg" else _F))
    _ns.setdefault("__name__", "n225_mut")
    exec(compile(_src.replace(_old, _new), "n225_mut.py", "exec"), _ns)
    if _which == "fsutil":
        setattr(_holder, _fname, staticmethod(_ns[_fname]))
    else:
        setattr(_holder, _fname, _ns[_fname])
    sys.stderr.write("[n225-mut] injected %s.%s\\n" % (_which, _fname))
except Exception as _e:
    sys.stderr.write("[n225-mut] inject FAILED: %r\\n" % (_e,))
'''


# 生效条件：lines 为待喂给 stdin 的字符串序列、tmp 为隔离根时，spawn `python -X utf8 -m md_cg.mcp_server`（cwd=仓根、env=_env(tmp)）一次喂完并 communicate；超时则 kill 后取残余输出；随后删掉**本子进程自己**的自报戳；返回 (returncode, stdout, stderr)。
def _talk(lines, tmp: str, timeout: int = 180):
    env = _env(tmp)
    mut = _MUTATION[0]
    if mut is not None:
        # 跨进程注入：sitecustomize 是 Python 启动时自动 import 的官方钩子，
        # 放到 PYTHONPATH 上即被本子进程吃到——生产启动形态（-m）保持不变。
        sc_dir = os.path.join(tmp, "_mutpath")
        os.makedirs(sc_dir, exist_ok=True)
        with open(os.path.join(sc_dir, "sitecustomize.py"), "w",
                  encoding="utf-8") as f:
            f.write(_SITECUSTOMIZE_SRC)
        env["PYTHONPATH"] = sc_dir + os.pathsep + env.get("PYTHONPATH", "")
        env["N225_REPO"] = os.path.dirname(os.path.dirname(
            os.path.abspath(__file__)))
        env["N225_MUT_WHICH"] = mut["which"]
        env["N225_MUT_FUNC"] = mut["func"]
        env["N225_MUT_OLD"] = mut["old"]
        env["N225_MUT_NEW"] = mut["new"]
    proc = subprocess.Popen(
        [sys.executable, "-X", "utf8", "-m", "md_cg.mcp_server"],
        cwd=os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        env=env, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
        stderr=subprocess.PIPE, text=True, encoding="utf-8", errors="replace")
    try:
        out, err = proc.communicate("\n".join(lines) + "\n", timeout=timeout)
    except subprocess.TimeoutExpired:
        proc.kill()
        out, err = proc.communicate()
    try:
        os.remove(os.path.join(tempfile.gettempdir(), "md_cg_servers",
                               "%d.json" % proc.pid))
    except OSError:
        pass
    return proc.returncode, out or "", err or ""


# 生效条件：rid/method 给定、params 为 None 时省略该键，否则原样写入；返回一行紧凑 JSON-RPC 请求文本。
def _rpc(rid, method, params=None) -> str:
    msg = {"jsonrpc": "2.0", "id": rid, "method": method}
    if params is not None:
        msg["params"] = params
    return json.dumps(msg, ensure_ascii=False)


# 生效条件：out 为 stdout 文本时逐行 strip、空行跳过，返回 [(原始行, 解析结果或 None)]（解析失败记 None，供「全行合法」类断言消费）。
def _resp_lines(out: str):
    got = []
    for ln in out.splitlines():
        ln = ln.strip()
        if not ln:
            continue
        try:
            got.append((ln, json.loads(ln)))
        except ValueError:
            got.append((ln, None))
    return got


# 生效条件：obj 为 dict 时返回其 error.code，否则返回 None。
def _err_code(obj):
    return (obj.get("error") or {}).get("code") if isinstance(obj, dict) else None


# 生效条件：端到端场景——建库 → 把快照覆盖为非对象 `[]` → 写坏分片 → 起 stdio 主循环喂 [initialize, tools/list, "[]", tools/list, shutdown]，返回上下文 dict（tmp / rc / out / err / objs / by_id / error）。
def _case_stdio() -> dict:
    tmp = _tmpdir("mdcg_n225_stdio_")
    ctx = {"tmp": tmp, "rc": None, "out": "", "err": "", "objs": [],
           "by_id": {}, "error": None, "inject_ok": True}
    try:
        root = os.path.join(tmp, "cgroot")
        _build_lib(root)
        _overwrite(os.path.join(root, "_index.json"), "[]")
        _write_bad_shard(root, {"path": "knowledge/c_new.md",
                                "layer": "knowledge", "bucket": "n225"})
        lines = [_rpc(1, "initialize"), _rpc(2, "tools/list"),
                 "[]", _rpc(3, "tools/list"), _rpc(4, "shutdown")]
        ctx["rc"], ctx["out"], ctx["err"] = _talk(lines, tmp)
        # 注入自证：变异轮里子进程必须报告「已注入」，否则 D 组判红（fail-closed，
        # 避免「注入失效」被误读成「端到端面无判别力」）。
        ctx["inject_ok"] = ("[n225-mut] injected" in ctx["err"]
                            if _MUTATION[0] is not None else True)
        objs = [o for _raw, o in _resp_lines(ctx["out"])]
        ctx["objs"] = objs
        ctx["by_id"] = {o.get("id"): o for o in objs if isinstance(o, dict)}
    except Exception as exc:              # noqa: BLE001
        ctx["error"] = exc
    return ctx


# ---------------- A 装载面：四种非对象形态 ----------------

# 生效条件：逐形态跑 A 组 5 条断言（构造不抛 / 确有全库扫描 / 既有节点一个不丢 / 不退化成空池 / 探活重载不抛且节点仍全）；ctx 由 _case_load 产出，构造失败时五条各自判红。
def g_a():
    begin("A")
    for tag, body in BODIES:
        print("[A·%s] %s" % (tag, json.dumps(body)))
        ctx = _case_load(body)
        cg = ctx["cg"]
        check_fn("A·%s·构造不抛（非对象快照视同损坏，走既有降级路径）" % tag,
                 lambda c=ctx: c["error"] is None,
                 "err=%r" % (ctx["error"],))
        check_fn("A·%s·确有全库扫描（_scan_nodes 被调用，非快照路径）" % tag,
                 lambda c=ctx: c["scans"][0] >= 1,
                 "scans=%d" % ctx["scans"][0])
        check_fn("A·%s·既有节点一个不丢（{n1,n2} ⊆ nodes）" % tag,
                 lambda c=cg: {"n1", "n2"} <= set(c.index["nodes"]),
                 "nodes=%s" % (sorted(cg.index["nodes"]) if cg else None))
        check_fn("A·%s·不得退化成空池（len(nodes) 与盘面 .md 数一致且 ≥2）"
                 % tag,
                 lambda c=cg: (c is not None
                               and len(c.index["nodes"]) == c._count_md_files()
                               and len(c.index["nodes"]) >= 2),
                 "nodes=%s surf=%s" % (
                     len(cg.index["nodes"]) if cg else None,
                     cg._count_md_files() if cg else None))

        def _probe(c=cg, t=tag):
            # 存活实例 + 外部再写一次非对象快照（签名变化）→ 探活必须重载成功。
            # 这一条钉住「_maybe_reload_index 不得因非对象而抛」。
            other = [b for n, b in BODIES if n != t][0]
            if c is None:
                return False
            _overwrite(os.path.join(c.root, "_index.json"), other)
            fired = c._maybe_reload_index()
            return fired is True and {"n1", "n2"} <= set(c.index["nodes"])

        check_fn("A·%s·探活重载不抛且节点仍全（_maybe_reload_index 收口）"
                 % tag, _probe)
        try:
            if cg is not None:
                cg.close()
        except Exception:                 # noqa: BLE001
            pass


# ---------------- B compact 面：四种非对象形态 ----------------

# 生效条件：逐形态跑 B 组 4 条断言（compact 不抛 / 落盘快照恢复为可再装载 dict / 不清池，账本对得上盘面 / 返回值含既有节点）；ctx 由 _case_compact 产出。
def g_b():
    begin("B")
    for tag, body in BODIES:
        print("[B·%s] %s" % (tag, json.dumps(body)))
        ctx = _case_compact(body)
        snap_path = os.path.join(ctx["root"], "_index.json")

        def _snap():
            with open(snap_path, encoding="utf-8") as f:
                return json.load(f)

        check_fn("B·%s·compact_index 不抛（非对象视同损坏走 scan_fallback）"
                 % tag, lambda c=ctx: c["error"] is None,
                 "err=%r" % (ctx["error"],))
        check_fn("B·%s·落盘快照恢复为可再装载 dict（schema 正确）" % tag,
                 lambda: isinstance(_snap(), dict)
                 and _snap().get("schema") == M.SCHEMA)
        check_fn("B·%s·不清池（快照 nodes 数 == 盘面 .md 数）" % tag,
                 lambda: len((_snap().get("nodes") or {})) == ctx["surf"]
                 and ctx["surf"] >= 2,
                 lambda: "snap_nodes=%s surf=%s" % (
                     len((_snap().get("nodes") or {}))
                     if isinstance(_snap(), dict) else None, ctx["surf"]))
        check_fn("B·%s·compact 返回值含既有节点" % tag,
                 lambda c=ctx: isinstance(c["idx"], dict)
                 and {"n1", "n2"} <= set(c["idx"].get("nodes") or {}))


# ---------------- C 分片日志面：非对象行 ----------------

# 生效条件：跑 C 组 9 条断言（read_all 不抛 / 只返回 dict 且条数正确 / 逐条是 dict / 坏行计数可断言 / stderr 告警可观测 / tombstone 记录保留在返回列表 / 排序有效；重放面：构造不抛 / 合法新记录生效）；ctx 由 _case_shard 产出。
def g_c():
    begin("C")
    ctx = _case_shard()
    recs = ctx["recs"]
    stats = ctx["stats"] or (None, ())

    check_fn("C1·read_all 不崩（非对象行不参与排序键）",
             lambda c=ctx: c["error"] is None and c["error0"] is None,
             "err=%r err0=%r" % (ctx["error"], ctx["error0"]))
    check_fn("C2·只返回 dict 记录且条数正确（合法 1 条 + tombstone 1 条 = 2）",
             lambda: isinstance(recs, list) and len(recs) == 2,
             "recs=%r" % (recs,))
    check_fn("C3·返回记录逐条是 dict（非对象行未混入）",
             lambda: isinstance(recs, list) and all(isinstance(r, dict)
                                                    for r in recs),
             "types=%s" % ([type(r).__name__ for r in recs]
                           if isinstance(recs, list) else None))
    check_fn("C4·坏行计数可断言（本片 4 条非对象行全部记账）",
             lambda: stats[0] == 4, "skips=%s" % (stats[0],))
    check_fn("C5·stderr 告警可观测（不静默：含分片名与条数）",
             lambda: "ShardedLog.read_all" in ctx["stderr"]
             and "4 条非对象" in ctx["stderr"],
             "stderr=%r" % (ctx["stderr"][:200],))
    check_fn("C6·tombstone 记录仍保留在返回列表（e=None 不得当坏行丢掉）",
             lambda: any(r.get("id") == "n2" and r.get("e") is None
                         for r in recs),
             "recs=%r" % (recs,))
    check_fn("C7·排序有效（按 (_t,_s) 单调不减，非对象行未污染次序）",
             lambda: all((recs[i].get("_t", 0), recs[i].get("_s", 0))
                         <= (recs[i + 1].get("_t", 0), recs[i + 1].get("_s", 0))
                         for i in range(len(recs) - 1)),
             "recs=%r" % (recs,))
    check_fn("C8·重放面：合法快照 + 坏分片下 MdCG 构造不抛",
             lambda c=ctx: c["error_replay"] is None,
             "err=%r" % (ctx["error_replay"],))
    check_fn("C9·重放面：坏分片里的合法新记录生效（c_new 可见）",
             lambda c=ctx: c["nodes"] is not None and "c_new" in c["nodes"],
             "nodes=%s" % (sorted(ctx["nodes"]) if ctx["nodes"] else None))


# ---------------- D stdio 端到端 ----------------

# 生效条件：跑 D 组 5 条断言（rc=0 / initialize 应答 / tools/list 应答 / 非对象行仍回 -32600 / 攻击行之后仍应答）；ctx 由 _case_stdio 产出，spawn 失败或进程即死时五条各自判红。
def g_d():
    begin("D")
    ctx = _case_stdio()
    by_id = ctx["by_id"]

    def _init():
        return ((by_id.get(1) or {}).get("result") or {}) \
            .get("serverInfo", {}).get("name")

    def _tools(rid):
        return ((by_id.get(rid) or {}).get("result") or {}).get("tools")

    check_fn("D1·非对象快照 + 坏分片下 stdio 主循环仍存活（rc=0）",
             lambda c=ctx: c["rc"] == 0 and c["inject_ok"],
             "rc=%r inject=%s stderr_tail=%r"
             % (ctx["rc"], ctx["inject_ok"], ctx["err"][-300:]))
    check_fn("D2·initialize 应答（serverInfo=mdcg-mcp）",
             lambda: _init() == "mdcg-mcp" and ctx["inject_ok"],
             "by_id[1]=%s" % (str(by_id.get(1))[:200],))
    check_fn("D3·tools/list 应答且工具表非空",
             lambda: isinstance(_tools(2), list) and len(_tools(2)) > 0
             and ctx["inject_ok"],
             "by_id[2]=%s" % (str(by_id.get(2))[:200],))
    check_fn("D4·非对象行仍回 id=null 的 -32600（入口闸未因坏数据失能）",
             lambda: ctx["inject_ok"] and any(
                 isinstance(o, dict) and o.get("id") is None
                 and _err_code(o) == -32600 for o in ctx["objs"]),
             "objs=%s" % (json.dumps(ctx["objs"], ensure_ascii=False)[:300],))
    check_fn("D5·攻击行之后的 tools/list 仍应答（不是半途死）",
             lambda: isinstance(_tools(3), list) and len(_tools(3)) > 0
             and ctx["inject_ok"],
             "by_id[3]=%s" % (str(by_id.get(3))[:200],))


# ---------------- E 载荷坏型收口（契约②） ----------------

# 生效条件：跑 E 组 6 条断言（装载不抛 / 坏载荷不进 nodes / 合法 upsert 仍生效 / 记账可断言且不静默 / compact 面不抛且快照无坏载荷 id / 两面对同一分片的 nodes 逐键相等）；ctx 由 _case_payload 产出，装载即失败时六条各自判红。
def g_e():
    begin("E")
    ctx = _case_payload()
    bad_ids = {"p_arr", "p_int", "p_str"}
    nodes = ctx["nodes"] or {}

    check_fn("E1·装载面：坏载荷分片下 MdCG 构造不抛（e 非 dict 不进 _count_buckets）",
             lambda c=ctx: c["err"] is None and c["err0"] is None and c["cg"] is not None,
             "err=%r err0=%r" % (ctx["err"], ctx["err0"]))
    check_fn("E2·装载面：三条坏载荷 id 一个都不进 nodes（跳过而非覆盖）",
             lambda c=ctx: c["err"] is None and not (bad_ids & set(c["nodes"] or {})),
             "nodes=%s" % (sorted(nodes) if nodes else None))
    check_fn("E3·装载面：同批里的合法 upsert 仍生效（n1.bucket=n225pay）",
             lambda: isinstance(nodes.get("n1"), dict)
             and nodes["n1"].get("bucket") == "n225pay",
             "n1=%r" % (nodes.get("n1"),))
    check_fn("E4·装载面：坏载荷行计入记账面（子面 3 条）且不静默（stderr 含条数）",
             lambda c=ctx: c["payload_before"] == 3
             and "载荷坏型记录" in c["stderr"] and "3 条" in c["stderr"],
             "payload=%r stderr=%r" % (ctx["payload_before"],
                                       ctx["stderr"][:160]))
    check_fn("E5·compact 面：不抛且落盘/返回索引里坏载荷 id 全不在（同一分片第二次重放）",
             lambda c=ctx: c["err_compact"] is None
             and isinstance(c["idx"], dict)
             and not (bad_ids & set(c["idx"]["nodes"])),
             "err=%r nodes=%s" % (ctx["err_compact"],
                                  sorted(ctx["idx"]["nodes"])
                                  if isinstance(ctx["idx"], dict) else None))
    check_fn("E6·两面同口径：compact 后 nodes 与装载面逐键相等，且同批坏载荷同样记账（子面共 6 条）",
             lambda c=ctx: isinstance(c["idx"], dict)
             and c["idx"]["nodes"] == nodes
             and c["payload_after"] == 6 and c["total_after"] == 6,
             "equal=%s payload=%r total=%r" % (
                 (isinstance(ctx["idx"], dict) and ctx["idx"]["nodes"] == nodes),
                 ctx["payload_after"], ctx["total_after"]))


# ---------------- F 排序键健壮化（契约①） ----------------

# 生效条件：跑 F 组 5 条断言（read_all 不抛且旧键直排在同一批记录上必抛 / 合法记录与旧键 oracle 逐位一致 / 记录一个不丢且按键单调不减 / 坏型键计数可断言 / 不静默）；ctx 由 _case_sortkey 产出，read_all 抛异常时五条各自判红。
def g_f():
    begin("F")
    ctx = _case_sortkey()
    recs = ctx["recs"]
    oracle = ctx["oracle"] or []
    got = ctx["got_legal"]

    check_fn("F1·read_all 不抛**且**旧键直排在同一批记录上必抛（fixture 有判别力）",
             lambda c=ctx: c["err"] is None and c["err0"] is None
             and c["old_raises"] is not False
             and c["old_raises"] is not None,
             "err=%r old=%r" % (ctx["err"], ctx["old_raises"]))
    check_fn("F2·合法记录相对次序与改前逐位一致（与旧键 oracle 的序与内容全等）",
             lambda: got is not None and oracle == got,
             "oracle=%s got=%s" % ([r.get("id") for r in oracle],
                                   [r.get("id") for r in got]
                                   if got is not None else None))
    check_fn("F3·记录一个不丢且返回列表按键单调不减（坏型槽记 0 参与排序）",
             lambda c=ctx: isinstance(recs, list)
             and len(recs) == len(ctx["rows"] or [])
             and all(_norm_key(recs[i]) <= _norm_key(recs[i + 1])
                     for i in range(len(recs) - 1)),
             "n=%s keys=%s" % (len(recs) if isinstance(recs, list) else None,
                               [_norm_key(r) for r in recs]
                               if isinstance(recs, list) else None))
    check_fn("F4·坏型排序键计数可断言（str/list/None/NaN 四形态各 1 条 = 4）",
             lambda c=ctx: c["sortkey_before"] == 4,
             "n=%r samples=%s" % (ctx["sortkey_before"],
                                  F.bad_sortkey_row_stats()[1][:2]))
    check_fn("F5·不静默（stderr 含条数、分片名与两个槽类型）",
             lambda c=ctx: "排序键坏型 4 条" in c["stderr"]
             and "9999-badkey.log" in c["stderr"] and "_t=str" in c["stderr"],
             "stderr=%r" % (ctx["stderr"][:200],))


# ---------------- G tombstone 语义（e is None ⇒ pop） ----------------

# 生效条件：跑 G 组 2 条断言（装载面 tombstone 重放生效、compact 面同款）；ctx 由 _case_tombstone 产出，构造失败时两条各自判红。
def g_g():
    begin("G")
    ctx = _case_tombstone()
    nodes = ctx["nodes"]

    check_fn("G1·装载面：e is None ⇒ pop 该 nid（删除可重放，节点不复活）",
             lambda c=ctx: c["err"] is None and c["nodes"] is not None
             and "n2" not in c["nodes"] and "n1" in c["nodes"],
             "err=%r nodes=%s" % (ctx["err"],
                                  sorted(nodes) if nodes else None))
    check_fn("G2·compact 面：快照与返回值同样 pop 该 nid（与装载面同口径）",
             lambda c=ctx: c["err_compact"] is None
             and isinstance(c["idx"], dict)
             and "n2" not in c["idx"]["nodes"] and "n1" in c["idx"]["nodes"],
             "err=%r nodes=%s" % (
                 ctx["err_compact"],
                 sorted(ctx["idx"]["nodes"])
                 if isinstance(ctx["idx"], dict) else None))


# ---------------- H read_jsonl 通用面（非对象行原样产出） ----------------

# 生效条件：跑 H 组 2 条断言（产出类型序列逐位一致、产出对象与 json.loads 同值——即只在 read_all 层过滤，read_jsonl 通用契约未改）；ctx 由 _case_jsonl 产出。
def g_h():
    begin("H")
    ctx = _case_jsonl()
    got = ctx["got"]

    check_fn("H1·read_jsonl 原样产出非对象行（类型序列逐位一致）",
             lambda c=ctx: c["error"] is None and isinstance(c["got"], list)
             and [type(x).__name__ for x in c["got"]]
             == ["dict", "NoneType", "list", "int", "str", "dict"],
             "err=%r types=%s" % (ctx["error"],
                                  [type(x).__name__ for x in got]
                                  if isinstance(got, list) else None))
    check_fn("H2·read_jsonl 不做类型改造（产出对象与 json.loads 结果同值）",
             lambda c=ctx: isinstance(c["got"], list) and len(c["got"]) == 6
             and c["got"][1] is None and c["got"][2] == [] and c["got"][3] == 123
             and c["got"][4] == "abc",
             "got=%r" % (got,))


_GROUPS = (("A", g_a), ("B", g_b), ("C", g_c), ("D", g_d), ("E", g_e),
           ("F", g_f), ("G", g_g), ("H", g_h))


# 生效条件：重算计数器后依次跑 A–H 八组（静默与否由 print 决定），返回 (总失败数, {组名: 失败数} 的副本)；供正常模式与 --branch-baseline 的变异核验共用。
def _run_groups():
    _reset_counters()
    for _name, fn in _GROUPS:
        fn()
    return FAIL, dict(_GROUP_FAILS)


# ---------------- 定点变异自证（--branch-baseline） ----------------

# 变异表：逐处关掉一个判据，守卫**必须转红**，且红项**恰好**落在该判据负责的
# 组、数量等于该组断言数（多一项少一项都报红）。基线源=**工作区源码**
# （inspect.getsource 取自当前已加载模块），绝不绑 git HEAD——本仓批次 80/81
# 两次教训：基线绑提交那一刻即失效。
#
# 组/判据一一对应（见模块头注「组与判据一一对应」）：①装载面类型闸（A 20 +
# 端到端 D 5，D 的病理本就是非对象快照）②compact 面类型闸（B 16）③日志面非对象
# 行过滤（C 9 + D 5，D 的另一个病理是非对象行）④载荷坏型闸（E 6）⑤载荷闸口径
# 过宽（G 2——把 e is None 的 tombstone 也当坏载荷）⑥排序键归一（F 5）⑦tombstone
# 重放（G 2——与⑤从「过窄/过宽」两侧把同一口径钉死）⑧read_jsonl 原样产出（H 2）。
_MUTATIONS = (
    ("装载面类型闸（_load_index 非对象视同损坏）",
     "mdcg", "_load_index",
     'if isinstance(d, dict) and d.get("schema") == SCHEMA:',
     'if d.get("schema") == SCHEMA:',
     {"A": 20, "D": 5}),
    ("compact 面类型闸（非对象走 scan_fallback）",
     "mdcg", "compact_index",
     "if not isinstance(d, dict):", "if False:",
     {"B": 16}),
    ("分片日志非对象行过滤（read_all 跳过 + 记账）",
     "fsutil", "read_all",
     "if not isinstance(rec, dict):", "if False:",
     {"C": 9, "D": 5}),
    ("载荷坏型闸（_apply_log 跳过 e 非 dict 且非 None + 记账）",
     "mdcg", "_apply_log",
     "if e is not None and not isinstance(e, dict):", "if False:",
     {"E": 6}),
    ("载荷闸口径过宽（把 e is None 的 tombstone 也当坏载荷跳过）",
     "mdcg", "_apply_log",
     "if e is not None and not isinstance(e, dict):",
     "if not isinstance(e, dict):",
     {"G": 2}),
    ("排序键归一（read_all：坏型槽记 0 而非直排）",
     "fsutil", "read_all",
     "isinstance(v, (int, float)) and v == v", "True",
     {"F": 5}),
    ("tombstone 重放（_apply_log：e is None ⇒ pop 该 nid）",
     "mdcg", "_apply_log",
     "nodes.pop(nid, None)", "pass",
     {"G": 2}),
    ("read_jsonl 通用面（非对象行原样产出）",
     "fsutil_mod", "read_jsonl",
     "yield json.loads(line)",
     '_o = json.loads(line)\n                yield _o if isinstance(_o, dict) else None',
     {"H": 2}),
)


# 生效条件：which 为 "mdcg" 时从 MdCG 类、为 "fsutil" 时从 ShardedLog 类、为 "fsutil_mod" 时从 fsutil 模块取 func_name 的源码文本；**从 `def <name>(` 行起截断再 dedent**——inspect.getsource 对本仓「顶格 `# 生效条件：` 注释 + 类内缩进 def」的排版会把注释/装饰器一并带来，直接 dedent 会因公共前缀为 0 而留下缩进（实测 IndentationError）；函数缺失或无法取源时返回 None。
def _func_src(which: str, func_name: str):
    try:
        if which == "mdcg":
            raw = MdCG.__dict__[func_name]
        elif which == "fsutil":
            raw = F.ShardedLog.__dict__[func_name]
        else:                              # fsutil_mod：模块级函数
            raw = F.__dict__[func_name]
        fn = getattr(raw, "__func__", raw)
        src = inspect.getsource(fn)
        return textwrap.dedent(src[src.index("def %s(" % func_name):])
    except Exception:                     # noqa: BLE001 —— 取源失败按锚点漂移处理
        return None


# 生效条件：which 为 "mdcg"/"fsutil"/"fsutil_mod"、old 在 func_name 源码中时，编译替换后的源码 exec 进对应模块命名空间并挂回目标（类属性或模块级名字；原为 staticmethod 者仍包 staticmethod），返回还原回调；old 不在源码中返回 None（调用方按 ANCHOR-MISS 处置，退出码 2）。
def _patch(which: str, func_name: str, old: str, new: str):
    src = _func_src(which, func_name)
    if src is None or old not in src:
        return None
    ns = dict(vars(M if which == "mdcg" else F))
    ns.setdefault("__name__", "n225_mut")
    exec(compile(src.replace(old, new), "n225_mut.py", "exec"), ns)
    holder = MdCG if which == "mdcg" else (F.ShardedLog if which == "fsutil"
                                           else F)
    orig = holder.__dict__[func_name]
    if isinstance(orig, staticmethod):
        setattr(holder, func_name, staticmethod(ns[func_name]))
    else:
        setattr(holder, func_name, ns[func_name])

    def _restore():
        setattr(holder, func_name, orig)

    return _restore


# 生效条件：无入参，跑定点变异自证——先跑未变异基线（必须零失败），再逐个应用 _MUTATIONS：锚点缺失立即打印 ANCHOR-MISS 并返回 2（fail-closed，不再继续）；变异后红项组与数量必须与预期完全一致，否则计入 bad；全部通过返回 0，存在不符返回 1。
def _branch_baseline() -> int:
    print("!! 定点变异模式：逐处关掉判据，守卫应当转红且**恰好**命中预期组/项数\n")
    with contextlib.redirect_stdout(io.StringIO()):
        clean_fail, _clean_groups = _run_groups()
    print("  未变异基线：失败=%d" % clean_fail)
    if clean_fail:
        print("  基线即失败 → 定点变异自证无意义（先修基线）")
        return 1
    bad = []
    for label, which, fname, old, new, expect in _MUTATIONS:
        restore = _patch(which, fname, old, new)
        if restore is None:
            print("  ANCHOR-MISS %s —— 变异锚点漂移（实现改了却没同步本表；"
                  "基线源=%s.%s）" % (label, which, fname))
            return 2                      # fail-closed：锚点漂移不静默失效
        _MUTATION[0] = {"which": which, "func": fname, "old": old, "new": new}
        try:
            with contextlib.redirect_stdout(io.StringIO()):
                got_fail, got_groups = _run_groups()
        finally:
            _MUTATION[0] = None
            restore()
            _cleanup()                    # 每轮清干净：临时根与活实例不跨轮累积
        hit = {g: n for g, n in got_groups.items() if n}
        if hit == expect and got_fail == sum(expect.values()):
            print("  关掉「%s」→ 红项=%d，命中组=%s  %s"
                  % (label, got_fail, dict(sorted(hit.items())),
                     "（恰好命中预期）"))
        else:
            print("  关掉「%s」→ 红项=%d，命中组=%s  期望=%s  "
                  "**红基线失效（判别力面不符）**"
                  % (label, got_fail, dict(sorted(hit.items())),
                     dict(sorted(expect.items()))))
            bad.append(label)
    print("\n定点变异自证：%s" % ("PASS（每处判据都有断言把它钉死）"
                                  if not bad else "FAIL —— " + "、".join(bad)))
    return 0 if not bad else 1


# 生效条件：命令行含 --branch-baseline 时走定点变异自证（退出码 0/1/2）；否则依次跑 A–H 八组打印逐条结果与汇总，全部通过返回 0、存在失败返回 1。
def main() -> int:
    if "--branch-baseline" in sys.argv:
        try:
            return _branch_baseline()
        finally:
            _cleanup()
    try:
        _reset_counters()
        for _name, fn in _GROUPS:
            fn()
    finally:
        _cleanup()
    print("\n" + "=" * 64)
    print("非对象形态索引/日志守卫（N225）：%d 通过，%d 失败" % (PASS, FAIL))
    if FAILS:
        for f in FAILS:
            print("  - %s" % f)
    return 0 if not FAILS else 1


if __name__ == "__main__":
    sys.exit(main())
