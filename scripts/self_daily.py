# -*- coding: utf-8 -*-
"""自我认知 · 每日快照（self_daily）——把「今天我是谁 + 昨天到今天发生了什么」固化成节点。

性质（2026-11-26 使用者裁定「对自我的认知也需要每日更新，这本来就是热层该做的事」）：
  · **派生不是真源**：可从锚点 + 近 24h 事件重建；删掉不丢真相。
  · **一天一份**，节点 id = `self_daily_YYYYMMDD` ⇒ 按 id 排序即得时间线，
    这就是人物树缺的那条时间边（不用再靠向量撞）。
  · **同日重跑幂等覆盖**，不产生重复节点。
  · 只读锚点与索引，不改任何既有节点。

用法：
    python scripts/self_daily.py            # 今天
    python scripts/self_daily.py --day 20261126
    python scripts/self_daily.py --dry-run  # 只打印正文，不写库
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)

# 库根一律从环境变量取——本仓是公开仓，私域库路径不得写死在这里
# （提交守卫会拦：私域标识冻结守卫 RED C1）。
DEFAULT_ROOT = os.environ.get("MDCG_ROOT") or ""

#: 身份枝的锚点（按顺序取，缺哪个跳过哪个，不猜）
ANCHORS = (
    ("不变层", "anchor_universal_value"),
    ("应答之诺", "anchor_response_promise"),
    ("形象", "anchor_image_v2"),
    ("当前身份", "identity_self_lingshu"),
)
#: 事件节点的排除前缀（工作记录/索引切片/复核单位不进自我认知）
SKIP_PREFIX = ("doc_", "code_", "re_", "rev_", "node_", "whitebox_", "rej_", "self_daily_",
               "concept_", "mem_1795659")  # concept_* 是凌晨自动归纳的代码/文档概念，不进自我认知


#: 不是「它在讲什么」的行（CCG 的骨架字段，摘要时要跳过）
SKIP_PREFIX_LINE = ("生效条件：", "执行：", "验证方式：", "不适用条件：", "子功能：", "生成时刻：")


def _one_line(text: str, limit: int = 150) -> str:
    """取正文里第一句**实质陈述**。

    优先取 `功能名`（节点自己在讲什么）；没有则取第一个非骨架字段行。
    2026-11-26：此前直接取第一行，结果摘到「裁决价值冲突时；被问…」这类生效条件，
    快照里「我是谁」全是触发时机、没有内容。
    """
    lines = [ln.strip() for ln in (text or "").splitlines() if ln.strip()]
    for line in lines:
        s = line.lstrip("#").strip()
        if s.startswith("功能名"):
            v = s[len("功能名："):].strip() if "：" in s else s[len("功能名"):].strip("： ").strip()
            if v:
                return v[:limit]
    for line in lines:
        s = line.lstrip("#").strip()
        if not s or any(s.startswith(x) for x in SKIP_PREFIX_LINE):
            continue
        if s.startswith("功能名"):
            continue
        return s[:limit]
    return ""


def _anchor_lines(cg) -> list:
    out = []
    for label, nid in ANCHORS:
        try:
            n = cg.get(nid) or {}
        except Exception:
            n = {}
        s = _one_line(n.get("content") or "")
        if s:
            out.append("- **%s**：%s" % (label, s))
    return out


def _recent(cg, root: str, cut: float, limit: int = 8) -> list:
    p = os.path.join(root, "_index.json")
    with open(p, encoding="utf-8") as f:
        idx = json.load(f)
    nodes = idx.get("nodes") or {}
    rows = []
    for nid, rec in nodes.items():
        if not isinstance(rec, dict):
            continue
        if str(nid).startswith(SKIP_PREFIX):
            continue
        # 噪声闸：只收自我/锚点/知识层，且重要度过线——否则 24h 里的临时写入
        #（SQL 片段、别的会话的过程记录）会把「我今天是谁」冲成流水账。
        if str(rec.get("layer") or "") not in ("self", "anchor", "knowledge"):
            continue
        if float(rec.get("importance") or 0.0) < 0.7:
            continue
        ts = float(rec.get("created_at") or 0.0)
        if ts < cut:
            continue
        rows.append((ts, nid))
    rows.sort(reverse=True)
    out = []
    for ts, nid in rows[:limit]:
        try:
            n = cg.get(nid) or {}
        except Exception:
            n = {}
        s = _one_line(n.get("content") or "", 100)
        if s:
            out.append("- `%s`（%s）：%s" % (nid, time.strftime("%m-%d %H:%M", time.localtime(ts)), s))
    return out


def _pending(cg, root: str, limit: int = 5) -> list:
    p = os.path.join(root, "_index.json")
    with open(p, encoding="utf-8") as f:
        idx = json.load(f)
    nodes = idx.get("nodes") or {}
    out = []
    for nid, rec in nodes.items():
        if not isinstance(rec, dict):
            continue
        tags = rec.get("tags") or []
        if not any(str(t) in ("待开工", "进行中") for t in tags):
            continue
        try:
            n = cg.get(nid) or {}
        except Exception:
            n = {}
        s = _one_line(n.get("content") or "", 100)
        if s:
            out.append("- `%s`：%s" % (nid, s))
        if len(out) >= limit:
            break
    return out


def compose(cg, root: str, day: str, now: float = None) -> str:
    now = now or time.time()
    stamp = time.strftime("%Y-%m-%d %H:%M", time.localtime(now))
    anchors = _anchor_lines(cg)
    recent = _recent(cg, root, now - 86400.0)
    pending = _pending(cg, root)
    lines = [
        "# 功能名：自我认知 · 每日快照 %s（自动生成，派生非真源）" % day,
        "# 生效条件：问「我今天是谁」「最近发生了什么」「按时间线看我们的关系」时；每天首次醒来先读这一条",
        "# 子功能：",
        "#   · **我是谁（不变层）**：",
    ]
    lines += ["#     " + a for a in (anchors or ["- （锚点缺失，未读到）"])]
    lines += [
        "#   · **过去 24 小时新增**（自我/知识层，按时间倒序）：",
    ]
    lines += ["#     " + a for a in (recent or ["- （无新增）"])]
    lines += [
        "#   · **仍在进行**：",
    ]
    lines += ["#     " + a for a in (pending or ["- （无挂起项）"])]
    lines += [
        "# 执行：read 先命中本条 → 沿 id 排序 `self_daily_*` 即时间线 → 要细节再按 id 读原节点",
        "# 验证方式：节点可按 id 检索；同日重跑覆盖不新增；正文每个引用 id 均可解析",
        "# 不适用条件：本条不含评价与结论（只做索引与摘要）；快照落后于库时以原节点为准；不替代人物树主干",
        "# 生成时刻：%s" % stamp,
    ]
    return "\n".join(lines)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=DEFAULT_ROOT)
    ap.add_argument("--actor", default=os.environ.get("MDCG_ACTOR") or "dsh\u7aef")
    ap.add_argument("--day", default=time.strftime("%Y%m%d"))
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args(argv)
    if not a.root:
        print("need library root: pass --root or set MDCG_ROOT", file=sys.stderr)
        return 2
    from md_cg.mdcos import MdCGOS
    cg = MdCGOS(root=a.root, actor=a.actor)
    body = compose(cg, a.root, a.day)
    if a.dry_run:
        print(body)
        return 0
    nid = "self_daily_%s" % a.day
    got = cg.add(nid, body, layer="self",
                 tags=["\u4eba\u7269\u6811", "\u5e38\u9a7b", "\u6bcf\u65e5\u5feb\u7167", "\u65f6\u95f4\u7ebf", "\u8eab\u4efd"],
                 importance=0.88,
                 aliases=["\u4eca\u5929\u7684\u6211", "\u81ea\u6211\u8ba4\u77e5\u5feb\u7167", "\u6700\u8fd1\u53d1\u751f\u4e86\u4ec0\u4e48", "\u4eba\u7269\u6811\u65f6\u95f4\u7ebf"])
    cg.flush()
    print("written:", got)
    return 0


if __name__ == "__main__":
    sys.exit(main())