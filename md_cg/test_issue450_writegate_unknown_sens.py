# -*- coding: utf-8 -*-
# 功能名：#450 写面层闸 _resolve_target 对「既有节点缺 sensitivity 键」改为 fail-closed
# 生效条件：python -X utf8 -m md_cg.test_issue450_writegate_unknown_sens [--mutate]
# 子功能：A 组=缺键 fail-closed（内部身份越权被拒）· K 组=非恒真对照（显式密级/新节点/高权身份均不误伤）· F 组=索引回填面（MdCGSecure._scan_nodes 把缺键擦成 internal 后闸仍能识别）· E 组=结构锚（单点内 fail-closed 判据在位）
# 执行：直接跑；--mutate 时把 fail-closed 判据逐条改回缺陷态，守卫必须按指定项转红
# 验证方式：断言全过 + 退出码 0；--mutate 下每条变异的指定命中须与预期一致（锚点缺失即 ANCHOR-MISS 并计不合格）
# 不适用条件：① 不覆盖读面 recent_events（属 #447）；② 不判「合法业务上应视 internal」的裁定——本守卫只钉「缺键不得被读成 internal」这一条；
#   ③ 不覆盖加密且无密钥导致盘面读不出的节点（此时无法确认缺键，保留索引值，见 _resolve_target 注释③）。
"""issue #450 守卫：写面层闸的「密级未知」必须 fail-closed。

病灶（修前实测，探针 .tmp/U16/probe_450.py）：
  `protect._resolve_target` 三来源（形参/索引条目/frontmatter）皆无密级时
  `return _layer, _sens or DEFAULT_SENSITIVITY` ⇒ 缺键节点被读成 `internal`
  ⇒ `clearance=internal` 的身份可经 `guard_overwrite` 覆写一个真实密级未知
  （可能是 restricted/private/secret）的既有节点（探针 A 行 `PASS`）。
  同身份对**显式 restricted** 节点被拒（探针 B 行 `DENY`）——「缺键」成了绕过
  层闸的降档通道。

修法（单点，不改保护语义）：`_resolve_target` 在既有节点上把「未知」按
`SENSITIVITY_ORDER` 最高档（`secret`）参与层闸；节点**不存在**（新写入面）
仍用 `DEFAULT_SENSITIVITY`。另加一条必须的补充判据：`MdCGSecure._scan_nodes`
用 `e["sensitivity"] = fm.get("sensitivity") or DEFAULT_SENSITIVITY` 回填索引，
会把「缺键」擦成 `internal` ⇒ 单看索引条目永远看不到缺键信号；故当生效值恰为
缺省档时回读一次 frontmatter 确认该键是否真的声明过（只读，不改盘）。
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO not in sys.path:
    sys.path.insert(0, _REPO)

FAILS = []
PASSED = []


def _check(name, cond, detail=""):
    if cond:
        PASSED.append(name)
        print("  PASS " + name)
    else:
        FAILS.append(name)
        print("  FAIL " + name + "  " + str(detail)[:200])


def _run(fn, *a, **kw):
    try:
        fn(*a, **kw)
        return "PASS"
    except Exception as exc:                     # noqa: BLE001
        return "DENY(%s)" % type(exc).__name__


def _env():
    tmp = tempfile.mkdtemp(prefix="iss450_")
    os.environ["MDCG_ROOT"] = os.path.join(tmp, "brain")
    os.environ["MDCG_STATE_ROOT"] = os.path.join(tmp, "state")
    os.environ["MDCG_AUX_ROOT"] = os.path.join(tmp, "auxroot")
    os.environ["MDCG_DATA_ROOT"] = os.path.join(tmp, "data")
    os.environ["MDCG_EXPORT_ROOT"] = os.path.join(tmp, "export")
    os.environ["MDCG_TOKEN_FILE"] = os.path.join(tmp, "auxroot", "tokens.json")
    os.environ["MDCG_MASTER_KEY"] = "cd" * 32
    for k in ("MDCG_TOKEN", "MDCG_VERIFY_KEY", "MDCG_TENANT", "MDCG_CLEARANCE",
              "MDCG_SESSION"):
        os.environ.pop(k, None)
    return tmp


def main():
    tmp = _env()
    from md_cg import protect
    from md_cg.mdcg import MdCG
    from md_cg.mdcos import MdCGSecure
    from md_cg.security import Principal

    try:
        root = os.environ["MDCG_ROOT"]
        # legacy 形态：基类 MdCG 直写（fm 无 sensitivity 键）
        base = MdCG(root)
        base.add("legacy_nokey", "升级前旧节点正文（无 sensitivity 键）",
                 layer="knowledge", importance=0.3)
        base.close()
        # 显式密级节点：只有 MdCGSecure 把 sensitivity 落 fm
        owner = Principal(tenant="default", actor="owner", clearance="secret",
                          can_write=True, can_admin=True, role="designer",
                          auth_mode="test")
        w = MdCGSecure(root, principal=owner)
        w.add("restricted_node", "显式受限正文", layer="knowledge",
              importance=0.3, sensitivity="restricted")
        w.add("internal_node", "显式内部正文", layer="knowledge",
              importance=0.3, sensitivity="internal")
        w.add("secret_node", "显式最高档正文", layer="knowledge",
              importance=0.3, sensitivity="secret")
        w.close()

        p = Principal(tenant="default", actor="internal-reader",
                      clearance="internal", can_write=True, can_admin=False,
                      role="record", auth_mode="test")
        cg = MdCGSecure(root, principal=p)

        print("== A 组：缺键 fail-closed（缺陷面） ==")
        # ★ 必须先「预热」到**真实运行态**：MdCGSecure 启动后索引条目的 sensitivity
        #   由 `_scan_nodes` 回填（缺键 → internal）。构造后第一次判定的重载尚未
        #   发生，条目还停在旧快照（无该键），此时缺键路径靠「条目无值」偶然成立
        #   ——M3 变异（只信条目）在这种状态下仍会绿，是假绿。故先显式走一次
        #   判定把重载/回填写完，并断言前置成立（不成立即守卫环境失效）。
        protect._resolve_target(cg, "legacy_nokey")
        _warm = (cg.index.get("nodes") or {}).get("legacy_nokey") or {}
        _check("A0 预热：索引条目已被回填为 'internal'（缺键被擦成缺省档，F 组的前提）",
               _warm.get("sensitivity") == "internal", _warm.get("sensitivity"))
        _check("A1 internal 身份 × legacy 无键节点 => 拒（修前 PASS）",
               _run(protect.guard_overwrite, cg, "legacy_nokey",
                    layer="knowledge") == "DENY(AccessDenied)",
               _run(protect.guard_overwrite, cg, "legacy_nokey",
                    layer="knowledge"))
        _check("A2 _resolve_target(legacy_nokey) 的密级 = 最高档 secret",
               protect._resolve_target(cg, "legacy_nokey")[1] == "secret",
               protect._resolve_target(cg, "legacy_nokey"))
        _check("A3 层位仍正确解析（knowledge，不被 fail-closed 波及）",
               protect._resolve_target(cg, "legacy_nokey")[0] == "knowledge",
               protect._resolve_target(cg, "legacy_nokey"))

        print("== K 组：非恒真对照（不得一刀切收紧） ==")
        _check("K1 显式 restricted => 仍拒（对照锚定）",
               _run(protect.guard_overwrite, cg, "restricted_node",
                    layer="knowledge") == "DENY(AccessDenied)",
               _run(protect.guard_overwrite, cg, "restricted_node",
                    layer="knowledge"))
        _check("K2 显式 internal => 放行（不把缺省档一并拦）",
               _run(protect.guard_overwrite, cg, "internal_node",
                    layer="knowledge") == "PASS",
               _run(protect.guard_overwrite, cg, "internal_node",
                    layer="knowledge"))
        _check("K3 节点不存在（新写入面）=> 放行（保护的是既有节点）",
               _run(protect.guard_overwrite, cg, "brand_new",
                    layer="knowledge") == "PASS",
               _run(protect.guard_overwrite, cg, "brand_new",
                    layer="knowledge"))
        hi = Principal(tenant="default", actor="secret-reader",
                       clearance="secret", can_write=True, can_admin=False,
                       role="designer", auth_mode="test")
        cg_hi = MdCGSecure(root, principal=hi)
        _check("K4 secret 身份 × 无键节点 => 放行（最高档身份不被误拦）",
               _run(protect.guard_overwrite, cg_hi, "legacy_nokey",
                    layer="knowledge") == "PASS",
               _run(protect.guard_overwrite, cg_hi, "legacy_nokey",
                    layer="knowledge"))
        cg_hi.close()

        print("== F 组：索引回填面（MdCGSecure._scan_nodes 把缺键擦成 internal） ==")
        # 同上：K4 用了第二个实例（cg_hi），可能推进索引代际 ⇒ 本实例下次判定会
        # 重载一次；先 warm 回「条目已回填」的真实运行态，F2 才是对回填面的判定。
        protect._resolve_target(cg, "legacy_nokey")
        e = (cg.index.get("nodes") or {}).get("legacy_nokey") or {}
        fm = (cg.get("legacy_nokey") or {}).get("frontmatter") or {}
        _check("F1 前置成立：索引条目 sensitivity == 'internal' 而 fm 无该键",
               e.get("sensitivity") == "internal" and not fm.get("sensitivity"),
               (e.get("sensitivity"), fm.get("sensitivity")))
        _check("F2 索引回填后闸仍判 fail-closed（不是只看条目值）",
               _run(protect.guard_overwrite, cg, "legacy_nokey",
                    layer="knowledge") == "DENY(AccessDenied)",
               _run(protect.guard_overwrite, cg, "legacy_nokey",
                    layer="knowledge"))

        print("== E 组：结构锚（单点内判据在位） ==")
        src = open(os.path.join(_REPO, "md_cg", "protect.py"),
                   encoding="utf-8").read()
        i = src.find("def _resolve_target(")
        j = src.find("\ndef ", i + 10)
        body = src[i:j if j > 0 else len(src)]
        _check("E1 单点内以 SENSITIVITY_ORDER 最高档作 fail-closed 值",
               "SENSITIVITY_ORDER[-1]" in body)
        _check("E2 单点内在缺省档时回读 frontmatter 确认缺键（F 组的行为前提）",
               'if not _fm.get("sensitivity"):' in body)
        _check("E3 既有节点判据与「新写入面」判据分叉（e or _node is not None）",
               "if e or _node is not None:" in body)
        cg.close()
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    print("=" * 60)
    print("#450 守卫：%d 通过，%d 失败" % (len(PASSED), len(FAILS)))
    for f in FAILS:
        print("  红项：" + f)
    return 1 if FAILS else 0


# ---------------------------------------------------------------- 变异自证
# (描述, 目标文件, 原文锚, 变异后, 必须转红的项前缀)
_MUTATIONS = (
    ("M1 缺键回落缺省档（回到缺陷：fail-open）",
     "md_cg/protect.py",
     "        if e or _node is not None:",
     "        if False:",
     ("A1", "A2", "F2")),
    ("M2 未知密级也拦新写入面（过度收紧）",
     "md_cg/protect.py",
     "        return _layer or \"knowledge\", DEFAULT_SENSITIVITY",
     "        return _layer or \"knowledge\", SENSITIVITY_ORDER[-1]",
     ("K3",)),
    ("M3 只信索引条目、不回读 frontmatter（索引回填把缺键擦掉）",
     "md_cg/protect.py",
     "    if _sens == DEFAULT_SENSITIVITY:",
     "    if False:",
     ("A1", "A2", "F2")),
)


def _mirror_build():
    dst = tempfile.mkdtemp(prefix="iss450_mut_")
    for name in ("md_cg",):
        src = os.path.join(_REPO, name)
        if os.path.isdir(src):
            shutil.copytree(src, os.path.join(dst, name),
                            ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    return dst


def _run_in(tree):
    env = dict(os.environ)
    env["PYTHONPATH"] = tree
    env["PYTHONUTF8"] = "1"
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    pr = subprocess.run([sys.executable, "-X", "utf8", "-m",
                         "md_cg.test_issue450_writegate_unknown_sens"],
                        capture_output=True, text=True, encoding="utf-8",
                        errors="replace", cwd=tree, env=env, timeout=1800)
    out = (pr.stdout or "") + (pr.stderr or "")
    reds = [ln.split("FAIL ", 1)[1].strip()
            for ln in out.splitlines() if "FAIL " in ln]
    return pr.returncode, reds, out


def _mutate():
    print("!! 定点变异自证：逐条把判据改回缺陷/过度收紧形态，守卫必须转红")
    tree = _mirror_build()
    try:
        rc, reds, out = _run_in(tree)
        print("  未变异镜像基线：rc=%d 红项=%d（必须 rc=0 且 0 红）"
              % (rc, len(reds)))
        if rc != 0 or reds:
            print("\n".join(out.splitlines()[-25:]))
        ok, bad = 0, []
        for desc, rel, old, new, exp in _MUTATIONS:
            p = os.path.join(tree, rel)
            t = open(p, encoding="utf-8", newline="").read()
            if t.count(old) != 1:
                bad.append("%s —— 锚点在 %s 里命中 %d 次"
                           % (desc, rel, t.count(old)))
                print("  ANCHOR-MISS " + desc)
                continue
            bak = t
            open(p, "w", encoding="utf-8", newline="").write(
                t.replace(old, new, 1))
            for root, _dd, _ff in os.walk(tree):
                if os.path.basename(root) == "__pycache__":
                    shutil.rmtree(root, ignore_errors=True)
            rc2, reds2, out2 = _run_in(tree)
            open(p, "w", encoding="utf-8", newline="").write(bak)
            hit = [r for r in reds2 if r.startswith(exp)]
            if rc2 != 0 and len(hit) == len(exp):
                ok += 1
                print("  OK   %s  红项=%d 指定命中=%d/%d"
                      % (desc, len(reds2), len(hit), len(exp)))
            else:
                bad.append(desc)
                print("  MISMATCH %s  红项=%d 指定命中=%d/%d rc=%d"
                      % (desc, len(reds2), len(hit), len(exp), rc2))
                for r in reds2[:8]:
                    print("        FAIL " + r)
        print("定点变异自证：%s（%d 条不合格）"
              % ("PASS" if not bad else "FAIL", len(bad)))
        for b in bad:
            print("  不合格：" + b)
        return 0 if not bad else 1
    finally:
        shutil.rmtree(tree, ignore_errors=True)


if __name__ == "__main__":
    if "--mutate" in sys.argv:
        sys.exit(_mutate())
    sys.exit(main())
