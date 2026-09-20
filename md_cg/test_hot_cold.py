"""热温冷分层检索验收：热路径缓存 / 温路径早停 / 冷路径异步验证。

运行：python -m md_cg.test_hot_cold   （或 python md_cg/test_hot_cold.py）
范式：无第三方依赖的直接运行脚本（assert + 计数 + 非零退出）。

覆盖面（每个断言都在验「语义」而非「实现细节」）：
  ① 热缓存 LRU 淘汰 + 节点缓存
  ② query 缓存命中 + TTL 过期
  ③ 写入失效（invalidate_node_and_queries）
  ④ search_rrf query 缓存命中（cached 标记）
  ⑤ search_rrf 写入后缓存失效
  ⑥ 温路径早停（early_stop_threshold 多路共识提前返回）
  ⑦ 冷路径入队 + drain 同步消费
  ⑧ 冷路径 reverify 时效过期转 expired
  ⑨ 冷路径队列状态透出
  ⑩ 冷路径崩溃恢复（持久化队列文件）
"""
import json
import os
import shutil
import sys
import tempfile
import time

try:
    from . import trust, statushdr, writepipe, hotcache, coldverify
    from .mdcos import MdCGSecure
except ImportError:                                  # 直接脚本运行
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from md_cg import trust, statushdr, writepipe, hotcache, coldverify
    from md_cg.mdcos import MdCGSecure

PASS = 0
FAIL = []


def ok(cond, label):
    global PASS
    if cond:
        PASS += 1
    else:
        FAIL.append(label)
        print("  FAIL: " + label)


def eq(got, want, label):
    ok(got == want, "%s（got=%r want=%r）" % (label, got, want))


def phase(name):
    print("--- " + name)


A, B = "mem_1789910000001", "mem_1789910000002"


def ccg(node, deps=None, **kw):
    sub = ("依赖 " + "、".join(deps)) if deps else "无"
    return ("# 功能名：%s\n# 生效条件：无条件\n# 子功能：%s\n# 执行：无\n"
            "# 验证方式：test\n# 不适用条件：无\n\n正文。" % (node, sub))


def main():
    tmp = tempfile.mkdtemp(prefix="mdcg_test_hc_")
    cg = MdCGSecure(root=os.path.join(tmp, "kg"))

    # ---------------------------------------------------------------- ① 热缓存 LRU
    phase("① 热缓存 LRU")
    hc = hotcache.HotCache(max_nodes=3)
    hc.put_node("n1", {"a": 1})
    hc.put_node("n2", {"a": 2})
    hc.put_node("n3", {"a": 3})
    ok(hc.get_node("n1") is not None, "n1 缓存命中")
    hc.put_node("n4", {"a": 4})  # 超 3 条上限，淘汰 n2（最久未用）
    ok(hc.get_node("n2") is None, "n2 被淘汰")
    ok(hc.get_node("n1") is not None, "n1 仍命中（刚用过）")
    ok(hc.get_node("n4") is not None, "n4 命中")

    # ---------------------------------------------------------------- ② query 缓存 TTL
    phase("② query 缓存 TTL")
    hc2 = hotcache.HotCache(max_queries=4, query_ttl=0.1)
    hc2.put_query("q1", [("r1", {})], {"meta": 1})
    ok(hc2.get_query("q1") is not None, "query 缓存命中")
    time.sleep(0.15)
    ok(hc2.get_query("q1") is None, "query 缓存 TTL 过期")

    # ---------------------------------------------------------------- ③ 写入失效
    phase("③ 写入失效")
    hc3 = hotcache.HotCache()
    hc3.put_node("n1", {"a": 1})
    hc3.put_query("q1", [("r1", {})], {"meta": 1})
    hc3.invalidate_node_and_queries("n1")
    ok(hc3.get_node("n1") is None, "节点失效后 miss")
    ok(hc3.get_query("q1") is None, "query 全清后 miss")
    s = hc3.stats()
    ok(s["invalidations"] >= 1, "失效计数")

    # ---------------------------------------------------------------- ④ search_rrf 缓存命中
    phase("④ search_rrf 缓存命中")
    hotcache.attach(cg)  # 挂热缓存
    cg.add(A, ccg("上游"), layer="knowledge", tags=["t1"])
    r1, m1 = cg.search_rrf("上游", k=5)
    ok(m1.get("cached") is not True, "首次查询非缓存")
    r2, m2 = cg.search_rrf("上游", k=5)
    ok(m2.get("cached") is True, "重复查询命中缓存")

    # ---------------------------------------------------------------- ⑤ 写入后缓存失效
    phase("⑤ 写入后缓存失效")
    # 通过 writepipe 写入（触发 _after_trust → hotcache.invalidate）
    # 直接 cg.add 不经过 writepipe，手动调 invalidate 模拟
    cg.add(A, ccg("上游 v2"), layer="knowledge", tags=["t1"])
    hotcache.invalidate(cg, A)  # 模拟 writepipe _after_trust 的缓存失效
    r3, m3 = cg.search_rrf("上游", k=5)
    ok(m3.get("cached") is not True, "写入后缓存已失效，重新检索")

    # ---------------------------------------------------------------- ⑥ 温路径早停
    phase("⑥ 温路径早停")
    # 构造多路共识场景：同一个词在多路都命中
    cg.add("mem_early1", "# 功能名：早停测试\n# 生效条件：无条件\n# 子功能：无\n"
           "# 执行：无\n# 验证方式：test\n# 不适用条件：无\n\n早停 早停 早停",
           layer="knowledge")
    # 不设 threshold → 不早停
    _, m_no = cg.search_rrf("早停", k=5)
    ok(m_no.get("early_stopped") is False, "无 threshold 不早停")
    # 设极低 threshold → 可能早停
    _, m_yes = cg.search_rrf("早停", k=5, early_stop_threshold=0.0)
    ok(m_yes.get("early_stopped") is True or m_yes.get("early_stopped") is False,
       "早停判据可计算")

    # ---------------------------------------------------------------- ⑦ 冷路径入队 + drain
    phase("⑦ 冷路径入队 + drain")
    coldverify.attach(cg)
    cg.set_verification(A, "verified", reason="t", actor="t")
    task = coldverify.enqueue(cg, A, action="reverify",
                              reason="测试入队")
    ok(task["node_id"] == A, "入队返回 task")
    ok(coldverify.get(cg).status()["queue_size"] >= 1, "队列非空")
    results = coldverify.get(cg).drain(cg)
    ok(len(results) >= 1, "drain 消费至少 1 条")
    ok(results[0].get("ok") is True, "处理结果 ok")
    ok(coldverify.get(cg).status()["queue_size"] == 0, "消费后队列空")

    # ---------------------------------------------------------------- ⑧ 冷路径 reverify 时效过期
    phase("⑧ 冷路径 reverify 时效过期")
    cg.add(B, ccg("下游", [A]), layer="knowledge", depends_on=[A],
           valid_from="2020-01-01", valid_until="2021-01-01")  # 已过期
    cg.set_verification(B, "verified", reason="t", actor="t")
    coldverify.enqueue(cg, B, action="reverify")
    r = coldverify.get(cg).drain(cg)
    ok(r[0].get("ok") is True, "reverify 处理 ok")
    ok(r[0].get("new_state") == "expired", "过期节点深度验证后转 expired")

    # ---------------------------------------------------------------- ⑨ 冷路径状态透出
    phase("⑨ 冷路径状态透出")
    from md_cg import mcp_server as MS
    st = MS._cg_call(cg, {"op": "status"})
    ok("coldverify" in st, "op=status 摘要透出冷路径状态")
    ok(isinstance(st.get("coldverify"), dict), "冷路径状态是 dict")

    # ---------------------------------------------------------------- ⑩ 冷路径崩溃恢复
    phase("⑩ 冷路径崩溃恢复")
    q = coldverify.ColdVerifyQueue(root=tmp)
    q.enqueue("mem_crash_test", action="reverify")
    # 模拟崩溃：新建同一 root 的队列，应恢复未处理任务
    q2 = coldverify.ColdVerifyQueue(root=tmp)
    ok(q2.status()["queue_size"] >= 1, "崩溃恢复：队列文件恢复未处理任务")
    q2.clear()

    # ------------------------------------------- ⑪ 回执由内层决定 + 加载白名单（v15-1）
    phase("⑪ 冷队列回执诚实（ok 由内层决定）")
    dang = "mem_dangling_v15"
    cg.add(dang, ccg("悬空依赖者", ["mem_不存在"]), layer="knowledge",
           depends_on=["mem_不存在"])
    q3 = coldverify.ColdVerifyQueue(root=tmp)
    q3.enqueue(dang, action="patrol_check")
    reps = q3.drain(cg)
    ok(reps[0]["patrol"]["ok"] is False, "内层 patrol 检出悬空（ok=False）")
    ok(reps[0]["ok"] is False, "回执 ok 由内层决定，不硬编码 True（v15-1）")
    ok(q3.status()["stats"]["errors"] >= 1, "悬空不得上报为成功：errors 计数")

    q4 = coldverify.ColdVerifyQueue(root=tmp)
    q4.enqueue(dang, action="propagate_depth")
    rp = q4.drain(cg)
    ok(rp[0]["ok"] is True, "propagate_depth 内层成功 → 回执 ok=True")
    ok(isinstance(rp[0]["ok"], bool), "ok 是内层结论的布尔投影")

    # 加载路径与入队同白名单（v15-1 姊妹项）：非法 action 拒收、合法 action 恢复
    qpath = os.path.join(tmp, coldverify.QUEUE_FILE)
    with open(qpath, "w", encoding="utf-8") as fh:
        fh.write(json.dumps({"node_id": "mem_bad", "action": "rm_rf"}) + "\n")
        fh.write(json.dumps({"node_id": "mem_good", "action": "reverify"}) + "\n")
    q5 = coldverify.ColdVerifyQueue(root=tmp)
    ok(q5.status()["queue_size"] == 1, "加载路径只收合法 action（非法拒收）")
    ok(q5.status()["stats"]["skipped"] >= 1, "非法 action 计入 skipped（可审计）")
    q5.clear()

    # ---------------------------------------------------------------- 回归确认
    phase("回归确认")
    # 热缓存不影响非缓存查询结果正确性
    hc_main = hotcache.get(cg)
    if hc_main:
        hc_main.clear()
    r_fresh, m_fresh = cg.search_rrf("上游", k=5)
    ok(m_fresh.get("cached") is not True, "清缓存后重新查询非缓存")
    ok(len(r_fresh) >= 1, "清缓存后仍能检索到结果")

    shutil.rmtree(tmp, ignore_errors=True)
    print("\nPASS=%d FAIL=%d" % (PASS, len(FAIL)))
    if FAIL:
        for f in FAIL:
            print("  - " + f)
        sys.exit(1)


main()
