# -*- coding: utf-8 -*-
"""test_mdcg_stale_servers_scan —— N255 进程代际守卫「探测可用性 + 只读边界」守卫

背景（2026-10-05 缺陷 N255，severity=high）：`scripts/mdcg_stale_servers.py` 有两条互相
纠缠的缺陷，一跑就同时发作（本轮实测，见 G2）：

  ① **探测失败被当成「没有进程」**：`_ps`（:132-141）只把 stdout+stderr 并流、**丢掉退出码**，
     `_parse_ps` 对 `<ERR …>` 这类文本可解析出**伪记录**（缺 Name 键），`scan()` 的
     `name.startswith("python")` 对它恒为假 → rows=[] → `risky=[]` →
     `list --fail-on-stale` 判「前置守卫通过」（退出码 0）。
  ② **`scan()` 尾部无条件 `purge(pids)`**（:277-281）与模块 docstring:4「只读枚举无副作用」、
     main 生效条件「不改状态」直接矛盾；探测失败时 `pids=[]` → `purge([])` 的 keep 为空集 →
     `md_cg/selfreport.py:130-152` 删除**目录下全部** *.json（含其它在役进程/其它端的自报）。

实测读数（沙盒 TEMP=`<tmp>` 预置 3 个自报 *.json、PATH 不含 powershell）：

    [修前] list --fail-on-stale → stdout「污染源 0 个：无」、EXITCODE=0；沙盒自报目录 → []
    [修后] list --fail-on-stale → stderr「[环境错误] 进程探测不可用…」、EXITCODE=2；3 件原样在位

修法：探测可用性收成单点 `probe_processes()`（Four 判据：未能执行 / 非零退出 / `<ERR` 标记 /
输出不可解析或记录缺 Name·ProcessId），探测不可用一律 fail-closed（list/kill/purge 退 2 或
记 ok=False）；`purge` 移出 `scan()`，改挂显式清理路径（`purge` 子命令与 `kill --purge-report`），
且 `selfreport.purge` 对空 keep 默认不删（`allow_empty` 显式开启）。

守卫断言面（Windows-only：该脚本 import 期即 `ctypes.WinDLL("kernel32")`；非 Windows 如实 SKIP）：
  G0 前提：Windows + 模块可导入
  G1 unit：probe_processes 对五种 `_ps` 输出判定正确（四种不可用形态各判 err，正常输出判可用）
  G2 E2E·探测不可用：list --fail-on-stale → 退出码 ≠ 0（修前 0）、stderr 报环境错误、
     **沙盒自报 3 件原样在位**（修前被 purge([]) 删光）
  G3 E2E·list 只读（探测可用）：沙盒自报 3 件仍在（修前被删），退出码 ∈ {0,1}
  G4 E2E·`purge` 子命令（探测可用）：退出码 0 且**确实**清掉非在役自报（修前无此子命令→2）
  G5 E2E·`purge` 探测不可用：退出码 2 且沙盒 3 件仍在（fail-closed：坏探测不得导致删光）
  G6 E2E·`kill` 探测不可用：报「探测不可用」而非「进程不存在」（修前误报后者），退出码 ≠ 0
  G7 E2E·`kill` 针对不存在 pid（探测可用）：报「进程不存在」、退出码 1，且绝不 taskkill
  G8 E2E·`--json` 形状兼容：可用时为 JSON 数组；不可用时为 `[]` + 退出码 2
  G9 unit：`selfreport.purge` 空 keep 默认不删、allow_empty=True 才删
  G10 unit：`selfreport` 的 report/info 契约未被本次改动破坏（写入沙盒后 read_all 可读回）

运行：python -X utf8 scripts/test_mdcg_stale_servers_scan.py
"""
import importlib.util
import json
import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, REPO)
_SCRIPT = os.path.join(HERE, "mdcg_stale_servers.py")

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


def _load_mod(name):
    spec = importlib.util.spec_from_file_location(name, _SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _seed(dirpath, pids=(999001, 999002, 999003)):
    os.makedirs(dirpath, exist_ok=True)
    for pid in pids:
        with open(os.path.join(dirpath, "%d.json" % pid), "w",
                  encoding="utf-8") as fh:
            json.dump({"schema": 1, "pid": pid, "ts": 1e9, "tag": "seed",
                       "source_dir": "sandbox", "render_version": 2}, fh)
    return sorted(os.listdir(dirpath))


def _sandbox_env(sandbox, reachable_ps: bool):
    """reachable_ps=False：PATH 指到一个空目录 → `powershell` 找不到（探测不可用）。"""
    env = {k: os.environ[k] for k in
           ("SystemRoot", "SystemDrive", "USERPROFILE", "PATHEXT",
            "COMSPEC", "NUMBER_OF_PROCESSORS", "windir")
           if k in os.environ}
    env["TEMP"] = sandbox
    env["TMP"] = sandbox
    env["PYTHONUTF8"] = "1"
    env["PATH"] = (os.environ.get("PATH", "") if reachable_ps
                   else os.path.join(sandbox, "nobin"))
    return env


def _run(sandbox, args, reachable_ps=True):
    if not reachable_ps:
        os.makedirs(os.path.join(sandbox, "nobin"), exist_ok=True)
    p = subprocess.run([sys.executable, "-X", "utf8", _SCRIPT] + args,
                       capture_output=True, text=True, encoding="utf-8",
                       errors="replace", env=_sandbox_env(sandbox, reachable_ps),
                       cwd=REPO, timeout=600)
    return p.returncode, (p.stdout or ""), (p.stderr or "")


_PS_OK = ("ProcessId      : 4242\nParentProcessId : 1\nName           : python\n"
          "CreationDate   : 2026/10/05 10:00:00\nCommandLine    : python -m md_cg.mcp_server\n\n")
_PS_PSEUDO = "<ERR FileNotFoundError: [WinError 2] 系统找不到指定的文件。>"


def main():
    global passed, failed
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    if os.name != "nt":
        skip("G0–G10", "mdcg_stale_servers 是 Windows-only（import 期 ctypes.WinDLL）")
        print("\n%d passed, %d failed, %d skipped" % (passed, failed, skipped))
        return 0
    try:
        mod = _load_mod("n255_stale")
        mod_ok = True
    except Exception as exc:  # noqa: BLE001
        mod_ok = False
        check("G0 模块可导入", False, "%s: %s" % (type(exc).__name__, exc))
    if not mod_ok:
        print("\n%d passed, %d failed, %d skipped" % (passed, failed, skipped))
        return 1
    check("G0 前提：Windows 且模块可导入", True)
    try:
        import md_cg.selfreport as sr
    except Exception as exc:  # noqa: BLE001
        check("G0 selfreport 可导入", False, str(exc))
        print("\n%d passed, %d failed, %d skipped" % (passed, failed, skipped))
        return 1

    print("[1] G1 探测可用性单点（unit，桩 _ps）")
    probe = getattr(mod, "probe_processes", None)
    if probe is None:
        check("G1 探测可用性单点 probe_processes 存在（N255 新增）", False,
              "模块未导出该单点——探测失败仍会被当成「无进程」")
    else:
        cases = [
            ((_PS_PSEUDO, None), False, "PowerShell 未能执行（rc=None）"),
            (("err text", 1), False, "PowerShell 非零退出"),
            (("<ERR TimeoutExpired: 超时>", 0), False, "输出带 <ERR 标记"),
            (("", 0), False, "输出为空"),
            ((_PS_PSEUDO, 0), False, "伪记录（<ERR 文本被解析成记录）"),
            ((_PS_OK, 0), True, "正常 Format-List 输出"),
        ]
        for (ret, usable, label) in cases:
            mod._ps = lambda *a, _r=ret, **k: _r
            rows, err = probe()
            if usable:
                check("G1 %s → 判可用（err=None 且记录非空）" % label,
                      err is None and bool(rows), (rows, err))
            else:
                check("G1 %s → 判不可用（err 非 None）" % label, bool(err), (rows, err))

    print("[2] G2 沙盒 E2E·探测不可用（修前：判绿 + 自报被删光）")
    with tempfile.TemporaryDirectory() as sandbox:
        rep = os.path.join(sandbox, "md_cg_servers")
        before = _seed(rep)
        check("G2 前提：沙盒预置 3 个自报文件", before == ["999001.json", "999002.json",
                                                        "999003.json"], before)
        rc, out, err = _run(sandbox, ["list", "--fail-on-stale"], reachable_ps=False)
        check("G2 探测不可用 → 退出码 ≠ 0（修前 EXITCODE=0）", rc != 0,
              "rc=%s | %s" % (rc, out[-300:]))
        check("G2 stderr 报环境错误（不判「前置守卫通过」）",
              "环境错误" in err and "探测不可用" in err, err[:300])
        check("G2 沙盒自报 3 件原样在位（修前被 purge([]) 删光）",
              sorted(os.listdir(rep)) == before, sorted(os.listdir(rep)))

    print("[3] G3/G4/G5 沙盒 E2E·list 只读 与 显式清理")
    with tempfile.TemporaryDirectory() as sandbox:
        rep = os.path.join(sandbox, "md_cg_servers")
        before = _seed(rep)
        rc, out, err = _run(sandbox, ["list"], reachable_ps=True)
        check("G3 list（探测可用）→ 沙盒自报 3 件仍在（修前被删）",
              sorted(os.listdir(rep)) == before, sorted(os.listdir(rep)))
        check("G3 list 退出码 ∈ {0,1}（只读，不因环境报错）", rc in (0, 1), rc)

        rc, out, err = _run(sandbox, ["purge"], reachable_ps=True)
        check("G4 `purge` 子命令 → 退出码 0（修前无此子命令：argparse exit 2）",
              rc == 0, "rc=%s | %s | %s" % (rc, out[-200:], err[-200:]))
        left = sorted(os.listdir(rep))
        check("G4 非在役自报确被清掉（清理能力未丢）", left == [], left)

        before2 = _seed(rep)
        rc, out, err = _run(sandbox, ["purge"], reachable_ps=False)
        check("G5 探测不可用时 `purge` → 退出码 2 且报「拒绝清理」",
              rc == 2 and "拒绝清理" in err, "rc=%s | %s" % (rc, err[:200]))
        check("G5 探测不可用时 `purge` 不删任何文件（fail-closed）",
              sorted(os.listdir(rep)) == before2, sorted(os.listdir(rep)))

    print("[4] G6/G7/G8 kill 与 --json")
    with tempfile.TemporaryDirectory() as sandbox:
        rep = os.path.join(sandbox, "md_cg_servers")
        _seed(rep)
        # 999999 不是 Windows 合法 pid（pid 为 4 的倍数）且即便存在也会因命令行不匹配被拒。
        rc, out, err = _run(sandbox, ["kill", "--pid", "999999"], reachable_ps=False)
        check("G6 kill 探测不可用 → 报「探测不可用」（修前误报「进程不存在」）",
              "探测不可用" in out and "进程不存在" not in out, out[:300])
        check("G6 kill 探测不可用 → 退出码 ≠ 0", rc != 0, rc)

        rc, out, err = _run(sandbox, ["kill", "--pid", "999999"], reachable_ps=True)
        check("G7 kill 不存在 pid（探测可用）→ 「进程不存在」且退出码 1",
              "进程不存在" in out and rc == 1, "rc=%s | %s" % (rc, out[:200]))

        rc, out, err = _run(sandbox, ["list", "--json"], reachable_ps=True)
        try:
            val = json.loads(out)
            shape_ok = isinstance(val, list)
        except ValueError:
            shape_ok = False
        check("G8 list --json（探测可用）→ stdout 仍为 JSON 数组", shape_ok, out[:200])

        rc, out, err = _run(sandbox, ["list", "--json"], reachable_ps=False)
        check("G8 list --json（探测不可用）→ stdout `[]` + 退出码 2",
              rc == 2 and out.strip() == "[]", "rc=%s | %r" % (rc, out[:80]))

    print("[5] G9/G10 selfreport.purge 边界 与 自报契约")
    with tempfile.TemporaryDirectory() as sandbox:
        rep = os.path.join(sandbox, "md_cg_servers")
        before = _seed(rep)
        _saved_dir = sr.SELF_REPORT_DIR
        sr.SELF_REPORT_DIR = rep
        try:
            try:
                n = sr.purge([])
            except TypeError as exc:
                check("G9 purge([]) 默认不删（修前删光整个目录，N255）", False,
                      "无 allow_empty 契约：%s" % exc)
            else:
                check("G9 purge([]) 默认不删（修前删光整个目录，N255）",
                      n == 0 and sorted(os.listdir(rep)) == before,
                      (n, sorted(os.listdir(rep))))
            try:
                n = sr.purge([], allow_empty=True)
            except TypeError as exc:
                check("G9 purge([], allow_empty=True) 才按「在役已全退」清空", False,
                      "无 allow_empty 契约：%s" % exc)
            else:
                check("G9 purge([], allow_empty=True) 才按「在役已全退」清空",
                      n == 3 and sorted(os.listdir(rep)) == [], (n, sorted(os.listdir(rep))))

            got = sr.report(tag="n255-guard")
            check("G10 report() 仍写自报且键齐（本次改动未破in-service契约）",
                  got is not None and os.path.isfile(got.get("self_report_path", "")),
                  got)
            back = sr.read_all()
            check("G10 read_all() 可读回（pid 键 = 本进程）",
                  os.getpid() in back and back[os.getpid()].get("schema") == sr.SELF_REPORT_SCHEMA,
                  back.get(os.getpid()))
        finally:
            sr.SELF_REPORT_DIR = _saved_dir

    print("\n%d passed, %d failed, %d skipped" % (passed, failed, skipped))
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
