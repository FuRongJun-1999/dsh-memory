# -*- coding: utf-8 -*-
"""test_bootstrap_channel_b_state —— 通道 B 状态 JSON 原子写与损坏自愈守卫（N169）

背景（2026-09-27 缺陷 N169，severity=medium）：bootstrap_loop.py 通道 B 的
三份状态 JSON（channel_b_queue.json / channel_b_verified_units.json /
channel_b_drafts/rejected_log.json）用 open("w")+json.dump 非原子写，与同
文件 persist_triggers 的 P2-14 os.replace 原子款（:178-183）不同型；写中被
taskkill /F（bootstrap_watchdog kill_procs）强杀即截断损坏。此后每轮
run_channel_b 在裸 json.load 同崩（JSONDecodeError）无自愈；run_once 捕获
后轮次仍记 round=bootstrap_v2（HEALTHY 清单）——通道 B 永久死亡且 watchdog
内容级判活假绿（--check-only 恒 status=alive、EXIT=0）。

守卫断言面（哑环境：哑 datapath 注入 sys.modules，全部状态/日志落临时目录，
绝不触真实数据根；verifier 走仓内真件）：
  S1 写侧原子性：run_channel_b 落盘 queue/verified 必经 os.replace（修前 0 次）
  S2 verified 损坏自愈：截断文件在场时 run_channel_b 不崩、留痕 .corrupt-*、
     告警事件落日志、verified 重建并可继续固化
  S3 queue 损坏自愈：同上（损坏队列不再每轮同崩）
  S4 rejected_log 损坏自愈：验证失败分支在损坏留痕文件上不崩、重建追加
  S5 自愈告警留痕：损坏自愈产生 round=channel_b_state_corrupt 事件
  S6 判活假绿消除：a) 通道 B 异常轮 round=channel_b_error（不再恒
     bootstrap_v2 假绿）；b) watchdog DEGRADED 清单注册 channel_b_error /
     channel_b_state_corrupt 且 consecutive_degraded 对其计数
运行：python -X utf8 scripts/test_bootstrap_channel_b_state.py
"""
import importlib.util
import json
import os
import shutil
import sys
import tempfile
import types

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)

passed = failed = 0


def check(name, cond, detail=""):
    global passed, failed
    if cond:
        passed += 1
        print("  [PASS] " + name)
    else:
        failed += 1
        print("  [FAIL] " + name + "  " + str(detail)[:240])


def _log_rounds(log_path):
    if not os.path.isfile(log_path):
        return []
    out = []
    with open(log_path, encoding="utf-8") as f:
        for ln in f:
            ln = ln.strip()
            if ln:
                try:
                    out.append(json.loads(ln).get("round"))
                except ValueError:
                    pass
    return out


def main():
    global passed, failed
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    smoke = tempfile.mkdtemp(prefix="n169_channel_b_state_")

    # 哑 datapath：两个脚本模块的数据根解析全部落到 smoke（不触真实数据根）
    dp = types.ModuleType("datapath")

    def data_root():
        return smoke

    def find_existing(name):
        p = os.path.join(smoke, name)
        return p if os.path.isfile(p) else None

    dp.data_root = staticmethod(data_root)
    dp.find_existing = staticmethod(find_existing)
    sys.modules["datapath"] = dp

    def load(name, mod_id):
        spec = importlib.util.spec_from_file_location(
            mod_id, os.path.join(HERE, "scripts", name))
        m = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(m)
        return m

    m = load("bootstrap_loop.py", "bl_n169_guard")
    m_w = load("bootstrap_watchdog.py", "bw_n169_guard")
    LOG = os.path.join(smoke, "bootstrap", "bootstrap_log.jsonl")
    good_code = "def good_add(a, b):\n    return a + b\n"
    good_queue = {"pending": [{"task": "好1", "code": good_code,
                               "cases": [[[3, 4], 7]], "status": "new"}]}
    try:
        # ---- S1 写侧原子性：落盘必经 os.replace ----
        state1 = os.path.join(smoke, "st1")
        os.makedirs(state1, exist_ok=True)
        m.STATE = state1
        _real_replace = os.replace
        replaced = []
        try:
            def spy_replace(src, dst, *a, **k):
                replaced.append(os.path.basename(str(dst)))
                return _real_replace(src, dst, *a, **k)
            os.replace = spy_replace
            with open(os.path.join(state1, "channel_b_queue.json"),
                      "w", encoding="utf-8") as f:
                json.dump(good_queue, f, ensure_ascii=False)
            res1 = m.run_channel_b(None, max_tasks=5)
        finally:
            os.replace = _real_replace
        check("S1 run_channel_b 正常完成（passed=1）",
              res1.get("passed") == 1, repr(res1))
        check("S1 queue 落盘经 os.replace（修前 0 次=非原子 open-w）",
              "channel_b_queue.json" in replaced, replaced)
        check("S1 verified 落盘经 os.replace",
              "channel_b_verified_units.json" in replaced, replaced)

        # ---- S2+S5 verified 损坏自愈 ----
        state2 = os.path.join(smoke, "st2")
        m.STATE = state2
        out2 = os.path.join(state2, "channel_b_verified_units.json")
        os.makedirs(state2, exist_ok=True)
        with open(out2, "w", encoding="utf-8") as f:
            f.write('{"task:旧单元": {"code": "def x')   # taskkill /F 截断形态
        with open(os.path.join(state2, "channel_b_queue.json"),
                  "w", encoding="utf-8") as f:
            json.dump(good_queue, f, ensure_ascii=False)
        crashed = None
        res2 = None
        try:
            res2 = m.run_channel_b(None, max_tasks=5)
        except Exception as e:                    # 修前：JSONDecodeError
            crashed = e
        check("S2 verified 截断损坏 → run_channel_b 不崩"
              "（修前 JSONDecodeError('Unterminated string')）",
              crashed is None, repr(crashed))
        if res2 is not None:
            check("S2 自愈后通道继续固化（passed=1）",
                  res2.get("passed") == 1, repr(res2))
        leftover = [n for n in os.listdir(state2)
                    if n.startswith("channel_b_verified_units.json.corrupt-")]
        check("S2 损坏文件改名 .corrupt-* 留痕（现场可人工找回）",
              len(leftover) == 1, os.listdir(state2))
        if leftover:
            keep = open(os.path.join(state2, leftover[0]),
                        encoding="utf-8").read()
            check("S2 留痕内容=原损坏文本（截断现场保全）",
                  keep.startswith('{"task:旧单元"'), keep[:40])
        try:
            rebuilt = json.load(open(out2, encoding="utf-8"))
            rebuilt_ok = "task:好1" in rebuilt
            rebuilt_detail = list(rebuilt)[:5]
        except ValueError:                        # 修前：文件仍为损坏态
            rebuilt_ok = False
            rebuilt_detail = "verified 仍为截断损坏态"
        check("S2 verified 重建且新条目固化（task:好1 在库）",
              rebuilt_ok, rebuilt_detail)
        check("S5 自愈产生 channel_b_state_corrupt 告警事件",
              "channel_b_state_corrupt" in _log_rounds(LOG),
              _log_rounds(LOG)[-5:])

        # ---- S3 queue 损坏自愈 ----
        state3 = os.path.join(smoke, "st3")
        m.STATE = state3
        os.makedirs(state3, exist_ok=True)
        q3 = os.path.join(state3, "channel_b_queue.json")
        with open(q3, "w", encoding="utf-8") as f:
            f.write('{"pending": [[[')                # 截断形态
        crashed = None
        res3 = None
        try:
            res3 = m.run_channel_b(None, max_tasks=5)
        except Exception as e:
            crashed = e
        check("S3 queue 截断损坏 → run_channel_b 不崩"
              "（修前 JSONDecodeError('Expecting , delimiter')类同崩）",
              crashed is None, repr(crashed))
        if res3 is not None:
            check("S3 自愈后按空队列完成（source=queue）",
                  res3.get("source") == "queue", repr(res3))
        left3 = [n for n in os.listdir(state3)
                 if n.startswith("channel_b_queue.json.corrupt-")]
        check("S3 损坏 queue 改名留痕（原路径不再每轮同崩）",
              len(left3) == 1 and not os.path.exists(q3),
              (left3, os.path.exists(q3)))

        # ---- S4 rejected_log 损坏自愈（验证失败分支） ----
        state4 = os.path.join(smoke, "st4")
        m.STATE = state4
        os.makedirs(state4, exist_ok=True)
        rej4 = os.path.join(state4, "channel_b_drafts", "rejected_log.json")
        os.makedirs(os.path.dirname(rej4), exist_ok=True)
        with open(rej4, "w", encoding="utf-8") as f:
            f.write('[{"task": "旧拒绝"')              # 截断形态
        bad_queue = {"pending": [{"task": "坏算术", "code": good_code,
                                  "cases": [[[3, 4], 100]],
                                  "status": "new"}]}
        with open(os.path.join(state4, "channel_b_queue.json"),
                  "w", encoding="utf-8") as f:
            json.dump(bad_queue, f, ensure_ascii=False)
        crashed = None
        res4 = None
        try:
            res4 = m.run_channel_b(None, max_tasks=5)
        except Exception as e:
            crashed = e
        check("S4 rejected_log 截断损坏 → 验证失败分支不崩"
              "（修前 JSONDecodeError 同崩）",
              crashed is None, repr(crashed))
        if res4 is not None:
            check("S4 stats：failed=1（cases 期望未过）",
                  res4.get("failed") == 1, repr(res4))
        try:
            rej = json.load(open(rej4, encoding="utf-8"))
            rej_ok = isinstance(rej, list) and any(
                r.get("task") == "坏算术" for r in rej)
            rej_detail = repr(rej)[:120]
        except ValueError:                        # 修前：文件仍为损坏态
            rej_ok = False
            rej_detail = "rejected_log 仍为截断损坏态"
        check("S4 rejected_log 重建为合法 list 且含本次拒绝",
              rej_ok, rej_detail)

        # ---- S6a 通道 B 异常轮次语义（判活假绿消除） ----
        state5 = os.path.join(smoke, "st5")
        m.STATE = state5
        m.scan_route_gaps = lambda limit=None: []     # 通道 A 哑转
        def _boom(*a, **k):
            raise RuntimeError("桩件故障（模拟通道 B 连续异常）")
        m.run_channel_b = _boom
        res5 = m.run_once(channel_b=True)
        rounds = _log_rounds(LOG)
        check("S6a 通道 B 异常轮 round=channel_b_error"
              "（修前恒 bootstrap_v2 落 HEALTHY 假绿）",
              rounds and rounds[-1] == "channel_b_error", rounds[-3:])
        check("S6a result.channel_b.error 带异常摘要",
              "桩件故障" in (res5.get("channel_b") or {}).get("error", ""),
              repr(res5.get("channel_b")))

        # ---- S6b watchdog DEGRADED 清单与计数 ----
        check("S6b DEGRADED 清单注册 channel_b_error",
              "channel_b_error" in m_w.DEGRADED_ROUNDS,
              m_w.DEGRADED_ROUNDS)
        check("S6b DEGRADED 清单注册 channel_b_state_corrupt",
              "channel_b_state_corrupt" in m_w.DEGRADED_ROUNDS,
              m_w.DEGRADED_ROUNDS)
        check("S6b HEALTHY 清单不含错误类轮次",
              not ({"channel_b_error", "channel_b_state_corrupt"}
                   & set(m_w.HEALTHY_ROUNDS)), m_w.HEALTHY_ROUNDS)
        with open(m_w.LOG, "a", encoding="utf-8") as f:
            for r in ("bootstrap_v2", "channel_b_error",
                      "channel_b_error", "channel_b_error"):
                f.write(json.dumps({"round": r, "ts": "2026-09-27 00:00:00"},
                                   ensure_ascii=False) + "\n")
        check("S6b consecutive_degraded 对 channel_b_error 连续计数=3"
              "（修前 0 → watchdog 恒 alive 假绿）",
              m_w.consecutive_degraded() == 3, m_w.consecutive_degraded())
    finally:
        for name in ("datapath",):                 # 撤哑件注入
            sys.modules.pop(name, None)
        shutil.rmtree(smoke, ignore_errors=True)

    print("\n%d passed, %d failed" % (passed, failed))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
