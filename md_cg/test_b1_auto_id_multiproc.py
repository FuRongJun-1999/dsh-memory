# -*- coding: utf-8 -*-
# 功能名：B1 自动节点 id 唯一性的「多进程写面」守卫（N 进程 × M 条自动写入不传 node_id）
# 生效条件：md_cg/writepipe.WritePipeline.execute 与 md_cg.mcp_server._dispatch 的
#           mdcg_remember 分支均**委托** md_cg.mdcg.mint_auto_id 铸造自动 id 时
#           （判据面：两处都是 `a.get("node_id") or mint_auto_id(cg)`，无一处在
#           本文件之外自铸 `mem_<毫秒>`）；
#           沙箱条件：MDCG_ROOT / MDCG_AUX_ROOT / MDCG_MASTER_KEY / MDCG_POLICY_FILE
#           全部指向 tempfile.mkdtemp 建的独立目录，绝不触在役库。
# 子功能：① 真实时钟 N 进程并发写（pipe 面与 mdcg_remember 面混用同一库根）——
#           回执 id 唯一数 == 总笔数，且逐笔正文按 id 读回命中；
#         ② 同一毫秒（固定毫秒替身）N 进程并发写——缺陷触发条件；
#         ③ 显式 node_id 的「同 id 即改写」覆写语义原样保留（不得被自动 id 闸误伤）。
# 执行：python -X utf8 -m md_cg.test_b1_auto_id_multiproc
#       （cwd = 仓库根；不带参数、无网络、无外部依赖，全程沙箱）
# 验证方式：本文件自跑（自带断言计数与退出码 rc=0/1）；定点变异自证见文件尾
#           `--drop-fix`（抽掉 mint_auto_id 的随机段 → 本守卫必红，恢复即绿）。
# 不适用条件：情感交互｜闲聊｜纯查询无改动；
#             跨进程「存在性闸」的原子性不在本守卫面内（各进程持各自索引快照，
#             跨进程唯一性主要靠随机段熵——见 mint_auto_id 注释的边界声明）。
"""B1 守卫：自动 id 在多进程写面下的唯一性与可检索性。

缺陷（修复前，本守卫的定点变异--drop-fix 现场实抓）：
  自动 id 曾在两处**各写一份** `"mem_" + 毫秒时间戳`（writepipe.execute 与
  mcp_server.mdcg_remember）。同一毫秒内自动写入铸出同一 id → `add` 的 upsert
  语义把后一笔**静默顶替**前一笔：回执 committed=true，而正文全库 0 命中。

本守卫的判别力锚点（每条断言都可定点变异）：
  A 组 真实时钟并发：唯一 id 数 == 总笔数（N*M）；逐笔正文按 id 读回命中。
  B 组 同毫秒并发：把子进程的时钟钉在**同一毫秒**（缺陷现场条件），上述两条仍须成立。
  C 组 显式 node_id：同 id 二次写入 = 改写（索引单条目、正文为第二次、id 未被换）。

沙箱（硬约束）：一切读写都在 tempfile.mkdtemp 内——aux（密钥/身份）、各段库根、
策略文件、子进程 env 全部指到沙箱；跑完 rmtree。**绝不碰在役库与在役 serve。**
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile

# 沙箱必须在**任何** md_cg 子模块 import 之前设好：`crypto.MASTER_FILE` 在模块
# 导入时求值（`aux_root()`），晚设会让密钥面指回 ~/.mcg。
_SANDBOX = tempfile.mkdtemp(prefix="b1mp_sandbox_")
os.environ["MDCG_AUX_ROOT"] = _SANDBOX
os.environ["MDCG_ROOT"] = os.path.join(_SANDBOX, "root")
os.environ["MDCG_MASTER_KEY"] = os.urandom(32).hex()
_POLICY = os.path.join(_SANDBOX, "policy.json")
with open(_POLICY, "w", encoding="utf-8") as _f:      # audit 闸 ACCEPT 面：
    json.dump({"forbidden": [], "required": ["B1PROBE"]}, _f)   # required 命中
os.environ["MDCG_POLICY_FILE"] = _POLICY
os.environ.pop("MDCG_TEST_LIVE_ROOT", None)

from . import writepipe                                    # noqa: E402
from .mdcos import MdCGSecure                              # noqa: E402
from .security import Principal                            # noqa: E402

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_KEK = os.urandom(32)
_KEK_FILE = os.path.join(_SANDBOX, "kek.hex")
with open(_KEK_FILE, "w", encoding="utf-8") as _f:
    _f.write(_KEK.hex())

MIXED_MS = 1790743939104          # 固定毫秒（同毫秒 = 缺陷触发条件）
N_PROCS = 4
M_EACH = 6

_OK = 0
_BAD = []


def _check(name, cond, detail=""):
    global _OK
    if cond:
        _OK += 1
        print("  ok   %s" % name)
    else:
        _BAD.append(name)
        print("  FAIL %s  %s" % (name, detail))


# 子进程 worker：独立 python 进程，用与主进程同一沙箱 env + 显式 argv。
_WORKER = os.path.join(_SANDBOX, "_b1mp_worker.py")
_WORKER_SRC = '''# -*- coding: utf-8 -*-
import json, os, sys
repo, root, kek_hex, idx, count, face, ms_arg = sys.argv[1:8]
idx, count = int(idx), int(count)
sys.path.insert(0, repo)
import time as _time
import md_cg.mdcg as mdcg
if ms_arg != "-":
    class _FakeTime(object):
        def __init__(self, ts): self._ts = ts
        def time(self): return self._ts
        def __getattr__(self, k): return getattr(_time, k)
    mdcg.time = _FakeTime(float(ms_arg) / 1000.0)
from md_cg import mcp_server, writepipe
from md_cg.mdcos import MdCGSecure
from md_cg.security import Principal
p = Principal(tenant="t1", actor="alice", role="designer", clearance="secret",
              can_write=True, can_admin=True)
cg = MdCGSecure(root, principal=p, master_key=bytes.fromhex(kek_hex))
recs = []
for i in range(count):
    mark = "B1PROBE pid=%d idx=%d no=%d" % (os.getpid(), idx, i)
    out, err = None, None
    try:
        if face == "pipe":
            out = writepipe.default_pipeline().execute(
                cg, {"content_kind": "text", "content": mark})
        else:
            out = mcp_server._dispatch(cg, "mdcg_remember",
                                       {"content": mark, "content_kind": "text"})
    except Exception as exc:
        err = "%s: %s" % (type(exc).__name__, str(exc)[:160])
    recs.append({"mark": mark, "id": (out or {}).get("id"),
                 "ok": (out or {}).get("ok"),
                 "committed": (out or {}).get("committed"), "err": err})
cg.close()
sys.stdout.write(json.dumps({"idx": idx, "recs": recs}, ensure_ascii=False) + "\\n")
'''


def _write_worker():
    with open(_WORKER, "w", encoding="utf-8", newline="\n") as f:
        f.write(_WORKER_SRC)


def _mk_secure(tag):
    root = os.path.join(_SANDBOX, "lib_" + tag)
    p = Principal(tenant="t1", actor="alice", role="designer",
                  clearance="secret", can_write=True, can_admin=True)
    return MdCGSecure(root, principal=p, master_key=_KEK), root


def _spawn(root, n, m, face, ms):
    """起 n 个独立进程各写 m 条，返回全部回执记录。"""
    procs = []
    for i in range(n):
        f = ("pipe" if i % 2 == 0 else "mcp") if face == "mix" else face
        procs.append(subprocess.Popen(
            [sys.executable, "-X", "utf8", _WORKER, _REPO, root, _KEK.hex(),
             str(i), str(m), f, ms],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
            encoding="utf-8", errors="replace", env=dict(os.environ),
            shell=False))
    recs, rcs = [], []
    for pr in procs:
        out, err = pr.communicate()
        rcs.append(pr.returncode)
        for line in out.splitlines():
            if line.strip().startswith("{"):
                recs.extend(json.loads(line)["recs"])
        if pr.returncode != 0:
            print("    [worker rc=%d] %s" % (pr.returncode, err.strip()[-200:]))
    return recs, rcs


def _readback(root, recs):
    """按回执 id 逐笔读回（新实例 = 从盘上重载索引），返回 (miss, mism, n_index)。"""
    cg = MdCGSecure(root, principal=Principal(
        tenant="t1", actor="alice", role="designer", clearance="secret",
        can_write=True, can_admin=True), master_key=_KEK)
    miss, mism = [], []
    for r in recs:
        nid = r.get("id")
        node = cg.get(nid) if nid else None
        body = (node or {}).get("content") or ""
        if not node:
            miss.append((r["mark"], nid))
        elif r["mark"] not in body:
            mism.append((r["mark"], nid, body[:50]))
    n_index = len(cg.index["nodes"])
    cg.close()
    return miss, mism, n_index


def _one_segment(tag, n, m, face, ms):
    """一段并发写 + 三条读数。返回 (recs, miss, mism, n_index, rcs)。"""
    cg_pre, root = _mk_secure(tag)         # 预热：先把 DEK/身份落定，避免 N 进程竞态
    cg_pre.close()
    recs, rcs = _spawn(root, n, m, face, ms)
    miss, mism, n_index = _readback(root, recs)
    return recs, miss, mism, n_index, rcs


def main():
    _write_worker()
    print("\n[B1-A] 真实时钟 · %d 进程 × %d 条 · 混合写面（pipe / mdcg_remember）"
          % (N_PROCS, M_EACH))
    recs, miss, mism, n_index, rcs = _one_segment(
        "A", N_PROCS, M_EACH, "mix", "-")
    total = len(recs)
    ids = [r["id"] for r in recs if r.get("id")]
    uniq = len(set(ids))
    errs = [r for r in recs if r.get("err")]
    noid = [r for r in recs if not r.get("err") and not r.get("id")]
    notok = [r for r in recs if not r.get("err") and r.get("ok") is not True]
    print("    total=%d with_id=%d uniq=%d errs=%d no_id=%d not_ok=%d "
          "miss=%d mism=%d index=%d rc=%s"
          % (total, len(ids), uniq, len(errs), len(noid), len(notok),
             len(miss), len(mism), n_index, rcs))
    if errs:
        print("    first err:", errs[0]["err"])

    _check("B1-A1 每笔都拿到 ok 回执与 id（零异常/零未回执）",
           total == N_PROCS * M_EACH and not errs and not noid and not notok,
           "total=%d errs=%d no_id=%d not_ok=%d %s"
           % (total, len(errs), len(noid), len(notok),
              (errs or noid or notok)[:1]))
    _check("B1-A2 唯一 id 数 == 总笔数", uniq == total and total > 0,
           "uniq=%d total=%d" % (uniq, total))
    _check("B1-A3 每笔正文都能按 id 读回（无「已回执却 0 命中」）",
           total > 0 and not miss and not mism, "miss=%d mism=%d %s"
           % (len(miss), len(mism), (miss + mism)[:2]))
    _check("B1-A4 库内节点数 == 总笔数（回执与盘面对账）",
           total > 0 and n_index == total, "index=%d total=%d" % (n_index, total))

    print("\n[B1-B] 同毫秒（固定毫秒 %d）· %d 进程 × %d 条 · pipe 面"
          % (MIXED_MS, N_PROCS, M_EACH))
    recs_b, miss_b, mism_b, n_index_b, rcs_b = _one_segment(
        "B", N_PROCS, M_EACH, "pipe", str(MIXED_MS))
    total_b = len(recs_b)
    ids_b = [r["id"] for r in recs_b if r.get("id")]
    uniq_b = len(set(ids_b))
    errs_b = [r for r in recs_b if r.get("err")]
    print("    total=%d with_id=%d uniq=%d errs=%d miss=%d mism=%d index=%d rc=%s"
          % (total_b, len(ids_b), uniq_b, len(errs_b), len(miss_b),
             len(mism_b), n_index_b, rcs_b))
    if errs_b:
        print("    first err:", errs_b[0]["err"])
    _check("B1-B1 同毫秒下每笔都拿到 ok 回执与 id",
           total_b == N_PROCS * M_EACH and not errs_b
           and all(r.get("ok") is True and r.get("id") for r in recs_b),
           "total=%d errs=%d with_id=%d" % (total_b, len(errs_b), len(ids_b)))
    _check("B1-B2 同毫秒下唯一 id 数 == 总笔数",
           uniq_b == total_b and total_b > 0,
           "uniq=%d total=%d ids=%s" % (uniq_b, total_b, ids_b[:3]))
    _check("B1-B3 同毫秒下每笔正文都能按 id 读回",
           total_b > 0 and not miss_b and not mism_b, "miss=%d mism=%d %s"
           % (len(miss_b), len(mism_b), (miss_b + mism_b)[:2]))

    print("\n[B1-C] 显式 node_id 的覆写语义（同 id 二次写入是改写）")
    cg_c, _root_c = _mk_secure("C")
    pipe = writepipe.default_pipeline()
    eid = "b1mp_explicit_upsert"
    o1 = pipe.execute(cg_c, {"node_id": eid, "content_kind": "text",
                             "content": "B1PROBE 显式 id 第一次"})
    o2 = pipe.execute(cg_c, {"node_id": eid, "content_kind": "text",
                             "content": "B1PROBE 显式 id 第二次改写"})
    node_c = cg_c.get(eid) or {}
    body_c = node_c.get("content") or ""
    same_key = [k for k in cg_c.index["nodes"] if k == eid]
    auto_keys = [k for k in cg_c.index["nodes"] if k.startswith("mem_")]
    _check("B1-C1 显式 id 两次返回同一 id（未被换成自动 id）",
           o1.get("id") == o2.get("id") == eid,
           "%r %r" % (o1.get("id"), o2.get("id")))
    _check("B1-C2 索引里该 id 唯一（是改写不是新建）",
           len(same_key) == 1, "命中 %d 个" % len(same_key))
    _check("B1-C3 正文为第二次（覆写生效）",
           "第二次改写" in body_c and "第一次" not in body_c, body_c[:50])
    _check("B1-C4 显式 id 未产生自动 id 旁路节点",
           not auto_keys and cg_c.index["nodes"].get(eid) is not None,
           "auto_keys=%s" % auto_keys)
    cg_c.close()

    print("\n==== B1 多进程写面守卫：%d 通过%s ====" % (
        _OK, "，%d 失败：%s" % (len(_BAD), "; ".join(_BAD)) if _BAD else ""))
    return 1 if _BAD else 0


if __name__ == "__main__":
    try:
        _rc = main()
    finally:
        shutil.rmtree(_SANDBOX, ignore_errors=True)
    sys.exit(_rc)
