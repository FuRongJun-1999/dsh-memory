# -*- coding: utf-8 -*-
"""orch._poll 解析短路守卫（v7 留档「orch._poll 重复解析」修复）。

缺陷形态（缺陷报告实测，8 子任务/210KB result，串行 7rep 中位）：
  _poll→_card 每次轮询对全部子任务全量重读+json.load status.json 与
  result.json 全文（mcp_server.py _read_status/_result_view 无 mtime/size
  短路）——poll 是编排等待循环的高频重复动作（spawn 返回 hint 明示
  「继续轮询 poll_subtasks」）：content 50K/200K/800K → _poll
  0.98/2.67/10.13ms 随产物大小近似线性、随轮询次数线性累积；对照同批
  16 文件纯 os.stat 仅 0.233ms（11.5×@210KB×8）。

修复口径：mcp_server._read_status/_result_view 以 (st_mtime_ns, st_size)
为签名的解析缓存短路未变更文件——文件未变复用已解析值（浅拷贝保持
「每次调用返回可独立变更的新 dict」既有语义），变更/删除按签名失配
重解析。orch._poll/_card 与 MCP 面 _t_poll 共用（单一真源）。

本守卫（调用计数/复杂度断言形态，非时间阈值）：
  C0 首次轮询冷启全量读（opens==2N）且卡片字段正确；
  C1 未变更文件重复轮询零重解析（opens==0，连续 3 次恒 0——旧实现
     每轮 2N → 红）；
  C2 同尺寸内容改写（只动 mtime）被识别：卡片见新内容、仅该文件
     重解析（opens ≤ 2，旧实现整轮 2N → 红）；
  C3 status 状态迁移（running→done）即时可见；
  C4 终态删 result.json 后不复活陈旧缓存内容（hint 如实）；
  C5 full=True 全文与盘面逐位一致（缓存不改变输出）；
  C6 _read_status 每次返回独立 dict（_t_poll 挂 st["result"] 不污染缓存）；
  C7 _result_view 截断派生不破坏缓存基底（head 截断后再全文读仍完整）。

运行：python -m hive.test_orch_poll_cache   （退出码 0 = 全绿）
"""
import builtins
import importlib.util
import json
import os
import shutil
import sys
import tempfile

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except AttributeError:
    pass

_HERE = os.path.dirname(os.path.abspath(__file__))
_REPO = os.path.dirname(_HERE)
for _p in (_REPO, _HERE):
    if _p not in sys.path:
        sys.path.insert(0, _p)

PASS, FAIL = 0, 0


def check(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  [ok] {name}")
    else:
        FAIL += 1
        print(f"  [FAIL] {name}  {detail}")


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


orc = _load("hive_orch_pc", os.path.join(_HERE, "orch.py"))
hm = sys.modules["hive_mcp.mcp_server"] if "hive_mcp.mcp_server" in sys.modules \
    else _load("hive_mcp.mcp_server", os.path.join(_HERE, "hive_mcp", "mcp_server.py"))

N = 6
TMP = tempfile.mkdtemp(prefix="hive_orch_pollcache_")
JOBS = os.path.join(TMP, "jobs")
os.makedirs(JOBS)


def _mk(jid, state="running", content="A" * 400, trace_n=20):
    d = os.path.join(JOBS, jid)
    os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, "status.json"), "w", encoding="utf-8") as f:
        json.dump({"job_id": jid, "state": state, "created_ts": 1,
                   "heartbeat_ts": 2, "elapsed_s": 1.5, "timeout_s": 300,
                   "model": None, "pid": None, "error": None}, f)
    with open(os.path.join(d, "result.json"), "w", encoding="utf-8") as f:
        json.dump({"ok": True, "completed": True, "need_continue": False,
                   "content": content,
                   "tool_trace": [{"tool": "t%d" % k, "ok": True, "brief": "b"}
                                  for k in range(trace_n)],
                   "usage": {"tokens": 100}}, f)
    return d


def _count_opens(fn):
    """计数 JOBS 下 status.json/result.json 的 open 次数（节点文件读度量面）。"""
    n = 0
    real = builtins.open

    def _spy(file, mode="r", *a, **kw):
        nonlocal n
        s = str(file)
        if "r" in mode and not ("w" in mode or "a" in mode or "+" in mode) \
                and JOBS in s and ("status.json" in s or "result.json" in s):
            n += 1
        return real(file, mode, *a, **kw)

    builtins.open = _spy
    try:
        return fn(), n
    finally:
        builtins.open = real


IDS = ["h_pc%03d" % i for i in range(N)]
for _jid in IDS:
    _mk(_jid)
orc._CFG.update({"job_id": "orchjob", "job_dir": TMP, "jobs": JOBS,
                 "children": [{"job_id": i} for i in IDS], "max_subtasks": N})

try:
    print("[C0] 首次轮询冷启全量读 + 卡片字段")
    r0, n0 = _count_opens(lambda: orc._poll({}))
    c0 = {c["job_id"]: c for c in r0["children"]}
    check("C0a 冷启 opens == 2N（每子任务 status+result 各一次）",
          n0 == 2 * N, f"opens={n0} expect={2 * N}")
    check("C0b 卡片字段正确（state/content_head/tool_calls）",
          r0["count"] == N
          and c0[IDS[0]]["state"] == "running"
          and c0[IDS[0]].get("content_head") == "A" * 200
          and c0[IDS[0]].get("tool_calls") == 20
          and len(c0[IDS[0]].get("tool_trace_brief") or []) == 6,
          str(c0[IDS[0]])[:120])

    print("[C1] 未变更重复轮询零重解析")
    seq = []
    for _ in range(3):
        _, n = _count_opens(lambda: orc._poll({}))
        seq.append(n)
    check("C1a 连续 3 次重复轮询 opens==0（旧实现每轮 2N）",
          seq == [0, 0, 0], f"opens={seq}")

    print("[C2] 同尺寸改写（只动 mtime）被识别")
    # content A*400 → B*400：字节数不变，只有 mtime 变——签名须含 mtime_ns
    _mk(IDS[0], content="B" * 400)
    r2, n2 = _count_opens(lambda: orc._poll({}))
    c2 = {c["job_id"]: c for c in r2["children"]}
    check("C2a 同尺寸改写后卡片见新内容（content_head 以 B 起）",
          c2[IDS[0]].get("content_head") == "B" * 200,
          str(c2[IDS[0]].get("content_head"))[:40])
    check("C2b 仅变更文件重解析（opens ≤ 2；旧实现整轮 2N）",
          n2 <= 2, f"opens={n2}")

    print("[C3] status 状态迁移即时可见")
    _mk(IDS[1], state="done")
    r3, n3 = _count_opens(lambda: orc._poll({}))
    c3 = {c["job_id"]: c for c in r3["children"]}
    check("C3a running→done 即时可见（done 计数 +1）",
          c3[IDS[1]]["state"] == "done" and r3["done"] == 1,
          f"state={c3[IDS[1]]['state']} done={r3['done']}")
    check("C3b 仅迁移文件重解析（opens ≤ 2）", n3 <= 2, f"opens={n3}")

    print("[C4] 删除 result.json 不复活陈旧缓存")
    os.remove(os.path.join(JOBS, IDS[1], "result.json"))
    r4, _ = _count_opens(lambda: orc._poll({}))
    c4 = {c["job_id"]: c for c in r4["children"]}
    check("C4a 终态无 result 如实提示（无陈旧 content/content_head 复活）",
          c4[IDS[1]]["state"] == "done"
          and "result.json" in (c4[IDS[1]].get("hint") or "")
          and "content" not in c4[IDS[1]]
          and "content_head" not in c4[IDS[1]],
          str(c4[IDS[1]])[:120])

    print("[C5] full=True 全文与盘面逐位一致")
    rf, _ = _count_opens(lambda: orc._poll({"full": True}))
    cf = {c["job_id"]: c for c in rf["children"]}
    with open(os.path.join(JOBS, IDS[2], "result.json"), encoding="utf-8") as f:
        disk = json.load(f)
    check("C5a full 卡片 content 与盘面全文逐位一致",
          cf[IDS[2]].get("content") == disk["content"]
          and cf[IDS[2]].get("tool_calls") == len(disk["tool_trace"]),
          f"len={len(cf[IDS[2]].get('content') or '')}/{len(disk['content'])}")

    print("[C6/C7] mcp_server 读函数语义保持（共享单一真源）")
    st1 = hm._read_status(JOBS, IDS[3])
    st1["result"] = {"污染": True}
    st2 = hm._read_status(JOBS, IDS[3])
    check("C6a _read_status 每次返回独立 dict（挂 result 不入缓存）",
          "result" not in st2, f"keys={sorted(st2)[:8]}")
    d3 = os.path.join(JOBS, IDS[3])
    v_head = hm._result_view(d3, head=200)
    v_full = hm._result_view(d3, head=None)
    v_head2 = hm._result_view(d3, head=200)
    check("C7a 截断派生不破坏缓存基底（head 截断→全文→再截断均正确）",
          v_head.get("content_head") == "A" * 200
          and "content" not in v_head
          and v_full.get("content") == "A" * 400
          and v_head2.get("content_head") == "A" * 200,
          f"head={str(v_head.get('content_head'))[:30]} "
          f"full_len={len(v_full.get('content') or '')}")
    miss = hm._result_view(os.path.join(JOBS, "h_nonexist"), head=200)
    check("C7b 不存在任务 result_view 返回 None（不缓存伪值）", miss is None)
finally:
    shutil.rmtree(TMP, ignore_errors=True)
    sys.modules.pop("hive_orch_pc", None)

print("=" * 60)
print(f"结果：PASS {PASS} / FAIL {FAIL}")
sys.exit(0 if FAIL == 0 else 1)
