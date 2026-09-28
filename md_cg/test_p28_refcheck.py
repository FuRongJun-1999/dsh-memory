# -*- coding: utf-8 -*-
"""ref 增量索引 + 漂移/悬空巡检（P28 · R3 改造验收）。

对照 `docs/mdcg/认知图_索引与工程规范化_计划_v0.1.md` 的 R3：

  ① 统一 ref 协议 + 提取器注册表：调用方只说 `kind`，`refindex` 决定用哪个
     提取器；无提取器后缀显式报错。
  ② `_refindex.json` 增量（修 F）：`incremental=True` 时未变文件**不再读盘重切**
     （`skipped_unchanged`），节点仍在（幂等）；默认全量，保证「不漏召回」。
  ③ `op=ref action=check` 漂移/悬空巡检（修 D）：改源一行 → 报 `stale`；删除源
     文件 → 报 `dangling`；**只读、不抛、不改源文件**。
  ④ `op=ref action=stat`：看水位，最近一次索引是否被截断（`truncated` 不再静默）。
  ⑤ 接入 `sustain.diagnose`：`ref_stale` / `ref_dangling` 进入体检；`heal` 的
     `rebuild_refs` 重建派生物后漂移消除（源文件不动）。
  ⑥ 检索结果带 `ref` / `ref_kind`（读侧只加字段，不改召回逻辑）。
  ⑦ 派生物不膨胀：`_refindex.json` 体积有界、重跑不涨。
  ⑧ **判据分工**（#4）：漂移 / 悬空只由**节点自身 frontmatter ref** 判，水位只判
     「这个节点能不能跳过、不读源」（五项全等 + 源 size/mtime 未变 + 同 id 只判一次）；
     水位与节点不一致记 `ledger_mismatch` 归因行（带两侧 root），**不进 ok、不重复报红**。
  ⑨ **撞 id 现场**（D1 现状钉子）：两域同 rel path + 同 name ⇒ 同 id、节点被后写域覆盖，
     但归因行可见。本组断言**现状事实**（+ 去重 + 归因字段），不作期望语义断言——
     `node_id` 一旦改为含 root，① 会转红以提示同步迁移。
  ⑩ **口径钉子**（#5）：id 是**位置化**寻址（`sha1(路径::符号名)` / `sha1(路径#标题路径)`），
     幂等判据是**区间哈希 + 行位全等**（不是「id 存在即已索引」）。两侧都钉——实现侧
     手算 sha1 独立复算 + 对 root / 正文 / 行位不敏感 + 五项逐项不跳过；文档侧
     `docs/plans/真源索引_通用机制_v0.3.md` §3.1 的口径字面、整块指纹（**陈化硬失败**）
     与行级引用必须仍与实现同源（引用漂移即红，失败信息附现址）。
  ⑪ **常驻循环止血**：`SustainLoop._tick_heal` 按 `repeat_guard=True` 调 heal——同因重复
     失败被拦下（`repeat_failure` + 退避）而**诊断面照旧报病灶**（判据不被削弱）、
     `heals[*].failed` 单列（没修好不静默、不假装成功）。
  红基线（判别力自证，见 `_MUTATIONS` / `EXPECTED_RED`）：`--head-baseline` 对
     **工作区 `md_cg/refindex.py`** 做定点变异（快路径探测数据改回水位条目＝v1 旧行为），
     断言红项集合**恰好**等于预期三项（⑩ / ⑪ 两段钉的是别的语义，变异态下**仍绿**，
     故不入红项表——「恰好」二字正是这么被守住的）。

运行：python -m md_cg.test_p28_refcheck [--head-baseline]
"""
from __future__ import annotations

import argparse
import hashlib
import os
import re
import shutil
import sys
import tempfile
import time

from . import corpus, refindex, sources, sustain, tokens
from .mdcg import MdCG
from .mcp_server import call_tool

PASS = FAIL = 0
FAILS = []
RED = []          # 转红项 cid（红基线模式比对用；绿态为空）

_BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ROOT = os.path.join(_BASE, "_md_cg_p28")


def check(name, cond, detail="", cid=None):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  [PASS] {name}" + (f"  · {detail}" if detail else ""))
    else:
        FAIL += 1
        FAILS.append(name)
        # 无 cid 的失败记哨兵：红基线模式下它会与预期红项不等 ⇒ fail-closed，
        # 不静默放过「变异波及了没被登记的断言」（同 test_logref.py:66 的口径）。
        RED.append(cid or ("?" + name))
        print(f"  [FAIL] {name}  · {detail}")


ALPHA = ('"""能量计算模块。"""\n'
         'import math\n'
         '\n'
         '\n'
         'def compute_energy(mass, speed):\n'
         '    """计算动能。"""\n'
         '    return mass * speed * speed\n'
         '\n'
         '\n'
         'class Reactor:\n'
         '    """反应堆模型。"""\n'
         '\n'
         '    def ignite(self):\n'
         '        """点火。"""\n'
         '        self.state = "on"\n')

# 同函数同区间，只改一行实现 → 行数不变，只有区间哈希变（最强的漂移信号）
ALPHA_DRIFT = ALPHA.replace("return mass * speed * speed",
                            "return 0.5 * mass * speed * speed")
# 第二个漂移变体：段⑤ 已把源改成 ALPHA_DRIFT 并重建索引，段⑨ 要再制造一次真实漂移，
# 必须写出**与当前索引内容不同**的正文；否则只是 mtime 变了、内容没变，报 ok 才对。
ALPHA_DRIFT2 = ALPHA.replace("return mass * speed * speed",
                             "return mass * speed * speed / 2.0")
ALPHA_MARK2 = "speed * speed / 2.0"

BETA = ('"""辅助模块。"""\n'
        '\n'
        '\n'
        'def helper_scale(x):\n'
        '    """缩放。"""\n'
        '    return x * 2\n')


def rd(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


def wr(path, text, bump=0.0):
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)
    if bump:
        # 显式推后 mtime：粗粒度文件系统上保证「变了」能被水位看见
        t = os.path.getmtime(path) + bump
        os.utime(path, (t, t))


def index_read(cg, code_dir, **extra):
    a = {"op": "index_code", "path": code_dir}
    a.update(extra)
    return call_tool(cg, "cg", a)


def ref_read(cg, **args):
    a = {"op": "ref"}
    a.update(args)
    return call_tool(cg, "cg", a)


# ---------------- 6 判据分工：节点 ref 判漂移，水位只判跳过 ----------------

#: 合成源：改一行实现 → 行数不变、只有区间哈希变（最强的漂移信号，同 ALPHA_DRIFT）。
PROBE_SRC = ('"""probe 模块。"""\n'
             '\n'
             '\n'
             'def probe_fn(x):\n'
             '    """probe 函数。"""\n'
             '    return x + 1\n')
PROBE_SRC2 = PROBE_SRC.replace("return x + 1", "return x + 2")


def _mk(tmp, name):
    d = os.path.join(tmp, name)
    os.makedirs(d)
    return d


def _index_into(cg, src, ledger=None):
    """直调 refindex 的两步（index_dir → add_items），返回本轮节点 id。

    必须直调：`op=index_code` 是这两步的**连写**，表达不了「只写一侧」的分歧。
    """
    items, _errors, _stats = refindex.index_dir(src, kind="code_ref",
                                                ledger=ledger)
    ids, _sens = refindex.add_items(cg, items, kind="code_ref", root=src)
    return ids


def _tamper_ref_hash(node_path, fake="deadbeefcafe"):
    """把节点 .md 里 frontmatter 的 ref 哈希改成假值（源与水位都不动）。

    `cg.get` 每次从盘上读节点，故改 .md 即改「节点自述」；水位条目不受影响——
    这正是「漂移只由节点 ref 判」要区分的场景（v1 拿水位当探测数据 ⇒ 静默）。
    """
    with open(node_path, encoding="utf-8") as f:
        txt = f.read()
    out = re.sub(r'"hash": "[0-9a-f]{12}"', '"hash": "%s"' % fake, txt, count=1)
    if out == txt:
        raise RuntimeError("夹具失效：节点 frontmatter 里没有可篡改的 ref.hash")
    with open(node_path, "w", encoding="utf-8") as f:
        f.write(out)


def _verdict(res):
    """巡检结果 → 去重/归因视角的摘要（红基线断言只看这里）。"""
    ids = [r.get("node_id") for r in list(res.get("stale") or [])
           + list(res.get("dangling") or [])]
    return {"ok": res["ok"], "ids": ids, "dup": len(ids) - len(set(ids)),
            "mm": res.get("ledger_mismatch") or [],
            "mm_count": res.get("ledger_mismatch_count", 0)}


def guard_verdict_owner(tmp):
    """三组构造：水位与节点分别推到不同代，看快路径认谁（直调 refindex）。"""
    # ①水位新、节点旧 —— 等价 mcp_server.py 的 index_dir→add_items 之间被杀
    lib = _mk(tmp, "fo_lib")
    src = _mk(tmp, "fo_src")
    p = os.path.join(src, "probe_widget.py")
    wr(p, PROBE_SRC)
    cg = MdCG(lib)
    ids = _index_into(cg, src, refindex.Ledger(lib))
    cg.flush()
    wr(p, PROBE_SRC2, bump=5.0)
    refindex.index_dir(src, kind="code_ref", ledger=refindex.Ledger(lib))
    res = refindex.check_refs(cg, ledger=refindex.Ledger(lib))
    v = _verdict(res)
    node_hashes = {refindex.ref_of(cg.get(n))[1]["hash"] for n in ids}
    check("6①只推水位：ok=False（漂移由节点 ref 判，水位说了不算）",
          res["ok"] is False, f"ok={res['ok']} stale={len(res['stale'])}", cid="A1")
    check("6①stale 覆盖该文件全部节点，hash_expected 取节点 ref（不是水位新哈希）",
          {r["node_id"] for r in res["stale"]} == set(ids)
          and {r["hash_expected"] for r in res["stale"]} == node_hashes,
          f"stale={sorted(r['node_id'] for r in res['stale'])}", cid="A1")
    check("6①水位/节点不一致记归因行 watermark_behind（写序断裂可见，不进 ok）",
          v["mm_count"] >= 1
          and all(r["kind_of_gap"] == "watermark_behind" for r in v["mm"]),
          str(v["mm"][:1]), cid="A2")

    # ②节点新、水位旧 —— ledger 根本不参与，才算「只推节点」
    lib = _mk(tmp, "fn_lib")
    src = _mk(tmp, "fn_src")
    p = os.path.join(src, "probe_widget.py")
    wr(p, PROBE_SRC)
    cg = MdCG(lib)
    _index_into(cg, src, refindex.Ledger(lib))
    cg.flush()
    wr(p, PROBE_SRC2, bump=5.0)
    _index_into(cg, src, ledger=None)          # 全量重切，水位不动
    cg.flush()
    res = refindex.check_refs(cg, ledger=refindex.Ledger(lib))
    v = _verdict(res)
    check("6②只推节点：ok=True 且 stale/dangling 空（旧水位不得误报漂移）",
          res["ok"] is True and not res["stale"] and not res["dangling"],
          f"ok={res['ok']} stale={sorted(v['ids'])}", cid="B1")
    # 归因面与「红不红」解耦：这里只断言「不一致被记下来了」（ok 由 B1 断），
    # 免得同一次误报把两条断言一起打红、红项表失去「一项一行为」的对应。
    check("6②旧水位与节点不一致仍归因（watermark_behind）",
          v["mm_count"] >= 1
          and all(r["kind_of_gap"] == "watermark_behind" for r in v["mm"]),
          str(v["mm"][:1]), cid="B2")

    # ③篡改节点 ref.hash（源与水位都不动）—— 只有节点自述变了
    lib = _mk(tmp, "ft_lib")
    src = _mk(tmp, "ft_src")
    p = os.path.join(src, "probe_widget.py")
    wr(p, PROBE_SRC)
    cg = MdCG(lib)
    ids = _index_into(cg, src, refindex.Ledger(lib))
    cg.flush()
    nid = sorted(ids)[0]
    _tamper_ref_hash(os.path.join(lib, cg.index["nodes"][nid]["path"]))
    res = refindex.check_refs(cg, ledger=refindex.Ledger(lib))
    v = _verdict(res)
    check("6③篡改节点 ref.hash（源与水位都不动）：必须报 stale",
          res["ok"] is False and any(r["node_id"] == nid for r in res["stale"]),
          f"ok={res['ok']} stale={v['ids']}", cid="C1")
    check("6③同一 node_id 至多一行（去重，不重复报红）", v["dup"] == 0,
          str(v["ids"]), cid="C2")


def guard_collision(tmp):
    """撞 id 现场（D1 状态）：钉现状事实 + 去重 + 归因，不作期望语义断言。

    `node_id` 不含 root ⇒ 两域同 rel path + 同 name 时撞 id、节点被**后写域**覆盖
    （`add_items` 同 id upsert 整条替换）。本组断言这个**现状**（以及归因行可见、
    不重复报红）；键一旦改为含 root，第一条会转红以提示同步迁移——那是迁移触发器，
    不是要实现的期望语义（见 docs/plans/真源索引_通用机制_v0.3.md「id 语义与设计债」）。
    """
    lib = _mk(tmp, "fc_lib")
    domA = _mk(tmp, "fc_domA")
    domB = _mk(tmp, "fc_domB")
    for d in (domA, domB):
        wr(os.path.join(d, "probe_widget.py"), PROBE_SRC)
    cg = MdCG(lib)
    ids_a = _index_into(cg, domA, refindex.Ledger(lib))
    ids_b = _index_into(cg, domB, refindex.Ledger(lib))
    cg.flush()
    nid = sorted(ids_a)[0]
    ref = refindex.ref_of(cg.get(nid))[1] or {}
    check("7①两域同 rel path + 同 name ⇒ 同一 id（现状：id 不含 root）",
          bool(ids_a) and set(ids_a) == set(ids_b), f"A={ids_a} B={ids_b}",
          cid="D1")
    check("7①同一 id 只留一条节点，ref.root 为后写域（现状钉子，非期望语义）",
          len(cg.index["nodes"]) == len(ids_a)
          and refindex._same_root(ref.get("root"), domB),
          f"nodes={len(cg.index['nodes'])} root={ref.get('root')}", cid="D1")
    _tamper_ref_hash(os.path.join(lib, cg.index["nodes"][nid]["path"]))
    res = refindex.check_refs(cg, ledger=refindex.Ledger(lib))
    v = _verdict(res)
    check("7②该现场篡改节点 ref.hash：同一 node_id 至多一行（dup=0）",
          v["dup"] == 0, str(v["ids"]), cid="D2")
    check("7②水位/节点不一致记 ledger_mismatch 归因行（撞 id 不再静默）",
          v["mm_count"] >= 1, str(v["mm_count"]), cid="D2")
    check("7②归因行带两侧 root 且 gap=collision_multi_root（可归因到域）",
          bool(v["mm"]) and all(r.get("watermark_root") and r.get("node_root")
                                and r.get("kind_of_gap") == "collision_multi_root"
                                for r in v["mm"]),
          str(v["mm"][:1]), cid="D2")
    # 该现场再推一步：**两域的源都改掉**（合法漂移，不是篡改）。v1 逐条水位条目各自
    # 探测 ⇒ 同一个 node_id 被反复报（本夹具实测 HEAD 4 行 / dup=2 ⇒ v2 2 行 / dup=0，
    # 两个数是该文件的两个节点各一行）。这一步才真正钉住「去重」，且不依赖篡改。
    wr(os.path.join(domA, "probe_widget.py"), PROBE_SRC2, bump=5.0)
    wr(os.path.join(domB, "probe_widget.py"), PROBE_SRC2, bump=5.0)
    v = _verdict(refindex.check_refs(cg, ledger=refindex.Ledger(lib)))
    check("7③两域源都改：同一 node_id 至多一行（v1 会按水位条目重复报）",
          v["dup"] == 0 and bool(v["ids"]), str(v["ids"]), cid="D3")
    check("7③撞 id 归因行仍在（collision_multi_root，带两侧 root）",
          v["mm_count"] >= 1
          and all(r.get("watermark_root") and r.get("node_root")
                  and r.get("kind_of_gap") == "collision_multi_root"
                  for r in v["mm"]),
          str(v["mm"][:1]), cid="D3")


# ---------------- 12 自愈止血 + 水位保全（H1/H1b/H2/H3/H4/H5/H6 + 写序） ----------------

def guard_heal_bounded(tmp):
    """水位不被写空 / 重建失败不许记成成功 / 同因不重试（直调 refindex|sustain）。

    全部用对称小夹具（每域 1 个源文件、2 个节点），断言的是**行为**而不是文案。
    """
    # ①水位保全（H1）：目录仍在、零文件 ⇒ 空扫不对账，水位不被剪空
    lib = _mk(tmp, "hb1_lib")
    src = _mk(tmp, "hb1_src")
    p = os.path.join(src, "hb1_widget.py")
    wr(p, PROBE_SRC)
    cg = MdCG(lib)
    ids = _index_into(cg, src, refindex.Ledger(lib))
    cg.flush()
    os.remove(p)                              # 目录仍在、零文件
    refindex.index_dir(src, kind="code_ref", ledger=refindex.Ledger(lib))
    s = refindex.Ledger(lib).summary()
    check("12①空扫不对账：水位条目与节点数保住（[C1] 目录仍在零文件）",
          s["files"] == 1 and s["nodes"] == len(ids),
          f"files={s['files']} nodes={s['nodes']} ids={len(ids)}", cid="E1")
    check("12①两面不打架：last_index 如实记 files=0 且 empty_scan=True",
          (s.get("last_index") or {}).get("files") == 0
          and (s.get("last_index") or {}).get("empty_scan") is True,
          str(s.get("last_index"))[:120], cid="E1")

    # ②悬空 root 不重建（H1b）：不调 index_dir ⇒ 水位不被写成空
    lib = _mk(tmp, "hb2_lib")
    src = _mk(tmp, "hb2_src")
    wr(os.path.join(src, "hb2_widget.py"), PROBE_SRC)
    cg = MdCG(lib)
    _index_into(cg, src, refindex.Ledger(lib))
    cg.flush()
    n_files = refindex.Ledger(lib).summary()["files"]
    shutil.rmtree(src)                        # 源大域整个没了
    r = refindex.rebuild(cg, ledger=refindex.Ledger(lib))
    check("12②rebuild 遇悬空 root：不重建、ok=False、roots_missing 如实记",
          r["ok"] is False and len(r["roots_missing"]) == 1 and r["indexed"] == 0
          and any("已不是目录" in e for e in r["errors"]),
          f"ok={r['ok']} missing={r['roots_missing']} err={r['errors'][:1]}", cid="E2")
    check("12②悬空 root 不再把水位写成空（[C3] files 保住 vs 现状 0）",
          refindex.Ledger(lib).summary()["files"] == n_files,
          f"files={refindex.Ledger(lib).summary()['files']} 期望 {n_files}", cid="E2")

    # ③空扫组如实置 ok=False（H2）
    lib = _mk(tmp, "hb3_lib")
    src = _mk(tmp, "hb3_src")
    p = os.path.join(src, "hb3_widget.py")
    wr(p, PROBE_SRC)
    cg = MdCG(lib)
    _index_into(cg, src, refindex.Ledger(lib))
    cg.flush()
    os.remove(p)
    r = refindex.rebuild(cg, ledger=refindex.Ledger(lib))
    check("12③rebuild 空扫组：ok=False + errors + 逐组 empty_scan 如实回报",
          r["ok"] is False and r["errors"] and r["rebuilt"]
          and r["rebuilt"][0]["empty_scan"] is True
          and r["rebuilt"][0]["files"] == 0,
          str(r["rebuilt"])[:140], cid="E3")

    # ④只有悬空 ⇒ heal 不重建（H3）：止血点在「按 code 分派」
    lib = _mk(tmp, "hb4_lib")
    domA = _mk(tmp, "hb4_domA")
    domB = _mk(tmp, "hb4_domB")
    for d, nm in ((domA, "hb4_a.py"), (domB, "hb4_b.py")):
        wr(os.path.join(d, nm), PROBE_SRC)
    cg = MdCG(lib)
    _index_into(cg, domA, refindex.Ledger(lib))
    _index_into(cg, domB, refindex.Ledger(lib))
    cg.flush()
    shutil.rmtree(domB)
    codes = {i["code"] for i in sustain.diagnose(cg)["issues"]}
    acts = [a["code"] for a in sustain.heal(cg)["actions"]]
    check("12④ref_dangling 不再触发重建（fix 字段无调度器消费，改它无效）",
          "ref_dangling" in codes and "rebuild_refs" not in acts,
          f"codes={sorted(codes)} actions={acts}", cid="E4")

    # ⑤重建失败如实记 ok=False（H4）+ ⑥同因不重试（H6）
    lib = _mk(tmp, "hb5_lib")
    domA = _mk(tmp, "hb5_domA")
    domB = _mk(tmp, "hb5_domB")
    for d, nm in ((domA, "hb5_a.py"), (domB, "hb5_b.py")):
        wr(os.path.join(d, nm), PROBE_SRC)
    cg = MdCG(lib)
    _index_into(cg, domA, refindex.Ledger(lib))
    _index_into(cg, domB, refindex.Ledger(lib))
    cg.flush()
    key = (os.path.abspath(lib), "rebuild_refs")
    sustain._HEAL_MEMO.pop(key, None)
    p = os.path.join(domA, "hb5_a.py")
    wr(p, PROBE_SRC2, bump=5.0)               # 一个域漂移
    shutil.rmtree(domB)                       # 另一个域悬空（重建必带 roots_missing）
    h1 = sustain.heal(cg, repeat_guard=True, heal_interval=300.0)
    row = next((a for a in h1["actions"] if a["code"] == "rebuild_refs"), None)
    check("12⑤重建失败不得记成成功：applied=True 且 ok=False，并带结果摘要",
          bool(row) and row["applied"] is True and row["ok"] is False
          and bool((row.get("result") or {}).get("roots_missing")),
          str(row)[:170], cid="E5")
    wr(p, PROBE_SRC, bump=5.0)                # 回到与上次相同的诊断信号
    h2 = sustain.heal(cg, repeat_guard=True, heal_interval=300.0)
    row2 = next((a for a in h2["actions"] if a["code"] == "rebuild_refs"), None)
    check("12⑥同一信号重复失败：拦下并如实记 repeat_failure（不是静默、不重刷）",
          bool(row2) and row2["applied"] is False
          and row2.get("reason") == "repeat_failure"
          and row2.get("streak") == 1 and row2.get("wait_s") == 300.0,
          str(row2)[:170], cid="E6")
    sustain._HEAL_MEMO[key]["ts"] = time.time() - 400     # 模拟退避窗已过
    h3 = sustain.heal(cg, repeat_guard=True, heal_interval=300.0)
    row3 = next((a for a in h3["actions"] if a["code"] == "rebuild_refs"), None)
    check("12⑥退避窗过后放行重试（退避 ≠ 永久静默）",
          bool(row3) and row3["applied"] is True, str(row3)[:170], cid="E6")
    sustain._HEAL_MEMO.clear()

    # ⑦sources 的水位面（H5）：Ledger 没有 stat()，写错被 except 吞成 {}
    st = sources.FileDispatcher(cg)._ledger_stat()
    check("12⑦ingest stat 的水位面不再被 AttributeError 吞成空",
          isinstance(st, dict) and "files" in st and "path" in st,
          str(sorted(st))[:120], cid="E7")

    # ⑧写序（#2）：节点写入失败 ⇒ 水位不得先落盘
    lib = _mk(tmp, "hb6_lib")
    src = _mk(tmp, "hb6_src")
    wr(os.path.join(src, "hb6_widget.py"), PROBE_SRC)
    cg = MdCG(lib)
    orig = refindex.add_items

# 生效条件：任何入参都抛 RuntimeError（把「节点写入失败」注入 op 面），用于验证水位未先落盘；
    def _boom(*_a, **_k):
        raise RuntimeError("夹具：节点写入失败")

    refindex.add_items = _boom
    raised = False
    try:
        index_read(cg, src)
    except RuntimeError:
        raised = True
    finally:
        refindex.add_items = orig
    led = refindex.Ledger(lib)
    check("12⑧节点写入失败时水位不落盘（残留方向=节点新/水位旧，不是反向）",
          raised and not os.path.isfile(led.path),
          f"raised={raised} ledger_exists={os.path.isfile(led.path)}", cid="E8")


# ---------------- 13 口径钉子：id 位置化 + 幂等判据由区间哈希承担（#5） ----------------

#: 口径真源（文档侧）。措辞与实现必须同源——改一边不改另一边即转红。
DOC_PLAN = os.path.join(_BASE, "docs", "plans", "真源索引_通用机制_v0.3.md")
#: 口径块定位：起＝该标题行，止＝下一个**二级**标题（`### ` 不算终止）。
DOC_SEC_HEAD = "### 3.1 "

#: §3.1（归一化后）的 sha1 前 16 位：**判据侧陈化硬失败**——口径一被改写（无论改真源
#: 还是改守卫）就必须同步本行，才谈得上「措辞与实现同源」。归一化＝空白折叠 ⇒ 换行 /
#: 缩进 / 表格对齐**不**误红，只有措辞变化才红。失败信息里打印现算值，照抄即恢复。
DOC_SEC_FP = "08c3e8fc30b1be7c"

#: §3.1 里必须**逐字**出现的口径字面（缺一条 ⇒ 措辞已从实现侧漂开）。
DOC_REQUIRED = (
    "路径-标题寻址",           # id 是位置化寻址（不是内容寻址）
    "sha1(路径::符号名)",       # code_ 的口径公式
    "sha1(路径#标题路径)",      # doc_ 的口径公式
    "不含 root、不含正文",       # 位置化的两个「不含」
    "id 存在即已索引",          # D2：明令禁止的判据（幂等不许看 id）
    "hash + 行位全等",          # 幂等判据的实际承担者
)

#: 行级引用 → 实现符号：(文档里必须出现的引用字面, 文件, 行号, 该行应以什么开头)。
#: 「文档说谁在哪一行」是措辞里最硬的一句——引用漂移（代码增删行）即红，失败信息附
#: 该符号**现址**，照抄回文档与本表即恢复（陈化可自愈到「人只需抄一次」）。
DOC_CITATIONS = (
    ("refindex.py:445", "md_cg/refindex.py", 445, "def _code_ref("),
    ("refindex.py:459", "md_cg/refindex.py", 459, "def _doc_ref("),
    ("refindex.py:503", "md_cg/refindex.py", 503,
     "got = codeindex.region_hash(lines, lineno, end)"),
    ("refindex.py:520", "md_cg/refindex.py", 520, "def read_ref("),
    ("refindex.py:588", "md_cg/refindex.py", 588, "def check_refs("),
    ("refindex.py:784", "md_cg/refindex.py", 784, "def prune_orphans("),
    ("srcindex.py:71", "md_cg/srcindex.py", 71, "def src_id("),
    ("srcindex.py:86", "md_cg/srcindex.py", 86, "def file_hash("),
    ("logref.py:119", "md_cg/logref.py", 119, "def node_state("),
    ("docindex.py:294", "md_cg/docindex.py", 294, "def node_id("),
)


def _doc_block(path: str, head: str) -> str:
    """取文档里 `head` 起、到下一个**二级**标题前的正文块，空白折叠后返回。

    起行不在文档里返回 ""（由调用方判红，不留静默分支）。归一化只折空白——
    重排 / 换行 / 表格对齐不影响指纹，只有**措辞**变化才改指纹。
    """
    try:
        with open(path, encoding="utf-8") as f:
            lines = f.read().replace("\r\n", "\n").split("\n")
    except OSError:
        return ""                     # 文档缺失＝口径真源不可读，交由调用方判红
    start = next((i for i, ln in enumerate(lines) if ln.startswith(head)), None)
    if start is None:
        return ""
    i = start + 1
    while i < len(lines) and not (lines[i].startswith("## ")
                                  and not lines[i].startswith("### ")):
        i += 1
    return re.sub(r"\s+", " ", "\n".join(lines[start:i])).strip()


def guard_id_and_idempotence(tmp):
    """#5 口径钉子：id 位置化（不含 root / 正文 / 行位）、幂等判据由区间哈希 + 行位承担。

    两侧都钉，谁单方面漂开都转红：①**实现侧**——id 用手算 sha1 独立复算（不借实现），
    对 root / 正文哈希 / 行位不敏感；水位与节点 ref 五项全等才是跳过的前提（「id 存在」
    不构成已索引）；「同 id 而内容变」必须判 stale。②**文档侧**——`v0.3` 计划 §3.1 的
    口径字面齐全、整块指纹不陈化、行级引用仍指向所声称的符号。
    """
    from . import codeindex, docindex

    # ---- ①id 口径：位置化，公式可手算复算 ----
    it = {"path": "pkg/probe_widget.py", "name": "probe_fn", "kind": "function",
          "lineno": 4, "end": 6, "hash": "aaaa1111bbbb", "lang": "py",
          "precise": True}
    want_code = "code_" + hashlib.sha1(
        b"pkg/probe_widget.py::probe_fn").hexdigest()[:12]
    check("13①code_ == sha1(路径::符号名)[:12]（手算交叉核验，非复用实现）",
          codeindex.node_id(it) == want_code
          and refindex.node_id_of(it, "code_ref") == want_code,
          f"{codeindex.node_id(it)} vs {want_code}", cid="F1")
    dit = {"path": "docs/probe.md", "heading_path": ["一", "二"], "heading": "二",
           "level": 2, "lineno": 10, "end": 20, "hash": "cccc2222", "dup": 1}
    want_doc = "doc_" + hashlib.sha1(
        "docs/probe.md#一/二".encode("utf-8")).hexdigest()[:12]
    check("13①doc_ == sha1(路径#标题路径)[:12]（手算交叉核验）",
          docindex.node_id(dit) == want_doc
          and refindex.node_id_of(dit, "doc_ref") == want_doc,
          f"{docindex.node_id(dit)} vs {want_doc}", cid="F1")
    check("13②id 不读 root（跨域同 rel path 必然同 id —— D1 的机械根）",
          codeindex.node_id(dict(it, root="/domA")) == want_code
          and codeindex.node_id(dict(it, root="/domB")) == want_code
          and docindex.node_id(dict(dit, root="/domA")) == want_doc,
          cid="F2")
    check("13②id 不读正文哈希与行位（改内容 / 挪行位 id 不变 ⇒ 位置化而非内容寻址）",
          codeindex.node_id(dict(it, hash="deadbeefdead", lineno=99, end=120)) == want_code
          and docindex.node_id(dict(dit, hash="zzzz9999", lineno=1, end=2)) == want_doc,
          cid="F2")

    # ---- ②幂等判据：水位只记「能不能跳过」，判据键 = 节点 ref 的五项 + 源 size/mtime ----
    lib = _mk(tmp, "fx_lib")
    src = _mk(tmp, "fx_src")
    p = os.path.join(src, "probe_widget.py")
    wr(p, PROBE_SRC)
    cg = MdCG(lib)
    ids = _index_into(cg, src, refindex.Ledger(lib))
    cg.flush()
    nid = sorted(ids)[0]
    _k0, ref0 = refindex.ref_of(cg.get(nid))
    ents = [e for e in (refindex.Ledger(lib).load().get("files") or {}).values()
            if (e.get("path") or "").endswith("probe_widget.py")]
    e = ents[0] if ents else {}
    n0 = (e.get("nodes") or [{}])[0]
    check("13③水位键 = 源文件绝对路径且只有一条（跨域不撞名）",
          len(ents) == 1, f"{len(ents)} 条", cid="F3")
    check("13③水位条目记的正是判据要用的五项（root/path/lineno/end/hash）+ 源 size/mtime",
          {"root", "path", "size", "mtime", "kind", "nodes"} <= set(e)
          and {"id", "lineno", "end", "hash"} <= set(n0), sorted(e), cid="F3")
    check("13③稳态：水位与节点 ref 五项全等（跳过的前提真的成立）",
          refindex._same_root(e.get("root"), (ref0 or {}).get("root"))
          and refindex._norm_rel(e.get("path")) == refindex._norm_rel((ref0 or {}).get("path"))
          and n0.get("hash") == (ref0 or {}).get("hash")
          and n0.get("lineno") == (ref0 or {}).get("lineno")
          and n0.get("end") == (ref0 or {}).get("end"),
          f"watermark={n0} ref={ref0}", cid="F3")
    # 逐项：五项全等 + 源未变 ⇒ 跳过；任一项不等 ⇒ 一律进探测（「id 存在」不构成已索引）
    n_rec = {"id": nid, "lineno": n0.get("lineno"), "end": n0.get("end"),
             "hash": n0.get("hash")}
    e_rec = {"root": e.get("root"), "path": e.get("path")}
    rel = refindex._norm_rel(e.get("path"))
    base = refindex._fast_path_verdict(cg, n_rec, e_rec, rel, e.get("root"), True)
    check("13④五项全等 + 源 size/mtime 未变 ⇒ 跳过（probe=None，不读源）",
          base["covered"] is True and base["probe"] is None, str(base), cid="F4")
    holes = []
    for k, v in (("hash", "000000000000"), ("lineno", 999), ("end", 1000)):
        n2 = dict(n_rec)
        n2[k] = v
        if refindex._fast_path_verdict(cg, n2, e_rec, rel, e.get("root"),
                                       True)["probe"] is None:
            holes.append(k)
    if refindex._fast_path_verdict(cg, n_rec, e_rec, "other_widget.py",
                                   e.get("root"), True)["probe"] is None:
        holes.append("path")
    v_root = refindex._fast_path_verdict(cg, n_rec, e_rec, rel,
                                         os.path.join(src, "elsewhere"), True)
    if v_root["probe"] is None:
        holes.append("root")
    check("13④五项任一项不等 ⇒ 一律不跳过（「id 存在」不构成已索引）", not holes,
          f"漏判项={holes}", cid="F4")
    check("13④跨域不一致归因 collision_multi_root 且带两侧 root（不静默、不改判定）",
          (v_root.get("mismatch") or {}).get("kind_of_gap") == "collision_multi_root"
          and bool((v_root.get("mismatch") or {}).get("watermark_root"))
          and bool((v_root.get("mismatch") or {}).get("node_root")),
          str(v_root.get("mismatch")), cid="F4")

    # ---- ③同 id 而内容变：必须判漂移（id 只做身份，不承担幂等） ----
    wr(p, PROBE_SRC2, bump=5.0)               # 行数不变，只有区间哈希变
    res = refindex.check_refs(cg, ledger=refindex.Ledger(lib))
    row = next((r for r in res["stale"] if r["node_id"] == nid), None)
    check("13⑤同 id 而区间哈希变（源改一行）⇒ 必须判 stale，且 hash_expected 取节点 ref",
          res["ok"] is False and row is not None
          and row.get("hash_expected") == (ref0 or {}).get("hash"),
          f"ok={res['ok']} stale={sorted(r['node_id'] for r in res['stale'])}",
          cid="F5")

    # ---- ④文档侧：措辞 / 指纹 / 行级引用都必须与实现同源 ----
    sec = _doc_block(DOC_PLAN, DOC_SEC_HEAD)
    check("13⑥口径真源可读：文档 §3.1 块非空", bool(sec), DOC_PLAN, cid="F6")
    missing = [lit for lit in DOC_REQUIRED if lit not in sec]
    check("13⑥文档 §3.1 逐字含口径字面（id 位置化 + 幂等判据不看 id）", not missing,
          f"缺字面={missing}", cid="F6")
    fp = hashlib.sha1(sec.encode("utf-8")).hexdigest()[:16]
    check("13⑥文档 §3.1 指纹未陈化（措辞一改即红，须同步 DOC_SEC_FP）",
          fp == DOC_SEC_FP, f"现={fp} 判据侧={DOC_SEC_FP}（照抄现算值即恢复）",
          cid="F6")
    doc_text = ""
    try:
        with open(DOC_PLAN, encoding="utf-8") as f:
            doc_text = f.read()
    except OSError:
        pass                              # 缺文档 ⇒ 每条引用都记「未出现」，逐条报红
    bad = []
    for literal, fpath, lineno, claim in DOC_CITATIONS:
        if literal not in doc_text:
            bad.append(f"{literal} 未出现在文档")
            continue
        lines = rd(os.path.join(_BASE, fpath)).replace("\r\n", "\n").split("\n")
        got = lines[lineno - 1] if 0 < lineno <= len(lines) else ""
        # 判据取 strip 后前缀：行内缩进不算「引用漂移」（只钉「这一行是不是这句」）
        if not got.strip().startswith(claim):
            now = next((i for i, ln in enumerate(lines, 1)
                        if ln.strip().startswith(claim)), "?")
            bad.append(f"{fpath}:{lineno} 现为 {got.strip()[:36]!r}"
                       f"（{claim.strip()} 现在 {fpath}:{now}）")
    check("13⑦文档行级引用仍指向所声称的符号（引用漂移即红，失败信息附现址）",
          not bad, "；".join(bad[:3]), cid="F7")


# ---------------- 14 常驻循环止血（heal 在役面） ----------------

def guard_loop_tick_heal(tmp):
    """`SustainLoop._tick_heal`：空转被止住 + 判据未被削弱（不静默、不假装修好）。

    直调 `_tick_heal()`（**不起线程、不打心跳戳**），`d` 显式落到临时目录——
    绝不写 ~/.mdcg。落点取循环自己的账（`heals` / `last_diagnose`）与 heal 的
    返回值，不断言内部实现细节。
    """
    lib = _mk(tmp, "lt_lib")
    domA = _mk(tmp, "lt_domA")
    domB = _mk(tmp, "lt_domB")
    for d, nm in ((domA, "lt_a.py"), (domB, "lt_b.py")):
        wr(os.path.join(d, nm), PROBE_SRC)
    cg = MdCG(lib)
    _index_into(cg, domA, refindex.Ledger(lib))
    _index_into(cg, domB, refindex.Ledger(lib))
    cg.flush()
    sustain._HEAL_MEMO.pop((os.path.abspath(lib), "rebuild_refs"), None)
    pa = os.path.join(domA, "lt_a.py")
    wr(pa, PROBE_SRC2, bump=5.0)              # 一域漂移
    shutil.rmtree(domB)                       # 一域悬空 ⇒ 重建必带 roots_missing
    loop = sustain.SustainLoop(cg, "p28_guard_loop", heal_interval=300.0,
                               auto_heal=True, d=os.path.join(tmp, "lt_sustain"))
    orig = sustain.heal
    seen = {}

    def _spy(cg_, **kw):
        res = orig(cg_, **kw)
        seen["kw"] = kw
        seen["actions"] = res.get("actions")
        return res

    sustain.heal = _spy
    try:
        loop._tick_heal()
    finally:
        sustain.heal = orig
    check("14①常驻循环按 repeat_guard=True + heal_interval 调 heal（空转止在这一面）",
          (seen.get("kw") or {}).get("repeat_guard") is True
          and (seen.get("kw") or {}).get("heal_interval") == 300.0,
          str(sorted((seen.get("kw") or {}))), cid="G1")
    h1 = loop.heals[-1]
    check("14②首轮真跑并如实记没修好：actions 含 rebuild_refs 且 failed 单列该码",
          "rebuild_refs" in h1["actions"] and "rebuild_refs" in h1["failed"],
          str(h1), cid="G2")
    check("14③判据未被削弱：诊断面照旧报出病灶（ref_stale 仍在 last_diagnose）",
          "ref_stale" in ((loop.last_diagnose or {}).get("issues") or []),
          str(loop.last_diagnose), cid="G2")
    # 同信号第二轮：先让信号与上次一致（重建已把索引推到新代 ⇒ 写回旧正文再漂一次）
    wr(pa, PROBE_SRC, bump=5.0)
    sustain.heal = _spy
    try:
        loop._tick_heal()
    finally:
        sustain.heal = orig
    row2 = next((a for a in (seen.get("actions") or [])
                 if a.get("code") == "rebuild_refs"), None)
    check("14④同一信号重复失败 ⇒ 被拦下并如实记 repeat_failure（不是又重跑一次）",
          bool(row2) and row2.get("applied") is False
          and row2.get("reason") == "repeat_failure" and row2.get("streak") == 1,
          str(row2), cid="G3")
    h2 = loop.heals[-1]
    check("14④拦下也照样进账：heals 记该动作 + failed 单列，诊断面仍报病灶（都不静默）",
          "rebuild_refs" in h2["actions"] and "rebuild_refs" in h2["failed"]
          and "ref_stale" in ((loop.last_diagnose or {}).get("issues") or []),
          str(h2), cid="G3")
    sustain._HEAL_MEMO.clear()


# ---------------- 红基线（判别力自证） ----------------

#: 定点变异表：(标签, 现实现锚点, 改回后的旧行为)。
#: **源 = 工作区 md_cg/refindex.py 的文本**（不取 git HEAD：HEAD 在改动提交那一刻就等于
#: 实现本身，判别力静默失效——同款教训见 md_cg/test_logref.py 的 _MUTATIONS 头注）。
#: 锚点必须**恰好命中 1 次**：0 次＝漂移、≥2 次＝歧义，皆 ANCHOR-MISS → fail-closed。
_MUTATIONS = (
    ("快路径探测数据：节点自身 frontmatter ref（现行）→ 水位条目（v1 旧行为）",
     '    out["probe"] = {**ref, "path": ref.get("path") or rel,\n'
     '                    "root": ref.get("root") or src_root}',
     '    out["probe"] = {**n, "path": rel, "root": src_root}'),
)

#: 变异态下**必须**转红的项：恰好命中这个集合（多一项少一项都报红）：
#:   A1  6①只推水位 ⇒ v1 拿水位当探测数据 ⇒ 哈希「匹配」而静默 ok=True（漏报）
#:   B1  6②只推节点 ⇒ v1 拿旧水位当探测数据 ⇒ 旧哈希对不上新源（误报 stale）
#:   C1  6③篡改节点 ref.hash ⇒ v1 根本不看节点自述 ⇒ 静默 ok=True
EXPECTED_RED = ("A1", "B1", "C1")


# 生效条件：锚点命中次数不是恰好 1 次时由 _mutated_verdict 抛出（fail-closed）。
class AnchorMiss(RuntimeError):
    pass


#: 导入时的实现体字节码（红基线模式会把变异体挂回该属性，故不能与属性现值比）
_IMPL_CODEC = refindex._fast_path_verdict.__code__.co_code


def _anchor_selfcheck() -> None:
    """锚点仍在、且 EXPECTED_RED 都是本文件里真实存在的 cid → 静默通过。"""
    _mutated_verdict()                       # 锚点漂移/歧义 → AnchorMiss
    with open(os.path.abspath(__file__), encoding="utf-8") as f:
        src = f.read()
    gone = [i for i in EXPECTED_RED if ('cid="%s"' % i) not in src]
    if gone:
        raise AnchorMiss("EXPECTED_RED 含本文件里不存在的 check id（红项表已陈化）：%s"
                         % "、".join(gone))


def _mutated_verdict():
    """读工作区 `md_cg/refindex.py`（**只读，不落盘**）按 _MUTATIONS 逐处文本替换，
    把变异后的模块体 exec 进真模块 globals 的副本，返回变异后的 _fast_path_verdict。
    锚点漂移/歧义时抛 AnchorMiss。"""
    p = os.path.join(_BASE, "md_cg", "refindex.py")
    with open(p, encoding="utf-8") as f:
        text = f.read()
    for label, anchor, repl in _MUTATIONS:
        n = text.count(anchor)
        if n != 1:
            raise AnchorMiss(
                "ANCHOR-MISS：定点变异锚点漂移/歧义 —— %s 命中 %d 次（应恰好 1 次）"
                "｜锚点首行：%s" % (label, n, anchor.splitlines()[0].strip()))
        text = text.replace(anchor, repl)
    g = dict(vars(refindex))        # __name__ / __package__ 保留 ⇒ 相对 import 照旧解析
    exec(compile(text, "<mutated md_cg/refindex.py>", "exec"), g)
    fn = g["_fast_path_verdict"]
    # 与**导入时**的实现体比（不能比当前属性：红基线模式会把变异体挂回该属性）
    if fn.__code__.co_code == _IMPL_CODEC:
        raise AnchorMiss("ANCHOR-MISS：变异后字节码与实现相同（替换未生效）")
    return fn


def main(argv=None):
    ap = argparse.ArgumentParser(
        description="P28 守卫：ref 增量索引 + 漂移/悬空巡检（R3）")
    ap.add_argument("--head-baseline", action="store_true",
                    help="红基线：对工作区 md_cg/refindex.py 做定点变异（快路径探测"
                         "数据改回水位条目＝v1 旧行为），断言红项集合 == 预期红项")
    args = ap.parse_args(argv)
    # 锚点自证：**两态都查**（绿态也查）——锚点漂移后若只查红基线，绿线会继续绿着
    # 而判别力已死（本守卫的判别力全靠这张表）。漂移即 fail-closed。
    try:
        _anchor_selfcheck()
    except AnchorMiss as exc:
        print("!! %s" % exc)
        print("结果：锚点自证未过（fail-closed）——定点变异表须同步实现")
        return 2
    if args.head_baseline:
        # 变异体注入（只在本进程内，不落盘）
        refindex._fast_path_verdict = _mutated_verdict()
        print("!! 红基线模式：md_cg/refindex.py 经定点变异 —— %s ⇒ 快路径改用水位条目"
              % "；".join(lbl for lbl, _a, _r in _MUTATIONS))

    print("=" * 68)
    print("md 认知图 P28 验收 · ref 增量索引 + 漂移/悬空巡检（R3）")
    print("=" * 68)

    tmp = tempfile.mkdtemp(prefix="mdcg_refcheck_")
    src = os.path.join(tmp, "pkg")
    os.makedirs(src)
    alpha = os.path.join(src, "alpha.py")
    beta = os.path.join(src, "beta.py")
    wr(alpha, ALPHA)
    wr(beta, BETA)

    corpus.reset_root(ROOT)
    cg = MdCG(ROOT)

    try:
        # ============================================ ① 统一 ref 协议 + 注册表
        print("\n【1】统一 ref 协议与提取器注册表")
        check("tokens.ALL_OPS 仍收录 ref / index_code",
              "ref" in tokens.ALL_OPS and "index_code" in tokens.ALL_OPS)
        check("REF_KEYS = (code_ref, doc_ref)",
              refindex.REF_KEYS == ("code_ref", "doc_ref"), str(refindex.REF_KEYS))
        reg = refindex.registry()
        check("注册表覆盖 code_ref / doc_ref",
              "code_ref" in reg and "doc_ref" in reg, str(sorted(reg)))
        check("kind_of_path 按后缀判 kind",
              refindex.kind_of_path("a.py") == "code_ref"
              and refindex.kind_of_path("a.md") == "doc_ref"
              and refindex.kind_of_path("a.txt") == "",
              f"py={refindex.kind_of_path('a.py')} md={refindex.kind_of_path('a.md')}")
        try:
            refindex.extract("x = 1", "foo.xyz")
            raised = False
        except ValueError as exc:
            raised = "无提取器" in str(exc) or "无索引提取器" in str(exc)
        check("无提取器后缀显式报错（不静默）", raised)

        # ============================================ ② 全量索引 + 水位
        print("\n【2】index_code 全量 + _refindex.json 水位")
        out1 = index_read(cg, src)
        check("op=index_code ok", out1.get("ok"), str(out1)[:120])
        check("files == 2（命中后缀）", out1.get("files") == 2, str(out1.get("files")))
        check("indexed > 0 且 error_count == 0",
              out1.get("indexed", 0) > 0 and out1.get("error_count") == 0)
        cg.flush()
        led = refindex.Ledger(ROOT)
        summ = led.summary()
        check("_refindex.json 落盘", summ["exists"], summ["path"])
        check("水位 files == 2", summ["files"] == 2, str(summ["files"]))
        check("水位 nodes == 本轮 indexed",
              summ["nodes"] == out1.get("indexed"), f"{summ['nodes']} == {out1.get('indexed')}")
        n_before = len((cg.index.get("nodes") or {}))
        ids1 = set(out1.get("ids") or [])

        # ============================================ ③ 增量：未变则跳过
        print("\n【3】增量索引：未变文件不重切（修 F）")
        out2 = index_read(cg, src, incremental=True)
        check("incremental 跳过未变文件",
              out2.get("skipped_unchanged") == 2, str(out2.get("skipped_unchanged")))
        check("incremental 下 indexed == 0（没有重复条目）",
              out2.get("indexed") == 0, str(out2.get("indexed")))
        cg.flush()
        check("增量后节点数不变（幂等）",
              len((cg.index.get("nodes") or {})) == n_before,
              f"{len((cg.index.get('nodes') or {}))} == {n_before}")
        out3 = index_read(cg, src)
        check("默认（不传 incremental）仍是全量：不跳过",
              out3.get("skipped_unchanged") == 0, str(out3.get("skipped_unchanged")))
        check("重跑 id 集合稳定", set(out3.get("ids") or []) == ids1,
              f"{len(set(out3.get('ids') or []))} vs {len(ids1)}")

        # ============================================ ④ 回读 + 检索带 ref
        print("\n【4】op=ref 回读 + 检索结果带 ref / ref_kind")
        rr = ref_read(cg, node_id=(out1.get("ids") or [""])[0])
        check("op=ref read ok", rr.get("ok") is True, str(rr)[:120])
        check("ref_kind == code_ref", rr.get("ref_kind") == "code_ref",
              str(rr.get("ref_kind")))
        check("回读带 hash_match（源未动 → True）",
              rr.get("hash_match") is True, str(rr.get("hash_match")))
        read = call_tool(cg, "cg", {"op": "read", "query": "compute_energy", "k": 10})
        hits = [r for r in read.get("results", []) if r.get("ref_kind") == "code_ref"]
        check("检索结果带 ref / ref_kind 字段", bool(hits), f"hits={len(hits)}")
        check("检索的 ref 指回源文件",
              bool(hits) and isinstance(hits[0].get("ref"), dict)
              and hits[0]["ref"].get("path") == "alpha.py",
              str(hits[0].get("ref") if hits else None))

        # ============================================ ⑤ 漂移：stale
        print("\n【5】漂移检测：改源一行 → stale（只读、不抛）")
        wr(alpha, ALPHA_DRIFT, bump=5.0)
        mt_before = {p: os.path.getmtime(p) for p in (alpha, beta)}
        chk = ref_read(cg, action="check")
        mt_after = {p: os.path.getmtime(p) for p in (alpha, beta)}
        check("action=check 返回 ok", isinstance(chk, dict), str(type(chk)))
        check("check 判定 ok=False（有漂移）", chk.get("ok") is False, str(chk.get("ok")))
        check("报出 stale 且指向 alpha.py",
              any((r.get("path") or "").endswith("alpha.py") for r in chk.get("stale", [])),
              str([r.get("path") for r in chk.get("stale", [])]))
        check("巡检只读：源文件 mtime 不变", mt_before == mt_after)
        stale_rr = ref_read(cg, ref={"path": "alpha.py", "lineno": 5, "end": 7,
                                     "hash": "deadbeef", "root": src, "precise": True})
        check("回读陈旧 ref → hash_match=False / stale=True",
              stale_rr.get("hash_match") is False and stale_rr.get("stale") is True,
              str(stale_rr.get("hash_match")))
        index_read(cg, src)                       # 重建：漂移消除
        chk2 = ref_read(cg, action="check")
        check("重跑 index_code 后 stale 消除", chk2.get("ok") is True,
              str([r.get("path") for r in chk2.get("stale", [])]))

        # ============================================ 6 判据分工（#4）
        print("\n【6】判据分工：漂移只由节点 ref 判，水位只判「能不能跳过」")
        guard_verdict_owner(tmp)

        # ============================================ 7 撞 id 现场（D1 现状钉子）
        print("\n【7】撞 id 现场：归因可见 + 不重复报红（现状钉子 / 迁移触发器）")
        guard_collision(tmp)

        # ============================================ 8 悬空：dangling
        print("\n【8】悬空检测：删源文件 → dangling")
        os.remove(beta)
        chk3 = ref_read(cg, action="check")
        check("报出 dangling 且指向 beta.py",
              any((r.get("path") or "").endswith("beta.py")
                  for r in chk3.get("dangling", [])),
              str([r.get("path") for r in chk3.get("dangling", [])]))
        check("dangling 时 ok=False", chk3.get("ok") is False)
        wr(beta, BETA)                            # 恢复源 + 重建
        index_read(cg, src)
        chk4 = ref_read(cg, action="check")
        check("恢复源并重建后 dangling 消除",
              chk4.get("ok") is True and not chk4.get("dangling"),
              str([r.get("path") for r in chk4.get("dangling", [])]))

        # ============================================ 9 截断不静默 + 水位留痕
        print("\n【9】截断显式上报 + 写进水位")
        tr = index_read(cg, src, max_files=1)
        check("max_files=1 → truncated=True", tr.get("truncated") is True)
        check("truncated_reason 指出 max_files",
              "max_files" in (tr.get("truncated_reason") or ""),
              str(tr.get("truncated_reason")))
        stt = ref_read(cg, action="stat")
        check("action=stat 返回水位与 last_index",
              isinstance(stt.get("ledger"), dict)
              and "last_index" in stt["ledger"], str(stt.get("ledger"))[:120])
        check("水位记下 last_index.truncated=True",
              (stt["ledger"].get("last_index") or {}).get("truncated") is True)
        index_read(cg, src)
        check("重跑全量后 last_index.truncated 回 False",
              (ref_read(cg, action="stat")["ledger"].get("last_index") or {})
              .get("truncated") is False)

        # ============================================ 10 接入 sustain.diagnose / heal
        print("\n【10】接入 sustain：diagnose 报 ref_stale，heal 的 rebuild_refs 修复")
        wr(alpha, ALPHA_DRIFT2, bump=5.0)
        diag = call_tool(cg, "cg", {"op": "sustain", "action": "diagnose"})
        codes = {i["code"] for i in diag.get("issues", [])}
        check("diagnose issues 含 ref_stale", "ref_stale" in codes, str(sorted(codes)))
        check("diagnose stats 报 ref_stale / ref_checked",
              diag.get("stats", {}).get("ref_stale", 0) >= 1
              and "ref_checked" in diag.get("stats", {}),
              str(diag.get("stats", {}).get("ref_stale")))
        check("巡检不改源文件（改动仍在）", ALPHA_MARK2 in rd(alpha))
        heal = call_tool(cg, "cg", {"op": "sustain", "action": "heal"})
        check("heal 动作含 rebuild_refs",
              any(a.get("code") == "rebuild_refs" for a in heal.get("actions", [])),
              str([a.get("code") for a in heal.get("actions", [])]))
        diag2 = call_tool(cg, "cg", {"op": "sustain", "action": "diagnose"})
        codes2 = {i["code"] for i in diag2.get("issues", [])}
        check("heal 后 ref_stale 消除", "ref_stale" not in codes2, str(sorted(codes2)))
        check("heal 不修改源文件", ALPHA_MARK2 in rd(alpha))

        # ============================================ 11 派生物不膨胀 + 未知 action
        print("\n【11】_refindex.json 不膨胀 / 未知 action 不静默")
        led2 = refindex.Ledger(ROOT)
        p = led2.path
        size1 = os.path.getsize(p)
        for _ in range(3):
            index_read(cg, src)
        size2 = os.path.getsize(p)
        check("_refindex.json 体积有界（< 20KB）", size2 < 20000, f"{size2}B")
        check("重跑 3 次不膨胀", size2 == size1, f"{size1} -> {size2}")
        check("水位 files 仍 == 2（无幽灵条目）", led2.summary()["files"] == 2,
              str(led2.summary()["files"]))
        try:
            r = ref_read(cg, action="nope")
            silent = (isinstance(r, dict) and r.get("ok") is True)
        except Exception:                          # noqa: BLE001
            silent = False
        check("未知 action 不静默成功", silent is False)

        # ============================================ 12 自愈止血 + 水位保全
        print("\n【12】自愈止血与水位保全（水位不被写空 / 失败不记成成功 / 同因不重试）")
        guard_heal_bounded(tmp)

        # ============================================ 13 口径钉子（#5）
        print("\n【13】口径钉子：id 位置化 + 幂等判据由区间哈希承担（文档↔实现同源）")
        guard_id_and_idempotence(tmp)

        # ============================================ 14 常驻循环止血
        print("\n【14】常驻循环止血（repeat_guard / 不静默 / 不假装修好）")
        guard_loop_tick_heal(tmp)

    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    print("\n" + "=" * 68)
    print(f"通过 {PASS} / 失败 {FAIL}")
    if FAILS:
        print("失败项：\n  - " + "\n  - ".join(FAILS))
    print("=" * 68)
    if args.head_baseline:
        # 短码集合比对：变异后**恰好**命中预期红项（多一项少一项都报红）。无 cid 的
        # 失败在 check 里记了哨兵 "?<name>"，故「波及到没登记的断言」也在此报红。
        got, exp = sorted(set(RED)), sorted(EXPECTED_RED)
        if got == exp:
            print("红基线符合预期：变异后恰好命中 %d 项 —— %s"
                  % (len(exp), "、".join(exp)))
            return 0
        print("红基线与预期不符（fail-closed）——预期红项：%s；实得红项：%s"
              % ("、".join(exp) or "（无）", "、".join(got) or "（无）"))
        return 1
    return 1 if FAIL else 0


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.exit(main())
