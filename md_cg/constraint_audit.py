# -*- coding: utf-8 -*-
"""约束对账（constraint_audit）——用**操作日志**核对约束，补 H7 的不可测。

为什么需要（2026-10-24 第四十六轮）：
    第二十四轮判定 H7「无工具」，因为文本检查器测不到行为。
    第四十六轮找到通道：**行为本身不可读，但操作留下的记录可读**——
    工具不在文本层，在日志层。

本模块做的是：拿一份约束清单 ＋ 一份操作日志（git log 或任意文本），
逐条看「这条约束在日志里有没有对应记录」。

**三条必须说清的边界**：

1. **「无记录」≠「没违反」**（I6 的另一面）
   日志只能证明「发生过」，不能证明「没发生」。
   所以本模块的结论是「有记录 / 无记录」，**不是「遵守 / 违反」**。

2. **匹配仍是词面**
   约束是自然语言，日志是提交信息——本模块用实词覆盖做近似匹配。
   所以它会漏掉「说法不同」的记录（第三十九、四十六轮已证：符号不被词频表示）。

3. **它不替你想该查什么**
   「这条约束对应查哪类日志」是语义判断（D_meta）；
   本模块只执行对账（D_task），不生成检查方法。

用一句话定位：
    **它把「让模型自查」换成「查记录」——查的是留痕，不是叙述。**

**第四条边界（2026-10-24 第四十八轮实测，最要紧的一条）**：

    **它的前提不是「有日志」，是「留痕率」。**

    实测：用本会话 5 条约束去对账 16 条 git 提交，**5/5 全部查不到**——
    而我明知自己违反了其中 2 条（覆盖文件、静默降级）。**漏检率 100%**。

    根因：那两次违反**从未提交**（覆盖后被 pre-commit 钩子挡住、随即 git checkout
    恢复；静默降级是瞬时缺陷，修了没单独提交）。**日志只记录「已提交」的行为。**

    所以本模块能验证的是「**留痕行为**的违反率」，不是「所有行为」。
    提升留痕率是前置条件（如「凡改必有提交」），而**对话中的判断永远不留痕**——
    那部分属于 D_meta，任何日志方案都覆盖不到。
"""

import re

__all__ = ["cross_check", "parse_constraints", "trace_gap", "MATCH_THRESHOLD"]

#: 约束与日志的实词覆盖阈值。低于此值视为「日志里没有对应记录」。
MATCH_THRESHOLD = 0.6

_CONSTRAINT_RE = re.compile(r"^[\s\-*•]*([C＃#]?\d{1,3})[\.、:：]?\s+(.+?)\s*$", re.M)


def parse_constraints(list_text):
    """解析约束清单（形如「C1 不得覆盖旧文件」）。"""
    out = []
    for m in _CONSTRAINT_RE.finditer(str(list_text or "")):
        cid, body = m.group(1), m.group(2).strip()
        if 2 <= len(body) <= 100:
            out.append({"id": cid if cid.upper().startswith("C") else "C" + cid.lstrip("C＃#"),
                        "text": body})
    return out


def _tokens(s):
    s = str(s or "")
    zh = re.findall(r"[\u4e00-\u9fa5]", s)
    bigrams = {"".join(zh[i:i + 2]) for i in range(len(zh) - 1)}
    words = {w.lower() for w in re.findall(r"[A-Za-z_]{2,}", s)}
    return bigrams | words


def cross_check(constraints, log_text, threshold=MATCH_THRESHOLD):
    """逐条对账。

    参数：
        constraints  清单文本或 [{id,text}]
        log_text     操作日志正文（git log 输出或任意文本）
        threshold    实词覆盖阈值

    返回 dict：
        checked    [{id,text,cover,evidence}]  日志里有对应记录
        unchecked  [{id,text,cover}]           日志里没找到（**不等于没违反**）
        ok         True=全部有记录；False=有未找到的；None=无法判定（无清单/无日志）
        note       边界提示
    """
    items = constraints
    if isinstance(items, str):
        items = parse_constraints(items)
    items = [it for it in (items or []) if it and it.get("text")]
    log = str(log_text or "")

    if not items:
        return {"ok": None, "checked": [], "unchecked": [],
                "reason": "没有可对账的约束"}
    if not log.strip():
        return {"ok": None, "checked": [], "unchecked": [],
                "reason": "日志为空，无从对账"}

    log_tokens = _tokens(log)
    log_lines = [ln for ln in log.splitlines() if ln.strip()]
    checked, unchecked = [], []
    for it in items:
        ct = _tokens(it["text"])
        if not ct:
            unchecked.append({"id": it.get("id", ""), "text": it["text"], "cover": 0.0})
            continue
        cover = len(ct & log_tokens) / float(len(ct))
        row = {"id": it.get("id", ""), "text": it["text"], "cover": round(cover, 3)}
        if cover >= threshold:
            # 找最相关的那一行作为证据
            best, best_c = "", 0.0
            for ln in log_lines:
                lt = _tokens(ln)
                if not lt:
                    continue
                c = len(ct & lt) / float(len(ct))
                if c > best_c:
                    best, best_c = ln.strip()[:90], c
            row["evidence"] = best
            checked.append(row)
        else:
            unchecked.append(row)

    return {
        "ok": not unchecked,
        "checked": checked,
        "unchecked": unchecked,
        "counts": {"total": len(items), "checked": len(checked),
                   "unchecked": len(unchecked)},
        "note": "「无记录」**不等于**「没违反」（I6）：日志只能证明发生过，不能证明没发生。"
                "本结论是「有记录/无记录」，不是「遵守/违反」。",
    }


def trace_gap(repo=None, paths=None):
    """留痕缺口检查——找出「有行为但没留痕」的改动。

    为什么需要（2026-10-24 第四十八轮）：H7 首次实测漏检率 100%，
    根因是违反从未提交、故日志无痕。**先能查出「没留痕的改动」，
    才谈得上用日志验证行为。**

    做法：跑 git status，把未提交的改动列出来——它们就是「尚未留痕的行为」。

    返回 dict：
        ok          True=工作区干净（当前改动都已留痕）；False=有未留痕改动
        untracked   未跟踪文件（新文件，行为没进历史）
        modified    已修改未提交
        staged      已暂存未提交
        note        边界提示

    注意 ok=False **不等于违反约束**——只是「这些改动还没进历史」，
    提交后就留痕了。它是**前置检查**，不是违规判定。
    """
    import os
    import subprocess
    root = str(repo or os.getcwd())
    try:
        env = dict(os.environ)
        env.setdefault("PYTHONUTF8", "1")
        r = subprocess.run(["git", "status", "--porcelain"],
                           capture_output=True, text=True, encoding="utf-8",
                           errors="replace", env=env, cwd=root, shell=False)
    except Exception as exc:                       # noqa: BLE001
        return {"ok": None, "reason": "无法执行 git status：%s" % str(exc)[:80]}
    if r.returncode != 0:
        return {"ok": None, "reason": "git status 返回 %d" % r.returncode}

    untracked, modified, staged = [], [], []
    for line in (r.stdout or "").splitlines():
        if not line.strip():
            continue
        code, _, path = line[:2], line[2:3], line[3:].strip()
        if paths and not any(pp in path for pp in paths):
            continue
        if code.strip() == "??":
            untracked.append(path)
        elif code[0] not in (" ", "?"):
            staged.append(path)
        else:
            modified.append(path)

    total = len(untracked) + len(modified) + len(staged)
    return {
        "ok": total == 0,
        "untracked": untracked,
        "modified": modified,
        "staged": staged,
        "counts": {"untracked": len(untracked), "modified": len(modified),
                   "staged": len(staged), "total": total},
        "note": "ok=False 只表示「这些改动尚未进历史」，**不等于违反约束**——"
                "提交即留痕。本函数是 H7 的**前置检查**，不是违规判定。",
    }


def main(argv=None):
    """CLI：python -m md_cg.constraint_audit <清单文件> <日志文件> [--json]"""
    import json
    import sys
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    argv = list(sys.argv[1:] if argv is None else argv)
    if len(argv) < 2:
        print("用法：python -m md_cg.constraint_audit <清单文件> <日志文件> [--json]")
        return 2
    try:
        with open(argv[0], encoding="utf-8", errors="replace") as fh:
            lst = fh.read()
        with open(argv[1], encoding="utf-8", errors="replace") as fh:
            log = fh.read()
    except OSError as exc:
        print("读文件失败：%s" % exc, file=sys.stderr)
        return 2
    rep = cross_check(lst, log)
    if "--json" in argv:
        print(json.dumps(rep, ensure_ascii=False, indent=1))
    else:
        c = rep.get("counts", {})
        print("约束 %d 条：有记录 %d，无记录 %d"
              % (c.get("total", 0), c.get("checked", 0), c.get("unchecked", 0)))
        for u in rep.get("unchecked", []):
            print("  [无记录] %s %s（覆盖 %.0f%%）" % (u["id"], u["text"], u["cover"] * 100))
        print("")
        print("注：%s" % rep["note"])
    return 0 if rep.get("ok") is not False else 1


if __name__ == "__main__":
    raise SystemExit(main())
