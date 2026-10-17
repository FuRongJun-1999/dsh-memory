# -*- coding: utf-8 -*-
# 功能名：#322 同一 node_id 并发写的跨进程串行化（writepipe 写链 + MdCGOS.add/_move_layer 库层）
# 生效条件：python -X utf8 -m md_cg.test_issue322_node_write_lock [--mutate]；
#   被测面=md_cg/writepipe.py 的 WritePipeline.execute、md_cg/mdcos.py 的 MdCGOS.add、
#   MdCGSecure.add、MdCGOS._move_layer、md_cg/fsutil.py 的 node_write_lock
# 子功能：A1=writepipe 并发同 id（3 进程 × 2 轮）不丢正文且至多一个 committed；
#   A2=writepipe anchor/knowledge 同 id 并发不得两份并存；A3=**库层** cg.add 直接并发
#   anchor/knowledge 同 id 不得两份并存（钉 add 自己的锁，不靠 writepipe）；
#   A4=**_move_layer 与 add 并发同 id**（搬迁的读旧位置→写新层→删旧文件 vs 覆写）——
#   已应答的 add 新值不得被搬迁写下的旧正文顶掉；A5=**密级继承的读改写**
#   （A 显式声明 internal 覆写 / B 未声明应继承当前密级）——盘面不得被陈旧索引降级回
#   public；K1=串行覆写仍真生效（锁不是空操作）；
#   E1/E2=结构锚（走 FileLock + strict、不用进程内锁）；E3/E4/E5/E5b/E6=各落点在锁块内
#   （E5b=密级继承读前先做跨进程代际探活：互斥 ≠ 读到新值）
# 执行：每轮新建隔离库；写者各自独立进程自旋对齐后并发写同一 id；读盘面同 id 文件集合
# 验证方式：全部 PASS 即通过（rc=0）；--mutate 走镜像树定点变异，红项集合须恰为预期
# 不适用条件：① 不测吞吐/锁开销（那是性能面，不是本缺陷）；② 不覆盖 Windows 之外的
#   OS 锁实现差异（FileLock 自身的语义由既有守卫负责）；③ 不判「不同 node_id 是否并行」
#   （按 id 分锁的设计意图，不是本缺陷的验收面）；④ 不覆盖**直接构造 `MdCG`**（父类）
#   的搬迁路径——锁的覆盖点在 `MdCGOS`（子类覆盖），`md_cg/mdcg.py` 不在本单元写面
"""#322 守卫：同 id 并发写必须被同一把**跨进程**锁串行化。

病象（修前，探针 .tmp/u06/probe_322.py 实测）：
  · 普通腿 6/6 轮：4 个写者全部回执 committed:true，盘面只有 1 份正文，
    其余 3 份**已应答却从 root 里消失**（静默丢正文）；
  · anchor 腿 6/6 轮：anchor 与 knowledge 各写同 id，盘面**两份并存**
    （anchor\\x.md + knowledge/orphan\\x.md），保护闸在两侧都看不到对方
    ⇒ 保护被绕过。
  · 搬迁腿（`.tmp/u06/probe_move_add.py`）3/3 轮：`_move_layer` 读到旧位置后
    慢写新层，并发的 add 已应答的新正文被搬迁写下的旧正文顶掉。
  · 密级继承腿（`.tmp/u06/probe_secure_add.py`）：无锁 6/6 轮、只加 add 锁仍 3/6 轮
    ——B 按**陈旧内存索引**继承密级，把他进程刚落盘的 internal 静默降级回 public。
修法（单点）：fsutil.node_write_lock（OS 级 FileLock + 同线程重入计数），
writepipe.execute 整条链 + MdCGOS.add / MdCGSecure.add / MdCGOS._move_layer
各持同一把（同线程重入不互锁）；密级继承读之前另做一次
`_maybe_reload_index` 代际探活（锁保证互斥，探活保证读到新值）。
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

CCG = ("# 功能名：并发写守卫夹具\n"
       "# 生效条件：多进程同 id 同 root 并发写\n"
       "# 子功能：无\n"
       "# 执行：无\n"
       "# 验证方式：无\n"
       "# 不适用条件：无\n"
       "%s\n")

_W_WRITEPIPE = r'''
import json, sys, time
sys.path.insert(0, sys.argv[1])
from md_cg.mdcos import MdCGOS
from md_cg.writepipe import default_pipeline
root, nid, layer, body, t0 = sys.argv[2], sys.argv[3], sys.argv[4], sys.argv[5], float(sys.argv[6])
cg = MdCGOS(root)
while time.time() < t0:
    pass
try:
    r = default_pipeline().execute(cg, {"node_id": nid, "content": body,
                                       "layer": layer, "content_kind": "text"})
    out = {"ok": r.get("ok"), "committed": r.get("committed"),
           "error": r.get("error")}
except Exception as exc:
    out = {"ok": False, "committed": False,
           "error": type(exc).__name__ + ": " + str(exc)[:90]}
try:
    cg.close()
except Exception:
    pass
print(json.dumps(out, ensure_ascii=False))
'''

_W_ADD = r'''
import json, sys, time
sys.path.insert(0, sys.argv[1])
from md_cg.mdcos import MdCGOS
root, nid, layer, body, t0 = sys.argv[2], sys.argv[3], sys.argv[4], sys.argv[5], float(sys.argv[6])
cg = MdCGOS(root)
while time.time() < t0:
    pass
try:
    cg.add(nid, body, layer=layer)
    out = {"ok": True, "committed": True, "error": None}
except Exception as exc:
    out = {"ok": False, "committed": False,
           "error": type(exc).__name__ + ": " + str(exc)[:90]}
try:
    cg.close()
except Exception:
    pass
print(json.dumps(out, ensure_ascii=False))
'''

#: 搬迁腿：把基类 `_write_node` 包一层 sleep 0.5s（只拉长「读到旧位置 → 写新层 →
#: 删旧文件」的窗口，不改任何判据），再对同一 id 调 `_move_layer`。
_W_MOVE = r'''
import json, sys, time
sys.path.insert(0, sys.argv[1])
from md_cg.mdcos import MdCGOS
from md_cg.mdcg import MdCG
root, nid, t0 = sys.argv[2], sys.argv[3], float(sys.argv[4])
_o = MdCG._write_node
def _slow(self, *a, **k):
    time.sleep(0.5)
    return _o(self, *a, **k)
MdCG._write_node = _slow
cg = MdCGOS(root)
while time.time() < t0:
    pass
try:
    r = cg._move_layer(nid, "contextual", reason="i322-guard")
    out = {"ok": True, "committed": True,
           "error": None, "to": (r or {}).get("to")}
except Exception as exc:
    out = {"ok": False, "committed": False,
           "error": type(exc).__name__ + ": " + str(exc)[:90]}
try:
    cg.close()
except Exception:
    pass
print(json.dumps(out, ensure_ascii=False))
'''


def _check(n, c, d=''):
    if c:
        print('  PASS ' + n)
        PASSED.append(n)
    else:
        print('  FAIL ' + n + '  ' + str(d)[:200])
        FAILS.append(n)


def _env(t):
    env = {k: v for k, v in os.environ.items()
           if not k.startswith(("MDCG_", "PYTHON"))}
    for k, d in (("HOME", "home"), ("MDCG_STATE_ROOT", "state"),
                 ("MDCG_AUX_ROOT", "auxstore"), ("MDCG_DATA_ROOT", "data"),
                 ("MDCG_EXPORT_ROOT", "export")):
        env[k] = os.path.join(t, d)
        os.makedirs(env[k])
    env.update(MDCG_SUSTAIN="0", MDCG_SLEEP="0", PYTHONUTF8="1",
               PYTHONPATH=_REPO)
    return env


def _race(root, env, worker, writers):
    t0 = __import__("time").time() + 1.5
    ps = [subprocess.Popen([sys.executable, "-X", "utf8", "-c", worker, _REPO,
                            root, nid, layer, body, str(t0)], env=env,
                           cwd=env["HOME"], stdout=subprocess.PIPE,
                           stderr=subprocess.PIPE, text=True)
          for nid, layer, body in writers]
    res = []
    for p in ps:
        o, e = p.communicate(timeout=180)
        try:
            res.append(__import__("json").loads(o.strip().splitlines()[-1]))
        except Exception:
            res.append({"ok": False, "committed": False,
                        "error": "ERR " + e.strip()[-120:]})
    return res


def _same_id_files(root, nid):
    out = []
    for dirpath, _d, files in os.walk(root):
        for fn in files:
            if fn == nid + ".md":
                out.append(os.path.relpath(os.path.join(dirpath, fn), root))
    return sorted(out)


def _one_round(worker, writers, tag):
    t = tempfile.mkdtemp(prefix="i322_" + tag + "_")
    env = _env(t)
    root = os.path.join(t, "root")
    res = _race(root, env, worker, writers)
    files = _same_id_files(root, writers[0][0])
    return res, files, root


def _body_of(root, nid):
    """从盘面读回该 id 节点的正文（唯一一份时）。"""
    for dirpath, _d, files in os.walk(root):
        if nid + ".md" in files:
            with open(os.path.join(dirpath, nid + ".md"),
                      encoding="utf-8") as f:
                return f.read()
    return ""


#: A4 的 add 腿：在 `_write_node` 里睡 0.4s（< 搬迁腿的 0.5s）——把「add 正在落盘」
#: 精确放进「搬迁已读完旧位置、还没删旧文件」的窗口。**只拉长窗口，不改判据**。
_W_ADD_SLOW = r'''
import json, sys, time
sys.path.insert(0, sys.argv[1])
from md_cg.mdcos import MdCGOS
from md_cg.mdcg import MdCG
root, nid, layer, body, t0 = sys.argv[2], sys.argv[3], sys.argv[4], sys.argv[5], float(sys.argv[6])
_o = MdCG._write_node
def _slow(self, *a, **k):
    time.sleep(0.4)
    return _o(self, *a, **k)
MdCG._write_node = _slow
cg = MdCGOS(root)
while time.time() < t0:
    pass
try:
    cg.add(nid, body, layer=layer)
    out = {"ok": True, "committed": True, "error": None}
except Exception as exc:
    out = {"ok": False, "committed": False,
           "error": type(exc).__name__ + ": " + str(exc)[:90]}
try:
    cg.close()
except Exception:
    pass
print(json.dumps(out, ensure_ascii=False))
'''


#: A5 的 worker：带 principal 的写（密级继承面）。`delay` 非 0 时在
#: `_write_sensitivity` **解析完旧密级之后**睡一会儿——这正是「读到旧值 → 据此落盘」
#: 的窗口（只拉长窗口，不改判据）。
_W_SECURE = r'''
import json, sys, time
sys.path.insert(0, sys.argv[1])
from md_cg.mdcos import MdCGSecure
from md_cg.security import Principal
from md_cg.tokens import role_spec
root, nid, body, sens, delay, t0 = (sys.argv[2], sys.argv[3], sys.argv[4],
                                   sys.argv[5], float(sys.argv[6]),
                                   float(sys.argv[7]))
sp = role_spec("designer")
cg = MdCGSecure(root, principal=Principal(
    actor="designer", clearance="secret", can_write=True, can_admin=True,
    role="designer", layers_allow=sp["layers_allow"],
    ops_allow=sp["ops_allow"]))
if delay:
    _o = cg._write_sensitivity
    def _slow(node_id, declared):
        s = _o(node_id, declared)
        time.sleep(delay)
        return s
    cg._write_sensitivity = _slow
while time.time() < t0:
    pass
try:
    cg.add(nid, body, layer="knowledge", sensitivity=(sens or None))
    out = {"ok": True, "committed": True, "error": None}
except Exception as exc:
    out = {"ok": False, "committed": False,
           "error": type(exc).__name__ + ": " + str(exc)[:90]}
try:
    cg.close()
except Exception:
    pass
print(json.dumps(out, ensure_ascii=False))
'''


def _sens_on_disk(root, nid):
    """盘面 frontmatter 里的 sensitivity 字面量（取不到返回 None）。"""
    import re
    for dirpath, _d, files in os.walk(root):
        if nid + ".md" in files:
            with open(os.path.join(dirpath, nid + ".md"),
                      encoding="utf-8") as f:
                m = re.search(r"^sensitivity:\s*\"?([A-Za-z]+)\"?",
                              f.read(), re.M)
                return m.group(1) if m else None
    return None


def _bodies_of(root, nid):
    """盘面上所有同 id 文件的正文（同 id 可能并存于多层——那本身就是缺陷，
    故 A4 判「新值是否在**任意一份**里」，而不是只看先遍历到的那份）。"""
    out = []
    for dirpath, _d, files in os.walk(root):
        if nid + ".md" in files:
            with open(os.path.join(dirpath, nid + ".md"),
                      encoding="utf-8") as f:
                out.append(f.read())
    return out


def group_a1():
    print('== A1：writepipe 并发同 id（3 进程 × 2 轮）==')
    bad_files = 0
    multi = 0
    lost = 0
    for rd in range(2):
        nid = "race_same"
        writers = [(nid, "knowledge", CCG % ("BODY-%04d" % i))
                   for i in range(3)]
        res, files, root = _one_round(_W_WRITEPIPE, writers, "a1")
        committed = [i for i, r in enumerate(res) if r.get("committed")]
        text = _body_of(root, nid)
        hit = [i for i in committed if "BODY-%04d" % i in text]
        bad_files += int(len(files) != 1)
        multi += int(len(committed) > 1)
        lost += len(committed) - len(hit)
        print("   round %d: committed=%s files=%s 命中=%s"
              % (rd, committed, files, hit))
    _check('A1a 盘面同 id 文件恒为 1 份（不并存）', bad_files == 0, bad_files)
    _check('A1b 并发下至多一个写者回执 committed（其余入审核队列/被拒）',
           multi == 0, multi)
    _check('A1c 已回执 committed 的正文 100% 在盘面（丢失 0）', lost == 0, lost)


def group_a2():
    print('== A2：writepipe anchor/knowledge 同 id 并发（2 轮）==')
    coex = 0
    for rd in range(2):
        nid = "race_anchor"
        res, files, _root = _one_round(
            _W_WRITEPIPE,
            [(nid, "anchor", CCG % "ANCHOR-BODY"),
             (nid, "knowledge", CCG % "KNOW-BODY")], "a2")
        coex += int(len(files) > 1)
        print("   round %d: files=%s res=%s"
              % (rd, files, [(r.get("committed"),
                              str(r.get("error") or "")[:40]) for r in res]))
    _check('A2 同 id 的 anchor 与 knowledge 两份文件不得并存', coex == 0, coex)


def group_a3():
    print('== A3：库层 cg.add 直接并发 anchor/knowledge 同 id（2 轮）==')
    coex = 0
    for rd in range(2):
        nid = "race_add_anchor"
        res, files, _root = _one_round(
            _W_ADD,
            [(nid, "anchor", CCG % "ANCHOR-BODY"),
             (nid, "knowledge", CCG % "KNOW-BODY")], "a3")
        coex += int(len(files) > 1)
        print("   round %d: files=%s res=%s"
              % (rd, files, [(r.get("committed"),
                              str(r.get("error") or "")[:40]) for r in res]))
    _check('A3 库层 add 并发同 id 也不得两份并存（add 自己的锁在位）',
           coex == 0, coex)


def group_a4():
    print('== A4：_move_layer 与 add 并发同 id（搬迁读改写 vs 覆写，2 轮）==')
    import json as _json
    import time as _time
    lost = 0
    for rd in range(2):
        t = tempfile.mkdtemp(prefix="i322_a4_")
        env = _env(t)
        root = os.path.join(t, "root")
        nid = "race_move"
        old = dict(os.environ)
        try:
            os.environ.update({k: v for k, v in env.items()
                               if k.startswith(("MDCG_", "HOME"))})
            from md_cg.mdcos import MdCGOS
            _cg = MdCGOS(root)
            _cg.add(nid, CCG % "OLD-BODY", layer="knowledge")
            _cg.close()
        finally:
            os.environ.clear()
            os.environ.update(old)
        t0 = _time.time() + 1.5
        ps = []
        for worker, extra in ((_W_MOVE, [nid, str(t0)]),
                              (_W_ADD_SLOW, [nid, "knowledge",
                                             CCG % "NEW-BODY", str(t0)])):
            ps.append(subprocess.Popen(
                [sys.executable, "-X", "utf8", "-c", worker, _REPO,
                 root] + extra, env=env, cwd=env["HOME"],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True))
        res = []
        for p in ps:
            o, e = p.communicate(timeout=180)
            try:
                res.append(_json.loads(o.strip().splitlines()[-1]))
            except Exception:
                res.append({"ok": False, "error": "ERR " + e.strip()[-120:]})
        bodies = _bodies_of(root, nid)
        hit = any("NEW-BODY" in t for t in bodies)
        lost += int(not hit)
        print("   round %d: 新值在盘=%s files=%s res=%s"
              % (rd, hit, _same_id_files(root, nid),
                 [(r.get("committed"), str(r.get("error") or "")[:36])
                  for r in res]))
    _check('A4 搬迁与 add 并发时，已应答 add 的新正文不得被搬迁的旧正文顶掉',
           lost == 0, lost)


def group_a5():
    print('== A5：MdCGSecure.add 密级继承的读改写（声明 vs 未声明，2 轮）==')
    import json as _json
    import time as _time
    downgraded = 0
    for rd in range(2):
        t = tempfile.mkdtemp(prefix="i322_a5_")
        env = _env(t)
        root = os.path.join(t, "root")
        nid = "race_sens"
        old = dict(os.environ)
        try:
            os.environ.update({k: v for k, v in env.items()
                               if k.startswith(("MDCG_", "HOME"))})
            from md_cg.mdcos import MdCGSecure
            from md_cg.security import Principal
            from md_cg.tokens import role_spec
            sp = role_spec("designer")
            _cg = MdCGSecure(root, principal=Principal(
                actor="designer", clearance="secret", can_write=True,
                can_admin=True, role="designer",
                layers_allow=sp["layers_allow"],
                ops_allow=sp["ops_allow"]))
            _cg.add(nid, CCG % "SEED", layer="knowledge",
                    sensitivity="public")
            _cg.close()
        finally:
            os.environ.clear()
            os.environ.update(old)
        t0 = _time.time() + 1.5
        ps = [
            # A：显式声明 internal，快写
            subprocess.Popen([sys.executable, "-X", "utf8", "-c", _W_SECURE,
                              _REPO, root, nid, CCG % "A-INTERNAL",
                              "internal", "0", str(t0)],
                             env=env, cwd=env["HOME"],
                             stdout=subprocess.PIPE,
                             stderr=subprocess.PIPE, text=True),
            # B：未声明（应继承**当前**密级），读到旧值后睡 0.5s 再落盘
            subprocess.Popen([sys.executable, "-X", "utf8", "-c", _W_SECURE,
                              _REPO, root, nid, CCG % "B-INHERIT",
                              "", "0.5", str(t0)],
                             env=env, cwd=env["HOME"],
                             stdout=subprocess.PIPE,
                             stderr=subprocess.PIPE, text=True),
        ]
        res = []
        for p in ps:
            o, e = p.communicate(timeout=180)
            try:
                res.append(_json.loads(o.strip().splitlines()[-1]))
            except Exception:
                res.append({"ok": False, "error": "ERR " + e.strip()[-120:]})
        final = _sens_on_disk(root, nid)
        bad = final != "internal"
        downgraded += int(bad)
        print("   round %d: 盘面密级=%s 降级=%s res=%s"
              % (rd, final, bad,
                 [(r.get("ok"), str(r.get("error") or "")[:36])
                  for r in res]))
    _check('A5 未声明的同 id 写必须继承他进程刚落盘的密级'
           '（不得按陈旧索引把 internal 静默降级回 public）',
           downgraded == 0, downgraded)


def group_k1():
    print('== K1：串行覆写仍真生效（锁不是空操作/不会永久占锁）==')
    t = tempfile.mkdtemp(prefix="i322_k1_")
    env = _env(t)
    root = os.path.join(t, "root")
    old = dict(os.environ)
    try:
        os.environ.update({k: v for k, v in env.items()
                           if k.startswith(("MDCG_", "HOME"))})
        from md_cg.mdcos import MdCGOS
        cg = MdCGOS(root)
        nid = "serial_node"
        cg.add(nid, CCG % "SERIAL-V1", layer="knowledge")
        cg.add(nid, CCG % "SERIAL-V2", layer="knowledge")   # 同 id 串行覆写
        got = cg.get(nid) or {}
        cg.close()
    finally:
        os.environ.clear()
        os.environ.update(old)
    text = got.get("content") or ""
    _check('K1 串行第二次覆写真落盘（正文为 V2，且锁未卡死/未误吞）',
           "SERIAL-V2" in text, text[-80:])


def _src(rel):
    with open(os.path.join(_REPO, rel), encoding="utf-8") as f:
        return f.read()


def _method_src(cls, name):
    """取运行中方法的源码（与既有守卫 test_session_attribution_consistency:555
    同手法：`inspect.getsource` + `textwrap.dedent`）。用它而不是整文件 grep，
    是因为 `node_write_lock(self, node_id)` 现在在 MdCGOS.add 与 MdCGSecure.add
    各出现一次——整文件计数判不出「哪一层漏了」。"""
    import inspect
    import textwrap
    return textwrap.dedent(inspect.getsource(getattr(cls, name)))


def group_e():
    print('== E 组：结构锚（fail-closed）==')
    from md_cg.mdcos import MdCGOS, MdCGSecure
    fs = _src("md_cg/fsutil.py")
    wp = _src("md_cg/writepipe.py")
    mo = _src("md_cg/mdcos.py")
    _add_src = _method_src(MdCGOS, "add")
    _sec_add_src = _method_src(MdCGSecure, "add")
    _move_src = _method_src(MdCGOS, "_move_layer")
    _ws_src = _method_src(MdCGSecure, "_write_sensitivity")
    _check('E1 node_write_lock 走 FileLock 且 strict=True（不得无锁放行）',
           "def node_write_lock" in fs and "strict=True" in fs
           and "FileLock(" in fs)
    _seg = fs.split("def node_write_lock")[1].split("def merge_rmw_lock")[0]
    _check('E2 不得用进程内锁冒充（node_write_lock 内无 threading.Lock；'
           '重入记账只允许 threading.local）',
           "threading.Lock(" not in _seg and "threading.RLock(" not in _seg,
           _seg[:200])
    _check('E3 writepipe.execute 在 node_write_lock 内跑整条链',
           "with node_write_lock(cg, _nid):" in wp
           and "return self._run_chain(ctx, a)" in wp)
    _check('E4 MdCGOS.add 在 node_write_lock 内落盘（落盘段在锁块内，'
           '不得只把加锁写在函数外/抽成子函数）',
           "with node_write_lock(self, node_id):" in _add_src
           and 'self._audit("add"' in _add_src.split(
               "with node_write_lock(self, node_id):", 1)[1]
           and "def _add_locked" not in mo)
    _check('E5 MdCGSecure.add 的密级继承读改写也在同一把锁内'
           '（_write_sensitivity 读旧值 → 据此落盘，锁在 super 之前）',
           "with node_write_lock(self, node_id):" in _sec_add_src
           and "self._write_sensitivity(node_id, sensitivity)" in
           _sec_add_src.split("with node_write_lock(self, node_id):", 1)[1])
    _check('E5b 密级继承读之前先做跨进程代际探活（_maybe_reload_index）'
           '——锁只保证互斥，不保证读到他进程已落盘的新密级',
           "_maybe_reload_index" in _ws_src
           and _ws_src.index("_maybe_reload_index")
           < _ws_src.index("subgraph.node_sensitivity("))
    _check('E6 MdCGOS._move_layer 在 node_write_lock 内转调父类'
           '（搬迁=同 id 读改写，不经 add，必须单独覆盖）',
           "with node_write_lock(self, node_id):" in _move_src
           and "super()._move_layer(" in
           _move_src.split("with node_write_lock(self, node_id):", 1)[1])


def main():
    print('== #322 守卫 ==')
    # 锚点自检（fail-closed）：修复的关键字面量不在源码里 ⇒ 对应 E 项红 + 整体 rc=1。
    # 不用 exit 2 提前返回：变异自证要求「撤哪一处就红哪一条」，提前退出会让
    # 红项集合为空、判别力无从体现。
    fs = _src("md_cg/fsutil.py")
    wp = _src("md_cg/writepipe.py")
    from md_cg.mdcos import MdCGOS
    _mo_add = _method_src(MdCGOS, "add")
    _check('E0a fsutil.node_write_lock 在位（锚点自检）',
           "def node_write_lock" in fs)
    _check('E0b writepipe 调用 node_write_lock 的锚点在位（锚点自检）',
           "with node_write_lock(cg, _nid):" in wp)
    # 锚点取 **MdCGOS.add 自己的源码**而非整文件：同一条 `with node_write_lock(
    # self, node_id):` 现在在 MdCGOS.add 与 MdCGSecure.add 各出现一次，整文件
    # 计数会让「撤掉 MdCGOS.add 那把锁」时本项仍绿（变异腿实测 M2 漏红）。
    _check('E0c mdcos.add 调用 node_write_lock 的锚点在位（锚点自检）',
           "with node_write_lock(self, node_id):" in _mo_add)
    try:
        group_a1()
        group_a2()
        group_a3()
        group_a4()
        group_a5()
        group_k1()
    except Exception as e:
        import traceback
        traceback.print_exc()
        _check('A/K 组内异常（fail-closed）', False, str(e)[:150])
    group_e()
    print('=' * 62)
    print('#322 守卫：%d 通过，%d 失败' % (len(PASSED), len(FAILS)))
    for f in FAILS:
        print('  红项：' + f)
    return 0 if not FAILS else 1


def _mirror():
    """镜像树：md_cg 包 + data/policy.json（包内默认策略按包根解析，
    缺它则写链在镜像里 policy_unavailable ⇒ 并发腿全被短路，变异判别力假绿）。"""
    d = tempfile.mkdtemp(prefix="i322_mirror_")
    shutil.copytree(os.path.join(_REPO, "md_cg"),
                    os.path.join(d, "md_cg"),
                    ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    # 仓根一级模块（`md_cg/mcp_server.py` 顶部 `from utf8_boot import ensure_utf8`
    # 等）必须一并镜像，否则副本里写链 import 即失败、并发腿全空跑（假红/假绿）。
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
                        "md_cg.test_issue322_node_write_lock"],
                       cwd=tree, capture_output=True, text=True,
                       timeout=1800,
                       env=dict({k: v for k, v in os.environ.items()
                                 if not k.startswith("PYTHON")},
                                PYTHONPATH=tree, PYTHONUTF8="1"))
    reds = [ln.strip().split("  ", 1)[0].replace("FAIL ", "")
            for ln in p.stdout.splitlines() if ln.strip().startswith("FAIL ")]
    return p.returncode, reds, p.stdout + p.stderr


_MUTATIONS = [
    ("M1 撤 writepipe 整链锁", [("md_cg/writepipe.py",
                               "        with node_write_lock(cg, _nid):\n"
                               "            return self._run_chain(ctx, a)",
                               "        return self._run_chain(ctx, a)")],
     # 撤链锁：add 级锁仍在 ⇒ 盘面不会两份并存（A1a/A2 仍绿，如实），
     # 但「判存在 → 定档 → 落盘」的整段不再互斥 ⇒ 两个写者都 committed（A1b）、
     # 输的那份正文从 root 消失（A1c）——正是 #322 的症状。
     ("A1b", "A1c", "E0b", "E3")),
    # M2/M3 用 `if True:` 顶替 `with`（保留缩进/作用域，只把锁去掉）：
    # 行为腿（A3）与结构锚同时可判，且不依赖字符串再缩进。
    ("M2 撤 MdCGOS.add 锁", [("md_cg/mdcos.py",
                            "        with node_write_lock(self, node_id):\n"
                            "            # #151",
                            "        if True:  # MUT\n"
                            "            # #151")],
     ("A3", "E0c", "E4")),
    ("M3 撤 MdCGSecure.add 的密级继承锁", [("md_cg/mdcos.py",
                                        "        with node_write_lock(self, "
                                        "node_id):\n"
                                        "            sens = self."
                                        "_write_sensitivity(",
                                        "        if True:  # MUT\n"
                                        "            sens = self."
                                        "_write_sensitivity(")],
     ("E5",)),
    # M3b：只撤「读前代际探活」——锁与结构锚都还在，只有**行为腿 A5** 能判它
    # （这正是复核意见 5 指出的残留窗口：互斥 ≠ 读到新值）。
    ("M3b 撤密级继承的跨进程代际探活", [("md_cg/mdcos.py",
                                     "        _probe = getattr(self, "
                                     "\"_maybe_reload_index\", None)\n"
                                     "        if callable(_probe):\n"
                                     "            _probe()\n",
                                     "        _probe = None\n")],
     ("A5",)),
    ("M4 撤 MdCGOS._move_layer 的搬迁锁", [("md_cg/mdcos.py",
                                        "        with node_write_lock(self, "
                                        "node_id):\n"
                                        "            return super()."
                                        "_move_layer(",
                                        "        if True:  # MUT\n"
                                        "            return super()."
                                        "_move_layer(")],
     ("A4", "E6")),
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
            hit = sorted({e for r in reds2 for e in exp if r.startswith(e + " ")
                          or r.startswith(e)})
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
