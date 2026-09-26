# -*- coding: utf-8 -*-
"""review_cli · 审核队列裁决命令行（设计者/管理权限专用）

背景：本机未配置外部验证器（MDCG_VERIFIER_MODULES）时，写入恒判 DEFER
入审核队列——这是诚实行為（不假装通过）。裁决权专属 can_admin 角色
（写入者不得自裁自决），agent 端被 AccessDenied 拒绝是设计行为；
由设计者在本机直接运行本脚本完成裁决。

用法（root 须与待裁决部署一致：--root 或环境变量 MDCG_ROOT）：
  python scripts/review_cli.py list
  python scripts/review_cli.py accept  <pid> --session <会话id> --reason "实跑测试证据"
  python scripts/review_cli.py reject  <pid> --reason "内容有误"
  python scripts/review_cli.py edit    <pid> --content "修正后内容" --reason "..."
  python scripts/review_cli.py merge   <pid> --into <已有节点id> --reason "..."
  python scripts/review_cli.py noop    <pid> --reason "已评估，判定无需改动"
  python scripts/review_cli.py rounds  <pid>        # 某提案裁决轮次历史
  python scripts/review_cli.py stats                # 裁决动作统计（含 noop）

noop 语义：**已评估、判定不改变任何现有记忆**——只留痕（decisions.jsonl +
审计 md 节点）并关闭提案，不落业务节点、不进负记忆。它与 reject 的区别是
「评估过了、无需改动」而非「否掉这条候选」，故不可借 noop 绕过 accept 门控。

裁决留痕：decisions.jsonl + 审计 md 节点（由 review_decide 内部完成）。

落盘归因（P1 修复，2026-09-26，与包内 md_cg/review_cli.py 同步）：
  · 会话：--session（各子命令通用）缺省取环境变量 MDCG_SESSION，仍无则维持
    现状随机会话并 stderr 告警一行。同一批裁决传同一 session，落盘节点的
    frontmatter.session 才稳定一致。
  · 写入者：accept/edit 落盘节点的 frontmatter.writer 保留**提案原始写入者**
    （propose 时库端快照的 actor）；裁决者身份记入 frontmatter.reviewer。
  · DSH 前置条件（环境侧自行核对，本 CLI 不校验）：MCP 写入面对 DSH 形态会话
    id（session-<8>-<4>-<4>-<4>-<12>）有 `_normalize_session` 防编造校验
    （md_cg/mcp_server.py）——会话目录须真存在于 MDCG_DSH_SESSIONS_ROOT 或
    ~/.dsh/sessions 之下，否则该会话在 MCP 面降级为 anonymous。
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


# 生效条件：args 的 root 属性为真值（含 getattr 缺省 None 时回落）否则回落 os.environ.get("MDCG_ROOT", "")，两者皆空串或该值经 os.path.isdir 判定不是目录时 sys.exit 退出，否则返回该 root。
def _root(args):
    root = getattr(args, "root", None) or os.environ.get("MDCG_ROOT", "")
    if not root:
        sys.exit("错误：未指定存储根（--root 或环境变量 MDCG_ROOT）。\n"
                 "root 必须与待裁决的部署一致——猜错会裁决到另一个空库。")
    if not os.path.isdir(root):
        sys.exit("错误：root 不存在：%s" % root)
    return root


# 生效条件：args 的 session 属性为真值（含 getattr 缺省 None 回落）或环境变量 MDCG_SESSION 去空白后非空时返回该值（前者优先），两者皆无返回 None。
def _session_of(args):
    """裁决会话归属：--session > 环境变量 MDCG_SESSION > None（随机 + 告警）。"""
    s = str(getattr(args, "session", None)
            or os.environ.get("MDCG_SESSION", "") or "").strip()
    return s or None


# 生效条件：args 就绪时先经 _session_of 取裁决会话归属，取到 None 时向 stderr 告警一行（缺省随机会话、同批裁决请传同一 --session）后维持现状；随后构造写死权限的 Principal(actor="designer-cli", clearance="secret", can_write=True, can_admin=True, role="designer", auth_mode="local-cli", session=<上述归属>)，再以 _root(args) 取到的存储根返回 MdCGSecure(root, principal=p)。
def _cg(args):
    session = _session_of(args)
    if session is None:
        # P1 归因（2026-09-26，DSH 端在役实测）：缺省随机会话会让同一批裁决
        # 得到互不相同的落盘归属（5 节点 5 个 sess_* 实录）。不拒绝、告警一行
        # 后维持现状（向后兼容）；要稳定归属请显式传同一 --session。
        sys.stderr.write("警告：未指定 --session / 环境变量 MDCG_SESSION，"
                         "本次裁决落盘使用随机会话 id——同一批裁决请传同一 "
                         "--session 以稳定归属。\n")
    p = Principal(actor="designer-cli", clearance="secret",
                  can_write=True, can_admin=True, role="designer",
                  auth_mode="local-cli", session=session)
    return MdCGSecure(_root(args), principal=p)


# 生效条件：rec 支持 .get 时，取 rec.get("content") 为假值则取 rec.get("statement")、再为假值则取空串，把其中的换行替换为空格，并按 width（缺省 66）切片后仅当 len(text) > width 才追加 "…"，返回该字符串。
def _brief(rec, width=66):
    text = (rec.get("content") or rec.get("statement") or "").replace("\n", " ")
    return text[:width] + ("…" if len(text) > width else "")


# 生效条件：cg 与 args 就绪时按 args.cmd 分派——"list" 时 cg.review_list() 为空则打印空队列并返回 0、非空则逐条打印（tags 取真值拼接、layer/round 为假值显示 "?"/0）后返回 0；"rounds" 时打印 cg.review_rounds(args.pid) 并返回 0；"stats" 时打印 cg.review_stats() 的记录数/提案数/待审数/已关闭数与动作分布（含 noop 计数）并返回 0；"edit" 时以 args.content 加真值 args.tags（按逗号分割并剔除空项）/args.layer 组成 edits 调 cg.review_decide；其余 cmd（含 noop）以 getattr(args, "into", None) 与 args.reason 调 cg.review_decide；后两类再按 out.get("ok") 为真返回 0，否则打印 out 并返回 1。
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

    if args.cmd == "stats":
        st = cg.review_stats()
        by = st.get("by_decision") or {}
        print("裁决记录 %d 条 · 提案 %d 个 · 待审 %d 条 · 已关闭 %d 个" % (
            st.get("records", 0), st.get("proposals", 0),
            st.get("pending", 0), st.get("closed", 0)))
        print("  动作分布：%s" % ("、".join(
            "%s=%d" % (k, by[k]) for k in sorted(by)) or "（无记录）"))
        print("  其中 noop（已评估、判定无需改动）= %d 条" % st.get("noop", 0))
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


# 生效条件：argv 为 None（默认）时由 argparse 解析 sys.argv、否则解析传入的 argv（子命令 dest="cmd" 为 required，已注册 list/accept/reject/edit/merge/rounds 并带 --root 等参数），解析成功后构造 cg=_cg(args) 并返回 _execute(cg, args)，finally 中执行 cg.close()。
def main(argv=None):
    ap = argparse.ArgumentParser(description="灵枢审核队列裁决（designer 权限）")
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--root", help="存储根目录（默认环境变量 MDCG_ROOT）")
    common.add_argument("--session", default=None,
                        help="裁决会话 id（落盘归属 frontmatter.session；缺省取"
                             "环境变量 MDCG_SESSION，仍无则随机会话并 stderr 告警。"
                             "同一批裁决传同一值即得同一归属）")
    sub = ap.add_subparsers(dest="cmd", required=True)

    sub.add_parser("list", help="列出待审条目", parents=[common])
    sub.add_parser("stats", help="裁决动作统计（含 noop）", parents=[common])
    for name, help_ in (("accept", "按原样写入落盘"),
                        ("reject", "丢弃（只记裁决）"),
                        ("noop", "已评估、判定不改变现有记忆（只留痕）")):
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
