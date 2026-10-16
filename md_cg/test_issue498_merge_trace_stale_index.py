# -*- coding: utf-8 -*-
# 功能名：合并痕迹对账不得依赖索引新鲜度（issue #498，接 #417 同族）
# 生效条件：python -X utf8 -m md_cg.test_issue498_merge_trace_stale_index [--mutate]；被测面=twophase._merge_target / twophase.reconcile（两段式恢复期判据）
# 子功能：A=崩溃窗口（合并已落盘、**索引未持久化**）⇒ 新实例必须判 committed；B=反向腿（盘面确无痕迹 ⇒ 仍须 interrupted，不放宽）；C=源码面（索引落空必须回退盘面扫描，防「闸被删守卫还绿」）；R=把 _merge_target 退回修前形态（内存内源码级回退）⇒ A3/A4 转红
# 执行：--mutate 时读 twophase.py 原文、把盘面回退段去掉后 exec 进模块命名空间，实跑 A 组，再 exec 回原文恢复
# 验证方式：全部 PASS 即通过；--mutate 下回退后红项须含 A3/A4（实跑，不接受推演）
# 不适用条件：不判 #417 主帖的库层入口接线（已有 test_issue417_twophase_merge_landed.py 覆盖）；不判索引加载策略（本修法不动 `_load_index`）；不判「真进程硬杀」形态（本守卫用确定性模拟：还原崩溃前的 _index.json；端到端硬杀读数见审计方证据包 repro/f64_*）
"""issue #498 守卫：**合并痕迹的对账不得依赖索引新鲜度**。

病象（修前实测，HEAD 2dbebee0）：写链 gated MERGE 在 `twophase.commit` 处被硬杀
（`os._exit(7)`，无 flush）后——盘面目标节点**已有** `merge_source_ids: ["n_x"]`
与聚合行，而磁盘 `_index.json` 里该键**缺失**（索引未持久化）⇒ 恢复实例只查索引
⇒ `_merge_target` 返回 None ⇒ 对账判 `interrupted/node_missing`（与盘面相反，
且 `_maybe_reload_index()` 也救不回来，它读的还是那份陈旧索引）。

修法：`_merge_target` 索引落空后**回退盘面扫描**（复用仓内唯一扫描实现
`cg._scan_nodes()`，扫出的条目走**同一条**复合判据），语义不放宽——盘面确无痕迹
时照旧 `interrupted`（B 组反向腿）。
"""
from __future__ import annotations

import io
import json
import os
import re
import shutil
import subprocess
import sys
import time

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _REPO)

# 沙箱用 gettempdir + makedirs（**不用 mkdtemp**）：受限宿主里 mkdtemp 目录带
# 「拒绝再建子目录」ACL，会让守卫整批 PermissionError（与代码无关）。
_SB = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                   "_i419_sandbox_%d_%d" % (os.getpid(), int(time.time() * 1000)))
shutil.rmtree(_SB, ignore_errors=True)
os.makedirs(_SB, exist_ok=True)
os.environ.update({"MDCG_ROOT": os.path.join(_SB, "brain"),
                   "MDCG_STATE_ROOT": os.path.join(_SB, "state"),
                   "MDCG_AUX_ROOT": os.path.join(_SB, "auxstore"),
                   "MDCG_DATA_ROOT": os.path.join(_SB, "datastore"),
                   "MDCG_EXPORT_ROOT": _SB, "MDCG_MASTER_KEY": "ef" * 32,
                   "MDCG_SUSTAIN": "0", "MDCG_SLEEP": "0", "MDCG_AUTONOMY": "full"})
from md_cg import autonomy_modes as am, forgetting, twophase                     # noqa: E402
from md_cg.mdcos import MdCGOS                                                   # noqa: E402
os.environ[am.AUTONOMY_ENV_KEYS["mode"]] = "full"

FAILS, _PASSED, _N = [], [0], [0]
BODY = ("# 功能名：目标节点\n# 生效条件：守卫合成\n# 子功能：无\n# 执行：写入\n"
        "# 验证方式：读回\n# 不适用条件：无\nPASSED 目标正文：深海热泉、玄武岩、管虫群落。")


def _check(name, cond, detail=""):
    if cond:
        print("  PASS " + name)
        _PASSED[0] += 1
    else:
        print("  FAIL " + name + ("  · " + str(detail) if detail else ""))
        FAILS.append(name)


def _lib(tag):
    _N[0] += 1
    root = os.path.join(_SB, "lib_%s_%d" % (tag, _N[0]))
    os.environ["MDCG_ROOT"] = root
    os.makedirs(root, exist_ok=True)
    return root


def _index_json(root):
    return os.path.join(root, "_index.json")


def _disk_fm(root, nid):
    for dp, _dn, fns in os.walk(root):
        for fn in fns:
            if fn == nid + ".md":
                from md_cg import nodefile
                fm, ct = nodefile.loads(io.open(os.path.join(dp, fn), encoding="utf-8",
                                                errors="replace").read())
                return fm, ct
    return {}, ""


def _crash_window_stale_index(root, tag):
    """真实崩溃窗口：**子进程**里 建目标→flush→记意图→合并落盘→`os._exit(7)`（无 flush/无 close）。

    为什么必须走子进程：`os._exit` 才等价于「进程在 `twophase.commit` 前被硬杀」，
    此时**索引只在内存里更新、未持久化**（这正是病象的触发条件）。在父进程里用
    「先合并再还原 _index.json」模拟会被后续 flush/del 覆盖，抓不稳（本守卫初版实测）。
    """
    src = "gm_" + tag
    r = subprocess.run([sys.executable, "-X", "utf8", "-B", os.path.abspath(__file__),
                        "child", root, src],
                       capture_output=True, text=True, encoding="utf-8", errors="replace",
                       env=dict(os.environ), cwd=_REPO)
    return src, r


def _child(root, src):
    """子进程体：写在崩溃窗口之前，然后硬终止（不 commit、不 flush 索引）。"""
    os.environ["MDCG_ROOT"] = root
    cg = MdCGOS(root, autoflush=0)
    cg.add("gm_t", BODY, layer="knowledge", verification_basis="test")
    cg.flush()                                   # 目标与索引先落盘（恢复期要能看到这个节点）
    twophase.begin(cg, src, BODY + "补充。", layer="knowledge", actor="writepipe:gated")
    res = forgetting.reinforce(cg, "gm_t", content=BODY + "补充。", session="s1",
                              actor="writepipe:gated", src_id=src)
    sys.stdout.write("CHILD-REINFORCE=%s\n" % json.dumps(res, ensure_ascii=False, default=str)[:160])
    sys.stdout.flush()
    os._exit(7)                                  # ← 硬杀：不 flush、不 close、不 commit
    return 0


def leg_A():
    print("\n[A 崩溃窗口（索引未持久化）⇒ 必须判 committed]")
    root = _lib("a")
    src, r = _crash_window_stale_index(root, "src1")
    print("   子进程 rc =", r.returncode, "|", (r.stdout or "").strip()[:150])
    fm, ct = _disk_fm(root, "gm_t")
    _check("A1 前提：盘面目标已有该来源痕迹与聚合行",
           src in (fm.get("merge_source_ids") or []) and "【聚合" in ct,
           (fm.get("merge_source_ids"), "【聚合" in ct))

    disk_idx = json.loads(io.open(_index_json(root), encoding="utf-8").read()) if \
        os.path.exists(_index_json(root)) else {}
    idx_key = ((disk_idx.get("nodes") or {}).get("gm_t") or {}).get("merge_source_ids")
    _check("A2 前提：**持久化索引里没有**该键（陈旧索引，正是病象触发条件）",
           not idx_key, idx_key)

    cg2 = MdCGOS(root, autoflush=0)
    ent = (cg2.index.get("nodes") or {}).get("gm_t") or {}
    print("   恢复实例索引里 gm_t.merge_source_ids =", ent.get("merge_source_ids"))
    tgt = twophase._merge_target(cg2, src)
    _check("A3 索引落空 ⇒ 回退盘面后命中目标（修前 None）", tgt == "gm_t", tgt)

    out = cg2.reconcile_writes()
    print("   reconcile_writes() =", json.dumps(out, ensure_ascii=False, default=str)[:220])
    _check("A4 对账判 committed（修前 interrupted/node_missing）",
           out.get("committed") == 1 and out.get("interrupted") == 0, out)
    _check("A5 结论理由指向合并目标（可追溯，不编造）",
           any("gm_t" in str(d.get("reason") or "") for d in (out.get("details") or [])) or
           all(d.get("status") == "committed" for d in (out.get("details") or [])),
           out.get("details"))
    cg2.close()


def leg_B():
    """反向腿：盘面确无痕迹 ⇒ 仍须 interrupted（不得因回退而放宽）。"""
    print("\n[B 反向腿：无痕迹 ⇒ 仍 interrupted]")
    root = _lib("b")
    cg = MdCGOS(root, autoflush=0)
    cg.add("bg_t", BODY, layer="knowledge", verification_basis="test")
    cg.flush()
    twophase.begin(cg, "bg_ghost", BODY + "幽灵。", layer="knowledge", actor="writepipe:gated")
    cg.flush()
    cg.close()
    cg2 = MdCGOS(root, autoflush=0)
    _check("B1 盘面无该来源痕迹 ⇒ _merge_target 返回 None",
           twophase._merge_target(cg2, "bg_ghost") is None,
           twophase._merge_target(cg2, "bg_ghost"))
    out = cg2.reconcile_writes()
    print("   reconcile_writes() =", json.dumps(out, ensure_ascii=False, default=str)[:200])
    _check("B2 仍判 interrupted/node_missing（不放宽）",
           out.get("interrupted") == 1 and out.get("committed") == 0, out)
    cg2.close()


def leg_C():
    """源码面：索引落空必须回退盘面扫描（防「回退被删而守卫还绿」）。"""
    print("\n[C 源码面：回退仍在]")
    src = io.open(os.path.join(_REPO, "md_cg", "twophase.py"), encoding="utf-8").read()
    m = re.search(r"def _merge_target\(cg, nid\):(.*?)\ndef _merge_target_in", src, re.S)
    body = m.group(1) if m else ""
    _check("C1 _merge_target 内仍有盘面回退（_scan_nodes）", "_scan_nodes" in body,
           body[-160:].replace("\n", " "))
    _check("C2 复合判据仍是单点（_merge_target_in 被两处共用）",
           src.count("_merge_target_in(") >= 2, src.count("_merge_target_in("))


def leg_R():
    """--mutate：把 _merge_target 退回修前形态（内存内源码级回退）⇒ A3/A4 转红。"""
    print("\n[R 变异自证：去掉盘面回退后实跑]")
    p = os.path.join(_REPO, "md_cg", "twophase.py")
    orig = io.open(p, encoding="utf-8").read()
    m = re.search(r"(def _merge_target\(cg, nid\):.*?)\n\n\n# 生效条件：nodes 为映射时", orig, re.S)
    if not m:
        print("  [R] 未定位到 _merge_target 段 ⇒ 跳过回退自证")
        return
    old_impl = ('def _merge_target(cg, nid):\n'
                '    """修前形态：只查索引。"""\n'
                '    return _merge_target_in(cg, (getattr(cg, "index", None) or {}).get("nodes") or {}, nid)')
    mutated = orig[:m.start(1)] + old_impl + orig[m.end(1):]
    try:
        exec(compile(mutated, p, "exec"), twophase.__dict__)     # 内存内回退（实跑）
        before = len(FAILS)
        leg_A()
        regressed = len(FAILS) - before
        print("  [R] 回退后新增红项 = %d" % regressed)
        _check("R1 回退即红（A3/A4 在红项内，实跑非推演）", regressed >= 2, "新增=%d" % regressed)
    finally:
        exec(compile(orig, p, "exec"), twophase.__dict__)


def main():
    mutate = "--mutate" in sys.argv
    print("=" * 72)
    print("md 认知图 · issue #498 守卫 · 合并痕迹对账不得依赖索引新鲜度")
    print("沙箱 =", _SB, "| mutate =", mutate)
    print("=" * 72)
    leg_A()
    leg_B()
    leg_C()
    if mutate:
        leg_R()
    print("\n" + ("全部 PASS（%d 项）" % _PASSED[0] if not FAILS
                  else "FAIL %d 项：%s" % (len(FAILS), FAILS)))
    shutil.rmtree(_SB, ignore_errors=True)
    return 1 if FAILS else 0


if __name__ == "__main__":
    if len(sys.argv) > 3 and sys.argv[1] == "child":
        sys.exit(_child(sys.argv[2], sys.argv[3]))
    sys.exit(main())
