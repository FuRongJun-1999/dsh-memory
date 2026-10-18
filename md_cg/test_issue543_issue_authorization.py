# -*- coding: utf-8 -*-
"""issue #543 守卫：`tokens issue` 的签发授权闸（管理级角色不得被「谁都能签」）。

背景（缺陷）：签发动作此前**没有任何授权门** —— 只要求目标目录可写，
不校验调用者身份、也不看是否已有更高权凭据。叠加「凭据库位置由
`MDCG_AUX_ROOT` 决定」（`datapath.aux_root`），构成提权原语：
**换一个空目录 + 设一个环境变量 = 拿到 designer 全权身份**
（实测可写 anchor/self 受保护层）。

本守卫的判据（可机械复核）：
  ① **空库首启**签 designer ⇒ 放行（保留既有开箱体验，不得误伤）；
  ② **库非空**再签 designer ⇒ 拒绝（核心判据：不给「换个空目录自铸」留门）；
  ③ 非管理级角色（recorder）⇒ 不受闸影响，始终可签；
  ④ 显式开关 `MDCG_ALLOW_ROOT_ISSUE=1` ⇒ 放行（运维逃生口）；
  ⑤ 出示既有管理级 Principal（`_authorized_by`）⇒ 放行（推荐委派路径）；
  ⑥ 空库时自举出的令牌**确实可用**（`verify_token` 通过、can_admin 为真）
     —— 证明闸不是把功能整个掐掉。

跑法（任意 cwd）：
    python -X utf8 -m md_cg.test_issue543_issue_authorization
退出码：全部通过 0，存在失败 1。
"""
from __future__ import annotations

import os
import shutil
import sys
import tempfile

_HERE = os.path.dirname(os.path.abspath(__file__))
_REPO = os.path.dirname(_HERE)
if _REPO not in sys.path:
    sys.path.insert(0, _REPO)

from md_cg import tokens as T  # noqa: E402

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


def _tokfile(d: str) -> str:
    return os.path.join(d, "_tokens.json")


def main() -> int:
    sandbox = tempfile.mkdtemp(prefix="issue543_")
    saved = os.environ.pop("MDCG_ALLOW_ROOT_ISSUE", None)
    try:
        # ---- 判据 ①：空库首启自举放行 ----
        print("== G1 空库首启：签 designer 必须放行（既有开箱体验不变）==")
        d1 = os.path.join(sandbox, "g1")
        os.makedirs(d1, exist_ok=True)
        t1 = _tokfile(d1)
        r1 = None
        try:
            r1 = T.issue("designer", actor="firstboot", path=t1)
        except Exception as exc:                      # noqa: BLE001
            r1 = "EXC:%s" % type(exc).__name__
        ok(isinstance(r1, dict) and r1.get("ok"), "G1a 空库 + designer ⇒ 放行", r1)

        # ---- 判据 ⑥：自举令牌确实可用 ----
        print("== G2 自举出的令牌必须真的可用（闸不是把功能掐掉）==")
        if isinstance(r1, dict) and r1.get("token"):
            try:
                p = T.verify_token(r1["token"], path=t1)
                ok(getattr(p, "can_admin", False) is True,
                   "G2a verify_token 通过且 can_admin=True", getattr(p, "can_admin", None))
                ok(getattr(p, "role", None) == "designer", "G2b role=designer",
                   getattr(p, "role", None))
            except Exception as exc:                  # noqa: BLE001
                ok(False, "G2 verify_token 应通过", "%s: %s" % (type(exc).__name__, exc))
        else:
            ok(False, "G2 前置：G1 未产出令牌")

        # ---- 判据 ②：库非空再签 designer ⇒ 拒绝（核心） ----
        print("== G3 库非空：再签 designer 必须拒绝（核心判据）==")
        r2 = None
        try:
            r2 = T.issue("designer", actor="attacker", path=t1)
        except T.TokenError as exc:
            r2 = exc
        except Exception as exc:                      # noqa: BLE001
            r2 = "OTHER:%s" % type(exc).__name__
        ok(isinstance(r2, T.TokenError),
           "G3a 库非空 + designer（无凭据出示）⇒ TokenError", r2)

        # ---- 判据 ③：非管理级角色不受闸影响 ----
        print("== G4 非管理级角色不受闸影响 ==")
        r3 = None
        try:
            r3 = T.issue("recorder", actor="normal", path=t1)
        except Exception as exc:                      # noqa: BLE001
            r3 = "EXC:%s" % type(exc).__name__
        ok(isinstance(r3, dict) and r3.get("ok"), "G4a 库非空 + recorder ⇒ 放行", r3)

        # ---- 判据 ④：显式开关放行 ----
        print("== G5 显式开关 MDCG_ALLOW_ROOT_ISSUE=1 ⇒ 放行（运维逃生口）==")
        os.environ["MDCG_ALLOW_ROOT_ISSUE"] = "1"
        r4 = None
        try:
            r4 = T.issue("designer", actor="ops", path=t1)
        except Exception as exc:                      # noqa: BLE001
            r4 = "EXC:%s" % type(exc).__name__
        ok(isinstance(r4, dict) and r4.get("ok"), "G5a 开关打开 ⇒ 放行", r4)
        os.environ.pop("MDCG_ALLOW_ROOT_ISSUE", None)
        # 开关关闭后应恢复拒绝（不得因上次放行而粘住）
        r4b = None
        try:
            T.issue("designer", actor="attacker2", path=t1)
            r4b = "ALLOWED"
        except T.TokenError:
            r4b = "TokenError"
        ok(r4b == "TokenError", "G5b 开关关闭后恢复拒绝（不粘住）", r4b)

        # ---- 判据 ⑤：出示既有管理级 Principal ⇒ 放行 ----
        print("== G6 出示既有管理级 Principal ⇒ 放行（推荐委派路径）==")
        class _P:
            can_admin = True
        r5 = None
        try:
            r5 = T.issue("designer", actor="delegated", path=t1, _authorized_by=_P())
        except Exception as exc:                      # noqa: BLE001
            r5 = "EXC:%s" % type(exc).__name__
        ok(isinstance(r5, dict) and r5.get("ok"), "G6a _authorized_by(can_admin=True) ⇒ 放行", r5)

        print("=" * 64)
        print("通过 %d / 失败 %d" % (_PASS, _FAIL))
        print("=" * 64)
        return 1 if _FAIL else 0
    finally:
        if saved is not None:
            os.environ["MDCG_ALLOW_ROOT_ISSUE"] = saved
        shutil.rmtree(sandbox, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
