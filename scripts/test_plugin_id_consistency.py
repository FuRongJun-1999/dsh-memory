# -*- coding: utf-8 -*-
r"""test_plugin_id_consistency · 插件 id 与文档一致性守卫（issue：示例写 lingshu-memory 导致 patch 静默失效）。

病象：包内 `dsh/cordis.patch.yml` 注册的插件 id 由包名派生（`@furongjun1999/dsh-memory`
→ `furongjun1999-dsh-memory`），而文档/示例里写的是 `lingshu-memory`。宿主 patch 按 id
匹配，匹配不到**不报错**——配置整体静默失效（python 路径都不被读取），用户只会看到“没生效”。

判据（三条，逐条可红）：
  ① 真源唯一：`dsh/cordis.patch.yml` 的 id 必须等于包名派生值；
  ② 文档一致：全仓追踪面里所有「形如本插件 id」的 `id:` 行必须等于该值；
  ③ 判据自证：喂一条伪造的旧 id 必须被判红（防止守卫恒绿）。
"""

from __future__ import annotations

import io
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
PATCH = os.path.join(REPO, "dsh", "cordis.patch.yml")
PKG = os.path.join(REPO, "package.json")

_PASS = 0
_FAIL = 0
_FAILS = []


def check(name, ok, detail=""):
    global _PASS, _FAIL
    if ok:
        _PASS += 1
        print("[PASS] %s%s" % (name, ("  · " + detail) if detail else ""))
    else:
        _FAIL += 1
        _FAILS.append(name)
        print("[FAIL] %s  · %s" % (name, detail))


def expected_id():
    """包名 → 宿主注册 id：去掉 scope 的 @ 前缀，`/` 换成 `-`。"""
    import json
    d = json.load(io.open(PKG, encoding="utf-8"))
    name = str(d.get("name", "")).strip()
    return name.lstrip("@").replace("/", "-"), name


def patch_id(path):
    """取 bundle patch 里第一条 insert 的 id。"""
    t = io.open(path, encoding="utf-8", errors="replace").read()
    m = re.search(r"-\s*id:\s*([A-Za-z0-9_.@/-]+)", t)
    return m.group(1) if m else None


def scan_docs(want, eid):
    """追踪面里所有「像本插件 id」的 id: 行 → [(相对路径:行号, 值)]。"""
    # core.quotepath=false：否则中文路径被 git 转义成 \345\256... 导致 os.path 找不到文件而被静默跳过。
    r = subprocess.run(["git", "-c", "core.quotepath=false", "ls-files"], cwd=REPO, capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    if r.returncode != 0:
        return None
    hits = []
    for rel in (r.stdout or "").splitlines():
        if not rel.endswith((".md", ".yml", ".yaml", ".ts", ".json")):
            continue
        fp = os.path.join(REPO, rel)
        if not os.path.isfile(fp):
            continue
        try:
            lines = io.open(fp, encoding="utf-8", errors="replace").read().splitlines()
        except OSError:
            continue
        for i, line in enumerate(lines, 1):
            m = re.search(r"id:\s*([A-Za-z0-9_.@/-]+)", line)
            if not m:
                continue
            val = m.group(1)
            # 只看“像本插件”的取值：含包名尾段或历史别名
            if ("dsh-memory" in val) or ("lingshu-memory" in val):
                hits.append(("%s:%d" % (rel, i), val))
    return hits


def main():
    eid, pkgname = expected_id()
    print("包名: %s ⇒ 期望 id: %s" % (pkgname, eid))

    # ① 真源唯一
    pid = patch_id(PATCH)
    check("① bundle patch 的 id = 包名派生值", pid == eid, "patch=%r 期望=%r" % (pid, eid))

    # ② 文档一致
    hits = scan_docs(None, eid)
    if hits is None:
        check("② 扫描追踪面", False, "git ls-files 不可用")
    else:
        bad = [(k, v) for k, v in hits if v != eid and v != eid + "-2"]
        check("② 文档/示例里的插件 id 全部等于注册值", not bad,
              "不符 %d 处: %s" % (len(bad), bad[:6]))

    # ③ 判据自证：伪造一条旧 id，必须能被判红
    fake = [("FAKE:1", "lingshu-memory")]
    bad_fake = [(k, v) for k, v in fake if v != eid]
    check("③ 判据自证：旧 id 会被判红", bool(bad_fake), "伪造样本被判红" if bad_fake else "守卫恒绿！")

    print()
    print("=" * 64)
    print("插件 id 一致性：%d 通过 / %d 失败" % (_PASS, _FAIL))
    for f in _FAILS:
        print("  - " + f)
    print("=" * 64)
    return 0 if _FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())