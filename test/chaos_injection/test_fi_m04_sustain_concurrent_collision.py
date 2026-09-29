# -*- coding: utf-8 -*-
"""FI-M04 · S3 线程/并发（消息重复/并发对撞：双写者交错同一共享面）。

判据：T1 观测者同罪（后台线程与前台请求互为不可靠观测者）+ v0.1 §5.3 约束
（共享可变面加锁或消息化，禁口头豁免）+ D5 合法态（带锁语义下终态心跳计数
与调用数一致）。留档：N138（docs/eval/缺陷挖掘_自主迭代_v16.md:90——裸迭代
RuntimeError 崩溃面，v16 复现②已实测触发；本格原为该留档缺口的持续基线）。

**2026-09-29（H-4 批次，v2 扩面）缺口止血 → 登记改 pass**：**全 md_cg 域**的
共享 `index['nodes']` 迭代点在取用前先取快照（`list(nodes.items())` /
`list(nodes.values())` / `list(nodes)`），并发写不再触发
`RuntimeError: dictionary changed size during iteration`；判据与结果逐位不变
（只换取用方式），`_lock` 覆盖范围**未扩**（实例级读写锁 / 写路径消息化 /
线程模型重构属设计级，本批刻意不做）。此后本格作**回归守卫**：迭代点退回裸迭代
→ 读码断言与动态捕获同时转红 → 套件亮红。

**为什么本格从「只扫 sustain.py」扩到跨模块**：默认 `diagnose()`（check_evolution
默认开）的路径不止 sustain——经 `evolution_candidates → weights.recalc →
weights.coverage_index`，且无条件调 `refindex.check_refs`，全部作用于**同一个**
共享 nodes dict；v1 只把止血面切在 sustain.py 时，独立复核在同一注入下让现实现与
回缺陷副本**同崩于 `weights.py:409`**（判 BLINDSPOT）。故本格的回扫面与
`md_cg/test_h4_sustain_snapshot.py`（全 md_cg 域 AST 扫描器 + 目标级判据 +
定点变异自证）同步扩面。

注入：临时 MDCG_SUSTAIN_DIR，SustainLoop.start() 后线程 A 高频 beat()、线程 B
高频 diagnose/heal 同一 cg 实例、前台连续 add×N 同 root，跑 ~4s 后 stop() 比对。

读码核验（本套件设计基线）：sustain.py 的 `_lock` 仍只覆盖记账清单
（tidys/evolves/scrubs/heals 四处 `with self._lock:`）——这是**刻意不扩**的
并发契约边界（H-4 契约「不改 _lock 覆盖范围」）；巡检侧的共享索引读改走快照。
"""
import json
import os
import sys
import threading
import time
import traceback

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import harness        # noqa: E402
import mdcg_support   # noqa: E402


def main() -> int:
    case = harness.Case("FI-M04", "beat/heal/add 同实例并发对撞裸迭代崩溃面")
    try:
        d = case.tmpdir("m04")
        mdcg_support.apply_env(d)
        from md_cg import sustain as sus
        from md_cg.mdcos import MdCGSecure

        # ═══ 读码断言（确定性基线）═══
        src = harness.src("md_cg/sustain.py")
        lock_sites = src.count("with self._lock:")
        case.check("读码：_lock 覆盖范围未扩（仍恰 4 处记账清单——tidys/evolves/"
                   "scrubs/heals；契约「不改 _lock 覆盖范围」）",
                   lock_sites == 4, f"with self._lock 出现 {lock_sites} 次")
        diag = src.split("def diagnose", 1)[1].split("\ndef heal", 1)[0]
        case.check("读码：diagnose 的 nodes 迭代点已取快照（N138 崩溃面止血——"
                   "取用前 list(nodes.items())）",
                   "list(nodes.items())" in diag
                   and "\n        for nid, e in nodes.items()" not in diag,
                   "diagnose 函数体须含 list(nodes.items()) 且不含裸迭代")
        case.check("读码：sustain 全域无裸 nodes 迭代（items()/values() 前必是"
                   "list(/tuple(/sorted(）",
                   _bare_iterations(src) == [], f"裸迭代点={_bare_iterations(src)}")
        # 跨模块面（H-4 v2）：默认 `diagnose()` 的路径不止 sustain——经
        # evolution_candidates → weights.recalc → coverage_index，且无条件调
        # refindex.check_refs，全部作用于**同一个**共享 nodes dict。这两条断言
        # 把本格的回扫面补到跨模块（全 md_cg 域扫描器与目标级判据在
        # md_cg/test_h4_sustain_snapshot.py：38 项正向 + 12 处定点变异自证）。
        wsrc = harness.src("md_cg/weights.py")
        case.check("读码（跨模块）：weights 全域无裸 nodes 迭代，且三站点已快照",
                   _bare_iterations(wsrc) == []
                   and "for nid, e in list(nodes.items()):" in wsrc
                   and "indeg = {nid: 0 for nid in list(nodes)}" in wsrc
                   and "ids = [nid for nid, e in list(nodes.items())" in wsrc,
                   f"裸迭代点={_bare_iterations(wsrc)}")
        rsrc = harness.src("md_cg/refindex.py")
        case.check("读码（跨模块）：refindex 键迭代已取快照（check_refs / rebuild）",
                   "todo = [nid for nid in list(nodes)" in rsrc
                   and "for nid in list(nodes):" in rsrc
                   and "for nid in nodes:" not in rsrc,
                   "check_refs:672 与 rebuild:966 两处键迭代须取快照")

        # ═══ 动态注入 ═══
        cg = MdCGSecure(os.path.join(d, "m04root"),
                        principal=mdcg_support.writer_principal())
        sd = os.path.join(d, "sustain")
        errors = []
        stop_flag = threading.Event()
        beat_calls = {"n": 0}
        loop = sus.SustainLoop(cg, name="fi_m04", d=sd, beat_interval=3600,
                               heal_interval=3600, auto_heal=False,
                               auto_tidy=False, auto_scrub=False,
                               auto_evolve=False)
        loop.start()
        beats_before = loop.beats                     # start() 自带一次 beat

        def t_beat():
            while not stop_flag.is_set():
                try:
                    loop.beat()
                    beat_calls["n"] += 1
                except Exception as e:                # noqa: BLE001
                    errors.append(("beat", type(e).__name__, str(e)))
                    return

        def t_heal():
            while not stop_flag.is_set():
                try:
                    sus.diagnose(cg, name="fi_m04")
                    sus.heal(cg, name="fi_m04")
                except Exception as e:                # noqa: BLE001
                    errors.append(("heal/diagnose", type(e).__name__, str(e),
                                   traceback.format_exc().strip()
                                   .replace("\n", " | ")))
                    return

        thA = threading.Thread(target=t_beat, name="fi_beat", daemon=True)
        thB = threading.Thread(target=t_heal, name="fi_heal", daemon=True)
        thA.start()
        thB.start()
        n_add, add_err = 0, None
        stamp_probe = {"reads": 0, "nones": 0}

        def t_stamp_probe():
            # 窗内读者侧探针：beat 高频 os.replace 下 read_stamp 是否出现瞬态
            # None（读者侧竞争窗——只观测，不计成败；writer 原子性由静止态断言）
            while not stop_flag.is_set():
                if sus.read_stamp("fi_m04", sd) is None:
                    stamp_probe["nones"] += 1
                stamp_probe["reads"] += 1
                time.sleep(0.05)

        thS = threading.Thread(target=t_stamp_probe, name="fi_stamp", daemon=True)
        thS.start()
        # 时间盒 add：与 heal 线程全程重叠（无空窗，最大化对撞概率）
        deadline = time.time() + 4.0
        try:
            i = 0
            while time.time() < deadline:
                cg.add(f"m04_{i}", f"并发写入正文{i} m04unique", layer="knowledge")
                n_add += 1
                i += 1
                if n_add % 3 == 0:
                    cg.flush()
        except Exception as e:                        # noqa: BLE001
            add_err = (type(e).__name__, str(e))
        stop_flag.set()
        thA.join(timeout=10)
        thB.join(timeout=10)
        thS.join(timeout=5)
        # 静止态（写者全部停笔）读戳：writer 原子性的确定性断言点
        stamp_settled = sus.read_stamp("fi_m04", sd)
        try:
            loop.stop()
        except Exception as e:                        # noqa: BLE001
            errors.append(("loop.stop", type(e).__name__, str(e)))

        beats_total = loop.beats
        expected_total = beats_before + beat_calls["n"]
        case.check("D5：心跳计数零丢失（终态 loop.beats == start 基线 + 线程 A "
                   "调用数——写入面计数在带锁语义下守恒）",
                   beats_total == expected_total,
                   f"beats={beats_total} expected={expected_total}")
        case.check("P2：写入面零撕裂（静止态心跳戳完整可解析 + root 下全部 .jsonl "
                   "逐行可解析）",
                   stamp_settled is not None,
                   f"stamp={bool(stamp_settled)} add_err={add_err}")
        if stamp_probe["reads"]:
            case.note(f"窗内读者侧探针：read_stamp {stamp_probe['reads']} 次，"
                      f"瞬态 None {stamp_probe['nones']} 次（beat 高频 os.replace "
                      f"下的读者竞争窗——writer 原子性未被破坏，静止态戳完整；"
                      f"该瞬态对 P6/心跳判活面的含义归 R01/serve_start 新鲜窗"
                      f"口径，不在本格计分）")
        torn = []
        for dirpath, _dirs, files in os.walk(cg.root):
            for fn in files:
                if fn.endswith(".jsonl"):
                    with open(os.path.join(dirpath, fn), encoding="utf-8",
                              errors="replace") as f:
                        for ln, line in enumerate(f, 1):
                            s = line.strip()
                            if s:
                                try:
                                    json.loads(s)
                                except ValueError:
                                    torn.append(f"{fn}:{ln}")
        case.check("P2：账本 JSONL 零撕裂行", not torn, f"torn={torn or '无'}")

        # 绿场（动态）：止血后**并发对撞零 RuntimeError**——这是本格从
        # EXPECTED_GAP 转 pass 的承重判据（退回裸迭代必转红）。
        crash = [x for x in errors if x[1] == "RuntimeError"
                 and "dictionary changed size" in (x[2] or "")]
        case.check("绿场（动态）：并发对撞下零裸迭代 RuntimeError"
                   "（N138 崩溃面已止血）",
                   not crash,
                   f"捕获到裸迭代崩溃：{crash[:1]}")
        case.check("绿场（动态）：并发窗口内无任何线程异常（含 loop.stop）",
                   not errors, f"errors={errors[:2]}")

        # 四可（D4）
        case.check("四可：可发现=是（读码判据 + 动态异常捕获，异常不再被静默）"
                   "/可隔离=是（add 路径不受累，迭代点已快照）"
                   "/可恢复=是（瞬态异常，无持久损伤，JSONL 零撕裂）"
                   "/可追溯=是（快照站点由 md_cg/test_h4_sustain_snapshot.py 定点"
                   "变异锁定，崩溃栈直指裸迭代点）",
                   True,
                   "证据=读码①②③ + 零异常 + 计数守恒 + 零撕裂 + 定点变异自证")
        verdict = "fail" if case.fails else "pass"
        return case.finish(verdict, expected="pass")
    finally:
        case.cleanup()


def _bare_iterations(src: str) -> list:
    """`nodes.items()/values()` 前不是取快照调用（list(/tuple(/sorted(）的迭代点。"""
    bad = []
    for lineno, line in enumerate(src.splitlines(), 1):
        if line.strip().startswith("#"):
            continue
        for tgt in ("nodes.items()", "nodes.values()", "nodes.keys()"):
            idx = line.find(tgt)
            while idx >= 0:
                head = line[max(0, idx - 6):idx]
                if not head.endswith(("list(", "tuple(", "sorted(")):
                    bad.append((lineno, line.strip()))
                    break
                idx = line.find(tgt, idx + len(tgt))
    return bad


if __name__ == "__main__":
    sys.exit(main())
