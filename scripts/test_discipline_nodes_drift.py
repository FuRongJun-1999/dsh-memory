#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""守卫：discipline_nodes 投影面「多出/重复可见（N259）」与「check/sync 同判据（N260）」

契约面 = scripts/discipline_nodes.py 的 scan_nodes_detail/_node_drift/sync_cg_nodes 注释。

覆盖：
  ①基线：sync(write) 建满 N 条 → check ok、drift 0、scanned==总数==N。
  ②N259a 重复：同条号第二份文件 → check 判红 kind=dup；sync(write) 记 removed 且清盘；
    清后回绿、scanned 回 N。（修前：scan 覆盖写 ⇒ 重复对 check/sync 全不可见。）
  ③N259b 多出：真源之外条号（discipline:99）→ check 判红 kind=orphan；sync 清盘回绿。
  ④N260a 触发器漂移：手改 fm condition_space.trigger（正文与 sha 不动）→ check 判红
    且 **sync 必须报 changed**（修前 sync「列表全等」判 same → 报「已一致」，文档指定
    的修复链清不掉漂移）；sync(write) 后回绿。
  ⑤N260b 正文追加行：多一行（包含判据仍成立）→ check 判绿 **且** sync 报 changed 空
    （修前 sync 列表全等判 changed 非空 ⇒「守卫恒绿」与「修正链恒有动作」矛盾）。
  ⑥N260c id 缺失闭环：清空 fm.id → check 判红 kind=id；sync(write) 重写并补发新 id
    → 回读 id 非空、check 回绿（修前 sync 判 same 跳过 ⇒ id 漂移永不收敛）。

红基线：`--impl head` 以 `git show HEAD:scripts/discipline_nodes.py` 物化修前实现
（render_discipline 用工作树副本），断言 ②③④⑤⑥ 的关键判据按点转红。
定点变异：`--mutate` 逐条把修复点改回缺陷形态，断言转红条数恰为预期；
锚点未命中 → ANCHOR-MISS → 退出码 2（fail-closed）。

退出码：0 = 全过（或红基线符合预期）；1 = 有断言失败 / 红基线未达标；2 = 用法或环境错误。
"""
from __future__ import annotations

import argparse
import importlib.util
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile

_HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(_HERE)
_LIVE = os.path.join(_HERE, "discipline_nodes.py")

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


def _fresh(impl, repo, run_tmp, tag):
    """建一个最小库（sync write 建满全部条号）→ root。"""
    root = os.path.join(run_tmp, "case_" + tag)
    os.makedirs(root, exist_ok=True)
    impl.sync_cg_nodes(repo, root, write=True)
    return root


def _tamper_cs(path, impl, **over):
    """手改某节点的 condition_space（保留其余键），正文不动。"""
    fm, body = impl._read_node(path)
    cs = impl._json_field(fm, "condition_space")
    cs.update(over)
    fm["condition_space"] = json.dumps(cs, ensure_ascii=False)
    impl._write_node(path, fm, [k for k in fm.keys()], body.splitlines())


def _battery(impl, repo):
    """跑全部 18 条断言（每条一次 _ok），返回 None（结果在 _RESULTS）。"""
    del _RESULTS[:]
    run_tmp = tempfile.mkdtemp(prefix="dn_drift_battery_")
    try:
        # ① 基线
        root = _fresh(impl, repo, run_tmp, "base")
        res = impl.check_cg_nodes(repo, root)
        N = res["nodes"]
        _ok(res["ok"] is True and not res["drift"],
            "①基线：check ok 且零漂移", "drift=%r" % (res["drift"][:2],))
        _ok(res["scanned"] == N and N >= 18,
            "①基线：scanned 计入总数（==N）", "scanned=%r N=%r" % (res["scanned"], N))

        # ② N259a 重复（复制第 1 条，文件名排序在后 ⇒ 进 dups，原件留存）
        base = impl.scan_nodes(root)
        p1 = base[1]["path"]
        dup_path = os.path.join(os.path.dirname(p1), "zz_dup_same_no.md")
        shutil.copyfile(p1, dup_path)
        res2 = impl.check_cg_nodes(repo, root)
        dups = [d for d in res2["drift"] if d["kind"] == "dup"]
        _ok((not res2["ok"]) and dups and dups[0]["no"] == 1,
            "②重复：check 判红并指认 dup（修前失明）", "drift=%r" % (res2["drift"][:3],))
        _ok(res2["scanned"] == N + 1,
            "②重复：scan 总数计入重复文件", "scanned=%r" % (res2["scanned"],))
        sy2 = impl.sync_cg_nodes(repo, root, write=True)
        _ok(any(r["kind"] == "dup" and r["path"] == dup_path
                for r in sy2.get("removed", [])) and not os.path.exists(dup_path),
            "②重复：sync 清除并落盘（removed）", "removed=%r" % (sy2.get("removed", []),))
        res2b = impl.check_cg_nodes(repo, root)
        _ok(res2b["ok"] is True and res2b["scanned"] == N,
            "②重复：清除后 check 回绿", "scanned=%r" % (res2b["scanned"],))

        # ③ N259b 多出（真源之外条号）
        root = _fresh(impl, repo, run_tmp, "orphan")
        orph_path = os.path.join(root, impl.NODE_DIR, "zz_orphan.md")
        with io.open(orph_path, "w", encoding="utf-8", newline="\n") as f:
            f.write('---\nid: "mem_zz_orphan"\ntags: ["work-discipline", "discipline:99"]\n'
                    '---\n# 功能名：伪造的第 99 条\n')
        res3 = impl.check_cg_nodes(repo, root)
        orphs = [d for d in res3["drift"] if d["kind"] == "orphan"]
        _ok((not res3["ok"]) and orphs and orphs[0]["no"] == 99,
            "③多出：check 判红并指认 orphan（修前失明）", "drift=%r" % (res3["drift"][:3],))
        sy3 = impl.sync_cg_nodes(repo, root, write=True)
        _ok(any(r["kind"] == "orphan" and r["path"] == orph_path
                for r in sy3.get("removed", [])) and not os.path.exists(orph_path),
            "③多出：sync 清除并落盘（removed）", "removed=%r" % (sy3.get("removed", []),))
        _ok(impl.check_cg_nodes(repo, root)["ok"] is True,
            "③多出：清除后 check 回绿")

        # ④ N260a 触发器漂移（正文与 sha 不动）
        root = _fresh(impl, repo, run_tmp, "trig")
        p2 = impl.scan_nodes(root)[2]["path"]
        _tamper_cs(p2, impl, trigger="篡改后的触发器文本")
        res4 = impl.check_cg_nodes(repo, root)
        trigs = [d for d in res4["drift"] if d["kind"] == "trigger"]
        _ok((not res4["ok"]) and trigs and trigs[0]["no"] == 2,
            "④触发器漂移：check 判红并指认 trigger", "drift=%r" % (res4["drift"][:3],))
        sy4 = impl.sync_cg_nodes(repo, root, write=False)
        _ok(any(c["no"] == 2 for c in sy4.get("changed", [])),
            "④触发器漂移：sync 与 check 同判（changed 非空）", "changed=%r" % (sy4.get("changed", []),))
        impl.sync_cg_nodes(repo, root, write=True)
        _ok(impl.check_cg_nodes(repo, root)["ok"] is True,
            "④触发器漂移：sync(write) 后回绿")

        # ⑤ N260b 正文追加行（包含判据仍成立）
        root = _fresh(impl, repo, run_tmp, "extra")
        p3 = impl.scan_nodes(root)[3]["path"]
        with io.open(p3, encoding="utf-8") as f:
            text = f.read()
        with io.open(p3, "w", encoding="utf-8", newline="") as f:
            f.write(text + "# 追加的非期望行\n")
        _ok(impl.check_cg_nodes(repo, root)["ok"] is True,
            "⑤正文追加行：check 判绿（包含判据）")
        sy5 = impl.sync_cg_nodes(repo, root, write=False)
        _ok(sy5.get("changed", []) == [],
            "⑤正文追加行：sync 报无动作（changed 空，与 check 同判）",
            "changed=%r" % (sy5.get("changed", []),))

        # ⑥ N260c id 缺失闭环
        root = _fresh(impl, repo, run_tmp, "id")
        p4 = impl.scan_nodes(root)[4]["path"]
        fm4, body4 = impl._read_node(p4)
        fm4["id"] = '""'
        impl._write_node(p4, fm4, [k for k in fm4.keys()], body4.splitlines())
        res6 = impl.check_cg_nodes(repo, root)
        ids = [d for d in res6["drift"] if d["kind"] == "id"]
        _ok((not res6["ok"]) and ids and ids[0]["no"] == 4,
            "⑥id 缺失：check 判红并指认 id", "drift=%r" % (res6["drift"][:3],))
        sy6 = impl.sync_cg_nodes(repo, root, write=True)
        _ok(any(c["no"] == 4 for c in sy6.get("changed", [])),
            "⑥id 缺失：sync 必须改写（changed 非空）", "changed=%r" % (sy6.get("changed", []),))
        fm4b, _ = impl._read_node(p4)
        _ok(impl._norm(fm4b.get("id") or "").strip('"') != "",
            "⑥id 缺失：sync 补发后 id 非空（修链收敛）", "id=%r" % (fm4b.get("id"),))
        _ok(impl.check_cg_nodes(repo, root)["ok"] is True,
            "⑥id 缺失：补发后 check 回绿")
    finally:
        shutil.rmtree(run_tmp, ignore_errors=True)
    return None


# ================================================================ 定点变异
# （名称, 源码锚点, 替换文本, 预期转红条数）
_MUTATIONS = (
    ("N259 check 侧重复检测撤掉",
     '    for no in sorted(det["dups"]):\n'
     '        paths = [have[no]["path"]] + det["dups"][no]\n'
     '        drift.append({"no": no, "id": "-", "kind": "dup",\n'
     '                      "detail": "discipline:%d 有 %d 个投影节点（重复）：%s"\n'
     '                                % (no, len(paths),\n'
     '                                   "、".join(os.path.basename(p) for p in paths))})\n',
     '    for no in sorted(det["dups"]):\n'
     '        pass  # MUT：重复不再判红\n', 1),
    ("N260 sync 判据回退为列表全等（修前形态）",
     "        if not _node_drift(exp, cur, sha):     # N260：与 check 同判据（单点）\n"
     "            continue\n",
     '        _c0, _t0 = _carrier_of(cur["body"], cur["fm"].get("created_at"))  # MUT\n'
     "        _w0 = expected_body(exp, _c0, _t0)\n"
     '        if [_norm(l) for l in (cur["body"] or "").splitlines() if l.strip()] == \\\n'
     "                [_norm(l) for l in _w0] and \\\n"
     '                str(_json_field(cur["fm"], "condition_space").get("source_sha") or "") == sha:\n'
     "            continue\n", 6),
    ("N260 id 补发撤掉",
     '        if _norm(fm.get("id") or "").strip(\'"\') == "":\n'
     '            fm["id"] = \'"%s"\' % _new_node_fm(exp, now)[0]\n',
     '        if False:  # MUT：id 缺失不再补发\n'
     '            fm["id"] = \'"%s"\' % _new_node_fm(exp, now)[0]\n', 2),
    ("N259 sync 侧清除撤掉",
     '    known = set(range(1, len(nodes) + 1))\n'
     '    for no in sorted(det["dups"]):\n'
     '        for p in det["dups"][no]:\n'
     '            if write:\n'
     '                try:\n'
     '                    os.remove(p)\n'
     '                except OSError:\n'
     '                    pass\n'
     '            removed.append({"no": no, "kind": "dup", "path": p, "written": bool(write)})\n'
     '    for no in sorted([k for k in have if k not in known]):\n'
     '        p = have[no]["path"]\n'
     '        if write:\n'
     '            try:\n'
     '                os.remove(p)\n'
     '            except OSError:\n'
     '                pass\n'
     '        removed.append({"no": no, "kind": "orphan", "path": p, "written": bool(write)})\n'
     '        del have[no]\n',
     '    known = set(range(1, len(nodes) + 1))  # MUT：多出/重复不再清除\n', 4),
)

# `--impl head` 红基线必须点名的关键判据（修前缺陷形态的直接断言面）
_HEAD_EXPECT_RED = (
    "②重复：check 判红",
    "③多出：check 判红",
    "④触发器漂移：sync 与 check 同判",
    "⑤正文追加行：sync 报无动作",
    "⑥id 缺失：sync 必须改写",
)


def _materialize_head(tmp):
    p = subprocess.run(["git", "show", "HEAD:scripts/discipline_nodes.py"],
                       cwd=REPO, capture_output=True)
    if p.returncode != 0:
        sys.stderr.write("[discipline_nodes_drift] git show 失败：rc=%d\n%s"
                         % (p.returncode, p.stderr.decode("utf-8", "replace")))
        raise SystemExit(2)
    d = os.path.join(tmp, "head")
    os.makedirs(d, exist_ok=True)
    path = os.path.join(d, "discipline_nodes.py")
    with io.open(path, "wb") as f:
        f.write(p.stdout)
    shutil.copyfile(os.path.join(_HERE, "render_discipline.py"),
                    os.path.join(d, "render_discipline.py"))
    return path


def _live_mode(impl):
    _battery(impl, REPO)
    bad = [n for n, okc, _d in _RESULTS if not okc]
    print("\n断言组 %d 通过 / %d 失败" % (len(_RESULTS) - len(bad), len(bad)))
    return 0 if not bad else 1


def _baseline_mode(impl):
    print("!! 红基线：以 HEAD 版 discipline_nodes 跑同一断言组——修前缺陷形态必须按点转红\n")
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
            sys.stderr.write("[discipline_nodes_drift] ANCHOR-MISS：%s\n" % name)
            return 2
        path = os.path.join(tmp, "mut_%d.py" % i)
        with io.open(path, "w", encoding="utf-8", newline="") as f:
            f.write(src.replace(old, new, 1))
        impl = _load(path, "dn_mut_%d" % i)
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
    ap = argparse.ArgumentParser(description="discipline_nodes 投影面守卫（N259/N260）")
    ap.add_argument("--impl", default="", help="head = HEAD 版红基线；省略 = 工作树")
    ap.add_argument("--mutate", action="store_true", help="定点变异自证")
    ap.add_argument("--list", action="store_true", help="只列变异表")
    args = ap.parse_args(argv)

    if args.list:
        for name, _o, _n, exp in _MUTATIONS:
            print("  %-42s expect_red=%d" % (name, exp))
        return 0

    tmp = tempfile.mkdtemp(prefix="dn_drift_guard_")
    try:
        if args.mutate:
            return _mutate_mode(tmp)
        if args.impl == "head":
            return _baseline_mode(_load(_materialize_head(tmp), "dn_head"))
        return _live_mode(_load(_LIVE, "dn_live"))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
