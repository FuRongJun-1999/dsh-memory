# -*- coding: utf-8 -*-
# 功能名：凭据载体权限收敛「声明与实现一致 + 失败不静默」（⑤）与 unwrap_dek 的 clearance 已文档化事实（⑥）（issue #326）
# 生效条件：python -X utf8 -m md_cg.test_issue326_key_perms [--mutate]；被测面＝md_cg/crypto.py 的 _tighten_perms / load_master_key / _save_keys（⑤）与 unwrap_dek、provision_dek、envelopes（⑥）
# 子功能：A 组＝⑤ 两处凭据载体都收敛、失败进有界告警且不上抛、成功不告警、密钥行为不变；K 组＝非恒真对照（过度收紧方向：chmod 失败不得阻断密钥生成；正常路径不得恒告警；_save_keys 对账/锁定语义与 provision→unwrap 往返不受扰）；E 组＝源码面（静默形态退役）＋ **⑥ 的三条已文档化事实钉**
# 执行：--mutate 时在镜像树里逐条改回「静默 chmod」（回缺陷）、「失败即上抛」（过度收紧）、「只修 master.key 不修 _keys.json」（半修），守卫必须按指定项转红
# 验证方式：全部 PASS 即通过（退出码 0）；--mutate 下每条变异的红项集合须与预期**逐项相符**
# 不适用条件：**不判「是否真的实现了 0600 语义」**——Windows 上 os.chmod 只切只读位是既有事实，本批确立的是「声明与实现一致 + 失败不静默」而非「已隔离」（icacls 方案经编排侧裁定不上）；不判 ⑥ 的行为改动（判为有意设计，**只记录不改**）；不判 _keys.json 的加密/信封语义
"""issue #326-⑤⑥ 守卫。

⑤ 病象（修前）：`load_master_key` 里 `try: os.chmod(path, 0o600) except OSError: pass` ——
**静默**；且 `_save_keys` 写 `_keys.json` 后**完全无权限收敛**（同为凭据载体，两种待遇）。
平台事实：Windows 上 `os.chmod` 只切只读位、不产生 POSIX 隔离（真实保护来自用户目录 ACL），
故本条**不宣称**「已隔离」，只消除**声明与实现不符 + 静默**。

⑥ 事实：`unwrap_dek(root, kek, tenant, actor, clearance=None)` 的 `clearance` **从不参与判定**
（函数体不引用）；`provision_dek` 的**位置透传**仅为与签发端签名对称；信封里的 `clearance`
供 `envelopes()` 审计。该事实**本仓审计已留痕**（`unwrap_dek` 的「生效条件」注释明写），
编排侧裁定为**有意设计 ⇒ 只记录、不改**（删形参是跨 2 模块的破坏性 API 改动）。
本守卫的 E 组把这三条钉住：**防后来者误以为它是活鉴权位而去「修」它**。

「守卫必须能在变异态下跑完」：取数经包装折成可命名形态，不崩栈。
"""
from __future__ import annotations

import ast
import os
import shutil
import subprocess
import sys
import tempfile

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO not in sys.path:
    sys.path.insert(0, _REPO)

FAILS = []


def _check(name, cond, detail=""):
    if cond:
        print("  PASS " + name)
    else:
        print("  FAIL " + name + "  " + str(detail)[:220])
        FAILS.append(name)


_TMP = tempfile.mkdtemp(prefix="iss326e_")
os.environ.update({"MDCG_ROOT": _TMP + "/brain", "MDCG_STATE_ROOT": _TMP + "/state",
                   "MDCG_AUX_ROOT": _TMP + "/auxstore",
                   "MDCG_DATA_ROOT": _TMP + "/datastore",
                   "MDCG_EXPORT_ROOT": _TMP, "MDCG_SUSTAIN": "0", "MDCG_SLEEP": "0"})

from md_cg import crypto as _c        # noqa: E402

_REAL_OS = _c.os


class _OsShim:
    """os 模块代理：只覆盖指定函数，其余转发（不改进程全局 os）。"""

    def __init__(self, **over):
        self._over = over

    def __getattr__(self, name):
        if name in self._over:
            return self._over[name]
        return getattr(os, name)


def _err(fn):
    """调 fn：正常返回 ("", 结果)；抛异常（含 BaseException）返回 (类型名, 异常对象)。"""
    try:
        return "", fn()
    except BaseException as exc:                 # noqa: BLE001 —— 变异态不得崩栈
        return type(exc).__name__, exc


def _fresh_root(tag):
    d = os.path.join(_TMP, tag)
    os.makedirs(d, exist_ok=True)
    return d


print("== A 组：⑤ 两处凭据载体都收敛、失败不静默、也不上抛 ==")
_calls = []
_c.PERM_WARNINGS.clear()
_r1 = _fresh_root("root1")
_mk = os.path.join(_r1, "master.key")
_real_chmod = os.chmod
_c.os = _OsShim(chmod=lambda p, m: _calls.append((p, m)))
_t1, _k1 = _err(lambda: _c.load_master_key(master_file=_mk))
_c.os = _REAL_OS
_check("A01 master.key 生成后**调用**权限收敛（path 命中、mode=0o600）",
       _t1 == "" and any(os.path.abspath(p) == os.path.abspath(_mk) and m == 0o600
                        for p, m in _calls), (_t1, _calls))
_check("A02 收敛成功时**不**告警（不得恒告警）", _c.PERM_WARNINGS == [],
       _c.PERM_WARNINGS)
_calls2 = []
_c.PERM_WARNINGS.clear()
_mk2 = os.path.join(_fresh_root("root2"), "master.key")
_c.os = _OsShim(chmod=lambda p, m: _calls2.append((p, m)))
_t2, _k2 = _err(lambda: _c.load_master_key(master_file=_mk2))
_c.os = _REAL_OS
_check("A03 第二次生成也是同一路径收敛（幂等，不受首次告警影响）",
       _t2 == "" and len(_calls2) == 1 and len(_k2) == 32, (_t2, _calls2))
# 失败路径：chmod 抛 OSError ⇒ 不上抛 + **不静默**（进有界告警）
_c.PERM_WARNINGS.clear()
_mk3 = os.path.join(_fresh_root("root3"), "master.key")
_c.os = _OsShim(chmod=lambda p, m: (_ for _ in ()).throw(OSError("not permitted")))
_t3, _k3 = _err(lambda: _c.load_master_key(master_file=_mk3))
_c.os = _REAL_OS
_check("A04 chmod 失败**不上抛**（受限平台/只读介质不得阻断启动）且密钥照常产出",
       _t3 == "" and len(_k3) == 32, (_t3, _k3))
_check("A05 chmod 失败**不静默**：告警含 (path, 异常类型, 文本) 且 path 命中",
       len(_c.PERM_WARNINGS) == 1
       and os.path.abspath(_c.PERM_WARNINGS[0][0]) == os.path.abspath(_mk3)
       and _c.PERM_WARNINGS[0][1] == "OSError", _c.PERM_WARNINGS)
_check("A06 密钥文件确实落盘且内容非空（失败的是权限收敛，不是写入）",
       os.path.exists(_mk3) and os.path.getsize(_mk3) > 0, "")
# _keys.json：同为凭据载体，同款收敛
_calls4 = []
_c.PERM_WARNINGS.clear()
_r4 = _fresh_root("root4")
_c.os = _OsShim(chmod=lambda p, m: _calls4.append((p, m)))
_t4, _ = _err(lambda: _c._save_keys(_r4, {"v": 1, "alg": "x", "envelopes": {}}))
_c.os = _REAL_OS
_kp = _c.keys_path(_r4)
_check("A07 _keys.json 写入后**也**收敛（修前完全无收敛；与 master.key 同待遇）",
       _t4 == "" and any(os.path.abspath(p) == os.path.abspath(_kp) and m == 0o600
                        for p, m in _calls4), (_t4, _calls4, _kp))
_check("A08 _keys.json 落盘内容正确（收敛不改写入语义）",
       _t4 == "" and os.path.exists(_kp) and _c._load_keys(_r4).get("v") == 1,
       (_t4, _kp))

print("== K 组：非恒真对照（过度收紧方向——失败不得阻断、正常路径不得恒告警） ==")
_c.PERM_WARNINGS.clear()
_mk5 = os.path.join(_fresh_root("root5"), "master.key")
_c.os = _OsShim(chmod=lambda p, m: (_ for _ in ()).throw(OSError(13, "denied")))
_t5, _k5 = _err(lambda: _c.load_master_key(master_file=_mk5))
_c.os = _REAL_OS
_check("K01 chmod 失败**不得阻断**密钥生成（返回 key、文件已落盘）",
       _t5 == "" and len(_k5) == 32 and os.path.exists(_mk5), (_t5, _k5))
_check("K02 失败告警**有界**（重复失败不无限增长）",
       len(_c.PERM_WARNINGS) <= _c._PERM_WARN_LIMIT, len(_c.PERM_WARNINGS))
_c.PERM_WARNINGS.clear()
_mk6 = os.path.join(_fresh_root("root6"), "master.key")
_t6, _k6 = _err(lambda: _c.load_master_key(master_file=_mk6))
_check("K03 正常路径不告警（真实 chmod 成功时告警列表保持空）",
       _t6 == "" and _c.PERM_WARNINGS == [], (_t6, _c.PERM_WARNINGS))
_r7 = _fresh_root("root7")
with open(_c.keys_path(_r7), "w", encoding="utf-8") as f:
    f.write("{broken-json")
_t7, _e7 = _err(lambda: _c._save_keys(_r7, {"envelopes": {}}))
_check("K04 _save_keys 的对账契约不受扰（盘面不可解析 ⇒ LockedError，拒绝整份覆盖）",
       _t7 == "LockedError", (_t7, str(_e7)[:80]))
_r8 = _fresh_root("root8")
_kek = b"k" * 32
_t8, _dek8 = _err(lambda: _c.provision_dek(_r8, _kek, "t1", "alice"))
_t9, _back8 = _err(lambda: _c.unwrap_dek(_r8, _kek, "t1", "alice"))
_check("K05 provision→unwrap 往返仍解出同一 DEK（⑤ 的收敛不触碰密钥语义）",
       _t8 == "" and _t9 == "" and _back8 == _dek8, (_t8, _t9))

print("== E 组：源码面（⑤ 静默形态退役）＋ ⑥ 三条已文档化事实钉 ==")


def _csrc():
    with open(os.path.join(_REPO, "md_cg/crypto.py"), encoding="utf-8") as f:
        return f.read()


_CS = _csrc()
_tree = ast.parse(_CS)
_chmod_calls = [n for n in ast.walk(_tree) if isinstance(n, ast.Call)
                and isinstance(n.func, ast.Attribute) and n.func.attr == "chmod"]
_check("E01 ⑤ 静默形态已退役：全模块只有 **1 处** chmod 调用（在 _tighten_perms 内）",
       len(_chmod_calls) == 1 and "def _tighten_perms(path):" in _CS,
       len(_chmod_calls))
_check("E02 ⑤ 失败不静默：OSError 分支写入 PERM_WARNINGS（有界）且 return False（不上抛）",
       "PERM_WARNINGS.append(" in _CS and "_PERM_WARN_LIMIT" in _CS, "")
_tighten_calls = sorted(ast.unparse(n) for n in ast.walk(_tree)
                        if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
                        and n.func.id == "_tighten_perms")
_check("E03 ⑤ 两处凭据载体同待遇：收敛调用点恰为 {master.key, _keys.json}",
       _tighten_calls == ["_tighten_perms(keys_path(root))", "_tighten_perms(path)"],
       _tighten_calls)
_check("E04 ⑤ Windows 平台事实被**如实文档化**（含 Windows + 只读位/ACL 字样）",
       "Windows" in _CS and ("只读位" in _CS or "ACL" in _CS), "")
_uw = [n for n in ast.walk(_tree)
       if isinstance(n, ast.FunctionDef) and n.name == "unwrap_dek"]
_uw_names = set()
if _uw:
    for _n in ast.walk(_uw[0]):
        if isinstance(_n, ast.Name):
            _uw_names.add(_n.id)
        elif isinstance(_n, ast.Attribute):
            _uw_names.add(_n.attr)
_uw_args = [a.arg for a in _uw[0].args.args] if _uw else []
_check("E05 ⑥ 钉①：unwrap_dek 的 clearance **不参与条件判定**（形参在、函数体不引用）",
       bool(_uw) and "clearance" in _uw_args
       and "clearance" not in _uw_names, (_uw_args, sorted(_uw_names)))
_check("E06 ⑥ 钉②：provision_dek 对 unwrap_dek 的 clearance 仅为**位置透传**（签名对称）",
       "return unwrap_dek(root, kek, tenant, actor, clearance)" in _CS, "")
_check("E07 ⑥ 钉③：信封存 clearance 供 envelopes() 审计（读方不是判定方）",
       "def envelopes(" in _CS and _CS.count("clearance") >= 4, _CS.count("clearance"))
_check("E08 ⑥ 已文档化：unwrap_dek 的生效条件注释明写「clearance 形参默认 None 但源码未在条件中使用」",
       "clearance 形参默认 None 但源码未在条件中使用" in _CS, "")

shutil.rmtree(_TMP, ignore_errors=True)
print("")
if FAILS:
    print("issue #326-⑤⑥ 结果：%d 失败" % len(FAILS))
else:
    print("issue #326-⑤⑥ 结果：全部通过")

# ---------------------------------------------------------------- 定点变异表
# 锚点跨行用 chr(10) 拼接；_apply_text 按目标文件**实际行尾**折算（crypto.py 为 CRLF）。
_TIGHTEN_CALL = "    _tighten_perms(path)"
_SILENT = chr(10).join([
    "    try:",
    "        os.chmod(path, 0o600)",
    "    except OSError:",
    "        pass",
])
_RAISE = chr(10).join([
    "    except OSError as e:",
    "        if len(PERM_WARNINGS) < _PERM_WARN_LIMIT:",
    "            PERM_WARNINGS.append((path, type(e).__name__, str(e)[:120]))",
    "        raise",
])
_WARN_BLOCK = chr(10).join([
    "    except OSError as e:",
    "        if len(PERM_WARNINGS) < _PERM_WARN_LIMIT:",
    "            PERM_WARNINGS.append((path, type(e).__name__, str(e)[:120]))",
    "        return False",
])
_KEYS_CALL = "    _tighten_perms(keys_path(root))"
_KEYS_OFF = "    # 变异：删掉 _keys.json 的收敛（半修）"

_MUTATIONS = (
    # M1 回缺陷（静默）：失败不告警 ⇒ A05 转红；裸 chmod 回到调用点 ⇒ E01（chmod 调用数）与
    # E03（收敛调用点集合）同步转红。A04/K01（不上抛）两态皆不抛 ⇒ 恒绿（如实）。
    ("M1 回缺陷：chmod 回到静默 try/except pass", "md_cg/crypto.py",
     ((_TIGHTEN_CALL, _SILENT),),
     ("A05", "E01", "E03")),
    # M2 过度收紧（失败即上抛）⇒ 受限平台上密钥生成被阻断：K01/A04 转红；
    # 告警仍在（A05/A06 绿）——告警与阻断是两件事，本腿只钉后者。
    ("M2 过度收紧：收敛失败即上抛（阻断密钥生成）", "md_cg/crypto.py",
     ((_WARN_BLOCK, _RAISE),),
     ("A04", "K01")),
    # M3 半修（只修 master.key，_keys.json 仍无收敛）⇒ A07 与 E03 转红（两种待遇不一致）。
    ("M3 半修：_keys.json 不收敛（凭据载体两样待遇）", "md_cg/crypto.py",
     ((_KEYS_CALL, _KEYS_OFF),),
     ("A07", "E03")),
)


def _mirror_build():
    dst = tempfile.mkdtemp(prefix="iss326e_mut_")
    for name in ("md_cg", "scripts", "compiler"):
        src = os.path.join(_REPO, name)
        if os.path.isdir(src):
            shutil.copytree(src, os.path.join(dst, name),
                            ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    for name in sorted(os.listdir(_REPO)):
        p = os.path.join(_REPO, name)
        if os.path.isfile(p) and (name.endswith(".py")
                                  or name in ("README.md", "pyproject.toml",
                                              "package.json")):
            shutil.copy2(p, os.path.join(dst, name))
    return dst


def _apply_text(text, rel, pairs):
    """按目标文件实际行尾折算锚点后逐条替换；任一锚点命中数 != 1 返回 (None, 原因)。"""
    eol = (chr(13) + chr(10)) if (chr(13) + chr(10)) in text else chr(10)
    for old, new in pairs:
        o = old.replace(chr(10), eol)
        n = new.replace(chr(10), eol)
        if text.count(o) != 1:
            return None, "锚点在 %s 里命中 %d 次" % (rel, text.count(o))
        text = text.replace(o, n, 1)
    return text, ""


def _run_in(tree):
    env = dict(os.environ)
    env["PYTHONPATH"] = tree
    env["PYTHONUTF8"] = "1"
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    for k in ("MDCG_ROOT", "MDCG_STATE_ROOT", "MDCG_AUX_ROOT",
              "MDCG_DATA_ROOT", "MDCG_EXPORT_ROOT"):
        env.pop(k, None)
    pr = subprocess.run([sys.executable, "-X", "utf8", "-m",
                         "md_cg.test_issue326_key_perms"],
                        capture_output=True, text=True, encoding="utf-8",
                        errors="replace", cwd=tree, env=env, timeout=1800)
    out = (pr.stdout or "") + (pr.stderr or "")
    reds = [ln.split("FAIL ", 1)[1].strip()
            for ln in out.splitlines() if ln.strip().startswith("FAIL ")]
    return pr.returncode, reds, out


def _mutate():
    print("!! 定点变异自证：逐条把权限收敛改回静默/过度收紧/半修形态，守卫必须按指定项转红")
    tree = _mirror_build()
    bad = []
    try:
        rc, reds, out = _run_in(tree)
        print("  未变异镜像基线：rc=%d 红项=%d（必须 rc=0 且 0 红）" % (rc, len(reds)))
        if rc != 0 or reds:
            bad.append("未变异镜像基线即红")
            print(chr(10).join(out.splitlines()[-25:]))
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
            for root, dd, ff in os.walk(tree):
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
                for r in reds2[:12]:
                    print("        FAIL " + r)
        print("定点变异自证：%s（%d 条不合格）" % ("PASS" if not bad else "FAIL", len(bad)))
        for b in bad:
            print("  不合格：" + b)
        return len(bad)
    finally:
        shutil.rmtree(tree, ignore_errors=True)


def main():
    _bad = _mutate() if "--mutate" in sys.argv else 0
    return 1 if (FAILS or _bad) else 0


if __name__ == "__main__":
    sys.exit(main())
