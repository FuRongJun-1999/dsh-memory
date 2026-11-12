# -*- coding: utf-8 -*-
# 功能名：writelimit 台账「读 → 改 → 写」的跨进程互斥（issue #354 P2-17 TOCTOU）
# 生效条件：python -X utf8 -m md_cg.test_issue354_p2_writelimit_toctou [--mutate]；被测面=md_cg/writelimit.py 的 check / record_accepted / _transaction / _save_locked
# 子功能：A 组=多进程并发 check 的记账零丢失（修前 8 并发实测只剩 3~7 条）；B 组=并发下的限流上限仍生效（计数不丢 ⇒ 第 RATE_MAX+1 条起判 DEFER）；C 组=单进程语义未变（放行/CONVERGE/DROP/DEFER 与 #345/#148 口径一致）；D 组=临界区判据在场（读改写同锁、落盘无锁版本、strict=True）
# 执行：--mutate 时把「读改写同临界区」退回修前形态（_load 在锁外、_save 在锁内）到**镜像树**，守卫必须转红
# 验证方式：默认模式全部 PASS（退出码 0）；--mutate 下未变异镜像 0 红、变异后指定项逐项转红
# 不适用条件：不覆盖 Windows 之外的 msvcrt/flock 实现差异（FileLock 本体另有 test_lock.py）；不判「限流阈值 RATE_MAX 是否合理」（业务参数）；不覆盖 swarm Rust 侧并发（另有 md_cg/test_issue354_rust_wal_containment.py）
"""issue #354 [P2-17] 守卫：writelimit 台账读改写必须全程持跨进程锁。

病象（修前，本文件 A 组实测）：8 个进程各自对同一台账调用一次 check，每个进程都
应留下 1 条时间戳；旧实现 `_load` 在锁**外**、`_save` 在锁**内**，后写者用陈旧
快照整份覆写先写者 ⇒ 实测只剩 3~7 条（丢更新），频率上限被并发穿透。
`atomic_write` 只防撕裂、不防丢失更新——这是两件事。

修法（报告 §5.9）：读改写全程持同一把 OS 级 `FileLock(strict=True)`（与 #322/#348
同口径）；临界区内落盘走 `_save_locked`（不再二次取锁——Windows 上同进程第二次
获取同一字节范围会自我阻塞）；`now` 也在锁内取（锁外取的 now 会落在别人已写入
的时间戳之前，被 P1-10 的双向界定当作「未来戳」剔掉，同样丢记账）。

隔离纪律：台账全部落在 tempfile.mkdtemp 下；子进程显式剔除父 shell 的
MDCG_TOKEN / MDCG_VERIFY_KEY（派工书 §0 的假红陷阱）。镜像树变异只在临时目录
改源码，真实工作树一字不动。
"""
from __future__ import annotations

import io
import json
import os
import shutil
import subprocess
import sys
import tempfile

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

FLOOR = 12
PASS, FAIL = 0, 0
FAILS = []

N_PROC = 8


def _check(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print("  PASS " + name)
    else:
        FAIL += 1
        FAILS.append(name)
        print("  FAIL " + name + "  " + str(detail)[:220])


# ---------------------------------------------------------------- 桩与夹具

class _CG:
    """最小 cg 桩：check/record_accepted 只用到 root 与 get。"""

    def __init__(self, root, nodes=None):
        self.root = root
        self._nodes = nodes or {}

    def get(self, nid):
        return self._nodes.get(nid)


def _env():
    e = dict(os.environ)
    e.pop("MDCG_TOKEN", None)          # 派工书 §0：父 shell 的令牌会污染子进程
    e.pop("MDCG_VERIFY_KEY", None)
    e["PYTHONUTF8"] = "1"
    e["PYTHONDONTWRITEBYTECODE"] = "1"
    e["MDCG_WRITELIMIT"] = "1"
    return e


#: 并发 worker：一次 check（正文各异 ⇒ 签名各异），跑完打印台账窗口条数。
_WORKER = r'''
import json, sys, time
sys.path.insert(0, sys.argv[1])
from md_cg import writelimit

class CG:
    def __init__(self, root):
        self.root = root
    def get(self, nid):
        return None

cg = CG(sys.argv[2])
r = writelimit.check(cg, "并发写入正文 %s 用于区分签名" % sys.argv[3], role="u")
try:
    st = json.load(open(sys.argv[2] + "/_writelimit.json", encoding="utf-8"))
    n = len((st.get("rate") or {}).get("contextual:u") or [])
except Exception as exc:
    n = -1
print(json.dumps({"verdict": r, "rate_after": n}))
'''


def _spawn_concurrent(root, repo, n=N_PROC):
    procs = [subprocess.Popen([sys.executable, "-X", "utf8", "-c", _WORKER, repo, root, str(i)],
                              env=_env(), stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                              text=True, encoding="utf-8", errors="replace")
             for i in range(n)]
    outs = []
    for p in procs:
        o, e = p.communicate(timeout=180)
        outs.append((p.returncode, o, e))
    return outs


def _rate_len(root, key="contextual:u"):
    p = os.path.join(root, "_writelimit.json")
    if not os.path.exists(p):
        return -1
    st = json.load(open(p, encoding="utf-8"))
    return len((st.get("rate") or {}).get(key) or [])


# ---------------------------------------------------------------- A/B 组：并发

def group_concurrent(repo):
    print("== A 组：8 进程并发 check 的记账零丢失（修前实测只剩 3~7 条）==")
    root = tempfile.mkdtemp(prefix="i354p2_toc_")
    outs = _spawn_concurrent(root, repo)
    bad = [(rc, (e or "")[-160:]) for rc, _o, e in outs if rc != 0]
    _check("A1 全部 worker 正常退出（锁竞争不误伤）", not bad, bad)
    got = _rate_len(root)
    _check("A2 并发记账零丢失（8 进程 ⇒ 恰好 8 条）", got == N_PROC,
           "台账窗口条数=%r 期望=%d" % (got, N_PROC))
    # B 组：并发下上限仍生效——再并发一轮，总量受 RATE_MAX*4 封顶且判定 DEFER
    print("== B 组：并发下的限流上限仍生效（计数不丢 ⇒ 后续判 DEFER）==")
    root2 = tempfile.mkdtemp(prefix="i354p2_cap_")
    # 先灌满窗口：顺序写 RATE_MAX 条（此刻未满，应全部放行）
    from . import writelimit as W
    cg = _CG(root2)
    verdicts = [W.check(cg, "顺序写入正文 %d 号" % i, role="u") for i in range(W.RATE_MAX)]
    _check("B1 前 RATE_MAX 条顺序写入放行", all(v is None for v in verdicts), verdicts)
    # 再并发 8 条：全部应判 DEFER（修前并发丢记账 ⇒ 部分被放行）
    outs2 = _spawn_concurrent(root2, repo)
    vs = []
    for _rc, o, _e in outs2:
        try:
            vs.append(json.loads(o.strip().splitlines()[-1])["verdict"])
        except Exception:
            vs.append(None)
    defers = [v for v in vs if isinstance(v, dict) and v.get("verdict") == "DEFER"]
    _check("B2 满窗口后并发写入一律 DEFER（上限未被并发穿透）",
           len(defers) == N_PROC, "实测 verdicts=%r" % (vs,))


# ---------------------------------------------------------------- C 组：单进程语义

def group_semantics():
    print("== C 组：单进程语义未变（放行 / CONVERGE / DROP / DEFER）==")
    from . import writelimit as W
    root = tempfile.mkdtemp(prefix="i354p2_sem_")
    node = {"id": "n1", "content": "同模板内容 1", "frontmatter": {"layer": "contextual"}}
    cg = _CG(root, {"n1": node})
    _check("C1 首次写入放行", W.check(cg, "同模板内容 1", role="u", node_id="n1") is None)
    r = W.check(cg, "同模板内容 2", role="u", node_id="n1")
    _check("C2 同模板不同正文 ⇒ CONVERGE",
           isinstance(r, dict) and r.get("verdict") == "CONVERGE", r)
    r = W.check(cg, "同模板内容 1", role="u", node_id="n1")
    _check("C3 正文完全一致 ⇒ DROP",
           isinstance(r, dict) and r.get("verdict") == "DROP", r)
    root2 = tempfile.mkdtemp(prefix="i354p2_defer_")
    cg2 = _CG(root2)
    for i in range(W.RATE_MAX):
        W.check(cg2, "灌水正文 %d 号" % i, role="u")
    r = W.check(cg2, "再来一条", role="u")
    _check("C4 窗口满 ⇒ DEFER", isinstance(r, dict) and r.get("verdict") == "DEFER", r)
    _check("C5 record_accepted 首见即落占位（锁内读改写）", _record_ok(W, root2))


def _record_ok(W, root):
    cg = _CG(root)
    W.record_accepted(cg, "nid-x", "一个足够长的模板正文用于签名")
    st = json.load(open(os.path.join(root, "_writelimit.json"), encoding="utf-8"))
    return any(isinstance(v, dict) and v.get("nid") == "nid-x" for v in st["sigs"].values())


# ---------------------------------------------------------------- D 组：判据在场

def group_source():
    print("== D 组：临界区判据在场（源码级）==")
    p = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                     "md_cg", "writelimit.py")
    src = io.open(p, encoding="utf-8").read()
    _check("D1 _transaction 用 strict=True 的跨进程锁", "FileLock(_state_path(cg), strict=True)" in src)
    _check("D2 check 的 _load 在 _transaction 内", "with _transaction(cg):\n        now = float" in src
           or "with _transaction(cg):\r\n        now = float" in src)
    _check("D3 临界区内落盘走无锁版 _save_locked", src.count("_save_locked(cg, st)") >= 4)
    _check("D4 record_accepted 也在临界区内", src.count("with _transaction(cg):") >= 2)
    _check("D5 反陈化：点名 issue #354 与 P2-17", "#354" in src and "P2-17" in src)


# ---------------------------------------------------------------- 定点变异自证

_TARGET = "md_cg/writelimit.py"

#: (说明, 改前锚, 改后锚, 期望转红的断言名前缀)
_MUTATIONS = (
    # 缺陷形态：**锁外**读快照、锁内用它落盘（后写者整份覆盖先写者）。为了把
    # 「读在锁外」这个竞态窗口放大成确定性现象，变异腿在 load 与取锁之间插入
    # 0.25s——语义上仍是「锁外的陈旧快照」，只是让 8 个 worker 必然同时落在
    # 同一个空快照上（真实修前代码正是这个形态，只是窗口更窄）。
    ("V1 读改写退回修前形态（_load 在锁外、_save 在锁内）",
     "    with _transaction(cg):\n"
     "        now = float(now) if now is not None else time.time()\n"
     "        st = _load(cg)\n"
     "        # 1) 同源频率限制",
     "    _st_pre = _load(cg)\n"
     "    time.sleep(0.25)\n"
     "    with _transaction(cg):\n"
     "        now = float(now) if now is not None else time.time()\n"
     "        st = _st_pre\n"
     "        # 1) 同源频率限制",
     ("A2",)),
)


def _fold(text, eol):
    return text.replace("\r\n", "\n").replace("\n", eol)


def _mirror_build():
    repo = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    dst = tempfile.mkdtemp(prefix="i354p2_mut_")
    for name in ("md_cg", "scripts"):
        src = os.path.join(repo, name)
        if os.path.isdir(src):
            shutil.copytree(src, os.path.join(dst, name),
                            ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    for name in sorted(os.listdir(repo)):
        p = os.path.join(repo, name)
        if os.path.isfile(p) and name.endswith(".py"):
            shutil.copy2(p, os.path.join(dst, name))
    return dst


def _run_in(tree):
    env = _env()
    env["PYTHONPATH"] = tree
    pr = subprocess.run([sys.executable, "-X", "utf8", "-m",
                         "md_cg.test_issue354_p2_writelimit_toctou"],
                        capture_output=True, text=True, encoding="utf-8",
                        errors="replace", cwd=tree, env=env, timeout=1800)
    out = (pr.stdout or "") + (pr.stderr or "")
    # 复核意见 4：只认行首的 "FAIL " 红项行；汇总行
    # "断言总数 N（PASS x / FAIL y），FLOOR=z" 里也含 "FAIL "，按子串匹配会把它
    # 当成一条红项（基线 0 红被读成 1 红）。
    reds = [ln.strip()[len("FAIL "):].strip()
            for ln in out.splitlines() if ln.strip().startswith("FAIL ")]
    return pr.returncode, reds, out


def _mutate():
    print("!! 定点变异自证：把读改写退回修前形态，守卫必须转红（镜像树）")
    tree = _mirror_build()
    try:
        rc, reds, out = _run_in(tree)
        print("  未变异镜像基线：rc=%d 红项=%d（须 rc=0 且 0 红）" % (rc, len(reds)))
        base_ok = (rc == 0 and not reds)
        if not base_ok:
            print("\n".join(out.splitlines()[-25:]))
        ok, bad = 0, []
        # 复核意见 4：基线必须干净才算变异腿有效（基线本身红着，转红就没有区分力）。
        if not base_ok:
            bad.append("未变异镜像基线不干净（rc=%d 红项=%d）" % (rc, len(reds)))
        for desc, old, new, exp in _MUTATIONS:
            p = os.path.join(tree, _TARGET)
            with io.open(p, encoding="utf-8", newline="") as f:
                t = f.read()
            eol = "\r\n" if "\r\n" in t else "\n"
            o, n = _fold(old, eol), _fold(new, eol)
            if t.count(o) != 1:
                bad.append("%s —— 锚点在 %s 里命中 %d 次" % (desc, _TARGET, t.count(o)))
                print("  ANCHOR-MISS " + desc)
                continue
            with io.open(p, "w", encoding="utf-8", newline="") as f:
                f.write(t.replace(o, n, 1))
            for root, dd, ff in os.walk(tree):
                if os.path.basename(root) == "__pycache__":
                    shutil.rmtree(root, ignore_errors=True)
            rc2, reds2, out2 = _run_in(tree)
            with io.open(p, "w", encoding="utf-8", newline="") as f:
                f.write(t)
            hit = [r for r in reds2 if any(r.startswith(e) for e in exp)]
            if rc2 != 0 and len(hit) >= len(exp):
                ok += 1
                print("  OK   %s  红项=%d 指定命中=%d/%d"
                      % (desc, len(reds2), len(hit), len(exp)))
            else:
                bad.append(desc)
                print("  MISMATCH %s  红项=%d 指定命中=%d/%d rc=%d"
                      % (desc, len(reds2), len(hit), len(exp), rc2))
                for r in reds2[:8]:
                    print("        FAIL " + r)
        print("定点变异自证：%s（%d 条不合格）"
              % ("PASS" if not bad else "FAIL", len(bad)))
        if bad:
            FAILS.extend(bad)
    finally:
        shutil.rmtree(tree, ignore_errors=True)


def main():
    repo = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if "--mutate" in sys.argv:
        _mutate()
        return 0 if not FAILS else 1
    group_concurrent(repo)
    group_semantics()
    group_source()
    print()
    print("断言总数 %d（PASS %d / FAIL %d），FLOOR=%d"
          % (PASS + FAIL, PASS, FAIL, FLOOR))
    if FAIL or (PASS + FAIL) < FLOOR:
        print("issue #354 [P2-17] 结果：失败")
        return 1
    print("issue #354 [P2-17] 结果：全部通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
