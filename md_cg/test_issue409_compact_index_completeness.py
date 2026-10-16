# -*- coding: utf-8 -*-
# 功能名：compact_index 的完整性判据必须 sound，「可信吗」判据必须单点（issue #409）
# 生效条件：python -X utf8 -m md_cg.test_issue409_compact_index_completeness [--mutate]；被测面＝md_cg/mdcg.py 的 compact_index / _load_index / _snapshot_trusted / _covers_disk
# 子功能：A 组＝五形态「净 .md 计数为零而语义已变」（旧判据假阳 + 新判据能抓 + 端到端读数正确）；K 组＝非恒真对照（正常路径不得重扫、幂等 compact、可信快照装载不扫盘）；E 组＝源码面（「可信吗」单点唯一实现、两个判据互不调用、接线在位）
# 执行：--mutate 时在镜像树里逐条把判据改回缺陷形态 / 过度收紧（恒判不可信、恒不过闸），守卫必须按指定项转红
# 验证方式：全部 PASS 即通过（退出码 0）；--mutate 下每条变异的红项集合须与预期逐项相符（多红/少红皆不合格）
# 不适用条件：不判「外部纯内容改写（不动文件名）」——那是 _dir_fingerprint 自述的协议外边界（合作写者协议，见其 docstring）；不判「实例已打开期间、库外纯改名/对调且路径集合不变」这一残余形态（需以装载时指纹为基线，本批不做，见汇报未覆盖；issue 原文的「更稳」建议亦不覆盖）；不判 Rust 侧索引装载（另一实现面）；不判 compact 的原子写/锁（属既有守卫）
#
# ── 本改动的硬边界登记（改动时撞上的既有限制，及为何这样绕）──────────────────
# ① 有效快照的重开路径不得扫盘：md_cg/test_index_snapshot_shape.py:191-196 用
#    mock.patch.object(MdCG, "_scan_nodes", side_effect=AssertionError(...)) 钉死
#    ⇒ _snapshot_trusted 必须保热路径（置信即用，不重扫）；本次未动该路径。
# ② compact 里的变异锚点唯一性：同文件 :227-229 的定点变异锚点
#    'if not _usable_index_snapshot(d):' 必须原样唯一存在于 compact_index
#    ⇒ 本批一字未动该行（形状准入闸保持原样）。
# ③ 源码窗口区间：md_cg/test_n212_n213_n224_generation_gates.py:481 取
#    「def _maybe_reload_index → 首个 def _dir_fingerprint」为窗口并断言含三个
#    invalidate_cache ⇒ 新函数不得插在该区间内：_snapshot_trusted / _md_rel_paths /
#    _covers_disk 一律放在 _dir_fingerprint 之后。
# ④ _count_md_files 的语义必须保持（层内 .md 计数）：
#    md_cg/test_n225_nonobject_load.py:688 断言 len(index.nodes) == c._count_md_files()
#    ⇒ 它改为「len(self._md_rel_paths())」——计数不变，只把走查收成同源一份。
# ⑤ 完整性闸的**位置**（不是既有约束，是本批的论证——写在这里防后人挪动）：
#    闸装在**重放之前**。闸问的是「我拿到的这份**基底**是否恰好描述当前盘面」；
#    而增量日志是**合作写者协议下的权威写入记录**，其条目**允许指向盘外路径**
#    ——这一点由 md_cg/test_n225_nonobject_load.py 的 E3（同批里的合法 upsert 仍
#    生效）与 E6（compact 后 nodes 与装载面逐键相等，且同批坏载荷同样记账：
#    子面共 6 条）钉死。若把闸装在**重放之后**，就会把「日志的正确性」误判成
#    「基底不完整」、并因此**多付一次重放** ⇒ E6 的记账面立刻转红（本批第一版正是
#    这样被打红的：payload/total 9 而非 6；根因与前后读数见汇报 §7）。
#    同源依据：_load_index 的兜底也在**重放之前**换基底（无快照/不可信 ⇒ 先扫盘，
#    再统一重放）——两面的时序一致。
#
# 另一条（不是限制而是先例）：_usable_index_snapshot（N225 准入闸）与 _apply_log
# （N225 重放）本来就是 load/compact 共用单点 ⇒ _snapshot_trusted 是延续既有形态，
# 不是新立机制。
"""issue #409 守卫：compact_index 的完整性命中判据必须 sound，「快照可信吗」必须单点。

病象（修前）：同一个问题（这份快照可信吗）有两套判据——
  · _load_index 用目录指纹（新鲜度）；
  · compact_index 用 .md 计数相等（自称完整性），随后无条件把当前指纹盖上去。
「净计数为零」的库外变化（改名 / 换目录 / 两文件内容对调 / 删一加一 / 另一实例
已落盘而其索引增量还在它自己的 _dirty 里）让计数判据必然假阳 ⇒ 陈旧
「节点→path」映射被原样保留 + 盖上当前指纹 ⇒ 下次打开指纹相符、不重扫 ⇒
get(id) 返回别人的正文；此后一次普通写回（读到→改→写回）会让别人的正文
全库无副本（_protected_history / trash / _index_log 均无）——只有全量
rebuild_index() 能救。

修法（两件事，各自单点、互不调用）：
  · 可信吗（新鲜度）⇒ _snapshot_trusted：唯一实现，_load_index 与 compact_index
    共用（收成单点，不是给 compact 再加一条）；
  · 写完安全吗（完整性）⇒ _covers_disk：把原来的 .md 计数相等升级为
    「索引路径集合 == 盘面 .md 路径集合」（集合相等 ⇒ 计数相等，反之不然），
    且只在基底确定后、重放之前判定（日志条目按合作写者协议是权威写入记录，
    允许指向盘外路径——N225 守卫 E3/E6 钉死）。
不可信的旧快照不作基底，改吃本进程内存索引；不采用「不可信一律重扫」
（正常 close 路径里本进程刚写过文件 ⇒ 盘上快照指纹必然失配，一律重扫会退化成
每次 close 全库重扫，正是 issue #33 要避免的）。
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
from unittest import mock

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO not in sys.path:
    sys.path.insert(0, _REPO)

from md_cg.mdcg import MdCG      # noqa: E402
from md_cg import mdcg as _mdcg  # noqa: E402

FAILS = []
_TMP = tempfile.mkdtemp(prefix="iss409_")
_K = "knowledge/orphan"
_BOOM = AssertionError("正常路径不得扫盘（_scan_nodes 被调用）")


def _check(name, cond, detail=""):
    if cond:
        print("  PASS " + name)
    else:
        print("  FAIL " + name + "  " + str(detail)[:220])
        FAILS.append(name)


def _no_scan():
    return mock.patch.object(MdCG, "_scan_nodes", side_effect=_BOOM)


def _root(tag):
    d = os.path.join(_TMP, tag)
    os.makedirs(d, exist_ok=True)
    return d


def _build(root, nodes=(("alpha", "甲"), ("beta", "乙"))):
    cg = MdCG(root)
    for nid, mark in nodes:
        cg.add(nid, "MARK-" + mark)
    cg.flush()
    cg.close()                       # 首次 close：无快照 → rebuild_index 落 S1
    return _snap(root)


def _snap(root):
    d = json.load(open(os.path.join(root, "_index.json"), encoding="utf-8"))
    return ({k: v["path"] for k, v in d["nodes"].items()}, d.get("_fingerprint"))


def _count_md(root):
    n = 0
    for layer in ("anchor", "structural", "knowledge", "contextual", "self",
                  "rejected", "unresolved", "goals"):
        for _dp, _dd, ff in os.walk(os.path.join(root, layer)):
            n += sum(1 for f in ff if f.endswith(".md"))
    return n


def _write_md(root, rel, nid, mark):
    p = os.path.join(root, rel.replace("/", os.sep))
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w", encoding="utf-8") as f:
        f.write("---" + chr(10) + "id: %s" % nid + chr(10) + "layer: knowledge"
                + chr(10) + "---" + chr(10) + "MARK-%s" % mark + chr(10))


def _gen3(root):
    """第三代：只用快照（指纹相符即不重扫）→ 逐 id 读回 {fm_id, mark}。"""
    cg = MdCG(root)
    out = {}
    for nid in tuple(sorted(cg.index["nodes"])):     # H-4(a)：迭代前取快照
        n = cg.get(nid)
        out[nid] = None if n is None else {
            "fm_id": (n.get("frontmatter") or {}).get("id"),
            "mark": [l for l in (n.get("content") or "").splitlines()
                     if l.startswith("MARK")]}
    cg.close()
    return out


def _probe_stale_base(root, while_open=None):
    """库外改动已发生、compact 未跑的时点取三条判据读数。

    返回 (old_judge, gate_judge, fresh_judge, disk_n, base_n)：
      · old_judge  = 旧判据「.md 计数相等」是否假阳（True ⇒ 它认为陈旧基底可用）
      · gate_judge = 完整性闸 _covers_disk(陈旧基底)（路径集合是否仍覆盖盘面）
      · fresh_judge= 新鲜度判据 _snapshot_trusted(盘上快照)（盘面动过 ⇒ False）
    """
    cg = MdCG(root) if while_open is None else while_open
    if while_open is None:
        d = json.load(open(os.path.join(root, "_index.json"), encoding="utf-8"))
        base = dict(d["nodes"])
    else:
        base = dict(cg.index["nodes"])
    old_judge = (cg._count_md_files() == len(base))
    gate_judge = cg._covers_disk(base)
    fresh_judge = (cg._snapshot_trusted(
        json.load(open(os.path.join(root, "_index.json"), encoding="utf-8"))))
    if while_open is None:
        cg.close()
    return old_judge, gate_judge, fresh_judge, len(cg._md_rel_paths()), len(base)


def _form(tag, mutate, expect, while_open=False):
    root = _root(tag.split(" ")[0])
    _build(root)
    if while_open:
        cg = MdCG(root)                    # 实例先打开（已装载 S1）
        mutate(root)
        old_judge, gate_judge, fresh_judge, dn, bn = _probe_stale_base(
            root, while_open=cg)
        cg.close()                         # close → compact
    else:
        mutate(root)
        old_judge, gate_judge, fresh_judge, dn, bn = _probe_stale_base(root)
        cg = MdCG(root)                    # 第二代装载（指纹失配 ⇒ 全量重扫）
        cg.close()                         # close → compact
    _check("A·%s·旧判据假阳吗（计数相等 ⇒ 它认为陈旧基底可用）" % tag,
           old_judge is True and dn == bn, (old_judge, dn, bn))
    _check("A·%s·新判据能抓吗①新鲜度：陈旧快照被判不可信（不作基底）" % tag,
           fresh_judge is False, fresh_judge)
    if expect.get("gate", True):
        _check("A·%s·新判据能抓吗②完整性：_covers_disk 判陈旧基底不覆盖盘面" % tag,
               gate_judge is False, gate_judge)
    got = _gen3(root)
    _check("A·%s·端到端读数正确：%s" % (tag, expect["label"]),
           expect["ok"](got), got)
    return got


def f1(root):
    os.rename(os.path.join(root, _K, "alpha.md"),
              os.path.join(root, _K, "alpha2.md"))


def f2(root):
    os.makedirs(os.path.join(root, "knowledge/other"), exist_ok=True)
    os.rename(os.path.join(root, _K, "alpha.md"),
              os.path.join(root, "knowledge/other/alpha.md"))


def f3(root):
    a = os.path.join(root, _K, "alpha.md")
    b = os.path.join(root, _K, "beta.md")
    t = a + ".tmp"
    os.rename(a, t)
    os.rename(b, a)
    os.rename(t, b)


def f4(root):
    os.remove(os.path.join(root, _K, "beta.md"))
    _write_md(root, _K + "/brand_new.md", "brand_new", "新")


def _is_node(got, nid, mark):
    v = got.get(nid)
    return bool(v) and v.get("fm_id") == nid and v.get("mark") == ["MARK-" + mark]


print("== A 组：净 .md 计数为零的五形态（#409 正题） ==")
_form("F1 改名（alpha.md→alpha2.md）", f1,
      {"label": "alpha 仍指向 alpha 的正文（修前为 None＝幽灵）",
       "ok": lambda g: _is_node(g, "alpha", "甲") and _is_node(g, "beta", "乙")})
_form("F2 移动目录（knowledge/orphan→knowledge/other）", f2,
      {"label": "alpha 仍指向 alpha 的正文（修前为 None）",
       "ok": lambda g: _is_node(g, "alpha", "甲") and _is_node(g, "beta", "乙")})
# F3 的**路径集合不变**（只是 id↔path 指派陈旧）⇒ 完整性闸抓不住它，
# 由**新鲜度判据**拦（陈旧快照不可信 ⇒ 基底改用本进程内存索引＝重扫结果）。
# 这是两个判据分工的活证据：闸只管「路径集合是否覆盖盘面」，不管指派语义。
_form("F3 两条对调（改名式互换内容）", f3,
      {"label": "get(alpha).fm_id == alpha（修前为 beta＝返回别人的正文）",
       "ok": lambda g: _is_node(g, "alpha", "甲") and _is_node(g, "beta", "乙"),
       "gate": False})
_form("F4 删一加一（库外同时删 beta.md / 加 brand_new.md）", f4,
      {"label": "新增节点可见且幽灵消失（修前：brand_new 不可见 + beta 幽灵）",
       "ok": lambda g: _is_node(g, "alpha", "甲") and _is_node(g, "brand_new", "新")
       and "beta" not in g})
_form("F5 删一加一·实例已打开期间（他实例写已落盘、其索引增量未 flush）", f4,
      {"label": "同上（修前：陈旧内存映射被盖章）",
       "ok": lambda g: _is_node(g, "alpha", "甲") and _is_node(g, "brand_new", "新")
       and "beta" not in g}, while_open=True)

print("== K 组：非恒真对照（正常路径不得被过度收紧） ==")
_root_k = _root("k01")
_build(_root_k)
try:
    with _no_scan():
        _cg = MdCG(_root_k)
        _cg.get("alpha")
        _cg.close()
    _k01 = True
except AssertionError:
    _k01 = False
_check("K01 有效快照：装载与 close(compact) 全程不扫盘（#33 热路径未被收紧）", _k01)

_root_k2 = _root("k02")
_build(_root_k2)
try:
    with _no_scan():
        _cg = MdCG(_root_k2)
        _cg.add("n2", "MARK-二")
        _cg.flush()
        _cg.close()
    _k02 = True
except AssertionError:
    _k02 = False
_snap2, _ = _snap(_root_k2)
_check("K02 本进程新增后 close：不扫盘且新节点进快照", _k02 and "n2" in _snap2,
       sorted(_snap2))

_root_k3 = _root("k03")
_build(_root_k3)
try:
    with _no_scan():
        _cg = MdCG(_root_k3)
        _cg.compact_index()
        _cg.compact_index()
    _k03 = True
except AssertionError:
    _k03 = False
_check("K03 连续两次 compact：幂等且不扫盘", _k03)

_root_k4 = _root("k04")
_build(_root_k4)
try:
    _mine = MdCG(_root_k4)
    _other = MdCG(_root_k4)
    _other.add("n_other", "MARK-他")
    _other.flush()
    _other.close()
    with _no_scan():
        _mine.add("n_mine", "MARK-我")
        _mine.flush()
        _mine.close()
    _k04 = True
except AssertionError:
    _k04 = False
_snap4, _ = _snap(_root_k4)
_check("K04 他实例 compact 后本实例 close：不扫盘且两边节点都在",
       _k04 and sorted(_snap4) == ["alpha", "beta", "n_mine", "n_other"],
       sorted(_snap4))

_root_k5 = _root("k05")
_build(_root_k5)
_cg5 = MdCG(_root_k5)
_check("K05 _count_md_files 语义保持（== 手工层内 .md 计数 == len(_md_rel_paths)）",
       _cg5._count_md_files() == _count_md(_root_k5)
       and _cg5._count_md_files() == len(_cg5._md_rel_paths()),
       (_cg5._count_md_files(), _count_md(_root_k5)))

_d = json.load(open(os.path.join(_root_k5, "_index.json"), encoding="utf-8"))
_check("K06 _snapshot_trusted 边界：真快照 True；无键/None/不符/非 dict 皆 False",
       _cg5._snapshot_trusted(_d) is True
       and _cg5._snapshot_trusted({"nodes": {}}) is False
       and _cg5._snapshot_trusted({"nodes": {}, "_fingerprint": None}) is False
       and _cg5._snapshot_trusted({"nodes": {}, "_fingerprint": 1}) is False
       and _cg5._snapshot_trusted(None) is False
       and _cg5._snapshot_trusted([]) is False, "")
_cg5.close()

print("== E 组：源码面（单点唯一实现 / 判据互不调用 / 硬边界） ==")
_SRC = open(os.path.join(_REPO, "md_cg", "mdcg.py"), encoding="utf-8").read()
_doc_t = _mdcg.MdCG._snapshot_trusted.__doc__ or ""
_doc_c = _mdcg.MdCG._covers_disk.__doc__ or ""
import ast as _ast          # noqa: E402


def _fn_code(src, name):
    """抽函数**代码体**（剔除 docstring 与注释）——判据互调用的判据必须只看代码。"""
    for node in _ast.walk(_ast.parse(src)):
        if isinstance(node, _ast.FunctionDef) and node.name == name:
            body = [n for n in node.body
                    if not (isinstance(n, _ast.Expr)
                            and isinstance(n.value, _ast.Constant)
                            and isinstance(n.value.value, str))]
            return chr(10).join(_ast.unparse(n) for n in body)
    return ""


_trusted_body = _fn_code(_SRC, "_snapshot_trusted")
_covers_body = _fn_code(_SRC, "_covers_disk")
_check("E01 「可信吗」判定只有一处实现（指纹比较式全文件唯一且在 _snapshot_trusted 体内）",
       _SRC.count("== self._dir_fingerprint()") == 1
       and "== self._dir_fingerprint()" in _trusted_body,
       _SRC.count("== self._dir_fingerprint()"))
_check("E02 装载面与落盘面都接同一单点（load/compact 各恰一处调用）",
       _SRC.split("def _load_index")[1].split("def _apply_log")[0]
       .count("_snapshot_trusted(") == 1
       and _SRC.split("def compact_index")[1].split("def _scan_nodes")[0]
       .count("_snapshot_trusted(") == 1)
_check("E03 两个判据互不调用（可信吗里无完整性面；完整性里无可信吗/指纹）",
       "_covers_disk" not in _trusted_body and "_md_rel_paths" not in _trusted_body
       and "_snapshot_trusted" not in _covers_body
       and "_dir_fingerprint" not in _covers_body)
_check("E04 判据自证命名：可信吗 docstring 写明「唯一」「可信」；完整性 docstring 写明「安全」且声明「不是」可信",
       "唯一" in _doc_t and "可信" in _doc_t
       and "安全" in _doc_c and "不是" in _doc_c)
_check("E05 硬边界①（热路径在位）：_load_index 仍走 _snapshot_trusted 不扫盘",
       "if not self._snapshot_trusted(idx):" in _SRC)
_check("E06 硬边界②（变异锚点唯一）：'if not _usable_index_snapshot(d):' 全文件恰一处且在 compact 内",
       _SRC.count("if not _usable_index_snapshot(d):") == 1
       and "if not _usable_index_snapshot(d):" in _SRC.split("def compact_index")[1])
_win = _SRC.split("def _maybe_reload_index")[1].split("def _dir_fingerprint")[0]
_check("E07 硬边界③（源码窗口不被截断）：窗口仍含三个 invalidate_cache",
       all(t in _win for t in ("chain.invalidate_cache", "subgraph.invalidate_cache",
                               "trust.invalidate_cache")))
_check("E08 硬边界④（计数语义单点）：_count_md_files 体内只剩 len(self._md_rel_paths())",
       "return len(self._md_rel_paths())"
       in _SRC.split("def _count_md_files")[1][:200])
_check("E09 先例延续：_snapshot_trusted docstring 点名 N225 两个共用单点",
       "_usable_index_snapshot" in _doc_t and "_apply_log" in _doc_t)

shutil.rmtree(_TMP, ignore_errors=True)
print("")
if FAILS:
    print("issue #409 结果：%d 失败" % len(FAILS))
else:
    print("issue #409 结果：全部通过")


# ---------------------------------------------------------------- 定点变异
_RAW = open(os.path.join(_REPO, "md_cg", "mdcg.py"), "rb").read()
_NL = "\r\n" if _RAW[:8192].count(b"\r\n") else "\n"


def _j(*lines):
    """跨行锚点按**目标文件实际行尾**拼接（本仓 CRLF/LF 混合）。"""
    return _NL.join(lines)

_MUTATIONS = (
    # 忠实回缺陷：① 陈旧快照照旧作基底（撤掉基底选择）② 摘掉重放前的完整性闸
    # ③ 把「.md 计数相等」判据装回**重放之后**（旧形态的时序：重放 → 计数 → 重扫+重放）
    ("M1 回缺陷：陈旧快照作基底 + 完整性退回重放后的「.md 计数相等」", "md_cg/mdcg.py",
     (("            if not scan_fallback and not self._snapshot_trusted(idx):",
       "            if False:  # 变异：陈旧快照照旧作基底"),
      (_j("            if not scan_fallback and not self._covers_disk(idx[\"nodes\"]):",
          "                idx = {\"schema\": SCHEMA, \"nodes\": self._scan_nodes(),",
          "                       \"buckets\": {}}"),
       "            pass  # 变异：摘掉重放前的完整性闸"),
      (_j("            self._apply_log(idx[\"nodes\"])",
          "            idx[\"buckets\"] = self._count_buckets(idx[\"nodes\"])"),
       _j("            self._apply_log(idx[\"nodes\"])",
          "            if not scan_fallback and self._count_md_files() != len(idx[\"nodes\"]):",
          "                idx = {\"schema\": SCHEMA,",
          "                       \"nodes\": self._apply_log(self._scan_nodes()),",
          "                       \"buckets\": {}}",
          "            idx[\"buckets\"] = self._count_buckets(idx[\"nodes\"])"))),
     ("A·F1", "A·F2", "A·F3", "A·F4", "A·F5", "E02")),
    ("M2 过度收紧：恒判快照不可信（正常路径恒重扫）", "md_cg/mdcg.py",
     (("        return fp is not None and fp == self._dir_fingerprint()",
       "        return False  # 变异：恒判不可信"),),
     ("E01", "K01", "K02", "K03", "K04", "K06")),
    ("M3 过度收紧：完整性闸恒不过（正常路径恒重扫）", "md_cg/mdcg.py",
     (("        return len(nodes) == len(disk) and paths == disk",
       "        return False  # 变异：恒不过闸"),),
     ("K01", "K02", "K03", "K04")),
)


def _mirror_build():
    dst = tempfile.mkdtemp(prefix="iss409_mut_")
    for name in ("md_cg", "scripts"):
        src = os.path.join(_REPO, name)
        if os.path.isdir(src):
            shutil.copytree(src, os.path.join(dst, name),
                            ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    for name in sorted(os.listdir(_REPO)):
        p = os.path.join(_REPO, name)
        if os.path.isfile(p) and (name.endswith(".py")
                                  or name in ("README.md", "pyproject.toml",
                                              "package.json")):
            shutil.copy2(p, os.path.join(dst, name))
    return dst


def _run_in(tree):
    env = dict(os.environ)
    env["PYTHONPATH"] = tree
    env["PYTHONUTF8"] = "1"
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env.pop("MDCG_ROOT", None)
    pr = subprocess.run([sys.executable, "-X", "utf8", "-m",
                         "md_cg.test_issue409_compact_index_completeness"],
                        capture_output=True, text=True, encoding="utf-8",
                        errors="replace", cwd=tree, env=env, timeout=3600)
    out = (pr.stdout or "") + (pr.stderr or "")
    reds = [ln.split("FAIL ", 1)[1].strip()
            for ln in out.splitlines() if ln.strip().startswith("FAIL ")]
    return pr.returncode, reds, out


def _mutate():
    print("!! 定点变异自证：回缺陷 + 两个方向的过度收紧，守卫必须按指定项转红")
    tree = _mirror_build()
    try:
        rc, reds, out = _run_in(tree)
        print("  未变异镜像基线：rc=%d 红项=%d（必须 rc=0 且 0 红）" % (rc, len(reds)))
        if rc != 0 or reds:
            print(chr(10).join(out.splitlines()[-25:]))
        bad = []
        for desc, rel, pairs, exp in _MUTATIONS:
            p = os.path.join(tree, rel)
            t = open(p, encoding="utf-8", newline="").read()
            bak = t
            if any(t.count(o) != 1 for o, _n in pairs):
                bad.append("%s —— 锚点命中 %s" % (desc, [t.count(o) for o, _n in pairs]))
                print("  ANCHOR-MISS " + desc)
                continue
            for o, n in pairs:
                t = t.replace(o, n, 1)
            open(p, "w", encoding="utf-8", newline="").write(t)
            for root, dd, ff in os.walk(tree):
                if os.path.basename(root) == "__pycache__":
                    shutil.rmtree(root, ignore_errors=True)
            rc2, reds2, out2 = _run_in(tree)
            open(p, "w", encoding="utf-8", newline="").write(bak)
            hit = sorted({r.split(" ")[0] for r in reds2})
            want = sorted(exp)
            if rc2 != 0 and hit == want:
                print("  OK   %s  红项=%d 指定命中=%d/%d"
                      % (desc, len(reds2), len(hit), len(want)))
            else:
                bad.append(desc)
                print("  MISMATCH %s  实际红项=%s  期望=%s  rc=%d"
                      % (desc, hit[:8], want[:8], rc2))
                for r in reds2[:10]:
                    print("        FAIL " + r)
        print("定点变异自证：%s（%d 条不合格）"
              % ("PASS" if not bad else "FAIL", len(bad)))
        for b in bad:
            print("  不合格：" + b)
        return len(bad)
    finally:
        shutil.rmtree(tree, ignore_errors=True)


def main():
    _bad = _mutate() if "--mutate" in sys.argv else 0
    return 1 if (FAILS or _bad) else 0


if __name__ == "__main__":
    sys.exit(main())
