# -*- coding: utf-8 -*-
"""test_t21a_extensible —— 分桶可扩展验收：『加一个新桶不触发全量迁移』。

复用灵枢既有分桶机制（写入侧 route_key→bucket_dir 落桶目录、扫描侧
bucket=子目录名、检索侧 S1b 桶阶段——本测试只锁写入/索引/健康面，不涉检索），
验收「加一个新桶 → 存量节点零迁移」：

  [A] 建临时库：knowledge 层分别写 domain:域A / domain:域B 节点各 3 个，
      确认全部落桶目录（索引 bucket 真值且 != orphan），快照记录每个节点的
      文件相对路径 / content_hash / 索引 bucket 字段 / buckets 计数字典。
  [B] 加新桶：再写一个 domain:域C 的 knowledge 节点 → 落新桶目录
      cond_域C_<sha8>（即 routing.bucket_dir("域C")），索引 bucket 为真值。
  [C] 老数据零迁移：域A/域B 全部老节点的文件相对路径一字未变、content_hash
      逐一相等（未重写）、索引 bucket 字段逐一不变；buckets 计数只新增域C 桶、
      域A/域B 桶计数不变；索引 node 集合无替换（老 nid 仍在，路径字段不变）。
  [D] bucket_health：新增桶后 buckets+1 可见（health 与 routing.bucket_health
      双侧一致）；problem 种类与新增前一致，不因新增桶新增『分区失效』类报错
      （单桶退化不成立，此处如实不报新增）。
  [E] 层隔离：写 contextual 层节点不落入任何 knowledge 桶、知识桶计数不变。

关键机制（mdcg.py）：
  · 写入侧 mdcg.py:2758-2787：bucket=None 起步；layer 在 BUCKETED_LAYERS
    (("knowledge",)) 且 MDCG_RETRIEVAL_PIPELINE=1 时
    bucket = routing.bucket_dir(routing.route_key(condition_space, tags))，
    文件落 root/<layer>/<bucket>/<nid>.md；
  · 扫描侧 mdcg.py:2232（_node_entry）：bucket = 父目录名，父目录等于层名时 None；
  · 桶计数单点 _set_index_entry/_bucket_shift（mdcg.py:3700-3749）。
  · health 分桶读数 = routing.bucket_health(index["buckets"],
    total_nodes=len(index["nodes"]))（mdcg.py:5701）。
  门控：MDCG_RETRIEVAL_PIPELINE 默认关，写入侧 domain 注入与 bucket 计算受它
  门控——main() 开头显式置 "1"，finally 恢复原值。

运行：cd /d D:\\wook\\lingshu-src && python -X utf8 -m md_cg.test_t21a_extensible
"""

import os
import sys
import shutil
import tempfile

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

from md_cg import routing                       # noqa: E402
from md_cg.mdcg import MdCG                     # noqa: E402

passed = 0
failed = 0

_ENV = "MDCG_RETRIEVAL_PIPELINE"

# ── 各段共享的库状态（test_a 建立，其后各段消费） ──
_CG = None
_ROOT = None
_SNAP = {}             # nid -> {"path","hash","bucket"}（建库后、加域C 前）
_SNAP_BUCKETS = {}     # {bucket_dir: count}（建库后、加域C 前）
_H_BEFORE = {}         # 加域C 前的 health()（[D] 段对照）


def check(name, cond, detail=""):
    global passed, failed
    if cond:
        passed += 1
        print("  [PASS] " + name)
    else:
        failed += 1
        print("  [FAIL] " + name + "  " + str(detail)[:300])


def _mk_cg():
    """临时目录建库（t65a 同款风格）。返回 (MdCG, root)。"""
    root = tempfile.mkdtemp(prefix="mdcg_t21a_")
    return MdCG(root), root


# ---------------------------------------------------------------------------
# [A] 建临时库：domain:域A / domain:域B 各 3 个 knowledge 节点 → 落桶 + 快照
# ---------------------------------------------------------------------------

def test_a_initial_lib():
    global _CG, _ROOT, _SNAP, _SNAP_BUCKETS, _H_BEFORE
    print("[A] 建临时库：domain:域A / domain:域B 各 3 个 knowledge 节点 → 落桶")
    _CG, _ROOT = _mk_cg()
    pairs = []
    for i in range(1, 4):
        pairs.append(("a%d" % i, "域A 知识点 %d：条件与规则（t21a）" % i,
                      "domain:域A"))
        pairs.append(("b%d" % i, "域B 知识点 %d：场景与推演（t21a）" % i,
                      "domain:域B"))
    for nid, content, tag in pairs:
        _CG.add(nid, content, "knowledge", tags=[tag])
    _CG.flush()
    nodes = _CG.index["nodes"]

    # 断言 1-6：每个节点索引 bucket 为真值且 != orphan
    for nid, _, _tag in pairs:
        b = (nodes.get(nid) or {}).get("bucket")
        check("[A] %s 索引 bucket 真值且 != orphan" % nid,
              bool(b) and b != routing.ORPHAN,
              "bucket=%r" % (b,))

    # 快照：文件相对路径 / content_hash / 索引 bucket / buckets 计数字典
    _SNAP = {}
    for nid, _, _tag in pairs:
        e = nodes[nid]
        _SNAP[nid] = {"path": e.get("path"),
                      "hash": e.get("content_hash"),
                      "bucket": e.get("bucket")}
    _SNAP_BUCKETS = dict(_CG.index["buckets"] or {})
    check("[A] 快照已记录 content_hash 真值（文件内容哈希）",
          all(_SNAP[nid]["hash"] for nid in _SNAP),
          "hashes=%s" % {nid: _SNAP[nid]["hash"] for nid in _SNAP})

    exp_a = routing.bucket_dir("域A")
    exp_b = routing.bucket_dir("域B")
    check("[A] 桶目录名可读回原域（bucket_key_readable）",
          routing.bucket_key_readable(exp_a) == "域A"
          and routing.bucket_key_readable(exp_b) == "域B"
          and routing.bucket_key_readable(_SNAP["a1"]["bucket"]) == "域A"
          and routing.bucket_key_readable(_SNAP["b1"]["bucket"]) == "域B",
          "a1=%r b1=%r" % (_SNAP["a1"]["bucket"], _SNAP["b1"]["bucket"]))
    check("[A] 文件相对路径形如 knowledge/<bucket>/<nid>.md",
          all(_SNAP[nid]["path"] == "knowledge/%s/%s.md"
              % (_SNAP[nid]["bucket"], nid)
              for nid in _SNAP),
          "paths=%s" % [(nid, _SNAP[nid]["path"]) for nid in _SNAP])
    check("[A] buckets 计数恰为 域A:3 / 域B:3 两桶",
          _SNAP_BUCKETS == {exp_a: 3, exp_b: 3},
          "buckets=%s exp=%s" % (_SNAP_BUCKETS, {exp_a: 3, exp_b: 3}))

    _H_BEFORE = _CG.health()          # 加域C 前的健康读数（[D] 对照基线）


# ---------------------------------------------------------------------------
# [B] 加新桶：写入 domain:域C 节点 → 落 cond_域C_<sha8> 新桶目录
# ---------------------------------------------------------------------------

def test_b_new_bucket():
    global _CG
    print("[B] 加新桶：写入 domain:域C knowledge 节点 → 落 cond_域C_<sha8>")
    exp_c = routing.bucket_dir("域C")
    nid_c = "c1"
    _CG.add(nid_c, "域C 知识点：新增域的存量零迁移验收（t21a）",
            "knowledge", tags=["domain:域C"])
    _CG.flush()
    e = _CG.index["nodes"][nid_c]
    check("[B] 域C 节点索引 bucket == routing.bucket_dir('域C')"
          "（cond_域C_<sha8>）",
          e.get("bucket") == exp_c,
          "bucket=%r exp=%r" % (e.get("bucket"), exp_c))
    check("[B] 域C 节点索引 bucket 为真值且 != orphan",
          bool(e.get("bucket")) and e.get("bucket") != routing.ORPHAN,
          "bucket=%r" % (e.get("bucket"),))
    rel = "knowledge/%s/%s.md" % (exp_c, nid_c)
    check("[B] 域C 文件确实落新桶目录（盘面存在）",
          e.get("path") == rel
          and os.path.isfile(os.path.join(_CG.root, rel)),
          "path=%r rel=%r" % (e.get("path"), rel))
    check("[B] buckets 计数新增 域C 桶 == 1 且键可读回 域C",
          (_CG.index["buckets"] or {}).get(exp_c) == 1
          and routing.bucket_key_readable(exp_c) == "域C",
          "buckets=%s" % _CG.index["buckets"])


# ---------------------------------------------------------------------------
# [C] 老数据零迁移：域A/域B 老节点 路径/哈希/索引 bucket/计数 全不变
# ---------------------------------------------------------------------------

def test_c_zero_migration():
    global _CG, _SNAP, _SNAP_BUCKETS
    print("[C] 老数据零迁移：域A/域B 节点路径/哈希/索引 bucket/桶计数全不变")
    exp_c = routing.bucket_dir("域C")
    nodes = _CG.index["nodes"]
    old_ids = sorted(_SNAP.keys())

    check("[C] 全部老节点文件相对路径一字未变",
          all(nodes[nid].get("path") == _SNAP[nid]["path"]
              for nid in old_ids),
          [(nid, nodes[nid].get("path"), _SNAP[nid]["path"])
           for nid in old_ids
           if nodes[nid].get("path") != _SNAP[nid]["path"]])
    check("[C] 全部老节点 content_hash 逐一相等（未重写）",
          all(nodes[nid].get("content_hash") == _SNAP[nid]["hash"]
              for nid in old_ids),
          [(nid, nodes[nid].get("content_hash"), _SNAP[nid]["hash"])
           for nid in old_ids
           if nodes[nid].get("content_hash") != _SNAP[nid]["hash"]])
    check("[C] 全部老节点索引 bucket 字段逐一不变",
          all(nodes[nid].get("bucket") == _SNAP[nid]["bucket"]
              for nid in old_ids),
          [(nid, nodes[nid].get("bucket"), _SNAP[nid]["bucket"])
           for nid in old_ids
           if nodes[nid].get("bucket") != _SNAP[nid]["bucket"]])

    exp_buckets = dict(_SNAP_BUCKETS)
    exp_buckets[exp_c] = 1
    check("[C] buckets 计数只新增域C 桶（域A/域B 计数不变）",
          _CG.index["buckets"] == exp_buckets,
          "got=%s exp=%s" % (_CG.index["buckets"], exp_buckets))
    check("[C] buckets 键集合仅新增 域C 桶（无删键）",
          set((_CG.index["buckets"] or {}).keys())
          == set(_SNAP_BUCKETS.keys()) | {exp_c},
          "got=%s snap=%s" % (sorted(_CG.index["buckets"] or {}),
                              sorted(_SNAP_BUCKETS)))
    cur_ids = set(nodes.keys())
    check("[C] 索引 node 集合无替换（老 nid 全在 + 仅新增 c1，路径字段不变）",
          set(old_ids) <= cur_ids and len(cur_ids) == len(old_ids) + 1
          and all(nodes[nid].get("path") == _SNAP[nid]["path"]
                  for nid in old_ids),
          "cur=%s" % sorted(cur_ids))


# ---------------------------------------------------------------------------
# [D] bucket_health：新增桶 buckets+1 可见、不新增『分区失效』类报错
# ---------------------------------------------------------------------------

def test_d_health():
    global _CG, _H_BEFORE
    print("[D] bucket_health：新增桶 buckets+1 可见、不新增分区失效报错")
    exp_c = routing.bucket_dir("域C")
    h_before = _H_BEFORE
    h_after = _CG.health()
    check("[D] health 可见新桶：buckets 新增桶后 +1（%d→%d）"
          % (h_before["buckets"], h_after["buckets"]),
          h_after["buckets"] == h_before["buckets"] + 1
          and h_after["buckets"] == 3,
          "before=%s after=%s"
          % (h_before["buckets"], h_after["buckets"]))
    rb = routing.bucket_health(_CG.index.get("buckets", {}),
                               total_nodes=len(_CG.index["nodes"]))
    check("[D] routing.bucket_health 同口径可见新桶（buckets+1 且键在计数内）",
          rb["buckets"] == h_before["buckets"] + 1
          and (_CG.index["buckets"] or {}).get(exp_c) == 1,
          "rb=%s" % rb)
    kinds_before = set(p.split("：", 1)[0]
                       for p in (h_before["problems"] or []))
    kinds_after = set(p.split("：", 1)[0]
                      for p in (h_after["problems"] or []))
    check("[D] 新增桶未引入新 problem 种类（不新增分区失效类报错）",
          kinds_after <= kinds_before,
          "before=%s after=%s" % (sorted(kinds_before), sorted(kinds_after)))
    nzf_before = sum("分区失效" in p for p in (h_before["problems"] or []))
    nzf_after = sum("分区失效" in p for p in (h_after["problems"] or []))
    check("[D] 不含『分区失效』条目的新增（计数 %d → %d）"
          % (nzf_before, nzf_after),
          nzf_after <= nzf_before,
          "before=%s after=%s"
          % (h_before["problems"], h_after["problems"]))


# ---------------------------------------------------------------------------
# [E] 层隔离：contextual 层节点不进 knowledge 桶、知识桶计数不变
# ---------------------------------------------------------------------------

def test_e_layer_isolation():
    global _CG
    print("[E] 层隔离：contextual 层节点不进 knowledge 桶、桶计数不变")
    pre_ctx_buckets = dict(_CG.index["buckets"] or {})
    _CG.add("ctx1",
            "情境层节点：不参与分桶（contextual 不在 BUCKETED_LAYERS）",
            "contextual", tags=["domain:域C"])
    _CG.flush()
    e = _CG.index["nodes"]["ctx1"]
    check("[E] contextual 节点索引 bucket 为假值（不落入任何 knowledge 桶）",
          not e.get("bucket"),
          "bucket=%r" % (e.get("bucket"),))
    check("[E] contextual 节点落在 contextual/ 层目录（非 knowledge 桶树）",
          str(e.get("path", "")).startswith("contextual/"),
          "path=%r" % (e.get("path"),))
    check("[E] contextual 写入后 knowledge 桶计数完全不变",
          _CG.index["buckets"] == pre_ctx_buckets,
          "got=%s pre=%s" % (_CG.index["buckets"], pre_ctx_buckets))


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

def main():
    global passed, failed, _CG, _ROOT
    print("===== md_cg.test_t21a_extensible"
          "（分桶可扩展：加新桶不触发全量迁移） =====")
    prev = os.environ.get(_ENV)
    os.environ[_ENV] = "1"        # 显式开启：写入侧 domain 注入与桶计算才生效
    try:
        test_a_initial_lib()
        test_b_new_bucket()
        test_c_zero_migration()
        test_d_health()
        test_e_layer_isolation()
    finally:
        if prev is not None:
            os.environ[_ENV] = prev
        else:
            os.environ.pop(_ENV, None)
        if _CG is not None:
            try:
                _CG.close()
            except Exception:                    # noqa: BLE001
                pass
        if _ROOT is not None:
            shutil.rmtree(_ROOT, ignore_errors=True)   # 临时库用完即清理
    print("\n===== t21a extensible：%d 通过，%d 失败 ====="
          % (passed, failed))
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    sys.exit(main())