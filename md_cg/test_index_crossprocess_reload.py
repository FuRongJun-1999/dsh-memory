# -*- coding: utf-8 -*-
"""md_cg · 常驻进程索引跨进程重载守卫（P1b-2 读面缓存代际，DSH 端在役复验）

缺陷（修复前）：`MdCG.__init__` 仅启动时 `self.index = self._load_index()`
一次（mdcg.py），此后 read/get/search 全走内存态——其它进程（review_cli
autoflush=1）写盘对常驻进程不可见。复验证据链（dsh_restart_recheck_20260926，
时间戳锁死）：22:13:16 常驻进程装载快照(14135 节点) → 22:14:37 review_cli
写入 → 22:14:43 磁盘 _index.json 已含探针 → 同常驻进程 read 仍 null、旁路
新进程可读。

修复：__init__ 记录 _index.json 签名 (st_mtime_ns, st_size)；读路径入口
（get / search（基类与 MdCGOS）/ search_rrf（热缓存查询之前）/ list_goals）
单点调 _maybe_reload_index()——签名变化才重载（一次 stat 微秒级）；自身
flush 只追加 _index_log 分片不改 _index.json（签名不变正合适）、compact/
rebuild 写快照后主动刷签名（自写不自载）；maintain action=reload 显式探活。

守卫（六组，全部临时库 + 哑主密钥，绝不触真实 ~/.mdcg）：
  ① 红转绿（同解释器双实例，复刻 DSH 形态）：A 建库常驻 → B 独立实例
    add+close（compact 落快照=review_cli 退出同款）→ 盘面快照已含探针 →
    A 禁用 reload 时 read null（修前病灶形态）→ 恢复后 read/search 命中
    （修复生效）→ C 实例 forget+close → A read 归 null（tombstone 重放）。
  ② 旁路新进程可读（subprocess 全新解释器 _load_index+read）——修前已绿，
    钉住「盘面账本正确」，防两层兜底（批次39 指纹自愈）未来被移除时复发。
  ③ 自身写入零重载：A' 写入+flush+compact+rebuild 全程真实重载次数 0
    （自写不自载循环防线）；连续读 N 次=签名探测 N 次、重载 0 次。
  ④ maintain reload 动作在位：MAINTAIN_ACTIONS 登记 + {"reloaded": bool}
    返回（他进程写入后 True 且读面可见；幂等二调 False）。
  ⑤ goal=list 链路跨进程可见（list_goals 接线腿，active_goals 同源）。
  ⑥ 性能粗测：无跨进程写入时接线态 vs 重载桩空转态逐读耗时对照（宽松
    上界断言防「重载被改成无条件」的性能回归；绝对数字只打印不作硬门）。

如实边界：② 在修复前的 HEAD 上已绿（旁路进程本就走全新 _load_index）；
修复前红的正是 ① 的常驻读面——本守卫以「禁用 reload → null」复现该形态，
并以 ③ 的计数桩钉住接线与自写不自载两道防线。

运行：python -m md_cg.test_index_crossprocess_reload
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import time

from .mdcos import MdCGSecure
from .security import Principal

PASS = FAIL = 0
FAILS = []

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

DUMMY_KEY = "ab" * 32          # 哑主密钥：本进程与子进程绝不触真实 ~/.mdcg

READ_CHILD = r'''
import sys
sys.path.insert(0, sys.argv[2])
from md_cg.mdcos import MdCGSecure
from md_cg.security import Principal
p = Principal(actor="p1b2-reader", clearance="internal", can_write=True,
              can_admin=True, role="designer", auth_mode="test")
cg = MdCGSecure(sys.argv[1], principal=p)
try:
    print("READ " + " ".join("1" if cg.get(nid) is not None else "0"
                             for nid in sys.argv[3].split(",")))
finally:
    cg.close()
'''


def check(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  [PASS] {name}" + (f"  · {detail}" if detail else ""))
    else:
        FAIL += 1
        FAILS.append(name)
        print(f"  [FAIL] {name}  · {detail}")


def _principal(**kw):
    d = dict(actor="p1b2", clearance="internal", can_write=True,
             can_admin=True, role="designer", auth_mode="test")
    d.update(kw)
    return Principal(**d)


def _spawn_read(root, ids):
    """独立子进程全新 _load_index + read（旁路读面）。"""
    env = dict(os.environ)
    env["MDCG_MASTER_KEY"] = DUMMY_KEY
    env["PYTHONUTF8"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONPATH"] = REPO + os.pathsep + env.get("PYTHONPATH", "")
    return subprocess.run(
        [sys.executable, "-X", "utf8", "-c", READ_CHILD, root, REPO, ids],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        env=env, cwd=REPO)


def _snapshot_ids(root):
    """盘面 _index.json 的节点 id 集（复验证据链 22:14:43 的观察点）。"""
    p = os.path.join(root, "_index.json")
    if not os.path.exists(p):
        return None
    with open(p, encoding="utf-8") as f:
        return set(json.load(f).get("nodes") or {})


def _counting(cg):
    """给 _maybe_reload_index 挂计数桩，返回 (计数 dict, 解挂函数)。"""
    calls = {"probe": 0, "reload": 0}
    orig = cg._maybe_reload_index

    def counted():
        calls["probe"] += 1
        r = orig()
        if r:
            calls["reload"] += 1
        return r

    cg._maybe_reload_index = counted
    return calls, (lambda: setattr(cg, "_maybe_reload_index", orig))


def main():
    roots = []
    # 纪律：哑主密钥先行——进程内任何 MdCGSecure 构造都不得触真实
    # ~/.mdcg/master.key（_init_crypto 的 env 回落链，mdcos.py）。
    os.environ["MDCG_MASTER_KEY"] = DUMMY_KEY
    try:
        # ---------- ① 红转绿：常驻 A + 独立写方 B（DSH 形态复刻） ----------
        print("\n【①】常驻 A 建库 → 独立 B add+close（compact 落快照）→ 红转绿")
        root1 = tempfile.mkdtemp(prefix="p1b2_1_")
        roots.append(root1)
        a = MdCGSecure(root1, principal=_principal())
        a.add("seed_node_1", "# 功能名：种子节点\n# 正文：常驻 A 的初始记忆",
              layer="knowledge")
        a.flush()                      # 只追加 _index_log 分片，不动 _index.json
        check("A 自身 flush 不改 _index.json 签名（分片追加不改快照）",
              a._index_sig == a._index_signature())
        b = MdCGSecure(root1, principal=_principal(actor="writer_b"))
        b.add("reload_probe_1", "# 功能名：跨进程探针\n# 正文：B 写入的探针节点",
              layer="knowledge")
        b.close()                      # close → compact：写 _index.json（review_cli 退出同款）
        ids = _snapshot_ids(root1)
        check("盘面 _index.json 已含 B 的探针（复验证据链 22:14:43 形态）",
              ids is not None and "reload_probe_1" in ids,
              "snapshot_ids=%s" % (sorted(ids or [])[:8]))
        # 红形态：修前无 _maybe_reload_index → 常驻 A 读不到
        orig_reload = a._maybe_reload_index
        a._maybe_reload_index = lambda: False
        red = a.get("reload_probe_1")
        a._maybe_reload_index = orig_reload
        check("红（修前病灶形态）：禁用 reload 时常驻 A read 探针 null",
              red is None, repr(red)[:80])
        fired = a._maybe_reload_index()
        check("绿：_maybe_reload_index 签名变化触发重载", fired is True)
        green = a.get("reload_probe_1")
        check("绿：常驻 A read 探针命中", green is not None,
              repr(green)[:80])
        res, _meta = a.search("跨进程探针")
        check("绿：常驻 A search（route/read 链路）命中探针",
              any(n.get("id") == "reload_probe_1" for n, _s, _q in res),
              str([n.get("id") for n, _s, _q in res])[:120])
        # 删除可见性：C 实例 forget → tombstone 经重放对 A 生效
        c = MdCGSecure(root1, principal=_principal(actor="writer_c"))
        fr = c.forget("reload_probe_1", reason="P1b-2 tombstone 腿")
        c.close()
        check("C forget 成功（ok=True）", isinstance(fr, dict) and fr.get("ok"),
              str(fr)[:80])
        check("绿：常驻 A read 已删节点归 null（tombstone 重放）",
              a.get("reload_probe_1") is None)
        a.close()

        # ---------- ② 旁路新进程可读（修前已绿，钉住盘面账本） ----------
        print("\n【②】旁路全新子进程 read（_load_index 直读盘面）")
        root2 = tempfile.mkdtemp(prefix="p1b2_2_")
        roots.append(root2)
        w = MdCGSecure(root2, principal=_principal(actor="writer_2"))
        w.add("bypass_probe", "# 功能名：旁路探针\n# 正文：新进程应立即可见",
              layer="knowledge")
        w.close()
        r2 = _spawn_read(root2, "bypass_probe,missing_node")
        line = (r2.stdout or "").strip().splitlines()[-1] if (r2.stdout or "").strip() else ""
        check("旁路新进程 read：探针 1 / 缺失 0（READ 1 0）",
              line == "READ 1 0",
              "stdout=%r stderr=%r" % ((r2.stdout or "")[:80], (r2.stderr or "")[:200]))

        # ---------- ③ 自身写入零重载 + 自写不自载 ----------
        print("\n【③】自身写入/flush/compact/rebuild 全程零真实重载")
        root3 = tempfile.mkdtemp(prefix="p1b2_3_")
        roots.append(root3)
        a2 = MdCGSecure(root3, principal=_principal())
        a2.add("own_seed", "# 功能名：自有种子\n# 正文：own seed", layer="knowledge")
        a2.flush()
        calls, uncount = _counting(a2)
        for i in range(3):
            a2.add("own_%d" % i, "# 功能名：自写%d\n# 正文：own write %d" % (i, i),
                   layer="knowledge")
        a2.flush()
        for i in range(3):
            a2.get("own_%d" % i)
        a2.search("自写")
        a2.list_goals()
        check("自身写入+flush+读全程：重载 0 次（写路径不接、flush 不改签名）",
              calls["reload"] == 0, str(calls))
        check("接线在位：读路径确经签名探测（3×get+1×search+1×list_goals=5 次）",
              calls["probe"] >= 5, str(calls))
        a2.compact_index()
        check("compact 后签名已主动刷新（自写不自载前提）",
              a2._index_sig == a2._index_signature())
        a2.get("own_0")
        a2.rebuild_index()
        a2.get("own_0")
        check("compact/rebuild 后紧接读：重载仍 0 次", calls["reload"] == 0,
              str(calls))
        uncount()
        a2.close()

        # ---------- ④ maintain reload 动作 ----------
        print("\n【④】maintain action=reload 显式探活")
        from .mdcos import MdCGOS
        check('"reload" 已登记 MAINTAIN_ACTIONS', "reload" in MdCGOS.MAINTAIN_ACTIONS,
              str(MdCGOS.MAINTAIN_ACTIONS))
        a3 = MdCGSecure(root3, principal=_principal())
        out0 = a3.maintain(action="reload")
        check("幂等：签名未变时 reloaded=False",
              isinstance(out0, dict) and out0.get("reloaded") is False,
              str(out0)[:120])
        bw = MdCGSecure(root3, principal=_principal(actor="writer_4"))
        bw.add("maintain_probe", "# 功能名：维护探针\n# 正文：maintain reload 腿",
               layer="knowledge")
        bw.close()
        out1 = a3.maintain(action="reload")
        check("他进程写快照后 maintain reload 返回 reloaded=True",
              isinstance(out1, dict) and out1.get("reloaded") is True,
              str(out1)[:120])
        check("探活后读面立即可见新节点", a3.get("maintain_probe") is not None)
        a3.close()

        # ---------- ⑤ goal=list 链路（list_goals 接线腿） ----------
        print("\n【⑤】goal 跨进程可见（list_goals / active_goals）")
        root4 = tempfile.mkdtemp(prefix="p1b2_4_")
        roots.append(root4)
        a4 = MdCGSecure(root4, principal=_principal())
        check("常驻 A' 初始无目标", a4.list_goals() == [])
        gw = MdCGSecure(root4, principal=_principal(actor="writer_5"))
        gid = gw.add_goal("跨进程目标探针：P1b-2 list_goals 接线腿", priority=0.9)
        gw.close()
        gl = a4.list_goals()
        check("goal=list 经 list_goals 重载后可见",
              any(g.get("id") == gid for g in gl),
              str([g.get("id") for g in gl])[:120])
        ag = a4.active_goals()
        check("active_goals 同源可见",
              any(g.get("id") == gid for g in ag))
        a4.close()

        # ---------- ⑥ 性能粗测：无跨进程写入时逐读开销 ----------
        print("\n【⑥】性能粗测（无跨进程写入，接线态 vs 重载桩空转态）")
        N = 300
        a2c = MdCGSecure(root3, principal=_principal())
        for _ in range(5):
            a2c.get("own_0")
        t0 = time.perf_counter()
        for _ in range(N):
            a2c.get("own_0")
        t_on = (time.perf_counter() - t0) / N * 1e6
        orig = a2c._maybe_reload_index
        a2c._maybe_reload_index = lambda: False
        for _ in range(5):
            a2c.get("own_0")
        t0 = time.perf_counter()
        for _ in range(N):
            a2c.get("own_0")
        t_off = (time.perf_counter() - t0) / N * 1e6
        a2c._maybe_reload_index = orig
        a2c.close()
        print("       接线态 %.1f µs/读 · 桩空转态 %.1f µs/读 · 增幅 %.1f%%"
              % (t_on, t_off, (t_on - t_off) / max(t_off, 1e-9) * 100))
        check("性能上界：接线态 ≤ 桩空转态×3 + 30µs（stat 微秒级；宽松防抖）",
              t_on <= t_off * 3 + 30.0,
              "on=%.1f off=%.1f" % (t_on, t_off))
    finally:
        for r_ in roots:
            shutil.rmtree(r_, ignore_errors=True)

    print("\n" + "=" * 64)
    print(f"PASS={PASS}  FAIL={FAIL}")
    if FAILS:
        print("失败项：" + "；".join(FAILS))
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
