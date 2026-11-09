# -*- coding: utf-8 -*-
"""签名策略「默认即最弱」只读巡检（t98a-20261011 / t3）。

背景
----
`md_cg/signer.py` 的 `load_policies()` 在策略文件**缺失 / 读不出 / 非 dict** 时
原先回落 `require_peer_signature=False` + `on_verify_fail='degrade'` —— 即
「什么都没配」等于「最弱配置」，而且是**静默**的：没有任何面会告诉你策略文件
根本不存在。本脚本把这件事变成**可见且报红**的。

它做什么
--------
只读打印当前实际生效的签名策略来源与四个关键取值：

    · 策略文件路径（`signer.signers_file()` 的解析结果）
    · 该文件是否存在
    · 生效 signer
    · require_peer_signature
    · on_verify_fail

并在下列任一情形以**非 0 退出码报红**（判据来自验收原文）：

    A 策略文件**缺失**（`exists is False`）—— 这正是「默认即最弱」的场景；
    B 生效 signer 为 `hmac-local` 且 `require_peer_signature` 非 True；
    C `on_verify_fail == 'degrade'`。

「严」的定义：`require_peer_signature is True` **且** `on_verify_fail == 'reject'`；
两者任一不满足即不算从严。

只读保证
--------
**绝不写盘**：不调用 `save_policies` / `set_policy` / `remove_policy` /
`save_key` / `load_key`，也不碰 `_signer.key`。连 `~/.mdcg/_signers.json` 都
不会因本脚本而被创建。只经 `signer.policy_source()` 这个只读探针取事实。

用法
----
    python D:\\wook\\lingshu-src\\md_cg\\check_security_defaults.py
    python ...\\check_security_defaults.py --signers-file <path>

退出码
------
    0  未命中任何报红判据（当前已是严格配置）
    1  报红（命中 A / B / C 中至少一条）
    2  巡检自身故障（拿不到策略事实）
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import sys


# 生效条件：仓库根（本文件所在包目录的上一级）不在 sys.path 时插入到首位，返回该根路径。
def _repo_root() -> str:
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


# 生效条件：优先 `from md_cg import signer` 成功即返回该模块；失败（无包上下文/导入错误）时按文件路径 importlib 加载同目录 signer.py，仍失败则返回 None。
def _load_signer():
    """取 signer 模块：包导入优先，失败则按文件路径加载。

    本文件要能被**当脚本直接跑**（`python .../check_security_defaults.py`），
    那时 `md_cg` 不一定在 sys.path 上，故必须有按路径加载的兜底。
    """
    root = _repo_root()
    if root not in sys.path:
        sys.path.insert(0, root)
    try:
        from md_cg import signer            # noqa: WPS433 (延迟导入是刻意的)
        return signer
    except Exception:                       # noqa: BLE001 —— 兜底路径见下
        pass
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "signer.py")
    if not os.path.isfile(path):
        return None
    spec = importlib.util.spec_from_file_location("_md_cg_signer_standalone", path)
    if spec is None or spec.loader is None:
        return None
    mod = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(mod)
    except Exception:                       # noqa: BLE001
        return None
    return mod


# 生效条件：default 为 None 时返回 fallback，否则返回 default（用于探针缺键时的保守回落）。
def _pick(default, fallback):
    return fallback if default is None else default


# 生效条件：就 src（policy_source 的返回）与 signer 模块返回 (report, reasons)；reasons 非空即报红，判据为 文件缺失 / hmac-local 且未要求对端签名 / on_verify_fail=='degrade' / 未达「严」标准。
def evaluate(src: dict, signer_mod) -> tuple:
    """把只读探针结果折算成 (报告 dict, 报红理由 list[str])。

    纯函数，无 I/O、无写入 —— 测试可直接喂合成输入。
    """
    eff = (src or {}).get("effective") or {}
    file = (src or {}).get("file")
    exists = bool((src or {}).get("exists"))
    signer_name = _pick(eff.get("signer"),
                        getattr(signer_mod, "DEFAULT_SIGNER", "hmac-local"))
    require_peer = bool(eff.get("require_peer_signature"))
    on_fail = _pick(eff.get("on_verify_fail"), "degrade")

    reasons = []
    if not exists:
        reasons.append(
            "策略文件缺失（%s）—— 当前跑的是「默认即最弱」的隐式回落" % file)
    if signer_name == "hmac-local" and not require_peer:
        reasons.append(
            "生效 signer 为 hmac-local 且 require_peer_signature=False"
            " —— 本地自签且不要求对端签名")
    if on_fail == "degrade":
        reasons.append(
            "on_verify_fail='degrade' —— 验签失败仅降级，不隔离也不拒绝")
    if not (require_peer is True and on_fail == "reject"):
        reasons.append(
            "整体未达从严标准（要求 require_peer_signature=True 且 "
            "on_verify_fail='reject'）")

    report = {
        "file": file,
        "exists": exists,
        "signer": signer_name,
        "require_peer_signature": require_peer,
        "on_verify_fail": on_fail,
        "strict": bool(require_peer is True and on_fail == "reject"),
        "missing_strict": bool((src or {}).get("missing_strict")),
    }
    return report, reasons


# 生效条件：argv 就绪时解析 --signers-file/--json，经只读探针打印报告并返回退出码；signer 模块或探针不可用返回 2，命名判据命中返回 1，否则 0。全程不写盘。
def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        prog="python check_security_defaults.py",
        description="签名策略「默认即最弱」只读巡检（不写盘）")
    ap.add_argument("--signers-file", default=None,
                    help="策略文件路径（缺省用 MDCG_SIGNERS_FILE 或 "
                         "signer.DEFAULT_SIGNERS_FILE）")
    ap.add_argument("--json", action="store_true",
                    help="只输出 JSON 报告")
    args = ap.parse_args(argv)

    signer_mod = _load_signer()
    if signer_mod is None:
        print("[check_security_defaults] 无法加载 md_cg.signer —— 巡检无法进行",
              file=sys.stderr)
        return 2

    try:
        src = signer_mod.policy_source(args.signers_file)
    except Exception as exc:                # noqa: BLE001 —— 探针故障即 fail-closed
        print("[check_security_defaults] 只读探针失败：%r" % (exc,),
              file=sys.stderr)
        return 2

    report, reasons = evaluate(src, signer_mod)

    if args.json:
        print(json.dumps({"report": report, "reasons": reasons},
                         ensure_ascii=False, indent=1))
        return 1 if reasons else 0

    print("=" * 62)
    print("签名策略只读巡检（t98a / 默认即最弱）")
    print("=" * 62)
    print("  策略文件          : %s" % report["file"])
    print("  文件是否存在      : %s" % ("是" if report["exists"] else "否"))
    print("  生效 signer       : %s" % report["signer"])
    print("  要求对端签名      : %s" % report["require_peer_signature"])
    print("  验签失败处置      : %s" % report["on_verify_fail"])
    print("  是否已达从严      : %s" % ("是" if report["strict"] else "否"))
    print("-" * 62)
    if reasons:
        print("结果：报红（非 0 退出码）—— 命中 %d 条判据：" % len(reasons))
        for r in reasons:
            print("  · %s" % r)
        print("=" * 62)
        return 1
    print("结果：未见「默认即最弱」—— 策略文件在且显式从严。")
    print("=" * 62)
    return 0


if __name__ == "__main__":
    sys.exit(main())
