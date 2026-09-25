# -*- coding: utf-8 -*-
"""灵枢自库端到端检索评测（中文 · 自然问句 vs 关键词对照 · 生产读路径）

实测方式（用户指定）：mdcg 的读检索——spawn python -m md_cg.mcp_server（stdio JSON-RPC，
与 DSH 插件 src/lib/mdcg_client.ts 同款生产路径），逐题调 cg(op=read, query=...)，
只收 top-10 候选的 node.id 与 score，判 gold 节点命中。

gold = 已落盘（索引可见）的已知节点；审核队列 pending 提案对检索不可见（如实记录为
发现，不进评测集）。运行环境继承 MDCG_TOKEN（designer/internal 档）。
"""
import json, subprocess, sys, os, time

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

# ── 测试集：20 题 · 自然问句 → gold（已落盘节点）──────────────────────────
CASES = [
    # (自然问句, [gold_node_ids], 关键词对照组)
    ("hive 的 serve 怎么判断还活着？", ["mem_1789612355948"], "serve 存活 判据 三层 心跳 pid"),
    ("双实例互验怎么防止验证者作弊？", ["mem_1789602635975"], "互验 判据冻结 A3 验证者 指纹"),
    ("任务派发应该按什么原则分层决策？", ["mem_1789605410646"], "任务派发 三层决策 L1 L2 L3 分层原则"),
    ("蜂群健康评分的 integrity 因子是怎么算的？", ["swarm_v061_integrity_fix"], "蜂群 integrity 健康评分 验签 aggregate_report"),
    ("全局截断 cap 会造成哪些检索可见性问题？", ["mem_1789511615088"], "GLOBAL_CAP 截断 检索 可见性 T3 importance"),
    ("冷验证队列的回执什么情况下会报假成功？", ["mem_1789897251107"], "冷队列 回执 诚实 patrol_check propagate_depth"),
    ("英文语料用中文索引检索效果怎么样？", ["mem_1789132609619"], "LongMemEval 中文层 探针 英文原文 载荷回填"),
    ("检索扩散 reach 功能默认是开的吗？", ["mem_1789795794376"], "reach opt-in MDCG_REACH 收敛层 接线"),
    ("记忆怎么按热度分层来加速检索？", ["mem_1789803443800"], "热温冷 分层检索 热路径缓存 冷路径 异步验证"),
    ("LLM 批次修复第二轮还是不过怎么办？", ["mem_1789666192335"], "fix pass 二轮 REJECT held 重生成"),
    ("子任务上下文快满了怎么交接？", ["mem_1789548798424"], "handoff 满上下文 换人续跑 progress.jsonl"),
    ("记忆条目的过期和观测变旧怎么区分？", ["mem_1789539356385"], "stale 时间窗 失效判据 observation_aged observation_aged 信息差"),
    ("代码提交推送到公开仓库前要做什么检查？", ["mem_1789612355948"], "提交 推送 双清单 门禁 隐私脱敏 扫描"),
    ("多个智能体共用一份权限时怎么区分是谁干的？", ["mem_1789122153945"], "嵌套身份 权限域 归因 进程 会话"),
    ("DSH 的会话 id 关机重启后会变吗？", ["mem_1789100285255"], "DSH 会话 id 持久 projcache resume"),
    ("对话日志怎么自动挖出错误和修复的配对？", ["node_02fe882d_1788905562143", "doc_4a3accff94d6"], "fix pairs 自动挖掘 行为日志 错误 修复 负记忆"),
    ("令牌放在系统环境变量里有什么安全风险？", ["mem_1789099723060"], "MDCG_TOKEN Machine 作用域 部署 按 身份授权 缺口"),
    ("服务进程的随机会话 id 会带来什么问题？", ["mem_1789099936556"], "Principal.session 进程随机 uuid 会话身份 前置缺口"),
    ("查询词完全命不中桶的时候检索会怎么走？", ["mem_1789511615088"], "no_key_match T3 全量兜底 importance 排序"),
    ("白箱知识库在进程里怎么被调用？", ["code_d98d1f5aa78e", "doc_3942cfca7bdf"], "白箱 引擎 进程内 门面 engine call_tool"),
]


class Client:
    def __init__(self):
        env = dict(os.environ)
        if not env.get("MDCG_ROOT"):
            raise SystemExit("须设 MDCG_ROOT 指向被测记忆库根（见同目录实测报告的复现节）")
        self.p = subprocess.Popen(
            [sys.executable, "-X", "utf8", "-m", "md_cg.mcp_server"],
            cwd=REPO, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL, env=env,
        )
        self._id = 0
        self._call("initialize", {"protocolVersion": "2024-11-05", "capabilities": {},
                                  "clientInfo": {"name": "self-bench", "version": "1.0"}})
        self.p.stdin.write((json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"}) + "\n").encode())
        self.p.stdin.flush()

    def _call(self, method, params):
        self._id += 1
        req = {"jsonrpc": "2.0", "id": self._id, "method": method, "params": params}
        self.p.stdin.write((json.dumps(req, ensure_ascii=False) + "\n").encode("utf-8"))
        self.p.stdin.flush()
        deadline = time.time() + 120
        while time.time() < deadline:
            line = self.p.stdout.readline().decode("utf-8", "replace").strip()
            if not line:
                continue
            try:
                return json.loads(line)
            except json.JSONDecodeError:
                continue  # 启动横幅等非 JSON 行
        return {"error": "timeout-waiting-json-line"}

    def read(self, query):
        r = self._call("tools/call", {"name": "cg", "arguments": {"op": "read", "query": query}})
        # 返回 {result:{content:[{type:text,text:json串}]}} 或 error
        if "error" in r:
            return {"error": str(r["error"])[:120]}
        try:
            txt = r["result"]["content"][0]["text"]
            return json.loads(txt)
        except Exception as e:
            return {"error": f"parse:{e}"}

    def close(self):
        try:
            self.p.stdin.close(); self.p.wait(timeout=5)
        except Exception:
            self.p.kill()


def top_ids(resp, k=10):
    if not isinstance(resp, dict) or "results" not in resp:
        return [], (resp.get("error") if isinstance(resp, dict) else "no-results")[:80], None
    rs = resp["results"][:k]
    ids = [x["node"]["id"] for x in rs]
    meta = resp.get("meta", {})
    return ids, meta.get("tier"), [round(x.get("score", 0), 4) for x in rs]


def hit_stats(hits_pos):
    h1 = sum(1 for p in hits_pos if p is not None and p < 1)
    h5 = sum(1 for p in hits_pos if p is not None and p < 5)
    h10 = sum(1 for p in hits_pos if p is not None and p < 10)
    return h1, h5, h10


def main():
    cli = Client()
    rows = []
    for nat_q, golds, kw_q in CASES:
        row = {"q": nat_q, "golds": golds}
        for arm, q in (("nat", nat_q), ("kw", kw_q)):
            resp = cli.read(q)
            ids, tier, scores = top_ids(resp)
            pos = next((i for i, nid in enumerate(ids) if nid in golds), None)
            row[arm] = {"pos": pos, "tier": tier, "top1": ids[0] if ids else None,
                        "top1_is_gold": bool(ids and ids[0] in golds),
                        "n_res": len(ids)}
            time.sleep(0.1)
        rows.append(row)
        m = row["nat"]
        print(f"[{m['tier'] or '?':>16}] nat pos={str(m['pos']):>4}  kw pos={str(row['kw']['pos']):>4}  {nat_q[:34]}")
    cli.close()

    for arm in ("nat", "kw"):
        h1, h5, h10 = hit_stats([r[arm]["pos"] for r in rows])
        n = len(rows)
        print(f"\n===== {arm}: hit@1={h1}/{n} ({h1/n:.0%})  hit@5={h5}/{n} ({h5/n:.0%})  hit@10={h10}/{n} ({h10/n:.0%})")
    tiers = {}
    for r in rows:
        tiers[r["nat"]["tier"]] = tiers.get(r["nat"]["tier"], 0) + 1
    print("nat tier 分布:", tiers)
    out = os.path.join(os.path.dirname(os.path.abspath(__file__)), "self_bench_result.json")
    with open(out, "w", encoding="utf-8") as f:
        json.dump(rows, f, ensure_ascii=False, indent=1)
    print("明细 →", out)


if __name__ == "__main__":
    main()
