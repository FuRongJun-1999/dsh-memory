# -*- coding: utf-8 -*-
"""召回记数即时落盘守卫（E-T63a t1 / 2026-10-11）。

运行（两路都必须能跑，退出码 0 = 通过）：
  python D:\\wook\\lingshu-src\\md_cg\\test_t63a_access_count.py   （直接跑，gate_cmd）
  python -m md_cg.run_tests md_cg -k t63a                        （仓根，-m 路）

病灶（Lead 侦察钉死，mdcg.py:5034）
-----------------------------------
`record_access()` 只写 `_access.log`；折叠落盘（frontmatter 的
`access_count` 递增 / `last_access` 变新）唯一触发点是 sustain 的
`access_log_backlog` 诊断码，而该码要求 `_acc_lines > ACCESS_LOG_COMPACT_LINES`
(=500，sustain.py:114,873-877)。本地库实测 401 行 < 500 ⇒ **永不折叠** ⇒
frontmatter `access_count` 恒 0、`_index.json` 重建取 fm 仍 0。
即「召回后节点的 access_count 递增、last_access 变新」在一台**不跑 sustain
常驻循环**的机器上永远观察不到。

判据（对应 accept ①②③④）
--------------------------
  G1 **主判据**：新临时库写 3 个节点 → 一次 `cg.search(record=True)` 命中其中
     节点 → 断言命中节点 `access_count` 比召回前**大**、`last_access` **变新且
     等于本次召回时间**（当前时间附近）。frontmatter 与索引快照**两路都断言**
     （accept 明说「从节点 frontmatter 或索引快照读取均可」，两路都查更硬）。
  G2 **脱离 sustain**：本测试全程**不 import sustain、不调用任何 sustain
     函数**，且临时库远小于 500 行日志阈值——绿色即证明落盘与「常驻循环」
     和「>500 行才折叠」都无关。另加一条**进程级**证据：同一临时库**新开一个
     MdCG 实例**（重建索引路径，取 fm），计数依然在 ⇒ 是**真落盘**，不是内存假象。
  G3 **契约②·审计痕迹**：`_access.log` 仍按 append_jsonl **逐行追加**——召回前后
     行数**恰好 +1**、末行含命中节点 id、JSON 可解析、`t`/`ids`/`tier` 三键形状不变。
  G4 **契约②·对外行为**：`access_counts()` 返回形状仍是 `(counts, last)` 二元组、
     counts 为该 id 的**日志行计数**；`compact_access()` 返回值仍是 int（写盘节点数），
     且折叠后日志被清空——两条既有契约都向后兼容。
  G5 **契约③·签名不变**：`search` 形参表**逐字**含既有参数（含 `record` 默认 True），
     `record=False` 时**一次都不记**（日志不增、计数不增）。
  G6 **契约④·非 O(n) 热点**：只命中 1 个节点时，**只有该节点文件被改写**——
     同库另一个未被命中的节点文件 `mtime_ns` / 字节内容**逐字不变**。这把
     「可只写命中节点」钉成判据，防止退化成「每命中一次全盘重写整个库」。

沙箱注记：全程在 tempfile 临时目录里造库（退出前 shutil.rmtree），**绝不碰
真实 ~/.mdcg**；`_access.log` 路径取 `cg.access_log`（mdcg.py:1520 单点），
不自己拼路径。
"""
from __future__ import annotations

import inspect
import json
import os
import shutil
import sys
import tempfile
import time

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if __package__:
    from .mdcos import MdCG
else:                                  # 直接 `python md_cg/test_t63a_access_count.py` 也能跑
    sys.path.insert(0, _REPO)
    from md_cg.mdcos import MdCG

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

QUERY = "苹果 章节 认知图"

# 三个节点：一个强命中（n_apple）、一个弱命中（n_pear）、一个**绝不命中**
# 的对照节点（n_kiwi）——G6 靠它证明「未被命中的节点一个字节都没动」。
N_HIT = "n_apple"
N_WEAK = "n_pear"
N_OTHER = "n_kiwi"

_PASS = []
_FAIL = []


# 生效条件：cond 为真记录 PASS 并返回 True，否则记录 FAIL 并返回 False；n 为断言名。
def ok(cond: bool, n: str) -> bool:
    if cond:
        _PASS.append(n)
    else:
        _FAIL.append(n)
    return bool(cond)


# 生效条件：无前置；读 cg.access_log 的原始文本（不存在/读不出返回 ""）。
def _log_text(cg) -> str:
    try:
        with open(cg.access_log, encoding="utf-8", errors="replace") as fh:
            return fh.read()
    except OSError:
        return ""


# 生效条件：无前置；返回 _access.log 里非空行数。
def _log_lines(cg) -> int:
    return len([ln for ln in _log_text(cg).splitlines() if ln.strip()])


# 生效条件：node_id 在 cg 索引中时返回该条目的 access_count/last_access 二元组，否则 (None, None)。
def _snap(cg, node_id):
    e = cg.index["nodes"].get(node_id)
    if not e:
        return None, None
    return e.get("access_count"), e.get("last_access")


# 生效条件：node_id 在 cg 索引中时读盘返回其 frontmatter 的 access_count/last_access 二元组，读不到返回 (None, None)。
def _fm(cg, node_id):
    e = cg.index["nodes"].get(node_id)
    if not e:
        return None, None
    f, _c = cg._read(e)
    if f is None:
        return None, None
    return f.get("access_count"), f.get("last_access")


# 生效条件：node_id 对应节点文件可读时返回 (st_mtime_ns, 原始字节)，否则 (None, None)。
def _disk_stat(cg, node_id):
    e = cg.index["nodes"].get(node_id)
    if not e:
        return None, None
    p = cg._node_disk_path(e)
    try:
        st = os.stat(p)
        with open(p, "rb") as fh:
            return st.st_mtime_ns, fh.read()
    except OSError:
        return None, None


# 生效条件：在 root 造一个临时库并写 3 个节点（2 个可被 QUERY 命中 + 1 个对照），返回该 MdCG 实例。
def _mk(root) -> "MdCG":
    cg = MdCG(root)
    cg.add(N_HIT, "苹果 章节：认知图的第一条论据", layer="knowledge")
    cg.add(N_WEAK, "梨 与 苹果 的对比章节", layer="knowledge")
    cg.add(N_OTHER, "猕猴桃 甜点 烘焙 温度 记录", layer="knowledge")
    return cg


# 生效条件：临时库 cg 就绪时执行主判据——召回前记账基线、search(record=True)、
# 断言命中节点 access_count 递增且 last_access 变新（frontmatter + 索引两路）；返回命中的 id 列表。
def _g1_immediate_fold(cg):
    hits_before = _log_lines(cg)
    ok(hits_before == 0, "G1 前置：召回前 _access.log 为空（基线干净）")

    fm_c0, fm_t0 = _fm(cg, N_HIT)
    ix_c0, ix_t0 = _snap(cg, N_HIT)
    ok(fm_c0 == 0 and ix_c0 == 0,
       "G1 前置：召回前 %s access_count 为 0（fm=%r idx=%r）" % (N_HIT, fm_c0, ix_c0))

    t_before = time.time()
    results, _meta = cg.search(QUERY, k=5)
    t_after = time.time()

    hit_ids = [r[0]["id"] for r in results]
    ok(N_HIT in hit_ids,
       "G1 前置：%s 确实被本次召回命中（命中 %r）" % (N_HIT, hit_ids))
    if N_HIT not in hit_ids:
        return hit_ids                      # 没命中就无从谈递增，后续断言会连带失败

    fm_c1, fm_t1 = _fm(cg, N_HIT)
    ix_c1, ix_t1 = _snap(cg, N_HIT)

    ok(fm_c1 is not None and fm_c1 > fm_c0,
       "G1a frontmatter access_count 递增（%r → %r）" % (fm_c0, fm_c1))
    ok(ix_c1 is not None and ix_c1 > ix_c0,
       "G1b 索引快照 access_count 递增（%r → %r）" % (ix_c0, ix_c1))
    ok(fm_t1 is not None and fm_t1 > fm_t0,
       "G1c frontmatter last_access 变新（%r → %r）" % (fm_t0, fm_t1))
    ok(ix_t1 is not None and ix_t1 > ix_t0,
       "G1d 索引快照 last_access 变新（%r → %r）" % (ix_t0, ix_t1))
    # last_access 必须是**本次召回**的时间（不是某个陈旧值/未来值）：
    # 允许 1 秒余量吸收时钟抖动与 float 截断。
    ok(fm_t1 is not None and (t_before - 1.0) <= fm_t1 <= (t_after + 1.0),
       "G1e last_access 落在本次召回的时间窗内（%r ∈ [%r, %r]）"
       % (fm_t1, t_before, t_after))
    ok(fm_c1 == ix_c1 and fm_t1 == ix_t1,
       "G1f fm 与索引两路口径一致（fm=%r/%r idx=%r/%r）"
       % (fm_c1, fm_t1, ix_c1, ix_t1))
    return hit_ids


# 生效条件：临时库 cg 就绪时验证「脱离 sustain / 脱离 500 行阈值」——断言本模块未 import sustain、
# 日志行数远低于阈值，且新开实例（重建索引取 fm）仍读到计数；返回重建实例（供后续复用）或 None。
def _g2_detached_from_sustain(cg):
    ok("sustain" not in sys.modules,
       "G2a 本测试全程未 import sustain（落盘与常驻循环无关）")
    n = _log_lines(cg)
    ok(n < 500,
       "G2b 日志 %d 行 < 500（ACCCESS_LOG_COMPACT_LINES 阈值），仍已落盘" % n)

    # 进程级证据：新实例走 _load_index → 取 fm。计数仍在 ⇒ 真落盘。
    fm_c, fm_t = _fm(cg, N_HIT)
    try:
        cg2 = MdCG(cg.root)
    except Exception as exc:                        # noqa: BLE001
        ok(False, "G2c 重开临时库未抛异常：%r" % (exc,))
        return None
    r_c, r_t = _snap(cg2, N_HIT)
    ok(r_c is not None and r_c >= (fm_c or 0) and r_c > 0,
       "G2c 重开后索引仍读到 access_count=%r（真落盘，非内存假象）" % (r_c,))
    ok(r_t is not None and r_t > 0,
       "G2d 重开后 last_access 仍是有效时间戳（%r）" % (r_t,))
    return cg2


# 生效条件：cg 就绪且已发生一次召回时，验证契约②的审计痕迹——日志**恰好 +1 行**、末行 JSON 可解析
# 且含命中 id、三键形状未变（t/ids/tier）。
def _g3_audit_trail(cg, n_before):
    text = _log_text(cg)
    lines = [ln for ln in text.splitlines() if ln.strip()]
    ok(len(lines) == n_before + 1,
       "G3a 一次召回恰好追加 1 行日志（%d → %d）" % (n_before, len(lines)))
    try:
        rec = json.loads(lines[-1])
    except (ValueError, IndexError) as exc:
        ok(False, "G3b 末行可解析为 JSON：%r" % (exc,))
        return
    ok(isinstance(rec, dict), "G3b 末行是 JSON 对象（append_jsonl 逐行形态未变）")
    ok(set(rec.keys()) == {"t", "ids", "tier"},
       "G3c 记录形状未变，仍是 {t, ids, tier}（实为 %r）" % (sorted(rec.keys()),))
    ok(isinstance(rec.get("ids"), list) and N_HIT in rec["ids"],
       "G3d 记录含本次命中节点 id（ids=%r）" % (rec.get("ids"),))
    ok(isinstance(rec.get("t"), (int, float)) and rec["t"] > 0,
       "G3e 记录含有效时间戳 t=%r" % (rec.get("t"),))


# 生效条件：cg 就绪时验证契约②的对外行为向后兼容——access_counts() 返回 (counts,last) 二元组且 counts 为日志计数；
# compact_access() 返回 int 且折叠后日志被清空（既有语义不动）。
def _g4_public_contract(cg):
    got = cg.access_counts()
    ok(isinstance(got, tuple) and len(got) == 2,
       "G4a access_counts() 仍返回 (counts, last) 二元组（实为 %r）" % (type(got),))
    if not (isinstance(got, tuple) and len(got) == 2):
        return
    counts, last = got
    ok(isinstance(counts, dict) and isinstance(last, dict),
       "G4b access_counts() 两项均为 dict")
    ok(counts.get(N_HIT, 0) >= 1,
       "G4c access_counts() 仍按日志行计数（%s=%r）" % (N_HIT, counts.get(N_HIT)))
    ok(last.get(N_HIT, 0) > 0,
       "G4d access_counts() 的 last 仍是有效时间戳（%r）" % (last.get(N_HIT),))

    n = cg.compact_access()
    ok(isinstance(n, int) and not isinstance(n, bool),
       "G4e compact_access() 仍返回 int（实为 %r=%r）" % (type(n), n))
    ok(n >= 1, "G4f compact_access() 折叠了至少 1 个节点（n=%r）" % (n,))
    ok(_log_lines(cg) == 0, "G4g compact_access() 后日志被清空（既有语义）")


# 生效条件：无前置；静态断言 search 形参表**逐字**含既有参数名（含 record 默认 True），
# 证明契约③「不改变 search 的函数签名」；返回 True 表示通过。
def _g5_signature_unchanged():
    try:
        sig = inspect.signature(MdCG.search)
    except (TypeError, ValueError) as exc:          # noqa: BLE001
        ok(False, "G5a 可取到 search 签名：%r" % (exc,))
        return
    params = sig.parameters
    for p in ("query", "layer", "k", "context", "min_results", "record",
              "include_neg", "judge", "pools", "session", "branch",
              "validity", "start_time", "end_time", "start_operator",
              "end_operator", "time_axis", "view"):
        ok(p in params, "G5b search 仍含形参 %r（签名不许变）" % (p,))
    if "record" in params:
        ok(params["record"].default is True,
           "G5c search 的 record 默认仍为 True（语义不变）")


# 生效条件：在独立临时子库里验证 record=False 一次都不记（日志不增、计数不增），
# 再验证不传 record 的缺省 True 记一次——契约③的语义面钉死。
def _g6_record_false_and_scope(tmp):
    d = os.path.join(tmp, "semantics")
    os.makedirs(d, exist_ok=True)
    cg = _mk(d)
    base = _log_lines(cg)
    ix0 = _snap(cg, N_HIT)[0]

    cg.search(QUERY, k=5, record=False)
    ok(_log_lines(cg) == base,
       "G6a record=False 不写日志（%d → %d）" % (base, _log_lines(cg)))
    ok(_snap(cg, N_HIT)[0] == ix0,
       "G6b record=False 不折叠计数（%r → %r）" % (ix0, _snap(cg, N_HIT)[0]))

    cg.search(QUERY, k=5)                    # 缺省 True
    ok(_log_lines(cg) == base + 1,
       "G6c 不传 record 即记（缺省 True：%d → %d）" % (base, _log_lines(cg)))
    ok((_snap(cg, N_HIT)[0] or 0) > ix0,
       "G6d 缺省 True 时计数递增（%r → %r）" % (ix0, _snap(cg, N_HIT)[0]))


# 生效条件：在独立临时子库里验证契约④——只命中 1 个节点时，未被命中的节点文件
# mtime_ns 与字节内容逐字不变（折叠是 O(命中数) 受控写，不是全盘重写）。
def _g7_not_full_rewrite(tmp):
    d = os.path.join(tmp, "scope")
    os.makedirs(d, exist_ok=True)
    cg = MdCG(d)
    cg.add(N_HIT, "苹果 章节：认知图的第一条论据", layer="knowledge")
    cg.add(N_OTHER, "猕猴桃 甜点 烘焙 温度 记录", layer="knowledge")

    mt0, body0 = _disk_stat(cg, N_OTHER)
    ok(mt0 is not None and body0 is not None,
       "G7 前置：对照节点 %s 文件可读" % (N_OTHER,))

    results, _meta = cg.search("苹果 认知图", k=1)   # k=1 → 只命中 1 个节点
    hit_ids = [r[0]["id"] for r in results]
    ok(hit_ids == [N_HIT],
       "G7 前置：k=1 只命中 %s（实为 %r）" % (N_HIT, hit_ids))
    ok((_snap(cg, N_HIT)[0] or 0) > 0,
       "G7 前置：命中节点确实被折叠（count=%r）" % (_snap(cg, N_HIT)[0],))

    mt1, body1 = _disk_stat(cg, N_OTHER)
    ok(mt1 == mt0 and body1 == body0,
       "G7a 未被命中的节点文件 mtime_ns/字节逐字不变（非全盘重写）")
    ok(_snap(cg, N_OTHER)[0] == 0,
       "G7b 未被命中节点索引计数仍 0（未误伤）")


def main() -> int:
    tmp = tempfile.mkdtemp(prefix="t63a_acc_")
    try:
        cg = _mk(os.path.join(tmp, "main"))
        n_before = _log_lines(cg)
        _g1_immediate_fold(cg)
        _g2_detached_from_sustain(cg)
        _g3_audit_trail(cg, n_before)
        _g4_public_contract(cg)
        _g5_signature_unchanged()
        _g6_record_false_and_scope(tmp)
        _g7_not_full_rewrite(tmp)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    for n in _FAIL:
        print("  FAIL  %s" % n)
    print("\nt63a 召回记数即时落盘守卫：%d 通过，%d 失败"
          % (len(_PASS), len(_FAIL)))
    return 0 if not _FAIL else 1


if __name__ == "__main__":
    sys.exit(main())
