#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""守卫：verify_discipline 的 semantic（语义标题）判据在场（N258）

契约面 = scripts/verify_discipline.py 的 FIELD_LABEL/FIELD_ORDER/field_value 注释。

缺陷形态（N258）：本文件 docstring 承诺「每条纪律的 semantic / 动作 / 声明 必须出现在
产物中」，但 FIELD_ORDER 只含 trigger/action/negative/declaration —— 渲染器写出的
「N. 语义」标题**零判据**：产物副本里语义文本被替换/删除，check() 仍 ok=True
（承诺项无守卫即等同无承诺，与「手写行号必腐化」同构）。

作业面：取矩阵内一个机器渲染的 file 目标，把**真产物与真源**拷进临时目录构成最小
repo，对副本断言——绝不碰工作区文件。覆盖 7 条断言：
  ⓪field_value(n,"semantic") 与渲染器单点（R._NUM_PREFIX 去前缀）同源。
  ①基线：真产物副本 check ok（判据面本身可跑）。
  ②替换某条语义文本（出现次数最少者，逐处替换）→ check 判红；missing 记录指认
    key=semantic、条号=N、field=「语义」。
  ③删除同一语义文本 → check 判红且 missing 指认 semantic。
  ④还原副本 → check 回绿（证明 ②③ 判红由篡改造成，非环境噪声）。

红基线：`--impl head`（git show HEAD:scripts/verify_discipline.py + 工作树
render_discipline/discipline_nodes 副本）→ ⓪②③④ 组断言按点转红。
定点变异：`--mutate` 逐条把修复点改回缺陷形态，断言转红条数恰为预期；
锚点未命中 → ANCHOR-MISS → 退出码 2（fail-closed）。

退出码：0 = 全过（或红基线符合预期）；1 = 断言失败 / 红基线未达标；2 = 用法或环境错误。
"""
from __future__ import annotations

import argparse
import importlib.util
import io
import os
import shutil
import subprocess
import sys
import tempfile

_HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(_HERE)
_LIVE = os.path.join(_HERE, "verify_discipline.py")

sys.path.insert(0, _HERE)
import render_discipline as R  # noqa: E402

_RESULTS = []


def _ok(cond, name, detail=""):
    cond = bool(cond)
    _RESULTS.append((name, cond, detail if not cond else ""))
    print(("[PASS] " if cond else "[FAIL] ") + name
          + ((" —— " + detail) if (detail and not cond) else ""))


def _load(path, modname):
    spec = importlib.util.spec_from_file_location(modname, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _sem_of(n):
    """渲染器单点取值（R._NUM_PREFIX 去数字前缀），守卫自己复算口径。"""
    return R._NUM_PREFIX.sub("", str(n.get("semantic", n["id"])))


def _pick_target(mx, repo):
    """选一个机器渲染的 file 目标（非 pointer、非 render:false、产物在位）。"""
    for name, t in (mx.get("targets") or {}).items():
        t = dict(t)
        if t.get("pointer") or t.get("render", True) is False:
            continue
        if t.get("transport") != "file":
            continue
        p = R.expand(t["path"], repo)
        if os.path.isfile(p):
            t["_name"] = name
            return t, p
    return None, None


def _battery(impl, repo):
    """跑全部 7 条断言（每条一次 _ok）。"""
    del _RESULTS[:]
    tmp = tempfile.mkdtemp(prefix="vd_sem_battery_")
    try:
        src = R.load_source(repo)
        nodes = R.nodes_of(src)
        mx = R.load_matrix(repo)
        t, real_path = _pick_target(mx, repo)
        if t is None:
            _ok(False, "①基线：真产物副本 check ok", "矩阵内找不到机器渲染的 file 目标")
            return

        # 最小 repo：真源（同相对路径）+ 矩阵 + 真产物副本（source_path 经 load_matrix 读
        # docs/discipline/harnesses.yaml —— 判据面的依赖闭包要一起拷进临时 repo）
        srel = os.path.relpath(R.source_path(repo), repo)
        spath = os.path.join(tmp, srel)
        os.makedirs(os.path.dirname(spath), exist_ok=True)
        shutil.copyfile(R.source_path(repo), spath)
        mdir = os.path.join(repo, "docs", "discipline")
        if os.path.isdir(mdir):
            shutil.copytree(mdir, os.path.join(tmp, "docs", "discipline"))
        prod = os.path.join(tmp, os.path.relpath(real_path, repo))
        os.makedirs(os.path.dirname(prod), exist_ok=True)
        real_text = io.open(real_path, encoding="utf-8").read()

        def _put(text):
            with io.open(prod, "w", encoding="utf-8", newline="") as f:
                f.write(text)

        def _ck():
            return impl.check(dict(t), src, tmp, False)

        # ⓪ 取值单点同源
        n0 = nodes[0]
        try:
            got = impl.field_value(n0, "semantic")
            _ok(got == _sem_of(n0),
                "⓪field_value(semantic) 与渲染器单点同源",
                "field_value=%r 单点=%r" % (got, _sem_of(n0)))
        except Exception as exc:                            # noqa: BLE001
            _ok(False, "⓪field_value(semantic) 与渲染器单点同源",
                "field_value(…,'semantic') 抛出 %r" % (exc,))

        # ① 基线
        _put(real_text)
        r0 = _ck()
        _ok(r0["ok"] is True, "①基线：真产物副本 check ok",
            "target=%s missing=%r" % (t["_name"], r0.get("missing", [])[:2]))

        # 选篡改对象：产物内出现次数最少、其次最短的语义文本（确定性）
        picks = []
        for i, n in enumerate(nodes, 1):
            sem = _sem_of(n)
            c = real_text.count(sem) if sem else 0
            if c:
                picks.append((c, len(sem), i, sem))
        if not picks:
            _ok(False, "②替换语义文本：check 判红", "产物内找不到任何语义文本（基线已异常）")
            return
        picks.sort()
        _c, _l, N, sem = picks[0]

        # ② 替换
        _put(real_text.replace(sem, "语义文本已被篡改（守卫探针）"))
        r2 = _ck()
        recs = [m for m in r2.get("missing", []) if m.get("key") == "semantic"]
        _ok(not r2["ok"], "②替换语义文本：check 判红",
            "missing=%r" % (r2.get("missing", [])[:2],))
        _ok(any(m.get("no") == N for m in recs),
            "②替换语义文本：missing 指认 key=semantic 且条号=N",
            "N=%d recs=%r" % (N, recs[:3]))
        _ok(any(m.get("field") == "语义" for m in recs),
            "②替换语义文本：记录 field=「语义」", "recs=%r" % (recs[:3],))

        # ③ 删除
        _put(real_text.replace(sem, ""))
        r3 = _ck()
        recs3 = [m for m in r3.get("missing", []) if m.get("key") == "semantic"]
        _ok((not r3["ok"]) and any(m.get("no") == N for m in recs3),
            "③删除语义文本：check 判红且 missing 指认 semantic",
            "missing=%r" % (r3.get("missing", [])[:2],))

        # ④ 还原
        _put(real_text)
        r4 = _ck()
        _ok(r4["ok"] is True, "④还原副本后 check 回绿",
            "missing=%r" % (r4.get("missing", [])[:2],))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return None


# ================================================================ 定点变异
# （名称, 源码锚点, 替换文本, 预期转红条数）
_MUTATIONS = (
    ("N258 FIELD_ORDER 去掉 semantic（判据面收窄回修前）",
     'FIELD_ORDER = ("semantic", "trigger", "action", "negative", "declaration")',
     'FIELD_ORDER = ("trigger", "action", "negative", "declaration")  # MUT', 4),
    ("N258 field_value 的 semantic 取值错位（与 _title 单点脱钩）",
     '    if key == "semantic":\n'
     '        # 与渲染器 _title 单点同源：去掉「N. 」数字前缀（产物标题是「N. <语义>」，\n'
     '        # 子串判据对去前缀形态最稳——标题被替换/删除即判缺失；号码格式不重复钉）\n'
     '        return R._NUM_PREFIX.sub("", str(n.get("semantic", n["id"])))\n',
     '    if key == "semantic":\n'
     '        return "与渲染器脱钩的错值ZZZ"  # MUT\n', 3),
)

# `--impl head` 红基线必须点名的关键判据
_HEAD_EXPECT_RED = (
    "⓪field_value(semantic)",
    "②替换语义文本：check 判红",
    "②替换语义文本：missing",
    "②替换语义文本：记录 field",
    "③删除语义文本",
)


def _materialize_head(tmp):
    p = subprocess.run(["git", "show", "HEAD:scripts/verify_discipline.py"],
                       cwd=REPO, capture_output=True)
    if p.returncode != 0:
        sys.stderr.write("[vd_semantic] git show 失败：rc=%d\n%s"
                         % (p.returncode, p.stderr.decode("utf-8", "replace")))
        raise SystemExit(2)
    d = os.path.join(tmp, "vd_head")
    os.makedirs(d, exist_ok=True)
    path = os.path.join(d, "verify_discipline.py")
    with io.open(path, "wb") as f:
        f.write(p.stdout)
    for fn in ("render_discipline.py", "discipline_nodes.py"):
        shutil.copyfile(os.path.join(_HERE, fn), os.path.join(d, fn))
    return path


def _live_mode(impl):
    _battery(impl, REPO)
    bad = [n for n, okc, _d in _RESULTS if not okc]
    print("\n断言组 %d 通过 / %d 失败" % (len(_RESULTS) - len(bad), len(bad)))
    return 0 if not bad else 1


def _baseline_mode(impl):
    print("!! 红基线：以 HEAD 版 verify_discipline 跑同一断言组——修前缺陷形态必须按点转红\n")
    _battery(impl, REPO)
    reds = [n for n, okc, _d in _RESULTS if not okc]
    miss = [k for k in _HEAD_EXPECT_RED if not any(k in n for n in reds)]
    for n, okc, d in _RESULTS:
        print("       %s %s%s" % ("RED " if not okc else "green", n, (" —— " + d) if not okc else ""))
    okr = not miss
    print("\n红基线点名断言：%s" % ("全部按点转红（%d/%d）" % (len(_HEAD_EXPECT_RED), len(_HEAD_EXPECT_RED))
                                   if okr else "未达标，缺 %r" % (miss,)))
    print("红基线断言组 %d 通过 / %d 失败%s"
          % (len(_RESULTS) - len(reds), len(reds), "（符合预期）" if okr else ""))
    return 0 if okr else 1


def _mutate_mode(tmp):
    print("!! 定点变异自证：逐条把修复点改回缺陷形态，断言组必须按预期条数转红\n")
    bad = 0
    src = io.open(_LIVE, encoding="utf-8").read()
    for i, (name, old, new, exp) in enumerate(_MUTATIONS, 1):
        if old not in src:
            sys.stderr.write("[vd_semantic] ANCHOR-MISS：%s\n" % name)
            return 2
        path = os.path.join(tmp, "mut_%d.py" % i)
        with io.open(path, "w", encoding="utf-8", newline="") as f:
            f.write(src.replace(old, new, 1))
        impl = _load(path, "vd_mut_%d" % i)
        print("  == %s（预期转红 %d 条）" % (name, exp))
        try:
            _battery(impl, REPO)
        except Exception as exc:                            # noqa: BLE001
            print("     [FAIL] 变异体跑断言组抛异常：%r（计入不达标）" % (exc,))
            bad += 1
            continue
        reds = [n for n, okc, _d in _RESULTS if not okc]
        good = len(reds) == exp
        print("     转红 %d 条（预期 %d）%s：%s"
              % (len(reds), exp, "恰合" if good else "**不符**", "；".join(reds[:6])))
        if not good:
            bad += 1
    print("\n定点变异 %d/%d 恰合" % (len(_MUTATIONS) - bad, len(_MUTATIONS)))
    return 0 if not bad else 1


def main(argv=None):
    ap = argparse.ArgumentParser(description="verify_discipline semantic 判据守卫（N258）")
    ap.add_argument("--impl", default="", help="head = HEAD 版红基线；省略 = 工作树")
    ap.add_argument("--mutate", action="store_true", help="定点变异自证")
    ap.add_argument("--list", action="store_true", help="只列变异表")
    args = ap.parse_args(argv)

    if args.list:
        for name, _o, _n, exp in _MUTATIONS:
            print("  %-52s expect_red=%d" % (name, exp))
        return 0

    tmp = tempfile.mkdtemp(prefix="vd_semantic_guard_")
    try:
        if args.mutate:
            return _mutate_mode(tmp)
        if args.impl == "head":
            return _baseline_mode(_load(_materialize_head(tmp), "vd_head"))
        return _live_mode(_load(_LIVE, "vd_live"))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
