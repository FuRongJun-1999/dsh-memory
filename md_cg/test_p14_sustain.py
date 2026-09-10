# -*- coding: utf-8 -*-
"""P14：持续性自维持（`sustain.py`）——常驻 / 心跳 / 自愈 / 会话续接。

覆盖：心跳戳与分级判定（含任务中放宽）→ 只读诊断（索引漂移 / 孤儿索引 /
陈旧临时文件 / 半截日志行 / 增量积压 / 缺密钥私有节点）→ 自愈（dry-run 与实修，
永不删节点）→ 会话水位续接 → 常驻循环（自动心跳 + 自动自愈 + 正常下线清戳）
→ MCP `op=sustain` 接入。
"""
import json
import os
import shutil
import tempfile
import time

from . import nodefile, sustain
from .fsutil import ends_mid_line
from .mdcg import MdCG
from .mdcos import MdCGSecure
from .security import Principal

PASS = FAIL = 0


def check(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  [PASS] {name}" + (f"  · {detail}" if detail else ""))
    else:
        FAIL += 1
        print(f"  [FAIL] {name}" + (f"  · {detail}" if detail else ""))


def main():
    net = tempfile.mkdtemp(prefix="mdcg_p14_net_")
    os.environ["MDCG_SUSTAIN_DIR"] = net
    root = sroot = None
    try:
        # ---------- A. 心跳与分级判定 ----------
        print("\n[A] 心跳与分级判定")
        sustain.write_stamp("t1", task_running=False, root="/tmp/x", uptime=1.5)
        check("A1 心跳戳落盘", os.path.exists(sustain.stamp_path("t1")))
        got = sustain.read_stamp("t1")
        check("A2 字段完整", bool(got and got["v"] == 1 and got["name"] == "t1"
                                 and got["pid"] == os.getpid()
                                 and got["root"] == "/tmp/x"
                                 and got["task_running"] is False))
        check("A3 age 近零", bool(got and got["age"] < 5))
        check("A4 新戳=ok", sustain.judge(0) == "ok")
        check("A5 2×间隔内仍 ok", sustain.judge(1200) == "ok")
        check("A6 3.3×=warning", sustain.judge(2000) == "warning")
        check("A7 5×=dead", sustain.judge(3000) == "dead")
        check("A8 无戳=absent", sustain.judge(None) == "absent")
        check("A9 任务中阈值放宽（4000s→warning）",
              sustain.judge(4000, task_running=True) == "warning")
        ps = sustain.peers()
        check("A10 peers 可见", len(ps) == 1 and ps[0]["name"] == "t1"
              and ps[0]["state"] == "ok")
        sustain.clear_stamp("t1")
        check("A11 清戳后 absent", sustain.read_stamp("t1") is None
              and sustain.peers() == [])

        # ---------- B. 诊断（只读） ----------
        print("\n[B] 诊断（只读）")
        root = tempfile.mkdtemp(prefix="mdcg_p14_")
        cg = MdCG(root)
        cg.add("n1", "# 功能名：甲\n# 执行：add\n\nhello")
        cg.add("n2", "# 功能名：乙\n# 执行：add\n\nworld")
        rep = sustain.diagnose(cg)
        check("B1 健康库 ok", rep["ok"] and not [i for i in rep["issues"]
                                                if i["severity"] == "warning"])
        check("B2 索引与磁盘一致", rep["stats"]["nodes_indexed"] == 2
              and rep["stats"]["nodes_on_disk"] == 2)

        cg.index["nodes"]["ghost"] = {"path": "knowledge/nope/ghost.md"}
        rep = sustain.diagnose(cg)
        check("B3 孤儿索引被发现（warning）",
              "index_orphan" in {i["code"] for i in rep["issues"]}
              and not rep["ok"])
        del cg.index["nodes"]["ghost"]

        p3 = os.path.join(root, "knowledge", "orphan", "n3.md")
        os.makedirs(os.path.dirname(p3), exist_ok=True)
        with open(p3, "w", encoding="utf-8") as f:
            f.write(nodefile.dumps({"layer": "knowledge"}, "# 功能名：丙\n\nnew"))
        rep = sustain.diagnose(cg)
        check("B4 索引漂移被发现",
              "index_drift" in {i["code"] for i in rep["issues"]})
        os.remove(p3)

        tmpf = os.path.join(root, ".n1.md.tmp-dead")
        with open(tmpf, "w", encoding="utf-8") as f:
            f.write("x")
        old = time.time() - 7200
        os.utime(tmpf, (old, old))
        rep = sustain.diagnose(cg)
        check("B5 陈旧临时文件被发现（info 不降 ok）",
              "stale_temps" in {i["code"] for i in rep["issues"]})

        logf = os.path.join(root, "_access.log")
        with open(logf, "w", encoding="utf-8") as f:
            f.write('{"a":1}')
        rep = sustain.diagnose(cg)
        check("B6 半截日志行被发现（warning）",
              "half_line_logs" in {i["code"] for i in rep["issues"]})

        ilog = os.path.join(root, "_index_log")
        os.makedirs(ilog, exist_ok=True)
        with open(os.path.join(ilog, "9-x.log"), "w", encoding="utf-8") as f:
            f.write('{"id":"n1"}\n')
        rep = sustain.diagnose(cg)
        check("B7 索引增量积压被发现",
              "index_log_backlog" in {i["code"] for i in rep["issues"]})

        snap = sorted(os.listdir(root))
        sustain.diagnose(cg)
        check("B8 诊断不改动文件", sorted(os.listdir(root)) == snap)

        sroot = tempfile.mkdtemp(prefix="mdcg_p14_sec_")
        sec = MdCGSecure(sroot, master_key=os.urandom(32), principal=Principal(
            tenant="t", actor="a", clearance="secret", can_write=True))
        sec.add("p1", "# 功能名：私\n# 执行：add\n\nsecret",
                sensitivity="private")
        sec.lock()
        rep = sustain.diagnose(sec)
        locked = [i for i in rep["issues"] if i["code"] == "locked_nodes"]
        check("B9 缺密钥私有节点被报告（fix=None，不自愈）",
              bool(locked and locked[0]["fix"] is None)
              and rep["stats"]["locked_nodes"] == 1)
        # ---------- C. 自愈 ----------
        print("\n[C] 自愈（只碰派生物，永不删节点）")
        os.remove(tmpf)
        os.remove(logf)
        shutil.rmtree(ilog, ignore_errors=True)
        cg.rebuild_index()
        nodes_before = sustain._count_node_files(root)

        cg.index["nodes"]["ghost"] = {"path": "knowledge/nope/ghost.md"}
        dry = sustain.heal(cg, dry_run=True)
        check("C1 dry-run 只列动作不改动",
              dry["dry_run"] and "ghost" in cg.index["nodes"]
              and all(not a["applied"] for a in dry["actions"])
              and any(a["code"] == "rebuild_index" for a in dry["actions"]))

        res = sustain.heal(cg)
        check("C2 孤儿索引被重建", "ghost" not in cg.index["nodes"]
              and any(a["code"] == "rebuild_index" and a.get("ok")
                      for a in res["actions"]))
        check("C3 自愈后 ok", res["ok"])

        tmp2 = os.path.join(root, ".n2.md.tmp-dead2")
        with open(tmp2, "w", encoding="utf-8") as f:
            f.write("y")
        os.utime(tmp2, (old, old))
        with open(logf, "w", encoding="utf-8") as f:
            f.write('{"b":2}')
        res = sustain.heal(cg)
        codes = {a["code"] for a in res["actions"]}
        check("C4 陈旧临时文件被清理", not os.path.exists(tmp2)
              and "sweep_temps" in codes)
        check("C5 半截日志行被修补", not ends_mid_line(logf)
              and "seal_half_lines" in codes)
        check("C6 节点文件数不变（永不删节点）",
              sustain._count_node_files(root) == nodes_before)
        check("C7 自愈留审计",
              os.path.exists(os.path.join(root, "_sustain.jsonl")))

        # ---------- D. 会话水位续接 ----------
        print("\n[D] 会话水位（重启续接）")
        led = sustain.SessionLedger(root)
        led.note("s1", t=1000.0, seq=3, actor="alice")
        led.note("s1", t=2000.0, seq=8, n=2)
        rp = led.resume_point("s1")
        check("D1 水位可续接", rp["resume"] == {"t": 2000.0, "seq": 8}
              and rp["events"] == 3 and rp["actor"] == "alice")
        check("D2 未知会话无续接点", led.resume_point("nope")["resume"] is None)
        led2 = sustain.SessionLedger(root)          # 模拟重启
        check("D3 重启后仍可读", led2.resume_point("s1")["events"] == 3)
        check("D4 summary 统计", led2.summary()["sessions"] == 1
              and led2.summary()["events"] == 3)
        with open(os.path.join(root, "_sources.json"), "w",
                  encoding="utf-8") as f:
            json.dump({"sources": {"file:x": {"t": 9, "seq": 2}}}, f)
        check("D5 源水位可读", sustain.watermarks(cg)["file:x"]["seq"] == 2)
        # ---------- E. 常驻循环与 MCP 接入 ----------
        print("\n[E] 常驻循环与 MCP 接入")
        cg.rebuild_index()
        if os.path.exists(logf):
            os.remove(logf)
        shutil.rmtree(ilog, ignore_errors=True)
        check("E0 起点健康", sustain.diagnose(cg)["ok"])

        lp = sustain.SustainLoop(cg, "loop1", beat_interval=0.05,
                                 heal_interval=0.05, auto_heal=True, d=net)
        lp.start()
        time.sleep(0.1)
        check("E1 start 后运行中且有戳", lp.status()["running"]
              and sustain.read_stamp("loop1") is not None)
        time.sleep(0.9)
        check("E2 自动补心跳", lp.beats >= 2, f"beats={lp.beats}")

        cg.index["nodes"]["ghost2"] = {"path": "knowledge/nope/ghost2.md"}
        time.sleep(0.9)
        check("E3 自动自愈（孤儿索引被重建）",
              bool(lp.heals) and "ghost2" not in cg.index["nodes"],
              f"heals={lp.heals}")
        lp.stop()
        check("E4 stop 后清戳", not lp.status()["running"]
              and sustain.read_stamp("loop1") is None)
        lp2 = sustain.ensure_loop(cg, "loop2", d=net)
        check("E5 ensure_loop 复用同一实例",
              sustain.ensure_loop(cg, "loop2", d=net) is lp2)

        from .mcp_server import call_tool
        st = call_tool(cg, "cg", {"op": "sustain", "action": "status"})
        check("E6 MCP status", "heartbeat" in st and "loop" in st
              and "sessions" in st)
        cat = call_tool(cg, "cg", {"op": "sustain", "action": "catalog"})
        check("E7 MCP catalog", "diagnose" in cat["actions"]
              and cat["net_dir"] == net)
        h = call_tool(cg, "cg", {"op": "sustain", "action": "heal",
                                 "dry_run": True})
        check("E8 MCP heal dry-run", h["dry_run"] is True)
        call_tool(cg, "cg", {"op": "sustain", "action": "note",
                             "session": "sX", "ts": 123, "seq": 7})
        r = call_tool(cg, "cg", {"op": "sustain", "action": "resume",
                                 "session": "sX"})
        check("E9 MCP note→resume", r["resume"] == {"t": 123.0, "seq": 7})
        dg = call_tool(cg, "cg", {"op": "sustain", "action": "diagnose"})
        check("E10 MCP diagnose", "stats" in dg and "ok" in dg)
        b = call_tool(cg, "cg", {"op": "sustain", "action": "beat",
                                 "name": "mcpbeat", "task_running": True})
        check("E11 MCP beat 写戳", b["beat"]["name"] == "mcpbeat"
              and b["beat"]["task_running"] is True)
        sustain.clear_stamp("mcpbeat")
    finally:
        os.environ.pop("MDCG_SUSTAIN_DIR", None)
        sustain.stop_all()
        for d in (net, root, sroot):
            if d:
                shutil.rmtree(d, ignore_errors=True)

    print(f"\n==== P14 结果：{PASS} 通过 / {FAIL} 失败 ====")
    return 1 if FAIL else 0


if __name__ == "__main__":
    import sys
    sys.exit(main())
