# -*- coding: utf-8 -*-
# 功能名：摄取根自身的私有提示不得被相对路径抹掉（issue #452）
# 生效条件：python -X utf8 -m md_cg.test_issue452_ingest_root_hint [--mutate]；被测面=doc_cg(op=ingest, action=dir) 端到端 + refindex.add_items 单点判据
# 子功能：A=端到端两形态（摄取私有目录本身 / 摄取父目录，同一文档必须同密级）；B=单点判据（path 无提示 + root 带提示 ⇒ 必须判 private）；C=对照（真·外部文档仍落 internal，不过度收紧）；R=回退即红自证（--mutate 时把判据面退回「只看相对路径」，A/B 必须转红）
# 执行：--mutate 时先在**同树**把 refindex.py 的判据行退回修前形态，实跑 A/B 记红项，再恢复
# 验证方式：全部 PASS 即通过；--mutate 下回退后红项须含 A 与 B（实跑，不接受推演）
# 不适用条件：不判「提示词表该不该含 internal 等词」（那是 PRIVATE_HINTS 本体）；不判 index_code 面（code_ref 密级另案）；不判 Windows 短路径/符号链接下的 realpath 归一（另案）
"""issue #452 守卫：**摄取根自身**的私有提示段不得被相对路径抹掉。

病象（修前实测，HEAD dd8a9640）：
  cg(op=ingest, action=dir, path=<…>/private) 时 item["path"] 是**相对被摄取根**的
  `hr_archive.md`，`private` 这一段正是 root 自身 ⇒ `docindex.sensitivity_for`
  永远命中不了提示 ⇒ 敏感文档以 internal 落库，同一写者身份（record/internal）
  可读回其正文摘要；同一份文档改传父目录（<…>）却正确判 private 并 fail-closed。
  ⇒ 同一文件、同一写者，只有 `path` 参数不同，密级就更松。

修法：`refindex.add_items` 的 doc_ref 分支把密级判据面改用「**摄取根 + 相对路径**」
  的合成路径（`os.path.join(root or "", it["path"])`）——与 `sensitivity_for` 已支持
  的绝对路径写法同口径；该函数只按段找提示、命中只收紧为 private，故仍满足其
  docstring 的「只可能更严、不可能更松」；root 为空时与修前逐字一致。
"""
from __future__ import annotations

import io
import json
import os
import shutil
import sys
import tempfile

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _REPO)

_TMP = tempfile.mkdtemp(prefix="iss452_")
_SRC = os.path.join(_TMP, "src")
_PRIV = os.path.join(_SRC, "private")
_OUT = os.path.join(_SRC, "public")
os.makedirs(_PRIV, exist_ok=True)
os.makedirs(_OUT, exist_ok=True)
_MARK = "ISS452_MARK_7E31"
_BODY = ("# 人事档案\n\n## 一、背景\n\n"
         + "本文件属于人事档案，包含员工姓名、薪酬与健康状况等不应扩散的信息。\n" * 10
         + "唯一标记：%s\n\n## 二、处置\n\n" % _MARK + "归档需双人复核并留痕。\n" * 10)
io.open(os.path.join(_PRIV, "hr_archive.md"), "w", encoding="utf-8").write(_BODY)
io.open(os.path.join(_OUT, "readme.md"), "w", encoding="utf-8").write(
    "# 公开说明\n\n## 一、背景\n\n对外可读的说明文档。\n\n## 二、处置\n\n无需归档。\n")

os.environ.update({"MDCG_ROOT": os.path.join(_TMP, "brain"),
                   "MDCG_STATE_ROOT": os.path.join(_TMP, "state"),
                   "MDCG_AUX_ROOT": os.path.join(_TMP, "auxstore"),
                   "MDCG_DATA_ROOT": os.path.join(_TMP, "datastore"),
                   "MDCG_EXPORT_ROOT": _TMP, "MDCG_INGEST_ROOT": _SRC,
                   "MDCG_MASTER_KEY": "ab" * 32,
                   "MDCG_SUSTAIN": "0", "MDCG_SLEEP": "0", "MDCG_AUTONOMY": "full"})
from md_cg import docindex, mcp_server as ms, refindex     # noqa: E402
from md_cg.mdcos import MdCGSecure                         # noqa: E402
from md_cg.security import Principal                       # noqa: E402
from md_cg import tokens as tk                             # noqa: E402

FAILS = []
_PASSED = [0]


def _check(name, cond, detail=""):
    if cond:
        print("  PASS " + name)
        _PASSED[0] += 1
    else:
        print("  FAIL " + name + ("  · " + str(detail) if detail else ""))
        FAILS.append(name)


def _writer(tag):
    root = os.path.join(_TMP, "brain_" + tag)
    os.environ["MDCG_ROOT"] = root
    return MdCGSecure(root, principal=Principal(
        role="record", actor="low-" + tag, clearance="internal", can_write=True,
        can_admin=False, layers_allow=("knowledge",),
        ops_allow=("info", "route", "read", "write", "ingest", "recent", "status", "edges")),
        autoflush=1)


def _ingest(cg, path):
    """工具面入口（不直调原语——本条病灶正是「同一入口换参数就换密级」）。"""
    try:
        return ms._dispatch(cg, "cg", {"op": "ingest", "action": "dir", "path": path}), ""
    except Exception as e:                                                            # noqa: BLE001
        return None, "%s: %s" % (type(e).__name__, e)


def _levels(cg):
    out = {}
    for nid in sorted(cg.index.get("nodes") or {}):
        got = cg.get(nid) or {}
        out[nid] = (got.get("frontmatter") or {}).get("sensitivity")
    return out


def leg_A():
    """端到端：摄取私有目录**本身** 与 摄取其父目录，同一文档必须同密级。"""
    print("\n[A 端到端] 同一文档、同一写者（record/internal）、都不声明 sensitivity")
    cg = _writer("a1")
    r1, err1 = _ingest(cg, _PRIV)                    # ← 摄取私有目录本身（病灶点）
    cg.flush()
    lv1 = _levels(cg)
    cg.close()
    print("    形态① ingest(path=<…>/private) 回执=%s 异常=%s 节点密级=%s"
          % (json.dumps(r1, ensure_ascii=False)[:110] if r1 else None, err1[:60] or "无", lv1))
    ok_fail_closed = bool(err1 and "private" in err1) or (
        lv1 and all(v == "private" for v in lv1.values() if v))
    _check("A1 摄取私有目录本身 ⇒ 不得落 internal 档",
           ok_fail_closed, "异常=%r 密级=%s（期望 AccessDenied private 或全 private）" % (err1, lv1))

    cg2 = _writer("a2")
    r2, err2 = _ingest(cg2, _SRC)                    # 对照：摄取父目录（提示在相对路径里）
    cg2.flush()
    lv2 = _levels(cg2)
    cg2.close()
    print("    形态② ingest(path=<…>)         回执=%s 异常=%s 节点密级=%s"
          % (json.dumps(r2, ensure_ascii=False)[:110] if r2 else None, err2[:60] or "无", lv2))
    _check("A2 摄取父目录 ⇒ 同样不得落 internal 档",
           bool(err2 and "private" in err2) or (
               lv2 and all(v == "private" for v in lv2.values() if v)),
           "异常=%r 密级=%s" % (err2, lv2))
    _check("A3 两形态密级一致（同文件不该因 path 参数更松）",
           ok_fail_closed == (bool(err2 and "private" in err2) or (
               lv2 and all(v == "private" for v in lv2.values() if v))),
           "①=%r ②=%r" % (ok_fail_closed, err2))


def leg_B():
    """单点判据：path 里没有提示、root 段里有提示 ⇒ 必须判 private。"""
    print("\n[B 单点判据] refindex.add_items：root 带提示 + path 无提示")
    items, errs, stats = docindex.index_dir(_PRIV)
    print("    index_dir(<…>/private) → items=%d errors=%s 每条 path=%s"
          % (len(items), errs[:1], [i.get("path") for i in items]))

    # B1：换成**有权限写 private** 的写者（designer/secret）⇒ 落库档位必须就是 private
    cg = MdCGSecure(os.path.join(_TMP, "brain_b1"), principal=Principal(
        role="designer", actor="hi-452", clearance="secret", can_write=True, can_admin=True,
        layers_allow=("knowledge",), ops_allow=("read", "write", "ingest", "info")), autoflush=1)
    try:
        ids, sens = refindex.add_items(cg, items, kind="doc_ref", root=_PRIV)
        cg.flush()
        lv = {i: (cg.get(i) or {}).get("frontmatter", {}).get("sensitivity") for i in ids}
    except Exception as e:                                                            # noqa: BLE001
        ids, sens, lv = [], {}, {"EXC": "%s: %s" % (type(e).__name__, str(e)[:100])}
    print("    [secret 写者] add_items(root=<…>/private) → ids=%s 密级=%s 分布=%s"
          % (ids, lv, sens))
    _check("B1 判据面含摄取根 ⇒ 落库档位 private（不得 internal）",
           bool(lv) and all(v == "private" for v in lv.values() if v), lv)
    cg.close()

    # B2：低权写者（record/internal）直调同一单点 ⇒ 必须 fail-closed 拒写
    cg2 = _writer("b2")
    try:
        ids2, sens2 = refindex.add_items(cg2, items, kind="doc_ref", root=_PRIV)
        cg2.flush()
        lv2 = {i: (cg2.get(i) or {}).get("frontmatter", {}).get("sensitivity") for i in ids2}
        err2 = ""
    except Exception as e:                                                            # noqa: BLE001
        ids2, lv2, err2 = [], {}, "%s: %s" % (type(e).__name__, str(e)[:90])
    cg2.close()
    print("    [internal 写者] add_items(root=<…>/private) → ids=%s 异常=%s"
          % (ids2, err2 or "无"))
    _check("B2 低权写者直调同一单点 ⇒ 拒写（fail-closed）",
           bool(err2 and "private" in err2), "异常=%r 落库=%s" % (err2, lv2))

    # B3：判据函数本身对「摄取根 + 相对路径」的合成路径生效
    _check("B3 单点判据本身对合成路径生效",
           docindex.sensitivity_for(os.path.join(_PRIV, "hr_archive.md"), None)[0] == "private")


def leg_C():
    """对照：真·外部非敏感文档仍落 internal（防过度收紧）。"""
    print("\n[C 对照] 非敏感目录摄取 ⇒ 应仍为 internal")
    cg = _writer("c")
    r, err = _ingest(cg, _OUT)
    cg.flush()
    lv = _levels(cg)
    cg.close()
    print("    ingest(path=<…>/public) 回执=%s 异常=%s 密级=%s"
          % (json.dumps(r, ensure_ascii=False)[:110] if r else None, err[:60] or "无", lv))
    _check("C1 非敏感目录仍 internal（未过度收紧）",
           bool(lv) and all(v == "internal" for v in lv.values() if v), lv)


def leg_R():
    """--mutate：把判据面退回「只看相对路径」，A/B 必须实跑转红。"""
    p = os.path.join(_REPO, "md_cg", "refindex.py")
    orig = io.open(p, encoding="utf-8").read()
    needle = ('_hint = os.path.join(root or "", it.get("path") or "")'
              '.replace("\\\\", "/")\n            s, _basis = docindex'
              '.sensitivity_for(_hint, sensitivity)')
    if needle not in orig:
        print("  [R] 变异点未找到（源码形态已变）⇒ 跳过回退自证")
        return
    mutated = orig.replace(
        needle,
        's, _basis = docindex.sensitivity_for(it.get("path") or "", sensitivity)')
    try:
        io.open(p, "w", encoding="utf-8").write(mutated)
        sys.modules.pop("md_cg.refindex", None)
        import importlib
        import md_cg.refindex as _ri
        importlib.reload(_ri)
        globals()["refindex"] = _ri          # 让 B 腿也走变异后的那份（否则只覆盖 A 腿）
        before = len(FAILS)
        leg_A()
        leg_B()
        regressed = len(FAILS) - before
        print("  [R] 回退后新增红项 = %d" % regressed)
        _check("R1 回退即红（红项来自实跑，不是推演）", regressed >= 2,
               "新增红项=%d（期望 ≥2：A 与 B）" % regressed)
    finally:
        io.open(p, "w", encoding="utf-8").write(orig)


def main():
    mutate = "--mutate" in sys.argv
    print("=" * 72)
    print("md 认知图 · issue #452 守卫 · 摄取根自身的私有提示")
    print("沙箱 =", _TMP, "| mutate =", mutate)
    print("=" * 72)
    leg_A()
    leg_B()
    leg_C()
    if mutate:
        leg_R()
    print("\n" + ("全部 PASS（%d 项）" % _PASSED[0] if not FAILS
                  else "FAIL %d 项：%s" % (len(FAILS), FAILS)))
    shutil.rmtree(_TMP, ignore_errors=True)
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
