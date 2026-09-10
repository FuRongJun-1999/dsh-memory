# -*- coding: utf-8 -*-
"""
智慧之书 · mock 云服务（零依赖 http.server）
==========================================
端点：
  POST /dex/query   {op, params}          七操作查询（读公开 · 任何灵枢智能体）
  POST /dex/upload  {entry, contributor}  上传已验证条目（verified 闸门 + 贡献记账）
  GET  /dex/ledger?contributor=X          贡献账本
  GET  /dex/status                        图谱元信息

运行：python wisdom_cloud.py [port]
"""
import json
import os
import sys
import threading
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

from wisdom_book import ConditionDex, _default_cs  # noqa: E402

CLOUD_DB = os.path.join(HERE, "wisdom-book-cloud.db")


def _cs_from_dict(d):
    """字典→ConditionSpace 还原（缺省字段落协议默认）。"""
    from aeis_core import ConditionSpace
    if not d:
        return _default_cs()
    try:
        tw = tuple(d.get("time_window") or (0.0, 9999999999.0))
    except Exception:
        tw = (0.0, 9999999999.0)
    return ConditionSpace(
        observation_position=d.get("observation_position", ""),
        observation_tool=d.get("observation_tool", ""),
        time_window=tw,
        existence_constraint=d.get("existence_constraint", ""))


class DexHandler(BaseHTTPRequestHandler):
    cloud = None  # ConditionDex 实例（由 run_server 注入）

    def log_message(self, *args):
        """静默访问日志：默认逐请求刷屏，覆写为空。"""
        pass

    def _send(self, obj, code=200):
        """JSON 应答统一出口：编码·头·状态码收口。"""
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _read(self):
        """读取请求体并按 UTF-8 JSON 解析。"""
        n = int(self.headers.get("Content-Length", 0))
        return json.loads(self.rfile.read(n).decode("utf-8"))

    # ---------------- GET ----------------

    def do_GET(self):
        """GET 三路分发：UI 页面·状态 API·数据端点。"""
        path = self.path.split("?")[0]
        qs = {}
        if "?" in self.path:
            qs = urllib.parse.parse_qs(self.path.split("?", 1)[1])
        if path in ("/", "/ui", "/index.html", "/ui/index.html", "/wisdom_ui.html"):
            self._send_html()
        elif path in ("/chat", "/chat.html", "/chat/index.html"):
            self._send_chat_html()
        elif path == "/dex/status":
            self._send(self._status())
        elif path == "/dex/ledger":
            c = qs.get("contributor", [None])[0]
            self._send(self._ledger(c))
        else:
            self._send({"error": "not_found"}, 404)

    def _send_chat_html(self):
        """普通人对话界面（H5 聊天式 · 第一智能入口）"""
        html_path = os.path.join(HERE, "chat.html")
        try:
            with open(html_path, "r", encoding="utf-8") as f:
                body = f.read().encode("utf-8")
        except OSError:
            self._send({"error": "chat_ui_not_found"}, 404)
            return
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_html(self):
        """人类学习/搜索界面（零依赖单页）"""
        html_path = os.path.join(HERE, "wisdom_ui.html")
        try:
            with open(html_path, "r", encoding="utf-8") as f:
                body = f.read().encode("utf-8")
        except OSError:
            self._send({"error": "ui_not_found"}, 404)
            return
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    # ---------------- POST ----------------

    def do_POST(self):
        """POST 分发：UTF-8 JSON 解析后按 path 派发（坏包 400）。"""
        try:
            body = self._read()
        except Exception:
            self._send({"error": "bad_json"}, 400)
            return
        path = self.path.split("?")[0]
        if path == "/chat":
            self._send(self._chat(body))
        elif path == "/dex/query":
            self._send(self._query(body))
        elif path == "/dex/upload":
            self._send(self._upload(body))
        else:
            self._send({"error": "not_found"}, 404)

    # ---------------- 普通人对话 ----------------

    def _chat(self, body):
        """普通人对话端点：人话检索 + 情感 + 记忆 + 诚实边界（chat_engine）
        记忆挂在 cloud 实例上（handler 每请求新建，cloud 是单例 → 跨请求共享）"""
        try:
            import chat_engine as _ce
            cloud = self.cloud
            if not hasattr(cloud, "_chat_memory"):
                cloud._chat_memory = {}
            return _ce.chat(cloud, body.get("message", ""),
                            session_id=body.get("session_id", "default"),
                            memory=cloud._chat_memory)
        except Exception as e:
            return {"error": f"chat_failed: {e}", "reply": "我暂时没反应过来，稍等再试？",
                    "hits": [], "emotion": None}

    # ---------------- 实现 ----------------

    def _query(self, body):
        """查询参数解析：query/domain/limit 三键归一。"""
        op = body.get("op", "")
        params = body.get("params") or {}
        d = self.cloud
        try:
            if op == "filter":
                return {"op": op, "results": d.dex_filter(**params)}
            if op == "respond":
                # 知识翻译体系全链路（四路融合：语义指纹+学科路由+二元组+神经索引）
                try:
                    import semantic_translate as _st
                    results = _st.graph_retrieve(d, params.get("condition", ""), limit=8)
                    return {"op": op, "results": results}
                except Exception:
                    return {"op": op, "results": d.dex_respond(
                        params.get("condition", ""))}
            if op == "status_node":
                return {"op": op, "results": d.dex_status(params.get("node_id", ""))}
            if op == "cs":
                return {"op": op, "results": d.dex_cs(params.get("code", ""))}
            if op == "combine":
                return {"op": op, "results": d.dex_combine(params.get("a", ""), params.get("b", ""))}
            if op == "separate":
                return {"op": op, "results": d.dex_separate(params.get("node_id", ""))}
            if op == "invert":
                return {"op": op, "results": d.dex_invert(params.get("node_id", ""))}
            if op == "cycle":
                return {"op": op, "results": d.dex_cycle(params.get("node_id", ""))}
            if op == "analyze":
                return {"op": op, "results": d.dex_analyze(params.get("knowledge", ""))}
            if op == "predict":
                return {"op": op, "results": d.dex_predict(
                    params.get("knowledge", ""),
                    horizon=int(params.get("horizon", 2)),
                    limit=int(params.get("limit", 4)))}
            if op == "predict_compare":
                return {"op": op, "results": d.dex_predict_compare(
                    params.get("knowledge", ""),
                    params.get("theory", ""),
                    horizon=int(params.get("horizon", 2)),
                    limit=int(params.get("limit", 4)))}
            if op == "auto_verify":
                return {"op": op, "results": d.dex_auto_verify(
                    params.get("knowledge", ""),
                    limit=int(params.get("limit", 5)),
                    threshold=float(params.get("threshold", 0.50)))}
            if op == "compose":
                return {"op": op, "results": d.dex_compose(
                    params.get("knowledge", ""),
                    limit=int(params.get("limit", 5)),
                    max_anchors=int(params.get("max_anchors", 3)))}
            if op == "test":
                return {"op": op, "results": d.dex_test(params.get("knowledge", ""))}
            if op == "battle":
                return {"op": op, "results": d.dex_battle(params.get("a", ""), params.get("b", ""))}
            if op == "layer_trace":
                return {"op": op, "results": d.dex_layer_trace()}
            if op == "sandbox":
                return {"op": op, "results": d.dex_sandbox(
                    params.get("a", ""), params.get("b", ""),
                    params.get("disturbance", ""))}
            if op == "auto_test":
                return {"op": op, "results": d.dex_auto_test(
                    params.get("a", ""), params.get("b", ""))}
            if op == "usage":
                return {"op": op, "results": d.dex_usage()}
            if op == "homology":
                return {"op": op, "results": d.dex_homology(
                    params.get("entry", ""), params.get("strip_concepts"))}
            if op == "standard_battle":
                return {"op": op, "results": d.dex_standard_battle(
                    params.get("a", ""), params.get("b", ""))}
            if op == "impact":
                return {"op": op, "results": d.dex_impact(
                    params.get("node_id", ""),
                    max_depth=int(params.get("max_depth", 3)))}
            if op == "chain":
                return {"op": op, "results": d.dex_chain(
                    params.get("node_id", ""),
                    max_depth=int(params.get("max_depth", 5)))}
            if op == "verify":
                return {"op": op, "results": d.dex_verify(
                    params.get("node_id", ""))}
            if op == "hot_paths":
                import os as _os
                hp = os.path.join(HERE, 'audit_log', 'chain_heat.json')
                if _os.path.exists(hp):
                    import json as _json
                    with open(hp, encoding='utf-8') as _f:
                        data = _json.load(_f)
                    chains = {k: v for k, v in data.items() if '→' in k}
                    singles = {k.replace('单卡:', ''): v
                               for k, v in data.items() if k.startswith('单卡:')}
                    return {"op": op, "results": {
                        "chains": sorted(chains.items(),
                                         key=lambda x: -x[1])[:10],
                        "singles": sorted(singles.items(),
                                          key=lambda x: -x[1])[:10],
                        "total": sum(singles.values())}}
                return {"op": op, "results": {"chains": [], "singles": [],
                                              "total": 0}}
            if op == "audit_danmaku":
                # 直播弹幕审核（三层判定：词表→信任上下文→终裁）
                try:
                    import danmaku_audit as _da
                    return {"op": op, "results": _da.audit(
                        params.get("text", ""))}
                except Exception:
                    return {"op": op, "error": "danmaku_audit 模块不可用"}
            if op == "audit_log_recent":
                import os as _os
                import json as _json
                log = os.path.join(HERE, 'audit_log', 'danmaku_audit.json')
                if _os.path.exists(log):
                    with open(log, encoding='utf-8') as _f:
                        data = _json.load(_f)
                    return {"op": op, "results": data[-10:]}
                return {"op": op, "results": []}
            return {"op": op, "error": "unknown_op"}
        except Exception as e:
            return {"op": op, "error": str(e)}

    def _upload(self, body):
        """云端上传处理：verified 状态与验证轨迹完整性闸门，不符即拒绝并说明原因。"""
        entry = body.get("entry") or {}
        contributor = body.get("contributor", "anonymous")
        # ---- 上传闸门：verified 且验证轨迹完整 ----
        if entry.get("status") != "verified":
            return {"ok": False, "reason": "upload_gate: status 必须为 verified",
                    "name": entry.get("name", "")}
        trail = entry.get("verification_trail") or {}
        if not trail.get("verified_by"):
            return {"ok": False, "reason": "upload_gate: verification_trail.verified_by 必填",
                    "name": entry.get("name", "")}
        if not entry.get("condition_space"):
            return {"ok": False, "reason": "upload_gate: 无明确条件空间不配加入图鉴（P17 收录判据）",
                    "name": entry.get("name", "")}
        d = self.cloud
        nid = d.add_entry(
            name=entry.get("name", "未命名"),
            domain=entry.get("domain", "未分类"),
            claim=entry.get("claim", ""),
            cs=_cs_from_dict(entry.get("condition_space")),
            level=int(entry.get("level", 2)),
            status="verified",
            response=entry.get("response"))
        now = time.time()
        d.store.conn.execute(
            "INSERT OR REPLACE INTO contributions (entry_id, contributor, verified_by, verified_at, weight) "
            "VALUES (?,?,?,?,?)",
            (nid, contributor, trail.get("verified_by"), now,
             float(entry.get("weight", 1.0))))
        d.store.conn.commit()
        cnt = d.store.conn.execute(
            "SELECT COUNT(*) FROM contributions WHERE contributor=?", (contributor,)).fetchone()[0]
        return {"ok": True, "entry_id": nid, "contributor": contributor,
                "contribution_count": cnt}

    def _ledger(self, contributor=None):
        """台账快照：近期变更记录列表直出。"""
        conn = self.cloud.store.conn
        if contributor:
            rows = conn.execute(
                "SELECT entry_id, contributor, verified_by, verified_at, weight "
                "FROM contributions WHERE contributor=?", (contributor,)).fetchall()
        else:
            rows = conn.execute(
                "SELECT entry_id, contributor, verified_by, verified_at, weight "
                "FROM contributions ORDER BY verified_at").fetchall()
        return {"contributions": [
            {"entry_id": r[0], "contributor": r[1], "verified_by": r[2],
             "verified_at": r[3], "weight": r[4]} for r in rows]}

    def _status(self):
        """云库状态统计：知识层节点总量与 verified 占比汇总。"""
        from aeis_core import MemoryLayer
        d = self.cloud
        nodes = d.store.query_nodes(layer=MemoryLayer.KNOWLEDGE, limit=1000)
        total = len(nodes)
        verified = sum(1 for n in nodes
                       if n.state_attributes.get("status") == "verified")
        domains = {}
        for n in nodes:
            dom = n.state_attributes.get("domain", "未知")
            domains[dom] = domains.get(dom, 0) + 1
        contrib = d.store.conn.execute(
            "SELECT COUNT(*) FROM contributions").fetchone()[0]
        return {"total_entries": total, "verified": verified,
                "domains": domains, "contributions": contrib}


SEED_CARDS_DIR = os.path.join(os.path.dirname(HERE), "seed_knowledge", "wisdom_cards")


def _parse_card_md(path):
    """解析卡 md → (name, domain, edu, kp_dict)。"""
    import re as _re
    with open(path, encoding="utf-8") as f:
        text = f.read()
    name = os.path.basename(path).replace("·知识综述.md", "").replace(".md", "")
    domain = None
    m = _re.search(r'^- \*\*领域\*\*: (.+)$', text, _re.M)
    if m:
        domain = m.group(1).strip()
    edu = None
    m = _re.search(r'^- \*\*教育层级\*\*: (E\d)', text, _re.M)
    if m:
        edu = m.group(1).strip()
    kp_start = text.find("## 知识点内容（按骨架填充）")
    kps = []
    if kp_start >= 0:
        kp_end = len(text)
        nxt = text.find("\n## ", kp_start + 10)
        if nxt >= 0:
            kp_end = nxt
        seg = text[kp_start:kp_end]
        cur = None
        for ln in seg.split("\n"):
            s = ln.strip()
            if s.startswith("### "):
                cur = s[4:].strip()
                kps.append([cur, []])
            elif cur and s and not s.startswith("#"):
                kps[-1][1].append(s)
    else:
        # 旧格式兼容：知识分层（### E2/E3/E4 各节）→ 每节一句
        kp_start = text.find("## 知识分层")
        if kp_start >= 0:
            kp_end = len(text)
            nxt = text.find("\n## ", kp_start + 10)
            if nxt >= 0:
                kp_end = nxt
            seg = text[kp_start:kp_end]
            cur = None
            for ln in seg.split("\n"):
                s = ln.strip()
                if s.startswith("### "):
                    cur = s[4:].strip()
                    kps.append([cur, []])
                elif cur and s and not s.startswith("#"):
                    kps[-1][1].append(s)
    kp_dict = {k[0]: " ".join(k[1]) for k in kps if k[1]}
    return name, domain, edu, kp_dict


def _seed_cards(dex):
    """从本地打包的卡源重建知识卡（首启种子，离线可用）。返回新增数。"""
    from aeis_core import MemoryLayer, ConditionSpace
    existing = {n.state_attributes.get("name")
                for n in dex.store.query_nodes(layer=MemoryLayer.KNOWLEDGE, limit=500)
                if n.state_attributes.get("name")}
    added = 0
    if not os.path.isdir(SEED_CARDS_DIR):
        return 0
    for fn in sorted(os.listdir(SEED_CARDS_DIR)):
        if not fn.endswith(".md"):
            continue
        path = os.path.join(SEED_CARDS_DIR, fn)
        name, domain, edu, kps = _parse_card_md(path)
        if not kps or name in existing:
            continue
        first_kp = next(iter(kps))
        claim = (f"{name}（知识卡源 {len(kps)} 知识点）——{kps[first_kp][:60]}……")
        cs = ConditionSpace(
            observation_position=f"{name} 外部观测位",
            observation_tool="知识卡源种子",
            time_window=(0.0, 9999999999.0),
            existence_constraint="通用现象/规律不受版权保护，开源非盈利知识库")
        response = {
            "trigger": f"涉及{name}议题（如：{'、'.join(list(kps)[:10])}）",
            "action": f"以{name}知识点回应",
        }
        level = {"E1": 1, "E2": 2, "E3": 3, "E4": 4, "E5": 5}.get(edu, 2)
        nid = dex.add_entry(name, domain or "未分类", claim, cs,
                            level=level, status="verified", response=response)
        node = dex.store.get_node(nid)
        node.state_attributes["edu_level"] = edu
        node.state_attributes["source_kind"] = "card_seed"
        node.content = claim + "\n" + "\n".join(
            f"{i+1}. {v}" for i, v in enumerate(kps.values()))
        dex.store.add_node(node)
        added += 1
    return added


def run_server(port=0, db_path=None):
    """启动智慧之书云（daemon 线程）。port=0 → 自动分配空闲端口。

    知识库策略：保留已有库（不删除）；缺卡时从本地种子重建（首启）。
    """
    db = db_path or CLOUD_DB
    if os.path.exists(db) and os.path.getsize(db) < 1024:
        os.remove(db)  # 空壳库（<1KB）重建
    if not os.path.exists(db):
        dex = ConditionDex(db_path=db, fresh=True)
        dex.seed_base()
    else:
        dex = ConditionDex(db_path=db, fresh=False)
    dex.store.conn.execute(
        "CREATE TABLE IF NOT EXISTS contributions ("
        "entry_id TEXT PRIMARY KEY, contributor TEXT, verified_by TEXT, "
        "verified_at REAL, weight REAL)")
    added = _seed_cards(dex)
    if added:
        dex.store.conn.commit()
        print(f"[seed] 首启重建 {added} 张知识卡（本地种子）")
    dex.store.conn.commit()

    DexHandler.cloud = dex
    srv = ThreadingHTTPServer(("127.0.0.1", port), DexHandler)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    return srv, dex


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 18766
    srv, _dex = run_server(port=port)
    print(f"智慧之书 mock 云运行于 http://127.0.0.1:{srv.server_address[1]}")
    try:
        while True:
            time.sleep(3600)
    except KeyboardInterrupt:
        srv.shutdown()
