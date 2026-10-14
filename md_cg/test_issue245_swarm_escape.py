# -*- coding: utf-8 -*-
r"""#245 守卫：swarm 参数一律不得路径穿越。

缺陷（本件修复）
----------------
`swarm_dir()` 对 `swarm` 参数零校验直接返回，后被 `os.path.join` 用于
`peers_dir`/`inbox_dir` 写文件路径。传入 `../../../tmp/evil` 可穿越到
任意目录写文件（`_write_json` 自带 makedirs，任意层级自动创建）；
`_rejected.jsonl` 同样受影响。

修法（`md_cg/evidence.py`）
---------------------------
新增 `_swarm_error()` 判据，在 `swarm_dir()` 汇点校验显式传入的 path，
非法抛 `EvidenceError`（fail-closed，与 `write_pack` 的 pack_id 判据同构）：
  ① 非 str/空 → 拒；② 含空字节 → 拒；③ 含 `..` 路径段（含反斜杠形态）→ 拒。
绝对路径**不拦截**——是本模块文档化语义（`--swarm` 帮助、`MDCG_SWARM_DIR`、
test_p24_evidence 均以绝对路径调用）；`..` 在绝对形态下同样被拦截。

**磁盘证据优先**：断言穿越类输入抛 EvidenceError **且**目标外无文件落盘。

运行：python -X utf8 -m md_cg.test_issue245_swarm_escape
退出码：0 全绿 / 1 有失败
"""
from __future__ import annotations

import os
import sys
import tempfile

from . import evidence as ev

PASS = FAIL = 0
FAILS = []


def check(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  [PASS] {name}  {detail}")
    else:
        FAIL += 1
        FAILS.append(name)
        print(f"  [FAIL] {name}  {detail}")


#: 必须拦截的穿越矩阵：(名, 值)
MALICIOUS = (
    ("相对穿越", "../../../tmp/evil"),
    ("相对穿越2", "../evil_rel_demo"),
    ("纯 ..", ".."),
    ("反斜杠穿越", "..\\..\\win"),
    ("绝对路径内穿越", "/tmp/e/../../etc"),
    ("中段穿越", "a/../../b"),
    ("空字节", "bad\x00evil"),
    ("非字符串", 123),
)

#: 必须放行的合法值
LEGIT = (
    ("默认", None, ev.DEFAULT_SWARM_DIR),
    ("相对名", "team-a", "team-a"),
    ("相对子路径", "a/b", "a/b"),
)


def main():
    print("== #245 swarm 穿越守卫 ==")
    # ① 判据：穿越类一律 EvidenceError
    for name, val in MALICIOUS:
        try:
            ev.swarm_dir(val)
            check(f"拦截:{name}", False, f"{val!r} 未抛异常")
        except ev.EvidenceError:
            check(f"拦截:{name}", True, "")
        except Exception as e:  # noqa: BLE001
            check(f"拦截:{name}", False, f"抛错类型不对：{type(e).__name__}")
    # ② 判据：合法值原样通过
    for name, val, expect in LEGIT:
        try:
            got = ev.swarm_dir(val)
            check(f"放行:{name}", got == expect, f"{got!r}")
        except Exception as e:  # noqa: BLE001
            check(f"放行:{name}", False, f"不应抛：{e}")
    # ③ 绝对路径是既定语义，必须放行
    with tempfile.TemporaryDirectory() as tmp:
        s = os.path.join(tmp, "swarm")
        try:
            check("放行:绝对路径", ev.swarm_dir(s) == s, "")
        except Exception as e:  # noqa: BLE001
            check("放行:绝对路径", False, f"不应抛：{e}")
        # ④ 磁盘腿：穿越不得在目标外落盘
        before = set(os.listdir(tmp))
        try:
            ev.publish_card(os.path.join(tmp, "root"), swarm="../evil_disk")
            check("磁盘:穿越无落盘", False, "未抛异常")
        except ev.EvidenceError:
            after = set(os.listdir(tmp))
            check("磁盘:穿越无落盘", after == before, f"before={before} after={after}")
        # ⑤ 合法端到端仍可用
        r = ev.publish_card(os.path.join(tmp, "root"), swarm=s)
        check("端到端:合法可用", r["ok"] and os.path.exists(r["file"]), r["file"])

    print(f"\nSUMMARY: #245 swarm 穿越守卫：{PASS} 通过，{FAIL} 失败")
    if FAILS:
        print("失败项：", FAILS)
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
