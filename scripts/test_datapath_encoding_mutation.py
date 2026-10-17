# -*- coding: utf-8 -*-
"""scripts/test_datapath_encoding_mutation.py · issue #426-F 守卫的定点变异自证。

对 src/lib/datapath.ts 逐臂注入（回 readFileSync utf8 / 换 utf-16le 口径 / 撤 UTF-8 文案），
运行 test/datapath-encoding.test.ts，要求**指定用例恰好转红**；每臂字节级还原。
环境依赖：node_modules/tsx（npm ci）；缺失时打印 SKIP 行并退 0。
"""
import os
import re
import subprocess
import sys

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_SRC = os.path.join(_REPO, "src", "lib", "datapath.ts")
_TEST = "test/datapath-encoding.test.ts"
_GBK = "编码守卫 · GBK/ANSI paths.json"
_UTF8 = "编码守卫 · UTF-8 paths.json 正常读取"
_BOM = "编码守卫 · UTF-8 BOM paths.json 正常读取"
_BADJSON = "编码守卫 · 非法 JSON"

_DECODE_OK = "new TextDecoder('utf-8', { fatal: true }).decode(readFileSync(pf))"
_ARMS = {
    "M1": (_DECODE_OK, "readFileSync(pf, 'utf8')", {_GBK}),
    "M2": (_DECODE_OK, "new TextDecoder('utf-16le', { fatal: true }).decode(readFileSync(pf))", {_UTF8, _BOM}),
    "M3": ("不是 UTF-8 编码", "不是有效编码", {_GBK}),
}


def _run_test():
    r = subprocess.run(["node", "--import", "tsx", "--test", _TEST],
                       cwd=_REPO, capture_output=True, text=True,
                       encoding="utf-8", errors="replace", timeout=600)
    out = (r.stdout or "") + (r.stderr or "")
    names = set()
    for line in out.splitlines():
        m = re.match(r"^\s*✖\s+(.+?)\s+\(", line)
        if m:
            names.add(m.group(1).strip())
    return r.returncode, names, out


def main():
    if not os.path.isdir(os.path.join(_REPO, "node_modules", "tsx")):
        print("[SKIP] node_modules/tsx 不存在——先 npm ci（本件守卫需 tsx 运行 TS 测试）")
        return 0
    rc, names, out = _run_test()
    if rc != 0 or names:
        print("[FAIL] 基线（修复态）未全绿：rc=%s 红=%s" % (rc, sorted(names)))
        print(out[-1500:])
        return 1
    with open(_SRC, "rb") as fh:
        orig = fh.read()
    red = 0
    try:
        for mid, (old, new, expect) in sorted(_ARMS.items()):
            text = orig.decode("utf-8")
            nl = "\r\n" if "\r\n" in text else "\n"
            norm = text.replace("\r\n", "\n")
            if norm.count(old) != 1:
                print("[ANCHOR-MISS] %s：锚点命中 %d 次（期望 1）" % (mid, norm.count(old)))
                return 2
            with open(_SRC, "wb") as fh:
                fh.write(norm.replace(old, new).replace("\n", nl).encode("utf-8"))
            rc2, names2, out2 = _run_test()
            # 用例名做前缀匹配（node 输出可能带速度尾巴）
            got = set()
            for n in names2:
                for e in expect:
                    if n.startswith(e):
                        got.add(e)
            extra = {n for n in names2 if not any(n.startswith(e) for e in expect)}
            if rc2 != 0 and got == expect and not extra:
                print("[MUTATE-OK]   %s：指定用例转红 %s" % (mid, sorted(got)))
            else:
                print("[MUTATE-FAIL] %s：期望红 %s，实际红 %s（额外：%s，rc=%s）"
                      % (mid, sorted(expect), sorted(got), sorted(extra), rc2))
                red += 1
            with open(_SRC, "wb") as fh:
                fh.write(orig)
    finally:
        with open(_SRC, "wb") as fh:
            fh.write(orig)
    print("反证结果：%d 条变异，%s" % (len(_ARMS), "全部恰好命中" if red == 0 else "%d 条未命中" % red))
    return 1 if red else 0


if __name__ == "__main__":
    sys.exit(main())
