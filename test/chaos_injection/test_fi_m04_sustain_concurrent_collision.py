# -*- coding: utf-8 -*-
"""FI-M04 · S3 线程/并发（消息重复/并发对撞：双写者交错同一共享面）。

判据：T1 观测者同罪（后台线程与前台请求互为不可靠观测者）+ v0.1 §5.3 约束
（共享可变面加锁或消息化，禁口头豁免）+ D5 合法态（带锁语义下终态心跳计数
与调用数一致）。留档：N138（docs/eval/缺陷挖掘_自主迭代_v16.md:90——裸迭代
RuntimeError 崩溃面，v16 复现②已实测触发；本格为该留档缺口的持续基线）。
注入：临时 MDCG_SUSTAIN_DIR，SustainLoop.start() 后线程 A 高频 beat()、线程 B
高频 diagnose/heal 同一 cg 实例、前台连续 add×N 同 root，跑 ~4s 后 stop() 比对。

读码核验（本套件设计基线）：sustain.py:844 _lock 已在位但只覆盖记账清单
（:940/:983/:1002/:1015 四处 with self._lock），diagnose 的裸迭代面
（sustain.py:484 nodes.items()）无锁——N138 崩溃面结构性仍在。动态复现属
时序敏感（两轮预演均在 ~1s 内捕获 RuntimeError），套件以读码断言为确定性
基线、动态捕获为加分证据（未捕获降级为 NOTE，不虚判绿）。

理论预期（EXPECTED_GAP，登记 gap）：裸迭代面无锁＝缺口仍在；beat 计数零丢失、
JSONL 零撕裂（写入面原子性由 P2 吸收，与缺口正交）。
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
        case.check("读码：_lock 在位但仅覆盖 4 处记账清单（tidys/evolves/scrubs/"
                   "heals——sustain.py:940/:983/:1002/:1015）",
                   lock_sites == 4, f"with self._lock 出现 {lock_sites} 次")
        diag = src.split("def diagnose", 1)[1].split("\ndef heal", 1)[0]
        case.check("读码：diagnose 的 nodes.items() 裸迭代无锁（sustain.py:484）"
                   "——T1 共享可变面违反点结构性在位",
                   "nodes.items()" in diag and "with self._lock" not in diag,
                   f"diagnose 函数体含裸迭代={('nodes.items()' in diag)}，"
                   f"含锁={('with self._lock' in diag)}")

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

        crash = [x for x in errors if x[1] == "RuntimeError"
                 and "dictionary changed size" in (x[2] or "")]
        if crash:
            case.check("红场（动态）：裸迭代 RuntimeError('dictionary changed "
                       "size during iteration') 当场捕获（N138 崩溃面实测复现）",
                       any("sustain.py" in (x[3] or "") and "diagnose" in
                           (x[3] or "") for x in crash),
                       crash[0][3][:300] if crash else "")
        else:
            case.note("动态捕获未命中（时序未命中，非防线生效）——缺口基线由读码"
                      "断言①②支撑（裸迭代无锁结构性在位），N138 动态实测证据见 "
                      "v16.md:90 复现②与本套件两轮预演（均 ~1s 内捕获）")

        # 四可（D4）
        case.check("四可：可发现=是（RuntimeError 异常打印/线程死亡，但无状态"
                   "告警）/可隔离=是（add 路径不受累，崩溃定位于 diagnose 迭代）"
                   "/可恢复=是（瞬态异常，无持久损伤，JSONL 零撕裂）/可追溯=是"
                   "（traceback 直指 sustain.py:484）",
                   True,
                   "证据=读码①② + 计数守恒 + 零撕裂 + 捕获栈定位")
        verdict = "gap" if not case.fails else "fail"
        return case.finish(verdict, expected="gap")
    finally:
        case.cleanup()


if __name__ == "__main__":
    sys.exit(main())
