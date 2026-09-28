# -*- coding: utf-8 -*-
"""真源索引契约层守卫（P0）：通用层覆盖任意文件 / 细化层仅可读文本 / 伴随文本挂通用层 / 回读逐字节。

判据姿态（P0 两次踩坑的产物，勿简化回「猜粒度」）：
  · **不猜提取器粒度**：细化层单位数与 `docindex.extract` 条数**平权**（units == extract + 1），
    H1 节合并、过短节并入等语义归提取器，本层只保证「它切几节我就几条」；
  · **哈希单一实现**：行区间哈希委托 `codeindex.region_hash`（sha1 前 12 位）；本模块自写第二份
    的行为已被 5b/5c 抓出并删除——两处算法会让漂移检测永远 hash_match=True；
  · **伴随文本挂通用层**：媒体不进可读文本分支，挂错层等于废掉多模态语义通道（6b 抓出）。

实验纪律：全程 `tempfile` 临时目录 + 合成件（含**假魔数**的合成二进制，绝不用真实媒体/私有数据）；
不写任何库面、不碰在役库、不出网。运行：退出码 0 = 全绿。
"""
from __future__ import annotations

import io
import os
import shutil
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from md_cg import codeindex                 # noqa: E402
from md_cg import docindex                  # noqa: E402
from md_cg import srcindex as S             # noqa: E402

PASS = FAIL = 0
FAILS = []


def ck(cid: str, ok: bool, detail: str = "") -> None:
    global PASS, FAIL
    if ok:
        PASS += 1
    else:
        FAIL += 1
        FAILS.append("%s %s" % (cid, detail))
    print("  %s %s%s" % ("OK  " if ok else "FAIL", cid, "" if ok else "  " + detail))


def w(path: str, data) -> str:
    if isinstance(data, bytes):
        with open(path, "wb") as f:
            f.write(data)
    else:
        with open(path, "w", encoding="utf-8") as f:
            f.write(data)
    return path


DOC = "\n".join([
    "# 合成文档标题", "", "这是一段引言。", "",
    "## 小节一", "", "小节一的正文，足够长以通过提取器的最小长度判断。", "",
    "## 小节二", "", "小节二的正文，同样足够长，并带一行说明。", "",
    "## 小节三", "", "小节三的正文。",
])
CCG = "\n".join([
    "# 功能名：合成样例", "# 生效条件：仅用于 P0 契约层守卫；合成件、非真实数据",
    "## 小节一", "正文一",
])


def main() -> int:
    tmp = tempfile.mkdtemp(prefix="p0_srcindex_")
    try:
        md = w(os.path.join(tmp, "说明.md"), DOC)
        ccg = w(os.path.join(tmp, "带条件.md"), CCG)
        png = w(os.path.join(tmp, "pic.png"), b"\x89PNG\r\n\x1a\n" + b"\x00\x01\x02" * 40)
        w(os.path.join(tmp, "pic.md"), "# pic 简介\n\n这是伴随文本（sidecar）")
        mp4 = w(os.path.join(tmp, "clip.mp4"), b"\x00\x00\x00\x18ftypmp42" + b"\x00" * 64)
        raw = w(os.path.join(tmp, "blob.dat"), bytes(range(256)) * 4)
        weird = w(os.path.join(tmp, "t.txt"), b"abc\x00def")            # NUL ⇒ 不可读
        fake = w(os.path.join(tmp, "disguised.txt"), b"\x89PNG\r\n\x1a\n" + b"\x00" * 16)
        empty = w(os.path.join(tmp, "empty.md"), "")

        # ① 通用层：任意文件都有 ≥1 条 whole 单位（含空文件/不可读二进制）
        for label, p in (("md", md), ("png", png), ("mp4", mp4), ("raw", raw),
                         ("nul", weird), ("empty", empty)):
            us = S.units(p)
            ck("1a[%s] 通用层恒在" % label,
               bool(us) and us[0]["span"]["unit"] == "whole" and bool(us[0]["span_hash"]),
               "units=%d" % len(us))

        # ② 细化层：与 docindex.extract 平权（不猜粒度）
        for label, p in (("md", md), ("ccg", ccg)):
            text = io.open(p, encoding="utf-8").read()
            want = len(docindex.extract(text, path=p)) + 1
            got = len(S.units(p))
            ck("2a[%s] 单位数 == extract+1" % label, got == want, "units=%d want=%d" % (got, want))
        ck("2b[png] 无细化层", all(u["span"]["unit"] == "whole" for u in S.units(png)))
        ck("2c[NUL 文本] 判不可读、不细化",
           all(u["span"]["unit"] == "whole" for u in S.units(weird)))
        ck("2d[空文件] 不细化且不抛", len(S.units(empty)) == 1)

        # ③ 类型判据：魔数优先于扩展名；未知类型不拒
        ck("3a[魔数优先] .txt 内容为 PNG ⇒ image/png",
           S.sniff_type(fake) == "image/png", S.sniff_type(fake))
        ck("3b[扩展名兜底] .md ⇒ text/markdown", S.sniff_type(md) == "text/markdown")
        ck("3c[未知不拒] .dat ⇒ octet-stream",
           S.sniff_type(raw) == "application/octet-stream", S.sniff_type(raw))

        # ④ 哈希判别力：改 1 字节 ⇒ file_hash 变；旧单位回读 hash_match=False
        u0 = S.units(md)[0]
        h0 = u0["src"]["file_hash"]
        w(md, DOC.replace("这是一段引言。", "这是一段引言！"))
        u1 = S.units(md)[0]
        ck("4a[1 字节改判] file_hash 变", h0 != u1["src"]["file_hash"])
        ck("4b[陈旧检出] 旧单位回读 hash_match=False",
           S.read_unit(u0).get("hash_match") is False)
        ck("4c[新鲜一致] 新单位回读 hash_match=True",
           S.read_unit(u1).get("hash_match") is True)

        # ⑤ 行区间回读逐字节 + 与 codeindex.region_hash 单一实现
        lu = [u for u in S.units(md) if u["span"]["unit"] == "line"][0]
        got = S.read_unit(lu)
        lines = io.open(md, encoding="utf-8").read().split("\n")
        want_text = "\n".join(lines[lu["span"]["start"] - 1:lu["span"]["end"]])
        ck("5a[区间逐字节]", got.get("text") == want_text, repr(got.get("text"))[:60])
        ck("5b[区间哈希一致]", got.get("hash_match") is True)
        ck("5c[哈希单一实现] 委托 codeindex.region_hash",
           codeindex.region_hash(lines, lu["span"]["start"], lu["span"]["end"])
           == S.region_hash("\n".join(lines), lu["span"]["start"], lu["span"]["end"])
           == got["hash"])

        # ⑥ 伴随文本挂**通用层**（媒体条目的语义通道）
        comps = S.companions(png)
        u_png = S.units(png)[0]
        ck("6a[sidecar 发现]", any(c["kind"] == "sidecar" for c in comps),
           str([c["name"] for c in comps]))
        ck("6b[挂进通用层] media 条目 text_view 含伴随文本且带 companions",
           "伴随文本" in u_png["text_view"] and bool(u_png.get("companions")))

        # ⑦ 未实现 locator 必须显式不静默
        bad = S.read_unit({"src": {"path": md}, "span": {"unit": "time", "t0": 0, "t1": 1}})
        ck("7a[time 显式不支持]", bad.get("ok") is False and "time" in bad.get("error", ""),
           str(bad)[:80])

        # ⑧ CCG 条件面进入细化层（且与该文件的 CCG 行相关）
        ccg_units = S.units(ccg)
        ck("8a[条件面非空]", any(u.get("condition_space") for u in ccg_units),
           str([bool(u.get("condition_space")) for u in ccg_units]))
        ck("8b[CCG 行落在细化层]",
           any("生效条件" in (u.get("text_view") or "") or
               "生效条件" in str(u.get("condition_space"))
               for u in ccg_units if u["span"]["unit"] == "line"),
           str([u.get("text_view") for u in ccg_units if u["span"]["unit"] == "line"])[:90])

        # ⑨ 能力自陈与实现一致（契约漂移守卫）
        cap = S.capability()
        ck("9a[units 自陈]", tuple(cap["units"]) == S.UNITS == ("whole", "line"))
        ck("9b[未实现项自陈]", set(cap["not_implemented"]) == {"time", "region", "byte"})
        ck("9c[零依赖/不写状态]", cap["deps"] == [] and cap["writes_state"] is False)

        # ⑩ 不存在路径：fail-closed 抛，而不是静默造条目
        try:
            S.units(os.path.join(tmp, "不存在.bin"))
            ck("10a[不存在 fail-closed]", False, "未抛")
        except OSError:
            ck("10a[不存在 fail-closed]", True)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    print("\n结果：PASS %d / FAIL %d" % (PASS, FAIL))
    if FAILS:
        print("失败项：" + "；".join(FAILS))
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
