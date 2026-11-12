# -*- coding: utf-8 -*-
# 功能名：合并痕迹对账不得读陈旧索引（索引落空须回退盘面扫描）——issue #498
# 生效条件：python -X utf8 -m md_cg.test_issue498_merge_trace_stale_index [--mutate]；被测面＝md_cg/twophase.py::_merge_target/_merge_target_in/_judge 与 reconcile（经 cg.reconcile_writes）
# 子功能：A 组＝陈旧索引（长活实例未重载 / 崩溃窗口内索引未持久化）下对账仍判 committed 并带去向；B 组＝非恒真反向腿（盘面确无痕迹仍 interrupted/node_missing，源已落盘仍 node_present_hash_match）；C 组＝单点与回退面（索引面与盘面扫描面共用同一条复合判据、回退只在索引落空之后）
# 执行：--mutate 时在镜像树里回退「回退盘面扫描」与放宽「未命中」两处，守卫必须按指定项转红
# 验证方式：全部 PASS 即通过（退出码 0）；默认模式另做源码锚点自检（关键判据字面量缺失 ⇒ exit 2，fail-closed）；--mutate 模式红项集合须与预期逐项相符
# 不适用条件：不判真断电/进程被硬杀的文件系统语义（本守卫用「子进程 os._exit(7) 不 flush/不 close」构造同一索引侧落盘态）；不判 MERGE 之外的动作（ACCEPT/DROP/DEFER 各自的崩溃窗口）；不判索引自身的重建策略（#409/_snapshot_trusted 面）；不判多目标/多来源同时合并
"""issue #498 守卫：对账判据的事实来源是**盘面**，不是「索引里有没有这个键」。

病象（修前）：`_merge_target` 只遍历 `cg.index["nodes"]`。索引是派生物——崩溃窗口
内 `_index.json` 可能根本没持久化，或本进程是长活实例（签名未变 ⇒ `_maybe_reload_index`
不重载）⇒ 索引里没有 `merge_source_ids` 这个键，判据看不到盘面已经存在的合并痕迹，
`reconcile` 判 `interrupted/node_missing`——**与盘面相反**，且会诱导重做不可逆的 MERGE。

修法：索引落空后**回退盘面扫描**（复用库层唯一扫描实现 `cg._scan_nodes()`，不新写
第二套遍历），扫出的条目交给**同一条**复合判据（`_merge_target_in`，仍 `cg.get(tid)`
回盘复核）。语义不放宽：盘面确无痕迹 ⇒ 仍 `interrupted/node_missing`。
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO not in sys.path:
    sys.path.insert(0, _REPO)

from md_cg.mdcos import MdCGOS   # noqa: E402
from md_cg import twophase       # noqa: E402

FAILS = []
_TMP = tempfile.mkdtemp(prefix="iss498_")
_CCG = "\n".join(["# 功能名：目标节点", "# 生效条件：本地合成库", "# 子功能：无",
                  "# 执行：无", "# 验证方式：test", "# 不适用条件：无",
                  "# 正文：目标节点正文"])


def _check(name, cond, detail=""):
    if cond:
        print("  PASS " + name)
    else:
        print("  FAIL " + name + "  " + str(detail)[:220])
        FAILS.append(name)


def _lib(tag):
    d = os.path.join(_TMP, tag)
    os.makedirs(d, exist_ok=True)
    cg = MdCGOS(d)
    cg.add("n_t", _CCG)
    cg.flush()
    cg.close()
    return d


def _crash_child(root, src="n_x"):
    """子进程：begin → reinforce（盘面落痕）→ os._exit(7)，索引侧零变化。"""
    code = (
        "import os, sys\n"
        "sys.path.insert(0, sys.argv[1])\n"
        "from md_cg.mdcos import MdCGOS\n"
        "from md_cg import forgetting, twophase\n"
        "cg = MdCGOS(sys.argv[2])\n"
        "twophase.begin(cg, sys.argv[3], 'PASSED 新增补充。', layer='knowledge',\n"
        "               actor='writepipe:gated')\n"
        "forgetting.reinforce(cg, 'n_t', content='PASSED 新增补充。', session='s1',\n"
        "                     actor='writepipe:gated', src_id=sys.argv[3])\n"
        "os._exit(7)\n")
    env = dict(os.environ)
    for k in ("MDCG_TOKEN", "MDCG_VERIFY_KEY"):   # 父 shell 陷阱：不传给子进程
        env.pop(k, None)
    return subprocess.run([sys.executable, "-X", "utf8", "-c", code, _REPO, root, src],
                          capture_output=True, text=True, encoding="utf-8", env=env)


print("== A 组：索引陈旧时对账仍须判 committed（#498 正题） ==")
_root = _lib("stale")
_cgA = MdCGOS(_root)                      # 长活实例：索引已载入，签名基线已记录
_sig0 = _cgA._index_signature()
_rc = _crash_child(_root)
_fm_txt = open(os.path.join(_root, "knowledge", "orphan", "n_t.md"),
               encoding="utf-8").read()
_check("A01 前提成立：盘面已有 merge_source_ids 含 n_x，且 cgA 索引里没有该键",
       _rc.returncode == 7 and "merge_source_ids" in _fm_txt and "n_x" in _fm_txt
       and not (((_cgA.index.get("nodes") or {}).get("n_t") or {})
                .get("merge_source_ids")),
       {"rc": _rc.returncode, "stderr": (_rc.stderr or "")[:120]})
_check("A02 前提成立：cgA 索引签名未变（不会重载，索引确实陈旧）",
       _cgA._index_signature() == _sig0)
_check("A03 陈旧索引下 _merge_target 仍命中盘面痕迹（修前：None）",
       twophase._merge_target(_cgA, "n_x") == "n_t",
       twophase._merge_target(_cgA, "n_x"))
_rep = _cgA.reconcile_writes()
_check("A04 对账判 **committed**（修前：interrupted/node_missing）",
       _rep.get("committed") == 1 and _rep.get("interrupted") == 0, _rep.get("details"))
_check("A05 判定码带去向（merged_into_present:n_t）",
       all(str(d.get("reason", "")).startswith("merged_into_present:")
           for d in (_rep.get("details") or [])), _rep.get("details"))
_cgA.close()

# A06：全新实例 + 合并前快照（崩溃窗口内 _index.json 未持久化）——端到端腿。
# 如实登记：本仓 `_snapshot_trusted` 在目录树指纹不符时会回落 `_scan_nodes`，
# 故这条路径**可能**由装载期重扫救回（本机实测如此）；它只作端到端对照，
# 判别力在 A01–A05（长活实例、签名未变、索引确实陈旧）。
_root2 = _lib("stale_snapshot")
_pre = open(os.path.join(_root2, "_index.json"), "rb").read()
_rc2 = _crash_child(_root2)
open(os.path.join(_root2, "_index.json"), "wb").write(_pre)   # 写回合并前快照
_cg2 = MdCGOS(_root2)
_rep2 = _cg2.reconcile_writes()
_check("A06 端到端对照：写回合并前快照的新实例对账判 committed",
       _rep2.get("committed") == 1 and _rep2.get("interrupted") == 0,
       _rep2.get("details"))
_cg2.close()

print("== B 组：非恒真反向腿（新判据只补「已合并」这一种真实情形） ==")
_root_b = _lib("absent")
_cg = MdCGOS(_root_b)
twophase.begin(_cg, "n_never", "从未落盘的正文", layer="knowledge",
               actor="writepipe:gated")
_cg.flush()
_cg.close()
_cg = MdCGOS(_root_b)
_rep_b = _cg.reconcile_writes()
_check("B01 反向腿：盘面确无合并痕迹 ⇒ 仍 interrupted/node_missing（不放宽）",
       _rep_b.get("interrupted") == 1 and _rep_b.get("committed") == 0
       and (_rep_b.get("details") or [{}])[0].get("reason") == "node_missing",
       _rep_b.get("details"))
_cg.close()

_root_c = _lib("present")
_cg = MdCGOS(_root_c)
twophase.begin(_cg, "n_y", "直接落盘正文", layer="knowledge")
_cg.add("n_y", "直接落盘正文")
_cg.flush()
_cg.close()
_cg = MdCGOS(_root_c)
_rep_c = _cg.reconcile_writes()
_check("B02 正向腿：源 id 已落盘 ⇒ 仍 committed/node_present_hash_match（原判据不被扰动）",
       _rep_c.get("committed") == 1
       and (_rep_c.get("details") or [{}])[0].get("reason") == "node_present_hash_match",
       _rep_c.get("details"))
_cg.close()

print("== C 组：单点与回退面（源码锚点） ==")
_SRC_T = open(os.path.join(_REPO, "md_cg", "twophase.py"), encoding="utf-8").read()
_MISSING = []
for _needle in ("_scan_nodes", "_merge_target_in", "def _merge_target_in("):
    if _needle not in _SRC_T:
        _MISSING.append(_needle)
_check("C01 索引落空后回退库层唯一扫描实现 _scan_nodes，且复合判据抽成 _merge_target_in 单点",
       not _MISSING, _MISSING)
_check("C02 复合判据只有**一份**实现（遍历 merge_source_ids 的循环只出现一次）",
       _SRC_T.count("for tid, e in tuple(nodes.items())") == 1,
       _SRC_T.count("for tid, e in tuple(nodes.items())"))
_check("C03 回退在索引命中判定**之后**（命中路径不触发全扫）",
       _SRC_T.index("tgt = _merge_target_in(cg, nid, nodes)")
       < _SRC_T.index("scan = getattr(cg, \"_scan_nodes\", None)"))
_check("C04 未命中仍回 interrupted/node_missing（不放宽的源码面证据）",
       "return STATUS_INTERRUPTED, R_NODE_MISSING" in _SRC_T)

if _MISSING and "--mutate" not in sys.argv:
    print("锚点自检失败：关键判据字面量缺失 %s" % _MISSING)
    shutil.rmtree(_TMP, ignore_errors=True)
    sys.exit(2)


def _mirror_build():
    dst = tempfile.mkdtemp(prefix="iss498_mut_")
    for name in ("md_cg", "scripts"):
        src = os.path.join(_REPO, name)
        if os.path.isdir(src):
            shutil.copytree(src, os.path.join(dst, name),
                            ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    for name in sorted(os.listdir(_REPO)):
        p = os.path.join(_REPO, name)
        if os.path.isfile(p) and (name.endswith(".py")
                                  or name in ("README.md", "pyproject.toml")):
            shutil.copy2(p, os.path.join(dst, name))
    return dst


def _run_in(tree):
    env = dict(os.environ)
    env.update({"PYTHONPATH": tree, "PYTHONUTF8": "1",
                "PYTHONDONTWRITEBYTECODE": "1"})
    env.pop("MDCG_ROOT", None)
    env.pop("MDCG_TOKEN", None)
    env.pop("MDCG_VERIFY_KEY", None)
    pr = subprocess.run([sys.executable, "-X", "utf8", "-m",
                         "md_cg.test_issue498_merge_trace_stale_index"],
                        cwd=tree, env=env, capture_output=True, text=True,
                        encoding="utf-8", errors="replace", timeout=1200)
    out = (pr.stdout or "") + (pr.stderr or "")
    reds = [ln.split("FAIL ", 1)[1].strip()
            for ln in out.splitlines() if ln.strip().startswith("FAIL ")]
    return pr.returncode, reds, out


_NL = "\r\n" if b"\r\n" in open(os.path.join(_REPO, "md_cg", "twophase.py"),
                                 "rb").read()[:8192] else "\n"


def _j(*lines):
    return _NL.join(lines)


_MUTATIONS = (
    ("M1 回缺陷：索引落空后不回退盘面扫描（回到只查索引）", "md_cg/twophase.py",
     (_j("    tgt = _merge_target_in(cg, nid, nodes)",
         "    if tgt is not None:",
         "        return tgt"),
      _j("    return _merge_target_in(cg, nid, nodes)  # 变异：不回退盘面扫描")),
     ("A03", "A04", "A05")),
    ("M2 过度放宽：盘面无痕迹也编造命中", "md_cg/twophase.py",
     (_j("        if nid in (fm.get(\"merge_source_ids\") or []):",
         "            return tid",
         "    return None"),
      _j("        if nid in (fm.get(\"merge_source_ids\") or []):",
         "            return tid",
         "    return \"n_t\"  # 变异：未命中也放行")),
     ("B01",)),
)


def _mutate():
    print("!! 定点变异：回退盘面回退 + 过度放宽，守卫必须按指定项转红")
    tree = _mirror_build()
    bad = []
    try:
        rc, reds, out = _run_in(tree)
        print("  未变异镜像基线：rc=%d 红项=%d（必须 rc=0 且 0 红）" % (rc, len(reds)))
        if rc != 0 or reds:
            print("\n".join(out.splitlines()[-20:]))
            bad.append("镜像基线非绿")
        for desc, rel, (old, new), exp in _MUTATIONS:
            p = os.path.join(tree, rel)
            t = open(p, encoding="utf-8", newline="").read()
            if t.count(old) != 1:
                bad.append("%s 锚点命中 %d 次" % (desc, t.count(old)))
                print("  ANCHOR-MISS " + desc)
                continue
            bak = t
            open(p, "w", encoding="utf-8", newline="").write(t.replace(old, new, 1))
            for r, _dd, _ff in os.walk(tree):
                if os.path.basename(r) == "__pycache__":
                    shutil.rmtree(r, ignore_errors=True)
            rc2, reds2, _o2 = _run_in(tree)
            open(p, "w", encoding="utf-8", newline="").write(bak)
            hit = sorted({r.split(" ")[0] for r in reds2})
            if rc2 != 0 and hit == sorted(exp):
                print("  OK   %s  红项=%d 指定命中=%d/%d"
                      % (desc, len(reds2), len(hit), len(exp)))
            else:
                bad.append(desc)
                print("  MISMATCH %s 实际=%s 期望=%s rc=%d"
                      % (desc, hit, sorted(exp), rc2))
                for r in reds2[:6]:
                    print("        FAIL " + r)
        print("定点变异自证：%s（%d 条不合格）" % ("PASS" if not bad else "FAIL", len(bad)))
        return len(bad)
    finally:
        shutil.rmtree(tree, ignore_errors=True)


shutil.rmtree(_TMP, ignore_errors=True)
print("")
print("issue #498 结果：%s" % ("全部通过" if not FAILS else "%d 失败" % len(FAILS)))


def main():
    _bad = _mutate() if "--mutate" in sys.argv else 0
    return 1 if (FAILS or _bad) else 0


if __name__ == "__main__":
    sys.exit(main())
