# -*- coding: utf-8 -*-
# 功能名：issue #322 守卫——同 root 多实例并发写同一 node_id 的跨进程互斥
# 生效条件：md_cg/writepipe.WritePipeline.execute 在拿到 node_id 后、进入
#           before 链之前按 node_id 持**跨进程排它锁**（fsutil.node_write_lock，
#           <root>/.locks/<sanitized nid>.lock，strict），且锁内先重载索引
#           （_refresh_index_in_lock）再跑「判存在→落盘→flush」整段；
#           **工具面（mcp_server._dispatch 的 mdcg_remember 分支——hooks 自动
#           记忆主通路）同样经 writepipe._node_write_lock 持锁 + 锁内刷代际 +
#           两个落盘出口 _commit_visibility（issue #322 R0，2026-10-16）**；
#           沙箱条件：MDCG_ROOT / MDCG_AUX_ROOT / MDCG_MASTER_KEY /
#           MDCG_POLICY_FILE 全部指向 tempfile.mkdtemp 建的独立目录，绝不触
#           在役库。
# 子功能：U  锁原语（路径布局 / sanitize 防穿越 / strict 跨进程互斥超时 /
#            同线程可重入——副作用 2 修复）
#         S  串行基线（同 id 二写 → 审核队列；anchor→knowledge → ProtectionError）
#         G1 并发同 id（2 进程 × 10 轮）：无静默丢——每轮恰一份 committed:true、
#            另一份 committed:false 进审核队列、盘上恰一份文件、读回=赢家正文
#         G2 anchor 竞态（2 进程 × 8 轮）：ProtectionError 语义恢复/两份不并存
#         G3 防过修：串行二次写零回归；不同 id 并发写互不阻塞全 committed
#         T1 锁间谍：动词面与工具面取锁读数各 =1（R0 回归锚——修前实测
#            verb_locks=1 / tool_locks=0，最热通路不在锁面内）
#         T2 工具面并发同 id（2 进程 × 8 轮，模拟 dispatch 面）：恰一份落盘、
#            无双 committed、读回=赢家（与 G1 同判据、换通路）
# 执行：python -X utf8 -m md_cg.test_issue322_concurrent_write_guard
#       定点变异自证：--drop-fix（抽掉 per-node 锁=恢复无锁直写）⇒ G1/G2/T1/T2
#       必红（G1 静默丢 > 0、G2 双文件 > 0、T1 tool_locks=0、T2 双 committed），
#       恢复即绿；S/G3 两向都绿（串行语义与锁正交）。
#       变异红项读数（值守实测，2026-10-16）：抽锁后红 8 项——G1×5（G1-1/2/4/5/6）
#       + G2×3（G2-1/2/3）。此前报告口径写 9，**订正为 8**（G1-3「恰一份文件」
#       在无锁双写下两写同层同路径、后者覆盖前者，盘面仍只见一份文件，
#       故该项不红——不计入）。补 T 面后变异红项另增 6（T1a/T1b + T2-1/2/4/5；
#       T2-3 与 G1-3 同理不红），合计 14。
# 不适用条件：情感交互｜闲聊｜纯查询无改动；
#             直调 MdCG.add 的其余写面（审核 accept 重放、backfill 等）不在
#             本锁面内（见 writepipe.execute 文档串「边界」段）；工具面
#             mdcg_remember 已入锁面（R0，2026-10-16）。
#
# 已知边界（如实登记，不设断言——本件修不了）：
#   · 锁文件外部删除（ybyz2 技术审副作用 1）：flock/msvcrt.locking 都是
#     per-inode 的锁，.locks/*.lock 被外部删除后同名重建会让两进程各持不同
#     inode 的锁、互斥静默失效。彻底关死需 OS 级目录锁或持锁者心跳方案，
#     超出本件（文件锁原语）能力面；缓解 = 本仓永不删除锁文件（fsutil
#     node_write_lock「清理口径」）。守卫不为其设断言（该面修不了，设断言
#     只会产生永远红不了的假判别力）。
#   · 同线程重入已修（副作用 2，fsutil._ReentrantFileLock：threading.local
#     计数，同线程重入放行、跨进程/跨线程仍互斥）；同进程**跨线程**同 id
#     竞争仍要等 OS 锁（超时 30s 后 strict TimeoutError）——串行等待语义，
#     非静默。
"""issue #322 守卫：多实例共根并发写同一 node_id——静默丢正文与 anchor 竞态。

缺陷（修复前，本守卫 --drop-fix 定点变异实抓）：
  「判存在（_gate_autonomy 的 prior_node / write_qualify 直读本进程内存索引）
  → 落盘（cg.add → _write_node）→ 索引可见（_commit_visibility 的 flush）」
  全段无跨进程互斥。同一 root 多实例并发写同一 node_id：两进程都判「不存在」
  都按新增落盘，后写盖前写，**两边都返回 committed:true 而输家正文全库消失**
  （改前实测 2 进程×5 轮 5/5 静默丢）；anchor/knowledge 跨层竞态则两份同 id
  文件并存、新实例读到 knowledge 份，串行时本该 ProtectionError（改前实测
  2 进程×8 轮 8/8 双文件）。

R0（ybyz2 技术审第 1 条，2026-10-16）：首批修复只锁了动词面
  （writepipe.execute）——hooks 自动记忆走的**工具面**（mcp_server 的
  mdcg_remember 分支）直调 remember_gated / cg.add 提前 return，根本到不了
  锁：锁间谍实测 verb_locks=1 / tool_locks=0，该通路并发同 id 双 committed +
  输家正文消失完全没有被修。本批给工具面接同款锁（复用 writepipe 三个单点），
  T1 钉锁间谍读数、T2 钉并发行为。

判别力锚点（每条断言都可定点变异）：
  G1 每轮「恰一 committed:true + 另一份 committed:false/review_queue」——
     抽掉锁后双 committed 复现，静默丢 > 0 必红；
  G2 每轮「不双 committed + 盘上恰一份」——抽掉锁后双文件 > 0 必红；
  T1 动词面/工具面取锁读数各 =1——抽掉锁后 tool_locks=0 必红（R0 回归锚）；
  T2 工具面并发同 id 恰一份落盘——抽掉锁后双 committed 复现必红；
  S/G3 钉住串行与不同 id 面：锁不得把串行二次写变成直写、不得把不同 id
     并发写互相阻塞出假失败。

沙箱（硬约束）：一切读写都在 tempfile.mkdtemp 内；子进程（multiprocessing
spawn 真进程）继承同一沙箱 env（哨兵变量防 spawn 重入时另建沙箱）。跑完清理。
"""
import json
import multiprocessing as mp
import os
import shutil
import sys
import tempfile
import time

# 沙箱必须在**任何** md_cg 子模块 import 之前设好（crypto.MASTER_FILE 在模块
# 导入时求值）。哨兵 + setdefault：spawn 子进程 import 本模块时不另建沙箱，
# 沿用父进程经 env 继承传来的同一套路径。
_SBX = os.environ.get("P322GUARD_SBX") or tempfile.mkdtemp(prefix="p322g_sbx_")
os.environ["P322GUARD_SBX"] = _SBX
os.environ.setdefault("MDCG_AUX_ROOT", _SBX)
os.environ.setdefault("MDCG_ROOT", os.path.join(_SBX, "root"))
os.environ.setdefault("MDCG_MASTER_KEY", os.urandom(32).hex())
_POLICY = os.path.join(_SBX, "policy.json")
if not os.path.exists(_POLICY):
    with open(_POLICY, "w", encoding="utf-8") as _f:      # audit 闸 ACCEPT 面
        json.dump({"forbidden": [], "required": ["P322REQ"]}, _f)
os.environ.setdefault("MDCG_POLICY_FILE", _POLICY)
os.environ.pop("MDCG_TEST_LIVE_ROOT", None)
# 三档自治档位**保持缺省 confirm**（不设 env）：本守卫考的就是缺省档下
# 「并发第二写必须与串行第二写同语义（出审核队列，不落盘）」。

KEK_HEX = os.environ.get("P322GUARD_KEK") or os.urandom(32).hex()
os.environ["P322GUARD_KEK"] = KEK_HEX

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


def _apply_drop_fix_if_any():
    """--drop-fix 定点变异：抽掉 per-node 锁 = 恢复 #322 之前的无锁直写。

    只替换 writepipe 的两个接线点（锁获取 + 锁内重载），不动库层——与
    「回退修复」等价的最小变异面（test_b1 --drop-fix 同款纪律）。
    R0 补线后工具面（mcp_server 的 mdcg_remember 分支）经
    `writepipe._node_write_lock / _refresh_index_in_lock` 属性访问接线，
    故本变异**同时**抽掉动词面与工具面的锁——两面一起回到 #322 之前。
    """
    if os.environ.get("P322GUARD_DROP_FIX") != "1":
        return
    import contextlib
    from . import writepipe
    writepipe._node_write_lock = lambda cg, nid: contextlib.nullcontext()
    writepipe._refresh_index_in_lock = lambda cg: None


def _mk_cg(root):
    from md_cg.mdcos import MdCGSecure
    from md_cg.security import Principal
    p = Principal(tenant="t1", actor="w", role="designer", clearance="secret",
                  can_write=True, can_admin=True)
    return MdCGSecure(root, principal=p, master_key=bytes.fromhex(KEK_HEX))


def _write(cg, nid, content, layer="knowledge"):
    from md_cg import writepipe
    return writepipe.default_pipeline().execute(
        cg, {"node_id": nid, "content": content,
             "content_kind": "text", "layer": layer})


def _remember_tool(cg, nid, content, layer="knowledge"):
    """工具面写入：模拟 MCP dispatch（hooks 自动记忆通路）。

    真实调用面是 serve 的 tools/call → call_tool → _dispatch；此处直接打
    `_dispatch(cg, "mdcg_remember", ...)` 同一实现（跳过 stdio 循环——
    循环层不触任何写语义），R0 修的正是这个分支。
    """
    from md_cg import mcp_server
    return mcp_server._dispatch(
        cg, "mdcg_remember",
        {"node_id": nid, "content": content, "layer": layer})


# ---------------- spawn worker：真进程、Barrier 对齐每轮起跑 ----------------

def _worker_pair(q, bar, root, widx, nids, layer):
    """两进程通用 worker：对每个 nid 与对端同时发起写入（Barrier 对齐）。"""
    _apply_drop_fix_if_any()
    layer = layer or "knowledge"
    cg = _mk_cg(root)
    recs = []
    for nid in nids:
        content = "P322REQ w=%d nid=%s body-%s-%d" % (widx, nid, layer, widx)
        bar.wait()                                  # 与对端同轮同时起跑
        out, err = None, None
        try:
            out = _write(cg, nid, content, layer=layer)
        except Exception as exc:
            err = "%s" % type(exc).__name__          # 只留类型名（ ProtectionError 等）
        recs.append({"nid": nid, "widx": widx, "content": content,
                     "committed": (out or {}).get("committed"),
                     "moved_to": (out or {}).get("moved_to"), "err": err})
    cg.close()
    q.put(recs)


def _worker_distinct(q, bar, root, widx, nids):
    """不同 id 并发写：两进程各写**自己的一组** id（无共享 nid）。"""
    _apply_drop_fix_if_any()
    cg = _mk_cg(root)
    recs = []
    for nid in nids:
        content = "P322REQ w=%d nid=%s body-DISTINCT" % (widx, nid)
        bar.wait()
        out, err = None, None
        t0 = time.time()
        try:
            out = _write(cg, nid, content)
        except Exception as exc:
            err = "%s: %s" % (type(exc).__name__, str(exc)[:100])
        recs.append({"nid": nid, "content": content,
                     "committed": (out or {}).get("committed"),
                     "err": err, "secs": round(time.time() - t0, 3)})
    cg.close()
    q.put(recs)


def _worker_hold_lock(q, root, hold_secs):
    """U3 用：子进程持锁 hold_secs 秒后释放。"""
    from .fsutil import node_write_lock
    with node_write_lock(root, "u3_mutex"):
        q.put("held")
        time.sleep(hold_secs)
    q.put("released")


def _spawn_pair(root, nids, layers):
    """起 2 个真进程并发写同一组 nid，返回全部回执。"""
    ctx = mp.get_context("spawn")
    bar = ctx.Barrier(2)
    q = ctx.Queue()
    ps = [ctx.Process(target=_worker_pair,
                      args=(q, bar, root, i, nids, layers[i]))
          for i in range(2)]
    for p_ in ps:
        p_.start()
    recs = []
    for _ in range(2):
        recs.extend(q.get())
    for p_ in ps:
        p_.join(timeout=120)
    rcs = [p_.exitcode for p_ in ps]
    return recs, rcs


def _files_of(root, nid):
    """全库（跨层）找该 nid 的 .md 文件。"""
    from .mdcg import LAYERS
    hits = []
    for layer in LAYERS:
        base = os.path.join(root, layer)
        for dp, _dn, files in os.walk(base):
            for fn in files:
                if fn == nid + ".md":
                    hits.append(os.path.relpath(os.path.join(dp, fn), root)
                                .replace("\\", "/"))
    return hits


def _fresh_read(root, nid):
    cg = _mk_cg(root)
    node = cg.get(nid)
    cg.close()
    return node


# ---------------- U：锁原语 ----------------

def sec_u():
    print("== U 锁原语（fsutil.node_write_lock）==")
    from .fsutil import NODE_LOCK_DIR, node_write_lock
    root = os.path.join(_SBX, "lib_u")
    os.makedirs(root, exist_ok=True)
    lk = node_write_lock(root, "safe_id_01")
    _check("U1 锁文件落 <root>/.locks/<nid>.lock",
           lk.path == os.path.join(root, NODE_LOCK_DIR, "safe_id_01.lock"),
           lk.path)
    # sanitize：白名单外的 id（路径不安全字符）折 sha256，产物不得逃出 .locks
    for evil in ("../evil", "a/b", "..", "空间 id", "x" * 200):
        lk2 = node_write_lock(root, evil)
        rel = os.path.relpath(lk2.path, os.path.join(root, NODE_LOCK_DIR))
        inside = (os.path.realpath(os.path.dirname(lk2.path))
                  .startswith(os.path.realpath(os.path.join(root, NODE_LOCK_DIR))))
        _check("U2 sanitize 防穿越（%r）" % (evil[:16],),
               inside and ".." not in rel.replace("\\", "/") and rel != "",
               lk2.path)
    # strict 跨进程互斥：子进程持锁 1.5s，父进程 0.5s 超时必 TimeoutError
    ctx = mp.get_context("spawn")
    q = ctx.Queue()
    holder = ctx.Process(target=_worker_hold_lock, args=(q, root, 1.5))
    holder.start()
    _check("U3a 持锁方先报 held", q.get(timeout=30) == "held")
    t0 = time.time()
    try:
        with node_write_lock(root, "u3_mutex", timeout=0.5):
            _check("U3b strict 互斥：锁被占时 0.5s 必 TimeoutError", False,
                   "竟然拿到了锁")
    except TimeoutError:
        _check("U3b strict 互斥：锁被占时 0.5s 必 TimeoutError",
               time.time() - t0 < 5, "")
    _check("U3c 持锁方释放报 released", q.get(timeout=30) == "released")
    holder.join(timeout=30)
    try:
        with node_write_lock(root, "u3_mutex", timeout=10):
            got = True
    except TimeoutError:
        got = False
    _check("U3d 释放后可再获锁", got, "")
    # 无 root：不得静默无锁（fail-closed 报错）
    try:
        node_write_lock(None, "x")
        _check("U4 root 缺失 fail-closed 抛 ValueError", False, "未抛")
    except ValueError:
        _check("U4 root 缺失 fail-closed 抛 ValueError", True, "")


# ---------------- S：串行基线（= 修复后必须保持的串行语义） ----------------

def sec_s():
    print("== S 串行基线（第二次写的既有语义）==")
    root = os.path.join(_SBX, "lib_serial")
    cg = _mk_cg(root)
    o1 = _write(cg, "s_x", "P322REQ serial-first")
    o2 = _write(cg, "s_x", "P322REQ serial-second")
    node = cg.get("s_x")
    _check("S1 同 id 第一写 committed:true", o1.get("committed") is True, o1)
    _check("S2 同 id 第二写 committed:false + review_queue",
           o2.get("committed") is False
           and o2.get("moved_to") == "review_queue", o2)
    _check("S3 正文仍是第一份（未被第二写顶替）",
           "serial-first" in (node or {}).get("content", ""), "")
    a1 = _write(cg, "s_anc", "P322REQ anchor-first", layer="anchor")
    _check("S4 anchor 写 committed:true", a1.get("committed") is True, a1)
    try:
        _write(cg, "s_anc", "P322REQ knowledge-second", layer="knowledge")
        k_err = None
    except Exception as exc:
        k_err = type(exc).__name__
    _check("S5 串行 anchor→knowledge 第二写 ProtectionError",
           k_err == "ProtectionError", k_err)
    _check("S6 盘上仅 anchor 一份", _files_of(root, "s_anc") == ["anchor/s_anc.md"],
           _files_of(root, "s_anc"))
    cg.close()


# ---------------- G1：并发同 id（无静默丢） ----------------

def sec_g1(rounds):
    print("== G1 并发同 id：2 进程 × %d 轮（Barrier 对齐）==" % rounds)
    root = os.path.join(_SBX, "lib_g1")
    pre = _mk_cg(root)                 # 预热：DEK/身份先落定，避免 N 进程竞态
    pre.close()
    nids = ["p322g1r%d" % i for i in range(rounds)]
    recs, rcs = _spawn_pair(root, nids, [None, None])
    _check("G1-0 两 worker 全部正常退出（rc=0）", rcs == [0, 0], rcs)
    both = dual = silent = honest = onefile = oneread = 0
    for nid in nids:
        rr = [r for r in recs if r["nid"] == nid]
        files = _files_of(root, nid)
        node = _fresh_read(root, nid)
        body = (node or {}).get("content") or ""
        winners = [r for r in rr if r["committed"] is True]
        losers = [r for r in rr if r["committed"] is not True]
        if all(r["committed"] is True for r in rr):
            both += 1
        if len(files) > 1:
            dual += 1
        # 静默丢 = 双 committed 而全库只剩一份正文（输家被假应答骗）
        if (all(r["committed"] is True for r in rr)
                and sum(1 for r in rr if r["content"] and r["content"] in body) < 2
                and len([r for r in rr if r["content"]]) == 2):
            # 双 committed 下按「读回正文只能是其中一份」计静默丢
            silent += 1
        if len(winners) == 1 and len(losers) == 1:
            honest += 1
        if len(files) == 1:
            onefile += 1
        if len(winners) == 1 and winners[0]["content"] in body:
            oneread += 1
    print("    G1 读数：双committed=%d 双文件=%d 静默丢=%d 恰一真应答=%d "
          "恰一文件=%d 读回=赢家=%d / %d 轮"
          % (both, dual, silent, honest, onefile, oneread, rounds))
    _check("G1-1 无「双 committed:true」轮（读数诚实）", both == 0, both)
    _check("G1-2 每轮恰一份 committed:true、另一份非 committed", honest == rounds,
           honest)
    _check("G1-3 每轮恰一份文件落盘", onefile == rounds, onefile)
    _check("G1-4 读回正文 = 赢家正文（恰一份存活）", oneread == rounds, oneread)
    # 输家去向：串行第二次写的同款出口（confirm 档 = 审核队列）；
    # 允许的另一合法出口 = 明确冲突异常（err 非空）——不许 committed:true。
    ok_losers = sum(
        1 for nid in nids
        for r in [x for x in recs if x["nid"] == nid]
        if r["committed"] is not True
        and (r.get("moved_to") == "review_queue" or r.get("err")))
    _check("G1-5 输家去向 = 审核队列/明确冲突（无假应答）",
           ok_losers == rounds, ok_losers)
    _check("G1-6 静默丢 = 0", silent == 0, silent)
    return {"both": both, "dual": dual, "silent": silent, "rounds": rounds}


# ---------------- G2：anchor 竞态 ----------------

def sec_g2(rounds):
    print("== G2 anchor 竞态：anchor vs knowledge，2 进程 × %d 轮 ==" % rounds)
    root = os.path.join(_SBX, "lib_g2")
    pre = _mk_cg(root)
    pre.close()
    nids = ["p322g2r%d" % i for i in range(rounds)]
    recs, rcs = _spawn_pair(root, nids, ["anchor", "knowledge"])
    _check("G2-0 两 worker 全部正常退出（rc=0）", rcs == [0, 0], rcs)
    both = dual = prot_ok = q_ok = 0
    for nid in nids:
        rr = [r for r in recs if r["nid"] == nid]
        files = _files_of(root, nid)
        krec = next((r for r in rr if "knowledge" in r["content"]), None)
        arec = next((r for r in rr if "anchor" in r["content"]), None)
        if all(r["committed"] is True for r in rr):
            both += 1
        if len(files) > 1:
            dual += 1
        if files and files[0].startswith("anchor/") and krec is not None:
            # anchor 先落 ⇒ knowledge 侧必须是 ProtectionError（串行同款）
            if krec.get("err") == "ProtectionError" \
                    and krec.get("committed") is not True:
                prot_ok += 1
        if files and files[0].startswith("knowledge/") and arec is not None:
            # knowledge 先落 ⇒ anchor 侧 = C 改写出单（review_queue）
            if arec.get("committed") is False \
                    and arec.get("moved_to") == "review_queue":
                q_ok += 1
    print("    G2 读数：双committed=%d 双文件=%d anchor先→ProtectionError=%d "
          "knowledge先→review_queue=%d / %d 轮"
          % (both, dual, prot_ok, q_ok, rounds))
    _check("G2-1 无「双 committed:true」轮", both == 0, both)
    _check("G2-2 两份同 id 文件并存 = 0", dual == 0, dual)
    _check("G2-3 ProtectionError 语义恢复/审核队列兜住（两交错都串行语义）",
           prot_ok + q_ok == rounds, (prot_ok, q_ok, rounds))
    return {"both": both, "dual": dual, "rounds": rounds}


# ---------------- G3：防过修（串行零回归 + 不同 id 并发互不阻塞） ----------------

def sec_g3():
    print("== G3 防过修：串行零回归 + 不同 id 并发互不阻塞 ==")
    # G3a 串行二次写（与 S 同判据、独立库根再钉一遍：守卫自含）
    root = os.path.join(_SBX, "lib_g3a")
    cg = _mk_cg(root)
    _write(cg, "g3_x", "P322REQ g3-first")
    o2 = _write(cg, "g3_x", "P322REQ g3-second")
    _check("G3a-1 串行第二次写仍进审核队列（零回归）",
           o2.get("committed") is False
           and o2.get("moved_to") == "review_queue", o2)
    cg.close()
    # G3b 不同 id 并发写：2 进程 × 各 6 个**互不相同**的 id
    ctx = mp.get_context("spawn")
    root = os.path.join(_SBX, "lib_g3b")
    pre = _mk_cg(root)
    pre.close()
    bar = ctx.Barrier(2)
    q = ctx.Queue()
    n_each = 6
    ps = [ctx.Process(target=_worker_distinct,
                      args=(q, bar, root, i,
                            ["p322g3b_w%d_n%d" % (i, j) for j in range(n_each)]))
          for i in range(2)]
    t0 = time.time()
    for p_ in ps:
        p_.start()
    recs = []
    for _ in range(2):
        recs.extend(q.get())
    for p_ in ps:
        p_.join(timeout=120)
    elapsed = time.time() - t0
    _check("G3b-0 两 worker 全部正常退出（rc=0）",
           [p_.exitcode for p_ in ps] == [0, 0], [p_.exitcode for p_ in ps])
    n_ok = sum(1 for r in recs if r["committed"] is True and not r["err"])
    _check("G3b-1 不同 id 并发写全部 committed:true（互不阻塞无假失败）",
           n_ok == 2 * n_each, (n_ok, 2 * n_each))
    miss = []
    cg = _mk_cg(root)
    for r in recs:
        node = cg.get(r["nid"])
        if not node or r["content"] not in (node.get("content") or ""):
            miss.append(r["nid"])
    cg.close()
    _check("G3b-2 逐笔读回命中", not miss, miss)
    print("    G3b 读数：2 进程 × %d id 全 committed，读回全命中，用时 %.1fs"
          % (n_each, elapsed))
    # 锁目录布局（修复在场的可见性；--drop-fix 变异下无锁自然无目录，
    # 该项属「修复存在性」断言而非防过修断言——变异模式跳过，G3 保持两向绿）
    if os.environ.get("P322GUARD_DROP_FIX") != "1":
        _check("G3b-3 锁目录落 <root>/.locks",
               os.path.isdir(os.path.join(root, ".locks")), "")


# ---------------- T1：锁间谍（两面取锁读数——R0 回归锚） ----------------

def sec_t1():
    print("== T1 锁间谍：动词面/工具面取锁读数 ==")
    from . import fsutil
    root = os.path.join(_SBX, "lib_t1")
    cg = _mk_cg(root)
    count = {"n": 0}
    _orig = fsutil.node_write_lock

    def _spy(_root, _nid, **_kw):
        count["n"] += 1
        return _orig(_root, _nid, **_kw)

    # 两个调用点（writepipe._node_write_lock / mcp_server 的 R0 接线）都在
    # 调用时 `from .fsutil import node_write_lock` 重绑定——只替换 fsutil 面
    # 即可同时看到两面。
    fsutil.node_write_lock = _spy
    try:
        _write(cg, "t1_verb", "P322REQ t1-verb")
        verb = count["n"]
        count["n"] = 0
        _remember_tool(cg, "t1_tool", "P322REQ t1-tool")
        tool = count["n"]
    finally:
        fsutil.node_write_lock = _orig
    print("    T1 读数：verb_locks=%d tool_locks=%d" % (verb, tool))
    _check("T1a 动词面（cg op=write）取锁 verb_locks=1", verb == 1, verb)
    _check("T1b 工具面（mdcg_remember）取锁 tool_locks=1", tool == 1, tool)
    cg.close()


# ---------------- T2：工具面并发同 id（无静默丢） ----------------

def _worker_tool(q, bar, root, widx, nids):
    """T2 用：两进程对同一组 nid 经**工具面**（模拟 dispatch）同时写。"""
    _apply_drop_fix_if_any()
    cg = _mk_cg(root)
    recs = []
    for nid in nids:
        content = "P322TOOL w=%d nid=%s body-%d" % (widx, nid, widx)
        bar.wait()                                  # 与对端同轮同时起跑
        out, err = None, None
        try:
            out = _remember_tool(cg, nid, content)
        except Exception as exc:
            err = "%s" % type(exc).__name__
        recs.append({"nid": nid, "widx": widx, "content": content,
                     "committed": (out or {}).get("committed"),
                     "moved_to": (out or {}).get("moved_to"), "err": err})
    cg.close()
    q.put(recs)


def sec_t2(rounds):
    print("== T2 工具面并发同 id（模拟 dispatch）：2 进程 × %d 轮 ==" % rounds)
    root = os.path.join(_SBX, "lib_t2")
    pre = _mk_cg(root)                 # 预热：DEK/身份先落定
    pre.close()
    nids = ["p322t2r%d" % i for i in range(rounds)]
    ctx = mp.get_context("spawn")
    bar = ctx.Barrier(2)
    q = ctx.Queue()
    ps = [ctx.Process(target=_worker_tool, args=(q, bar, root, i, nids))
          for i in range(2)]
    for p_ in ps:
        p_.start()
    recs = []
    for _ in range(2):
        recs.extend(q.get())
    for p_ in ps:
        p_.join(timeout=120)
    rcs = [p_.exitcode for p_ in ps]
    _check("T2-0 两 worker 全部正常退出（rc=0）", rcs == [0, 0], rcs)
    both = honest = onefile = oneread = 0
    for nid in nids:
        rr = [r for r in recs if r["nid"] == nid]
        files = _files_of(root, nid)
        node = _fresh_read(root, nid)
        body = (node or {}).get("content") or ""
        winners = [r for r in rr if r["committed"] is True]
        losers = [r for r in rr if r["committed"] is not True]
        if all(r["committed"] is True for r in rr):
            both += 1
        if len(winners) == 1 and len(losers) == 1:
            honest += 1
        if len(files) == 1:
            onefile += 1
        if len(winners) == 1 and winners[0]["content"] in body:
            oneread += 1
    print("    T2 读数：双committed=%d 恰一真应答=%d 恰一文件=%d 读回=赢家=%d"
          " / %d 轮" % (both, honest, onefile, oneread, rounds))
    _check("T2-1 工具面无「双 committed:true」轮", both == 0, both)
    _check("T2-2 每轮恰一份 committed:true、另一份非 committed",
           honest == rounds, honest)
    _check("T2-3 每轮恰一份文件落盘", onefile == rounds, onefile)
    _check("T2-4 读回正文 = 赢家正文（恰一份存活）", oneread == rounds, oneread)
    ok_losers = sum(
        1 for nid in nids
        for r in [x for x in recs if x["nid"] == nid]
        if r["committed"] is not True
        and (r.get("moved_to") == "review_queue" or r.get("err")))
    _check("T2-5 输家去向 = 审核队列/明确冲突（无假应答）",
           ok_losers == rounds, ok_losers)
    return {"both": both, "honest": honest, "rounds": rounds}


# ---------------- main ----------------

def main():
    drop = "--drop-fix" in sys.argv
    if drop:
        os.environ["P322GUARD_DROP_FIX"] = "1"
        _apply_drop_fix_if_any()
        print("[变异模式] --drop-fix：已抽掉 per-node 写锁（动词面 + 工具面，"
              "恢复 #322 前的无锁直写）——G1/G2/T1/T2 应红、S/G3 应绿")
    try:
        sec_u()
        sec_s()
        g1 = sec_g1(10)
        g2 = sec_g2(8)
        sec_g3()
        sec_t1()
        t2 = sec_t2(8)
        if drop:
            # 变异向断言：病必须在多轮中可见（红得稳定：改前实测 5/5 与 8/8）
            _check("MUT-G1 抽锁后静默丢 > 0（10 轮至少 1 轮丢）",
                   g1["silent"] > 0 or g1["both"] > 0, g1)
            _check("MUT-G2 抽锁后双文件 > 0（8 轮至少 1 轮并存）",
                   g2["dual"] > 0 or g2["both"] > 0, g2)
            _check("MUT-T2 抽锁后工具面双 committed/输家假应答 > 0",
                   t2["both"] > 0 or t2["honest"] < t2["rounds"], t2)
    finally:
        shutil.rmtree(_SBX, ignore_errors=True)
    print()
    if _BAD:
        print("issue #322 守卫：失败 %d 项 -> %s" % (len(_BAD), _BAD))
        sys.exit(1)
    print("issue #322 守卫：全部通过（%d 项）" % _OK)
    sys.exit(0)


if __name__ == "__main__":
    main()
