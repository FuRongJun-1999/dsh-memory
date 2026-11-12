# -*- coding: utf-8 -*-
"""test_probe_cd_shipped —— 两个**随包运维探针**的发货面守卫。

# 功能名：probe_c / probe_d 随包性 + 薄垫片等价性 + 设备无关性
# 生效条件：改动 `md_cg/probe_c_ledger_integrity.py`、`md_cg/probe_d_retirement_discipline.py`、
#   对应 `scripts/` 薄垫片，或改 `package.json` 的 `files` 白名单时。
# 子功能：① 本体在包内（files 覆盖 `md_cg/`，且两件文件真实存在）
#   ② 薄垫片只转发（不含第二份判据：不得出现 argparse / 判据常量 / main 实现）
#   ③ 两路径等价（`-m md_cg.X` 与 `scripts/X.py` 的 stdout 逐字节一致）
#   ④ 设备无关（本体不含本机路径字面量；`_package_root()` 两种布局都可解析）
#   ⑤ `--out` fail-closed 在包内路径上确实拒跑（不是只写在文档里）
# 执行：`python -X utf8 -m md_cg.test_probe_cd_shipped`
# 验证方式：本文件自身即验证面；每条判据都有一条**定点变异**（`--mutate`）证明它会红。
# 不适用条件：不测探针的**读数正确性**（那是 probe_c/probe_d 自己的口径，
#   由 docs/eval 里的实测报告与 `md_cg/test_state_ledger_*` 覆盖）；本件只管「随包与等价」。

背景（为什么需要这道守卫）：文档 `docs/mdcg/世界模型功能端_使用与运维_v1.0.md`
的 §七/§十 是**随包发给使用者**的运维页，里面照抄抄了 5 条
`python -X utf8 scripts/*.py` 命令。实测装机侧照抄执行：

    python: can't open file '...\\scripts\\probe_c_ledger_integrity.py': [Errno 2]

同类缺陷第三次出现（前两次见 issue #38 / #48 的「仓库里在、包里不在」）。
修法与 `state_extract` 同款：**本体移进 `md_cg/`（随包），`scripts/` 留薄垫片**；
并把文档命令改成 `-m md_cg.X` 形态（装机侧可用）。本守卫钉住这个形态不再退化。
"""
from __future__ import annotations

import io
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)

#: 两个探针的 (本体模块名, 源码树薄垫片相对路径, 供等价性比对用的一份最小输入构造器名)。
PROBES = (
    ("probe_c_ledger_integrity", os.path.join("scripts", "probe_c_ledger_integrity.py")),
    ("probe_d_retirement_discipline", os.path.join("scripts", "probe_d_retirement_discipline.py")),
)

#: 薄垫片里**不得出现**的东西——出现即说明「同一判据两个落点」（R9b 同族缺陷）。
SHIM_FORBIDDEN = (
    "argparse.ArgumentParser",   # 自己解析参数 = 有自己的入口面
    "def read_face_ids",         # probe_d 的判据函数被复制
    "def stg_face_ids",
    "def load_records",          # probe_c 的读台账实现被复制
    "BIG_LIMIT =",               # 判据常量被复制
    "SYNTH_SLOTS =",
)

_PASS, _FAIL, _MISS = [], [], []


class AnchorMiss(Exception):
    """变异锚点找不到（实现改了但守卫未同步）——fail-closed。"""


def ok(cond, msg, extra=""):
    (_PASS if cond else _FAIL).append(msg)
    print(("  PASS " if cond else "  FAIL ") + msg
          + (("  ← " + str(extra)) if (extra and not cond) else ""))
    return bool(cond)


def _read(p):
    with io.open(p, encoding="utf-8") as fh:
        return fh.read()


def _pkg_files(root):
    pj = json.loads(_read(os.path.join(root, "package.json")))
    return pj.get("files") or []


# ---- ① 本体随包 ----
def check_shipped(root):
    files = _pkg_files(root)
    covers = "md_cg" in files
    ok(covers, "① package.json 的 files 含 md_cg/（本体目录随包）",
       "files=%r" % (files,))
    for mod, _shim in PROBES:
        p = os.path.join(root, "md_cg", mod + ".py")
        ok(os.path.isfile(p), "① 本体存在：md_cg/%s.py" % mod)
        ok(covers and os.path.isfile(p),
           "① 本体**随包**：md_cg/%s.py 在 files 覆盖面内" % mod)


# ---- ② 薄垫片只转发 ----
def check_shims(root):
    for mod, shim_rel in PROBES:
        p = os.path.join(root, shim_rel)
        if not os.path.isfile(p):
            ok(False, "② 薄垫片存在：%s" % shim_rel)
            continue
        src = _read(p)
        ok(True, "② 薄垫片存在：%s" % shim_rel)
        hits = [t for t in SHIM_FORBIDDEN if t in src]
        ok(not hits, "② 薄垫片不含第二份判据：%s" % shim_rel, "命中 %r" % (hits,))
        ok(("from md_cg.%s import" % mod) in src,
           "② 薄垫片确实转发本体：%s" % shim_rel,
           "未见 `from md_cg.%s import`" % mod)
        # 行数上限：薄垫片就是二十来行的转发壳；超了说明有人往里塞了逻辑
        n = len([l for l in src.splitlines() if l.strip()])
        ok(n <= 60, "② 薄垫片仍是薄壳（有效行 ≤ 60）：%s" % shim_rel, "实得 %d 行" % n)# ---- ③ 两路径等价 ----
def _run(argv, timeout=300):
    p = subprocess.run(argv, capture_output=True, text=True, encoding="utf-8",
                       errors="replace", cwd=HERE, timeout=timeout)
    return p.returncode, (p.stdout or ""), (p.stderr or "")


def check_equivalence(root):
    """`-m md_cg.X` 与 `scripts/X.py` 的 stdout 必须逐字节一致。

    probe_d 自带隔离根（无入参即可跑，全确定性）；probe_c 需要 `--events`，
    故此处给它一份**合成台账**（两条事件、固定内容），输出同样确定性。
    """
    missing = [m for m, _ in PROBES
               if not os.path.isfile(os.path.join(root, "md_cg", m + ".py"))]
    if missing:
        # 本体被挪走时也不能抛——报红即可（与 check_device_neutral 同口径）。
        for m in missing:
            ok(False, "③ 本体存在（等价性检查的前置）：md_cg/%s.py" % m, "文件缺失")
        return
    tmp = tempfile.mkdtemp(prefix="probe_cd_eq_")
    try:
        ev = os.path.join(tmp, "_state_events.jsonl")
        rows = [
            {"t": 1, "subject": "我", "slot": "地点·所在", "old": None, "new": "杭州",
             "kind": "migration", "seq": 7, "evidence": "[auto] fixture", "actor": "state_extract"},
            {"t": 2, "subject": "我", "slot": "情感·偏好", "old": None, "new": "西湖",
             "kind": "acquisition", "seq": 7, "evidence": "[auto] fixture", "actor": "state_extract"},
        ]
        with io.open(ev, "w", encoding="utf-8", newline="\n") as fh:
            for r in rows:
                fh.write(json.dumps(r, ensure_ascii=False) + "\n")

        cases = (
            ("probe_c_ledger_integrity",
             ["--events", ev, "--expect-slots", "地点·所在,情感·偏好,住所"]),
            ("probe_d_retirement_discipline", []),
        )
        for mod, extra in cases:
            rc1, out1, err1 = _run([sys.executable, "-X", "utf8", "-m",
                                    "md_cg." + mod] + extra)
            rc2, out2, err2 = _run([sys.executable, "-X", "utf8",
                                    os.path.join(root, "scripts", mod + ".py")] + extra)
            ok(rc1 == 0, "③ `-m md_cg.%s` 跑通（rc=0）" % mod,
               "rc=%s stderr=%s" % (rc1, err1.strip()[:200]))
            ok(rc2 == 0, "③ 薄垫片跑通（rc=0）：scripts/%s.py" % mod,
               "rc=%s stderr=%s" % (rc2, err2.strip()[:200]))
            ok(out1 == out2, "③ 两路径 stdout 逐字节一致：%s" % mod,
               "长度 %d vs %d" % (len(out1), len(out2)))
            ok("PROBE_%s_JSON" % ("C_LEDGER" if mod.startswith("probe_c") else "D") in out1,
               "③ 末行机器可读摘要在场：%s" % mod)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


# ---- ④ 设备无关 ----
_LOCAL_PATH_PAT = re.compile(r"[A-Za-z]:[\\/](?:Users|Documents and Settings)[\\/]", re.I)


def check_device_neutral(root):
    for mod, _shim in PROBES:
        p = os.path.join(root, "md_cg", mod + ".py")
        # 本体不在时必须**判红**而不是抛异常——否则「本体被挪走」这处变异会让
        # 整组检查崩掉，红项反而看不到（本轮踩过：FileNotFoundError 直接把
        # 变异组打断，末行汇总只剩半截）。
        if not os.path.isfile(p):
            ok(False, "④ 本体存在（设备无关性检查的前置）：md_cg/%s.py" % mod,
               "文件缺失")
            continue
        src = _read(p)
        hits = _LOCAL_PATH_PAT.findall(src)
        ok(not hits, "④ 本体不含本机路径字面量：md_cg/%s.py" % mod, "命中 %r" % (hits[:3],))
        ok("_package_root" in src,
           "④ 本体用 `_package_root()` 定位包根（两种布局都对）：md_cg/%s.py" % mod)
    if not all(os.path.isfile(os.path.join(root, "md_cg", m + ".py")) for m, _ in PROBES):
        return
    # `_package_root()` 在源码树里必须解析到仓根（含 package.json 的那层）
    code = ("import json;"
            "from md_cg.probe_c_ledger_integrity import _package_root as f;"
            "print(json.dumps(f()))")
    p = subprocess.run([sys.executable, "-X", "utf8", "-c", code], cwd=HERE,
                       capture_output=True, text=True, encoding="utf-8",
                       errors="replace", timeout=120)
    raw = (p.stdout or "").strip()
    ok(p.returncode == 0 and raw, "④ `_package_root()` 可执行",
       "rc=%s stderr=%s" % (p.returncode, (p.stderr or "")[:200]))
    # json.dumps 会把 Windows 反斜杠转义成 `\\`——必须反解回真路径再比，
    # 直接比原串会永远不等（本轮踩过）。
    got = ""
    if raw:
        try:
            got = json.loads(raw)
        except ValueError:
            got = raw
    if got:
        ok(os.path.normcase(os.path.abspath(got)) == os.path.normcase(HERE),
           "④ `_package_root()` 在源码树解析到包根",
           "实得 %r 期望 %r" % (got, HERE))
        ok(os.path.isfile(os.path.join(got, "package.json")),
           "④ 解析结果确实是含 package.json 的那层")


# ---- ⑤ --out fail-closed ----
def check_out_closed(root):
    inside = os.path.join(root, "docs", "_probe_out_should_be_refused")
    missing = [m for m, _ in PROBES
               if not os.path.isfile(os.path.join(root, "md_cg", m + ".py"))]
    if missing:
        # 本体缺失时 `-m` 必然 rc≠0 但不是因为「拒跑」——那是**前置不成立**，
        # 不能混进「fail-closed 有效」的红项里（否则红项糊成一片，失去信号价值）。
        for m in missing:
            ok(False, "⑤ 本体存在（拒跑检查的前置）：md_cg/%s.py" % m, "文件缺失")
        return
    tmp = tempfile.mkdtemp(prefix="probe_cd_out_")
    try:
        # probe_c 的 `--events` 是**必填**参数——不喂它会在 argparse 处就 rc=2，
        # 那测到的是「参数缺失」而不是「--out 被拒」。故给它一份合成台账。
        ev = os.path.join(tmp, "_state_events.jsonl")
        with io.open(ev, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(json.dumps({"t": 1, "subject": "我", "slot": "地点·所在",
                                 "old": None, "new": "杭州", "kind": "migration",
                                 "seq": 7, "evidence": "[auto] fixture",
                                 "actor": "state_extract"},
                                ensure_ascii=False) + "\n")
        extra_c = ["--events", ev]
        for mod, _shim, extra in (("probe_c_ledger_integrity", None, extra_c),
                                  ("probe_d_retirement_discipline", None, [])):
            p = subprocess.run([sys.executable, "-X", "utf8", "-m", "md_cg." + mod,
                                "--out", inside] + extra,
                               capture_output=True, text=True, encoding="utf-8",
                               errors="replace", cwd=root, timeout=180)
            blob = (p.stdout or "") + (p.stderr or "")
            ok(p.returncode != 0 and "包外" in blob,
               "⑤ `--out` 指向包内即拒跑（fail-closed）：%s" % mod,
               "rc=%s blob=%s" % (p.returncode, blob.strip()[:200]))
            ok(not os.path.isdir(inside),
               "⑤ 拒跑时**不建目录**（零落盘）：%s" % mod)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


# ---- 定点变异 ----
def _mutations(root_src):
    """(名字, 施加函数) —— 每处都必须让**恰好**某些断言转红。"""
    def mut_body_to_scripts(root):
        """把本体从 md_cg/ 挪回 scripts/（= 修前的缺陷形态）。"""
        for mod, _shim in PROBES:
            p = os.path.join(root, "md_cg", mod + ".py")
            if not os.path.isfile(p):
                raise AnchorMiss("本体不在 md_cg/：%s" % p)
            os.remove(p)

    def mut_shim_gets_logic(root):
        """往薄垫片里塞一份判据（= 拆分叉）。"""
        mod, shim = PROBES[0]
        p = os.path.join(root, shim)
        src = _read(p)
        if "if __name__" not in src:
            raise AnchorMiss("薄垫片里找不到 __main__ 锚点")
        _write(p, src.replace("if __name__", "BIG_LIMIT = 10 ** 9\n\nif __name__", 1))

    def mut_files_drop_md_cg(root):
        """files 白名单删掉 md_cg（= 本体整目录不随包）。"""
        mod, _shim = PROBES[0]
        p = os.path.join(root, "package.json")
        pj = json.loads(_read(p))
        if "md_cg" not in (pj.get("files") or []):
            raise AnchorMiss("package.json 的 files 里没有 md_cg（变异无从施加）")
        pj["files"] = [f for f in pj["files"] if f != "md_cg"]
        _write(p, json.dumps(pj, ensure_ascii=False, indent=2) + "\n")

    return (
        ("把本体挪回 scripts/（修前形态）", mut_body_to_scripts),
        ("薄垫片塞一份判据（拆分叉）", mut_shim_gets_logic),
        ("files 删掉 md_cg", mut_files_drop_md_cg),
    )


def _write(p, text):
    with io.open(p, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(text)


def _run_checks(root):
    """在给定 root 上跑全部判据 → 返回红项列表（**不污染** [A] 组的累计计分）。

    注意：判据函数把结果追加进模块级 `_PASS/_FAIL`，故此处必须先**快照**再还原——
    否则每跑一次变异就把 [A] 组的读数清空，末行汇总只剩最后一次变异的数字
    （本轮踩过这个坑：终判看起来「通过了变异」，实则 [A] 的 32 项读数被抹掉了）。
    """
    saved_pass, saved_fail = list(_PASS), list(_FAIL)
    _PASS.clear(); _FAIL.clear()
    try:
        check_shipped(root)
        check_shims(root)
        check_equivalence(root)
        check_device_neutral(root)
        check_out_closed(root)
        return list(_FAIL)
    finally:
        _PASS[:] = saved_pass
        _FAIL[:] = saved_fail


def mutate_group():
    print("== [B] 定点变异自证（临时副本：每处必须让**预期断言**转红）==")
    for name, fn in _mutations(HERE):
        tmp = tempfile.mkdtemp(prefix="probe_cd_mut_")
        try:
            dst = os.path.join(tmp, "repo")
            shutil.copytree(os.path.join(HERE, "md_cg"),
                            os.path.join(dst, "md_cg"),
                            ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
            os.makedirs(os.path.join(dst, "scripts"), exist_ok=True)
            shutil.copy2(os.path.join(HERE, "package.json"),
                         os.path.join(dst, "package.json"))
            for _mod, shim in PROBES:
                shutil.copy2(os.path.join(HERE, shim), os.path.join(dst, shim))
            try:
                fn(dst)
            except AnchorMiss as exc:
                _MISS.append("%s：%s" % (name, exc))
                print("  ANCHOR-MISS %s ← %s" % (name, exc))
                continue
            fails = _run_checks(dst)
            ok(bool(fails), "变异「%s」确实让判据转红（%d 项）" % (name, len(fails)),
               "实得 0 项红 —— 变异无效或判据失效")
            print("     红项：%s" % ("；".join(fails[:4]) or "无"))
            # 每处变异还必须**只**打红它该打的那一族（不是「顺手全红」）：
            # 判据之间的耦合若失控，红项会糊成一片，那时「转红」就不再是有效信号。
            # 允许面：①②③ 的实质判据，以及 ④⑤ 的**前置**断言（「本体存在」）——
            # 本体被挪走时各组的「前置」必然红，这是语义必然，不是耦合失控。
            def _is_precondition(f):
                return ("本体存在（" in f)

            noisy = [f for f in fails
                     if not (("①" in f) or ("②" in f) or ("③" in f)
                             or _is_precondition(f))]
            ok(not noisy,
               "变异「%s」的红项落在随包/等价族（无 ⑤ 实质项与非前置 ④ 的噪声）" % name,
               "噪声项 %s" % noisy[:4])
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    print("== [A] 静态判据组（真实仓库根 %s）==" % HERE)
    _PASS.clear(); _FAIL.clear()
    check_shipped(HERE)
    check_shims(HERE)
    check_equivalence(HERE)
    check_device_neutral(HERE)
    check_out_closed(HERE)
    print("  微结：%d 通过，%d 失败" % (len(_PASS), len(_FAIL)))

    if "--mutate" in sys.argv[1:]:
        mutate_group()
    else:
        print("== [B] 定点变异自证：未启用（加 --mutate 跑）==")

    print("\n%d 通过，%d 失败，%d 锚点漂移" % (len(_PASS), len(_FAIL), len(_MISS)))
    if _MISS:
        print("ANCHOR-MISS：" + "；".join(_MISS))
        return 2
    if _FAIL:
        print("失败项：")
        for f in _FAIL:
            print("   - " + f)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
