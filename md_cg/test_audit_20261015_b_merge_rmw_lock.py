# -*- coding: utf-8 -*-
# 功能名：MERGE/CONVERGE 目标节点读改写的跨进程互斥（issue #348-B）
# 生效条件：python -X utf8 -m md_cg.test_audit_20261015_b_merge_rmw_lock [--mutate]；被测面=md_cg/forgetting.py 的 reinforce 与 md_cg/writelimit.py 的 converge_into
# 子功能：B 组=三条落点 4 进程同刻并入同一目标，已回执的新值必须都在目标正文里，且临界区确实持锁；K 组=串行聚合与目标缺失语义不变（非恒真对照）
# 执行：--mutate 时摘掉 reinforce 的 merge_rmw_locked 装饰器、或摘掉 converge_into 的取锁，守卫必须转红
# 验证方式：全部 PASS 即通过；--mutate 下变异的「指定命中」须与预期一致
# 不适用条件：不判 #322 的 add/writepipe 路径（另一条 issue）；不判缺省 confirm 档（只有 full 档才直接落盘）；不覆盖 POSIX 腿
"""issue #348-B 守卫：MERGE/CONVERGE 目标读改写没有跨进程互斥时，已回执的聚合行会消失。

病象（修前）：forgetting.reinforce 与 writelimit.converge_into 都按「cg.get(目标) →
aggregate_line 追加 → _write_node 整文件覆写」处理同一目标节点，读与写之间没有跨进程
互斥。多实例同根并发把不同的近重复并入同一目标时，后写者按自己读到的旧正文整份覆盖
前者刚追加的聚合行——两边都回执 MERGE，被覆盖的新值在库里 0 命中。

定向验收用「加宽窗口」变体：工作进程把 forgetting.aggregate_line 包一层 0.3 秒睡眠，
只拉长「读到旧正文 → 写回」之间的窗口，不改任何判据。修前每条落点 4 进程里丢 3 条，
修后 0 条。
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _REPO)
_TMP = tempfile.mkdtemp(prefix="iss348b_")
os.environ.update({"MDCG_ROOT": _TMP + "/brainroot", "MDCG_STATE_ROOT": _TMP + "/state",
                   "MDCG_AUX_ROOT": _TMP + "/auxstore",
                   "MDCG_DATA_ROOT": _TMP + "/datastore", "MDCG_EXPORT_ROOT": _TMP,
                   "MDCG_SUSTAIN": "0", "MDCG_SLEEP": "0"})
from md_cg.mdcos import MdCGOS  # noqa: E402
from md_cg import forgetting as _fg  # noqa: E402
from md_cg import writelimit as _wl  # noqa: E402

K = 4
BASE = ("差旅报销上限 15000 元，负责人张三，财务部审批，发票须在 30 天内提交，超标需副总签字，"
        "住宿标准一线城市 600 元每晚，二线城市 400 元每晚，餐补每天 100 元，交通费实报实销")
FAILS = []


def _check(name, cond, detail=""):
    if cond:
        print("  PASS " + name)
    else:
        print("  FAIL " + name + "  " + str(detail)[:300])
        FAILS.append(name)


# 工作进程：自旋对齐到 t0，各自把「原文 + 一条新值」经指定落点并入同一目标节点。
_WORKER = r'''
import json, os, sys, time
sys.path.insert(0, sys.argv[1])
from md_cg import forgetting
root, i, t0, base, landing = sys.argv[2], int(sys.argv[3]), float(sys.argv[4]), sys.argv[5], sys.argv[6]
LOCK = os.path.join(root, "_merge_rmw.lock")
seen = {"in_lock": False}
_orig = forgetting.aggregate_line
def _slow(body, content, stamp=None):
    seen["in_lock"] = os.path.exists(LOCK)
    time.sleep(0.3)
    return _orig(body, content, stamp=stamp)
forgetting.aggregate_line = _slow
from md_cg.mdcos import MdCGOS
cg = MdCGOS(root)
while time.time() < t0:
    pass
text = base + "\nVAL%04d" % (7000 + i)
if landing == "merge":
    r = cg.remember_gated(None, text, layer="contextual", role="user")
    acked = r.get("verdict") == "MERGE"
elif landing == "converge":
    from md_cg import writelimit
    r = writelimit.converge_into(cg, "policy", text, actor="w")
    acked = bool(r.get("ok"))
else:
    r = forgetting.reinforce(cg, "policy", content=text, actor="w")
    acked = bool(r)
cg.close()
print(json.dumps({"i": i, "acked": bool(acked), "in_lock": bool(seen["in_lock"])}))
'''


def _round(landing):
    """一轮 4 进程并发；返回 (回执行号列表, 丢失值号列表, 未持锁的号列表, 原始读数)。"""
    t = tempfile.mkdtemp(prefix="iss348b_r_")
    env = {k: v for k, v in os.environ.items() if not k.startswith(("MDCG_", "PYTHON"))}
    for k, d in (("HOME", "home"), ("MDCG_STATE_ROOT", "state"), ("MDCG_AUX_ROOT", "auxstore"),
                 ("MDCG_DATA_ROOT", "datastore"), ("MDCG_EXPORT_ROOT", "export")):
        env[k] = os.path.join(t, d)
        os.makedirs(env[k])
    env.update({"MDCG_AUTONOMY": "full", "MDCG_SUSTAIN": "0", "MDCG_SLEEP": "0",
                "MDCG_TOKEN_FILE": t + "/auxstore/tokens.json", "PYTHONUTF8": "1"})
    root = os.path.join(t, "root")
    env["MDCG_ROOT"] = root
    subprocess.run([sys.executable, "-X", "utf8", "-c",
                    "import sys;sys.path.insert(0,sys.argv[1]);from md_cg.mdcos import MdCGOS;"
                    "cg=MdCGOS(sys.argv[2]);cg.add('policy',sys.argv[3],layer='contextual');cg.close()",
                    _REPO, root, BASE], env=env, check=True, cwd=env["HOME"], capture_output=True)
    t0 = time.time() + 2.5
    ps = [subprocess.Popen([sys.executable, "-X", "utf8", "-c", _WORKER, _REPO, root, str(i), str(t0),
                            BASE, landing], env=env, cwd=env["HOME"], stdout=subprocess.PIPE,
                           stderr=subprocess.PIPE, text=True) for i in range(K)]
    res = []
    for p in ps:
        o, e = p.communicate(timeout=600)
        try:
            res.append(json.loads(o.strip().splitlines()[-1]))
        except Exception:
            res.append({"i": -1, "acked": False, "in_lock": False, "err": e.strip()[-200:]})
    with open(os.path.join(root, "contextual", "policy.md"), encoding="utf-8") as f:
        body = f.read()
    acked = [r["i"] for r in res if r.get("acked")]
    miss = [i for i in acked if "VAL%04d" % (7000 + i) not in body]
    nolock = [r["i"] for r in res if r.get("acked") and not r.get("in_lock")]
    shutil.rmtree(t, ignore_errors=True)
    return acked, miss, nolock, res


print("== P 组：前提 ==")
_ser = MdCGOS(_TMP + "/serialroot")
_ser.add("policy", BASE, layer="contextual")
_check("P1 前提：基础节点可写可读",
       BASE[:12] in ((_ser.get("policy") or {}).get("content") or ""),
       (_ser.get("policy") or {}).get("content", "")[:40])

print("== B 组：三条落点，4 进程同刻并入同一目标 ==")
for _name, _landing in (("B1 remember_gated（MERGE 支）", "merge"),
                        ("B2 writelimit.converge_into（CONVERGE 支）", "converge"),
                        ("B3 forgetting.reinforce（直接调用）", "reinforce")):
    _acked, _miss, _nolock, _res = _round(_landing)
    _check(_name + "：4 条回执的新值全部留在目标正文里",
           len(_acked) == K and not _miss,
           "回执=%s 丢失=%s 原始=%s" % (_acked, _miss, _res))
    _check(_name + "：聚合行在跨进程临界区内生成（锁文件在时才算持锁）",
           bool(_acked) and not _nolock,
           "未持锁=%s 回执=%s" % (_nolock, _acked))

print("== K 组：非恒真对照 ==")
for _i in range(3):
    _fg.reinforce(_ser, "policy", content=BASE + "\nSER%03d" % _i, actor="k1")
_serbody = (_ser.get("policy") or {}).get("content") or ""
_serfm = (_ser.get("policy") or {}).get("frontmatter") or {}
_check("K1 单进程串行 3 次 MERGE：3 条新值照旧全部追加、merge_count=3",
       all(("SER%03d" % i) in _serbody for i in range(3)) and _serfm.get("merge_count") == 3,
       "merge_count=%s" % _serfm.get("merge_count"))
_check("K2 converge_into 目标缺失仍返回 target_missing（错误语义不变）",
       _wl.converge_into(_ser, "no_such_node", "x") == {"ok": False, "error": "target_missing"})
_check("K3 reinforce 目标缺失仍返回 None（错误语义不变）",
       _fg.reinforce(_ser, "no_such_node", content="x") is None)
_ser.close()

print("== E 组：单点 ==")
# 按字节码名字表判（不按源码文本判）：converge_into 的文档字符串里也提到
# merge_rmw_lock，用 getsource 会恒真——那样这条断言挡不住 V2 变异。
_check("E1 两个落点共用同一把锁（reinforce 走装饰器、converge_into 走 merge_rmw_lock）",
       getattr(_fg.reinforce, "__wrapped__", None) is not None
       and "merge_rmw_lock" in _wl.converge_into.__code__.co_names,
       _wl.converge_into.__code__.co_names)

shutil.rmtree(_TMP, ignore_errors=True)

print("")
if FAILS:
    print("issue #348-B 结果：%d 失败" % len(FAILS))
else:
    print("issue #348-B 结果：全部通过")

# ------------------------------------------------------------------ 定点变异
# 锚点按换行符构造，_mutate 里按目标文件实际行尾折算。
_MUTATIONS = (
    ("V1 摘掉 reinforce 的 merge_rmw_locked 装饰器（回到 #348-B 修前）",
     "md_cg/forgetting.py",
     "# issue #348-B：本函数与 writelimit.converge_into 是同一条读改写的两个落点——" + chr(10)
     + "# 装饰器把整段（含函数开头的 cg.get 读）放进 merge_rmw_lock 的跨进程临界区。" + chr(10)
     + "@merge_rmw_locked" + chr(10),
     "",
     ("B1", "B3", "E1")),
    ("V2 摘掉 converge_into 的取锁（回到 #348-B 修前）",
     "md_cg/writelimit.py",
     "    with forgetting.merge_rmw_lock(cg):" + chr(10)
     + "        return _converge_locked(cg, target, content, override=override," + chr(10)
     + "                                actor=actor, session=session," + chr(10)
     + "                                sensitivity=sensitivity)" + chr(10),
     "    return _converge_locked(cg, target, content, override=override," + chr(10)
     + "                            actor=actor, session=session," + chr(10)
     + "                            sensitivity=sensitivity)" + chr(10),
     ("B2", "E1")),
)


def _mirror_build():
    dst = tempfile.mkdtemp(prefix="iss348b_mut_")
    for name in ("md_cg", "scripts"):
        src = os.path.join(_REPO, name)
        if os.path.isdir(src):
            shutil.copytree(src, os.path.join(dst, name),
                            ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    for name in sorted(os.listdir(_REPO)):
        p = os.path.join(_REPO, name)
        if os.path.isfile(p) and (name.endswith(".py")
                                  or name in ("README.md", "pyproject.toml", "package.json")):
            shutil.copy2(p, os.path.join(dst, name))
    return dst


def _run_in(tree):
    env = dict(os.environ)
    env["PYTHONPATH"] = tree
    env["PYTHONUTF8"] = "1"
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    pr = subprocess.run([sys.executable, "-X", "utf8", "-m",
                         "md_cg.test_audit_20261015_b_merge_rmw_lock"],
                        capture_output=True, text=True, encoding="utf-8",
                        errors="replace", cwd=tree, env=env, timeout=1800)
    out = (pr.stdout or "") + (pr.stderr or "")
    reds = [ln.split("FAIL ", 1)[1].strip()
            for ln in out.splitlines() if "FAIL " in ln]
    return pr.returncode, reds, out


def _mutate():
    print("!! 定点变异自证：把判据改回改动前形态，守卫必须转红")
    tree = _mirror_build()
    try:
        rc, reds, out = _run_in(tree)
        print("  未变异镜像基线：rc=%d 红项=%d（必须 rc=0 且 0 红）" % (rc, len(reds)))
        if rc != 0 or reds:
            print(chr(10).join(out.splitlines()[-25:]))
        ok, bad = 0, []
        for desc, rel, old, new, exp in _MUTATIONS:
            p = os.path.join(tree, rel)
            raw = open(p, "rb").read()
            _nl = "\r\n" if b"\r\n" in raw[:8192] else "\n"
            t = raw.decode("utf-8")
            old = old.replace("\n", _nl)
            new = new.replace("\n", _nl)
            if t.count(old) != 1:
                bad.append("%s —— 锚点命中 %d 次" % (desc, t.count(old)))
                print("  ANCHOR-MISS " + desc)
                continue
            bak = t
            open(p, "w", encoding="utf-8", newline="").write(t.replace(old, new, 1))
            rc2, reds2, out2 = _run_in(tree)
            open(p, "w", encoding="utf-8", newline="").write(bak)
            hit = [r for r in reds2 if r.startswith(exp)]
            # 断言名可能多行同前缀（B1 有两条断言），故按**前缀集合**判命中：
            # 变异必须打红且恰打红预期的那些判据组（多打红也算不合格）。
            got = sorted({r.split(" ", 1)[0] for r in reds2})
            if rc2 != 0 and got == sorted(set(exp)):
                ok += 1
                print("  OK   %s  红项=%d 指定命中=%s" % (desc, len(reds2), got))
            else:
                bad.append(desc)
                print("  MISMATCH %s  红项=%d 指定命中=%d/%d rc=%d"
                      % (desc, len(reds2), len(hit), len(exp), rc2))
                for r in reds2[:8]:
                    print("        FAIL " + r)
        print("定点变异自证：%s（%d 条不合格）"
              % ("PASS" if not bad else "FAIL", len(bad)))
        for b in bad:
            print("  不合格：" + b)
    finally:
        shutil.rmtree(tree, ignore_errors=True)


def main():
    if "--mutate" in sys.argv:
        _mutate()
    return 0 if not FAILS else 1


if __name__ == "__main__":
    sys.exit(main())
