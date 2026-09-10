# -*- coding: utf-8 -*-
"""版本层端到端测试（P22 · 蜂群互联层0）。

验证目标：
  ① 声明与校验：未声明 / 合法声明 / 封缄被篡改 / schema 不符 / 版本不在认可集合
  ② fail-closed：theory_ok=False → 写操作与管理操作**全拒**（只读降级）
  ③ 唯一核心权限：theory op 仅 designer 可达，其余角色 op 作用域外
  ④ 审计链：版本跃迁写入 audit
  ⑤ CLI：`python -m md_cg.theory check` 可用

运行：python -m md_cg.test_p22_theory
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import time

from . import theory, tokens
from .security import AccessDenied, Principal

PASS = FAIL = 0
FAILS = []


def check(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  [PASS] {name}" + (f"  · {detail}" if detail else ""))
    else:
        FAIL += 1
        FAILS.append(name)
        print(f"  [FAIL] {name}  · {detail}")


def denied(fn, *a, **kw):
    """执行 fn，返回 (是否被拒, 错误文本)。"""
    try:
        fn(*a, **kw)
        return False, ""
    except (AccessDenied, tokens.TokenError) as e:
        return True, str(e)


def main():
    tmp = tempfile.mkdtemp(prefix="mdcg_theory_")
    tf = os.path.join(tmp, "theory.json")
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    try:
        # ---------- ① 未声明（放行，不阻断既有部署） ----------
        st = theory.check(tf)
        check("未声明 → 按默认版本放行",
              st["theory_ok"] is True and st.get("auto") is True, st["reason"])
        check("未声明 reason 可归因", "未声明" in st["reason"], st["reason"])

        # ---------- ①b ensure：无声明则落盘（声明常态化） ----------
        st = theory.ensure(tf)
        check("ensure → 落盘声明", os.path.exists(tf))
        check("ensure → theory_ok=True", st["theory_ok"] is True, st["reason"])
        v_before = st["version"]
        theory.ensure(tf)
        check("ensure 幂等（不覆盖已有声明）",
              theory.check(tf)["version"] == v_before)

        # ---------- ② 合法声明 ----------
        r = theory.declare("3.4", accepted=["3.4", "3.3"], actor="designer",
                           path=tf)
        check("declare → ok", r["ok"] is True)
        check("declare → theory_ok=True", r["status"]["theory_ok"] is True,
              r["status"]["reason"])
        check("声明含自身版本", "3.4" in r["status"]["accepted_versions"],
              str(r["status"]["accepted_versions"]))
        check("声明文件已落盘", os.path.exists(tf))
        check("声明含封缄字段",
              bool((theory.load(tf) or {}).get("declaration_hash")))

        # ---------- ③ 封缄被篡改 ----------
        raw = theory.load(tf)
        raw["theory_version"] = "9.9"          # 改内容不改封缄
        with open(tf, "w", encoding="utf-8") as f:
            json.dump(raw, f, ensure_ascii=False)
        st = theory.check(tf)
        check("篡改版本号 → 校验失败", st["theory_ok"] is False, st["reason"])
        check("篡改 reason 指向封缄", "篡改" in st["reason"], st["reason"])

        # ---------- ④ 重新声明即恢复（版本更新权的修复入口） ----------
        theory.declare("3.4", accepted=["3.4"], path=tf)
        check("重新声明 → 恢复", theory.check(tf)["theory_ok"] is True)

        # ---------- ⑤ 版本不在认可集合（封缄合法） ----------
        bad = theory.seal({"schema": theory.SCHEMA, "theory_version": "9.9",
                           "accepted_versions": ["3.4"], "declared_by": "x",
                           "declared_at": time.time()})
        st = theory.check(tf, decl=bad)
        check("版本不在认可集合 → 失败", st["theory_ok"] is False, st["reason"])
        check("集合 reason 可归因", "不在认可集合" in st["reason"], st["reason"])

        # ---------- ⑥ schema 不符 ----------
        bad2 = dict(bad)
        bad2["schema"] = 99
        st = theory.check(tf, decl=theory.seal(bad2))
        check("schema 不符 → 失败", st["theory_ok"] is False, st["reason"])
        check("schema reason 可归因", "schema" in st["reason"], st["reason"])

        # ---------- ⑦ 审计链 ----------
        theory.declare("3.5", accepted=["3.5"], path=tf)
        theory.declare("3.6", accepted=["3.6"], path=tf)
        decl = theory.load(tf)
        audit = decl.get("audit") or []
        check("audit 记录版本跃迁", len(audit) >= 2, str(audit))
        check("audit 末条指向当前版本",
              bool(audit) and audit[-1].get("to") == "3.6", str(audit[-1:]))

        # ---------- ⑧ fail-closed：写 / 管理全拒 ----------
        blocked = Principal(actor="designer", role="designer", can_write=True,
                            can_admin=True, ops_allow=("*",), theory_ok=False)
        w_dn, w_msg = denied(blocked.require_write, "internal")
        check("theory_ok=False → 写被拒", w_dn, w_msg)
        check("写拒绝原因指向版本层", "版本层" in w_msg, w_msg)
        a_dn, a_msg = denied(blocked.require_admin, "scrub")
        check("theory_ok=False → 管理被拒", a_dn, a_msg)
        check("管理拒绝原因指向版本层", "版本层" in a_msg, a_msg)

        allowed = Principal(actor="designer", role="designer", can_write=True,
                            can_admin=True, ops_allow=("*",), theory_ok=True)
        ok_w, _ = denied(allowed.require_write, "internal")
        check("theory_ok=True → 写放行", ok_w is False)
        ok_a, _ = denied(allowed.require_admin, "scrub")
        check("theory_ok=True → 管理放行", ok_a is False)

        # ---------- ⑨ 唯一核心权限：theory op 仅 designer ----------
        check("ALL_OPS 含 theory", "theory" in tokens.ALL_OPS)
        for role, spec in tokens.ROLE_SPECS.items():
            ops = spec.get("ops_allow") or ()
            if role == "designer":
                check("designer 可执行 theory", "*" in ops, str(ops))
                continue
            check(f"{role} 的 ops_allow 不含 theory", "theory" not in ops,
                  str(ops))
            p = Principal(role=role, ops_allow=ops, theory_ok=True)
            dn, msg = denied(p.require_op, "theory")
            check(f"{role} 执行 theory 被拒", dn, msg)

        # ---------- ⑩ whoami 暴露版本层 ----------
        d = allowed.as_dict()
        check("whoami 含 theory_ok",
              "theory_ok" in d and d["theory_ok"] is True, str(d.get("theory_ok")))
        check("whoami 含 theory_version", "theory_version" in d)

        # ---------- ⑪ CLI 可用 ----------
        r = subprocess.run(
            [sys.executable, "-m", "md_cg.theory", "check"],
            env={**os.environ, "MDCG_THEORY_FILE": tf},
            cwd=root, capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=120)
        check("CLI check 退出码 0", r.returncode == 0, (r.stderr or "")[:200])
        check("CLI 输出 theory_ok=True", '"theory_ok": true' in r.stdout,
              (r.stdout or "")[:200])

    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    print(f"\nP22 版本层：{PASS} passed, {FAIL} failed")
    if FAILS:
        print("失败项：" + "、".join(FAILS))
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
