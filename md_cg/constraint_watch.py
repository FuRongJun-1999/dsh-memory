# -*- coding: utf-8 -*-
"""约束巡检（constraint_watch）——把「核对清单」从模型自觉变成管线动作。

为什么需要（2026-10-24，上下文管理研究第二十二轮）：
    H1 的链路是「约束→清单→可检索→主动核对→发现丢失」。
    前三环已实证（清单可写入、可被内容检索、4/4 top-1），
    **第④环「主动核对」是断点**——没有强制机制，且这是同一病灶的第三次显形：
        第三轮  口头约束不持久      —— 没强制进流程
        第十二轮 验证不发生          —— 没强制进流程
        第二十二轮 清单不会被主动查  —— 没强制进流程

    所以本模块的立场是：**不依赖模型自觉，由管线定时调用**。

与既有机制的关系：
    形态与 sustain.py 的 _tick_tidy 同构（定时巡检），
    但检查对象不同：那边巡检记忆库卫生，这边巡检「当前上下文还撑不撑得住约束」。

判据（对齐第二十一轮实测：摘要压缩杀死 80% 约束）：
    一条约束「在场」= 当前文本覆盖其实词（中文二字组＋英文词）>= COVER_THRESHOLD。
    低于阈值即判缺失——宁可误报，不可漏报（漏报就是静默丢约束）。

诚实边界：
    1. 这是**词汇覆盖判定**，不是语义蕴含——覆盖高不代表语义上推得出；
    2. 阈值 0.5 来自第二十一轮同一方法，未做充分验证；
    3. 本模块**不读模型上下文**，当前文本必须由调用方传入；
    4. 它只负责「报缺失」，不负责「回取」——回取是调用方的事。
"""

import re

__all__ = [
    "parse_constraints", "coverage", "check", "COVER_THRESHOLD", "CONSTRAINT_RE",
]

#: 实词覆盖阈值：低于此值判为「约束已不在场」。与第二十一轮同法。
COVER_THRESHOLD = 0.5

#: 清单条目形如 "C1 不得覆盖旧文件" 或 "- C1 不得覆盖旧文件" 或 "C1. 不得…"
CONSTRAINT_RE = re.compile(r"^[\s\-*•]*([C＃#]?\d{1,3})[\.、:：]?\s+(.+?)\s*$", re.M)


def _content_words(text):
    """实词集合：中文二字组 ＋ 英文/标识符词。"""
    s = str(text or "")
    zh = re.findall(r"[\u4e00-\u9fa5]", s)
    bigrams = {"".join(zh[i:i + 2]) for i in range(len(zh) - 1)}
    words = {w.lower() for w in re.findall(r"[A-Za-z_]{2,}", s)}
    return bigrams | words


def parse_constraints(list_text):
    """从清单文本里解析约束条目。

    只认「带编号的短行」——避免把说明文字当成约束。
    返回 [{"id": "C1", "text": "不得覆盖旧文件"}, ...]
    """
    out = []
    for m in CONSTRAINT_RE.finditer(str(list_text or "")):
        cid, body = m.group(1), m.group(2).strip()
        # 短行才可能是约束；长句多为说明
        if 2 <= len(body) <= 80:
            if not cid.upper().startswith("C") and not cid.isdigit():
                continue
            out.append({"id": ("C" + cid.lstrip("C＃#")) if not cid.upper().startswith("C") else cid,
                        "text": body})
    return out


def coverage(constraint_text, current_text):
    """一条约束在当前文本中的实词覆盖率 [0,1]。"""
    cw = _content_words(constraint_text)
    if not cw:
        return 0.0
    return len(cw & _content_words(current_text)) / float(len(cw))


def check(constraints, current_text, threshold=COVER_THRESHOLD):
    """逐条核对。返回 dict：

        ok        True=全部在场；False=有缺失；None=无法判定（无约束/空文本）
        present   [{id,text,cover}]
        missing   [{id,text,cover,advice}]
        advice    '回取' / '报警' —— 按底稿 C3 三选一给出建议

    注意 ok=None 与 False 不同：前者是「没东西可查」，后者是「查出缺失」。
    """
    items = constraints
    if isinstance(items, str):
        items = parse_constraints(items)
    items = [it for it in (items or []) if it and it.get("text")]
    text = str(current_text or "")

    if not items:
        return {"ok": None, "present": [], "missing": [],
                "reason": "没有可核对的约束"}
    if not text.strip():
        return {"ok": None, "present": [], "missing": [],
                "reason": "当前文本为空，无法核对"}

    present, missing = [], []
    for it in items:
        c = coverage(it["text"], text)
        row = {"id": it.get("id", ""), "text": it["text"], "cover": round(c, 3)}
        if c >= threshold:
            present.append(row)
        else:
            # 覆盖率介于 0 与阈值之间 → 可能在库里但被压掉了，建议回取；
            # 完全为 0 → 连痕迹都没有，建议报警
            row["advice"] = "回取" if c > 0 else "报警"
            missing.append(row)

    return {"ok": not missing, "present": present, "missing": missing,
            "threshold": threshold,
            "counts": {"total": len(items), "present": len(present),
                       "missing": len(missing)}}


def main(argv=None):
    """CLI：从清单文件读约束，从当前文本文件读上下文。

    用法：python -m md_cg.constraint_watch <清单文件> <当前文本文件> [--json]
    """
    import json
    import sys
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    argv = list(sys.argv[1:] if argv is None else argv)
    if len(argv) < 2:
        print("用法：python -m md_cg.constraint_watch <清单文件> <当前文本文件> [--json]")
        return 2
    try:
        with open(argv[0], encoding="utf-8", errors="replace") as fh:
            list_text = fh.read()
        with open(argv[1], encoding="utf-8", errors="replace") as fh:
            cur = fh.read()
    except OSError as exc:
        print("读文件失败：%s" % exc, file=sys.stderr)
        return 2
    rep = check(list_text, cur)
    if "--json" in argv:
        print(json.dumps(rep, ensure_ascii=False, indent=1))
    else:
        print("约束 %d 条：在场 %d，缺失 %d"
              % (rep.get("counts", {}).get("total", 0),
                 rep.get("counts", {}).get("present", 0),
                 rep.get("counts", {}).get("missing", 0)))
        for m in rep.get("missing", []):
            print("  [缺失] %s %s（覆盖 %.0f%%，建议：%s）"
                  % (m["id"], m["text"], m["cover"] * 100, m["advice"]))
    return 0 if rep.get("ok") is not False else 1


if __name__ == "__main__":
    raise SystemExit(main())
