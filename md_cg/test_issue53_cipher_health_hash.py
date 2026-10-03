# -*- coding: utf-8 -*-
# 功能名：issue #53 三缺陷守卫——密文域标签(A) / 桶计数单点(B) / 写盘口内容指纹同步(C)
# 生效条件：md_cg/routing.py 的 `classify_text` 密文拦截与「单桶」文案、md_cg/mdcg.py 的
#           `backfill_big_domain` 密文计数分支 / `_set_index_entry`+`_bucket_shift` 桶计数
#           单点 / `_write_node` 内容指纹同步 / `health` 的 bucket_scope 自述在位时成立；
#           沙箱条件：所有库根一律 tempfile.mkdtemp，绝不触在役库与在役服务；
#           本文件只读源码，变异时只写目标文件且在 finally 里按原始字节复原。
# 子功能：钉消费方看得见的目标语义（报告 issue #53 三条逐条对应）：
#   A 密文不得被当可分类正文：`classify_text(密文)` 恒 None（含 GDP 撞词形态）；
#     backfill 不写密文节点标签、ciphertext 计数单列且各计数为互斥分区；明文对照不误伤
#   B 桶计数是单点事务：同桶覆写零动作、换桶撤旧加新、删除归零删键、读数自洽
#     （nodes==带桶条目数）且带 bucket_scope 覆盖面自述
#   C 重封（密文重写）必须同步索引内容指纹：update_tags/append_edge 后 entry.content_hash
#     仍落在盘面双形态内、reconcile 零假漂移、跨 close/重开仍零假漂移
# 执行：python -X utf8 -m md_cg.test_issue53_cipher_health_hash
#       python -X utf8 -m md_cg.test_issue53_cipher_health_hash --mutation=all
# 验证方式：本文件自跑（自带断言计数、live 计数与退出码 rc=0/1）；定点变异自证见
#           --mutation（把每处修复逐点抽回改动前语义 → 本守卫必红且红项名可贴出；
#           变异在 finally 中按原始字节复原并回读核对逐字节相等 → 无残余）。
# 不适用条件：情感交互｜闲聊｜纯查询无改动；routing 阈值面与既有区块守卫（test_m3_h9 /
#           test_retr_s1）的判据面不在本席改动面内。
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile

# ── 隔离前置：在任何 md_cg 子模块 import 之前把根指到临时目录 ──
_TMP = tempfile.mkdtemp(prefix="i53_")
os.environ["MDCG_AUX_ROOT"] = os.path.join(_TMP, "auxroot")
os.environ["MDCG_ROOT"] = os.path.join(_TMP, "cgroot")
for _k in ("MDCG_TOKEN", "MDCG_TENANT", "MDCG_CLEARANCE", "MDCG_SESSION",
           "DSH_SESSION_ID", "MDCG_LEGACY_ENV_AUTH", "MDCG_LEGACY_ENV_ADMIN",
           "MDCG_CAN_ADMIN", "MDCG_CAN_WRITE", "MDCG_STATE_ROOT",
           "MDCG_DATA_ROOT", "MDCG_TENANT_REGISTRY", "MDCG_VERIFIER_MODULES"):
    os.environ.pop(_k, None)
os.environ["MDCG_RETRIEVAL_PIPELINE"] = "1"      # A/B 组前置（回填/域标签面）

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from md_cg import nodefile, routing                  # noqa: E402
from md_cg.mdcg import MdCG                          # noqa: E402
from md_cg.mdcos import MdCGOS, MdCGSecure           # noqa: E402
from md_cg.security import Principal                 # noqa: E402

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:                                    # noqa: BLE001
    pass

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

PASS = FAIL = LIVE = 0
LIVE_FLOOR = 10
FAILS = []
_OPEN = []

TEST_KEY = bytes(range(32))          # 合成测试钥；绝不触碰真实主密钥面

#: GDP 三连是唯一实测命中形态（BIG_DOMAINS 里唯一的拉丁词是「经济」的 GDP）
CIPHER_GDP = "<!-- mdcg-enc:v1:QUJDREVGGDPQUJDREVG -->"
CIPHER_PLAIN = "<!-- mdcg-enc:v1:QUJDREVGQUJDREVG -->"
BODY = ("# 功能名：issue53 探针\n"
        "# 生效条件：守卫临时库\n"
        "# 子功能：素材节点\n"
        "# 执行：cg.add\n"
        "# 验证方式：本守卫断言\n"
        "# 不适用条件：无\n"
        "守卫探针正文。\n")


def check(name, cond, detail="", live=False):
    global PASS, FAIL, LIVE
    if live:
        LIVE += 1
    if cond:
        PASS += 1
        print("  [PASS] %s" % name)
    else:
        FAIL += 1
        FAILS.append(name)
        print("  [FAIL] %s · %s" % (name, detail))


def _mk(rel, cls=MdCGOS, **kw):
    cg = cls(os.path.join(_TMP, rel), autoflush=0, **kw)
    _OPEN.append(cg)
    return cg


def _put_raw(lib, nid, layer, content, sens=None):
    """手工落一个节点文件（可造密文形态正文——基类写入不做封装）。"""
    fm = {"id": nid, "layer": layer, "modality": "text", "importance": 0.5,
          "confidence": 0.6, "condition_space": {"time_window": [1.0, 9e9]},
          "tags": [], "created_at": 1.0, "access_count": 0, "last_access": 0,
          "edges": [], "verification_basis": None,
          "non_applicable_conditions": [], "evidence_count": 0,
          "positive_evidence": 0, "negative_evidence": 0}
    if sens:
        fm["sensitivity"] = sens
    p = os.path.join(lib, layer, nid + ".md")
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w", encoding="utf-8") as f:
        f.write(nodefile.dumps(fm, content))


def _disk_match(cg, nid):
    """entry.content_hash 是否落在盘面双形态接受集（reconcile 同口径）。"""
    e = cg.index["nodes"][nid]
    p = os.path.join(cg.root, e["path"])
    with open(p, encoding="utf-8") as f:
        _fm, content = nodefile.loads(f.read())
    raw = nodefile.content_hash(content or "")
    norm = nodefile.content_hash((content or "").rstrip("\n"))
    return e.get("content_hash") in (raw, norm), e.get("content_hash"), raw, norm


def _close_all():
    for cg in _OPEN:
        try:
            cg.close()
        except Exception:                            # noqa: BLE001
            pass


def _cleanup():
    import gc
    import time
    for _ in range(6):
        shutil.rmtree(_TMP, ignore_errors=True)
        if not os.path.exists(_TMP):
            return
        gc.collect()
        time.sleep(0.25)


# ───────────────────────── A：密文域标签 ─────────────────────────

def group_a():
    print("\n【A】issue #53-A：密文不得被当可分类正文")
    check("A1 classify_text 对密文（含 GDP 撞词形态）恒 None",
          routing.classify_text(CIPHER_GDP) is None
          and routing.classify_text(CIPHER_PLAIN) is None,
          "%r / %r" % (routing.classify_text(CIPHER_GDP),
                       routing.classify_text(CIPHER_PLAIN)))
    check("A2 明文对照不误伤：GDP 明文字面仍归「经济」",
          routing.classify_text("GDP 与市场") == "经济",
          repr(routing.classify_text("GDP 与市场")))

    lib = os.path.join(_TMP, "lib_a")
    os.makedirs(lib, exist_ok=True)
    _put_raw(lib, "a_cip_gdp", "contextual", CIPHER_GDP, sens="private")
    _put_raw(lib, "a_cip_ok", "contextual", CIPHER_PLAIN, sens="private")
    _put_raw(lib, "a_plain", "contextual", "# 功能名：x\n计算机与算法内容\n")
    cg = MdCG(lib)                       # 基类＝backfill CLI 的同款打开方式
    st = cg.backfill_big_domain()
    check("A3 回填不给密文写假标签（修前：GDP 形态被判「经济」并落盘）",
          st["written"] == 1
          and (cg.get("a_cip_gdp")["frontmatter"] or {}).get("big_domain") is None
          and (cg.get("a_cip_ok")["frontmatter"] or {}).get("big_domain") is None
          and cg.get("a_plain")["frontmatter"].get("big_domain") == "计算机",
          str(st), live=True)
    check("A4 ciphertext 独立计数且各计数为互斥分区（和 == seen）",
          st.get("ciphertext") == 2
          and (st["written"] + st["already"] + st["no_signal"]
               + st["unreadable"] + st["ciphertext"] + st["index_synced"]
               == st["seen"]),
          str(st), live=True)
    st2 = cg.backfill_big_domain()
    check("A5 二次回填：密文仍走 ciphertext（不被 already 假确认、不重写）",
          st2.get("ciphertext") == 2 and st2["already"] == 1
          and st2["written"] == 0, str(st2))
    cg.close()


# ───────────────────────── B：桶计数单点 ─────────────────────────

def group_b():
    print("\n【B】issue #53-B：桶计数单点（覆写零虚高 / 换桶撤旧加新 / 归零删键）")
    cg = _mk("lib_b")
    cg.add("b1", BODY, layer="knowledge")
    cg.flush()
    check("B1a 首次写入计数 1（前置）",
          dict(cg.index["buckets"]) == {"orphan": 1}, str(cg.index["buckets"]))
    cg.add("b1", BODY + "覆写。\n", layer="knowledge")
    check("B1b 同桶覆写不虚高（修前：{'orphan': 2}）",
          dict(cg.index["buckets"]) == {"orphan": 1}, str(cg.index["buckets"]),
          live=True)
    cg.flush()
    cg.update_tags("b1", add=["t"])
    check("B1c update_tags 不动桶计数（物理未动）",
          dict(cg.index["buckets"]) == {"orphan": 1}, str(cg.index["buckets"]))

    cg.add("b2", BODY, layer="knowledge", tags=["domain:甲"])
    cg.flush()
    b_old = routing.bucket_dir(routing.normalize_domain("甲"))
    b_new = routing.bucket_dir(routing.normalize_domain("乙"))
    has_old = b_old in cg.index["buckets"]
    cg.add("b2", BODY + "换桶覆写。\n", layer="knowledge", tags=["domain:乙"])
    check("B2 换桶覆写：旧桶撤、新桶加（净变化守恒）",
          has_old and b_old not in cg.index["buckets"]
          and cg.index["buckets"].get(b_new) == 1
          and sum(cg.index["buckets"].values()) == 2,
          "%s | old_in=%s" % (cg.index["buckets"], has_old), live=True)
    cg.flush()

    cg.forget("b2", reason="守卫归零删键探针")
    check("B3 删除路径归零删键（counts 无 0 值残留、总数守恒）",
          b_new not in cg.index["buckets"]
          and sum(cg.index["buckets"].values()) == 1,
          str(cg.index["buckets"]), live=True)

    h = cg.health()
    n_bucketed = sum(1 for e in list(cg.index["nodes"].values())
                     if e.get("bucket"))
    check("B4 health 读数自洽且带覆盖面自述（nodes==带桶条目数 / bucket_scope）",
          h.get("nodes") == n_bucketed
          and h.get("bucket_scope") == ["knowledge"],
          "nodes=%s n=%s scope=%s" % (h.get("nodes"), n_bucketed,
                                      h.get("bucket_scope")), live=True)
    check("B5 修复后单桶文案不再称「全库」（统计面已如实）",
          any("单桶" in p for p in (h.get("problems") or []))
          and not any("全库" in p for p in (h.get("problems") or [])),
          str(h.get("problems")))
    cg.close()


# ───────────────────────── C：写盘口内容指纹 ─────────────────────────

def group_c():
    print("\n【C】issue #53-C：重封必须同步索引内容指纹（零假漂移）")
    pri = Principal(clearance="secret", actor="i53")
    lib = os.path.join(_TMP, "lib_c")
    cg = _mk("lib_c", cls=MdCGSecure, principal=pri, master_key=TEST_KEY)
    nid = cg.add("c_priv", BODY + "私密。\n", layer="contextual",
                 sensitivity="private")
    cg.add("c_plain", BODY + "明文。\n", layer="contextual")
    cg.flush()
    m0 = _disk_match(cg, nid)
    check("C1 写入后指纹即落入盘面双形态（前置）", m0[0], str(m0), live=True)
    cg.update_tags(nid, add=["t1"])
    m1 = _disk_match(cg, nid)
    check("C2 update_tags 重封后指纹仍同步（修前：停在旧密文）",
          m1[0] and m1[1] != m0[1], str(m1), live=True)
    cg.append_edge(nid, {"target": "x", "relation_type": "derived_from"})
    m2 = _disk_match(cg, nid)
    check("C3 append_edge 重封后指纹仍同步", m2[0], str(m2))
    cg.flush()
    rep = cg.reconcile_state(apply=False)
    check("C4 对账零假漂移（修前：hash_drift=['c_priv']）",
          rep["hash_drift"] == [], str(rep["hash_drift"]), live=True)
    cg.close()

    # 跨 close / 重开：毒若未根治会随 compact 快照持久（issue #53-C 实测路径）
    cg2 = _mk("lib_c", cls=MdCGSecure, principal=pri, master_key=TEST_KEY)
    rep2 = cg2.reconcile_state(apply=False)
    m3 = _disk_match(cg2, nid)
    check("C5 重开后仍零假漂移且指纹同步（跨进程持久面）",
          rep2["hash_drift"] == [] and m3[0], str(rep2["hash_drift"]),
          live=True)
    check("C6 明文节点对照：重写后指纹不漂（内容未变，零误伤）",
          _disk_match(cg2, "c_plain")[0], str(_disk_match(cg2, "c_plain")))
    cg2.close()


# ───────────────────────── 主流程 ─────────────────────────

def main():
    print("【⓪】隔离自证")
    check("0a 临时根内（不触在役库）",
          os.path.abspath(_TMP).startswith(os.path.abspath(tempfile.gettempdir())),
          _TMP, live=True)
    group_a()
    group_b()
    group_c()
    print("\n" + "=" * 66)
    print("PASS=%d  FAIL=%d  LIVE=%d（floor=%d）" % (PASS, FAIL, LIVE, LIVE_FLOOR))
    check("live 断言数不低于 floor", LIVE >= LIVE_FLOOR, "live=%d" % LIVE)
    if FAILS:
        print("失败项：" + "；".join(FAILS))
    return 0 if FAIL == 0 else 1


# =========================================================================
# 定点变异（把每处修复逐点抽回改动前语义）——字节保真改写 → 跑 → finally 复原
# =========================================================================

def _read_bytes(rel):
    with open(os.path.join(_REPO, rel), "rb") as f:
        return f.read()


def _j(*lines):
    return "\n".join(lines) + "\n"


MUTATIONS = {
    # A：classify_text 单点去掉密文拦截 ⇒ A1 红
    "a_classify": ("md_cg/routing.py",
                   "    if crypto.is_encrypted(text):\n        return None\n",
                   "    if False:\n        return None\n"),
    # A：backfill 显式计数分支抽掉（单点仍在，故 A3 仍绿、A4 计数红）
    "a_backfill": ("md_cg/mdcg.py",
                   "            if crypto.is_encrypted(content):\n",
                   "            if False:\n"),
    # B：桶计数退回「同 id 无条件 +1」⇒ B1b 红
    "b_bucket": ("md_cg/mdcg.py",
                 _j("        if _ob != _nb:",
                    "            self._bucket_shift(_ob, -1)",
                    "            self._bucket_shift(_nb, +1)"),
                 _j("        if _nb:",
                    "            self._bucket_shift(_nb, +1)")),
    # C：写盘口指纹同步段抽掉 ⇒ C2/C4 红
    "c_hash": ("md_cg/mdcg.py",
               _j("        _entry = self.index[\"nodes\"].get(node_id)",
                  "        if _entry is not None:",
                  "            _entry[\"content_hash\"] = nodefile.content_hash(sealed)"),
               _j("        _entry = None",
                  "        if _entry is not None:",
                  "            _entry[\"content_hash\"] = nodefile.content_hash(sealed)")),
}


def _run_child():
    env = dict(os.environ)
    env["PYTHONUTF8"] = "1"
    p = subprocess.run([sys.executable, "-X", "utf8", "-m",
                        "md_cg.test_issue53_cipher_health_hash"],
                       cwd=_REPO, env=env, capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    return p.returncode, (p.stdout or "") + (p.stderr or "")


def _mutate(name):
    rel, old, new = MUTATIONS[name]
    path = os.path.join(_REPO, rel)
    raw = _read_bytes(rel)
    text = raw.decode("utf-8")
    if text.count(old) != 1:
        raise SystemExit("[MUT] %s：锚点命中 %d 次（应为 1）——树已变，请复核"
                         % (name, text.count(old)))
    try:
        with open(path, "wb") as f:
            f.write(text.replace(old, new, 1).encode("utf-8"))
        rc, out = _run_child()
    finally:
        with open(path, "wb") as f:
            f.write(raw)
    restored = _read_bytes(rel) == raw
    reds = [ln.strip() for ln in out.splitlines() if "[FAIL]" in ln]
    print("\n" + "=" * 66)
    print("[MUT] %s（%s）→ 子进程 rc=%d" % (name, rel, rc))
    for ln in reds:
        print("      RED " + ln)
    print("[MUT] 红项数 = %d" % len(reds))
    print("[MUT] 恢复核对：%s 逐字节复原=%s" % (rel, restored))
    return rc, len(reds), restored


if __name__ == "__main__":
    args = list(sys.argv[1:])
    _mut = [a for a in args if a.startswith("--mutation")]
    if _mut:
        want = _mut[-1].split("=", 1)[1] if "=" in _mut[-1] else "all"
        names = list(MUTATIONS) if want == "all" else [want]
        bad = []
        for nm in names:
            if nm not in MUTATIONS:
                raise SystemExit("未知变异：%s" % nm)
            rc, nred, ok = _mutate(nm)
            if rc == 0 or nred == 0 or not ok:
                bad.append(nm)
        print("\n[SUMMARY] 变异 %d 项；未变红或未复原的：%s"
              % (len(names), bad or "无"))
        _close_all()
        _cleanup()
        sys.exit(1 if bad else 0)
    try:
        rc = main()
    finally:
        _close_all()
        _cleanup()
    sys.exit(rc)
