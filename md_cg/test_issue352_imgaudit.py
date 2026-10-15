# -*- coding: utf-8 -*-
# 功能名：imgskill 审计台账落点不得跟随符号链接写到沙箱根外（issue #352-C）
# 生效条件：python -X utf8 -m md_cg.test_issue352_imgaudit [--mutate]；被测面=md_cg/imgskill.py 的 audit_path/_audit_write/read_audit/_audit_seq
# 子功能：A 组=根内 .imgskill 指向根外时 run() 照常返回、台账不落根外、结果体带 audit_warning、audit_path(strict) 抛 E_PATH_OUT_OF_SCOPE、读面不跟随；K 组=非恒真对照（正常台账照写照读、幂等复用面不受影响、目录尚未创建时不误拒）；E 组=源码面单点
# 执行：在临时沙箱根内把 .imgskill 造成指向根外的**目录链接**（POSIX=symlink，Windows=junction——junction 不需特权而 open() 同样跟随，本机实测），随后调 md_cg.imgskill.run()/_find_reuse()
# 验证方式：全部 PASS 即通过；--mutate 走镜像树定点变异，变异后红项必须**恰为**预期集合
# 不适用条件：①不判台账完整性（HMAC/签名）②不判台账落点搬迁（移到 aux_root 属设计决定）③不判台账被「换内容」的投毒面（#325 读方向已覆盖）④不覆盖「末段是符号链接」的实机腿——本机无 SeCreateSymbolicLinkPrivilege（已实测），该腿在有权限的宿主上自动启用，无权限时按源码面单点（E1）钉住
"""issue #352-C 守卫：台账落点不得跟随链接写到沙箱根外。

病象（修前）：`audit_path` 只有一句 `os.path.join(root, AUDIT_REL)`，而
`_audit_write` 用 `open(p, "a")` **跟随符号链接**。沙箱根内可写者只做一步
（把 `.imgskill` 目录或 `.imgskill/audit.jsonl` 换成链接），受害者下一次**合法**
调用就会把一行审计 JSON 追加到根外任意可写文件——目标是 `json.dump` 写的整文件
JSON 时该文件从此解析失败（报告实测：指向 `MDCG_TOKEN_FILE` 后 MCP 服务重启
rc=3 退出）。`read_audit` / `_audit_seq` 同样跟随链接**读**根外文件。

处置（真源复用）：落点判定一律走同文件既有的 `safe_join`（realpath +
commonpath，与 src/dst 同一份实现），上段/末段各补一次 `os.path.islink` 显式判；
写面用 `os.open(..., O_NOFOLLOW)`（平台无该标志时取 0）。

★**fail-open 还是 fail-closed**：报告把这一条列为维护者裁定。本实现取
**fail-open + 可观测告警**——台账落点不可信时 `run()` 照常返回结果，只是不写
台账并在结果体带 `audit_warning`（读面按空表计）。理由：imgskill 不经 MCP 暴露，
把本地可信边界问题升级成「一个可写者建个链接就让所有合法调用失败」的拒服务面
得不偿失；且报告给的边界本就是「可人工删掉追加行恢复」。**不静默**是硬要求——
M3 变异（摘掉告警回填）必须打红 C1。

★**过度收紧方向**：K1（正常台账照写照读）、K2（幂等复用面不受影响）、
K3（`.imgskill` 目录尚未创建时不得误拒）三条盯住「修复没把正常面一起关掉」。
"""
import hashlib
import inspect
import json
import os
import shutil
import struct
import subprocess
import sys
import tempfile
import zlib

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _REPO)
from md_cg import imgskill as _I                              # noqa: E402

FAILS = []
_SKIPPED = []


def _check(name, cond, detail=""):
    if cond:
        print("  PASS " + name)
    else:
        print("  FAIL " + name + "  " + str(detail)[:400])
        FAILS.append(name)


_TMP = tempfile.mkdtemp(prefix="iss352c_")


def _png(path, w=8, h=8):
    ch = lambda t, d: (struct.pack(">I", len(d)) + t + d
                       + struct.pack(">I", zlib.crc32(t + d) & 0xffffffff))
    raw = b"".join(b"\x00" + b"\xff\x00\x00" * w for _ in range(h))
    with open(path, "wb") as f:
        f.write(b"\x89PNG\r\n\x1a\n"
                + ch(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
                + ch(b"IDAT", zlib.compress(raw)) + ch(b"IEND", b""))


def _sandbox(tag):
    base = os.path.join(_TMP, tag)
    root = os.path.join(base, "sandbox")
    out = os.path.join(base, "outside")
    os.makedirs(root)
    os.makedirs(out)
    _png(os.path.join(root, "a.png"))
    return base, root, out


def _dir_link(link, target):
    """把 link 造成指向 target 的**目录链接**。

    POSIX 用 `os.symlink`；Windows 用 `mklink /J`（junction）——junction
    **不需要 SeCreateSymbolicLinkPrivilege**（本机 `os.symlink` 实测
    WinError 1314 拒绝，junction 成功），而 `open()` 与 `realpath` 对它的行为
    与符号链接一致（本机实测：跟随写入成立、realpath 解析到链接目标）。
    故这条腿在两个平台上都是**真实**复现，不是桩。
    """
    if os.name == "nt":
        # 文本模式子进程必须显式声明编码（scripts 的编码守卫要求；不依赖 locale）。
        pr = subprocess.run(["cmd", "/c", "mklink", "/J", link, target],
                            capture_output=True, text=True,
                            encoding="utf-8", errors="replace")
        return pr.returncode == 0
    try:
        os.symlink(target, link, target_is_directory=True)
        return True
    except OSError:
        return False


def _file_link(link, target):
    try:
        os.symlink(target, link)
        return True
    except OSError:
        return False


def _run(root, **extra):
    req = {"op": "inspect", "src": "a.png", "sandbox_root": root,
           "caller": "victim"}
    req.update(extra)
    try:
        return _I.run(req)
    except Exception as exc:                                  # noqa: BLE001
        return {"_raised": "%s: %s" % (type(exc).__name__, exc)}


def _sha(path):
    with open(path, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


# 能力探测：末段文件符号链接是否可建（本机无 SeCreateSymbolicLinkPrivilege）
_T = tempfile.mkdtemp(prefix="iss352c_cap_")
open(os.path.join(_T, "tgt"), "w", encoding="utf-8").close()
_FILE_LINK_OK = _file_link(os.path.join(_T, "lnk"), os.path.join(_T, "tgt"))
print("   [能力] 文件符号链接可建=%s（Windows 无特权时 False；目录链接走 junction，恒可用）"
      % _FILE_LINK_OK)

print("== A 组：台账落点跟随链接 ==")

# --- C1：.imgskill 目录指向根外 ---
_b, _root, _out = _sandbox("c1")
_link_ok = _dir_link(os.path.join(_root, ".imgskill"), _out)
_res = _run(_root)
_out_ledger = os.path.join(_out, "audit.jsonl")
print("   [读数] C1 目录链接=%s run=%s 根外台账=%s 告警=%s"
      % (_link_ok, {k: _res.get(k) for k in ("ok", "error")},
         os.path.exists(_out_ledger),
         bool(_res.get("audit_warning"))))
_check("C1 .imgskill 指向根外：run() 照常返回结果（不拒服务）、台账不落根外、"
       "结果体带 audit_warning（不静默）",
       _link_ok and "_raised" not in _res
       and not os.path.exists(_out_ledger)
       and bool(_res.get("audit_warning"))
       and bool(_res.get("audit_id")), (_res, os.path.exists(_out_ledger)))

# --- C4：audit_path(strict) 对不可信落点抛 E_PATH_OUT_OF_SCOPE ---
_c4 = None
try:
    _I.audit_path(_root)
    _c4 = "未抛"
except _I.SkillError as _e:
    _c4 = _e.code
_check("C4 audit_path(root) 对链接落点抛 E_PATH_OUT_OF_SCOPE（fail-closed 调用方可用）",
       _c4 == _I.E_PATH_OUT_OF_SCOPE and _I.audit_path(_root, strict=False) is None,
       _c4)

# --- C3：读面不跟随链接去读根外台账（含投毒条目）---
_poison = {"idempotency_key": "k352", "ok": True, "op": "inspect",
           "input_sha256": _sha(os.path.join(_root, "a.png")), "params": {},
           "output_path": "a.png",
           "output_sha256": _sha(os.path.join(_root, "a.png")),
           "audit_id": "audit_poison"}
with open(_out_ledger, "w", encoding="utf-8") as f:
    f.write(json.dumps(_poison, ensure_ascii=False) + "\n")
_rows = _I.read_audit(_root)
_hit = _I._find_reuse(_root, "k352", "inspect",
                      _poison["input_sha256"], {})
print("   [读数] C3 读面条目=%d _find_reuse=%s（均须为空）"
      % (len(_rows), _hit))
_check("C3 读面不跟随链接：read_audit 按空表计、_find_reuse 不复用根外台账条目",
       _rows == [] and _hit is None, (_rows, _hit))

# --- C2：末段（audit.jsonl 本身）是符号链接 ---
if _FILE_LINK_OK:
    _b2, _root2, _out2 = _sandbox("c2")
    _victim = os.path.join(_out2, "tokens.json")
    with open(_victim, "w", encoding="utf-8") as f:
        json.dump({"tokens": {"abc": {"role": "designer"}}}, f)
    os.makedirs(os.path.join(_root2, ".imgskill"))
    _lk = _file_link(os.path.join(_root2, ".imgskill", "audit.jsonl"), _victim)
    _res2 = _run(_root2)
    _raw = open(_victim, encoding="utf-8").read()
    try:
        json.loads(_raw)
        _parses = True
    except ValueError:
        _parses = False
    print("   [读数] C2 末段链接=%s 根外 JSON 仍可解析=%s 含 audit_id=%s 告警=%s"
          % (_lk, _parses, "audit_id" in _raw, bool(_res2.get("audit_warning"))))
    _check("C2 末段是符号链接：根外整文件 JSON 不被追加破坏",
           _lk and _parses and "audit_id" not in _raw
           and bool(_res2.get("audit_warning")), _raw[:120])
else:
    _SKIPPED.append("C2")
    print("  [跳过] C2 末段符号链接腿：本机无 SeCreateSymbolicLinkPrivilege"
          "（os.symlink 实测 WinError 1314）——该腿在有权限的宿主上自动启用，"
          "此处由源码面单点 E1 兜底")

# ========================================================= K 组：非恒真对照
print("== K 组：非恒真对照（含**过度收紧**方向）==")

# --- K1：正常沙箱：台账照写照读、结果体无告警 ---
_kb, _kroot, _kout = _sandbox("k1")
_kres = _run(_kroot)
_kp = _I.audit_path(_kroot)
_krows = _I.read_audit(_kroot)
print("   [读数] K1 run=%s 台账路径在根内=%s 条目=%d 告警=%s"
      % ({k: _kres.get(k) for k in ("ok", "error")},
         bool(_kp) and not os.path.relpath(_kp, _kroot).startswith(".."),
         len(_krows), _kres.get("audit_warning")))
_check("K1 正常沙箱（无链接）：台账照常写入可读回、结果体**无** audit_warning",
       "_raised" not in _kres and os.path.isfile(_kp) and len(_krows) >= 1
       and _kres.get("audit_warning") is None
       and bool(_kres.get("audit_id")), (_kres, _kp))

# --- K2：正常沙箱：幂等复用面不受影响（#325 的 safe_join 未回退）---
_krec = {"idempotency_key": "kk352", "ok": True, "op": "inspect",
         "input_sha256": _sha(os.path.join(_kroot, "a.png")), "params": {},
         "output_path": "a.png",
         "output_sha256": _sha(os.path.join(_kroot, "a.png")),
         "audit_id": "audit_k2"}
with open(_kp, "a", encoding="utf-8") as f:
    f.write(json.dumps(_krec, ensure_ascii=False) + "\n")
_khit = _I._find_reuse(_kroot, "kk352", "inspect", _krec["input_sha256"], {})
_check("K2 正常台账仍可复用（幂等面不因本次收口而失效）",
       isinstance(_khit, dict) and _khit.get("audit_id") == "audit_k2", _khit)

# --- K3：.imgskill 目录**尚不存在**时不得误拒（过度收紧方向）---
_kb3, _kroot3, _ = _sandbox("k3")
_p3 = _I.audit_path(_kroot3)
_res3 = _run(_kroot3)
_p3b = _I.audit_path(_kroot3)
print("   [读数] K3 目录未建时 audit_path=%s 事后条目=%d"
      % (bool(_p3), len(_I.read_audit(_kroot3))))
_check("K3 .imgskill 目录尚未创建时不误拒：audit_path 仍返根内路径、run() 能建目录写入",
       _p3 is not None and os.path.isfile(_p3b)
       and len(_I.read_audit(_kroot3)) >= 1
       and not str(_res3.get("audit_warning") or ""), (_p3, _p3b))

# ========================================================= E 组：源码面单点
print("== E 组：源码面单点 ==")
_src_ap = inspect.getsource(_I.audit_path)
_src_aw = inspect.getsource(_I._audit_write)
_src_ra = inspect.getsource(_I.read_audit)
_src_as = inspect.getsource(_I._audit_seq)
_src_fr = inspect.getsource(_I._find_reuse)
_check("E1 落点判定走 safe_join 真源 + 上段/末段 islink 显式判",
       'safe_join(root, AUDIT_REL, what="audit_path")' in _src_ap
       and "os.path.islink(d)" in _src_ap and "os.path.islink(p)" in _src_ap)
_check("E2 写面用 os.open + O_NOFOLLOW（不再裸 open(p, 'a')）",
       "os.open(p, flags, 0o600)" in _src_aw and "O_NOFOLLOW" in _src_aw)
_check("E3 读面（read_audit/_audit_seq）走同一判定、不可信即按空表",
       "audit_path(root, strict=False)" in _src_ra
       and "audit_path(root, strict=False)" in _src_as)
_check("E4 #325 的 safe_join 收口未回退（_find_reuse 仍过 safe_join）",
       'safe_join(root, rec["output_path"]' in _src_fr)

shutil.rmtree(_TMP, ignore_errors=True)

print("")
if FAILS:
    print("issue #352-C 结果：%d 失败 → %s" % (len(FAILS), ", ".join(FAILS)))
else:
    print("issue #352-C 结果：全部通过（跳过腿：%s）"
          % (",".join(_SKIPPED) or "无"))

# ------------------------------------------------------------- 定点变异（镜像树）
_EXP_M1 = ("C1", "C3", "C4", "E1") + (("C2",) if _FILE_LINK_OK else ())
_MUTATIONS = (
    ("M1 摘掉落点判定（回到 os.path.join + open 跟随链接的修前形态）",
     (("md_cg/imgskill.py",
       ['    if os.path.islink(d):',
        '        why = "%s 是符号链接（台账落点不得经链接指向沙箱根外）" % os.path.dirname(rel)',
        '    elif os.path.islink(p):',
        '        why = "%s 是符号链接（台账落点不得经链接指向沙箱根外）" % rel',
        '    else:',
        '        try:',
        '            cand = safe_join(root, AUDIT_REL, what="audit_path")',
        '        except SkillError as exc:',
        '            why = exc.message'],
       ['    if False:',
        '        why = None',
        '    else:',
        '        cand = os.path.join(root, AUDIT_REL)']),),
     _EXP_M1),
    ("M2 写面摘掉 O_NOFOLLOW（回到跟随链接的 open 口径）",
     (("md_cg/imgskill.py",
       ['        flags = (os.O_WRONLY | os.O_APPEND | os.O_CREAT',
        '                 | getattr(os, "O_NOFOLLOW", 0))',
        '        fd = os.open(p, flags, 0o600)'],
       ['        fd = os.open(p, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)']),),
     ("E2",)),
    ("M3 摘掉结果体的告警回填（落点不可信重新变成**静默**不写）",
     (("md_cg/imgskill.py",
       ['        if _aw is not None:',
        '            # #352-C：台账落点不可信 ⇒ 本次不写台账，但**不静默**（结果体带告警）',
        '            res["audit_warning"] = _aw'],
       ['        pass']),),
     ("C1",)),
    ("M4 读面回退成直接拼接（跟随链接读根外台账）",
     (("md_cg/imgskill.py",
       ['    p = audit_path(root, strict=False)',
        '    if p is None or not os.path.exists(p):',
        '        return []'],
       ['    p = os.path.join(root, AUDIT_REL)',
        '    if not os.path.exists(p):',
        '        return []']),),
     ("C3", "E3")),
)


def _mirror_build():
    dst = tempfile.mkdtemp(prefix="iss352c_mut_")
    for name in ("md_cg", "scripts"):
        src = os.path.join(_REPO, name)
        if os.path.isdir(src):
            shutil.copytree(src, os.path.join(dst, name),
                            ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    for name in sorted(os.listdir(_REPO)):
        p = os.path.join(_REPO, name)
        if os.path.isfile(p) and name.endswith(".py"):
            shutil.copy2(p, os.path.join(dst, name))
    return dst


def _nl_of(path):
    with open(path, "rb") as fh:
        raw = fh.read(8192)
    return "\r\n" if b"\r\n" in raw else "\n"


def _run_in(tree):
    env = dict(os.environ)
    env["PYTHONPATH"] = tree
    env["PYTHONUTF8"] = "1"
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    pr = subprocess.run([sys.executable, "-X", "utf8", "-m",
                         "md_cg.test_issue352_imgaudit"],
                        capture_output=True, text=True, encoding="utf-8",
                        errors="replace", cwd=tree, env=env, timeout=1800)
    out = (pr.stdout or "") + (pr.stderr or "")
    reds = [ln.split("FAIL ", 1)[1].strip()
            for ln in out.splitlines() if "FAIL " in ln]
    return pr.returncode, reds, out


def _mutate():
    print("!! 定点变异自证：把修复点改回改动前形态，守卫必须转红")
    tree = _mirror_build()
    try:
        rc, reds, out = _run_in(tree)
        print("  未变异镜像基线：rc=%d 红项=%d（必须 rc=0 且 0 红）" % (rc, len(reds)))
        if rc != 0 or reds:
            print(chr(10).join(out.splitlines()[-30:]))
        for ln in out.splitlines():
            if "[读数]" in ln or "[跳过]" in ln:
                print("  修后读数（未变异镜像）：" + ln.strip())
        okc, bad = 0, []
        for desc, edits, exp in _MUTATIONS:
            backups, miss = [], []
            for rel, oldp, newp in edits:
                p = os.path.join(tree, rel)
                nl = _nl_of(p)
                old, new = nl.join(oldp), nl.join(newp)
                with open(p, encoding="utf-8", newline="") as fh:
                    t = fh.read()
                if t.count(old) != 1:
                    miss.append("%s —— 锚点命中 %d 次" % (rel, t.count(old)))
                    continue
                backups.append((p, t))
                with open(p, "w", encoding="utf-8", newline="") as fh:
                    fh.write(t.replace(old, new, 1))
            if miss:
                bad.append("%s —— %s" % (desc, "；".join(miss)))
                print("  ANCHOR-MISS " + desc)
                for p, t in backups:
                    with open(p, "w", encoding="utf-8", newline="") as fh:
                        fh.write(t)
                continue
            rc2, reds2, out2 = _run_in(tree)
            for p, t in backups:
                with open(p, "w", encoding="utf-8", newline="") as fh:
                    fh.write(t)
            hit = sorted({e for r in reds2 for e in exp if r.startswith(e + " ")})
            if rc2 != 0 and hit == sorted(exp) and len(reds2) == len(exp):
                okc += 1
                print("  OK   %s  红项=%d 指定命中=%d/%d"
                      % (desc, len(reds2), len(hit), len(exp)))
            else:
                bad.append(desc)
                print("  MISMATCH %s  红项=%d 指定命中=%d/%d rc=%d"
                      % (desc, len(reds2), len(hit), len(exp), rc2))
                for r in reds2[:14]:
                    print("        FAIL " + r)
        print("定点变异自证：%s（%d 条不合格）"
              % ("PASS" if not bad else "FAIL", len(bad)))
        for b in bad:
            print("  不合格：" + b)
    finally:
        shutil.rmtree(tree, ignore_errors=True)


def main():
    if "--mutate" in sys.argv:
        _mutate()
        return 1 if FAILS else 0
    return 0 if not FAILS else 1


if __name__ == "__main__":
    sys.exit(main())
