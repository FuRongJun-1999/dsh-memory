# -*- coding: utf-8 -*-
# 功能名：paths.json 编码失真（GBK/ANSI）不得被当成记忆根（#426-F）
# 生效条件：python -u -X utf8 -m md_cg.test_issue426f_paths_gbk_failclosed [--mutate]；
#   被测面＝md_cg/datapath.py 的 _abs_host_path（所有根解析的归一单点：
#   state_root / data_root / mdcg_root / aux_root 四条解析链的公共闸）
# 子功能：A GBK paths.json 在 Python 侧响亮失败（#352-D 既有，本腿锚定不回归）·
#   B 插件宽松解码出的 U+FFFD 根经 MDCG_ROOT 注入 ⇒ 不得被接受（本件主面）·
#   C/D 反向：UTF-8 paths.json 的中文根、合法中文 env 根照常解析（防一刀切）·
#   E 同判据覆盖其余根（state_root 同单点）· F mcp_server 启动探针对该根 fail-closed
# 执行：默认跑全部腿并做源码锚点自检（锚点缺失 ⇒ exit 2，fail-closed）；
#   --mutate 时在镜像树里撤掉 U+FFFD 判据，守卫必须按指定项转红
# 验证方式：全部 PASS 且 --mutate 红项集合与预期逐项相符 ⇒ 退出码 0
# 不适用条件：① **插件侧** `src/lib/datapath.ts` 的 `readFileSync(pf,'utf8')` 宽松解码
#   本单元无权改（不在授权文件清单），已按 NEED_FILE 上报；本件修的是**接收侧**：
#   即便插件把 U+FFFD 串注入 `MDCG_ROOT`，Python 侧也不再照单全收、不再据此新建乱码库。
#   ② 不判「用户故意用 U+FFFD 命名目录」这种形态（该字符不是任何正常配置的产物，
#   fail-closed 优于把新写入分叉进另一个库）；③ 不做 GBK→UTF-8 的自动转码
#   （自动猜测编码=另一种静默；#352-D 已定口径：响亮失败 + 给恢复路径）。
"""issue #426-F 守卫：编码失真路径必须响亮失败。

病象（修前实测，见 `.tmp/U04/probe_426f.py`）：
  · 插件 `readFileSync(pf, 'utf8')` 对 GBK/ANSI 保存的 paths.json **不抛**，把非法
    字节替换成 U+FFFD，`JSON.parse` 仍成功 ⇒ 插件把乱码串当记忆根注入 `MDCG_ROOT`；
  · Python 侧对**同一文件**是严格解码（`PathsConfigError`），但对**注入的乱码
    env 根**原样接受 ⇒ 两侧口径分叉：原库从插件面消失、新写入分叉进乱码空库。

修法（条件层，落在归一单点）：`_abs_host_path` 增加「含 U+FFFD ⇒ ValueError」
判据——任何平台的根解析（env / paths.json / 默认根）都经它，故只需一处。
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO not in sys.path:
    sys.path.insert(0, _REPO)

_TMP = tempfile.mkdtemp(prefix="iss426f_")
_KEYS = ("MDCG_ROOT", "MDCG_DATA_ROOT", "MDCG_STATE_ROOT", "MDCG_AUX_ROOT",
         "MDCG_EXPORT_ROOT", "MDCG_INGEST_ROOT", "DSH_HOME")
for _k in _KEYS + ("MDCG_TOKEN", "MDCG_VERIFY_KEY"):
    os.environ.pop(_k, None)
os.environ.update({"MDCG_STATE_ROOT": _TMP + "/state", "HOME": _TMP,
                   "USERPROFILE": _TMP, "PYTHONUTF8": "1"})
os.makedirs(_TMP + "/state", exist_ok=True)
os.makedirs(_TMP + "/灵枢记忆", exist_ok=True)

from md_cg import datapath as dp                          # noqa: E402

PASSED, FAILS = [], []
GARBAGE = _TMP + "/" + "\ufffd" * 7


def _check(name, cond, detail=""):
    if cond:
        print("  PASS " + name)
        PASSED.append(name)
    else:
        print("  FAIL " + name + "  " + str(detail)[:300])
        FAILS.append(name)


def _raises(fn):
    try:
        return fn(), False
    except Exception as exc:                    # noqa: BLE001 —— 只取类型名做判据
        return type(exc).__name__ + ": " + str(exc)[:160], True


def _pf():
    return os.path.join(_TMP + "/state", "paths.json")


def group_a():
    print("\n[A] GBK paths.json：Python 侧响亮失败（#352-D 既有，锚定不回归）")
    with open(_pf(), "wb") as f:
        f.write(json.dumps({"root": _TMP + "/灵枢记忆"},
                           ensure_ascii=False).encode("gbk"))
    got, raised = _raises(dp.mdcg_root)
    _check("A1 GBK 保存的 paths.json ⇒ mdcg_root() 抛 PathsConfigError",
           raised and got.startswith("PathsConfigError"), got)
    os.remove(_pf())


def group_b():
    print("\n[B] 插件宽松解码出的 U+FFFD 根不得被接受（本件主面）")
    os.environ["MDCG_ROOT"] = GARBAGE
    got, raised = _raises(dp.mdcg_root)
    _check("B1 MDCG_ROOT 含 U+FFFD ⇒ 抛 ValueError（不再返回乱码根）",
           raised and got.startswith("ValueError"), got)
    _check("B2 错误消息点明编码失真与恢复路径",
           raised and ("U+FFFD" in got or "编码失真" in got), got)
    del os.environ["MDCG_ROOT"]

    os.environ["MDCG_DATA_ROOT"] = GARBAGE
    got2, raised2 = _raises(dp.data_root)
    _check("B3 同判据覆盖 data_root（单一归一闸，不是逐函数补 if）",
           raised2, got2)
    del os.environ["MDCG_DATA_ROOT"]


def group_c():
    print("\n[C] 反向：UTF-8 paths.json 的中文根照常解析")
    with open(_pf(), "w", encoding="utf-8") as f:
        json.dump({"root": _TMP + "/灵枢记忆"}, f, ensure_ascii=False)
    got = dp.mdcg_root()
    _check("C1 UTF-8 paths.json + 中文根 ⇒ 解析正确（防一刀切）",
           got == os.path.abspath(_TMP + "/灵枢记忆"), got)
    os.remove(_pf())


def group_d():
    print("\n[D] 反向：合法中文 env 根照常解析")
    os.environ["MDCG_ROOT"] = _TMP + "/灵枢记忆"
    got = dp.mdcg_root()
    _check("D1 合法中文 MDCG_ROOT ⇒ 解析正确", got == os.path.abspath(
        _TMP + "/灵枢记忆"), got)
    del os.environ["MDCG_ROOT"]


def group_e():
    print("\n[E] 同判据覆盖其余根（state_root 同单点）")
    os.environ["MDCG_STATE_ROOT"] = GARBAGE
    got, raised = _raises(dp.state_root)
    _check("E1 MDCG_STATE_ROOT 含 U+FFFD ⇒ 抛 ValueError", raised, got)
    os.environ["MDCG_STATE_ROOT"] = _TMP + "/state"
    os.environ["MDCG_AUX_ROOT"] = GARBAGE
    got2, raised2 = _raises(dp.aux_root)
    _check("E2 MDCG_AUX_ROOT 含 U+FFFD ⇒ 抛 ValueError", raised2, got2)
    del os.environ["MDCG_AUX_ROOT"]


def group_f():
    print("\n[F] mcp_server 启动探针：乱码根 ⇒ fail-closed（不再带病起服务）")
    env = {k: v for k, v in os.environ.items()
           if not k.startswith("MDCG_") and k != "DSH_HOME"}
    env.update({"MDCG_ROOT": GARBAGE, "MDCG_STATE_ROOT": _TMP + "/state",
                "MDCG_AUX_ROOT": _TMP + "/auxstore", "PYTHONUTF8": "1",
                "PYTHONPATH": _REPO})
    pr = subprocess.run([sys.executable, "-u", "-X", "utf8", "-m",
                         "md_cg.mcp_server"], input="", capture_output=True,
                        text=True, encoding="utf-8", errors="replace",
                        env=env, cwd=_REPO, timeout=180)
    err = pr.stderr or ""
    _check("F1 server rc=2（拒绝启动）", pr.returncode == 2,
           "rc=%d err=%s" % (pr.returncode, err[-300:]))
    _check("F2 stderr 点明 U+FFFD/编码失真",
           ("U+FFFD" in err) or ("编码失真" in err), err[-300:])


def _anchor_check():
    src = open(os.path.join(_REPO, "md_cg", "datapath.py"),
               encoding="utf-8").read()
    missing = [a for a in ("_REPLACEMENT_CHAR", "U+FFFD") if a not in src]
    if missing:
        print("ANCHOR-MISS md_cg/datapath.py: %s" % missing)
        return 2
    return 0


# ================================================= M 组：反向腿②（定点变异）
_MUTATIONS = (
    ("M1 撤 U+FFFD 判据（回到 #426-F 原形态：乱码根照单全收）",
     "md_cg/datapath.py",
     (("    if _REPLACEMENT_CHAR in r:" + chr(10)
       + "        who = env_key or \"该路径\"" + chr(10)
       + "        raise ValueError(" + chr(10)
       + "            f\"{who} 归一后含 U+FFFD 替换符（{r!r}）——这是**编码失真**的痕迹，\""
       + chr(10)
       + "            \"不是合法目录名：paths.json 若以 GBK/ANSI 保存（PowerShell 5 的 \""
       + chr(10)
       + "            \"Set-Content 不带 -Encoding、cmd 的 echo >、旧编辑器另存为 ANSI），\""
       + chr(10)
       + "            \"宽松 UTF-8 解码会把非法字节替换成该字符，于是「记忆真源」变成一个\""
       + chr(10)
       + "            \"乱码目录，新写入分叉进空库、原库从插件面消失（#426-F）。请把该文件\""
       + chr(10)
       + "            \"改存为 UTF-8（含 BOM 亦可），或删掉它回到用户级默认数据根；\""
       + chr(10)
       + "            \"本侧与 Python 侧同一口径：**要么取到真路径，要么响亮失败**。\")",
       "    pass  # M1 撤 U+FFFD 判据"),),
     ("B1", "B2", "B3", "E1", "E2", "F1", "F2")),
)


def _mirror_build():
    dst = tempfile.mkdtemp(prefix="iss426f_mut_")
    for name in ("md_cg", "lib"):
        src = os.path.join(_REPO, name)
        if os.path.isdir(src):
            shutil.copytree(src, os.path.join(dst, name),
                            ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    for name in sorted(os.listdir(_REPO)):
        p = os.path.join(_REPO, name)
        if os.path.isfile(p) and name.endswith(".py"):
            shutil.copy2(p, os.path.join(dst, name))
    return dst


def _run_in(tree):
    env = dict(os.environ)
    env["PYTHONPATH"] = tree
    env["PYTHONUTF8"] = "1"
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    for k in _KEYS + ("MDCG_TOKEN", "MDCG_TOKEN_FILE", "MDCG_VERIFY_KEY"):
        env.pop(k, None)
    pr = subprocess.run([sys.executable, "-u", "-X", "utf8", "-m",
                         "md_cg.test_issue426f_paths_gbk_failclosed"],
                        capture_output=True, text=True, encoding="utf-8",
                        errors="replace", cwd=tree, env=env, timeout=1800)
    out = (pr.stdout or "") + (pr.stderr or "")
    reds = [ln.split("FAIL ", 1)[1].strip()
            for ln in out.splitlines() if ln.strip().startswith("FAIL ")]
    return pr.returncode, reds, out


def _apply_text(text, rel, pairs):
    eol = (chr(13) + chr(10)) if (chr(13) + chr(10)) in text else chr(10)
    for old, new in pairs:
        o = old.replace(chr(10), eol)
        n = new.replace(chr(10), eol)
        if text.count(o) != 1:
            return None, "锚点在 %s 里命中 %d 次" % (rel, text.count(o))
        text = text.replace(o, n, 1)
    return text, ""


def _mutate():
    print("!! 反向腿②：撤 U+FFFD 判据，守卫必须按指定项转红")
    tree = _mirror_build()
    bad = []
    try:
        rc, reds, out = _run_in(tree)
        print("  未变异镜像基线：rc=%d 红项=%d（必须 rc=0 且 0 红）"
              % (rc, len(reds)))
        if rc != 0 or reds:
            bad.append("未变异镜像基线即红")
            print(chr(10).join(out.splitlines()[-20:]))
        for desc, rel, pairs, exp in _MUTATIONS:
            p = os.path.join(tree, rel)
            with open(p, encoding="utf-8", newline="") as f:
                bak = f.read()
            mut, why = _apply_text(bak, rel, pairs)
            if mut is None:
                bad.append("%s —— %s" % (desc, why))
                print("  ANCHOR-MISS " + desc + "  " + why)
                continue
            with open(p, "w", encoding="utf-8", newline="") as f:
                f.write(mut)
            for root, _dd, _ff in os.walk(tree):
                if os.path.basename(root) == "__pycache__":
                    shutil.rmtree(root, ignore_errors=True)
            rc2, reds2, out2 = _run_in(tree)
            with open(p, "w", encoding="utf-8", newline="") as f:
                f.write(bak)
            hit = sorted({r.split(" ")[0] for r in reds2})
            if rc2 != 0 and hit == sorted(exp):
                print("  OK   %s  红项=%d 指定命中=%s" % (desc, len(reds2), hit))
            else:
                bad.append(desc)
                print("  MISMATCH %s  实际红项=%s  期望=%s  rc=%d"
                      % (desc, hit, sorted(exp), rc2))
                for r in reds2[:10]:
                    print("        FAIL " + r)
        print("反向腿②：%s（%d 条不合格）"
              % ("PASS" if not bad else "FAIL", len(bad)))
        return len(bad)
    finally:
        shutil.rmtree(tree, ignore_errors=True)


def main():
    print("== #426-F paths.json 编码失真守卫 ==")
    try:
        _rc = _anchor_check()
        if _rc:
            return _rc
        group_a()
        group_b()
        group_c()
        group_d()
        group_e()
        group_f()
    finally:
        shutil.rmtree(_TMP, ignore_errors=True)
    print("=" * 68)
    print("#426-F 守卫：%d 通过，%d 失败" % (len(PASSED), len(FAILS)))
    for f in FAILS:
        print("  红项：" + f)
    _bad = _mutate() if "--mutate" in sys.argv else 0
    return 1 if (FAILS or _bad) else 0


if __name__ == "__main__":
    sys.exit(main())
