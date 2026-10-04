# -*- coding: utf-8 -*-
"""test_linux_verify_exit_code —— N254 Linux 验证脚本「退出码诚实」守卫

背景（2026-10-05 缺陷 N254，severity=high）：`scripts/verify_linux.sh` 与
`scripts/verify_linux_node.sh` 只有 `set -u`（无 `set -e`、无跨段聚合），且末句是
`echo "=== done ==="` / `tail -6 /tmp/ts_test.log` —— **进程退出码恒 0**。本轮实测
（把 python/pip/npm/node/cargo 全桩成 exit 1 后跑）：

    verify_linux.sh       → 打印 `python_suite pass=0 fail=46`、`orch=1 et=1 se=1 jm=1`、
                            `cpa=1`、`gate4=1`，末行 `=== done ===`，**EXITCODE=0**
    verify_linux_node.sh  → 打印 `ci=1 build=1 test=1`，**EXITCODE=0**

这两个脚本是发版/容器验证链的入口（`README.md:591` 的
`docker run … bash scripts/linux_verify.sh full` 直接挂载工作树执行），退出码是它们唯一的
机械消费面；恒 0 等于把门禁变成只会打印的日志——宿主的 `&&` 下一步把「全失败」读成「成功」。
同目录 `scripts/linux_verify.sh:128-129` 早已用同一单点正确传播
（`echo "=== 汇总: $pass pass / $fail fail ==="` + 末行 `[ "$fail" -eq 0 ]`）。
修法：两脚本复用该单点（`note`/`record` + 末行判据），且**各判负段都进同一个 fail 聚合**
——只加末行而各段仍只 echo，则「仅 gate 段败」时退出码照样是 0（本守卫 V3/V4/V7/V8 钉这一点）。

守卫断言面（行为断言：桩工具 + 脚本副本跑真脚本读退出码，不做源码文本匹配）：
  前提：容器腿入口硬编码 `cd /work`（Docker 挂载点），本机/CI 无法原样执行——守卫把脚本
        复制到临时仓并**只**把 `cd /work` 一行重定向到临时仓，其余字节不动（行数不符即报 FAIL）。
        子进程 PATH 由 `_tool_path()` 组成（桩目录 → 本守卫所用 bash 的所在目录 → 继承的 PATH）：
        桩是 `#!/usr/bin/env bash` 脚本、被测脚本还要 `tail`/`uname`，若只依赖继承的 PATH，
        在编排层那种精简环境下会成片 127 —— 那正是本守卫 2026-10-05 那次假红的成因（见该函数注）。
  L0 行尾：三件 Linux 脚本皆 LF（CRLF 会让容器腿在第一步 `set: -^M: invalid option` 退出）
  L0b 前提：桩面可用（全过桩 rc=0 且无 command-not-found；全败桩 rc=1）——把「环境坏了」
        与「被测脚本坏了」分开报，避免一次环境抖动被读成三个断言红。
  L1/L2 verify_linux.sh 全败 → 退出码 ≠ 0（修前 0）／全过 → 退出码 = 0（不误伤）
  L3    仅 gate 段（cogmap/link/index/discipline 链）败 → 退出码 ≠ 0（修前 0）
  L4    仅 hive/scripts 段败 → 退出码 ≠ 0（修前 0）
  L5/L6 verify_linux_node.sh 全败 → ≠ 0（修前 0）／全过 → = 0
  L7    仅 npm run build 败 → ≠ 0（修前 0）
  L8    仅 ts test 败 → ≠ 0（修前 0）
  L9    参照腿：同目录既有单点 scripts/linux_verify.sh 全败 → ≠ 0 / 全过 → = 0（同契约）
  （「全过」腿的失败 detail 会列出被测脚本 stdout 里被记为 `[FAIL]` 的段，红了能一眼定位。）

运行：python -X utf8 scripts/test_linux_verify_exit_code.py
"""
import os
import re
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)

_SCRIPTS = ("verify_linux.sh", "verify_linux_node.sh")
_REF_SCRIPT = "linux_verify.sh"
_TOOLS = ("python", "pip", "npm", "node", "cargo", "python3")

passed = failed = skipped = 0


def check(name, cond, detail=""):
    global passed, failed
    if cond:
        passed += 1
        print("  [PASS] " + name)
    else:
        failed += 1
        print("  [FAIL] " + name + "  "
              + str(detail).replace("\n", " | ")[:400])


def skip(name, why):
    global skipped
    skipped += 1
    print("  [SKIP] %s（%s）" % (name, why))


def _bash_candidates():
    """bash 候选路径，**全部在运行时推导**（不写死任何本机安装路径）。

    为什么运行时推导：本守卫要进公开仓（内容政策·清单 2 禁内嵌作者机器的盘符路径），
    而「本机装了哪个 Git/在哪个目录」是环境事实、不是判据。三条来源：PATH 探测 →
    由 `git` 的安装根同层推出 `usr/bin/bash` → `ProgramFiles` 环境变量拼 Git 目录
    （与 `scripts/check_publish_artifact.py` 运行时拼接 R3 正则同一手法）。
    """
    cands = []
    w = shutil.which("bash")
    if w:
        cands.append(w)
    git = shutil.which("git")
    if git:
        # <安装根>/cmd/git.exe → <安装根>/usr/bin/bash[.exe]（同一安装下的 bash）
        root = os.path.dirname(os.path.dirname(os.path.abspath(git)))
        cands.append(os.path.join(root, "usr", "bin",
                                  "bash.exe" if os.name == "nt" else "bash"))
    for var in ("ProgramFiles", "ProgramW6432"):
        base = os.environ.get(var)
        if base:
            cands.append(os.path.join(base, "Git", "usr", "bin", "bash.exe"))
            cands.append(os.path.join(base, "Git", "bin", "bash.exe"))
    cands += ["/usr/bin/bash", "/bin/bash"]
    return [c for c in cands if c and os.path.isfile(c)]


def _find_bash():
    """取一个非 WSL 的 bash（Windows 上 System32 下的 bash 是 WSL 存根，`execvpe(/bin/bash)` 必失败）。"""
    cands = _bash_candidates()
    for c in cands:
        if "system32" not in c.lower():
            return c
    return cands[0] if cands else None


def _mk_stub(stub_dir, name, body):
    p = os.path.join(stub_dir, name)
    with open(p, "w", encoding="utf-8", newline="\n") as fh:
        fh.write("#!/usr/bin/env bash\n" + body + "\n")
    os.chmod(p, 0o755)


def _install(stub_dir, stubs):
    for t in _TOOLS:
        _mk_stub(stub_dir, t, stubs.get(t, "exit 0"))


def _failed_records(out):
    """脚本 stdout 里被记为 FAIL 的段（供断言 detail 用：全过腿红了要能一眼看出**哪段**失败）。"""
    return [l.strip() for l in (out or "").splitlines() if "[FAIL]" in l][:4]


def _tool_path(bash, stub_dir):
    """子进程 PATH = 桩目录 → **本守卫所用 bash 的所在目录** → 继承的 PATH。

    为什么必须显式补 bash 目录（2026-10-05 实证，不是防御性猜测）：桩是
    `#!/usr/bin/env bash` 脚本，被测脚本还要用 `tail` / `uname` / `mkdir`——这些都从
    **子进程 PATH** 解析。而全量套件由编排层以自己的环境跑时，继承的 PATH 可能不含
    Git 的 `usr/bin`：那时每个桩都 127（`env bash` 找不到 bash）、`tail` 也找不到，
    于是**三个「全过 → 必须 rc=0」的腿全红，而「全败」的腿照绿**（非零本就预期），
    表现为一次偶发假红。本轮复现：把 PATH 收窄到「只留系统目录」（Windows 系统盘下的
    `System32`，此处不写字面绝对路径）后本守卫得
    10 passed / 3 failed（L2/L6/L9-全过），与本仓全量回归当时那次失败逐条吻合。
    桩面与工具面不依赖外界的 PATH，断言才有意义——故把 bash 所在目录钉进 PATH 前段。
    """
    parts = [stub_dir]
    b = os.path.dirname(bash) if bash else ""
    if b:
        parts.append(b)
    parts.append(os.environ.get("PATH", ""))
    return os.pathsep.join([p for p in parts if p])


def _prep(work, script):
    """脚本副本 → (路径, 是否就绪)。

    容器挂载点 `cd /work` 须重定向到临时仓；`linux_verify.sh` 无该行（靠
    `docker -w /work` 定 cwd），原样复制由 cwd 承担——但若该行**存在却非标准形态**
    （如 `cd /work/`）则判不就绪，避免守卫在错误的目录下空跑而假绿。
    """
    txt = open(os.path.join(REPO, "scripts", script), encoding="utf-8").read()
    patched, n = re.subn(r"^cd /work$", "cd " + work.replace("\\", "/"),
                         txt, flags=re.M)
    suspicious = re.search(r"^cd\s+/work", txt, flags=re.M) is not None
    dst = os.path.join(work, script)
    with open(dst, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(patched)
    return dst, (n == 1) or not suspicious


def _run(bash, work, stub_dir, script, stubs, mk_hive=False):
    _install(stub_dir, stubs)
    if mk_hive:
        os.makedirs(os.path.join(work, "hive"), exist_ok=True)
    dst, ok = _prep(work, script)
    if not ok:
        return None, dst
    env = dict(os.environ, PATH=_tool_path(bash, stub_dir), PYTHONUTF8="1")
    p = subprocess.run([bash, dst], capture_output=True, text=True,
                       encoding="utf-8", errors="replace", env=env, cwd=work,
                       timeout=600)
    return p.returncode, p.stdout


_ALL_FAIL = {t: "exit 1" for t in _TOOLS}
_ALL_OK = {t: "exit 0" for t in _TOOLS}
# 仅 gate 链（cogmap/link/index/discipline）败：python 只对 cogmap_sync.py 返回 1
_GATE_ONLY = dict(_ALL_OK, python='for a in "$@"; do case "$a" in *cogmap_sync.py*) exit 1;; esac; done\nexit 0')
# 仅 hive/scripts 段败
_HIVE_ONLY = dict(_ALL_OK, python='for a in "$@"; do case "$a" in *test_orch.py*) exit 1;; esac; done\nexit 0')
# 仅 npm run build 败（npm ci 仍成功）
_BUILD_ONLY = dict(_ALL_OK, npm='for a in "$@"; do [ "$a" = "run" ] && exit 1; done\nexit 0')
# 仅 ts test 败
_TEST_ONLY = dict(_ALL_OK, node='for a in "$@"; do [ "$a" = "--test" ] && exit 1; done\nexit 0')


def main():
    global passed, failed
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    print("[1] L0 行尾（CRLF 会让容器腿第一步即语法错退出）")
    for name in _SCRIPTS:
        b = open(os.path.join(REPO, "scripts", name), "rb").read()
        check("L0 %s 为 LF（CRLF=0）" % name, b.count(b"\r\n") == 0,
              "CRLF=%d" % b.count(b"\r\n"))

    bash = _find_bash()
    if bash is None:
        skip("L1–L9", "本机无 bash（容器腿行为断言需要）")
        print("\n%d passed, %d failed, %d skipped" % (passed, failed, skipped))
        return 1 if failed else 0

    with tempfile.TemporaryDirectory() as tmp:
        work = os.path.join(tmp, "work")
        stub = os.path.join(tmp, "stub")
        os.makedirs(work)
        os.makedirs(stub)

        # L0b 前提：桩面本身的可用性——「让所有工具返回 0/1」这件事必须先成立，
        # 否则下面「全过 → rc=0」的腿测的是环境而非被测脚本（2026-10-05 那次假红即
        # 此前提失效：桩的 `#!/usr/bin/env bash` 在精简 PATH 下 127）。
        _install(stub, _ALL_OK)
        p_ok = subprocess.run([bash, "-c", "python --version"], capture_output=True,
                              text=True, encoding="utf-8", errors="replace",
                              env=dict(os.environ, PATH=_tool_path(bash, stub)),
                              cwd=work, timeout=120)
        _install(stub, _ALL_FAIL)
        p_no = subprocess.run([bash, "-c", "python --version"], capture_output=True,
                              text=True, encoding="utf-8", errors="replace",
                              env=dict(os.environ, PATH=_tool_path(bash, stub)),
                              cwd=work, timeout=120)
        check("L0b 前提：桩面可用（全过桩 rc=0 且无「command not found」）",
              p_ok.returncode == 0 and "not found" not in (p_ok.stderr or ""),
              "rc=%s err=%s" % (p_ok.returncode, (p_ok.stderr or "")[:120]))
        check("L0b 前提：全败桩 rc=1（桩面语义正确）", p_no.returncode == 1,
              "rc=%s" % p_no.returncode)

        print("[2] verify_linux.sh（修前：全败仍 EXITCODE=0）")
        rc, out = _run(bash, work, stub, "verify_linux.sh", _ALL_FAIL)
        if rc is None:
            check("L1 全败 → 退出码 ≠ 0", False, "副本未含容器挂载点行 cd /work")
        else:
            check("L1 全败 → 退出码 ≠ 0（修前 EXITCODE=0）", rc != 0,
                  "rc=%s | %s" % (rc, [l for l in out.splitlines() if l][-3:]))
            check("L1 全败读数含 python_suite fail=46（前提坐实）",
                  "python_suite pass=0 fail=46" in (out or ""),
                  [l for l in (out or "").splitlines() if "python_suite" in l])
        rc, out = _run(bash, work, stub, "verify_linux.sh", _ALL_OK)
        check("L2 全过 → 退出码 = 0（不误伤）", rc == 0,
              "rc=%s 失败段=%s" % (rc, _failed_records(out)))
        rc, out = _run(bash, work, stub, "verify_linux.sh", _GATE_ONLY)
        check("L3 仅 gate 段败 → 退出码 ≠ 0（修前 EXITCODE=0）", rc not in (0, None),
              "rc=%s 失败段=%s" % (rc, _failed_records(out)))
        rc, out = _run(bash, work, stub, "verify_linux.sh", _HIVE_ONLY)
        check("L4 仅 hive/scripts 段败 → 退出码 ≠ 0（修前 EXITCODE=0）",
              rc not in (0, None), "rc=%s 失败段=%s" % (rc, _failed_records(out)))

        print("[3] verify_linux_node.sh（修前：全败仍 EXITCODE=0）")
        rc, out = _run(bash, work, stub, "verify_linux_node.sh", _ALL_FAIL)
        if rc is None:
            check("L5 全败 → 退出码 ≠ 0", False, "副本未含容器挂载点行 cd /work")
        else:
            check("L5 全败 → 退出码 ≠ 0（修前 EXITCODE=0）", rc != 0,
                  "rc=%s | %s" % (rc, [l for l in out.splitlines() if l][-3:]))
        rc, out = _run(bash, work, stub, "verify_linux_node.sh", _ALL_OK)
        check("L6 全过 → 退出码 = 0（不误伤）", rc == 0,
              "rc=%s 失败段=%s" % (rc, _failed_records(out)))
        rc, out = _run(bash, work, stub, "verify_linux_node.sh", _BUILD_ONLY)
        check("L7 仅 npm run build 败 → 退出码 ≠ 0（修前 EXITCODE=0）",
              rc not in (0, None), "rc=%s" % rc)
        rc, out = _run(bash, work, stub, "verify_linux_node.sh", _TEST_ONLY)
        check("L8 仅 ts test 败 → 退出码 ≠ 0（修前 EXITCODE=0）",
              rc not in (0, None), "rc=%s" % rc)

        print("[4] L9 参照腿：既有单点 scripts/linux_verify.sh 同契约")
        rc, _ = _run(bash, work, stub, _REF_SCRIPT, _ALL_FAIL, mk_hive=True)
        check("L9 linux_verify.sh 全败 → 退出码 ≠ 0（同一单点口径）",
              rc not in (0, None), "rc=%s" % rc)
        rc, out = _run(bash, work, stub, _REF_SCRIPT, _ALL_OK, mk_hive=True)
        check("L9 linux_verify.sh 全过 → 退出码 = 0", rc == 0,
              "rc=%s 失败段=%s" % (rc, _failed_records(out)))

    print("\n%d passed, %d failed, %d skipped" % (passed, failed, skipped))
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
