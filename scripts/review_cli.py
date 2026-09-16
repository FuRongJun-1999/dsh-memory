# -*- coding: utf-8 -*-
"""review_cli · 审核队列裁决命令行（设计者/管理权限专用）

背景：本机未配置外部验证器（MDCG_VERIFIER_MODULES）时，写入恒判 DEFER
入审核队列——这是诚实行為（不假装通过）。裁决权专属 can_admin 角色
（写入者不得自裁自决），agent 端被 AccessDenied 拒绝是设计行为；
由设计者在本机直接运行本脚本完成裁决。

用法（root 须与待裁决部署一致：--root 或环境变量 MDCG_ROOT）：
  python scripts/review_cli.py list
  python scripts/review_cli.py accept  <pid> --reason "实跑测试证据"
  python scripts/review_cli.py reject  <pid> --reason "内容有误"
  python scripts/review_cli.py edit    <pid> --content "修正后内容" --reason "..."
  python scripts/review_cli.py merge   <pid> --into <已有节点id> --reason "..."
  python scripts/review_cli.py rounds  <pid>        # 某提案裁决轮次历史

裁决留痕：decisions.jsonl + 审计 md 节点（由 review_decide 内部完成）。
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

from md_cg.mdcos import MdCGSecure        # noqa: E402
from md_cg.security import Principal      # noqa: E402


def _root(args):
    root = getattr(args, "root", None) or os.environ.get("MDCG_ROOT", "")
    if not root:
        sys.exit("错误：未指定存储根（--root 或环境变量 MDCG_ROOT）。\n"
                 "root 必须与待裁决的部署一致——猜错会裁决到另一个空库。")
    if not os.path.isdir(root):
        sys.exit("错误：root 不存在：%s" % root)
    return root


def _cg(args):
    p = Principal(actor="designer-cli", clearance="secret",
                  can_write=True, can_admin=True, role="designer",
                  auth_mode="local-cli")
    return MdCGSecure(_root(args), principal=p)


def _brief(rec, width=66):
    text = (rec.get("content") or rec.get("statement") or "").replace("\n", " ")
    return text[:width] + ("…" if len(text) > width else "")


def _execute(cg, args):
    """按子命令执行裁决（cg 的生命周期由 main 统一收尾）。"""
    if args.cmd == "list":
        pend = cg.review_list()
        if not pend:
            print("审核队列为空（0 条待审）。")
            return 0
        print("待审 %d 条：" % len(pend))
        for r in pend:
            tags = (", tags=" + ",".join(r.get("tags") or [])) if r.get("tags") else ""
            print("  [%s] %s · %s 层%s · round=%s\n      %s" % (
                r.get("pid"), r.get("status"), r.get("layer") or "?",
                tags, r.get("round") or 0, _brief(r)))
        print('\n裁决示例：python scripts/review_cli.py accept <pid> --reason "实跑测试证据"')
        return 0

    if args.cmd == "rounds":
        print(json.dumps(cg.review_rounds(args.pid), ensure_ascii=False, indent=1))
        return 0

    if args.cmd == "edit":
        edits = {"content": args.content}
        if args.tags:
            edits["tags"] = [t.strip() for t in args.tags.split(",") if t.strip()]
        if args.layer:
            edits["layer"] = args.layer
        out = cg.review_decide(args.pid, "edit", edits=edits, reason=args.reason)
    else:
        out = cg.review_decide(args.pid, args.cmd,
                               merge_into=getattr(args, "into", None),
                               reason=args.reason)

    if out.get("ok"):
        print("已裁决：%s → %s%s" % (
            args.pid, args.cmd,
            ("，落盘节点 " + out["node_id"]) if out.get("node_id") else ""))
        return 0
    print("裁决未生效：%s" % json.dumps(out, ensure_ascii=False))
    return 1


def main(argv=None):
    ap = argparse.ArgumentParser(description="灵枢审核队列裁决（designer 权限）")
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--root", help="存储根目录（默认环境变量 MDCG_ROOT）")
    sub = ap.add_subparsers(dest="cmd", required=True)

    sub.add_parser("list", help="列出待审条目", parents=[common])
    for name, help_ in (("accept", "按原样写入落盘"), ("reject", "丢弃（只记裁决）")):
        s = sub.add_parser(name, help=help_, parents=[common])
        s.add_argument("pid")
        s.add_argument("--reason", default="", help="裁决理由（进留痕）")
    s = sub.add_parser("edit", help="修订后写入", parents=[common])
    s.add_argument("pid")
    s.add_argument("--content", required=True)
    s.add_argument("--tags", default=None, help="逗号分隔")
    s.add_argument("--layer", default=None)
    s.add_argument("--reason", default="")
    s = sub.add_parser("merge", help="合并进已有节点", parents=[common])
    s.add_argument("pid")
    s.add_argument("--into", required=True, help="目标节点 id")
    s.add_argument("--reason", default="")
    s = sub.add_parser("rounds", help="某提案的裁决轮次历史", parents=[common])
    s.add_argument("pid")
    args = ap.parse_args(argv)

    cg = _cg(args)
    try:
        return _execute(cg, args)
    finally:
        # 收尾（2026-09-16 取证）：裁决写入先进内存 _dirty，不落盘则「节点在盘上
        # 但索引无条目」——已有 _index.json 的根重开不重扫目录，其它进程与重载后的
        # 长驻进程都检索不到（只能靠某次全量 rebuild 偶然救回）。库层另有 atexit
        # 兜底，但显式收尾才是正路：兜底只覆盖「正常退出」这一条路径。
        cg.close()


if __name__ == "__main__":
    sys.exit(main())
