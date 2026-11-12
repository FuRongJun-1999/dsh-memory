# -*- coding: utf-8 -*-
# 功能名：#348-B MERGE/CONVERGE 目标读改写的跨进程锁（reinforce/converge_into + 审核 merge 支）
# 生效条件：python -X utf8 -m md_cg.test_issue348_merge_rmw_lock [--mutate]；
#   被测面=md_cg/mdcos.py 中**六处** `with merge_rmw_lock(self):` 落点
#   （_mutation_execute 的 B 合并两原语、review_decide 的 merge 支、maintain prefeed 的
#   reinforce、remember_gated 的 CONVERGE 支与 MERGE 支）与 md_cg/fsutil.py 的 merge_rmw_lock
# 子功能：A1=4 进程并发 remember_gated 到同一 MERGE 目标（加宽读改写窗口）——
#   已回执 MERGE 的新值必须全部在目标正文里；A2=另两轮合计丢失 0；
#   K1=串行 MERGE 仍追加（锁不是空操作/不吞聚合）；
#   E1=merge_rmw_lock 走 FileLock strict；E2/E3a/E3b/E3c=逐落点结构锚；
#   E3d=六处落点计数（防只改一半）；E4=审核 accept 的 merge 支整段在锁内。
#   **CONVERGE 支只有结构锚 E2，无并发行为腿**——CONVERGE 需要 remember_gated 判出
#   冲突才走到，构造成本高且与 MERGE 共用同一把根锁（同一原语同一锁），故行为面由
#   MERGE 腿代偿；此点如实写明，不宣称已覆盖 CONVERGE 的行为面。
# 执行：每轮新建隔离库；写者各自独立进程自旋对齐后并发 remember_gated；
#   worker 内把 forgetting.aggregate_line 包一层睡 0.3s——只拉长「读到旧正文 → 写回」
#   的窗口，不改任何判据（#348 报告 B.3 的定向验收手法）
# 验证方式：全部 PASS 即通过（rc=0）；--mutate 走镜像树定点变异，红项集合须恰为预期
# 不适用条件：① 不测缺省 confirm 档（该档 MERGE 先出变更单、不进合并原语——报告 B.1 前提）；
#   ② 不测吞吐/锁开销；③ 不判「不同目标是否并行」（按根一把是刻意的粒度选择，见
#   fsutil.merge_rmw_lock 文档串）；④ 不覆盖 CONVERGE 的行为面（理由见「子功能」末段）
"""#348-B 守卫：MERGE/CONVERGE 的「读目标 → 聚合 → 整份覆写」必须跨进程互斥。

病象（修前，探针 .tmp/u06/probe_348b.py 实测）：4 进程 × 5 轮，MERGE 回执 20 条、
新值丢失 15 条（5/5 轮）——后写者用自己读到的旧正文整份覆盖前者刚追加的聚合行，
两边都回执 MERGE，被覆盖的新值在库里 0 命中、merge_count 也少加。
"""
import os
import shutil
import subprocess
import sys
import tempfile

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO not in sys.path:
    sys.path.insert(0, _REPO)

PASSED, FAILS = [], []
NL = chr(10)

BASE = ("差旅报销上限 15000 元，负责人张三，财务部审批，发票须在 30 天内提交，"
        "超标需副总签字，住宿标准一线城市 600 元每晚，二线城市 400 元每晚，"
        "餐补每天 100 元，交通费实报实销")

#: 并发 MERGE worker：加宽 aggregate_line 的读改写窗口（只 sleep，不改判据）。
_W_MERGE = r'''
import json, sys, time
sys.path.insert(0, sys.argv[1])
from md_cg.mdcos import MdCGOS
from md_cg import forgetting
root, i, t0, base = sys.argv[2], int(sys.argv[3]), float(sys.argv[4]), sys.argv[5]
_orig = forgetting.aggregate_line
def _slow(old, new):
    time.sleep(0.3)
    return _orig(old, new)
forgetting.aggregate_line = _slow
cg = MdCGOS(root)
while time.time() < t0:
    pass
r = cg.remember_gated(None, base + "\nVAL%04d" % (7000 + i),
                      layer="contextual", role="user")
cg.close()
print(json.dumps({"i": i, "verdict": r.get("verdict"),
                  "merged_into": r.get("merged_into")}))
'''


def _check(n, c, d=''):
    if c:
        print('  PASS ' + n)
        PASSED.append(n)
    else:
        print('  FAIL ' + n + '  ' + str(d)[:200])
        FAILS.append(n)


def _env(t, root):
    env = {k: v for k, v in os.environ.items()
           if not k.startswith(("MDCG_", "PYTHON"))}
    for k, d in (("HOME", "home"), ("MDCG_STATE_ROOT", "state"),
                 ("MDCG_AUX_ROOT", "auxstore"), ("MDCG_DATA_ROOT", "data"),
                 ("MDCG_EXPORT_ROOT", "export")):
        env[k] = os.path.join(t, d)
        os.makedirs(env[k])
    env.update(MDCG_ROOT=root, MDCG_AUTONOMY="full", MDCG_SUSTAIN="0",
               MDCG_SLEEP="0", PYTHONUTF8="1", PYTHONPATH=_REPO)
    return env


def _seed(env, root):
    subprocess.run(
        [sys.executable, "-X", "utf8", "-c",
         "import sys;sys.path.insert(0,sys.argv[1]);"
         "from md_cg.mdcos import MdCGOS;"
         "cg=MdCGOS(sys.argv[2]);cg.add('policy',sys.argv[3],layer='contextual');"
         "cg.close()", _REPO, root, BASE],
        env=env, check=True, cwd=env["HOME"], capture_output=True)


def _policy_body(root):
    for dirpath, _d, files in os.walk(root):
        if "policy.md" in files:
            with open(os.path.join(dirpath, "policy.md"),
                      encoding="utf-8") as f:
                return f.read()
    return ""


def _round(tag, k=4):
    t = tempfile.mkdtemp(prefix="i348b_" + tag + "_")
    root = os.path.join(t, "root")
    env = _env(t, root)
    _seed(env, root)
    t0 = __import__("time").time() + 2.0
    ps = [subprocess.Popen(
        [sys.executable, "-X", "utf8", "-c", _W_MERGE, _REPO, root, str(i),
         str(t0), BASE], env=env, cwd=env["HOME"],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        encoding="utf-8", errors="replace")
        for i in range(k)]
    res = []
    for p in ps:
        o, e = p.communicate(timeout=180)
        try:
            res.append(__import__("json").loads(o.strip().splitlines()[-1]))
        except Exception:
            res.append({"i": -1, "verdict": "ERR " + e.strip()[-120:]})
    return res, _policy_body(root)


def group_a1():
    print('== A1：4 进程并发 MERGE 到同一目标（加宽窗口）==')
    res, body = _round("a1")
    ok = [r["i"] for r in res if r.get("verdict") == "MERGE"]
    miss = [i for i in ok if "VAL%04d" % (7000 + i) not in body]
    print("   verdicts=%s 丢失=%s" % ([r.get("verdict") for r in res], miss))
    _check('A1a 全部写者都回执 MERGE（前提成立，否则本腿无效）',
           len(ok) == 4, [r.get("verdict") for r in res])
    _check('A1b 已回执 MERGE 的新值 100% 在目标正文里（丢失 0）',
           len(ok) == 4 and not miss, miss)


def group_a2():
    print('== A2：连跑 2 轮（判据稳定，不是单轮偶然）==')
    lost = 0
    for _ in range(2):
        res, body = _round("a2")
        ok = [r["i"] for r in res if r.get("verdict") == "MERGE"]
        lost += len([i for i in ok if "VAL%04d" % (7000 + i) not in body])
    _check('A2 两轮合计丢失 0', lost == 0, lost)


def group_k1():
    print('== K1：串行 MERGE 仍追加（锁不吞聚合、不卡死）==')
    t = tempfile.mkdtemp(prefix="i348b_k1_")
    root = os.path.join(t, "root")
    env = _env(t, root)
    old = dict(os.environ)
    try:
        os.environ.update({k: v for k, v in env.items()
                           if k.startswith(("MDCG_", "HOME"))})
        from md_cg.mdcos import MdCGOS
        cg = MdCGOS(root)
        cg.add("policy", BASE, layer="contextual")
        r1 = cg.remember_gated(None, BASE + "\nVAL7001", layer="contextual",
                               role="user")
        r2 = cg.remember_gated(None, BASE + "\nVAL7002", layer="contextual",
                               role="user")
        got = cg.get("policy") or {}
        cg.close()
    finally:
        os.environ.clear()
        os.environ.update(old)
    body = got.get("content") or ""
    _check('K1 串行两次 MERGE 都回执 MERGE 且两值都在正文',
           r1.get("verdict") == "MERGE" and r2.get("verdict") == "MERGE"
           and "VAL7001" in body and "VAL7002" in body,
           (r1.get("verdict"), r2.get("verdict"), body[-120:]))


def _src(rel):
    with open(os.path.join(_REPO, rel), encoding="utf-8") as f:
        return f.read()


def group_e():
    print('== E 组：结构锚（fail-closed）==')
    fs = _src("md_cg/fsutil.py")
    mo = _src("md_cg/mdcos.py")
    _check('E1 merge_rmw_lock 走 FileLock 且 strict=True',
           "def merge_rmw_lock" in fs and "strict=True" in fs
           and "FileLock(" in fs)
    # 六个落点（remember_gated 的 MERGE/CONVERGE、maintain prefeed、变更单执行
    # 的两原语、审核 accept 的 merge 支）都必须出现 `with merge_rmw_lock(self):`。
    # 判据是「整次原语调用被这一行包住」——用原文片段钉（不靠行号）。
    _check('E2 remember_gated CONVERGE 支在 merge_rmw_lock 内',
           "with merge_rmw_lock(self):" + NL + "                    _conv = "
           "writelimit.converge_into(" in mo)
    _check('E3a remember_gated MERGE 支在 merge_rmw_lock 内',
           "with merge_rmw_lock(self):" + NL + "                    "
           'out["reinforced"] = forgetting.reinforce(' in mo)
    _check('E3b maintain prefeed 的 reinforce 在 merge_rmw_lock 内',
           "with merge_rmw_lock(self):" + NL + "                "
           'out["reinforced"] = forgetting.reinforce(' in mo)
    _check('E3c 变更单执行（B 合并）两原语都在 merge_rmw_lock 内',
           "with merge_rmw_lock(self):" + NL + "                        res = "
           "writelimit.converge_into(self, tgt, after," in mo
           and "with merge_rmw_lock(self):" + NL + "                        res = "
           "forgetting.reinforce(self, tgt, override=_ovr," in mo)
    _check('E3d 六处落点齐全（计数口径，防只改一半）',
           mo.count("with merge_rmw_lock(self):") == 6,
           mo.count("with merge_rmw_lock(self):"))
    # 精确绑定审核 merge 支：从 `else:  # merge` 起的切片里必须出现锁行
    # （M2 把它换成 `if True:` 时该切片内不再有锁 ⇒ E4 单独转红）。
    _seg4 = mo.split("else:  # merge", 1)[1][:3000] if "else:  # merge" in mo else ""
    _check('E4 审核 accept 的 merge 支整段在 merge_rmw_lock 内',
           "with merge_rmw_lock(self):" in _seg4)


def main():
    print('== #348-B 守卫 ==')
    try:
        group_a1()
        group_a2()
        group_k1()
    except Exception as e:
        import traceback
        traceback.print_exc()
        _check('A/K 组内异常（fail-closed）', False, str(e)[:150])
    group_e()
    print('=' * 62)
    print('#348-B 守卫：%d 通过，%d 失败' % (len(PASSED), len(FAILS)))
    for f in FAILS:
        print('  红项：' + f)
    return 0 if not FAILS else 1


def _mirror():
    """镜像树：md_cg 包 + 仓根一级模块 + data/policy.json（写链的包内默认策略）。"""
    d = tempfile.mkdtemp(prefix="i348b_mirror_")
    shutil.copytree(os.path.join(_REPO, "md_cg"),
                    os.path.join(d, "md_cg"),
                    ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    for fn in os.listdir(_REPO):
        if fn.endswith(".py") and os.path.isfile(os.path.join(_REPO, fn)):
            shutil.copy2(os.path.join(_REPO, fn), os.path.join(d, fn))
    src_pol = os.path.join(_REPO, "data", "policy.json")
    if os.path.exists(src_pol):
        os.makedirs(os.path.join(d, "data"), exist_ok=True)
        shutil.copy2(src_pol, os.path.join(d, "data", "policy.json"))
    return d


def _run_in(tree):
    p = subprocess.run([sys.executable, "-X", "utf8", "-m",
                        "md_cg.test_issue348_merge_rmw_lock"],
                       cwd=tree, capture_output=True, text=True, timeout=2400,
                       encoding="utf-8", errors="replace",
                       env=dict({k: v for k, v in os.environ.items()
                                 if not k.startswith("PYTHON")},
                                PYTHONPATH=tree, PYTHONUTF8="1"))
    reds = [ln.strip().split("  ", 1)[0].replace("FAIL ", "")
            for ln in p.stdout.splitlines() if ln.strip().startswith("FAIL ")]
    return p.returncode, reds, p.stdout + p.stderr


_MUTATIONS = [
    # M1：把 remember_gated MERGE 支的锁换成 `if True:`（缩进不变 ⇒ 只撤互斥，
    # 不改语义分支）——并发腿 A1b/A2 必须转红，结构锚 E3a 一并转红。
    ("M1 撤 remember_gated MERGE 支的跨进程锁",
     [("md_cg/mdcos.py",
       "                with merge_rmw_lock(self):" + NL +
       "                    out[\"reinforced\"] = forgetting.reinforce(",
       "                if True:" + NL +
       "                    out[\"reinforced\"] = forgetting.reinforce(")],
     ("A1b", "A2", "E3a", "E3d")),
    # M2：审核 accept 的 merge 支同款撤锁。
    ("M2 撤审核 accept 的 merge 支锁",
     [("md_cg/mdcos.py",
       "            with merge_rmw_lock(self):" + NL +
       "                target = merge_into or "
       "(item.get(\"extra\") or {}).get(\"merge_into\")",
       "            if True:" + NL +
       "                target = merge_into or "
       "(item.get(\"extra\") or {}).get(\"merge_into\")")],
     ("E4", "E3d")),
]

def _mutate():
    print('!! 定点变异自证：把锁撤掉，守卫必须转红')
    tree = _mirror()
    try:
        rc, reds, out = _run_in(tree)
        print('  未变异镜像基线：rc=%d 红项=%d（须 rc=0/0 红）' % (rc, len(reds)))
        if rc != 0 or reds:
            print(chr(10).join(out.splitlines()[-25:]))
        bad = []
        for desc, edits, exp in _MUTATIONS:
            backups = []
            miss = []
            for rel, oldp, newp in edits:
                p = os.path.join(tree, rel)
                with open(p, encoding="utf-8", newline="") as f:
                    t = f.read()
                if t.count(oldp) != 1:
                    miss.append("%s 命中 %d 次" % (rel, t.count(oldp)))
                    continue
                backups.append((p, t))
                with open(p, "w", encoding="utf-8", newline="") as f:
                    f.write(t.replace(oldp, newp, 1))
            if miss:
                bad.append("%s —— %s" % (desc, "；".join(miss)))
                print('  ANCHOR-MISS ' + desc)
                for p, t in backups:
                    with open(p, "w", encoding="utf-8", newline="") as f:
                        f.write(t)
                continue
            rc2, reds2, out2 = _run_in(tree)
            for p, t in backups:
                with open(p, "w", encoding="utf-8", newline="") as f:
                    f.write(t)
            hit = sorted({e for r in reds2 for e in exp
                          if r.startswith(e)})
            if rc2 != 0 and hit == sorted(exp):
                print('  OK   %s  红项=%s' % (desc, reds2))
            else:
                bad.append(desc)
                print('  MISMATCH %s rc=%d 红项=%s' % (desc, rc2, reds2))
                print(chr(10).join(out2.splitlines()[-20:]))
        print('定点变异自证：%s（%d 条不合格）'
              % ('PASS' if not bad else 'FAIL', len(bad)))
        for b in bad:
            print('  不合格：' + b)
        _check('变异自证全过', not bad, bad)
    finally:
        shutil.rmtree(tree, ignore_errors=True)


if __name__ == '__main__':
    if '--mutate' in sys.argv:
        _mutate()
        sys.exit(0 if not FAILS else 1)
    sys.exit(main())
