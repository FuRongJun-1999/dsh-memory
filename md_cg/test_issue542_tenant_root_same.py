# -*- coding: utf-8 -*-
"""issue #542 守卫：租户根同一性判定必须用 realpath（解析 junction / symlink）。

背景（缺陷）：`_resolve_root` 的两处同一性比较原用 `os.path.abspath(...)`，
而 abspath **只做字符串归一（解析 `..`），不解析 junction / symlink**
⇒ 「同一物理目录的两种写法」被判为不同根。后果两种、方向相反：

  · `#98` 反查分支（未声明 MDCG_TENANT 时）：junction 指向他人登记根
    **不命中反查** ⇒ fail-closed 被**绕过**（安全面）——可跨租户读；
  · 已声明租户分支：junction 指向**自己**的登记根被判「不一致」
    ⇒ **误拒**（可用性面）。

本守卫的判据（可机械复核）：
  ① junction 指向 B 的登记根 + 未声明 tenant ⇒ **必须拒绝启动**（不得放行）；
  ② junction 指向**自己**的登记根（已声明 tenant）⇒ **必须放行**（不得误拒）；
  ③ 大小写变形（`ROOTB`）⇒ 与 ① 同判（必须拒绝）；
  ④ 无关根 ⇒ 两者皆不命中（不得误伤）。

跑法（任意 cwd）：
    python -X utf8 -m md_cg.test_issue542_tenant_root_same
退出码：全部通过 0，存在失败 1。
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile

_HERE = os.path.dirname(os.path.abspath(__file__))
_REPO = os.path.dirname(_HERE)
if _REPO not in sys.path:
    sys.path.insert(0, _REPO)

from md_cg.mcp_server import _resolve_root, _same_root  # noqa: E402

_PASS = 0
_FAIL = 0


def ok(cond, label, detail=None):
    global _PASS, _FAIL
    if cond:
        _PASS += 1
        print("  [PASS] %s" % label)
    else:
        _FAIL += 1
        print("  [FAIL] %s%s" % (label, ("  <- " + repr(detail)) if detail is not None else ""))


def _fs_case_insensitive(path: str) -> bool:
    """探测该路径所在文件系统是否大小写不敏感（#98 的大小写绕过只在其上成立）。"""
    probe = os.path.join(path, "_cis_probe_dir")
    try:
        os.makedirs(probe, exist_ok=True)
        return os.path.exists(probe.swapcase())
    except OSError:
        return False
    finally:
        shutil.rmtree(probe, ignore_errors=True)

def _mk_junction(link: str, target: str) -> bool:
    """建目录 junction（Windows）；非 Windows 退化为 symlink。返回是否成功。"""
    if os.name == "nt":
        r = subprocess.run(["cmd", "/c", "mklink", "/J", link, target],
                           capture_output=True, text=True,
                           encoding="utf-8", errors="replace")   # 第15条：不依赖 locale
        return os.path.isdir(link) and r.returncode == 0
    try:
        os.symlink(target, link, target_is_directory=True)
        return True
    except OSError:
        return False


def main() -> int:
    sandbox = tempfile.mkdtemp(prefix="issue542_")
    rootB = os.path.join(sandbox, "tenantB")
    own = os.path.join(sandbox, "ownroot")
    other = os.path.join(sandbox, "unrelated")
    for d in (rootB, own, other):
        os.makedirs(d, exist_ok=True)

    reg = os.path.join(sandbox, "_tenants.json")
    with open(reg, "w", encoding="utf-8") as fh:
        json.dump({"schema": 1, "tenants": {"tenantB": {"root": rootB}}}, fh)

    junc_to_B = os.path.join(sandbox, "decoy_link")
    junc_ok = _mk_junction(junc_to_B, rootB)

    print("== 前置：junction 建立成功（否则本守卫无判别力，必须显式 SKIP）==")
    ok(junc_ok, "前置 junction(→tenantB) 已建立", junc_to_B)
    if not junc_ok:
        print("=" * 64)
        print("通过 %d / 失败 %d（junction 不可用 ⇒ 判据不可达，请在有权限的环境重跑）" % (_PASS, _FAIL))
        print("=" * 64)
        shutil.rmtree(sandbox, ignore_errors=True)
        return 1

    # ---- 判据 A：realpath 才能判同一物理位置 ----
    print("== A 前置事实：abspath 判不同、realpath 判相同 ==")
    ok(os.path.realpath(junc_to_B) == os.path.realpath(rootB),
       "A1 realpath(junction) == realpath(真实目标)", os.path.realpath(junc_to_B))
    ok(os.path.abspath(junc_to_B) != os.path.abspath(rootB),
       "A2 abspath(junction) != abspath(真实目标)（这正是修前的绕过成因）")
    ok(_same_root(junc_to_B, rootB), "A3 _same_root(junction, 真实目标) ⇒ True")

    # ---- 判据 B（安全面）：未声明 tenant + junction 指向他人登记根 ⇒ 必须拒 ----
    print("== B 安全面：#98 反查不得被 junction 绕过 ==")
    root, err = _resolve_root({"MDCG_ROOT": junc_to_B,
                               "MDCG_TENANT_REGISTRY": reg})
    ok(root is None and err, "B1 未声明 tenant + MDCG_ROOT=junction→B ⇒ 拒绝启动", (root, err))

    # 对照：真根也要拒（证明反查本身有效，非因 junction 才拒）
    root2, err2 = _resolve_root({"MDCG_ROOT": rootB, "MDCG_TENANT_REGISTRY": reg})
    ok(root2 is None and err2, "B2 对照：MDCG_ROOT=B 真根 ⇒ 同样拒绝（反查有效）", (root2, err2))

    # ---- 判据 C：大小写变形同判 ----
    print("== C 大小写变形亦不得绕过 ==")
    upper = rootB.upper()
    # v0.9.1：大小写变形**只在大小写不敏感的文件系统上**等价于同一物理位置；
    # 在 POSIX（大小写敏感）上，大写后是一条全新路径，此时「必须拒绝」不是本闸的判据
    # ——E1 已钉住「无关的新根应放行」。故按文件系统实际语义分档，不按平台名猜。
    if upper != rootB and _fs_case_insensitive(rootB):
        root3, err3 = _resolve_root({"MDCG_ROOT": upper, "MDCG_TENANT_REGISTRY": reg})
        ok(root3 is None and err3, "C1 未声明 tenant + MDCG_ROOT=B 全大写 ⇒ 拒绝启动", (root3, err3))
    else:
        print("  [SKIP] C1 大小写敏感文件系统：大写后是另一条路径，本变形不可构造（#98 的大小写绕过只在大小写不敏感的 FS 上成立）")

    # ---- 判据 D（可用性面）：已声明 tenant + junction 指向自己登记根 ⇒ 必须放行 ----
    print("== D 可用性面：junction 指向自己的登记根不得被误拒 ==")
    root4, err4 = _resolve_root({"MDCG_TENANT": "tenantB", "MDCG_ROOT": junc_to_B,
                                 "MDCG_TENANT_REGISTRY": reg})
    ok(err4 is None, "D1 声明 tenantB + MDCG_ROOT=junction→B（自己的根）⇒ 放行（修前误拒）",
       (root4, err4))

    # ---- 判据 E：无关根不得误伤 ----
    print("== E 无关根不得被误判 ==")
    root5, err5 = _resolve_root({"MDCG_ROOT": other, "MDCG_TENANT_REGISTRY": reg})
    ok(err5 is None and root5, "E1 未声明 tenant + 无关自建根 ⇒ 放行（自建根不受 #98 影响）",
       (root5, err5))

    print("=" * 64)
    print("通过 %d / 失败 %d" % (_PASS, _FAIL))
    print("=" * 64)
    shutil.rmtree(sandbox, ignore_errors=True)
    return 1 if _FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
