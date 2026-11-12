# -*- coding: utf-8 -*-
"""resconf.py —— 逐个冲突块裁决的工具（不是判据，只是把「选哪侧」写成机械动作）。

为什么不用 `git checkout --ours / --theirs`：那会把**整份文件**换成某一侧，
连 git 已经自动合并好的部分一起丢掉（本轮实测踩过：reconcile.py / self_state.py
被整份换成 ours，远端在同一文件里的非冲突改动一并消失）。正确做法是**只处理
冲突块**，块外的自动合并内容原样保留。

用法：
  python resconf.py <file> list             # 列冲突块（编号 + 两侧行数 + 首行摘要）
  python resconf.py <file> ours   [n ...]   # 第 n 块取本地（缺省=全部块）
  python resconf.py <file> theirs [n ...]   # 第 n 块取远端
  python resconf.py <file> both   [n ...]   # 两侧都留（先本地后远端）
"""
import io
import sys


def read(path):
    raw = io.open(path, "rb").read()
    crlf = raw.count(b"\r\n") > 0
    text = raw.decode("utf-8")
    return text.split("\r\n" if crlf else "\n"), crlf


def write(path, lines, crlf):
    io.open(path, "wb").write(("\r\n" if crlf else "\n").join(lines).encode("utf-8"))


def blocks(lines):
    out, i = [], 0
    while i < len(lines):
        if lines[i].startswith("<<<<<<<"):
            j = i + 1
            ours, theirs = [], []
            # diff3 形态：<<<<<<< ours / ||||||| base / ======= / theirs / >>>>>>>
            # base 段**必须跳过**，否则取 ours 会把 base 正文一起留在文件里
            # （本轮实测：insight/reconcile/self_state/eval_common 各残留一行标记）。
            while j < len(lines) and not lines[j].startswith(("|||||||", "=======")):
                ours.append(lines[j]); j += 1
            if j < len(lines) and lines[j].startswith("|||||||"):
                while j < len(lines) and not lines[j].startswith("======="):
                    j += 1
            j += 1
            while j < len(lines) and not lines[j].startswith(">>>>>>>"):
                theirs.append(lines[j]); j += 1
            out.append((i, j, ours, theirs))
            i = j + 1
        else:
            i += 1
    return out


def main():
    path, action = sys.argv[1], sys.argv[2]
    picks = [int(x) for x in sys.argv[3:]] or None
    lines, crlf = read(path)
    bs = blocks(lines)
    if action == "list":
        for k, (i, j, ours, theirs) in enumerate(bs, 1):
            o = ours[0].strip()[:70] if ours else "(空)"
            t = theirs[0].strip()[:70] if theirs else "(空)"
            print("[%d] 第 %d 行起 · ours %d 行 / theirs %d 行" % (k, i + 1, len(ours), len(theirs)))
            print("    ours  : " + o)
            print("    theirs: " + t)
        print("共 %d 块" % len(bs))
        return 0
    todo = picks or list(range(1, len(bs) + 1))
    for k in sorted(todo, reverse=True):
        i, j, ours, theirs = bs[k - 1]
        if action == "ours":
            new = ours
        elif action == "theirs":
            new = theirs
        elif action == "both":
            new = ours + theirs
        else:
            raise SystemExit("action 只能是 list/ours/theirs/both")
        lines[i:j + 1] = new
    write(path, lines, crlf)
    left = len(blocks(read(path)[0]))
    print("%s：处理 %d 块，剩余冲突块 %d" % (path, len(todo), left))
    return 0


if __name__ == "__main__":
    sys.exit(main())
