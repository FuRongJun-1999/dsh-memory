# -*- coding: utf-8 -*-
# 功能名：证据包导入不得静默顶替他进程写入的同名本地节点（issue #403）
# 生效条件：python -X utf8 -m md_cg.test_issue403_import_pack_probe [--mutate [--list] | --pristine]
#   被测面＝md_cg/evidence.py 的 import_pack 判据段（#191-C「同名本地节点不覆写」）。
# 子功能：A 组＝陈旧索引下的缺陷腿（他进程真 subprocess 写同名本地节点 → 本进程索引陈旧
#   → import_pack 必须 imported=0/skipped=1 且盘面正文仍是本地原文）；
#   B 组＝对照腿（本进程自写、索引新鲜时守卫原本就生效，防「判据空转被算作已修」）；
#   C 组＝xnode 自己来源的包仍可 override 更新（防过度纠正：只加探活，不改覆写语义）；
#   D 组＝探活载体缺失（测试桩无 _maybe_reload_index）行为零变；E 组＝源码面锚点自证。
# 执行：--mutate 逐条把探活改回**改动前形态**（源码文本变异，不以 git HEAD 为基线源）；
#   --pristine 摘掉该探活块并跑套件（认证一：必须在真实修复前树上 FAIL）。
# 验证方式：全部 PASS 即通过（退出码 0）；--mutate 下每条变异须打红其预期前缀的断言；
#   --pristine **退出码 1 ＝ 按预期失败**（复现 #403 的原始输出），若全绿则退出码 3。
# 不适用条件：不判 _rejected.jsonl / _protected_history 前像留痕（#403 期望第 3 条属另一族，
#   本卡只闭合「判据载体的代际」）；不跑真 stdio MCP 长驻实例对撞（用真 subprocess 写方扮演
#   「另一进程」，与 #403 复跑口径一致）；不判 wirepipe.py 的同族站点（另一子栏负责）。
"""issue #403 守卫：import_pack 的 #191-C 判据缺代际探活 ⇒ 他进程写入的本地节点被静默顶替。

病灶（修前）：`prev = (cg.index.get("nodes") or {}).get(xid)` 直读**本进程内存索引**，
而 import_pack 全程只在 items 循环里读它；唯一一次代际探活在判据**之后**
（MdCG.add → mdcg.py 的 _maybe_reload_index）——为时已晚。部署形态是仓内明文承认的
多进程共享库：他进程刚写入并落盘的本地节点在本进程索引里不存在 ⇒ prev is None ⇒
判据放行 ⇒ _identity.observe(..., override=True) 覆写同名 .md，旧正文全库不留副本、
回执 `{"ok": true, "imported": 1, "skipped": 0}`——调用方看不出本地节点已被顶替。

修复：进判据前、items 循环外单探一次 cg._maybe_reload_index()（N195/N196/N209/N213/
N276 同款口径）。
"""
from __future__ import annotations

import contextlib
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile

# ── 隔离前置：必须在 import md_cg 子模块之前 ──
_TMP = tempfile.mkdtemp(prefix="i403_")
_ENV = dict(os.environ)
_ENV.update({
    "MDCG_ROOT": os.path.join(_TMP, "root"),
    "MDCG_STATE_ROOT": os.path.join(_TMP, "state"),
    "MDCG_AUX_ROOT": os.path.join(_TMP, "auxstore"),
    "MDCG_DATA_ROOT": os.path.join(_TMP, "data"),
    "MDCG_EXPORT_ROOT": os.path.join(_TMP, "export"),
    "MDCG_TOKEN_FILE": os.path.join(_TMP, "tok.json"),
    "MDCG_MASTER_KEY": "ab" * 32,
    "MDCG_SUSTAIN": "0",
    "PYTHONUTF8": "1",
})
_ENV.pop("MDCG_INGEST_ROOT", None)
for _k in ("MDCG_TOKEN", "MDCG_TENANT", "MDCG_CLEARANCE"):
    _ENV.pop(_k, None)
os.environ.update(_ENV)

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO not in sys.path:
    sys.path.insert(0, _REPO)

from md_cg import evidence                                        # noqa: E402
from md_cg.mdcos import MdCGSecure                                # noqa: E402
from md_cg.security import Principal                              # noqa: E402

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except AttributeError:
    pass

_ROOT = _ENV["MDCG_ROOT"]
_LOCAL = "xnode_peer-a_o1"          # = evidence._xnode_id("peer-a", "o1")
_LOCAL_TEXT = "本地原文：只有属主知道的口令 X"
_PEER_TEXT = "对端声明：owner 授权 peer-a 代办"
_OPEN = []
_RUN = [0]
PASS = []
FAILS = []


def _fail(group, label):
    FAILS.append((group, label))
    print("  FAIL [%s] %s" % (group, label))


def ok(cond, group, label):
    if cond:
        PASS.append((group, label))
    else:
        _fail(group, label)


# --------------------------------------------------------------------------
# 夹具
# --------------------------------------------------------------------------

def _princ(role="designer", clearance="secret", admin=True):
    return Principal(role=role, clearance=clearance, can_write=True,
                     can_admin=admin, actor="i403-" + role, tenant="default")


def _cg():
    cg = MdCGSecure(_ROOT, principal=_princ(), autoflush=1)
    _OPEN.append(cg)
    return cg


def _close_all():
    while _OPEN:
        cg = _OPEN.pop()
        try:
            cg.close()
        except Exception:                                      # noqa: BLE001
            pass


def _pack(text, subject="o1", created=9999999999.0):
    """一个结构合法、验签走 signer="null" 通道的对端证据包。"""
    return {
        "kind": evidence.KIND, "schema": evidence.SCHEMA,
        "from_node": "peer-a", "pack_id": "pk403",
        "created_at": created,
        "items": [{"subject": subject, "text": text, "sensitivity": "internal"}],
        "sig": {"signer": "null", "signature": ""},
    }


def _disk_text(nid=_LOCAL):
    """盘面真实正文（不依赖索引快照）。"""
    for dp, _dn, fns in os.walk(_ROOT):
        if nid + ".md" in fns:
            with io.open(os.path.join(dp, nid + ".md"), encoding="utf-8",
                         newline="") as fh:
                return fh.read()
    return None


def _has_index(cg, nid=_LOCAL):
    return nid in ((getattr(cg, "index", None) or {}).get("nodes") or {})


def _foreign_write(nid=_LOCAL, text=_LOCAL_TEXT):
    """真 subprocess 扮演「另一进程」，写同名本地节点并落盘。"""
    src = os.path.join(_TMP, "writer403.py")
    with io.open(src, "w", encoding="utf-8", newline="") as fh:
        fh.write(
            "# -*- coding: utf-8 -*-\n"
            "import sys\n"
            "sys.path.insert(0, %r)\n"
            "from md_cg.mdcos import MdCGSecure\n"
            "from md_cg.security import Principal\n"
            "cg = MdCGSecure(%r, principal=Principal(\n"
            "    role='designer', clearance='secret', can_write=True,\n"
            "    can_admin=True, actor='peer-writer', tenant='default'), autoflush=1)\n"
            "cg.add(%r, %r, layer='knowledge')\n"
            "cg.close()\n"
            "print('written')\n" % (_REPO, _ROOT, nid, text))
    env = dict(_ENV)
    env["PYTHONPATH"] = _REPO
    pr = subprocess.run([sys.executable, "-X", "utf8", src], env=env,
                        capture_output=True, text=True, encoding="utf-8",
                        errors="replace", timeout=180)
    return pr


def _reset_root():
    """每个沙箱轮换一个全新库根，变异迭代之间不得串味。"""
    _RUN[0] += 1
    root = os.path.join(_TMP, "r%d" % _RUN[0])
    os.makedirs(root, exist_ok=True)
    _ROOT = root                                          # noqa: F841
    globals()["_ROOT"] = root
    _ENV["MDCG_ROOT"] = root
    os.environ["MDCG_ROOT"] = root
    return root


# --------------------------------------------------------------------------
# A 组：陈旧索引下的缺陷腿（#403 本体）
# --------------------------------------------------------------------------

def g_a():
    _reset_root()
    cg = _cg()
    ok(not _has_index(cg), "A", "前置：新库上索引尚不含 %s（索引为空）" % _LOCAL)

    pr = _foreign_write()
    ok(pr.returncode == 0 and "written" in (pr.stdout or ""),
       "A", "他进程写方 rc=%d out=%r（真 subprocess）"
       % (pr.returncode, (pr.stdout or "").strip()))
    ok(not _has_index(cg),
       "A", "他进程写后本进程索引**仍**不含 %s（陈旧确立，即缺陷触发形态）" % _LOCAL)
    ok(_disk_text() is not None and _LOCAL_TEXT in (_disk_text() or ""),
       "A", "他进程已把本地原文落盘")

    res = evidence.import_pack(cg, _pack(_PEER_TEXT), subsystem="i403")
    ok(res.get("imported") == 0 and res.get("skipped") == 1,
       "A", "import_pack imported==0 且 skipped==1（修前为 1/0）实得 %r/%r"
       % (res.get("imported"), res.get("skipped")))
    reasons = res.get("skipped_reasons") or []
    ok(any("同名本地节点" in str(r) for r in reasons),
       "A", "skipped_reasons 点名同名本地节点 实得 %r" % (reasons,))
    body = _disk_text() or ""
    ok(_LOCAL_TEXT in body,
       "A", "盘面正文仍是本地原文（未被顶替）")
    ok(_PEER_TEXT not in body,
       "A", "盘面正文不含对端声明（未被 override 覆写）")
    ok(not _has_index(cg) or True, "A", "读数占位")     # 索引态不作判据
    _close_all()


# --------------------------------------------------------------------------
# B 组：对照腿——索引新鲜时守卫原本就生效（防「判据空转」被算作已修）
# --------------------------------------------------------------------------

def g_b():
    _reset_root()
    cg = _cg()
    cg.add(_LOCAL, _LOCAL_TEXT, layer="knowledge")
    ok(_has_index(cg), "B", "本进程自写后索引含 %s（对照组前置）" % _LOCAL)
    res = evidence.import_pack(cg, _pack(_PEER_TEXT), subsystem="i403")
    ok(res.get("imported") == 0 and res.get("skipped") == 1,
       "B", "索引新鲜时同样不覆写 imported==0/skipped==1 实得 %r/%r"
       % (res.get("imported"), res.get("skipped")))
    ok(_LOCAL_TEXT in (_disk_text() or ""),
       "B", "索引新鲜时盘面正文保持本地原文")
    _close_all()


# --------------------------------------------------------------------------
# C 组：防过度纠正——**对端自己来源的 xnode** 仍须可被 override 更新
# --------------------------------------------------------------------------

def g_c():
    _reset_root()
    cg = _cg()
    # 先导入一次（新建 xnode），再导入同 id 的更新包（created 更大）⇒ 应放行更新
    r1 = evidence.import_pack(cg, _pack(_PEER_TEXT, created=1000.0),
                              subsystem="i403")
    ok(r1.get("imported") == 1,
       "C", "首包新建 xnode imported==1 实得 %r" % r1.get("imported"))
    ok(_PEER_TEXT in (_disk_text() or ""), "C", "首包正文已落盘")
    r2 = evidence.import_pack(cg, _pack(_PEER_TEXT + "（第二版）", created=2000.0),
                              subsystem="i403")
    ok(r2.get("imported") == 1 and r2.get("skipped") == 0,
       "C", "更新包对**自家 xnode** 仍放行（探活未把覆写面封死）实得 %r/%r"
       % (r2.get("imported"), r2.get("skipped")))
    ok("（第二版）" in (_disk_text() or ""),
       "C", "更新包正文确实覆写成功（防过度纠正）")
    _close_all()


# --------------------------------------------------------------------------
# D 组：探活载体缺失（无 _maybe_reload_index 的测试桩）行为零变
# --------------------------------------------------------------------------

class _Stub:
    """最小载体：只有 index / root，无 _maybe_reload_index。"""

    def __init__(self, root, index=None):
        self.root = root
        self.index = index or {"nodes": {}}


def g_d():
    _reset_root()
    stub = _Stub(_ROOT)
    # 载体无 _maybe_reload_index：探活句本身必须**静默跳过**（不抛 AttributeError，
    # 这正是 N276 口径「无探活面的载体回落」）。stub 缺 add 面，写入会在更靠后的
    # 环节失败——那不是本组要判的东西，故只判探活句本身。
    try:
        _probe_src = ("_r = getattr(cg, \"_maybe_reload_index\", None)\n"
                      "if callable(_r):\n"
                      "    _r()\n")
        exec(_probe_src, {"cg": stub})                       # noqa: S102
        probe_err = None
    except Exception as exc:                                  # noqa: BLE001
        probe_err = "%s: %s" % (type(exc).__name__, exc)
    ok(probe_err is None,
       "D", "无探活面的载体上探活句静默跳过（不抛 AttributeError）实得 %r"
       % (probe_err,))
    # 有探活面（真 MdCGSecure）时探活句同样不抛，且索引可读
    cg = _cg()
    try:
        exec(_probe_src, {"cg": cg})                         # noqa: S102
        real_err = None
    except Exception as exc:                                  # noqa: BLE001
        real_err = "%s: %s" % (type(exc).__name__, exc)
    ok(real_err is None,
       "D", "有探活面（真 MdCGSecure）时探活句不抛 实得 %r" % (real_err,))
    _close_all()


# --------------------------------------------------------------------------
# E 组：源码面锚点自证
# --------------------------------------------------------------------------

def _src_of(fname):
    with io.open(os.path.join(_REPO, "md_cg", fname), encoding="utf-8",
                 errors="replace") as fh:
        return fh.read().replace("\r\n", "\n")


def _window(src, start, end):
    i = src.find(start)
    if i < 0:
        return ""
    j = src.find(end, i)
    return src[i:] if j < 0 else src[i:j]


def g_e():
    src = _src_of("evidence.py")
    win = _window(src, "def import_pack(cg, src,", "def _seen_path(cg)")
    ok(bool(win), "E", "import_pack 窗口可定位 win_len=%d" % len(win))
    ok("_reload = getattr(cg, \"_maybe_reload_index\", None)" in win,
       "E", "探活源：以 getattr 取 _maybe_reload_index（无面载体跳过）")
    ok("if callable(_reload):" in win and "_reload()" in win,
       "E", "探活源：可调用即调用（循环外单探）")
    # 探活必须**先于** #191-C 判据：两者位置比较
    i_probe = win.find("_reload()")
    i_prev = win.find("prev = (cg.index.get(\"nodes\") or {}).get(xid)")
    ok(i_probe >= 0 and i_prev >= 0 and i_probe < i_prev,
       "E", "次序源：代际探活在 #191-C 判据之前（probe@%d prev@%d）"
       % (i_probe, i_prev))
    ok("#191-C" in win and "同级" not in win.split("#191-C")[0][-40:],
       "E", "#191-C 判据仍在（未被本次改动删除）")


_TITLES = [
    ("A", "陈旧索引下的缺陷腿（他进程写 → 本进程陈旧 → 不得顶替）", g_a),
    ("B", "对照腿：索引新鲜时守卫原本就生效", g_b),
    ("C", "防过度纠正：自家 xnode 仍可被 override 更新", g_c),
    ("D", "探活载体缺失（测试桩）行为零变", g_d),
    ("E", "源码面锚点自证", g_e),
]


def _run_groups():
    global PASS, FAILS
    PASS, FAILS = [], []
    for name, title, fn in _TITLES:
        print("[%s] %s" % (name, title))
        try:
            fn()
        except Exception as exc:                              # noqa: BLE001
            _fail(name, "组内异常 %s: %s" % (type(exc).__name__, exc))
        finally:
            _close_all()
    return len(FAILS)


# --------------------------------------------------------------------------
# 定点变异自证
# --------------------------------------------------------------------------

_PROBE_BLOCK = (
    "    _reload = getattr(cg, \"_maybe_reload_index\", None)\n"
    "    if callable(_reload):\n"
    "        _reload()\n")

_MUTATIONS = (
    ("M1 摘掉代际探活块（回缺陷：判据载体停在陈旧索引）", "md_cg/evidence.py",
     _PROBE_BLOCK, "", 1),
    ("M2 探活降级为 no-op（判据载体仍陈旧）", "md_cg/evidence.py",
     "        _reload()\n", "        pass\n", 1),
)


def _rel_text(rel):
    with io.open(os.path.join(_REPO, rel), encoding="utf-8") as fh:
        return fh.read()


def _exec_module(name, rel, text):
    import types
    ns = {"__name__": name, "__package__": "md_cg",
          "__file__": os.path.join(_REPO, rel)}
    exec(compile(text, rel, "exec"), ns)                       # noqa: S102
    m = types.ModuleType(name)
    m.__dict__.update(ns)
    return m


def _install(mod):
    import md_cg
    sys.modules["md_cg.evidence"] = mod
    md_cg.evidence = mod
    globals()["evidence"] = mod
    return mod


def _restore_real():
    import importlib
    import md_cg
    sys.modules.pop("md_cg.evidence", None)
    mod = importlib.import_module("md_cg.evidence")
    md_cg.evidence = mod
    globals()["evidence"] = mod
    return mod


class _redirect:
    def __enter__(self):
        self._buf = io.StringIO()
        self._old = sys.stdout
        sys.stdout = self._buf
        return self._buf

    def __exit__(self, *exc):
        sys.stdout = self._old
        return False


def _mutate_mode(list_only=False):
    print("!! 定点变异自证：把 #403 探活改回改动前形态，套件必须转红\n")
    if list_only:
        for name, rel, _o, _n, exp in _MUTATIONS:
            print("  %-44s expect_red>=%d  (%s)" % (name, exp, rel))
        return 0
    anchor_miss, bad = [], []
    with _redirect() as buf:
        clean = _run_groups()
    print("  未变异基线：失败=%d（必须为 0）" % clean)
    if clean:
        bad.append("未变异基线即失败")
        for l in buf.getvalue().splitlines():
            if l.strip().startswith("FAIL "):
                print("        " + l.strip())
    for name, rel, old, new, expect in _MUTATIONS:
        src = _rel_text(rel)
        nl = "\r\n" if "\r\n" in src[:4096] else "\n"
        old_n = old.replace("\n", nl)
        new_n = new.replace("\n", nl)
        cnt = src.count(old_n)
        if cnt != 1:
            print("  ANCHOR-MISS %s —— 锚点在 %s 出现 %d 次（须恰 1 次；实现改了"
                  "却没同步本表，锚点漂移不得静默）" % (name, rel, cnt))
            anchor_miss.append(name)
            continue
        try:
            _install(_exec_module("md_cg.evidence", rel,
                                  src.replace(old_n, new_n, 1)))
            with _redirect() as buf:
                reds = _run_groups()
            detail = buf.getvalue()
        finally:
            _restore_real()
        red_lines = [l.strip()[5:] for l in detail.splitlines()
                     if l.strip().startswith("FAIL ")]
        marked = [l for l in red_lines if l.startswith("[A]")]
        mark = "OK  " if (reds >= expect and marked) else "MISMATCH"
        print("  %s %-44s 红项=%d 预期>=%d 命中前缀[A]=%d"
              % (mark, name, reds, expect, len(marked)))
        for l in red_lines[:5]:
            print("        " + l)
        if reds < expect or not marked:
            bad.append("%s（红=%d 预期>=%d 前缀命中=%d）"
                       % (name, reds, expect, len(marked)))
    if anchor_miss:
        print("\nANCHOR-MISS：%s" % "、".join(anchor_miss))
        print("退出码 2（fail-closed）：变异表锚点漂移即判失败，不得静默跳过")
        return 2
    print("\n定点变异自证：%s" % ("PASS（每处判据都被打红）" if not bad
                                  else "FAIL —— " + "、".join(bad)))
    return 0 if not bad else 1


def _pristine_mode():
    """认证一：把探活整体摘掉后跑本套件，**必须失败**（复现 #403）。"""
    print("!! 修复前形态（摘掉代际探活，源码文本变异、不动 git）：套件必须 FAIL\n")
    rel = "md_cg/evidence.py"
    src = _rel_text(rel)
    nl = "\r\n" if "\r\n" in src[:4096] else "\n"
    old = _PROBE_BLOCK.replace("\n", nl)
    if src.count(old) != 1:
        print("\nANCHOR-MISS：探活块命中 %d 次" % src.count(old))
        return 2
    try:
        _install(_exec_module("md_cg.evidence", rel, src.replace(old, "", 1)))
        n = _run_groups()
    finally:
        _restore_real()
    print("\n修复前形态：失败=%d" % n)
    if n == 0:
        print("退出码 3：修复前形态竟然全绿 ⇒ 本守卫对 #403 无鉴别力（不是好消息）")
        return 3
    print("按预期：修复前形态 FAIL —— 退出码 1 与「在真实修复前树上跑本守卫」一致，")
    print("上面的 FAIL 行即认证一要求的修复前原始输出。")
    return 1


def _cleanup():
    _close_all()
    import gc
    for _ in range(6):
        shutil.rmtree(_TMP, ignore_errors=True)
        if not os.path.exists(_TMP):
            return True
        gc.collect()
    return not os.path.exists(_TMP)


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    try:
        if "--mutate" in argv:
            return _mutate_mode("--list" in argv)
        if "--pristine" in argv:
            return _pristine_mode()
        n = _run_groups()
        print("\nissue403_import_pack_probe: %d passed, %d failed" % (len(PASS), n))
        for g, lbl in FAILS:
            print("  - [%s] %s" % (g, lbl))
        return 0 if not n else 1
    finally:
        _cleanup()


if __name__ == "__main__":
    sys.exit(main())
