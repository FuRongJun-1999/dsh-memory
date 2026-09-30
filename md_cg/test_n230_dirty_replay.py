# -*- coding: utf-8 -*-
"""N230 `_dirty` 重放遮蔽守卫（P0-3：新记录必须能盖住旧记录，旧不得盖新）。

缺陷（材料自编 N226，`docs/eval/缺陷挖掘_自主迭代_v25.md:132/:178` 记为**留档未修**）：

    站点 `md_cg/mdcg.py` 的 `_maybe_reload_index`（改动前 :1353-1357）——
    `for nid, e in self._dirty.items(): … idx["nodes"][nid] = e` **无条件**把本实例
    未 flush 的 `_dirty` 条目盖回重载后的索引上，没有任何时序/代际比较。

**探针实跑复现（2026-10-01，独立 tempfile 沙箱）**：

    ① A = MdCG(R, autoflush=1000)；A.add("x_node", 正文=OLD) ⇒ A._dirty 含 x_node（未 flush）
    ② B = MdCG(R, autoflush=1)；B.add("x_node", 正文=NEW)；B.close() ⇒ 盘面与快照都是 NEW
    ③ A._maybe_reload_index() 返回 **True**（确实重载了），但重载后
       A.index["nodes"]["x_node"]["content_hash"] **仍是 OLD**；新建读者实例 C 读到 NEW
       ⇒ 索引与盘面撕裂（检索面按旧值给候选/桶/指纹）

**修法（本轮）**：给 `_dirty` 引入「**落盘逐字见证**」——标脏时记下节点文件的
`(st_mtime_ns, st_size)`；重放前再 stat 一次，失配 ⇒ 本实例这条已被盘面更新盖过
⇒ **跳过重放**（放行盘面）。证不出陈旧（无 path / stat 失败 / 未挂 root）时照旧
重放——「本实例未落盘写入不因重载从检索面消失」这条既有不变量一并保留。
tombstone（`None`）语义**一字不改**（`_unstage` 立即 flush，不跨重载存活）。

断言分组：

  G0 前置——站点在位：`_dirty_entry_superseded` / `_note_witness` 各一处；`_dirty.root` 已挂。
  G1 **红基线可出示**（探针三步复现）——旧记录**不得**盖住盘面新记录：A 重载后
     必须收敛到 NEW（= 新建读者实例 C 的读数），且 `_dirty_replay_superseded ≥ 1`。
  G2 不变量保持——他进程只动**别的**节点时，本实例未 flush 的写入必须仍在检索面
     上（`_dirty_replay_superseded == 0`，该条目仍在 index 且哈希不变）。
  G3 tombstone 语义一字不改——`_dirty[nid]=None` 在重载时仍 pop 掉该条目。
  G4 见证判据的判别力（正/负对照）——`_dirty_entry_superseded` 的四条边界逐一断言。
  G5 单点结构（静态）——`for nid, e in self._dirty.items():` 的重放体内**必须**
     经过 `_dirty_entry_superseded`（副本回归/裸赋值回归即红）。

运行：python -X utf8 -m md_cg.test_n230_dirty_replay
      python -X utf8 -m md_cg.test_n230_dirty_replay --head-baseline  # 红基线自证
      python -X utf8 -m md_cg.test_n230_dirty_replay --mutate         # 定点变异自证
      python -X utf8 -m md_cg.test_n230_dirty_replay --mutate --list

退出码（fail-closed）：0 = 全绿；1 = 有断言失败 / 变异未按预期转红；
2 = ANCHOR-MISS（变异锚点在当前源码里找不到——实现改了却没同步本表）。

**基线纪律**：`--head-baseline` 把 `_dirty_entry_superseded` 换回「恒 False」
（= 改动前的无条件重放），G1 必须转红；若不红，说明 G1 没有判别力。
"""
from __future__ import annotations

import contextlib
import io
import os
import shutil
import sys
import tempfile
import types

from .mdcg import MdCG

_PASS = []
_FAIL = []
_SKIP = []
_SRC = {}
_TMP = tempfile.mkdtemp(prefix="mdcg_n230_")
_GEN = [0]
_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

BODY = "# 功能名：%s\n# 生效条件：全时窗\n# 子功能：s\n# 执行：%s\n" \
       "# 验证方式：test\n# 不适用条件：无\n"


def ok(cond, msg, extra=""):
    (_PASS if cond else _FAIL).append(msg)
    print(("  PASS " if cond else "  FAIL ") + msg
          + (("  ← " + str(extra)) if (extra and not cond) else ""))


def _rel_text(rel: str) -> str:
    if rel in _SRC:
        return _SRC[rel]
    with open(os.path.join(_REPO, rel), encoding="utf-8") as f:
        return f.read()


def _sandbox(name: str) -> str:
    _GEN[0] += 1
    d = os.path.join(_TMP, "gen%d_%s" % (_GEN[0], name))
    os.makedirs(d, exist_ok=True)
    return d


def _disk_body(root: str, nid: str) -> str:
    p = os.path.join(root, "knowledge", "orphan", nid + ".md")
    return open(p, encoding="utf-8").read()


# ---------------------------------------------------------------- G0
def g0():
    print("== G0 站点在位（前置）==")
    src = _rel_text("md_cg/mdcg.py")
    ok(src.count("def _dirty_entry_superseded") == 1,
       "G0a mdcg.py 内 `_dirty_entry_superseded` 恰一处定义")
    ok(src.count("def _note_witness") == 1,
       "G0b mdcg.py 内 `_note_witness` 恰一处定义")
    ok("self._dirty.root = self.root" in src,
       "G0c MdCG.__init__ 把数据根交给脏集（见证要靠它拼绝对路径）")
    r = _sandbox("g0")
    cg = MdCG(r, autoflush=1000)
    ok(cg._dirty.root == cg.root and os.path.isabs(cg._dirty.root),
       "G0d 实例构造后 _dirty.root = 数据根", cg._dirty.root)
    ok(cg._dirty_replay_superseded == 0,
       "G0e 读数 _dirty_replay_superseded 初始为 0")
    cg.close()


# ---------------------------------------------------------------- G1
def _probe_repro():
    """探针三步复现（返回值供 G1 逐条断言）。"""
    r = _sandbox("g1")
    a = MdCG(r, autoflush=1000)
    a.add("x_node", BODY % ("x", "OLD"), layer="knowledge",
          verification_basis="test")
    witness = dict(a._dirty.staged_stat)
    b = MdCG(r, autoflush=1)
    b.add("x_node", BODY % ("x", "NEW"), layer="knowledge",
          verification_basis="test")
    b.close()                                   # 他进程写出新盘面 + 新快照
    reloaded = a._maybe_reload_index()
    c = MdCG(r, autoflush=1000)                 # 新建读者实例（只读盘面）
    out = {"root": r, "a": a, "c": c, "reloaded": reloaded,
           "a_hash": (a.index["nodes"].get("x_node") or {}).get("content_hash"),
           "c_hash": (c.index["nodes"].get("x_node") or {}).get("content_hash"),
           "superseded": a._dirty_replay_superseded,
           "witness": witness, "dirty": list(a._dirty),
           "disk": _disk_body(r, "x_node")}
    return out


def g1():
    print("== G1 红基线可出示：旧记录不得盖住盘面新记录（探针复现）==")
    R = _probe_repro()
    ok(R["witness"].get("x_node") is not None,
       "G1 前置：A 标脏时记下了逐字见证 (mtime_ns, size)", R["witness"])
    ok(R["reloaded"] is True,
       "G1a 前置：重载确已发生（_maybe_reload_index() == True）", R["reloaded"])
    ok("执行：NEW" in R["disk"],
       "G1b 前置：盘面真值是 NEW", R["disk"].splitlines()[3])
    ok(R["c_hash"] is not None and R["a_hash"] == R["c_hash"],
       "G1c **新盖旧**：A 重载后条目 == 新建读者实例 C 的条目（收敛到盘面）",
       {"A": R["a_hash"], "C": R["c_hash"]})
    ok(R["superseded"] >= 1,
       "G1d 可判读数：至少 1 条被判「已被盘面更新盖过」而跳过重放",
       R["superseded"])
    ok(R["a"]._dirty.get("x_node") is not None,
       "G1e 该条仍在 _dirty（本实例确实还没 flush——不是靠 flush 凑的绿）",
       list(R["a"]._dirty))
    R["a"].close(); R["c"].close()


# ---------------------------------------------------------------- G2
def g2():
    print("== G2 不变量保持：他进程只动别的节点时，未落盘写入不消失 ==")
    r = _sandbox("g2")
    a = MdCG(r, autoflush=1000)
    a.add("y_node", BODY % ("y", "MINE"), layer="knowledge",
          verification_basis="test")
    a_hash = a.index["nodes"]["y_node"]["content_hash"]
    b = MdCG(r, autoflush=1)
    b.add("z_node", BODY % ("z", "OTHER"), layer="knowledge",
          verification_basis="test")
    b.close()
    reloaded = a._maybe_reload_index()
    ok(reloaded is True, "G2 前置：重载确已发生（他进程改了签名）", reloaded)
    ok(a._dirty_replay_superseded == 0,
       "G2a y_node 未被判陈旧（盘面上没人动它）——见证失配才是陈旧",
       a._dirty_replay_superseded)
    e = a.index["nodes"].get("y_node")
    ok(e is not None and e.get("content_hash") == a_hash,
       "G2b **不变量保持**：本实例未 flush 的 y_node 仍在检索面上且哈希不变",
       {"present": e is not None})
    ok(a.index["nodes"].get("z_node") is not None,
       "G2c 他进程的 z_node 也可见（重载不该只保一边）")
    a.close(); b.close()


# ---------------------------------------------------------------- G3
def g3():
    print("== G3 tombstone 语义一字不改 ==")
    r = _sandbox("g3")
    c = MdCG(r, autoflush=1000)
    c.add("tomb_node", BODY % ("t", "X"), layer="knowledge",
          verification_basis="test")
    c.flush()                              # 入日志；_dirty 清空
    ok("tomb_node" in c.index["nodes"], "G3 前置：节点已在索引里")
    c.index["nodes"].pop("tomb_node", None)
    c._dirty["tomb_node"] = None           # 不经 _unstage（那条路立即 flush）
    ok(c._dirty.get("tomb_node") is None and "tomb_node" in c._dirty,
       "G3a 前置：_dirty 里有该 nid 的 tombstone（值 None）")
    c._index_sig = None                    # 强制签名失配 → 下次读面必然重载
    ok(c._maybe_reload_index() is True, "G3b 前置：已重载")
    ok("tomb_node" not in c.index["nodes"],
       "G3c tombstone 仍被重放 pop 掉（本修复不碰 tombstone 语义）")
    c.close()


# ---------------------------------------------------------------- G4
def g4():
    print("== G4 见证判据的判别力（正/负对照）==")
    r = _sandbox("g4")
    c = MdCG(r, autoflush=1000)
    c.add("w_node", BODY % ("w", "V1"), layer="knowledge",
          verification_basis="test")
    ok(c._dirty_entry_superseded("w_node") is False,
       "G4a 负对照：标脏后盘面未动 → 不判陈旧（未落盘写入照旧重放）")
    import time as _t
    _t.sleep(0.01)
    with open(os.path.join(r, c._dirty["w_node"]["path"]), "w",
              encoding="utf-8", newline="\n") as f:
        f.write(BODY % ("w", "V2"))
    ok(c._dirty_entry_superseded("w_node") is True,
       "G4b 正对照：盘面被改写 → 判陈旧（旧不得盖新）")
    os.remove(os.path.join(r, c._dirty["w_node"]["path"]))
    ok(c._dirty_entry_superseded("w_node") is True,
       "G4c 正对照：文件被删掉（标脏时在）→ 判陈旧")
    c._dirty.staged_stat.pop("w_node", None)
    ok(c._dirty_entry_superseded("w_node") is False,
       "G4d 无见证（证不出陈旧）→ 不判陈旧——不变量优先于覆盖面")
    c._dirty.staged_stat["nopath"] = (1, 1)
    c._dirty["nopath"] = {"layer": "knowledge"}       # 无 path 的条目
    ok(c._dirty_entry_superseded("nopath") is False,
       "G4e 条目无 path → 不判陈旧（无见证可查）")
    ok(c._dirty.root == r and c._dirty.staged_stat.get("w_node") is None,
       "G4f 移除文件的那次 stat 失败**不登记**见证（staged_stat 无该键）")
    c.close()


# ---------------------------------------------------------------- G5
def g5():
    print("== G5 单点结构（静态：重放体必须过判据）==")
    src = _rel_text("md_cg/mdcg.py")
    i = src.index("for nid, e in self._dirty.items():")
    body = src[i:i + 900]
    ok("self._dirty_entry_superseded(nid)" in body,
       "G5 重放循环体内经过 `_dirty_entry_superseded`（副本回归即红）")
    ok("superseded += 1" in body and "continue" in body,
       "G5a 判为陈旧即 `continue`（跳过重放，不是只记账）")
    # 可执行行里不得再有无条件覆盖的裸赋值形态
    code = "\n".join(l for l in body.splitlines()
                     if not l.strip().startswith("#"))
    ok(code.count('idx["nodes"][nid] = e') == 1,
       "G5b 重放体里 `idx[\"nodes\"][nid] = e` 恰一处（在判据之后）")
    ok("self._dirty_replay_superseded = superseded" in src,
       "G5c 跳过条数落在可判读数 `_dirty_replay_superseded` 上")


_GROUPS = (g0, g1, g2, g3, g4, g5)


def _run_groups() -> int:
    _PASS.clear()
    _FAIL.clear()
    for g in _GROUPS:
        try:
            g()
        except Exception as exc:                       # noqa: BLE001
            ok(False, "断言组 %s 抛异常：%s" % (g.__name__, exc))
            import traceback
            print(traceback.format_exc()[-900:])
    return len(_FAIL)


# ---------------------------------------------------------------- 变异表
# 锚点 = (名字, rel, old, new)。每次变异必须让套件**转红**：
#   M1 重放体恢复无条件覆盖（= 改动前形态）→ G1c/G1d/G5 红
#   M2 判据恒 False（见证照记但不采信）→ G1c/G1d 红
#   M3 见证完全不登记 → 判据永远拿不到见证 ⇒ 同 M2
_MUTATIONS = (
    ("重放体恢复无条件覆盖（改动前形态）", "md_cg/mdcg.py",
     "            if self._dirty_entry_superseded(nid):\n"
     "                superseded += 1\n                continue",
     "            if False:\n                superseded += 1\n                continue"),
    ("判据恒 False（见证不采信）", "md_cg/mdcg.py",
     "        return (cur.st_mtime_ns, cur.st_size) != st",
     "        return False"),
    ("见证完全不登记", "md_cg/mdcg.py",
     "        self.staged_stat[k] = (st.st_mtime_ns, st.st_size)",
     "        self.staged_stat.pop(k, None)"),
)


def _exec_module(name: str, rel: str, text: str):
    ns = {"__name__": name, "__package__": "md_cg",
          "__file__": os.path.join(_REPO, rel)}
    exec(compile(text, rel, "exec"), ns)               # noqa: S102 —— 基线自证用
    m = types.ModuleType(name)
    m.__dict__.update(ns)
    return m


def _mutate_mode(list_only: bool = False) -> int:
    print("!! 定点变异自证：逐条把判据改回「改动前/失效」形态，套件必须转红\n")
    if list_only:
        for name, rel, _o, _n in _MUTATIONS:
            print("  %-34s [%s]" % (name, rel))
        return 0
    anchor_miss, bad = [], []
    with contextlib.redirect_stdout(io.StringIO()):
        clean = _run_groups()
    print("  未变异基线：失败=%d（必须为 0）" % clean)
    if clean:
        bad.append("未变异基线即失败")

    for name, rel, old, new in _MUTATIONS:
        src = _rel_text(rel)
        if old not in src:
            print("  ANCHOR-MISS %s —— 锚点在 %s 源码里找不到（实现改了却没同步"
                  "本表）" % (name, rel))
            anchor_miss.append(name)
            continue
        mut_src = src.replace(old, new, 1)
        _SRC[rel] = mut_src
        try:
            mut = _exec_module("md_cg._n230_mut", rel, mut_src)
            globals()["MdCG"] = mut.MdCG
            with contextlib.redirect_stdout(buf := io.StringIO()):
                reds = _run_groups()
            detail = buf.getvalue()
        finally:
            globals()["MdCG"] = _REAL_MdCG
            _SRC.pop(rel, None)
        red_lines = [l for l in detail.splitlines()
                     if l.strip().startswith("FAIL ")]
        verdict = "红" if reds else "**仍全绿 = 该判据空转**"
        print("  %s %-34s 红项=%d  %s"
              % ("OK    " if reds else "MISS  ", name, reds, verdict))
        for l in red_lines[:5]:
            print("        " + l.strip()[5:])
        if not reds:
            bad.append(name)

    if anchor_miss:
        print("\nANCHOR-MISS：%s" % "、".join(anchor_miss))
        print("退出码 2（fail-closed）：变异表锚点漂移即判失败，不得静默跳过")
        return 2
    print("\n定点变异自证：%s"
          % ("PASS（每处判据都被打红）" if not bad else "FAIL —— " + "、".join(bad)))
    return 0 if not bad else 1


_REAL_MdCG = MdCG


def main() -> int:
    try:
        if "--mutate" in sys.argv:
            return _mutate_mode("--list" in sys.argv)
        if "--head-baseline" in sys.argv:
            print("!! 红基线模式：_dirty_entry_superseded 换回「恒 False」"
                  "（= 改动前的无条件重放），G1 应当转红\n")
            MdCG._dirty_entry_superseded = lambda self, nid: False
            n = _run_groups()
            print("\n== 红基线判定：应有失败 ==")
            print("红基线失败数 = %d（>0 才算断言有判别力）" % n)
            for f in _FAIL:
                print("   红:", f)
            return 0 if n else 1
        n = _run_groups()
        print("\nN230 `_dirty` 重放遮蔽守卫：%d 通过，%d 失败，%d 跳过"
              % (len(_PASS), n, len(_SKIP)))
        return 0 if not n else 1
    finally:
        shutil.rmtree(_TMP, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
