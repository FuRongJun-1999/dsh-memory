# -*- coding: utf-8 -*-
"""triage.py —— 把 diff3 形态的冲突块自动分类，只对「能机械判定」的块动手。

为什么这么做：`git checkout --ours/--theirs` 会整份丢改动；逐块手看 148 个文件
不现实。diff3 冲突标记里有 **base** 段，于是每个块都能回答一个问题：
「这一块到底是谁改的？」三种可机械判定的情形：

  ours == base            ⇒ 只有远端改了 ⇒ 取 theirs（不丢任何人的改动）
  theirs == base          ⇒ 只有本地改了 ⇒ 取 ours
  两侧都改且完全相同        ⇒ 取任一侧
  其余（两侧都改且不同）    ⇒ **留给人工**（脚本不动，保持冲突标记）

用法：
  python triage.py <file> [--apply]
  不带 --apply 只打印分类结果；带 --apply 才真的改文件（只改前三种情形）。
"""
import io
import sys


def read(path):
    raw = io.open(path, "rb").read()
    crlf = raw.count(b"\r\n") > 0
    return raw.decode("utf-8").split("\r\n" if crlf else "\n"), crlf


def write(path, lines, crlf):
    io.open(path, "wb").write(("\r\n" if crlf else "\n").join(lines).encode("utf-8"))


def blocks(lines):
    """返回 [(start, end, ours, base, theirs)]，要求 diff3 形态（含 ||||||| 段）。"""
    out, i, n = [], 0, len(lines)
    while i < n:
        if lines[i].startswith("<<<<<<<"):
            j = i + 1
            ours = []
            while j < n and not lines[j].startswith("|||||||"):
                ours.append(lines[j]); j += 1
            base = []
            if j < n:
                j += 1
                while j < n and not lines[j].startswith("======="):
                    base.append(lines[j]); j += 1
            theirs = []
            if j < n:
                j += 1
                while j < n and not lines[j].startswith(">>>>>>>"):
                    theirs.append(lines[j]); j += 1
            out.append((i, j, ours, base, theirs))
            i = j + 1
        else:
            i += 1
    return out


def classify(ours, base, theirs):
    if ours == theirs:
        return "same"
    if ours == base:
        return "theirs"
    if theirs == base:
        return "ours"
    return "manual"


def main():
    path = sys.argv[1]
    apply_ = "--apply" in sys.argv
    lines, crlf = read(path)
    bs = blocks(lines)
    if not bs:
        print("%s：无 diff3 冲突块（可能是 ours/theirs 形态或已解决）" % path)
        return 0
    stats = {"same": 0, "ours": 0, "theirs": 0, "manual": 0}
    for k, (i, j, ours, base, theirs) in enumerate(bs, 1):
        kind = classify(ours, base, theirs)
        stats[kind] += 1
        if kind == "manual":
            o = ours[0].strip()[:60] if ours else "(空)"
            t = theirs[0].strip()[:60] if theirs else "(空)"
            print("  [%d] 人工 · ours %d 行 / theirs %d 行" % (k, len(ours), len(theirs)))
            print("        ours  : " + o)
            print("        theirs: " + t)
    print("%s：共 %d 块 → ours %d / theirs %d / same %d / manual %d"
          % (path, len(bs), stats["ours"], stats["theirs"], stats["same"], stats["manual"]))
    if apply_ and stats["manual"] < len(bs):
        new = []
        for (i, j, ours, base, theirs) in reversed(bs):
            kind = classify(ours, base, theirs)
            if kind in ("same", "ours"):
                lines[i:j + 1] = ours
            elif kind == "theirs":
                lines[i:j + 1] = theirs
        write(path, lines, crlf)
        left = len(blocks(read(path)[0]))
        print("  → 已应用机械裁决，剩余冲突块 %d" % left)
    return 0


if __name__ == "__main__":
    sys.exit(main())
