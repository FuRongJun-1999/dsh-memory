# -*- coding: utf-8 -*-
"""索引域四处诚实性守卫（R-561 / R-562 / R-563 / R-564 / R-565，2026-11-10）。

缺陷（审计 P1-F1~F5）：
  a) `os.walk` 穿过 junction / 符号链接 ⇒ 库外 `.md` 进索引（R-561）；
  b) 同 `id:` 两文件静默覆盖，另一份既不报错也不可见（R-562）；
  c) `export` 声称「可灾备」但没有 import 逆操作（R-563）；
  d) `materialize_subjects` 硬编码 `/home/ubuntu/mdcg-data`（R-564）；
  e) `condgate.qualify()` 只有测试调用，判据写好没人用（R-565）。

契约（本文件即其守卫）：

  【1】层目录挂 junction 指向库外 ⇒ 库外 `.md` **不进索引**；摘掉判据则必须进（负控）。
  【2】同 id 两文件 ⇒ 索引只留先扫到的一份、`_duplicate_ids` 记录冲突、
      `_covers_disk` 仍为真（冲突不得转嫁给读面变成永久重扫）。
  【3】`materialize_subjects` 的根走 `datapath.mdcg_root()`，代码里不再有本机路径字面量。
  【4】`diagnose` 带 `legacy_pose` 段，且 `qualify` 有非测试调用点。
  【5】`export` 不再把「可灾备」当能力宣称。

运行：python -m md_cg.test_index_honesty
"""
from __future__ import annotations

import io
import os
import shutil
import subprocess
import tempfile

from . import codeindex, condgate, export, materialize_subjects, sustain
from .mdcos import MdCGOS

PASSED = FAILED = 0
HERE = os.path.dirname(os.path.abspath(__file__))


def ok(cond, name):
    global PASSED, FAILED
    if cond:
        PASSED += 1
        print("  [PASS] " + name)
    else:
        FAILED += 1
        print("  [FAIL] " + name)


def _mklink_junction(link, target):
    """Windows 上建 junction（不需要管理员）；非 Windows 退回 symlink。"""
    try:
        if os.name == "nt":
            r = subprocess.run(["cmd", "/c", "mklink", "/J", link, target],
                               capture_output=True, text=True)
            return r.returncode == 0 and os.path.isdir(link)
        os.symlink(target, link, target_is_directory=True)
        return True
    except OSError:
        return False


def main():
    tmp = tempfile.mkdtemp(prefix="idxhon_")
    try:
        print("[1] junction 不穿透（R-561）")
        lib = os.path.join(tmp, "lib")
        outside = os.path.join(tmp, "outside")
        os.makedirs(os.path.join(lib, "knowledge"), exist_ok=True)
        os.makedirs(outside, exist_ok=True)
        with io.open(os.path.join(outside, "leak.md"), "w", encoding="utf-8",
                     newline="\n") as f:
            f.write("# 库外文件\n")
        with io.open(os.path.join(lib, "knowledge", "own.md"), "w",
                     encoding="utf-8", newline="\n") as f:
            f.write("# 库内文件\n")
        link = os.path.join(lib, "knowledge", "link_out")
        made = _mklink_junction(link, outside)
        if not made:
            print("  [SKIP] 本机不支持 junction/symlink")
        else:
            ok(codeindex._is_link_dir(link) is True, "G1a 判据认出链接目录")
            items, _errs, _stats = codeindex.index_dir(lib)
            rels = {i.get("rel") or i.get("path") for i in items}
            ok(not any("leak.md" in str(r) for r in rels),
               "G1b 库外 leak.md 未进索引（%d 条）" % len(items))
            # 负控改成**源码级**：Windows 新版 Python 的 os.walk(followlinks=False)
            # 本身就不下降进 junction，故「摘掉判据就漏」在行为面复现不出来；
            # 能机械钉死的是「判据在路径上」——两处索引模块都必须剪枝。
            srcs = [io.open(os.path.join(HERE, f), encoding="utf-8").read()
                    for f in ("codeindex.py", "docindex.py")]
            ok(all("followlinks=False" in x and "_is_link_dir(" in x for x in srcs),
               "G1c 两处索引模块都剪链接目录（源码级钉子）")

        print("[2] 同 id 两文件（R-562）")
        lib2 = os.path.join(tmp, "lib2")
        os.makedirs(os.path.join(lib2, "knowledge"), exist_ok=True)
        os.makedirs(os.path.join(lib2, "contextual"), exist_ok=True)
        for d, fn in (("knowledge", "a.md"), ("contextual", "b.md")):
            with io.open(os.path.join(lib2, d, fn), "w", encoding="utf-8",
                         newline="\n") as f:
                f.write("---\nid: dup1\nlayer: %s\n---\n# 同名 id\n"
                        % ("knowledge" if d == "knowledge" else "contextual"))
        cg = MdCGOS(lib2)
        ok(list(cg.index["nodes"]).count("dup1") == 1, "G2a 索引里只留一份")
        dup = getattr(cg, "_duplicate_ids", None) or {}
        ok("dup1" in dup and len(dup["dup1"]) == 2, "G2b 冲突被记录（%s）" % (dup,))
        ok(cg._covers_disk(cg.index["nodes"]) is True,
           "G2c 冲突不污染 _covers_disk（快照仍可写，读面不被迫永久重扫）")

        print("[3] 根不硬编码（R-564）")
        src = io.open(os.path.join(HERE, "materialize_subjects.py"),
                      encoding="utf-8").read()
        ok("datapath import mdcg_root" in src.replace(".", "").replace(" ", "") or
           "mdcg_root" in src, "G3a 走 datapath.mdcg_root()")
        ok("/home/ubuntu/mdcg-data" not in src, "G3b 代码里不再有该本机路径字面量")
        from .datapath import mdcg_root
        ok(os.path.normcase(str(materialize_subjects.ROOT)) ==
           os.path.normcase(str(mdcg_root())), "G3c ROOT == datapath.mdcg_root()")

        print("[4] qualify 有在役消费方（R-565）")
        sus = io.open(os.path.join(HERE, "sustain.py"), encoding="utf-8").read()
        ok("legacy_pose_sample(" in sus, "G4a sustain.diagnose 调 legacy_pose_sample")
        cg2 = MdCGOS(os.path.join(tmp, "lib3"))
        cg2.add("q1", "# 功能名：无条件空间\n\n正文。\n", layer="knowledge")
        cg2.flush()
        cg2.rebuild_index()
        d = sustain.diagnose(cg2, check_evolution=False, check_provenance=False)
        ok(isinstance(d.get("legacy_pose"), dict)
           and d["legacy_pose"].get("sampled", 0) >= 1,
           "G4b diagnose 透出 legacy_pose（%s）" % (d.get("legacy_pose"),))
        ok(condgate.legacy_pose_sample(cg2, n=10)["legacy_blindspot"] >= 1,
           "G4c 抽样判据真判出 legacy_blindspot")

        print("[5] export 不再宣称可灾备（R-563）")
        esrc = io.open(os.path.join(HERE, "export.py"), encoding="utf-8").read()
        ok("可搬运、可灾备" not in esrc, "G5a 模块头不再把「可灾备」当能力")
        ok("没有导入" in esrc and "R-563" in esrc, "G5b 明写「只有导出、没有导入」的边界")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    print("\ntest_index_honesty: %d 通过 / %d 失败" % (PASSED, FAILED))
    return 0 if FAILED == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
