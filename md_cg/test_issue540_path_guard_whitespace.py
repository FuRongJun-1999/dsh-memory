# -*- coding: utf-8 -*-
"""issue #540 守卫：路径类工具参数的「判空」不得把**纯空白**当成「没给参数」。

背景（缺陷）：`check_path_root` / `check_export_target` 原判据是
`if path is None or str(path).strip() == "":  return`。
`str.strip()` 剥的是**全部 Unicode 空白**，而其中若干字符在 NTFS 上是**合法文件名
字符**（NBSP U+00A0、全角空格 U+3000、行分隔符 U+2028、OGHAM 空格 U+1680 等）。
两者交集即：闸门判「无参数」而早退放行，该串随后被当作真实路径使用
——实测 `op=export` + `out="\\u00a0"` 会把整库正文写到白名单根之外。

本守卫的判据（可机械复核）：
  ① 纯空白输入 ⇒ 两道闸**均抛 PermissionError**（不得早退放行）；
  ② `None` 与 `""` ⇒ 两道闸**仍放行**（"没给参数"的既有语义不得被误伤）；
  ③ 空白字符集**不枚举**：覆盖 4+ 个不同 Unicode 空白，防止有人只拉黑常见的两个。

跑法（任意 cwd；本仓约定以模块方式从仓根跑）：
    python -X utf8 -m md_cg.test_issue540_path_guard_whitespace
退出码：全部通过 0，存在失败 1。
"""
from __future__ import annotations

import os
import sys
import tempfile

_HERE = os.path.dirname(os.path.abspath(__file__))
_REPO = os.path.dirname(_HERE)
if _REPO not in sys.path:
    sys.path.insert(0, _REPO)

from md_cg.security import check_export_target, check_path_root  # noqa: E402

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


#: 纯空白字符集——**刻意不止常见的两个**，判据必须是「全部空白」而非枚举黑名单。
#:
#: 注意与 `test_p14_root_fallback.c4_no_path_arg` 的既有契约的关系（本守卫 G3 钉住）：
#: 那条契约是「`None` / `''` / ASCII 空格 不触回落、不写配置」——本修复**保留**它，
#: 故 ASCII 空格仍走「无参数」早退。真正要拒的是**能在该平台成为文件名**的空白
#: （实测 Windows：ASCII 空格与 TAB 建文件被 OS 拒，NBSP/U+3000 能建出文件）。
#: 为免歧义，G1/G2 用**非纯 ASCII 空格**的字符证明判据不是碰巧。
WHITESPACE_ONLY = [
    ("NBSP U+00A0", "\u00a0"),
    ("全角空格 U+3000", "\u3000"),
    ("行分隔符 U+2028", "\u2028"),
    ("OGHAM 空格 U+1680", "\u1680"),
    ("多字符混合（含 NBSP）", " \u00a0\t\u3000"),
]


def _expect_denied(fn, *args, **kw):
    """返回 (是否被拒, 异常类型名或 None)。"""
    try:
        fn(*args, **kw)
        return False, None
    except PermissionError:
        return True, "PermissionError"
    except Exception as exc:                      # noqa: BLE001
        return False, type(exc).__name__


def main() -> int:
    sandbox = tempfile.mkdtemp(prefix="issue540_")
    root = os.path.join(sandbox, "root")
    lib = os.path.join(sandbox, "lib")
    os.makedirs(root, exist_ok=True)
    os.makedirs(lib, exist_ok=True)
    os.environ["MDCG_TEST_ISSUE540_ROOT"] = root

    print("== G1 纯空白 ⇒ check_path_root 必须拒绝（不得早退放行）==")
    for name, val in WHITESPACE_ONLY:
        denied, kind = _expect_denied(
            check_path_root, val, "MDCG_TEST_ISSUE540_ROOT", "export")
        ok(denied, "G1 %-18s ⇒ PermissionError" % name, kind)

    print("== G2 纯空白 ⇒ check_export_target 必须拒绝（#211 新增闸同样必修）==")
    for name, val in WHITESPACE_ONLY:
        denied, kind = _expect_denied(
            check_export_target, val, lib, "export", allow_overwrite=True)
        ok(denied, "G2 %-18s ⇒ PermissionError" % name, kind)

    print("== G3 未给参数（None / 空串）⇒ 两道闸仍放行（不得误伤既有语义）==")
    for label, val in (("None", None), ("空串", "")):
        ok(not _expect_denied(check_path_root, val, "MDCG_TEST_ISSUE540_ROOT", "export")[0],
           "G3a %-6s ⇒ check_path_root 放行（无路径参数）" % label)
        ok(not _expect_denied(check_export_target, val, lib, "export", allow_overwrite=True)[0],
           "G3b %-6s ⇒ check_export_target 放行（未指定落点）" % label)

    print("== G3c 既有 p14 契约：ASCII 空格仍按「无路径参数」放行（不误伤）==")
    ok(not _expect_denied(check_path_root, "   ", "MDCG_TEST_ISSUE540_ROOT", "export")[0],
       "G3c '   '（纯 ASCII 空格）⇒ 仍放行（test_p14 c4_no_path_arg 契约）")
    ok(not _expect_denied(check_export_target, "   ", lib, "export", allow_overwrite=True)[0],
       "G3d '   ' ⇒ check_export_target 仍放行（同契约）")

    print("== G4 正常根内路径仍放行（修复不得过宽）==")
    inside = os.path.join(root, "ok.jsonl")
    ok(not _expect_denied(check_path_root, inside, "MDCG_TEST_ISSUE540_ROOT", "export")[0],
       "G4a 根内普通路径 ⇒ 放行")
    ok(not _expect_denied(check_export_target, inside, lib, "export", allow_overwrite=True)[0],
       "G4b 库根外普通路径 ⇒ 放行（allow_overwrite=True）")

    print("== G5 根外路径仍被拒（原判据不被削弱）==")
    outside = os.path.join(tempfile.gettempdir(), "issue540_outside_%d" % os.getpid())
    ok(_expect_denied(check_path_root, outside, "MDCG_TEST_ISSUE540_ROOT", "export")[0],
       "G5 根外绝对路径 ⇒ 仍 PermissionError")

    print("=" * 64)
    print("通过 %d / 失败 %d" % (_PASS, _FAIL))
    print("=" * 64)
    return 1 if _FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
