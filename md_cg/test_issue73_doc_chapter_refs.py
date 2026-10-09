# -*- coding: utf-8 -*-
"""issue #73 守卫：文档章节号引用不得「无出处」，幻影判定须有真源对拍（反退化守卫）。

## 为什么有这个守卫
issue #73 报的是 `md_cg/weights.py` 里的「§4.3」——本仓两份候选真源的编号体系不同：
  · `docs/theory/智能的公理化基石.md`：**中文序号**（`## 十、信任：对协作者行为的概率估计`），
    全文无 `§4.3` / `§3.2` / `§4.2` / `§5.1` 这类阿拉伯章号；
  · `docs/swarm/蜂群互联_v0.1.md`：**阿拉伯数字章号**，`### 3.2 层1 · 连接层` /
    `### 4.2 隐式学习` / `### 4.3 信任连接` / `### 5.1 五步` 四节俱在。
故代码里孤立出现的 `§4.3` 究竟指哪份文档，**只能靠文档名判**——只写「（文档 §4.3）」
会被读成「引用上文那份（theory）文档」的幻影号。本守卫钉住三件事：
  ① 两文件**必须正向点名**真源文档（不许只有裸章号）；
  ② 引用的章号**必须是真章节**，且被引的**内容确实落在该章区间内**（引文对拍，
     这是「不是幻影」的机械证明，而不是只断言字符串存在）；
  ③ `links.py` 的 `clause="…"` 是**运行期数据字段**（写入 `_links.json` 的 audit 记录），
     其字面量不得有第二处消费者/断言钉住旧值（本守卫自扫，排除自身）。

## 断言面读**盘上文件**（`io.open`），不用 `inspect.getsource`
变异注入的是「退化文本」（内存），若断言走 `inspect.getsource` 会读到变异体、
失去「盘上产物是否真的修好」的判别力。故断言只经 `_READ["fn"]` 读盘。

运行：
  python -X utf8 -m md_cg.test_issue73_doc_chapter_refs            # 正向
  python -X utf8 -m md_cg.test_issue73_doc_chapter_refs --mutate A # 族退化注入自证

退出码（fail-closed）：
  0 = 正向全绿 / 变异逐条**恰好**命中期望红项；1 = 有断言失败 / 变异未按预期转红 /
  基线非 0 红；2 = ANCHOR-MISS（变异锚点在盘上文件命中数 ≠1，实现已漂移，须硬失败）。

隔离：本守卫**只读**，绝不写盘（变异是内存替换读取器）。
"""
from __future__ import annotations

import contextlib
import io
import os
import re
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SELF_REL = "md_cg/" + os.path.basename(os.path.abspath(__file__))

WEIGHTS = "md_cg/weights.py"
LINKS = "md_cg/links.py"
THEORY = "docs/theory/智能的公理化基石.md"          # 中文序号真源
SWARM = "docs/swarm/蜂群互联_v0.1.md"               # 阿拉伯章号真源

PASS = 0
FAIL = 0
FAILS = []


def ok(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print("  [PASS] " + name + ("  · " + detail if detail else ""))
    else:
        FAIL += 1
        FAILS.append(name)
        print("  [FAIL] " + name + ("  · " + detail if detail else ""))


def _disk_read(rel):
    """盘上真值读取（唯一 IO 原语）。"""
    with io.open(os.path.join(ROOT, rel.replace("/", os.sep)), encoding="utf-8") as f:
        return f.read()


#: 变异注入点：替换读取器（内存，不落盘）。
_READ = {"fn": _disk_read}


def src(rel):
    return _READ["fn"](rel)


def _section(text, start_marker, end_marker):
    """取 [start_marker, end_marker) 区间文本；起点缺失返回空串。"""
    i = text.find(start_marker)
    if i < 0:
        return ""
    j = text.find(end_marker, i + 1)
    return text[i:] if j < 0 else text[i:j]


#: 引文形态：`蜂群互联 §4.3：「…」`——引号内的字必须是真源里的**逐字**文本（#73 的引文保真面）。
_QUOTE_RE = re.compile(r"蜂群互联 §4\.3：「([^」]+)」")


def _quotes(text):
    return _QUOTE_RE.findall(text)


def _verbatim_missing(quotes, source_section):
    """引号内文本未在真源区间逐字出现者（空 = 全部逐字可查）。"""
    return [q for q in quotes if q not in source_section]


# ------------------------------------------------------------------ 正向断言
def group_weights():
    """weights.py 面（A 组）。"""
    w = src(WEIGHTS)
    ok("A1 weights.py 不再含「该文档…无 §4.3」的幻影否定（假否定会误导全文件）",
       "无 §4.3" not in w)
    ok("A2 weights.py 正向点名真源文档（docs/swarm/蜂群互联_v0.1.md）", SWARM in w)
    ok("A3 weights.py 的 §4.3 指针带文档名（不再裸「文档 §4.3」）",
       "文档 §4.3" not in w and "蜂群互联 §4.3" in w,
       "裸号命中=" + str("文档 §4.3" in w))
    th = src(THEORY)
    ok("A4 真源①（theory）确为中文序号：有「## 十、信任」且无「## 4.」类阿拉伯章",
       "## 十、信任" in th and "## 4." not in th)
    sw = src(SWARM)
    ok("A5 真源②（swarm）确有 §3.2/§4.2/§4.3/§5.1 四节真标题（「幻影」判定被反证）",
       all(h in sw for h in ("### 3.2 层1 · 连接层", "### 4.2 隐式学习",
                             "### 4.3 信任连接", "### 5.1 五步")))
    s43 = _section(sw, "### 4.3 信任连接", "## 5. 接入握手")
    ok("A6 引文对拍：swarm §4.3 区间含三分量合成式（weights.py 的出处声明为真）",
       "P_trust(B) = f( 一致性, 位置可预测性, 版本对齐度 )" in s43)
    ok("A7 引文对拍（逐字）：weights.py 的 §4.3 引号内文本能在真源 §4.3 逐字找到",
       bool(_quotes(w)) and not _verbatim_missing(_quotes(w), s43),
       "引文=" + str(_quotes(w)))
    ok("A8 weights.py 无「无源 v0.1」引文（真源无「v0.1 只声明结构」这一串）",
       "v0.1 只声明结构" not in w)
    wl = w.splitlines()
    fi = next((k for k, x in enumerate(wl) if x.strip().startswith("P_trust = f(")), None)
    ok("A9 weights.py 合成式的冒号挂在 swarm §4.3 行（不在 §十 名下、不前后打脸）",
       fi is not None and fi > 1 and SWARM in wl[fi - 1]
       and wl[fi - 1].rstrip().endswith("：") and not wl[fi - 2].rstrip().endswith("："),
       ("公式前一行=" + repr(wl[fi - 1][:64])) if fi else "未找到合成式行")


def group_links():
    """links.py 面（B 组）。"""
    l = src(LINKS)
    ok("B1 links.py 无裸「（文档 §」前缀（章号一律带文档名）", "（文档 §" not in l)
    ok("B2 links.py 正向点名真源文档（docs/swarm/蜂群互联_v0.1.md）", SWARM in l)
    ok("B3 links.py 四个真章节号仍在场（正向：不许靠「删干净」过关）",
       all(x in l for x in ("§3.2", "§4.2", "§4.3", "§5.1")))
    sw = src(SWARM)
    s32 = _section(sw, "### 3.2 层1 · 连接层", "#### 3.2.1")
    ok("B4 引文对拍：§3.2 含「长时间无观测则向初值回归」（decay 的 clause 依据）",
       "长时间无观测则向初值回归" in s32)
    s42 = _section(sw, "### 4.2 隐式学习", "### 4.3 信任连接")
    ok("B5 引文对拍：§4.2 含「跨节点时主体 id 需全局唯一」", "主体 id 需全局唯一" in s42)
    s43 = _section(sw, "### 4.3 信任连接", "## 5. 接入握手")
    ok("B7 引文对拍：§4.3 含「只声明结构，不宣称权重数值」（诚实边界引文出处）",
       "只声明结构，不宣称权重数值" in s43)
    s51 = _section(sw, "### 5.1 五步", "### 5.2 状态机")
    ok("B6 引文对拍：§5.1 五步表 ①–⑤ 齐（声明/校验/建档/观察期/转正）",
       all(c in s51 for c in "①②③④⑤")
       and all(k in s51 for k in ("声明", "校验", "建档", "观察期", "转正")))
    old = 'clause="§3.2（无观测向初值回归）"'
    new = 'clause="蜂群互联 §3.2（无观测向初值回归）"'
    hits = []
    for rel in _tracked_py():
        if rel == SELF_REL:
            continue
        try:
            if old in src(rel):
                hits.append(rel)
        except OSError:
            continue
    ok("B8 clause 旧字面量无第二处消费者/断言钉住（且新字面量在场）",
       not hits and new in l, "旧串仍在=" + str(hits))
    ok("B9 引文对拍（逐字）：links.py 的 §4.3 引号内文本能在真源 §4.3 逐字找到",
       bool(_quotes(l)) and not _verbatim_missing(_quotes(l), s43),
       "引文=" + str(_quotes(l)))
    ok("B10 links.py 无「无源 v0.1」引文", "v0.1 只声明结构" not in l)


def _tracked_py():
    env = dict(os.environ, PYTHONUTF8="1")
    p = subprocess.run(["git", "ls-files", "*.py"], cwd=ROOT, capture_output=True,
                       text=True, encoding="utf-8", errors="replace", shell=False, env=env)
    return [x for x in p.stdout.splitlines() if x.strip()]


# ------------------------------------------------------- 族退化注入（--mutate A）
#: 每项 = (新形态锚点, 退化形态)；锚点在盘上文件里须恰好命中 1 次（ANCHOR-MISS 判据）。
_DEG_LINKS = [
    ("真源：`docs/swarm/蜂群互联_v0.1.md`（该文档用阿拉伯数字章节号；下文「蜂群互联 §x」均指它）。"
     "\n\n四条不可动摇的性质（蜂群互联 §3.2 / §4.3）：",
     "四条不可动摇的性质（文档 §3.2 / §4.3）："),
    ("（蜂群互联 §4.3：「只声明结构，不宣称权重数值」）",
     "（文档 §4.3：「v0.1 只声明结构，不宣称权重数值」）"),
    ("的纪律（蜂群互联 §4.3）。", "的纪律（文档 §4.3）。"),
    ("# 握手（蜂群互联 §5.1 五步：", "# 握手（文档 §5.1 五步："),
    ("# 蜂群互联 §4.2 全局唯一主体 id", "# §4.2 全局唯一主体 id"),
    ('clause="蜂群互联 §3.2（无观测向初值回归）"', 'clause="§3.2（无观测向初值回归）"'),
]
_DEG_WEIGHTS = [
    ("（该文档章节用中文序号）给出信任的**定义**；\n"
     "其**合成式**的出处＝`docs/swarm/蜂群互联_v0.1.md` §4.3（该文档用阿拉伯数字章节号；"
     "下文引用的 §4.3 均指它）：\n"
     "    P_trust = f(一致性, 位置可预测性, 版本对齐度)",
     "（该文档章节用中文序号，无 §4.3）：信任合成是\n"
     "    P_trust = f(一致性, 位置可预测性, 版本对齐度)"),
    ("同一纪律（蜂群互联 §4.3：「只声明结构，不宣称权重数值」）",
     "同一纪律（文档 §4.3：「v0.1 只声明结构」）"),
]


def _anchor_preflight():
    """变异锚点自检：任一 (新形态锚点, 退化形态) 在盘上文件里命中数 ≠1 → 退出码 2。"""
    bad = []
    for rel, pairs in ((LINKS, _DEG_LINKS), (WEIGHTS, _DEG_WEIGHTS)):
        try:
            text = _disk_read(rel)
        except OSError as exc:
            bad.append((rel, "<读失败 " + str(exc) + ">", -1))
            continue
        for anchor, _degraded in pairs:
            n = text.count(anchor)
            if n != 1:
                bad.append((rel, anchor[:48], n))
    if not bad:
        return 0
    for rel, anchor, n in bad:
        print("  ANCHOR-MISS " + rel + "：命中 " + str(n) + " 次（期望 1）" + repr(anchor))
    print("  => 实现已漂移，族退化注入表失效：退出码 2（fail-closed）")
    return 2


def _degrade(rel, pairs):
    """内存退化：把 rel 的读取结果换回 #73 修前形态；返回复原函数。"""
    text = _disk_read(rel)
    for anchor, degraded in pairs:
        if text.count(anchor) != 1:
            raise RuntimeError("锚点命中 " + str(text.count(anchor)) + " 次（期望 1）：" + repr(anchor[:48]))
        text = text.replace(anchor, degraded, 1)
    prev = _READ["fn"]
    _READ["fn"] = lambda r, _t=text, _rel=rel, _p=prev: (_t if r == _rel else _p(r))

    def _restore():
        _READ["fn"] = prev
    return _restore


def _mut_links():
    """退化①：links.py 退回裸「文档 §x」形态（章号重新无出处）。"""
    return _degrade(LINKS, _DEG_LINKS)


def _mut_weights():
    """退化②：weights.py 退回「无 §4.3」的假否定 ＋ 裸「文档 §4.3」。"""
    return _degrade(WEIGHTS, _DEG_WEIGHTS)


#: 变异组 A = #73 族退化。期望红项集合＝**实测值**（2026-10-09，工作树；两轮实测一致）：
#:   变异1（links.py 退化，含引文回退「v0.1 只声明结构…」）→ {B1, B2, B8, B9, B10}；
#:   变异2（weights.py 退化：假否定＋裸号＋归属倒挂）→ {A1, A2, A3, A7, A8, A9}；
#:   未变异基线 0 红；ANCHOR-MISS 腿单测已验（漂移 weights.py 后 rc=2）。
_MUTATIONS = {
    "A": [("links.py 退回裸「文档 §x」（含引文回退）", _mut_links,
           {"B1", "B2", "B8", "B9", "B10"}),
          ("weights.py 退回假否定＋裸号＋归属倒挂", _mut_weights,
           {"A1", "A2", "A3", "A7", "A8", "A9"})],
}

_GROUPS = {"weights": group_weights, "links": group_links}


def _run_all():
    global PASS, FAIL
    PASS = FAIL = 0
    del FAILS[:]
    for name in ("weights", "links"):
        _GROUPS[name]()
    return {n.split(" ", 1)[0] for n in FAILS}, PASS, FAIL


def _mutate(group):
    if group not in _MUTATIONS:
        print("未知组名 " + repr(group) + "（可选 " + str(sorted(_MUTATIONS)) + "）")
        return 1
    rc = _anchor_preflight()
    if rc:
        return rc
    print("!! #73 族退化注入自证 · 组 " + group + "：内存注入退化，逐条要求**恰好**命中期望红项\n")
    with contextlib.redirect_stdout(io.StringIO()):
        base_red, _, _ = _run_all()
    print("  未变异基线：红项 " + str(len(base_red)) + " "
          + ("（应为 0）" if not base_red else str(sorted(base_red))))
    bad = []
    if base_red:
        bad.append("基线即转红：" + str(sorted(base_red)))
    for i, (mname, apply, expect) in enumerate(_MUTATIONS[group]):
        restore = apply()
        try:
            with contextlib.redirect_stdout(io.StringIO()):
                red, _, _ = _run_all()
        except Exception as exc:                                   # noqa: BLE001
            red = {"<变异体异常:" + type(exc).__name__ + ">"}
        finally:
            restore()
        hit = red == expect
        if not hit:
            bad.append("变异" + str(i + 1) + " " + mname + "：红项 " + str(sorted(red))
                       + " ≠ 期望 " + str(sorted(expect)))
        print("  变异" + str(i + 1) + " " + mname + "  红项 " + str(len(red))
              + "（期望 " + str(len(expect)) + "）"
              + ("PASS" if hit else "**FAIL** 实=" + str(sorted(red)) + " 期=" + str(sorted(expect))))
    print("\n变异自证：" + ("PASS（逐条恰好命中期望红项）" if not bad else "FAIL —— " + "；".join(bad)))
    return 0 if not bad else 1


def main():
    if "--mutate" in sys.argv:
        i = sys.argv.index("--mutate")
        return _mutate(sys.argv[i + 1] if i + 1 < len(sys.argv) else "")
    print("issue #73 文档章节号引用守卫（幻影号 → 真源文档名；引文对拍）")
    print("=" * 74)
    red, _, _ = _run_all()
    print("=" * 74)
    print("通过 " + str(PASS) + " / 失败 " + str(FAIL))
    if FAILS:
        print("失败项：" + "，".join(FAILS))
        return 1
    print("ALL OK（两文件均点名真源；四个章号经引文对拍证明为真章节；反面证明见 --mutate A）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
