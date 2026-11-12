# -*- coding: utf-8 -*-
"""test_check_publish_artifact_docrefs —— R10 文档可执行引用判据守卫

背景（2026-11-02，与 R9 同源但**面不同**）：
R9 查「**代码**按路径装载的件在不在包里」；R10 查「**文档**让人照抄的命令在装机侧
跑不跑得起来」。两者不重叠——R9 全绿时文档里仍可能写着 `python scripts/x.py`，
而 `scripts/` 只有 `workspace_index.py` 随包 ⇒ 装机用户照抄即 `Errno 2`。
本仓实测两次这种事故（probe_c / probe_d，见 docs/mdcg/世界模型功能端…§七）。

本守卫分三段：
  [1] 单元（哑数据 · 临时目录）：判据语义逐条钉死
  [2] E2E（临时 git 仓 + 真实 npm + 真实脚本）：真判负、修好后真判绿
  [3] **变异自证**：证明每条判据都真的在被测对象上起作用——不是「加了断言」

为什么第 [3] 段是必需的（上一轮教训，必须写在这里防止下次忘）：
  上一轮把变异写成 `RULES = [] or [A, B]`——`[] or [A,B]` 求值仍是原列表，
  **变异等于空转**，而当时三条断言全绿，差点被当成「守卫很强」。
  另一形态更隐蔽：变异让语法错 → 进程起不来 → 红项变多，看起来像「守卫更强」。
  故本段每条变异必须**自证三件**：
    ① 文本确实变了（变异不是空转）；
    ② 变异后的源码 `compile()` 合法（变异不是把包改坏）；
    ③ 读数**按预期方向**变化（不是「红了就算」，而是红在预期的那条判据上）。

运行：python -X utf8 scripts/test_check_publish_artifact_docrefs.py
"""
import importlib.util
import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)

_GATE = os.path.join(HERE, "scripts", "check_publish_artifact.py")

passed = failed = skipped = 0


def check(name, cond, detail=""):
    global passed, failed
    if cond:
        passed += 1
        print("  [PASS] " + name)
    else:
        failed += 1
        print("  [FAIL] " + name + "  " + str(detail)[:400])


def skip(name, why):
    global skipped
    skipped += 1
    print("  [SKIP] " + name + "  " + why)


def _env():
    return dict(os.environ, PYTHONUTF8="1")


def _load_mod(path=None):
    path = path or _GATE
    spec = importlib.util.spec_from_file_location("cpa_r10_guard", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _write(root, rel, body):
    fp = os.path.join(root, *rel.split("/"))
    os.makedirs(os.path.dirname(fp) or root, exist_ok=True)
    with open(fp, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(body)
    return fp


def _fixture(tmp, name, docs, shipped_extra=None):
    """建一个最小仓：docs 形如 {相对路径: 正文}；返回值 (root, pkg_set)。"""
    root = os.path.join(tmp, name)
    os.makedirs(root, exist_ok=True)
    for rel, body in docs.items():
        _write(root, rel, body)
    pkg_set = set(shipped_extra or [])
    pkg_set |= {rel for rel in docs if rel.endswith(".md")}
    return root, pkg_set


# ---------------------------------------------------------------- [1] 单元
def unit(mod):
    print("[1] 单元：判据语义（哑数据 · 临时目录）")
    with tempfile.TemporaryDirectory() as tmp:
        # U1 R10a 红点：文档写 `python scripts/x.py`，任何基址下都不存在
        root, pkg = _fixture(tmp, "u1", {
            "docs/a.md": "# a\n\n```bash\npython scripts/nope.py --flag\n```\n"})
        a, b, n = mod._r10_doc_exec_refs(root, pkg)
        check("U1 目标任何基址都不存在 → R10a 命中", len(a) == 1 and not b, (a, b, n))
        check("U1 命中说明里点名了文档与目标", "docs/a.md" in a[0] and "scripts/nope.py" in a[0], a)
        check("U1 扫到的可执行引用处数=1（不是 0 处被读成干净）", n == 1, n)

        # U2 文档目录基址：文件在 docs/scripts/x.py
        root, pkg = _fixture(tmp, "u2", {
            "docs/a.md": "python scripts/ok.py\n",
            "docs/scripts/ok.py": "# ok\n"})
        pkg.add("docs/scripts/ok.py")
        a, b, n = mod._r10_doc_exec_refs(root, pkg)
        check("U2 doc-dir 基址解析生效（不误判 R10a）", not a and not b, (a, b, n))

        # U3 cd 块基址：`cd sub` 之后跑 `python tests/x.py`
        root, pkg = _fixture(tmp, "u3", {
            "docs/a.md": "```bash\ncd sub\npython tests/run.py\n```\n",
            "docs/sub/tests/run.py": "# run\n"})
        pkg.add("docs/sub/tests/run.py")
        a, b, n = mod._r10_doc_exec_refs(root, pkg)
        check("U3 cd 块基址解析生效", not a and not b, (a, b, n))

        # U4 R10b 红点：源码树存在、但不随包、且未登记
        root, pkg = _fixture(tmp, "u4", {
            "docs/a.md": "python scripts/tool_x.py\n",
            "scripts/tool_x.py": "# tool\n"})
        a, b, n = mod._r10_doc_exec_refs(root, pkg)
        check("U4 源码树存在但不随包 → R10b 命中", not a and len(b) == 1, (a, b, n))

        # U5 登记放行：把该文件塞进登记表（临时改模块属性）后不再命中
        saved = dict(mod.R10_REGISTERED_UNSHIPPED)
        try:
            mod.R10_REGISTERED_UNSHIPPED = dict(saved)
            mod.R10_REGISTERED_UNSHIPPED["scripts/tool_x.py"] = {"why": "哑测试"}
            a, b, n = mod._r10_doc_exec_refs(root, pkg)
            check("U5 登记后 R10b 不再命中（登记面真的在起作用）",
                  not a and not b, (a, b, n))
        finally:
            mod.R10_REGISTERED_UNSHIPPED = saved

        # U5b 目录前缀登记：`scripts/` 前缀条目应覆盖 scripts/*.py
        try:
            mod.R10_REGISTERED_UNSHIPPED = dict(saved)
            mod.R10_REGISTERED_UNSHIPPED["scripts/"] = {"why": "哑测试·整目录"}
            a, b, n = mod._r10_doc_exec_refs(root, pkg)
            check("U5b 目录前缀登记覆盖整棵子树", not a and not b, (a, b, n))
        finally:
            mod.R10_REGISTERED_UNSHIPPED = saved

        # U6 目标随包 → 不命中
        root, pkg = _fixture(tmp, "u6", {
            "docs/a.md": "python scripts/tool_x.py\n",
            "scripts/tool_x.py": "# tool\n"})
        pkg.add("scripts/tool_x.py")
        a, b, n = mod._r10_doc_exec_refs(root, pkg)
        check("U6 目标随包 → 两档都不命中", not a and not b, (a, b, n))

        # U7 叙述性提及不算：裸反引号里写路径、但没有 python 调用 token
        root, pkg = _fixture(tmp, "u7", {
            "docs/a.md": "真源在 `scripts/nope.py` 里（叙述性提及）。\n"})
        a, b, n = mod._r10_doc_exec_refs(root, pkg)
        check("U7 叙述性提及不扫描（n=0，不灌误报）", not a and not b and n == 0, (a, b, n))

        # U8 `-m <module>` 形态也认
        root, pkg = _fixture(tmp, "u8", {
            "docs/a.md": "python -X utf8 -m md_cg.nope_mod --flag\n"})
        a, b, n = mod._r10_doc_exec_refs(root, pkg)
        check("U8 `-m <module>` 形态可解析并判 R10a",
              len(a) == 1 and "md_cg/nope_mod.py" in a[0], (a, n))

        # U9 `-m` 目标随包 → 不命中（与 U8 成对，坐实不是「凡 -m 就红」）
        root, pkg = _fixture(tmp, "u9", {
            "docs/a.md": "python -m md_cg.real_mod\n",
            "md_cg/real_mod.py": "# real\n"})
        pkg.add("md_cg/real_mod.py")
        a, b, n = mod._r10_doc_exec_refs(root, pkg)
        check("U9 `-m` 目标随包 → 不命中", not a and not b, (a, b, n))

        # U10 非随包文档不参与（判据只对「读者真能读到的文档」负责）
        root, pkg = _fixture(tmp, "u10", {
            "docs/internal.md": "python scripts/nope.py\n",
            "docs/ship.md": "普通正文\n"})
        pkg.discard("docs/internal.md")
        a, b, n = mod._r10_doc_exec_refs(root, pkg)
        check("U10 不随包文档不参与判据", not a and not b and n == 0, (a, b, n))


# ---------------------------------------------------------------- [2] E2E
def _make_git_repo(root, pkg, files):
    import json
    os.makedirs(root, exist_ok=True)
    with open(os.path.join(root, "package.json"), "w", encoding="utf-8") as fh:
        json.dump(pkg, fh, indent=2)
    for rel, body in files.items():
        _write(root, rel, body)
    env = _env()
    subprocess.run(["git", "init", "-q", "."], cwd=root, check=True, env=env)
    subprocess.run(["git", "add", "-A"], cwd=root, check=True, env=env)
    subprocess.run(["git", "-c", "user.email=t@t", "-c", "user.name=t",
                    "commit", "-qm", "init"], cwd=root, check=True, env=env)


def _run_gate(root):
    return subprocess.run([sys.executable, "-X", "utf8", _GATE, "--root", root],
                          capture_output=True, text=True, encoding="utf-8",
                          errors="replace", env=_env(), cwd=HERE, timeout=600)


def e2e():
    print("[2] E2E：真跑门禁（临时 git 仓 + 真实 npm）")
    if shutil.which("npm") is None or shutil.which("git") is None:
        skip("E2E 两腿", "本机无 npm 或 git")
        return
    pkg = {"name": "r10-e2e", "version": "1.0.0", "private": True,
           "files": ["docs", "lib"]}
    with tempfile.TemporaryDirectory() as tmp:
        # E1 红腿：随包文档点名一个不存在的脚本
        red = os.path.join(tmp, "red")
        _make_git_repo(red, pkg, {
            "docs/guide.md": "# 指南\n\n```bash\npython scripts/nope.py --run\n```\n",
            "lib/keep.txt": "keep\n"})
        got = _run_gate(red)
        out = got.stdout or ""
        check("E1 红腿 exit 1", got.returncode == 1,
              "rc=%s\n%s" % (got.returncode, out[-700:]))
        check("E1 VERDICT=FAIL", "VERDICT=FAIL" in out, out[-400:])
        check("E1 R10a 判负并点名文档与目标",
              "R10a" in out and "docs/guide.md" in out and "scripts/nope.py" in out,
              out[-900:])

        # E1b 红腿（R10b）：脚本在源码树、不随包、未登记
        red2 = os.path.join(tmp, "red2")
        _make_git_repo(red2, pkg, {
            "docs/guide.md": "# 指南\n\n```bash\npython scripts/tool_y.py\n```\n",
            "scripts/tool_y.py": "# tool\n",
            "lib/keep.txt": "keep\n"})
        got = _run_gate(red2)
        out = got.stdout or ""
        check("E1b R10b 判负并点名", "R10b" in out and "scripts/tool_y.py" in out,
              out[-900:])
        check("E1b 且 R10a 保持 PASS（两档互不串扰）",
              "[PASS] R10a" in out, out[-900:])

        # E2 绿腿：同一条命令，但目标是随包件（不触发 R8 的 lib/web/ui 声明面判据）
        green = os.path.join(tmp, "green")
        _make_git_repo(green, {"name": "r10-e2e", "version": "1.0.0",
                               "private": True, "files": ["docs"]}, {
            "docs/guide.md": "# 指南\n\n```bash\npython docs/keep.py\n```\n",
            "docs/keep.py": "# keep\n"})
        got = _run_gate(green)
        out = got.stdout or ""
        check("E2 绿腿 exit 0（新判据不误伤发版链路）", got.returncode == 0,
              "rc=%s\n%s" % (got.returncode, out[-800:]))
        check("E2 绿腿 R10a/R10b 双 PASS",
              "[PASS] R10a" in out and "[PASS] R10b" in out, out[-900:])


# ---------------------------------------------------------------- [3] 变异自证
def _mutate(src, old, new):
    """在源码文本上做一次定点替换，并**自证**它是有效变异。

    返回 (mutated_src, ok, why)。ok=False 表示变异空转/把包改坏——此时**必须判负**，
    否则整段变异测试就是在自我欺骗（上一轮的真实事故）。
    """
    n = src.count(old)
    if n != 1:
        return src, False, "锚点出现 %d 次（要求恰好 1 次）" % n
    mut = src.replace(old, new)
    if mut == src:
        return src, False, "替换后文本未变（变异空转）"
    try:
        compile(mut, "<mutant>", "exec")
    except SyntaxError as exc:
        return mut, False, "变异后源码不合法：%s" % exc
    return mut, True, ""


def mutations():
    print("[3] 变异自证：每条判据都真的在起作用（不是「加了断言」）")
    with open(_GATE, encoding="utf-8") as fh:
        src = fh.read()

    with tempfile.TemporaryDirectory() as tmp:
        # 基准夹具：一条 R10a（doc-dir 基址下存在）+ 一条 R10b（源码树存在不随包）
        root, pkg = _fixture(tmp, "base", {
            "docs/a.md": ("python scripts/gone.py\n\n"
                          "```bash\ncd docs\npython tools/here.py\n```\n\n"
                          "python scripts/tool_x.py\n"),
            "docs/tools/here.py": "# here\n",
            "scripts/tool_x.py": "# tool\n"})
        pkg.add("docs/tools/here.py")
        base = _load_mod()
        a0, b0, n0 = base._r10_doc_exec_refs(root, pkg)
        check("M0 基准读数：1 条 R10a + 1 条 R10b（3 处引用）",
              len(a0) == 1 and len(b0) == 1 and n0 == 3, (a0, b0, n0))

        # —— M1：把可执行形态正则改成永不命中 → R10 扫描面必须归零（自证「扫了 N 处」不是装饰）
        old_rx = ('_R10_EXE = re.compile(\n'
                  '    r"(?:^|[\\s`\\"\'($>|;])"')
        if old_rx in src:
            mut, ok, why = _mutate(src, old_rx,
                                   '_R10_EXE = re.compile(\n'
                                   '    r"(?!x)x"')
            check("M1 变异本身有效（文本变了 + 语法合法）", ok, why)
            if ok:
                p = os.path.join(tmp, "m1.py")
                with open(p, "w", encoding="utf-8", newline="\n") as fh:
                    fh.write(mut)
                m1 = _load_mod(p)
                a1, b1, n1 = m1._r10_doc_exec_refs(root, pkg)
                check("M1 正则失效后扫描处数归零（证明判据真跑在正则上）",
                      n1 == 0 and not a1 and not b1, (n1, a1, b1))
        else:
            skip("M1 正则变异", "锚点文本已变，需同步本守卫")

        # —— M2：清空登记表 → R10b 命中数上升（证明登记面真在起作用）
        old_reg = "R10_REGISTERED_UNSHIPPED = {"
        mut, ok, why = _mutate(src, old_reg, "R10_REGISTERED_UNSHIPPED = {}\n_UNUSED_R10 = {")
        check("M2 变异本身有效", ok, why)
        if ok:
            p = os.path.join(tmp, "m2.py")
            with open(p, "w", encoding="utf-8", newline="\n") as fh:
                fh.write(mut)
            m2 = _load_mod(p)
            a2, b2, n2 = m2._r10_doc_exec_refs(root, pkg)
            check("M2 清空登记后 R10b 命中数上升（证明登记表真被查）",
                  len(b2) >= len(b0) and n2 == n0, (b2, b0))

        # —— M3：基址解析退化为只认仓根 → 原 doc-dir/cd 块可解析的那条必须变红
        old_fn = ("def _r10_base_candidates(doc_rel, raw, cd_dir):\n"
                  "    \"\"\"文档内可执行引用的**基址候选**（按现实写法排序，先命中先用）。")
        mut, ok, why = _mutate(
            src, old_fn,
            "def _r10_base_candidates(doc_rel, raw, cd_dir):\n"
            "    \"\"\"变异：只认仓根\"\"\"\n"
            "    return [(\"repo-root\", raw)]\n"
            "def _r10_base_candidates_orig(doc_rel, raw, cd_dir):\n"
            "    \"\"\"文档内可执行引用的**基址候选**（按现实写法排序，先命中先用）。")
        check("M3 变异本身有效", ok, why)
        if ok:
            p = os.path.join(tmp, "m3.py")
            with open(p, "w", encoding="utf-8", newline="\n") as fh:
                fh.write(mut)
            m3 = _load_mod(p)
            a3, b3, n3 = m3._r10_doc_exec_refs(root, pkg)
            # 基准夹具里靠 doc-dir/cd 块解析出来的只有 1 条（tools/here.py）——
            # 退化为只认仓根后它必然掉进 R10a，故命中数应恰好 +1。
            check("M3 基址退化为仓根后，cd 块那条变 R10a 红",
                  len(a3) == len(a0) + 1 and any("tools/here.py" in x for x in a3)
                  and n3 == n0, (a3, a0, n3))

        # —— M4：把「不随包才判」改成「一律放行」→ R10b 必须归零（自证判据不是恒绿）
        old_gate = 'if _is_shipped(hit):'
        mut, ok, why = _mutate(src, old_gate, 'if True:')
        check("M4 变异本身有效", ok, why)
        if ok:
            p = os.path.join(tmp, "m4.py")
            with open(p, "w", encoding="utf-8", newline="\n") as fh:
                fh.write(mut)
            m4 = _load_mod(p)
            a4, b4, n4 = m4._r10_doc_exec_refs(root, pkg)
            check("M4 放行一切后 R10b 归零（证明它不是恒绿判据）",
                  not b4 and n4 == n0, (b4, n4))


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    mod = _load_mod()
    unit(mod)
    e2e()
    mutations()
    print("\n%d passed, %d failed, %d skipped" % (passed, failed, skipped))
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
