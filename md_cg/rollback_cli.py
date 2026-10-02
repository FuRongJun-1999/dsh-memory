# -*- coding: utf-8 -*-
"""rollback_cli · 变更单回滚命令行（三档自治 · 设计 v0.2 §四「回滚原语四条」）。

用法（root 须与执行该变更单的部署一致：--root 或环境变量 MDCG_ROOT）：
  python -X utf8 -m md_cg.rollback_cli --root <root> --pid <pid>
  python -X utf8 -m md_cg.rollback_cli --root <root> --pid <pid> --reason "..."

本模块是**回滚命令串的载体**：变更单执行时点的 `rollback` 字段即指向本 CLI
（`md_cg.rollback.command_for` 构造，随执行记录落 decisions.jsonl 的
`rec["mutation"]["rollback"]`）。CLI 做的事：

  1. 从 `<root>/hippocampus/decisions.jsonl` 读回该 pid 最后一条
     `decision="accept"` 的裁决记录，取其 `rec["mutation"]`（**执行时点载荷**
     ——动作类/目标/前像/影响面/回滚命令由执行桥补全）；
  2. 交统一回滚入口 `rollback.rollback_mutation` 按动作类分派：
       · C 改写 → 从执行时点前像恢复（含第三方改动的那个版本）；
       · B 合并 → 聚合行定向剥离 + 前像 fm 恢复；
       · D 删除 → 既有 restore（trash + 删除清单口径）+ 前像校准；
  3. 输出 JSON（stdout）：`ok` + `bytes_equal_preimage`（逐字节比对前像读数）
     + `residual`（残留核对：边/索引条目/聚合行三面）。

退出码：0 = 回滚完成（读数照实打印，含校准等如实字段）；1 = 未回滚
（错误体照实打印——绝不假装成功）。

边界（如实）：本 CLI 不做裁决（回滚是执行记录的既有授权动作——它的执行时点
前像就是执行桥拍的）；对**未执行**（reject / fail-closed / pending）的变更单，
统一入口以 `rollback_gap` fail-closed 拒绝（无前像即不猜）。
"""
import argparse
import json
import os
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except AttributeError:
    pass

_HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

from md_cg import rollback as _rb          # noqa: E402
from md_cg.mdcos import MdCGOS             # noqa: E402


# 生效条件：args 的 root 属性为真值（含 getattr 缺省 None 时回落）否则回落 os.environ.get("MDCG_ROOT", "")，两者皆空串或该值经 os.path.isdir 判定不是目录时 sys.exit 退出，否则返回该 root；
def _root(args):
    root = getattr(args, "root", None) or os.environ.get("MDCG_ROOT", "")
    if not root:
        sys.exit("错误：未指定存储根（--root 或环境变量 MDCG_ROOT）。\n"
                 "root 必须与执行该变更单的部署一致——猜错会回滚到另一个库。")
    if not os.path.isdir(root):
        sys.exit("错误：root 不存在：%s" % root)
    return root


# 生效条件：cg 与 pid 就绪时返回 decisions 记录中 pid 匹配、decision=="accept" 且 rec["mutation"] 为 dict 的最后一条记录；无匹配返回 None（调用方 fail-closed）；
def _mutation_record(cg, pid):
    """从裁决记录读回变更单的执行时点载荷（rec["mutation"]）。"""
    picked = None
    for r in cg.decisions():
        if r.get("pid") != pid:
            continue
        if r.get("decision") != "accept":
            continue
        if isinstance(r.get("mutation"), dict):
            picked = r
    return picked


# 生效条件：argv 为 None（默认）时由 argparse 解析 sys.argv、否则解析传入的 argv（--root/--pid 必填、--reason 可选），解析成功后取 root 构造 MdCGOS(root, autoflush=1)，无匹配执行记录时打印 ok False error decision_not_found 并返回 1，否则调 rollback.rollback_mutation 打印其结果 JSON，按其 ok 真值返回 0、假值返回 1；finally 中执行 cg.close()；
def main(argv=None):
    ap = argparse.ArgumentParser(
        prog="python -m md_cg.rollback_cli",
        description="变更单回滚（设计 §四：从执行时点前像恢复）")
    ap.add_argument("--root", help="存储根目录（默认环境变量 MDCG_ROOT）")
    ap.add_argument("--pid", required=True, help="变更单的裁决 pid（accept 记录）")
    ap.add_argument("--reason", default="", help="回滚理由（进返回体）")
    args = ap.parse_args(argv)

    cg = MdCGOS(_root(args), autoflush=1)
    try:
        rec = _mutation_record(cg, args.pid)
        if rec is None:
            out = {"ok": False, "error": "decision_not_found", "pid": args.pid,
                   "hint": "decisions.jsonl 中无该 pid 的 accept 执行记录"
                           "（或记录缺 mutation 载荷）——变更单未执行即无可"
                           "回滚的前像（fail-closed，不猜）。"}
            print(json.dumps(out, ensure_ascii=False))
            return 1
        out = _rb.rollback_mutation(cg, rec["mutation"], reason=args.reason,
                                    actor="rollback-cli")
        print(json.dumps(out, ensure_ascii=False, default=str))
        return 0 if out.get("ok") else 1
    finally:
        # 收尾（与 review_cli 同款）：回滚落盘经 _dirty→flush→_index_log，
        # 不 close 则「节点在盘上但索引无条目」；库层另有 atexit 兜底，显式
        # 收尾才是正路。
        cg.close()


if __name__ == "__main__":
    sys.exit(main())
