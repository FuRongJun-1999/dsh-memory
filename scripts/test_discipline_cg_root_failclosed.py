# -*- coding: utf-8 -*-
"""test_discipline_cg_root_failclosed —— A2 裁决：投影判据体 root 三态 fail-closed + 四自动化面真执行

背景（2026-10-05 使用者裁决 A2）：`scripts/discipline_nodes.py` 的 root 解析此前在
「无 --cg-root 也无 MDCG_ROOT」时一律 `[SKIP]` 退 0 ⇒ 投影判据体（真源 ↔ 认知图
structural/ 下 discipline:N 节点一致性）在**全部自动化面从未执行**；且「提供但不存在」
与「未提供」同分支、文案还误写成「未提供」；「存在但非认知图」则报满额 DRIFT 退 1
——三种误配一绿一红。修后：判据面三态一律 fail-closed（退出码 2，文案各归其态），
四个自动化面各自建最小库（`--init --write --cg-root .tmp/discipline-cg`）再显式传根。

守卫断言（**行为断言**：跑真命令读退出码与输出文案，不做源码文本匹配）：
  S1 未提供          → discipline_nodes.py --check 退出码 ≠ 0，文案含「未提供」
  S2 提供但不存在    → 退出码 ≠ 0，文案含「不存在」且**不得**含「未提供」（旧误写形态）
  S3 存在但非认知图  → 退出码 ≠ 0，文案含「非认知图」，且不得是满额 DRIFT 的旧形态
  S4 verify_discipline.py 同三态 → 退出码 ≠ 0（skipped 不得计入通过）
  S5 合法 root（--init 建的最小库）→ --check 与 verify_discipline --allow-missing 均退 0
     （不得把正常面一起打红）
  S6 四自动化面（package.json gate 链 / discipline-check.yml / verify_linux.sh /
     pre-commit 钩子）各自把 --cg-root 显式交给守卫：逐面抽出其纪律腿并**真跑**，
     全链退 0（面里若漏掉 root，S4 口径会让该腿退 2 ⇒ 本项必红，无需文本匹配）

运行：python -X utf8 scripts/test_discipline_cg_root_failclosed.py
"""
import json
import os
import re
import shlex
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)

_DN = os.path.join(HERE, "discipline_nodes.py")
_VD = os.path.join(HERE, "verify_discipline.py")
_TOOLS = ("scripts/discipline_nodes.py", "scripts/verify_discipline.py")
_FACES = {
    "package.json gate 链": os.path.join(REPO, "package.json"),
    "discipline-check.yml": os.path.join(REPO, ".github", "workflows",
                                         "discipline-check.yml"),
    "verify_linux.sh": os.path.join(HERE, "verify_linux.sh"),
    "pre-commit 钩子": os.path.join(HERE, "git-hooks", "pre-commit"),
}

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


def _env():
    """守卫自身进程环境去掉 MDCG_ROOT：三态断言必须以「未提供」为真前提。"""
    e = dict(os.environ, PYTHONUTF8="1")
    e.pop("MDCG_ROOT", None)
    return e


def _run(argv, cwd=None, env=None):
    p = subprocess.run(argv, capture_output=True, text=True, encoding="utf-8",
                       errors="replace", env=env if env is not None else _env(),
                       cwd=cwd or REPO, timeout=300)
    return p.returncode, (p.stdout or "") + (p.stderr or "")


# 生效条件：给定 argv 尾参，以未设置 MDCG_ROOT 的环境跑 discipline_nodes.py 的 --check，返回 (退出码, 合并输出)。
def _dn_check(extra=()):
    return _run([sys.executable, "-X", "utf8", _DN, "--check"] + list(extra))


# 生效条件：给定 argv 尾参，以未设置 MDCG_ROOT 的环境跑 verify_discipline.py --allow-missing，返回 (退出码, 合并输出)。
def _vd(extra=()):
    return _run([sys.executable, "-X", "utf8", _VD, "--allow-missing"] + list(extra))


# 生效条件：从 pkg 的 gate 串按 "&&" 切条、从 yml/sh/hook 逐行取「run/命令行」，只保留含 _TOOLS 任一名的条目（跳过 '#' 注释行），把首 token 为 python/python3/$PY 者换成当前解释器，返回 [(来源面, argv)]（按文件内原序）。
def _face_legs(name, path):
    """抽出一个自动化面里**真跑纪律腿**的命令行（按文件内原序）。"""
    def _pin(argv):
        if argv and argv[0] in ("python", "python3", "$PY", '"$PY"'):
            return [sys.executable] + argv[1:]
        return argv

    legs = []
    if path.endswith(".json"):
        gate = json.loads(open(path, encoding="utf-8").read())["scripts"]["gate"]
        for leg in gate.split("&&"):
            leg = leg.strip()
            if any(t in leg for t in _TOOLS):
                legs.append((name, _pin(shlex.split(leg))))
        return legs
    is_yaml = path.endswith((".yml", ".yaml"))
    for raw in open(path, encoding="utf-8").read().splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        m = re.match(r"^-?\s*run:\s*(.+)$", line)
        if is_yaml and not m:
            continue          # yml 只认 `run:` 行长（paths: 列表项也含工具名，不是命令）
        cmd = (m.group(1) if m else line)
        cmd = re.sub(r"\s*\\$", "", cmd)
        cmd = re.sub(r"\s*&&\s*(#.*)?$", "", cmd)
        cmd = re.sub(r"\s*>\s*/dev/null\s*2>&1", "", cmd)
        if not any(t in cmd for t in _TOOLS):
            continue
        legs.append((name, _pin(shlex.split(cmd))))
    return legs


def _valid_root(tmp):
    """用一个最小库当「合法 root」：--init --write 建之（与四自动化面同口径）。"""
    return os.path.join(tmp, "cg-lib")


def main():
    global passed, failed
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    with tempfile.TemporaryDirectory() as tmp:
        absent = os.path.join(tmp, "不存在的库")     # 提供但不存在（含中文，顺带钉 UTF-8 面）
        noncg = os.path.join(tmp, "非认知图目录")
        os.makedirs(noncg)
        with open(os.path.join(noncg, "README.md"), "w", encoding="utf-8") as fh:
            fh.write("这不是认知图库。\n")            # 有内容 ⇒ not_library 而非「空目录待建」

        print("[1] 判据面三态 fail-closed（discipline_nodes.py --check）")
        rc, out = _dn_check()
        check("S1 未提供 root → 退出码 ≠ 0（修前 0 + [SKIP]）", rc != 0, "rc=%s %s" % (rc, out[-300:]))
        check("S1 文案为「未提供」态", "未提供" in out, out[-300:])
        rc, out = _dn_check(["--cg-root", absent])
        check("S2 提供但不存在 → 退出码 ≠ 0（修前 0，且文案误写「未提供」）", rc != 0,
              "rc=%s %s" % (rc, out[-300:]))
        check("S2 文案为「不存在」态且不再误写成「未提供」",
              "不存在" in out and "未提供" not in out, out[-300:])
        rc, out = _dn_check(["--cg-root", noncg])
        check("S3 存在但非认知图 → 退出码 ≠ 0（修前报满额 DRIFT 退 1）", rc != 0,
              "rc=%s %s" % (rc, out[-300:]))
        check("S3 文案为「非认知图」态（不是 18 条 missing 的旧形态）",
              "非认知图" in out and "DRIFT" not in out, out[-300:])

        print("[2] 同一口径在守卫入口（verify_discipline.py）")
        rc, out = _vd()
        check("S4 verify 无 root → 退出码 ≠ 0（修前 0：skipped 计入通过）", rc != 0,
              "rc=%s %s" % (rc, out[-200:]))
        check("S4 verify 提供但不存在 → 退出码 ≠ 0", _vd(["--cg-root", absent])[0] != 0,
              _vd(["--cg-root", absent])[1][-200:])
        check("S4 verify 非认知图 → 退出码 ≠ 0", _vd(["--cg-root", noncg])[0] != 0,
              _vd(["--cg-root", noncg])[1][-200:])

        print("[3] 合法 root：正常面不得被打红")
        lib = _valid_root(tmp)
        rc, out = _run([sys.executable, "-X", "utf8", _DN, "--init", "--write",
                        "--cg-root", lib])
        check("S5 前提：--init --write 建最小库成功", rc == 0, "rc=%s %s" % (rc, out[-300:]))
        check("S5 前提：最小库含 structural/ 层",
              os.path.isdir(os.path.join(lib, "structural")), os.listdir(lib))
        rc, out = _dn_check(["--cg-root", lib])
        check("S5 合法 root：--check 退 0（判据体真执行且一致）", rc == 0,
              "rc=%s %s" % (rc, out[-300:]))
        check("S5 合法 root：输出点明扫到的投影节点数（判据体确已执行）",
              "投影节点" in out and "[OK" in out, out[-200:])
        rc, out = _vd(["--cg-root", lib])
        check("S5 合法 root：verify --allow-missing 退 0（正常面不误伤）", rc == 0,
              "rc=%s %s" % (rc, out[-300:]))

    print("[4] 四自动化面：各自的纪律腿真跑（漏 root 即退 2 ⇒ 必红）")
    for name, path in _FACES.items():
        if not os.path.isfile(path):
            skip("S6 " + name, "文件不在（外部 clone 形态）")
            continue
        legs = _face_legs(name, path)
        if len(legs) < 2:
            check("S6 %s：含建库腿 + 验证腿" % name, False,
                  "抽到 %d 条腿：%s" % (len(legs), [l[1] for l in legs]))
            continue
        print("  %s：" % name)
        ok_all = True
        for _src, argv in legs:
            rc, out = _run(argv)
            print("      %s -> rc=%s" % (" ".join(argv[-5:]), rc))
            if rc != 0:
                ok_all = False
                print("        %s" % out[-300:].replace("\n", " | "))
        check("S6 %s：%d 条纪律腿按序真跑全绿" % (name, len(legs)), ok_all, "")

    print("\n%d passed, %d failed, %d skipped" % (passed, failed, skipped))
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
