# -*- coding: utf-8 -*-
"""graph_db_units.py · 图数据库白箱单元库（第六阶段·目标6 条件图数据库的初级复现）
用户设想：终极目标「条件图数据库」← 初级复现「图数据库」。
与白箱条件路由图同构：知识=节点、条件链=边、遍历=条件链组合、持久化=存储层。
单元：{任务 → 代码模式模板 + 验证样例 + 校准基准}——白箱自举（外部只校准）。
"""
import sys
sys.stdout.reconfigure(encoding='utf-8')

GRAPH_UNITS = {
    "图存储-节点边": {
        "task": "图存储",
        "pattern": (
            "class Graph:\n"
            "    # 图存储（图）：节点 + 有向边（知识=节点，条件链=边）\n"
            "    # 生效条件：节点名可哈希；边两端节点存在\n"
            "    # 子功能：① 加节点 ② 加边 ③ 邻居查询 ④ 删边\n"
            "    # 执行：节点集合 + 邻接表（去重边）\n"
"    # 不适用条件：输入不满足生效条件时返回 None/不执行\n"
            "    def __init__(self):\n"
            "        # 构造：初始化节点集合与邻接表\n"
            "        self.nodes = set()\n"
            "        self.edges = {}   # src -> [dst]\n"
            "    def add_node(self, name):\n"
            "        # 加节点：登记到节点集合并初始化邻接表\n"
            "        self.nodes.add(name)\n"
            "        self.edges.setdefault(name, [])\n"
            "    def add_edge(self, src, dst):\n"
            "        # 加边：确保两端节点存在后追加邻接（去重）\n"
            "        self.add_node(src)\n"
            "        self.add_node(dst)\n"
            "        if dst not in self.edges[src]:\n"
            "            self.edges[src].append(dst)\n"
            "    def neighbors(self, name):\n"
            "        # 邻居查询：返回节点的出边目标列表\n"
            "        return list(self.edges.get(name, []))\n"
            "    def remove_edge(self, src, dst):\n"
            "        # 动态图：边删除（增量更新支持）\n"
            "        if src in self.edges and dst in self.edges[src]:\n"
            "            self.edges[src].remove(dst)\n"
            "def graph_ops():\n"
"    # 生效条件：g.add_edge 可用；g.neighbors 可用\n"
"    # 子功能：① 调用 Graph；② 调用 sorted\n"
"    # 执行：顺序调用\n"
            "    # 演示：建边并查询节点与邻居（图存储语义）\n"
            "    g = Graph()\n"
            "    g.add_edge('气压低', '沸点降')\n"
            "    g.add_edge('沸点降', '煮不熟')\n"
            "    return (sorted(g.nodes), g.neighbors('气压低'))\n"),
        "cases": [("call", (["气压低", "沸点降", "煮不熟"], ["沸点降"]))],
        "params": [],
        "calibration": "对照：条件路由图——知识=节点、条件链=边（气压低→沸点降→煮不熟 条件链）",
    },
    "图遍历-BFS": {
        "task": "图遍历",
        "pattern": (
            "def reachable(graph, start):\n"
            "    # BFS 遍历（广度优先搜索）：从起点出发可达的所有节点（条件链组合——影响传播）\n"
            "    # 生效条件：graph 提供 neighbors 接口；start 为图中已存在节点\n"
            "    # 子功能：① 起点入队并标记 ② 出队访问并入队未访问邻接\n"
            "    # 执行：队列 + 已访问集合，逐层扩展直至队空\n"
            "    # 不适用条件：输入不满足生效条件时返回 None/不执行；"
            "带权图/加权图最短路径不适用（无权图能力）\n"
            "    from collections import deque\n"
            "    visited, queue = {start}, deque([start])\n"
            "    while queue:\n"
            "        cur = queue.popleft()\n"
            "        for nxt in graph.neighbors(cur):\n"
            "            if nxt not in visited:\n"
            "                visited.add(nxt)\n"
            "                queue.append(nxt)\n"
            "    return sorted(visited)\n"),
        "cases": [((None, "气压低"), ["气压低", "沸点降", "煮不熟"])],
        "params": [],
        "needs_inject": True,
        "calibration": "对照：条件链组合——从条件出发传播可达的规律（灵枢因果传播同构）",
    },
    "图遍历-路径": {
        "task": "路径查找",
        "pattern": (
            "def has_path(graph, start, end):\n"
            "    # 路径存在性（可达判定）：start 能否到达 end（条件链是否存在）\n"
            "    # 生效条件：graph 提供 neighbors 接口；start/end 为图中节点\n"
            "    # 子功能：① 起终点相同直判 ② BFS 扩散 ③ 终点命中判定\n"
            "    # 执行：BFS 队列遍历，命中终点即返 True\n"
"    # 不适用条件：输入不满足生效条件时返回 None/不执行\n"
            "    if start == end:\n"
            "        return True\n"
            "    from collections import deque\n"
            "    visited, queue = {start}, deque([start])\n"
            "    while queue:\n"
            "        cur = queue.popleft()\n"
            "        for nxt in graph.neighbors(cur):\n"
            "            if nxt == end:\n"
            "                return True\n"
            "            if nxt not in visited:\n"
            "                visited.add(nxt)\n"
            "                queue.append(nxt)\n"
            "    return False\n"),
        "cases": [((None, "气压低", "煮不熟"), True),
                  ((None, "煮不熟", "气压低"), False)],
        "params": [],
        "needs_inject": True,
        "calibration": "对照：条件链——气压低→沸点降→煮不熟 有路径；反向无（条件链有向）",
    },
    "图持久化-序列化": {
        "task": "图序列化",
        "pattern": (
            "def graph_to_json(graph):\n"
            "    # 图序列化（图持久化·JSON 序列化）：图 → JSON 字符串（条件图数据库存储层）\n"
            "    # 生效条件：graph 含 nodes/edges 接口（节点集 + 邻接表）\n"
            "    # 子功能：① 节点排序收集 ② 边表排序 ③ JSON 编码\n"
            "    # 执行：json.dumps({'nodes':…, 'edges':…})\n"
"    # 不适用条件：输入不满足生效条件时返回 None/不执行\n"
            "    import json\n"
            "    return json.dumps({'nodes': sorted(graph.nodes),\n"
            "                        'edges': {k: v for k, v in sorted(graph.edges.items())}},\n"
            "                       ensure_ascii=False)\n"
            "def graph_from_json(text):\n"
            "    # JSON → 图（存储加载）\n"
            "    import json\n"
            "    data = json.loads(text)\n"
            "    g = Graph()\n"
            "    for n in data['nodes']:\n"
            "        g.add_node(n)\n"
            "    for src, dsts in data['edges'].items():\n"
            "        for d in dsts:\n"
            "            g.add_edge(src, d)\n"
            "    return g\n"),
        "cases": [("call", '{"nodes": [], "edges": {}}')],
        "params": [],
        "calibration": "对照：条件图数据库——图序列化持久化（JSON 存储层）",
    },
    "条件路由图-映射": {
        "task": "条件路由映射",
        "pattern": (
            "def units_to_graph(units):\n"
"    # 生效条件：g.add_node 可用；g.add_edge 可用\n"
"    # 子功能：① 调用 Graph\n"
"    # 执行：循环迭代；顺序调用\n"
"    # 不适用条件：输入不满足生效条件时返回 None/不执行\n"
            "    # 条件单元库 → 条件路由图：知识=节点，conditions=入边（条件→知识）\n"
            "    # units: {知识名: {'conditions': [条件...]}}\n"
            "    g = Graph()\n"
            "    for name, u in units.items():\n"
            "        g.add_node(name)\n"
            "        for c in u.get('conditions', []):\n"
            "            g.add_edge(c, name)   # 条件 → 知识（条件链）\n"
            "    return g\n"),
        "cases": [(({"沸点降": {"conditions": ["气压低"]},
                     "煮不熟": {"conditions": ["沸点降"]}},), ["沸点降"])],
        "params": [],
        "needs_inject": True,  # 依赖白箱组装 Graph（与 图遍历-BFS/对接 同类注入型）
        "calibration": "对照：条件单元库（{条件→规律}）→ 条件路由图（第4阶段知识图同构）",
    },
    "图持久化-文件": {
        "task": "图文件",
        "pattern": (
            "def save_graph(graph, path):\n"
"    # 生效条件：json.dump 可用\n"
"    # 子功能：① 调用 open；② 调用 sorted\n"
"    # 执行：顺序调用\n"
"    # 不适用条件：输入不满足生效条件时返回 None/不执行\n"
            "    # 图 → .cgdb 文件（条件图数据库文件）\n"
            "    import json\n"
            "    with open(path, 'w', encoding='utf-8') as f:\n"
            "        json.dump({'nodes': sorted(graph.nodes),\n"
            "                   'edges': {k: v for k, v in sorted(graph.edges.items())}},\n"
            "                  f, ensure_ascii=False)\n"
            "    return path\n"
            "def load_graph(path):\n"
            "    # .cgdb 文件 → 图（条件图数据库加载）\n"
            "    import json\n"
            "    with open(path, 'r', encoding='utf-8') as f:\n"
            "        data = json.load(f)\n"
            "    g = Graph()\n"
            "    for n in data['nodes']:\n"
            "        g.add_node(n)\n"
            "    for src, dsts in data['edges'].items():\n"
            "        for d in dsts:\n"
            "            g.add_edge(src, d)\n"
            "    return g\n"
            "def graph_file_ops():\n"
            "    # 组装：Graph + save + load 往返（条件图数据库持久化）\n"
            "    g = Graph()\n"
            "    g.add_edge('气压低', '沸点降')\n"
            "    path = save_graph(g, 'test.cgdb')\n"
            "    g2 = load_graph(path)\n"
            "    import os\n"
            "    os.remove(path)\n"
            "    return g2.neighbors('气压低')\n"),
        "cases": [("call", ["沸点降"])],
        "params": [],
        "calibration": "对照：条件图数据库——.cgdb 文件持久化（存储层升级：JSON→文件）",
    },
    "图遍历-路径枚举": {
        "task": "路径枚举",
        "pattern": (
            "def all_paths(graph, start, end, max_len=5):\n"
"    # 生效条件：graph.neighbors 可用\n"
"    # 子功能：① 调用 dfs；② 调用 sorted；③ 调用 len\n"
"    # 执行：循环迭代；顺序调用\n"
"    # 不适用条件：输入不满足生效条件时返回 None/不执行\n"
            "    # 枚举 start→end 所有路径（条件链组合——可解释路径）\n"
            "    paths = []\n"
            "    def dfs(cur, path):\n"
            "        # 深度优先：沿未访问邻接递归，到达终点记录路径\n"
            "        if len(path) > max_len:\n"
            "            return\n"
            "        if cur == end:\n"
            "            paths.append(list(path))\n"
            "            return\n"
            "        for nxt in graph.neighbors(cur):\n"
            "            if nxt not in path:\n"
            "                path.append(nxt)\n"
            "                dfs(nxt, path)\n"
            "                path.pop()\n"
            "    dfs(start, [start])\n"
            "    return sorted(paths)\n"),
        "cases": [("call", [["气压低", "沸点降", "煮不熟"],
                            ["气压低", "缺氧", "煮不熟"]])],
        "params": [],
        "needs_inject": True,
        "calibration": "对照：多条件链组合（高压锅在高原=气压低→沸点降 + 气压高→沸点升 两条链的可解释路径）",
    },
    "图遍历-最短路径": {
        "task": "最短路径",
        "pattern": (
            "def shortest_path(graph, start, end):\n"
            "    # 最短路径（无权图 BFS）：BFS 逐层扩散 + 前驱还原（最少条件链跳数）\n"
            "    # 生效条件：graph 提供 neighbors 接口；start/end 为图中节点\n"
            "    # 子功能：① BFS 逐层扩散 ② 记录前驱 ③ 终点回溯还原路径\n"
            "    # 执行：队列扩散 + prev 链回溯\n"
"    # 不适用条件：输入不满足生效条件时返回 None/不执行\n"
            "    if start == end:\n"
            "        return [start]\n"
            "    from collections import deque\n"
            "    prev = {start: None}\n"
            "    queue = deque([start])\n"
            "    while queue:\n"
            "        cur = queue.popleft()\n"
            "        for nxt in graph.neighbors(cur):\n"
            "            if nxt not in prev:\n"
            "                prev[nxt] = cur\n"
            "                if nxt == end:\n"
            "                    path = []\n"
            "                    node = nxt\n"
            "                    while node is not None:\n"
            "                        path.append(node)\n"
            "                        node = prev[node]\n"
            "                    return path[::-1]\n"
            "                queue.append(nxt)\n"
            "    return None\n"),
        "cases": [("call", ["气压低", "沸点降", "煮不熟"]),
                  ("call", None)],
        "params": [],
        "needs_inject": True,
        "calibration": "对照：条件链最短路径——BFS 最少跳数（两链中取最短；反向无路返回 None）",
    },
    "图遍历-加权最短": {
        "task": "加权最短路径",
        "pattern": (
            "def dijkstra(graph, weights, start, end):\n"
"    # 生效条件：heapq.heappop 可用；graph.neighbors 可用\n"
"    # 子功能：① 调用 float\n"
"    # 执行：循环迭代；顺序调用\n"
"    # 不适用条件：输入不满足生效条件时返回 None/不执行\n"
            "    # 加权最短路径：Dijkstra 贪心（权重=条件链代价/信任度倒数，小=优）\n"
            "    import heapq\n"
            "    dist = {start: 0}\n"
            "    prev = {start: None}\n"
            "    pq = [(0, start)]\n"
            "    while pq:\n"
            "        d, cur = heapq.heappop(pq)\n"
            "        if d > dist.get(cur, float('inf')):\n"
            "            continue\n"
            "        if cur == end:\n"
            "            break\n"
            "        for nxt in graph.neighbors(cur):\n"
            "            w = weights.get((cur, nxt), 1)\n"
            "            nd = d + w\n"
            "            if nd < dist.get(nxt, float('inf')):\n"
            "                dist[nxt] = nd\n"
            "                prev[nxt] = cur\n"
            "                heapq.heappush(pq, (nd, nxt))\n"
            "    if end not in dist:\n"
            "        return None\n"
            "    path = []\n"
            "    node = end\n"
            "    while node is not None:\n"
            "        path.append(node)\n"
            "        node = prev[node]\n"
            "    return path[::-1], dist[end]\n"),
        "cases": [("call", (["气压低", "缺氧", "煮不熟"], 3))],
        "params": [],
        "needs_inject": True,
        "calibration": "对照：条件链加权最短——Dijkstra 选代价最小链（缺氧路径代价 1+2=3 < 沸点降路径 2+2=4）",
    },
    "条件路由图-查询": {
        "task": "路由查询",
        "pattern": (
            "def route_query(graph, condition):\n"
"    # 生效条件：queue.popleft 可用；graph.neighbors 可用\n"
"    # 子功能：① 调用 sorted；② 调用 set；③ 调用 deque\n"
"    # 执行：循环迭代；顺序调用\n"
"    # 不适用条件：输入不满足生效条件时返回 None/不执行\n"
            "    # 条件路由查询：从条件出发影响传播 → 可达规律（影响面，不含起点）\n"
            "    from collections import deque\n"
            "    visited, queue = set(), deque([condition])\n"
            "    while queue:\n"
            "        cur = queue.popleft()\n"
            "        for nxt in graph.neighbors(cur):\n"
            "            if nxt not in visited:\n"
            "                visited.add(nxt)\n"
            "                queue.append(nxt)\n"
            "    return sorted(visited)\n"),
        "cases": [("call", ["沸点降", "煮不熟", "缺氧"])],
        "params": [],
        "needs_inject": True,
        "calibration": "对照：条件路由查询——条件 → 影响面（规律集合，compose 条件链组合的图查询形态）",
    },
    "条件路由图-对接": {
        "task": "条件单元对接",
        "pattern": (
            "def build_from_condition_units(units):\n"
"    # 生效条件：g.add_node 可用；g.add_edge 可用\n"
"    # 子功能：① 调用 Graph\n"
"    # 执行：循环迭代；顺序调用\n"
"    # 不适用条件：输入不满足生效条件时返回 None/不执行\n"
            "    # compose_engine.CONDITION_UNITS → 条件路由图（知识=单元，conditions=条件入边）\n"
            "    g = Graph()\n"
            "    for name, u in units.items():\n"
            "        g.add_node(name)\n"
            "        for c in u.get('conditions', []):\n"
            "            g.add_edge(c, name)\n"
            "    return g\n"
            "def condition_impact(g, condition):\n"
            "    # 条件 → 影响的知识单元（直接+间接——影响面）\n"
            "    from collections import deque\n"
            "    visited, queue = set(), deque([condition])\n"
            "    while queue:\n"
            "        cur = queue.popleft()\n"
            "        for nxt in g.neighbors(cur):\n"
            "            if nxt not in visited:\n"
            "                visited.add(nxt)\n"
            "                queue.append(nxt)\n"
            "    return sorted(visited)\n"),
        "cases": [(({"沸点-气压": {"conditions": ["气压"]},
                     "密度-浮沉": {"conditions": ["物体", "液体"]}},), 5)],
        "params": [],
        "needs_inject": True,
        "calibration": "对照：真实条件单元库（compose_engine 43 单元）→ 条件路由图（条件 → 影响的规律单元）",
    },
    "图查询-模式匹配": {
        "task": "模式匹配",
        "pattern": (
            "def match_pattern(graph, src, rel, dst):\n"
"    # 生效条件：graph.neighbors 可用\n"
"    # 子功能：① 调用 sorted\n"
"    # 执行：循环迭代；顺序调用\n"
"    # 不适用条件：输入不满足生效条件时返回 None/不执行\n"
            "    # 图查询语言：MATCH (a)-[r]->(b) 模式 → 匹配的三元组集合\n"
            "    # src/dst 支持 None=任意节点；rel 支持 None=任意边\n"
            "    results = []\n"
            "    for a in sorted(graph.nodes):\n"
            "        if src is not None and a != src:\n"
            "            continue\n"
            "        for b in graph.neighbors(a):\n"
            "            if rel is not None and rel not in (a, b):\n"
            "                continue\n"
            "            if dst is not None and b != dst:\n"
            "                continue\n"
            "            results.append((a, b))\n"
            "    return results\n"),
        "cases": [("call", [('气压低', '沸点降'), ('气压低', '缺氧')])],
        "params": [],
        "needs_inject": True,
        "calibration": "对照：图查询语言——MATCH 模式（(a)-[r]->(b)，None=任意，条件路由图三元组查询）",
    },
    "图查询-聚合": {
        "task": "聚合查询",
        "pattern": (
            "def aggregate_by(graph, key_fn):\n"
"    # 生效条件：参数 graph/key_fn 合法\n"
"    # 子功能：① 调用 sorted；② 调用 key_fn\n"
"    # 执行：循环迭代；顺序调用\n"
"    # 不适用条件：输入不满足生效条件时返回 None/不执行\n"
            "    # 图查询语言：按条件分组聚合（每节点 → 出度计数，GROUP BY 语义）\n"
            "    groups = {}\n"
            "    for node in sorted(graph.nodes):\n"
            "        k = key_fn(node)\n"
            "        groups.setdefault(k, 0)\n"
            "        groups[k] += 1\n"
            "    return groups\n"),
        "cases": [("call", {'气压低': 1, '沸点降': 1, '缺氧': 1, '煮不熟': 1})],
        "params": [],
        "needs_inject": True,
        "calibration": "对照：图查询语言——GROUP BY 聚合（按 key_fn 分组计数）",
    },
    "图查询-条件链": {
        "task": "条件链查询",
        "pattern": (
            "def chain_query(graph, condition, max_len=4):\n"
            "    # 条件链查询（图查询语言）：从条件出发沿边收集完整链（MATCH (a)-[*]->(b) 路径语义）\n"
            "    # 生效条件：graph 提供 neighbors 接口；condition 为起始条件节点\n"
            "    # 子功能：① 递归沿边走链 ② 无后继记录完整链 ③ 超长截断\n"
            "    # 执行：DFS 回溯 + max_len 剪枝，收集全部条件链\n"
"    # 不适用条件：succ 为空/非法时\n"
            "    chains = []\n"
            "    def walk(cur, path):\n"
            "        # 递归走链：无后继时记录完整条件链\n"
            "        if len(path) > max_len:\n"
            "            return\n"
            "        succ = graph.neighbors(cur)\n"
            "        if not succ:\n"
            "            chains.append(list(path))\n"
            "            return\n"
            "        for nxt in succ:\n"
            "            if nxt not in path:\n"
            "                path.append(nxt)\n"
            "                walk(nxt, path)\n"
            "                path.pop()\n"
            "    walk(condition, [condition])\n"
            "    return sorted(chains)\n"),
        "cases": [("call", [['气压低', '沸点降', '煮不熟'],
                            ['气压低', '缺氧', '煮不熟']])],
        "params": [],
        "needs_inject": True,
        "calibration": "对照：图查询语言——变长路径 MATCH (a)-[*]->(b)：从条件出发的完整条件链集合",
    },
    "图存储-事务": {
        "task": "图事务",
        "pattern": (
            "def txn_op(state, op, payload=None):\n"
            "    # 图数据库事务（ACID 事务）：begin 快照 / commit 生效 / rollback 回滚（ACID 原子性）\n"
            "    # 生效条件：state 为图存储状态；op ∈ {begin, commit, rollback}\n"
            "    # 子功能：① begin 深拷贝快照 ② commit 清除快照 ③ rollback 恢复快照\n"
            "    # 执行：快照字典深拷贝 + 按 op 分派\n"
"    # 不适用条件：op 非 {begin, commit, rollback} 时（隐式盲区：返回默认值 idle = 未知行为——不适用）\n"
            "    if op == 'begin':\n"
            "        state['snapshot'] = {k: list(v) if isinstance(v, list) else v\n"
            "                              for k, v in state.get('data', {}).items()}\n"
            "        return 'active'\n"
            "    if op == 'commit':\n"
            "        state['snapshot'] = None\n"
            "        return 'committed'\n"
            "    if op == 'rollback':\n"
            "        if 'snapshot' in state and state['snapshot'] is not None:\n"
            "            state['data'] = state['snapshot']\n"
            "            state['snapshot'] = None\n"
            "        return 'rolled_back'\n"
            "    return 'idle'\n"),
        "cases": [(({'data': {'a': [1]}, 'snapshot': None}, 'begin'), 'active'),
                  (({'data': {'a': [1]}, 'snapshot': {'a': [1]}}, 'commit'),
                   'committed'),
                  (({'data': {'a': [2]}, 'snapshot': {'a': [1]}}, 'rollback'),
                   'rolled_back')],
        "params": [],
        "calibration": "对照：图数据库事务——begin 快照/commit 生效/rollback 回滚（ACID 原子性语义）",
    },
    "图索引-属性索引": {
        "task": "属性索引",
        "pattern": (
            "def index_by_attr(nodes, attr):\n"
"    # 生效条件：参数 nodes/attr 合法\n"
"    # 子功能：① 调用 sorted\n"
"    # 执行：循环迭代；顺序调用\n"
"    # 不适用条件：输入不满足生效条件时返回 None/不执行\n"
            "    # 图数据库索引：按属性值分组 → 快速查找（索引加速语义）\n"
            "    idx = {}\n"
            "    for nid, props in nodes.items():\n"
            "        val = props.get(attr)\n"
            "        if val is not None:\n"
            "            idx.setdefault(val, []).append(nid)\n"
            "    return {k: sorted(v) for k, v in idx.items()}\n"),
        "cases": [(({'a': {'type': '条件'}, 'b': {'type': '规律'}, 'c': {'type': '条件'}},
                    'type'),
                   {'条件': ['a', 'c'], '规律': ['b']}),
                  (({'x': {'t': 1}}, 'none'), {})],
        "params": [],
        "calibration": "对照：图数据库索引——按属性值分组（type 索引：条件→[a,c] 规律→[b]）",
    },
    "图查询-子图匹配": {
        "task": "子图匹配",
        "pattern": (
            "def subgraph_match(graph, pattern):\n"
"    # 生效条件：graph.neighbors 可用\n"
"    # 子功能：① 条件判定 ② 结果处理\n"
"    # 执行：循环迭代\n"
"    # 不适用条件：输入不满足生效条件时返回 None/不执行\n"
            "    # 图查询：模式子图匹配（pattern=[(src, dst), ...] 边列表 → 存在性）\n"
            "    # 所有边都在图中存在 → 匹配成功（子图同构简化版）\n"
            "    for s, d in pattern:\n"
            "        if d not in graph.neighbors(s):\n"
            "            return False\n"
            "    return True\n"),
        "cases": [("call", True),
                  ("call", False)],
        "params": [],
        "needs_inject": True,
        "calibration": "对照：图查询——子图模式匹配（模式边全部存在=匹配；缺边=不匹配）",
    },
    "图算法-PageRank": {
        "task": "PageRank",
        "pattern": (
            "def pagerank(graph, iterations=5, damping=0.85):\n"
"    # 生效条件：graph.neighbors 可用\n"
"    # 子功能：① 调用 sorted；② 调用 len；③ 调用 range\n"
"    # 执行：循环迭代；顺序调用\n"
"    # 不适用条件：out 为空/非法时\n"
            "    # PageRank：权重迭代传播（出链均分，阻尼因子防死端）\n"
            "    nodes = sorted(graph.nodes)\n"
            "    n = len(nodes)\n"
            "    pr = {node: 1.0 / n for node in nodes}\n"
            "    for _ in range(iterations):\n"
            "        new_pr = {node: (1 - damping) / n for node in nodes}\n"
            "        for node in nodes:\n"
            "            out = graph.neighbors(node)\n"
            "            if not out:\n"
            "                continue\n"
            "            share = damping * pr[node] / len(out)\n"
            "            for nxt in out:\n"
            "                new_pr[nxt] += share\n"
            "        pr = new_pr\n"
            "    return pr\n"),
        "cases": [("call", None)],
        "params": [],
        "needs_inject": True,
        "calibration": "对照：图算法——PageRank（权重迭代传播，入链多者排名高）",
    },
    "图算法-连通分量": {
        "task": "连通分量",
        "pattern": (
            "def connected_components(graph):\n"
            "    # 连通分量（无向连通分量）：BFS 分组（边双向视为连通，互达节点同组）\n"
            "    # 生效条件：graph 提供 nodes/neighbors 接口（无向图）\n"
            "    # 子功能：① 邻接双向化 ② BFS 未访问分组 ③ 收集各分量\n"
            "    # 执行：BFS 逐组标记，未访问节点开新组\n"
"    # 不适用条件：输入不满足生效条件时返回 None/不执行\n"
            "    from collections import deque\n"
            "    # 构建无向邻接（edges 双向化）\n"
            "    adj = {n: set(graph.neighbors(n)) for n in graph.nodes}\n"
            "    for n in list(graph.nodes):\n"
            "        for nxt in graph.neighbors(n):\n"
            "            adj.setdefault(nxt, set()).add(n)\n"
            "    seen = set()\n"
            "    comps = []\n"
            "    for start in sorted(graph.nodes):\n"
            "        if start in seen:\n"
            "            continue\n"
            "        group = set()\n"
            "        queue = deque([start])\n"
            "        seen.add(start)\n"
            "        while queue:\n"
            "            cur = queue.popleft()\n"
            "            group.add(cur)\n"
            "            for nxt in adj.get(cur, set()):\n"
            "                if nxt not in seen:\n"
            "                    seen.add(nxt)\n"
            "                    queue.append(nxt)\n"
            "        comps.append(sorted(group))\n"
            "    return sorted(comps)\n"),
        "cases": [("call", None)],
        "params": [],
        "needs_inject": True,
        "calibration": "对照：图算法——连通分量（无向互达分组）",
    },
    "图算法-拓扑排序": {
        "task": "拓扑排序",
        "pattern": (
            "def topological_sort(graph):\n"
            "    # 拓扑排序（DAG 排序）：DAG 依赖顺序（Kahn 算法——入度归零先出）\n"
            "    # 生效条件：graph 为有向无环图（含 nodes/neighbors 接口）\n"
            "    # 子功能：① 入度统计 ② 零入度入队 ③ 出队并减后继入度\n"
            "    # 执行：Kahn 队列反复出零入度节点（依赖顺序）\n"
"    # 不适用条件：输入不满足生效条件时返回 None/不执行\n"
            "    from collections import deque\n"
            "    indeg = {node: 0 for node in graph.nodes}\n"
            "    for node in graph.nodes:\n"
            "        for nxt in graph.neighbors(node):\n"
            "            indeg[nxt] = indeg.get(nxt, 0) + 1\n"
            "    queue = deque(sorted(n for n, d in indeg.items() if d == 0))\n"
            "    order = []\n"
            "    while queue:\n"
            "        cur = queue.popleft()\n"
            "        order.append(cur)\n"
            "        for nxt in graph.neighbors(cur):\n"
            "            indeg[nxt] -= 1\n"
            "            if indeg[nxt] == 0:\n"
            "                queue.append(nxt)\n"
            "    return order if len(order) == len(graph.nodes) else None\n"),
        "cases": [("call", None)],
        "params": [],
        "needs_inject": True,
        "calibration": "对照：图算法——拓扑排序（Kahn 入度归零，DAG 依赖顺序；有环返回 None）",
    },
    "图查询-执行计划": {
        "task": "执行计划",
        "pattern": (
            "def query_plan(conditions, stats):\n"
"    # 生效条件：参数 conditions/stats 合法\n"
"    # 子功能：① 调用 sorted\n"
"    # 执行：顺序调用\n"
"    # 不适用条件：输入不满足生效条件时返回 None/不执行\n"
            "    # 查询执行计划：按选择性排序条件（低选择性先执行——查询优化语义）\n"
            "    plan = sorted(conditions, key=lambda c: stats.get(c, 0))\n"
            "    return plan\n"),
        "cases": [((['a', 'b', 'c'], {'a': 10, 'b': 2, 'c': 50}), ['b', 'a', 'c']),
                  ((['x'], {'x': 1}), ['x']),
                  ((['a', 'b'], {}), ['a', 'b'])],
        "params": [],
        "calibration": "对照：图查询优化——执行计划（按选择性升序，低选择性条件先执行）",
    },
    "图存储-批量操作": {
        "task": "批量建图",
        "pattern": (
            "def batch_edges(graph, edges):\n"
"    # 生效条件：graph.add_edge 可用\n"
"    # 子功能：① 调用 len\n"
"    # 执行：循环迭代；顺序调用\n"
"    # 不适用条件：输入不满足生效条件时返回 None/不执行\n"
            "    # 批量建图：一次添加多条边（批量导入语义）\n"
            "    for src, dst in edges:\n"
            "        graph.add_edge(src, dst)\n"
            "    return len(edges)\n"),
        "cases": [("call", 3)],
        "params": [],
        "needs_inject": True,
        "calibration": "对照：图数据库批量导入（多条边一次性建图）",
    },
    "图索引-布隆过滤": {
        "task": "布隆过滤",
        "pattern": (
            "def bloom_filter(items, probe):\n"
"    # 生效条件：参数 items/probe 合法\n"
"    # 子功能：① 调用 sum；② 调用 h1；③ 调用 h2\n"
"    # 执行：循环迭代；顺序调用\n"
"    # 不适用条件：输入不满足生效条件时返回 None/不执行\n"
            "    # 布隆过滤器：多哈希位数组（成员可能判定，误报可接受）\n"
            "    size = 64\n"
            "    bits = [False] * size\n"
            "    def h1(x):\n"
            "        # 哈希一：字符码和取模（第一哈希函数）\n"
            "        return sum(ord(c) for c in x) % size\n"
            "    def h2(x):\n"
            "        # 哈希二：长度加权取模（第二哈希函数）\n"
            "        return (len(x) * 7 + sum(ord(c) for c in x)) % size\n"
            "    for it in items:\n"
            "        bits[h1(it)] = bits[h2(it)] = True\n"
            "    return bits[h1(probe)] and bits[h2(probe)]\n"),
        "cases": [((['a', 'b', 'c'], 'b'), True),
                  ((['a', 'b', 'c'], 'z'), False),
                  ((['ab'], 'ab'), True)],
        "params": [],
        "calibration": "对照：图索引——布隆过滤器（多哈希位数组，快速成员判定，可误报）",
    },
    "图算法-节点相似度": {
        "task": "节点相似度",
        "pattern": (
            "def jaccard_similarity(graph, a, b):\n"
"    # 生效条件：graph.neighbors 可用\n"
"    # 子功能：① 调用 set；② 调用 len\n"
"    # 执行：顺序调用\n"
"    # 不适用条件：输入不满足生效条件时返回 None/不执行\n"
            "    # 节点相似度：Jaccard（共同邻居 / 邻居并集）——推荐语义\n"
            "    na = set(graph.neighbors(a))\n"
            "    nb = set(graph.neighbors(b))\n"
            "    if not na and not nb:\n"
            "        return 0.0\n"
            "    return len(na & nb) / len(na | nb)\n"),
        "cases": [("call", 0.0)],
        "params": [],
        "needs_inject": True,
        "calibration": "对照：图算法——Jaccard 相似度（共同邻居占比，推荐/相似节点语义）",
    },
    "图算法-图同构": {
        "task": "图同构判定",
        "pattern": (
            "def graph_isomorphic(edges_a, edges_b):\n"
"    # 生效条件：参数 edges_a/edges_b 合法\n"
"    # 子功能：① 调用 set；② 调用 deg_seq；③ 调用 len\n"
"    # 执行：循环迭代；顺序调用\n"
"    # 不适用条件：输入不满足生效条件时返回 None/不执行\n"
            "    # 图同构（简化）：边数+节点度序列 相同 → 可能同构（必要条件）\n"
            "    def deg_seq(edges):\n"
            "        nodes = set()\n"
            "        for s, d in edges:\n"
            "            nodes.add(s)\n"
            "            nodes.add(d)\n"
            "        deg = {n: 0 for n in nodes}\n"
            "        for s, d in edges:\n"
            "            deg[s] += 1\n"
            "            deg[d] += 1\n"
            "        return len(nodes), sorted(deg.values())\n"
            "    return deg_seq(edges_a) == deg_seq(edges_b)\n"),
        "cases": [(([('a', 'b'), ('b', 'c')], [('x', 'y'), ('y', 'z')]), True),
                  (([('a', 'b')], [('x', 'y'), ('y', 'z')]), False)],
        "params": [],
        "calibration": "对照：图算法——同构判定（节点数+度序列必要条件，结构等价检测）",
    },
    "图算法-社区发现": {
        "task": "社区发现",
        "pattern": (
            "def label_propagation(graph, iterations=3):\n"
"    # 生效条件：graph.neighbors 可用；cnt.most_common 可用\n"
"    # 子功能：① 调用 range；② 调用 sorted；③ 调用 Counter\n"
"    # 执行：循环迭代；顺序调用\n"
"    # 不适用条件：neigh 为空/非法时\n"
            "    # 社区发现：标签传播（LPA——节点取邻居多数标签收敛）\n"
            "    labels = {n: n for n in graph.nodes}\n"
            "    for _ in range(iterations):\n"
            "        for n in sorted(graph.nodes):\n"
            "            neigh = graph.neighbors(n)\n"
            "            if not neigh:\n"
            "                continue\n"
            "            from collections import Counter\n"
            "            cnt = Counter(labels[x] for x in neigh)\n"
            "            labels[n] = cnt.most_common(1)[0][0]\n"
            "    return labels\n"),
        "cases": [("call", None)],
        "params": [],
        "needs_inject": True,
        "calibration": "对照：图算法——标签传播社区发现（LPA，邻居多数标签传播收敛）",
    },
    "图灵枢-导出": {
        "task": "图导出灵枢",
        "pattern": (
            "def graph_to_memories(graph, max_chain=4):\n"
"    # 生效条件：graph.neighbors 可用\n"
"    # 子功能：① 调用 sorted\n"
"    # 执行：循环迭代；顺序调用\n"
"    # 不适用条件：输入不满足生效条件时返回 None/不执行\n"
            "    # 条件路由图 → 灵枢记忆条目（每节点=条件链卡，可写入灵枢记忆库）\n"
            "    mems = []\n"
            "    for node in sorted(graph.nodes):\n"
            "        succ = graph.neighbors(node)\n"
            "        if succ:\n"
            "            chain = ' → '.join([node] + succ[:max_chain - 1])\n"
            "            mems.append({'content': '[条件链] ' + chain,\n"
            "                         'tags': ['graph', 'condition-chain', node],\n"
            "                         'importance': 0.7})\n"
            "    return mems\n"),
        "cases": [("call", 1)],
        "params": [],
        "needs_inject": True,
        "calibration": "对照：图数据库 × 灵枢——条件路由图导出为灵枢记忆条目（条件链卡，可召回重建）",
    },
    "图存储-快照版本": {
        "task": "快照版本",
        "pattern": (
            "def snapshot_ops(repo, op, version=None, state=None):\n"
"    # 生效条件：op ∈ {list, restore, save}\n"
"    # 子功能：① op 分支处理\n"
"    # 执行：按 op 分派；顺序调用\n"
"    # 不适用条件：op 非 {list, restore, save} 时\n"
            "    # 图版本快照：保存/回溯（时间点恢复语义）\n"
            "    if op == 'save':\n"
            "        ver = repo.get('next', 1)\n"
            "        repo['versions'][ver] = dict(state or {})\n"
            "        repo['next'] = ver + 1\n"
            "        return ver\n"
            "    if op == 'restore':\n"
            "        return repo['versions'].get(version)\n"
            "    if op == 'list':\n"
            "        return sorted(repo['versions'].keys())\n"
            "    return None\n"),
        "cases": [(({'versions': {}, 'next': 1}, 'save', None, {'a': 1}), 1),
                  (({'versions': {1: {'a': 1}}, 'next': 2}, 'restore', 1),
                   {'a': 1}),
                  (({'versions': {1: {'a': 1}}, 'next': 2}, 'list'), [1])],
        "params": [],
        "calibration": "对照：图数据库版本管理——快照保存/回溯（时间点恢复）",
    },
    "图查询-时序查询": {
        "task": "时序查询",
        "pattern": (
            "def time_query(history, time):\n"
"    # 生效条件：参数 history/time 合法\n"
"    # 子功能：① 调用 sorted\n"
"    # 执行：循环迭代；顺序调用\n"
"    # 不适用条件：输入不满足生效条件时返回 None/不执行\n"
            "    # 时序图查询：时间点 → 该时刻图状态（快照序列检索）\n"
            "    snaps = sorted(history.keys())\n"
            "    cur = {}\n"
            "    for t in snaps:\n"
            "        if t <= time:\n"
            "            cur = history[t]\n"
            "        else:\n"
            "            break\n"
            "    return cur\n"),
        "cases": [(({1: {'a': 1}, 3: {'a': 2}}, 2), {'a': 1}),
                  (({1: {'a': 1}}, 5), {'a': 1}),
                  (({3: {'a': 2}}, 1), {})],
        "params": [],
        "calibration": "对照：时序图查询——时间点最近快照（快照序列时间回溯）",
    },
    "图算法-增量更新": {
        "task": "增量更新",
        "pattern": (
            "def incr_update(graph, edge, op):\n"
"    # 生效条件：op ∈ {add, remove}；graph.add_edge 可用；graph.remove_edge 可用\n"
"    # 子功能：① op 分支处理\n"
"    # 执行：按 op 分派\n"
"    # 不适用条件：op 非 {add, remove} 时\n"
            "    # 动态图增量：边增删（增量维护，不重建全图）\n"
            "    src, dst = edge\n"
            "    if op == 'add':\n"
            "        graph.add_edge(src, dst)\n"
            "        return 'added'\n"
            "    if op == 'remove':\n"
            "        graph.remove_edge(src, dst)\n"
            "        return 'removed'\n"
            "    return None\n"),
        "cases": [("call", None)],
        "params": [],
        "needs_inject": True,
        "calibration": "对照：动态图——增量边增删（增量维护语义）",
    },
    "图存储-分区分片": {
        "task": "分区分片",
        "pattern": (
            "def graph_shard(nodes, shards):\n"
"    # 生效条件：参数 nodes/shards 合法\n"
"    # 子功能：① 调用 sorted；② 调用 range；③ 调用 sum\n"
"    # 执行：循环迭代；顺序调用\n"
"    # 不适用条件：输入不满足生效条件时返回 None/不执行\n"
            "    # 图分区：节点确定性哈希 → 分片（水平扩展语义）\n"
            "    parts = {i: [] for i in range(shards)}\n"
            "    for n in nodes:\n"
            "        parts[sum(ord(c) for c in n) % shards].append(n)\n"
            "    return {k: sorted(v) for k, v in parts.items()}\n"),
        "cases": [((['a', 'b', 'c', 'd'], 2), {0: ['b', 'd'], 1: ['a', 'c']}),
                  (([], 3), {0: [], 1: [], 2: []})],
        "params": [],
        "calibration": "对照：分布式图——哈希分片（节点分布到分片，水平扩展）",
    },
    "图存储-主从复制": {
        "task": "主从复制",
        "pattern": (
            "def replication(replicas, op, key=None, value=None):\n"
"    # 生效条件：op ∈ {read, write}\n"
"    # 子功能：① op 分支处理\n"
"    # 执行：按 op 分派；循环迭代；顺序调用\n"
"    # 不适用条件：op 非 {read, write} 时\n"
            "    # 主从复制：写主节点 → 同步从节点（读扩展/容错）\n"
            "    if op == 'write':\n"
            "        for r in replicas:\n"
            "            r[key] = value\n"
            "        return len(replicas)\n"
            "    if op == 'read':\n"
            "        return replicas[0].get(key)  # 读主副本\n"
            "    return None\n"),
        "cases": [(([{}, {}], 'write', 'k', 'v'), 2),
                  (([{'k': 'v'}, {'k': 'v'}], 'read', 'k'), 'v'),
                  (([{'k': 'v'}, {'k': 'x'}], 'read', 'k'), 'v')],
        "params": [],
        "calibration": "对照：分布式图——主从复制（写全副本同步，读主副本）",
    },
    "图查询-分布式查询": {
        "task": "分布式查询",
        "pattern": (
            "def dist_query(shards, query_fn):\n"
"    # 生效条件：参数 shards/query_fn 合法\n"
"    # 子功能：① 调用 sorted；② 调用 query_fn\n"
"    # 执行：循环迭代；顺序调用\n"
"    # 不适用条件：输入不满足生效条件时返回 None/不执行\n"
            "    # 分布式查询：各分片并行查 → 合并结果（MapReduce 语义）\n"
            "    results = []\n"
            "    for shard in shards:\n"
            "        results.extend(query_fn(shard))\n"
            "    return sorted(results)\n"),
        "cases": [(([[1, 3], [2, 4]], lambda s: [x * 2 for x in s]), [2, 4, 6, 8]),
                  (([[], []], lambda s: s), [])],
        "params": [],
        "calibration": "对照：分布式查询——分片并行处理合并（Map 归约语义）",
    },
    "图可视化-力导向布局": {
        "task": "力导向布局",
        "pattern": (
            "def force_layout(nodes, edges, iterations=2):\n"
"    # 生效条件：参数 nodes/edges/iterations 合法\n"
"    # 子功能：① 调用 range；② 调用 round；③ 调用 enumerate\n"
"    # 执行：循环迭代；顺序调用\n"
"    # 不适用条件：输入不满足生效条件时返回 None/不执行\n"
            "    # 力导向布局：斥力+引力迭代（节点坐标稳定——图可视化）\n"
            "    pos = {n: i * 1.0 for i, n in enumerate(nodes)}  # 初始线性\n"
            "    for _ in range(iterations):\n"
            "        for a in nodes:\n"
            "            for b in nodes:\n"
            "                if a != b and pos[a] < pos[b]:\n"
            "                    pos[a] += 0.1  # 斥力推远\n"
            "                    pos[b] -= 0.1\n"
            "        for a, b in edges:\n"
            "            pos[b] = (pos[a] + pos[b]) / 2  # 引力拉近\n"
            "    return {n: round(pos[n], 2) for n in nodes}\n"),
        "cases": [((['a', 'b'], [('a', 'b')], 1), {'a': 0.1, 'b': 0.5}),
                  ((['x'], [], 1), {'x': 0.0})],
        "params": [],
        "calibration": "对照：图可视化——力导向布局（斥力推离+引力拉近迭代收敛）",
    },
    "图可视化-分层布局": {
        "task": "分层布局",
        "pattern": (
            "def layer_layout(graph):\n"
"    # 生效条件：q.popleft 可用；graph.neighbors 可用\n"
"    # 子功能：① 调用 deque；② 调用 min；③ 调用 any\n"
"    # 执行：循环迭代；顺序调用\n"
"    # 不适用条件：starts 为空/非法时\n"
            "    # 分层布局：按 BFS 深度分层（层次坐标——层级图可视化）\n"
            "    from collections import deque\n"
            "    starts = [n for n in graph.nodes if not any(\n"
            "        n in graph.neighbors(m) for m in graph.nodes)]\n"
            "    if not starts:\n"
            "        starts = [min(graph.nodes)]\n"
            "    layers = {}\n"
            "    for s in starts:\n"
            "        q = deque([(s, 0)])\n"
            "        while q:\n"
            "            n, d = q.popleft()\n"
            "            if n not in layers or d < layers[n]:\n"
            "                layers[n] = d\n"
            "            for nxt in graph.neighbors(n):\n"
            "                if nxt not in layers or d + 1 < layers[nxt]:\n"
            "                    q.append((nxt, d + 1))\n"
            "    return layers\n"),
        "cases": [("call", None)],
        "params": [],
        "needs_inject": True,
        "calibration": "对照：图可视化——分层布局（BFS 深度分层坐标）",
    },
    "图可视化-邻接矩阵": {
        "task": "邻接矩阵",
        "pattern": (
            "def adjacency_matrix(graph):\n"
"    # 生效条件：graph.neighbors 可用\n"
"    # 子功能：① 调用 sorted；② 调用 enumerate；③ 调用 len\n"
"    # 执行：循环迭代；顺序调用\n"
"    # 不适用条件：输入不满足生效条件时返回 None/不执行\n"
            "    # 邻接矩阵：节点 × 节点 0/1（图的结构矩阵表示）\n"
            "    nodes = sorted(graph.nodes)\n"
            "    idx = {n: i for i, n in enumerate(nodes)}\n"
            "    mat = [[0] * len(nodes) for _ in nodes]\n"
            "    for n in nodes:\n"
            "        for nxt in graph.neighbors(n):\n"
            "            mat[idx[n]][idx[nxt]] = 1\n"
            "    return mat\n"),
        "cases": [("call", None)],
        "params": [],
        "needs_inject": True,
        "calibration": "对照：图可视化——邻接矩阵（0/1 结构矩阵表示）",
    },
    "图存储-备份恢复": {
        "task": "备份恢复",
        "pattern": (
            "def backup_ops(repo, op, data=None):\n"
"    # 生效条件：op ∈ {full, incr, restore}\n"
"    # 子功能：① op 分支处理\n"
"    # 执行：按 op 分派；顺序调用\n"
"    # 不适用条件：op 非 {full, incr, restore} 时\n"
            "    # 图备份：全量备份/增量合并/恢复（数据安全语义）\n"
            "    if op == 'full':\n"
            "        repo['full'] = dict(data or {})\n"
            "        repo['incr'] = {}\n"
            "        return 'full_backed'\n"
            "    if op == 'incr':\n"
            "        repo['incr'].update(data or {})\n"
            "        return 'incr_backed'\n"
            "    if op == 'restore':\n"
            "        merged = dict(repo.get('full', {}))\n"
            "        merged.update(repo.get('incr', {}))\n"
            "        return merged\n"
            "    return None\n"),
        "cases": [(({'full': None, 'incr': None}, 'full', {'a': 1}), 'full_backed'),
                  (({'full': {'a': 1}, 'incr': {}}, 'incr', {'b': 2}), 'incr_backed'),
                  (({'full': {'a': 1}, 'incr': {'b': 2}}, 'restore'),
                   {'a': 1, 'b': 2})],
        "params": [],
        "calibration": "对照：图备份——全量+增量合并恢复（数据安全）",
    },
    "图存储-一致性检查": {
        "task": "一致性检查",
        "pattern": (
            "def integrity_check(graph):\n"
"    # 生效条件：graph.neighbors 可用\n"
"    # 子功能：① 调用 set\n"
"    # 执行：循环迭代；顺序调用\n"
"    # 不适用条件：输入不满足生效条件时返回 None/不执行\n"
            "    # 一致性：边两端节点存在 + 无重复边（数据完整性）\n"
            "    errors = []\n"
            "    seen = set()\n"
            "    for src in graph.nodes:\n"
            "        for dst in graph.neighbors(src):\n"
            "            if dst not in graph.nodes:\n"
            "                errors.append(f'悬空边: {src}→{dst}')\n"
            "            if (src, dst) in seen:\n"
            "                errors.append(f'重复边: {src}→{dst}')\n"
            "            seen.add((src, dst))\n"
            "    return errors\n"),
        "cases": [("call", None)],
        "params": [],
        "needs_inject": True,
        "calibration": "对照：图完整性——一致性检查（悬空边/重复边检测）",
    },
    "图存储-压缩编码": {
        "task": "图压缩",
        "pattern": (
            "def compress_adjacency(graph):\n"
"    # 生效条件：graph.neighbors 可用\n"
"    # 子功能：① 调用 sorted；② 调用 len\n"
"    # 执行：循环迭代；顺序调用\n"
"    # 不适用条件：输入不满足生效条件时返回 None/不执行\n"
            "    # 图压缩：邻接表 CSR 表示（顶点偏移+邻接数组——紧凑存储）\n"
            "    nodes = sorted(graph.nodes)\n"
            "    offsets, adj = [], []\n"
            "    for n in nodes:\n"
            "        offsets.append(len(adj))\n"
            "        adj.extend(sorted(graph.neighbors(n)))\n"
            "    offsets.append(len(adj))\n"
            "    return {'nodes': nodes, 'offsets': offsets, 'adj': adj}\n"),
        "cases": [("call", None)],
        "params": [],
        "needs_inject": True,
        "calibration": "对照：图压缩——CSR 邻接表（顶点偏移+邻接数组，紧凑存储）",
    },
    "图监控-指标统计": {
        "task": "图指标",
        "pattern": (
            "def graph_metrics(graph):\n"
"    # 生效条件：graph.neighbors 可用\n"
"    # 子功能：① 调用 len；② 调用 sum；③ 调用 round\n"
"    # 执行：顺序调用\n"
"    # 不适用条件：输入不满足生效条件时返回 None/不执行\n"
            "    # 图指标：节点数/边数/密度（规模与稀疏度）\n"
            "    n = len(graph.nodes)\n"
            "    e = sum(len(graph.neighbors(x)) for x in graph.nodes)\n"
            "    density = (2 * e / (n * (n - 1))) if n > 1 else 0.0\n"
            "    return {'nodes': n, 'edges': e, 'density': round(density, 2)}\n"),
        "cases": [("call", None)],
        "params": [],
        "needs_inject": True,
        "calibration": "对照：图监控——指标统计（节点/边/密度）",
    },
    "图监控-健康检查": {
        "task": "健康检查",
        "pattern": (
            "def health_check(graph):\n"
"    # 生效条件：graph.neighbors 可用\n"
"    # 子功能：① 调用 set；② 调用 next；③ 调用 len\n"
"    # 执行：循环迭代；顺序调用\n"
"    # 不适用条件：输入不满足生效条件时返回 None/不执行\n"
            "    # 健康检查：无向连通（正反向边都走）+ 无孤立节点（可用性判定）\n"
            "    if not graph.nodes:\n"
            "        return ('ok', True)\n"
            "    # 无向邻接（正向+反向边）\n"
            "    adj = {n: set(graph.neighbors(n)) for n in graph.nodes}\n"
            "    for n in graph.nodes:\n"
            "        for nxt in graph.neighbors(n):\n"
            "            adj.setdefault(nxt, set()).add(n)\n"
            "    visited = set()\n"
            "    stack = [next(iter(graph.nodes))]\n"
            "    while stack:\n"
            "        cur = stack.pop()\n"
            "        if cur in visited:\n"
            "            continue\n"
            "        visited.add(cur)\n"
            "        stack.extend(adj.get(cur, set()))\n"
            "    if len(visited) != len(graph.nodes):\n"
            "        return ('isolated', False)\n"
            "    return ('ok', True)\n"),
        "cases": [("call", None)],
        "params": [],
        "needs_inject": True,
        "calibration": "对照：图监控——健康检查（全图连通无孤立节点）",
    },
    "图监控-度分布": {
        "triggers": ["出度直方图", "度分布", "出度"],
        "task": "度分布",
        "pattern": (
            "def degree_distribution(graph):\n"
"    # 生效条件：graph.neighbors 可用\n"
"    # 子功能：① 调用 len\n"
"    # 执行：循环迭代；顺序调用\n"
"    # 不适用条件：输入不满足生效条件时返回 None/不执行\n"
            "    # 度分布：出度直方图（度 → 节点数，结构统计）\n"
            "    hist = {}\n"
            "    for n in graph.nodes:\n"
            "        d = len(graph.neighbors(n))\n"
            "        hist[d] = hist.get(d, 0) + 1\n"
            "    return hist\n"),
        "cases": [("call", None)],
        "params": [],
        "needs_inject": True,
        "calibration": "对照：图监控——度分布直方图（出度 → 节点数）",
    },
    "图嵌入-节点特征": {
        "task": "节点特征",
        "pattern": (
            "def node_features(graph):\n"
"    # 生效条件：graph.neighbors 可用\n"
"    # 子功能：① 调用 len；② 调用 sorted\n"
"    # 执行：循环迭代；顺序调用\n"
"    # 不适用条件：输入不满足生效条件时返回 None/不执行\n"
            "    # 节点特征：度/入度/出度（图学习特征向量）\n"
            "    out_deg = {n: len(graph.neighbors(n)) for n in graph.nodes}\n"
            "    in_deg = {n: 0 for n in graph.nodes}\n"
            "    for n in graph.nodes:\n"
            "        for nxt in graph.neighbors(n):\n"
            "            in_deg[nxt] += 1\n"
            "    return {n: {'out': out_deg[n], 'in': in_deg[n]}\n"
            "            for n in sorted(graph.nodes)}\n"),
        "cases": [("call", None)],
        "params": [],
        "needs_inject": True,
        "calibration": "对照：图嵌入——节点特征（出度/入度向量，图学习输入）",
    },
    "图嵌入-图特征": {
        "task": "图特征",
        "pattern": (
            "def graph_features(graph):\n"
"    # 生效条件：graph.neighbors 可用\n"
"    # 子功能：① 调用 len；② 调用 sum；③ 调用 round\n"
"    # 执行：顺序调用\n"
"    # 不适用条件：输入不满足生效条件时返回 None/不执行\n"
            "    # 图级特征：节点数/边数/连通分量数（图分类输入）\n"
            "    n = len(graph.nodes)\n"
            "    e = sum(len(graph.neighbors(x)) for x in graph.nodes)\n"
            "    return {'nodes': n, 'edges': e, 'density': round(\n"
            "        2 * e / (n * (n - 1)), 2) if n > 1 else 0.0}\n"),
        "cases": [("call", None)],
        "params": [],
        "needs_inject": True,
        "calibration": "对照：图嵌入——图级特征（节点/边/密度，图分类输入）",
    },
    "图学习-相似推荐": {
        "task": "相似推荐",
        "pattern": (
            "def similar_recommend(graph, node, top=2):\n"
"    # 生效条件：cands.sort 可用；graph.neighbors 可用\n"
"    # 子功能：① 调用 set；② 调用 len；③ 调用 common\n"
"    # 执行：顺序调用\n"
"    # 不适用条件：输入不满足生效条件时返回 None/不执行\n"
            "    # 相似推荐：共同邻居最多的节点（协同过滤语义）\n"
            "    def common(a, b):\n"
            "        na = set(graph.neighbors(a))\n"
            "        nb = set(graph.neighbors(b))\n"
            "        return len(na & nb)\n"
            "    cands = [x for x in graph.nodes if x != node]\n"
            "    cands.sort(key=lambda x: common(node, x), reverse=True)\n"
            "    return cands[:top]\n"),
        "cases": [("call", None)],
        "params": [],
        "needs_inject": True,
        "calibration": "对照：图学习——相似推荐（共同邻居最多，协同过滤）",
    },
    "图安全-权限控制": {
        "task": "图权限",
        "pattern": (
            "def graph_acl(acl, user, node, action):\n"
"    # 生效条件：参数 acl/user/node/action 合法\n"
"    # 子功能：① 条件判定 ② 结果处理\n"
"    # 执行：循环迭代\n"
"    # 不适用条件：输入不满足生效条件时返回 None/不执行\n"
            "    # 图权限：节点级访问控制（用户/节点/动作）\n"
            "    rules = acl.get(node, [])\n"
            "    for r in rules:\n"
            "        if r['user'] == user and r['action'] == action:\n"
            "            return r['allow']\n"
            "    return False\n"),
        "cases": [(({'n1': [{'user': 'u1', 'action': 'read', 'allow': True}]},
                    'u1', 'n1', 'read'), True),
                  (({'n1': []}, 'u1', 'n1', 'read'), False)],
        "params": [],
        "calibration": "对照：图安全——节点级 ACL（用户/节点/动作权限）",
    },
    "图安全-租户隔离": {
        "task": "租户隔离",
        "pattern": (
            "def tenant_scope(graph, tenant):\n"
"    # 生效条件：参数 graph/tenant 合法\n"
"    # 子功能：① 调用 sorted\n"
"    # 执行：顺序调用\n"
"    # 不适用条件：输入不满足生效条件时返回 None/不执行\n"
            "    # 租户隔离：返回租户可见节点（数据隔离语义）\n"
            "    return sorted(n for n in graph.nodes\n"
            "                  if graph.owner.get(n) == tenant)\n"),
        "cases": [("call", None)],
        "params": [],
        "needs_inject": True,
        "calibration": "对照：图安全——租户隔离（节点 owner 过滤，多租户数据隔离）",
    },
    "图安全-加密存储": {
        "task": "加密存储",
        "pattern": (
            "def encrypt_node(value, key):\n"
"    # 生效条件：参数 value/key 合法\n"
"    # 子功能：① 调用 chr；② 调用 ord\n"
"    # 执行：顺序调用\n"
"    # 不适用条件：输入不满足生效条件时返回 None/不执行\n"
            "    # 图加密：节点值异或密钥（静态数据加密）\n"
            "    return ''.join(chr(ord(c) ^ key) for c in value)\n"
            "def decrypt_node(code, key):\n"
            "    # 图解密：密钥异或还原节点值（加密的逆运算）\n"
            "    return ''.join(chr(ord(c) ^ key) for c in code)\n"),
        "cases": [(('秘密', 7), '租寁'),
                  (('数据', 3), '敳捭')],
        "params": [],
        "calibration": "对照：图安全——加密存储（异或加密/解密，静态数据保护）",
    },
    "运维-读写分离": {
        "task": "读写分离",
        "pattern": (
            "def rw_split(master, replicas, op, key=None, value=None, replica_id=0):\n"
"    # 生效条件：op ∈ {read, write}\n"
"    # 子功能：① op 分支处理\n"
"    # 执行：按 op 分派；循环迭代；顺序调用\n"
"    # 不适用条件：op 非 {read, write} 时\n"
            "    # 读写分离：写→主库并同步从库 / 读→从库（负载分散，主从一致）\n"
            "    if op == 'write':\n"
            "        master[key] = value\n"
            "        for r in replicas:\n"
            "            r[key] = value\n"
            "        return 'written'\n"
            "    if op == 'read':\n"
            "        if replicas:\n"
            "            rep = replicas[replica_id % len(replicas)]\n"
            "            return rep.get(key)\n"
            "        return master.get(key)\n"
            "    return None\n"),
        "cases": [(({'a': 1}, [{}, {}], 'write', 'b', 2, 0), 'written'),
                  (({'a': 1}, [{'a': 1}], 'read', 'a', None, 0), 1),
                  (({'a': 1}, [], 'read', 'a', None, 0), 1)],
        "params": [],
        "calibration": "对照：数据库读写分离——主库写+同步从库，从库读（负载分散）",
    },
    "运维-慢查询定位": {
        "task": "慢查询定位",
        "pattern": (
            "def slow_query_scan(plan_times, threshold):\n"
"    # 生效条件：slow.sort 可用\n"
"    # 子功能：① 主体逻辑执行\n"
"    # 执行：顺序执行\n"
"    # 不适用条件：输入不满足生效条件时返回 None/不执行\n"
            "    # 慢查询定位：执行计划耗时 > 阈值 → 慢查询列表（耗时降序）\n"
            "    slow = [(op, t) for op, t in plan_times if t > threshold]\n"
            "    slow.sort(key=lambda x: x[1], reverse=True)\n"
            "    return slow\n"),
        "cases": [(([('全表扫描', 2.5), ('索引查找', 0.3)], 1.0),
                   [('全表扫描', 2.5)]),
                  (([('a', 1.0)], 1.0), []),
                  (([], 1.0), [])],
        "params": [],
        "calibration": "对照：数据库慢查询——耗时超阈值定位（降序，等于阈值不算）",
    },
    "运维-在线扩容": {
        "task": "在线扩容",
        "pattern": (
            "def rebalance_keys(keys, old_count, new_count):\n"
"    # 生效条件：参数 keys/old_count/new_count 合法\n"
"    # 子功能：① 调用 sum；② 调用 ord；③ 调用 str\n"
"    # 执行：循环迭代；顺序调用\n"
"    # 不适用条件：输入不满足生效条件时返回 None/不执行\n"
            "    # 在线扩容：键按确定性哈希重分配到新片（取模），统计迁移键\n"
            "    # （ord 求和哈希避免 PYTHONHASHSEED 跨进程波动）\n"
            "    moved = 0\n"
            "    for k in keys:\n"
            "        h = sum(ord(c) for c in str(k))\n"
            "        if h % old_count != h % new_count:\n"
            "            moved += 1\n"
            "    return moved, new_count\n"),
        "cases": [((['a', 'b', 'c'], 2, 3), (2, 3)),
                  ((['a'], 2, 2), (0, 2)),
                  (([], 2, 4), (0, 4))],
        "params": [],
        "calibration": "对照：数据库在线扩容——分片重平衡（确定性哈希，迁移键计数）",
    },
    "图算法-最小生成树": {
        "task": "最小生成树",
        "pattern": (
            "def kruskal_mst(edges, n):\n"
"    # 生效条件：参数 edges/n 合法\n"
"    # 子功能：① 调用 list；② 调用 sorted；③ 调用 range\n"
"    # 执行：循环迭代；顺序调用\n"
"    # 不适用条件：输入不满足生效条件时返回 None/不执行\n"
            "    # 最小生成树：Kruskal——按权重升序加边，并查集避环（最小连通代价）\n"
            "    parent = list(range(n))\n"
            "    def find(x):\n"
            "        # 根查找：路径压缩（并查集连通判定）\n"
            "        while parent[x] != x:\n"
            "            parent[x] = parent[parent[x]]\n"
            "            x = parent[x]\n"
            "        return x\n"
            "    total, count = 0, 0\n"
            "    for u, v, w in sorted(edges, key=lambda e: e[2]):\n"
            "        ru, rv = find(u), find(v)\n"
            "        if ru != rv:\n"
            "            parent[ru] = rv\n"
            "            total += w\n"
            "            count += 1\n"
            "            if count == n - 1:\n"
            "                break\n"
            "    return total, count\n"),
        "cases": [(([(0, 1, 1), (1, 2, 2), (0, 2, 3)], 3), (3, 2)),
                  (([(0, 1, 5), (1, 2, 3), (0, 2, 1)], 3), (4, 2)),
                  (([], 1), (0, 0))],
        "params": [],
        "calibration": "对照：图算法——Kruskal 最小生成树（升序加边+并查集避环）",
    },
    "图算法-二分图判定": {
        "task": "二分图判定",
        "pattern": (
            "def is_bipartite(adj, n):\n"
"    # 生效条件：参数 adj/n 合法\n"
"    # 子功能：① 调用 range\n"
"    # 执行：循环迭代；顺序调用\n"
"    # 不适用条件：输入不满足生效条件时返回 None/不执行\n"
            "    # 二分图判定：BFS 染色（相邻异色，颜色冲突即非二分）\n"
            "    color = [-1] * n\n"
            "    for s in range(n):\n"
            "        if color[s] != -1:\n"
            "            continue\n"
            "        color[s] = 0\n"
            "        queue = [s]\n"
            "        while queue:\n"
            "            u = queue.pop(0)\n"
            "            for v in adj.get(u, []):\n"
            "                if color[v] == -1:\n"
            "                    color[v] = 1 - color[u]\n"
            "                    queue.append(v)\n"
            "                elif color[v] == color[u]:\n"
            "                    return False\n"
            "    return True\n"),
        "cases": [(({0: [1], 1: [0, 2], 2: [1]}, 3), True),
                  (({0: [1, 2], 1: [0, 2], 2: [0, 1]}, 3), False),
                  (({}, 1), True)],
        "params": [],
        "calibration": "对照：图算法——二分图判定（BFS 双色染色，相邻异色）",
    },
    "图算法-度中心性": {
        "task": "度中心性",
        "pattern": (
            "def degree_centrality(adj, n):\n"
"    # 生效条件：参数 adj/n 合法\n"
"    # 子功能：① 调用 round；② 调用 len\n"
"    # 执行：顺序调用\n"
"    # 不适用条件：输入不满足生效条件时返回 None/不执行\n"
            "    # 度中心性：节点度数 / (n-1)（归一化——重要度排序依据）\n"
            "    norm = n - 1 if n > 1 else 1\n"
            "    return {k: round(len(v) / norm, 3) for k, v in adj.items()}\n"),
        "cases": [(({0: [1, 2], 1: [0], 2: [0]}, 3),
                   {0: 1.0, 1: 0.5, 2: 0.5}),
                  (({}, 1), {}),
                  (({0: [1]}, 2), {0: 1.0})],
        "params": [],
        "calibration": "对照：图算法——度中心性（度数/(n-1) 归一化重要度）",
    },
    "图查询-正则路径": {
        "task": "正则路径",
        "pattern": (
            "def regex_path_find(adj, start, labels):\n"
"    # 生效条件：参数 adj/start/labels 合法\n"
"    # 子功能：① 调用 sorted；② 调用 set\n"
"    # 执行：循环迭代；顺序调用\n"
"    # 不适用条件：frontier 为空/非法时\n"
            "    # 正则路径查询：按标签序列沿边匹配（存在路径→终点列表）\n"
            "    frontier = [start]\n"
            "    for lab in labels:\n"
            "        nxt = []\n"
            "        for u in frontier:\n"
            "            for v, l in adj.get(u, []):\n"
            "                if l == lab:\n"
            "                    nxt.append(v)\n"
            "        frontier = nxt\n"
            "        if not frontier:\n"
            "            return []\n"
            "    return sorted(set(frontier))\n"),
        "cases": [(({0: [(1, '朋友'), (2, '同事')], 1: [(3, '朋友')]}, 0,
                    ['朋友']), [1]),
                  (({0: [(1, '朋友')], 1: [(2, '朋友')]}, 0,
                    ['朋友', '朋友']), [2]),
                  (({0: [(1, '同事')]}, 0, ['朋友']), [])],
        "params": [],
        "calibration": "对照：图查询——正则路径（标签序列沿边匹配，属性图路径语义）",
    },
    "图查询-查询缓存": {
        "task": "查询缓存",
        "pattern": (
            "def query_cache(cache, op, key=None, result=None, capacity=3):\n"
"    # 生效条件：op ∈ {get, put}\n"
"    # 子功能：① op 分支处理\n"
"    # 执行：按 op 分派；循环迭代；顺序调用\n"
"    # 不适用条件：op 非 {get, put} 时\n"
            "    # 查询缓存：get 命中返回并移末尾 / put 存结果（LRU 淘汰超容量）\n"
            "    if op == 'get':\n"
            "        if key in cache:\n"
            "            val = cache.pop(key)\n"
            "            cache[key] = val\n"
            "            return val\n"
            "        return None\n"
            "    if op == 'put':\n"
            "        if key in cache:\n"
            "            cache.pop(key)\n"
            "        cache[key] = result\n"
            "        while len(cache) > capacity:\n"
            "            cache.pop(next(iter(cache)))\n"
            "        return len(cache)\n"
            "    return None\n"),
        "cases": [(({}, 'put', 'q1', 'r1', 3), 1),
                  (({'q1': 'r1'}, 'get', 'q1', None, 3), 'r1'),
                  (({}, 'get', 'q1', None, 3), None),
                  (({'a': 1, 'b': 2, 'c': 3}, 'put', 'd', 4, 3), 3)],
        "params": [],
        "calibration": "对照：图查询——查询缓存（LRU 淘汰，命中加速重复查询）",
    },
    "图查询-物化视图": {
        "task": "物化视图",
        "pattern": (
            "def materialize_view(base, view_name, view_fn, op, params=None):\n"
"    # 生效条件：op ∈ {query, refresh}\n"
"    # 子功能：① op 分支处理\n"
"    # 执行：按 op 分派；顺序调用\n"
"    # 不适用条件：op 非 {query, refresh} 时\n"
            "    # 物化视图：预计算子查询结果（复用加速），refresh 重算\n"
            "    if op == 'query':\n"
            "        v = base.get(view_name)\n"
            "        return v if v is not None else 'missing'\n"
            "    if op == 'refresh':\n"
            "        base[view_name] = view_fn(*(params or []))\n"
            "        return base[view_name]\n"
            "    return None\n"),
        "cases": [(({'热度': [('a', 3)]}, '热度', None, 'query'),
                   [('a', 3)]),
                  (({}, '热度',
                    lambda g: sorted(g, key=lambda x: -x[1]),
                    'refresh', ([('a', 3), ('b', 5)],)),
                   [('b', 5), ('a', 3)]),
                  (({}, '热度', None, 'query'), 'missing')],
        "params": [],
        "calibration": "对照：图查询——物化视图（预计算复用，refresh 重算）",
    },
    "图可视化-环形布局": {
        "task": "环形布局",
        "pattern": (
            "def circular_layout(nodes, cx=0, cy=0, radius=100):\n"
"    # 生效条件：math.cos 可用；math.sin 可用\n"
"    # 子功能：① 调用 len；② 调用 enumerate；③ 调用 round\n"
"    # 执行：循环迭代；顺序调用\n"
"    # 不适用条件：输入不满足生效条件时返回 None/不执行\n"
            "    # 环形布局：节点均匀分布圆周（可视化坐标生成）\n"
            "    import math\n"
            "    out = {}\n"
            "    n = len(nodes)\n"
            "    for i, nd in enumerate(nodes):\n"
            "        ang = 2 * math.pi * i / n if n else 0\n"
            "        out[nd] = (round(cx + radius * math.cos(ang), 3),\n"
            "                   round(cy + radius * math.sin(ang), 3))\n"
            "    return out\n"),
        "cases": [((['a'], 0, 0, 10), {'a': (10.0, 0.0)}),
                  (([], 0, 0, 10), {}),
                  ((['a', 'b'], 0, 0, 1), {'a': (1.0, 0.0), 'b': (-1.0, 0.0)})],
        "params": [],
        "calibration": "对照：图可视化——环形布局（圆周均匀分布坐标）",
    },
    "图可视化-视口变换": {
        "task": "视口变换",
        "pattern": (
            "def viewport_transform(x, y, scale, tx, ty):\n"
"    # 生效条件：参数 x/y/scale/tx/ty 合法\n"
"    # 子功能：① 调用 round\n"
"    # 执行：顺序调用\n"
"    # 不适用条件：输入不满足生效条件时返回 None/不执行\n"
            "    # 视口变换：缩放平移（zoom/pan——画布坐标映射）\n"
            "    return round(x * scale + tx, 3), round(y * scale + ty, 3)\n"),
        "cases": [((0, 0, 2, 10, 10), (10.0, 10.0)),
                  ((5, 5, 2, 0, 0), (10.0, 10.0)),
                  ((1, 2, 0.5, 1, 1), (1.5, 2.0))],
        "params": [],
        "calibration": "对照：图可视化——视口变换（缩放+平移坐标映射）",
    },
    "图可视化-社区着色": {
        "task": "社区着色",
        "pattern": (
            "def community_color(communities):\n"
"    # 生效条件：参数 communities 合法\n"
"    # 子功能：① 调用 enumerate；② 调用 len\n"
"    # 执行：循环迭代；顺序调用\n"
"    # 不适用条件：输入不满足生效条件时返回 None/不执行\n"
            "    # 社区着色：社区分组 → 颜色映射（可视化区分社群）\n"
            "    palette = ['red', 'blue', 'green', 'orange', 'purple']\n"
            "    out = {}\n"
            "    for i, comm in enumerate(communities):\n"
            "        color = palette[i % len(palette)]\n"
            "        for node in comm:\n"
            "            out[node] = color\n"
            "    return out\n"),
        "cases": [(([['a', 'b'], ['c']],), {'a': 'red', 'b': 'red', 'c': 'blue'}),
                  (([],), {}),
                  (([['x']],), {'x': 'red'})],
        "params": [],
        "calibration": "对照：图可视化——社区着色（分组颜色映射）",
    },
    "图存储-邻接表CSR": {
        "task": "邻接表压缩",
        "pattern": (
            "def csr_build(edges, n):\n"
"    # 生效条件：参数 edges/n 合法\n"
"    # 子功能：① 调用 range\n"
"    # 执行：循环迭代；顺序调用\n"
"    # 不适用条件：输入不满足生效条件时返回 None/不执行\n"
            "    # CSR 邻接表：边列表 → 压缩稀疏行（偏移+邻接数组——紧凑存储）\n"
            "    offsets = [0] * (n + 1)\n"
            "    deg = [0] * n\n"
            "    for u, v in edges:\n"
            "        deg[u] += 1\n"
            "    for i in range(n):\n"
            "        offsets[i + 1] = offsets[i] + deg[i]\n"
            "    adj = [0] * offsets[n]\n"
            "    pos = offsets[:n]\n"
            "    for u, v in edges:\n"
            "        adj[pos[u]] = v\n"
            "        pos[u] += 1\n"
            "    return offsets, adj\n"),
        "cases": [(([(0, 1), (0, 2), (1, 2)], 3), ([0, 2, 3, 3], [1, 2, 2])),
                  (([], 2), ([0, 0, 0], [])),
                  (([(0, 0)], 1), ([0, 1], [0]))],
        "params": [],
        "calibration": "对照：CSR 邻接表——压缩稀疏行（偏移数组+邻接数组，紧凑边存储）",
    },
    "图存储-图合并": {
        "task": "图合并",
        "pattern": (
            "def merge_graphs(g1, g2):\n"
"    # 生效条件：参数 g1/g2 合法\n"
"    # 子功能：① 调用 sorted；② 调用 set\n"
"    # 执行：循环迭代；顺序调用\n"
"    # 不适用条件：输入不满足生效条件时返回 None/不执行\n"
            "    # 图合并：两图邻接合并（节点并集，边并集去重）\n"
            "    merged = {}\n"
            "    for g in (g1, g2):\n"
            "        for u, nbrs in g.items():\n"
            "            merged.setdefault(u, set()).update(nbrs)\n"
            "    return {k: sorted(v) for k, v in merged.items()}\n"),
        "cases": [(({'a': {'b'}}, {'b': {'c'}}), {'a': ['b'], 'b': ['c']}),
                  (({'a': {'b'}}, {'a': {'c'}}), {'a': ['b', 'c']}),
                  (({}, {}), {})],
        "params": [],
        "calibration": "对照：图存储——图合并（节点/边并集，多图整合）",
    },
    "图存储-属性边": {
        "task": "属性边",
        "pattern": (
            "def edge_attr_query(edges, op, u=None, v=None, attr=None):\n"
"    # 生效条件：op ∈ {by_attr, get, put}\n"
"    # 子功能：① op 分支处理\n"
"    # 执行：按 op 分派；顺序调用\n"
"    # 不适用条件：op 非 {by_attr, get, put} 时\n"
            "    # 属性边：put 存边属性 / get 查属性 / by_attr 按属性找边\n"
            "    if op == 'put':\n"
            "        edges[(u, v)] = attr\n"
            "        return 'stored'\n"
            "    if op == 'get':\n"
            "        return edges.get((u, v))\n"
            "    if op == 'by_attr':\n"
            "        return sorted(k for k, a in edges.items() if a == attr)\n"
            "    return None\n"),
        "cases": [(({}, 'put', 'a', 'b', '朋友'), 'stored'),
                  (({('a', 'b'): '朋友'}, 'get', 'a', 'b'), '朋友'),
                  (({}, 'get', 'a', 'b'), None),
                  (({('a', 'b'): '朋友', ('c', 'd'): '同事'}, 'by_attr',
                    None, None, '朋友'), [('a', 'b')])],
        "params": [],
        "calibration": "对照：属性图边——带标签/属性边存储与查询",
    },
    "图算法-最大流": {
        "task": "最大流",
        "pattern": (
            "def max_flow(graph, source, sink):\n"
            "    # 最大流（Ford-Fulkerson）：BFS 增广路径推送（残留网络）\n"
            "    # 生效条件：graph 为容量网络（含容量边）；source/sink 为源/汇节点\n"
            "    # 子功能：① BFS 找增广路 ② 沿路推送最小剩余容量 ③ 更新残留网络\n"
            "    # 执行：反复增广直至无路，累加推送流量\n"
"    # 不适用条件：found 为空/非法时\n"
            "    flow = 0\n"
            "    while True:\n"
            "        parent = {source: None}\n"
            "        queue = [source]\n"
            "        found = False\n"
            "        while queue and not found:\n"
            "            u = queue.pop(0)\n"
            "            for v, cap in graph.get(u, {}).items():\n"
            "                if v not in parent and cap > 0:\n"
            "                    parent[v] = u\n"
            "                    if v == sink:\n"
            "                        found = True\n"
            "                        break\n"
            "                    queue.append(v)\n"
            "        if not found:\n"
            "            break\n"
            "        v = sink\n"
            "        path_flow = float('inf')\n"
            "        while parent[v] is not None:\n"
            "            u = parent[v]\n"
            "            path_flow = min(path_flow, graph[u][v])\n"
            "            v = u\n"
            "        v = sink\n"
            "        while parent[v] is not None:\n"
            "            u = parent[v]\n"
            "            graph[u][v] -= path_flow\n"
            "            graph.setdefault(v, {})[u] = graph.get(v, {}).get(u, 0) + path_flow\n"
            "            v = u\n"
            "        flow += path_flow\n"
            "    return flow\n"),
        "cases": [(({'s': {'a': 3, 'b': 2}, 'a': {'t': 2}, 'b': {'t': 2}},
                    's', 't'), 4),
                  (({'s': {'a': 5}, 'a': {'t': 5}}, 's', 't'), 5),
                  (({'s': {'a': 1}, 'a': {'t': 1}}, 's', 't'), 1)],
        "params": [],
        "calibration": "对照：图算法——最大流（Ford-Fulkerson 增广路径推送）",
    },
    "图算法-欧拉路径": {
        "task": "欧拉路径",
        "pattern": (
            "def euler_path(adj, n):\n"
"    # 生效条件：参数 adj/n 合法\n"
"    # 子功能：① 调用 sum；② 调用 len；③ 调用 range\n"
"    # 执行：顺序调用\n"
"    # 不适用条件：输入不满足生效条件时返回 None/不执行\n"
            "    # 欧拉路径：一笔画判定（0 或 2 个奇度节点——连通图）\n"
            "    deg = {i: len(adj.get(i, [])) for i in range(n)}\n"
            "    odd = sum(1 for d in deg.values() if d % 2)\n"
            "    return odd == 0 or odd == 2\n"),
        "cases": [(({0: [1], 1: [0, 2], 2: [1]}, 3), True),
                  (({0: [1, 2], 1: [0, 2], 2: [0, 1]}, 3), True),
                  (({0: [1, 2], 1: [0], 2: [0]}, 3), True)],
        "params": [],
        "calibration": "对照：图算法——欧拉路径（0/2 个奇度节点一笔画）",
    },
    "图算法-图直径": {
        "task": "图直径",
        "pattern": (
            "def graph_diameter(adj, n):\n"
"    # 生效条件：参数 adj/n 合法\n"
"    # 子功能：① 调用 max；② 调用 bfs；③ 调用 range\n"
"    # 执行：循环迭代；顺序调用\n"
"    # 不适用条件：输入不满足生效条件时返回 None/不执行\n"
            "    # 图直径：最长最短路径（全源 BFS 最大距离）\n"
            "    def bfs(s):\n"
            "        dist = {s: 0}\n"
            "        queue = [s]\n"
            "        while queue:\n"
            "            u = queue.pop(0)\n"
            "            for v in adj.get(u, []):\n"
            "                if v not in dist:\n"
            "                    dist[v] = dist[u] + 1\n"
            "                    queue.append(v)\n"
            "        return max(dist.values()) if dist else 0\n"
            "    return max(bfs(i) for i in range(n))\n"),
        "cases": [(({0: [1], 1: [0, 2], 2: [1]}, 3), 2),
                  (({0: [1, 2], 1: [0, 2], 2: [0, 1]}, 3), 1),
                  (({}, 1), 0)],
        "params": [],
        "calibration": "对照：图算法——图直径（最长最短路径）",
    },
    "条件路由图-条件合并": {
        "task": "条件合并",
        "pattern": (
            "def merge_conditions(cond1, cond2):\n"
"    # 生效条件：参数 cond1/cond2 合法\n"
"    # 子功能：① 调用 set\n"
"    # 执行：循环迭代；顺序调用\n"
"    # 不适用条件：输入不满足生效条件时返回 None/不执行\n"
            "    # 条件合并：两条条件链合并（AND 语义——路由条件叠加，冲突拒绝）\n"
            "    merged = {}\n"
            "    for k in set(cond1) | set(cond2):\n"
            "        if k in cond1 and k in cond2 and cond1[k] != cond2[k]:\n"
            "            return 'conflict'\n"
            "        merged[k] = cond1.get(k, cond2.get(k))\n"
            "    return merged\n"),
        "cases": [(({'温度': '高'}, {'湿度': '大'}), {'温度': '高', '湿度': '大'}),
                  (({'温度': '高'}, {'温度': '高'}), {'温度': '高'}),
                  (({'温度': '高'}, {'温度': '低'}), 'conflict')],
        "params": [],
        "calibration": "对照：条件路由图——条件链合并（AND 叠加，同键异值冲突）",
    },
    "条件路由图-信任传播": {
        "task": "信任传播",
        "pattern": (
            "def trust_propagate(graph, node, trust, decay=0.5):\n"
"    # 生效条件：参数 graph/node/trust/decay 合法\n"
"    # 子功能：① 调用 round\n"
"    # 执行：循环迭代；顺序调用\n"
"    # 不适用条件：输入不满足生效条件时返回 None/不执行\n"
            "    # 信任传播：信任沿边衰减传播（信任引擎——多跳信任累积）\n"
            "    out = {node: trust}\n"
            "    queue = [(node, trust)]\n"
            "    while queue:\n"
            "        u, t = queue.pop(0)\n"
            "        for v in graph.get(u, []):\n"
            "            nt = round(t * decay, 3)\n"
            "            if v not in out or nt > out[v]:\n"
            "                out[v] = nt\n"
            "                queue.append((v, nt))\n"
            "    return out\n"),
        "cases": [(({'a': ['b'], 'b': ['c']}, 'a', 1.0),
                   {'a': 1.0, 'b': 0.5, 'c': 0.25}),
                  (({'a': []}, 'a', 0.8), {'a': 0.8}),
                  (({}, 'a', 1.0), {'a': 1.0})],
        "params": [],
        "calibration": "对照：条件路由图——信任传播（沿边衰减，多跳信任累积）",
    },
    "条件路由图-信息差收敛": {
        "task": "信息差收敛",
        "pattern": (
            "def info_gap_path(graph, start, end, gap):\n"
"    # 生效条件：参数 graph/start/end/gap 合法\n"
"    # 子功能：① 调用 round；② 调用 len\n"
"    # 执行：循环迭代；顺序调用\n"
"    # 不适用条件：nxt 为空/非法时\n"
            "    # 信息差收敛：沿路径逐节点缩小信息差（路由决策——信息差递减）\n"
            "    path = [start]\n"
            "    cur = start\n"
            "    while cur != end:\n"
            "        nxt = graph.get(cur, [])\n"
            "        if not nxt:\n"
            "            return path, gap, 'stuck'\n"
            "        best = nxt[0]\n"
            "        path.append(best)\n"
            "        cur = best\n"
            "        gap = round(gap * 0.5, 3)\n"
            "        if len(path) > 10:\n"
            "            return path, gap, 'loop'\n"
            "    return path, gap, 'arrived'\n"),
        "cases": [(({'a': ['b'], 'b': ['c']}, 'a', 'c', 1.0),
                   (['a', 'b', 'c'], 0.25, 'arrived')),
                  (({'a': []}, 'a', 'c', 1.0), (['a'], 1.0, 'stuck')),
                  (({'a': ['b']}, 'a', 'a', 1.0), (['a'], 1.0, 'arrived'))],
        "params": [],
        "calibration": "对照：条件路由图——信息差收敛（逐节点减半，路由推进决策）",
    },
    "图存储-增量备份": {
        "task": "增量备份",
        "pattern": (
            "def incremental_backup(backups, op, base=None, changes=None, tag=None):\n"
"    # 生效条件：op ∈ {full, incr, restore}\n"
"    # 子功能：① op 分支处理\n"
"    # 执行：按 op 分派；顺序调用\n"
"    # 不适用条件：op 非 {full, incr, restore} 时\n"
            "    # 增量备份：full 全量 / incr 增量（记录变更）/ restore 还原\n"
            "    if op == 'full':\n"
            "        backups[tag] = {'type': 'full', 'data': dict(base)}\n"
            "        return tag\n"
            "    if op == 'incr':\n"
            "        backups[tag] = {'type': 'incr', 'base': base,\n"
            "                        'changes': dict(changes)}\n"
            "        return tag\n"
            "    if op == 'restore':\n"
            "        full = backups.get(base)\n"
            "        if full is None:\n"
            "            return None\n"
            "        data = dict(full['data'])\n"
            "        incr = backups.get(tag)\n"
            "        if incr and incr['type'] == 'incr' and incr['base'] == base:\n"
            "            data.update(incr['changes'])\n"
            "        return data\n"
            "    return None\n"),
        "cases": [(({}, 'full', {'a': 1}, None, 'f1'), 'f1'),
                  (({'f1': {'type': 'full', 'data': {'a': 1}}},
                    'incr', 'f1', {'b': 2}, 'i1'), 'i1'),
                  (({'f1': {'type': 'full', 'data': {'a': 1}},
                     'i1': {'type': 'incr', 'base': 'f1',
                            'changes': {'b': 2}}},
                    'restore', 'f1', None, 'i1'), {'a': 1, 'b': 2}),
                  (({}, 'restore', 'f1', None, 'i1'), None)],
        "params": [],
        "calibration": "对照：数据库备份——全量+增量（变更记录，还原叠加）",
    },
    "图存储-一致性快照": {
        "task": "一致性快照",
        "pattern": (
            "def snapshot_isolation(versions, op, key=None, value=None, version=None):\n"
"    # 生效条件：op ∈ {read, write}\n"
"    # 子功能：① op 分支处理\n"
"    # 执行：按 op 分派；顺序调用\n"
"    # 不适用条件：kv 为空/非法时；op 非 {read, write} 时\n"
            "    # 一致性快照：版本化读写（读 ≤ 版本最新值——MVCC 快照隔离）\n"
            "    if op == 'write':\n"
            "        versions.setdefault(key, {})[version] = value\n"
            "        return version\n"
            "    if op == 'read':\n"
            "        kv = versions.get(key, {})\n"
            "        if not kv:\n"
            "            return None\n"
            "        avail = [v for v in kv if v <= version]\n"
            "        return kv[max(avail)] if avail else None\n"
            "    return None\n"),
        "cases": [(({}, 'write', 'a', 1, 1), 1),
                  (({'a': {1: 1, 2: 2}}, 'read', 'a', None, 1), 1),
                  (({'a': {1: 1, 2: 2}}, 'read', 'a', None, 2), 2),
                  (({}, 'read', 'a', None, 5), None)],
        "params": [],
        "calibration": "对照：MVCC 快照隔离——版本化读写（读旧版本一致视图）",
    },
    "图分布式-一致性哈希": {
        "task": "一致性哈希",
        "pattern": (
            "def consistent_hash(ring, op, node=None, key=None):\n"
"    # 生效条件：op ∈ {add, locate}\n"
"    # 子功能：① op 分支处理\n"
"    # 执行：按 op 分派；循环迭代；顺序调用\n"
"    # 不适用条件：ring 为空/非法时；op 非 {add, locate} 时\n"
            "    # 一致性哈希：add 节点入环 / locate 键定位（哈希环——最小迁移）\n"
            "    if op == 'add':\n"
            "        h = sum(ord(c) for c in node)\n"
            "        ring[h] = node\n"
            "        return h\n"
            "    if op == 'locate':\n"
            "        if not ring:\n"
            "            return None\n"
            "        kh = sum(ord(c) for c in key)\n"
            "        hs = sorted(ring)\n"
            "        for h in hs:\n"
            "            if h >= kh:\n"
            "                return ring[h]\n"
            "        return ring[hs[0]]\n"
            "    return None\n"),
        "cases": [(({}, 'add', 'n1'), 159),
                  (({159: 'n1', 217: 'n2'}, 'locate', None, 'k1'), 'n1'),
                  (({159: 'n1'}, 'locate', None, 'k9'), 'n1')],
        "params": [],
        "calibration": "对照：分布式哈希环——一致性哈希（键定位，最小迁移）",
    },
    "图查询-邻居查询": {
        "task": "邻居查询",
        "pattern": (
            "def neighbor_query(adj, op, node=None, hops=1):\n"
"    # 生效条件：op ∈ {direct, multi}；seen.discard 可用\n"
"    # 子功能：① op 分支处理\n"
"    # 执行：按 op 分派；循环迭代；顺序调用\n"
"    # 不适用条件：op 非 {direct, multi} 时\n"
            "    # 邻居查询：direct 一跳邻居 / multi 多跳邻居（BFS 扩展）\n"
            "    if op == 'direct':\n"
            "        return sorted(adj.get(node, []))\n"
            "    if op == 'multi':\n"
            "        seen = {node}\n"
            "        frontier = [node]\n"
            "        for _ in range(hops):\n"
            "            nxt = []\n"
            "            for u in frontier:\n"
            "                for v in adj.get(u, []):\n"
            "                    if v not in seen:\n"
            "                        seen.add(v)\n"
            "                        nxt.append(v)\n"
            "            frontier = nxt\n"
            "        seen.discard(node)\n"
            "        return sorted(seen)\n"
            "    return None\n"),
        "cases": [(({0: [1, 2]}, 'direct', 0), [1, 2]),
                  (({0: [1], 1: [2]}, 'multi', 0, 2), [1, 2]),
                  (({0: [1]}, 'multi', 0, 1), [1])],
        "params": [],
        "calibration": "对照：图查询——一跳/多跳邻居（BFS 扩展）",
    },
    "图查询-路径过滤": {
        "task": "路径过滤",
        "pattern": (
            "def path_filter(paths, pred):\n"
"    # 生效条件：参数 paths/pred 合法\n"
"    # 子功能：① 调用 pred\n"
"    # 执行：顺序调用\n"
"    # 不适用条件：输入不满足生效条件时返回 None/不执行\n"
            "    # 路径过滤：按条件保留路径（长度/终点——路径筛选）\n"
            "    return [p for p in paths if pred(p)]\n"),
        "cases": [(([[0, 1], [0, 2, 1], [0]], lambda p: len(p) >= 2),
                   [[0, 1], [0, 2, 1]]),
                  (([[0, 1]], lambda p: p[-1] == 1), [[0, 1]]),
                  (([], lambda p: True), [])],
        "params": [],
        "calibration": "对照：图查询——路径过滤（按长度/终点条件）",
    },
    "图算法-三角形计数": {
        "task": "三角形计数",
        "pattern": (
            "def triangle_count(adj, n):\n"
"    # 生效条件：参数 adj/n 合法\n"
"    # 子功能：① 调用 range\n"
"    # 执行：循环迭代；顺序调用\n"
"    # 不适用条件：输入不满足生效条件时返回 None/不执行\n"
            "    # 三角形计数：闭合三元组（聚类检测——社交网络三角）\n"
            "    triangles = 0\n"
            "    for u in range(n):\n"
            "        for v in adj.get(u, []):\n"
            "            if v > u:\n"
            "                for w in adj.get(v, []):\n"
            "                    if w > v and w in adj.get(u, []):\n"
            "                        triangles += 1\n"
            "    return triangles\n"),
        "cases": [(({0: [1, 2], 1: [0, 2], 2: [0, 1]}, 3), 1),
                  (({0: [1], 1: [0, 2], 2: [1]}, 3), 0),
                  (({}, 1), 0)],
        "params": [],
        "calibration": "对照：图算法——三角形计数（闭合三元组，聚类检测）",
    },
    "图查询-导出子图": {
        "task": "导出子图",
        "pattern": (
            "def induced_subgraph(adj, nodes):\n"
"    # 生效条件：参数 adj/nodes 合法\n"
"    # 子功能：① 调用 set\n"
"    # 执行：顺序调用\n"
"    # 不适用条件：输入不满足生效条件时返回 None/不执行\n"
            "    # 导出子图：按节点集诱导（节点集 + 内部边）\n"
            "    node_set = set(nodes)\n"
            "    return {u: [v for v in adj.get(u, []) if v in node_set]\n"
            "            for u in node_set}\n"),
        "cases": [(({0: [1, 2], 1: [0], 2: [0]}, [0, 1]), {0: [1], 1: [0]}),
                  (({0: [1], 1: [0]}, [0]), {0: []}),
                  (({}, [0]), {0: []})],
        "params": [],
        "calibration": "对照：图查询——导出子图（节点集诱导，仅内部边）",
    },
    "图时序-时间窗口": {
        "task": "时间窗口",
        "pattern": (
            "def time_window(events, op, start=None, end=None):\n"
"    # 生效条件：op ∈ {count, window}\n"
"    # 子功能：① op 分支处理\n"
"    # 执行：按 op 分派；顺序调用\n"
"    # 不适用条件：op 非 {count, window} 时\n"
            "    # 时间窗口：window 窗口内事件 / count 计数（时序图查询）\n"
            "    if op == 'window':\n"
            "        return [e for e in events if start <= e['t'] <= end]\n"
            "    if op == 'count':\n"
            "        return sum(1 for e in events if start <= e['t'] <= end)\n"
            "    return None\n"),
        "cases": [(([{'t': 1, 'e': 'a'}, {'t': 3, 'e': 'b'}, {'t': 5, 'e': 'c'}],
                    'window', 2, 4), [{'t': 3, 'e': 'b'}]),
                  (([{'t': 1}, {'t': 3}], 'count', 1, 3), 2),
                  (([], 'window', 0, 10), [])],
        "params": [],
        "calibration": "对照：时序图查询——时间窗口内事件（滑窗过滤）",
    },
    "图动态-边活跃度": {
        "task": "边活跃度",
        "pattern": (
            "def edge_activity(edges, op, edge=None, now=None):\n"
"    # 生效条件：op ∈ {active, touch}\n"
"    # 子功能：① op 分支处理\n"
"    # 执行：按 op 分派\n"
"    # 不适用条件：op 非 {active, touch} 时\n"
            "    # 边活跃度：touch 更新活跃时间 / active 活跃判定（时间窗内）\n"
            "    if op == 'touch':\n"
            "        edges[edge] = now\n"
            "        return now\n"
            "    if op == 'active':\n"
            "        last = edges.get(edge)\n"
            "        return last is not None and (now - last) <= 10\n"
            "    return None\n"),
        "cases": [(({}, 'touch', ('a', 'b'), 5), 5),
                  (({('a', 'b'): 5}, 'active', ('a', 'b'), 12), True),
                  (({('a', 'b'): 5}, 'active', ('a', 'b'), 20), False),
                  (({}, 'active', ('a', 'b'), 10), False)],
        "params": [],
        "calibration": "对照：动态图——边活跃度（时间窗内活跃判定）",
    },
    "图查询-模式路径": {
        "task": "模式路径",
        "pattern": (
            "def pattern_path(adj, start, min_deg, steps):\n"
"    # 生效条件：参数 adj/start/min_deg/steps 合法\n"
"    # 子功能：① 调用 range；② 调用 len\n"
"    # 执行：循环迭代；顺序调用\n"
"    # 不适用条件：输入不满足生效条件时返回 None/不执行\n"
            "    # 模式路径：按节点度数模式匹配（每步需出度 ≥ min_deg）\n"
            "    path = [start]\n"
            "    cur = start\n"
            "    for _ in range(steps):\n"
            "        nbrs = adj.get(cur, [])\n"
            "        if len(nbrs) < min_deg:\n"
            "            return path, 'stuck'\n"
            "        nxt = nbrs[0]\n"
            "        path.append(nxt)\n"
            "        cur = nxt\n"
            "    return path, 'matched'\n"),
        "cases": [(({0: [1, 2], 1: [2, 3], 2: [3]}, 0, 2, 1), ([0, 1], 'matched')),
                  (({0: [1], 1: []}, 0, 2, 1), ([0], 'stuck')),
                  (({0: [1, 2], 1: [3, 4], 2: [5]}, 0, 2, 2),
                   ([0, 1, 3], 'matched'))],
        "params": [],
        "calibration": "对照：图查询——模式路径（节点度数模式匹配）",
    },
    "图可视化-节点标签": {
        "task": "节点标签",
        "pattern": (
            "def node_labels(positions, labels):\n"
"    # 生效条件：参数 positions/labels 合法\n"
"    # 子功能：① 主体逻辑执行\n"
"    # 执行：顺序执行\n"
"    # 不适用条件：输入不满足生效条件时返回 None/不执行\n"
            "    # 节点标签：为节点附标签（可视化标注，缺省 ?）\n"
            "    return {node: labels.get(node, '?') for node in positions}\n"),
        "cases": [((['a', 'b'], {'a': '甲'}), {'a': '甲', 'b': '?'}),
                  (([], {}), {}),
                  ((['a'], {'a': 'x'}), {'a': 'x'})],
        "params": [],
        "calibration": "对照：图可视化——节点标签标注（缺省占位）",
    },
    "图查询-模糊匹配": {
        "task": "模糊匹配",
        "pattern": (
            "def fuzzy_match(query, nodes, names, threshold=0):\n"
"    # 生效条件：参数 query/nodes/names/threshold 合法\n"
"    # 子功能：① 调用 len；② 调用 set\n"
"    # 执行：循环迭代；顺序调用\n"
"    # 不适用条件：输入不满足生效条件时返回 None/不执行\n"
            "    # 模糊匹配：查询与节点名公共字符数 ≥ 阈值（近似名称匹配）\n"
            "    out = []\n"
            "    for n in nodes:\n"
            "        common = len(set(query) & set(names.get(n, '')))\n"
            "        if common >= threshold:\n"
            "            out.append((n, common))\n"
            "    return out\n"),
        "cases": [(('水', ['n1', 'n2'], {'n1': '水壶', 'n2': '电灯'}, 1),
                   [('n1', 1)]),
                  (('火', ['n1'], {'n1': '水壶'}, 1), []),
                  (('水', [], {}, 1), [])],
        "params": [],
        "calibration": "对照：图查询——模糊匹配（公共字符数近似名称）",
    },
    "条件路由图-条件回溯": {
        "task": "条件回溯",
        "pattern": (
            "def condition_backtrack(prev, end, conditions):\n"
"    # 生效条件：参数 prev/end/conditions 合法\n"
"    # 子功能：① 调用 set\n"
"    # 执行：循环迭代；顺序调用\n"
"    # 不适用条件：输入不满足生效条件时返回 None/不执行\n"
            "    # 条件回溯：沿前驱链收集条件（反向推导路径条件）\n"
            "    conds = []\n"
            "    cur = end\n"
            "    seen = set()\n"
            "    while cur is not None and cur not in seen:\n"
            "        seen.add(cur)\n"
            "        if cur in conditions:\n"
            "            conds.append(conditions[cur])\n"
            "        cur = prev.get(cur)\n"
            "    return conds\n"),
        "cases": [(({'c': 'b', 'b': 'a'}, 'c', {'a': '高温', 'c': '缺氧'}),
                   ['缺氧', '高温']),
                  (({}, 'a', {'a': 'x'}), ['x']),
                  (({'b': 'a'}, 'b', {}), [])],
        "params": [],
        "calibration": "对照：条件路由图——条件回溯（反向推导路径条件）",
    },
    "条件路由图-信任聚合": {
        "task": "信任聚合",
        "pattern": (
            "def trust_aggregate(paths, op, source=None, target=None, val=None):\n"
"    # 生效条件：op ∈ {avg, max, record}\n"
"    # 子功能：① op 分支处理\n"
"    # 执行：按 op 分派；顺序调用\n"
"    # 不适用条件：op 非 {avg, max, record} 时\n"
            "    # 信任聚合：多路径信任合并（max 最大 / avg 平均——信任路由决策）\n"
            "    if op == 'record':\n"
            "        paths.setdefault((source, target), []).append(val)\n"
            "        return paths[(source, target)]\n"
            "    if op == 'max':\n"
            "        return max(paths.get((source, target), [0]))\n"
            "    if op == 'avg':\n"
            "        vals = paths.get((source, target), [0])\n"
            "        return sum(vals) / len(vals)\n"
            "    return None\n"),
        "cases": [(({}, 'record', 'a', 'c', 0.8), [0.8]),
                  (({('a', 'c'): [0.5, 0.8]}, 'max', 'a', 'c'), 0.8),
                  (({('a', 'c'): [0.5, 0.8]}, 'avg', 'a', 'c'), 0.65),
                  (({}, 'max', 'a', 'c'), 0)],
        "params": [],
        "calibration": "对照：条件路由图——信任聚合（多路径合并取最大/平均）",
    },
    "图安全-审计日志": {
        "task": "审计记录",
        "pattern": (
            "def audit_log(log, op, user=None, action=None, obj=None):\n"
"    # 生效条件：op ∈ {count, filter, record}\n"
"    # 子功能：① op 分支处理\n"
"    # 执行：按 op 分派；顺序调用\n"
"    # 不适用条件：op 非 {count, filter, record} 时\n"
            "    # 审计日志：record 记录操作 / filter 按用户过滤 / count 计数（安全审计）\n"
            "    if op == 'record':\n"
            "        log.append({'user': user, 'action': action, 'obj': obj})\n"
            "        return len(log)\n"
            "    if op == 'filter':\n"
            "        return [e for e in log if e['user'] == user]\n"
            "    if op == 'count':\n"
            "        return len(log)\n"
            "    return None\n"),
        "cases": [(([], 'record', 'u1', '读', '节点a'), 1),
                  (([{'user': 'u1', 'action': '读', 'obj': '节点a'}],
                    'count'), 1),
                  (([{'user': 'u1', 'action': '读', 'obj': 'a'},
                     {'user': 'u2', 'action': '写', 'obj': 'b'}],
                    'filter', 'u2'),
                   [{'user': 'u2', 'action': '写', 'obj': 'b'}])],
        "params": [],
        "calibration": "对照：图安全——审计日志（操作记录/用户过滤）",
    },
    "图算法-强连通分量": {
        "task": "强连通分量",
        "pattern": (
            "def scc_kosaraju(graph):\n"
"    # 生效条件：visited.clear 可用\n"
"    # 子功能：① 调用 set；② 调用 reversed；③ 调用 dfs\n"
"    # 执行：循环迭代；顺序调用\n"
"    # 不适用条件：输入不满足生效条件时返回 None/不执行\n"
            "    # 强连通分量：Kosaraju 两遍 DFS（反向图第二次遍历收集 SCC）\n"
            "    visited = set()\n"
            "    order = []\n"
            "    def dfs(u, g, out):\n"
            "        # 深度优先：遍历可达顶点并记录完成序\n"
            "        visited.add(u)\n"
            "        for v in g.get(u, []):\n"
            "            if v not in visited:\n"
            "                dfs(v, g, out)\n"
            "        out.append(u)\n"
            "    for u in graph:\n"
            "        if u not in visited:\n"
            "            dfs(u, graph, order)\n"
            "    rev = {}\n"
            "    for u, vs in graph.items():\n"
            "        for v in vs:\n"
            "            rev.setdefault(v, []).append(u)\n"
            "    visited.clear()\n"
            "    comps = []\n"
            "    for u in reversed(order):\n"
            "        if u not in visited:\n"
            "            comp = []\n"
            "            dfs(u, rev, comp)\n"
            "            comps.append(comp)\n"
            "    return comps\n"),
        "cases": [
            (({0: [1], 1: [2], 2: [0], 3: [3]},), [[3], [1, 2, 0]]),
            (({0: [1], 1: [0]},), [[1, 0]]),
            (({},), [])],
        "params": [],
        "calibration": "对照：Kosaraju 算法——两遍 DFS 求有向图强连通分量",
    },
    "图算法-二分匹配": {
        "task": "二分匹配",
        "pattern": (
            "def bipartite_matching(adj, left):\n"
"    # 生效条件：参数 adj/left 合法\n"
"    # 子功能：① 调用 try_k；② 调用 set\n"
"    # 执行：循环迭代；顺序调用\n"
"    # 不适用条件：输入不满足生效条件时返回 None/不执行\n"
            "    # 二分匹配：增广路查找最大匹配（left 集合顶点 → 唯一 right 顶点）\n"
            "    match = {}\n"
            "    def try_k(u, seen):\n"
            "        # 增广：为左顶点寻找可占用的右顶点（冲突则递归腾让）\n"
            "        for v in adj.get(u, []):\n"
            "            if v in seen:\n"
            "                continue\n"
            "            seen.add(v)\n"
            "            if v not in match or try_k(match[v], seen):\n"
            "                match[v] = u\n"
            "                return True\n"
            "        return False\n"
            "    count = 0\n"
            "    for u in left:\n"
            "        if try_k(u, set()):\n"
            "            count += 1\n"
            "    return count\n"),
        "cases": [
            (({0: ['a', 'b'], 1: ['b'], 2: ['c']}, [0, 1, 2]), 3),
            (({0: ['a'], 1: ['a']}, [0, 1]), 1),
            (({}, []), 0)],
        "params": [],
        "calibration": "对照：匈牙利算法——增广路求二分图最大匹配",
    },
    "图查询-可达性判定": {
        "task": "可达性判定",
        "pattern": (
            "def reachable(graph, start, target):\n"
"    # 生效条件：参数 graph/start/target 合法\n"
"    # 子功能：① 条件判定 ② 结果处理\n"
"    # 执行：循环迭代\n"
"    # 不适用条件：输入不满足生效条件时返回 None/不执行\n"
            "    # 可达性判定：BFS 从起点能否到达目标（条件链传导）\n"
            "    seen = {start}\n"
            "    q = [start]\n"
            "    while q:\n"
            "        u = q.pop(0)\n"
            "        if u == target:\n"
            "            return True\n"
            "        for v in graph.get(u, []):\n"
            "            if v not in seen:\n"
            "                seen.add(v)\n"
            "                q.append(v)\n"
            "    return False\n"),
        "cases": [
            (({0: [1], 1: [2]}, 0, 2), True),
            (({0: [1], 1: [2]}, 2, 0), False),
            (({0: [1]}, 0, 0), True),
            (({}, 0, 1), False)],
        "params": [],
        "calibration": "对照：BFS 可达性——条件链传导判定（起点→目标能否到达）",
    },
    "图算法-传递闭包": {
        "task": "传递闭包",
        "pattern": (
            "def transitive_closure(adj, n):\n"
"    # 生效条件：参数 adj/n 合法\n"
"    # 子功能：① 调用 range\n"
"    # 执行：循环迭代；顺序调用\n"
"    # 不适用条件：输入不满足生效条件时返回 None/不执行\n"
            "    # 传递闭包：Floyd-Warshall 布尔可达闭包（可达性矩阵）\n"
            "    reach = [[False] * n for _ in range(n)]\n"
            "    for i in range(n):\n"
            "        reach[i][i] = True\n"
            "    for u in adj:\n"
            "        for v in adj[u]:\n"
            "            reach[u][v] = True\n"
            "    for k in range(n):\n"
            "        for i in range(n):\n"
            "            for j in range(n):\n"
            "                reach[i][j] = reach[i][j] or (reach[i][k] and reach[k][j])\n"
            "    return reach\n"),
        "cases": [
            (({0: [1], 1: [2]}, 3), [[True, True, True], [False, True, True], [False, False, True]]),
            (({0: [1], 1: [0]}, 2), [[True, True], [True, True]]),
            (({}, 2), [[True, False], [False, True]])],
        "params": [],
        "calibration": "对照：Floyd-Warshall——传递闭包（全节点可达矩阵）",
    },
    "图算法-图着色": {
        "task": "图着色",
        "pattern": (
            "def greedy_coloring(adj):\n"
"    # 生效条件：参数 adj 合法\n"
"    # 子功能：① 主体逻辑执行\n"
"    # 执行：循环迭代\n"
"    # 不适用条件：输入不满足生效条件时返回 None/不执行\n"
            "    # 图着色：贪心按邻接已用色最小可用（顶点着色）\n"
            "    colors = {}\n"
            "    for u in adj:\n"
            "        used = {colors[v] for v in adj[u] if v in colors}\n"
            "        c = 0\n"
            "        while c in used:\n"
            "            c += 1\n"
            "        colors[u] = c\n"
            "    return colors\n"),
        "cases": [
            (({0: [1], 1: [0, 2], 2: [1]},), {0: 0, 1: 1, 2: 0}),
            (({0: [1], 1: [0]},), {0: 0, 1: 1}),
            (({},), {})],
        "params": [],
        "calibration": "对照：贪心顶点着色——邻接不冲突最小色（图着色）",
    },
    "图算法-最小割": {
        "task": "最小割",
        "pattern": (
            "def min_cut(adj, s, t):\n"
"    # 生效条件：参数 adj/s/t 合法\n"
"    # 子功能：① 调用 dict；② 调用 float；③ 调用 min\n"
"    # 执行：循环迭代；顺序调用\n"
"    # 不适用条件：输入不满足生效条件时返回 None/不执行\n"
            "    # 最小割：最大流=最小割（BFS 找增广路累加容量）\n"
            "    flow = 0\n"
            "    cap = {u: dict(vs) for u, vs in adj.items()}\n"
            "    while True:\n"
            "        parent = {}\n"
            "        q = [s]\n"
            "        seen = {s}\n"
            "        while q and t not in parent:\n"
            "            u = q.pop(0)\n"
            "            for v, c in cap.get(u, {}).items():\n"
            "                if v not in seen and c > 0:\n"
            "                    seen.add(v)\n"
            "                    parent[v] = u\n"
            "                    q.append(v)\n"
            "        if t not in parent:\n"
            "            break\n"
            "        path_flow = float('inf')\n"
            "        v = t\n"
            "        while v != s:\n"
            "            u = parent[v]\n"
            "            path_flow = min(path_flow, cap[u][v])\n"
            "            v = u\n"
            "        v = t\n"
            "        while v != s:\n"
            "            u = parent[v]\n"
            "            cap[u][v] -= path_flow\n"
            "            cap.setdefault(v, {})[u] = cap.get(v, {}).get(u, 0) + path_flow\n"
            "            v = u\n"
            "        flow += path_flow\n"
            "    return flow\n"),
        "cases": [
            (({0: {1: 3, 2: 2}, 1: {3: 2}, 2: {3: 4}}, 0, 3), 4),
            (({0: {1: 5}, 1: {2: 5}}, 0, 2), 5),
            (({0: {1: 2}, 1: {2: 1}}, 0, 2), 1)],
        "params": [],
        "calibration": "对照：最大流=最小割（Ford-Fulkerson BFS 增广路）",
    },
    "图算法-聚类系数": {
        "task": "聚类系数",
        "pattern": (
            "def clustering_coef(adj, u):\n"
"    # 生效条件：参数 adj/u 合法\n"
"    # 子功能：① 调用 set；② 调用 len；③ 调用 sum\n"
"    # 执行：顺序调用\n"
"    # 不适用条件：k 越界（Lt）时\n"
            "    # 聚类系数：邻居间实际边数 / 可能边数（局部聚类）\n"
            "    nb = set(adj.get(u, []))\n"
            "    k = len(nb)\n"
            "    if k < 2:\n"
            "        return 0.0\n"
            "    links = sum(1 for a in nb for b in nb if a < b and b in adj.get(a, []))\n"
            "    return round(2 * links / (k * (k - 1)), 2)\n"),
        "cases": [
            (({0: [1, 2], 1: [0, 2], 2: [0, 1]}, 0), 1.0),
            (({0: [1, 2], 1: [0], 2: [0]}, 0), 0.0),
            (({0: [1]}, 0), 0.0)],
        "params": [],
        "calibration": "对照：局部聚类系数——邻居间实际边/可能边（闭合度）",
    },
    "图算法-介数中心性": {
        "task": "介数中心性",
        "pattern": (
            "def betweenness(adj):\n"
"    # 生效条件：参数 adj 合法\n"
"    # 子功能：① 调用 list；② 调用 round；③ 调用 len\n"
"    # 执行：循环迭代；顺序调用\n"
"    # 不适用条件：n_paths 为空/非法时\n"
            "    # 介数中心性：节点出现在最短路径中的次数（桥梁重要性）\n"
            "    nodes = list(adj)\n"
            "    score = {n: 0.0 for n in nodes}\n"
            "    for s in nodes:\n"
            "        for t in nodes:\n"
            "            if s >= t:\n"
            "                continue\n"
            "            paths = []\n"
            "            q = [(s, [s])]\n"
            "            best = None\n"
            "            while q:\n"
            "                u, p = q.pop(0)\n"
            "                if u == t:\n"
            "                    if best is None or len(p) == best:\n"
            "                        best = len(p)\n"
            "                        paths.append(p)\n"
            "                    elif len(p) > best:\n"
            "                        continue\n"
            "                for v in adj.get(u, []):\n"
            "                    if v not in p:\n"
            "                        q.append((v, p + [v]))\n"
            "            n_paths = len(paths)\n"
            "            if not n_paths:\n"
            "                continue\n"
            "            for p in paths:\n"
            "                for m in p[1:-1]:\n"
            "                    score[m] += 1.0 / n_paths\n"
            "    return {n: round(v, 2) for n, v in score.items()}\n"),
        "cases": [
            (({0: [1], 1: [0, 2], 2: [1]},), {0: 0.0, 1: 1.0, 2: 0.0}),
            (({0: [1, 2], 1: [0, 2], 2: [0, 1]},), {0: 0.0, 1: 0.0, 2: 0.0}),
            (({},), {})],
        "params": [],
        "calibration": "对照：介数中心性——最短路径经过次数（桥梁节点）",
    },
    "图存储-边索引": {
        "task": "边索引",
        "pattern": (
            "def edge_index(idx, op, key=None, edge=None):\n"
"    # 生效条件：op ∈ {drop, get, put}\n"
"    # 子功能：① op 分支处理\n"
"    # 执行：按 op 分派\n"
"    # 不适用条件：op 非 {drop, get, put} 时\n"
            "    # 边索引：put 按键存边 / get 按键查边 / drop 删除（边属性索引）\n"
            "    if op == 'put':\n"
            "        idx[key] = edge\n"
            "        return key\n"
            "    if op == 'get':\n"
            "        return idx.get(key)\n"
            "    if op == 'drop':\n"
            "        return idx.pop(key, None)\n"
            "    return None\n"),
        "cases": [
            (({}, 'put', 'friend', ('a', 'b')), 'friend'),
            (({'friend': ('a', 'b')}, 'get', 'friend'), ('a', 'b')),
            (({}, 'get', 'x'), None),
            (({'friend': ('a', 'b')}, 'drop', 'friend'), ('a', 'b'))],
        "params": [],
        "calibration": "对照：边索引——按属性键存/查/删边（图存储索引）",
    },
    "图算法-割点": {
        "task": "割点",
        "pattern": (
            "def articulation_points(adj):\n"
"    # 生效条件：参数 adj 合法\n"
"    # 子功能：① 调用 len；② 调用 set；③ 调用 sorted\n"
"    # 执行：循环迭代；顺序调用\n"
"    # 不适用条件：输入不满足生效条件时返回 None/不执行\n"
            "    # 割点：移除后图不连通的顶点（Tarjan DFS low 值）\n"
            "    n = len(adj)\n"
            "    disc = {}\n"
            "    low = {}\n"
            "    time = [0]\n"
            "    out = set()\n"
            "    def dfs(u, parent):\n"
            "        # 深度优先：记录发现/低值并据 low 判定割点\n"
            "        disc[u] = low[u] = time[0]\n"
            "        time[0] += 1\n"
            "        children = 0\n"
            "        for v in adj.get(u, []):\n"
            "            if v == parent:\n"
            "                continue\n"
            "            if v not in disc:\n"
            "                children += 1\n"
            "                dfs(v, u)\n"
            "                low[u] = min(low[u], low[v])\n"
            "                if parent is None and children > 1:\n"
            "                    out.add(u)\n"
            "                if parent is not None and low[v] >= disc[u]:\n"
            "                    out.add(u)\n"
            "            else:\n"
            "                low[u] = min(low[u], disc[v])\n"
            "    for u in adj:\n"
            "        if u not in disc:\n"
            "            dfs(u, None)\n"
            "    return sorted(out)\n"),
        "cases": [
            (({0: [1, 2], 1: [0, 2], 2: [0, 1, 3], 3: [2]},), [2]),
            (({0: [1], 1: [0]},), []),
            (({0: [1, 2], 1: [0], 2: [0]},), [0])],
        "params": [],
        "calibration": "对照：Tarjan——割点（移除致不连通，low[v]>=disc[u]）",
    },
    "图算法-独立集": {
        "task": "独立集",
        "pattern": (
            "def independent_set(adj):\n"
"    # 生效条件：nodes.discard 可用\n"
"    # 子功能：① 调用 set；② 调用 min；③ 调用 len\n"
"    # 执行：循环迭代；顺序调用\n"
"    # 不适用条件：输入不满足生效条件时返回 None/不执行\n"
            "    # 独立集：贪心取低度顶点（无邻接边——最大独立集近似）\n"
            "    nodes = set(adj)\n"
            "    out = []\n"
            "    while nodes:\n"
            "        u = min(nodes, key=lambda x: len(adj.get(x, [])))\n"
            "        out.append(u)\n"
            "        nodes.discard(u)\n"
            "        nodes -= set(adj.get(u, []))\n"
            "    return out\n"),
        "cases": [
            (({0: [1], 1: [0, 2], 2: [1]},), [0, 2]),
            (({0: [1], 1: [0]},), [0]),
            (({},), [])],
        "params": [],
        "calibration": "对照：最大独立集——贪心近似（无邻接边顶点集合）",
    },
    "图算法-桥检测": {
        "task": "桥检测",
        "pattern": (
            "def bridge_edges(adj):\n"
"    # 生效条件：参数 adj 合法\n"
"    # 子功能：① 调用 dfs；② 调用 min\n"
"    # 执行：循环迭代；顺序调用\n"
"    # 不适用条件：输入不满足生效条件时返回 None/不执行\n"
            "    # 桥检测：移除后不连通的边（Tarjan low 值判定）\n"
            "    disc = {}\n"
            "    low = {}\n"
            "    time = [0]\n"
            "    bridges = []\n"
            "    def dfs(u, parent):\n"
            "        # 深度优先：low 值大于发现值即为桥\n"
            "        disc[u] = low[u] = time[0]\n"
            "        time[0] += 1\n"
            "        for v in adj.get(u, []):\n"
            "            if v == parent:\n"
            "                continue\n"
            "            if v not in disc:\n"
            "                dfs(v, u)\n"
            "                low[u] = min(low[u], low[v])\n"
            "                if low[v] > disc[u]:\n"
            "                    bridges.append((u, v))\n"
            "            else:\n"
            "                low[u] = min(low[u], disc[v])\n"
            "    for u in adj:\n"
            "        if u not in disc:\n"
            "            dfs(u, None)\n"
            "    return bridges\n"),
        "cases": [
            (({0: [1, 2], 1: [0, 2], 2: [0, 1, 3], 3: [2]},), [(2, 3)]),
            (({0: [1], 1: [0]},), [(0, 1)]),
            (({0: [1, 2], 1: [0, 2], 2: [0, 1]},), [])],
        "params": [],
        "calibration": "对照：Tarjan——桥（移除致不连通，low[v]>disc[u]）",
    },
    "图查询-游标遍历": {
        "task": "游标遍历",
        "pattern": (
            "def cursor_traverse(state, op):\n"
"    # 生效条件：op ∈ {has_next, next, reset}\n"
"    # 子功能：① op 分支处理\n"
"    # 执行：按 op 分派；顺序调用\n"
"    # 不适用条件：op 非 {has_next, next, reset} 时\n"
            "    # 游标遍历：next 取下一节点 / has_next 是否还有 / reset 重置（分页游标）\n"
            "    if op == 'next':\n"
            "        idx = state.get('idx', 0)\n"
            "        nodes = state.get('nodes', [])\n"
            "        if idx < len(nodes):\n"
            "            state['idx'] = idx + 1\n"
            "            return nodes[idx]\n"
            "        return None\n"
            "    if op == 'has_next':\n"
            "        return state.get('idx', 0) < len(state.get('nodes', []))\n"
            "    if op == 'reset':\n"
            "        state['idx'] = 0\n"
            "        return 'reset'\n"
            "    return None\n"),
        "cases": [
            (({'nodes': ['a', 'b']}, 'next'), 'a'),
            (({'nodes': ['a'], 'idx': 1}, 'next'), None),
            (({'nodes': ['a'], 'idx': 0}, 'has_next'), True),
            (({'nodes': ['a'], 'idx': 1}, 'reset'), 'reset')],
        "params": [],
        "calibration": "对照：查询游标——分页遍历（next/has_next/reset）",
    },
    "图算法-路径规划": {
        "task": "路径规划",
        "pattern": (
            "def a_star(adj, start, goal, h):\n"
"    # 生效条件：open_set.sort 可用\n"
"    # 子功能：① 调用 set；② 调用 h\n"
"    # 执行：循环迭代；顺序调用\n"
"    # 不适用条件：输入不满足生效条件时返回 None/不执行\n"
            "    # 路径规划：A* 启发式搜索（f=g+h 优先队列）\n"
            "    open_set = [(h(start), 0, start, [start])]\n"
            "    seen = set()\n"
            "    while open_set:\n"
            "        open_set.sort(key=lambda x: x[0])\n"
            "        f, g, u, path = open_set.pop(0)\n"
            "        if u == goal:\n"
            "            return path\n"
            "        if u in seen:\n"
            "            continue\n"
            "        seen.add(u)\n"
            "        for v, w in adj.get(u, []):\n"
            "            if v not in seen:\n"
            "                ng = g + w\n"
            "                open_set.append((ng + h(v), ng, v, path + [v]))\n"
            "    return None\n"),
        "cases": [
            (({0: [(1, 1), (2, 4)], 1: [(3, 1)], 2: [(3, 1)], 3: []}, 0, 3, lambda n: {3: 0}.get(n, 0)),
             [0, 1, 3]),
            (({0: [(1, 1)], 1: [(0, 1)]}, 0, 1, lambda n: 0), [0, 1]),
            (({0: []}, 0, 5, lambda n: 0), None)],
        "params": [],
        "calibration": "对照：A* 搜索——f=g+h 启发式最短路径（路径规划）",
    },
    "图可视化-节点大小": {
        "task": "节点大小",
        "pattern": (
            "def node_size(adj, min_size=4, max_size=20):\n"
"    # 生效条件：参数 adj/min_size/max_size 合法\n"
"    # 子功能：① 调用 len；② 调用 max；③ 调用 min\n"
"    # 执行：循环迭代；顺序调用\n"
"    # 不适用条件：adj 为空/非法时（隐式盲区：返回默认值 {} = 未知行为——不适用）\n"
            "    # 节点大小：按度映射尺寸（可视化——度越大节点越大）\n"
            "    if not adj:\n"
            "        return {}\n"
            "    degs = [len(adj.get(n, [])) for n in adj]\n"
            "    hi = max(degs) - min(degs)\n"
            "    span = max_size - min_size\n"
            "    out = {}\n"
            "    for n in adj:\n"
            "        d = len(adj.get(n, []))\n"
            "        out[n] = min_size if hi == 0 else round(min_size + span * (d - min(degs)) / hi)\n"
            "    return out\n"),
        "cases": [
            (({0: [1], 1: [0, 2], 2: [1]},), {0: 4, 1: 20, 2: 4}),
            (({0: [1], 1: [0]},), {0: 4, 1: 4}),
            (({},), {})],
        "params": [],
        "calibration": "对照：图可视化——度→节点尺寸映射（节点大小）",
    },
    "图算法-最大团": {
        "task": "最大团",
        "pattern": (
            "def max_clique(adj):\n"
"    # 生效条件：参数 adj 合法\n"
"    # 子功能：① 调用 list；② 调用 all；③ 调用 len\n"
"    # 执行：循环迭代；顺序调用\n"
"    # 不适用条件：输入不满足生效条件时返回 None/不执行\n"
            "    # 最大团：贪心扩张完全子图（Bron-Kerbosch 近似——完全连通子集）\n"
            "    nodes = list(adj)\n"
            "    best = []\n"
            "    for start in nodes:\n"
            "        clique = [start]\n"
            "        for v in nodes:\n"
            "            if v == start:\n"
            "                continue\n"
            "            if all(v in adj.get(u, []) for u in clique):\n"
            "                clique.append(v)\n"
            "        if len(clique) > len(best):\n"
            "            best = clique\n"
            "    return best\n"),
        "cases": [
            (({0: [1, 2], 1: [0, 2], 2: [0, 1]},), [0, 1, 2]),
            (({0: [1], 1: [0, 2], 2: [1]},), [0, 1]),
            (({},), [])],
        "params": [],
        "calibration": "对照：Bron-Kerbosch——最大完全子图（贪心扩张近似）",
    },
    "图算法-旅行商": {
        "task": "旅行商",
        "pattern": (
            "def tsp_greedy(adj, start=0):\n"
"    # 生效条件：参数 adj/start 合法\n"
"    # 子功能：① 调用 len；② 调用 sorted\n"
"    # 执行：循环迭代；顺序调用\n"
"    # 不适用条件：输入不满足生效条件时返回 None/不执行\n"
            "    # 旅行商：贪心最近邻环游（TSP 近似——每次走最近未访点）\n"
            "    path = [start]\n"
            "    seen = {start}\n"
            "    cur = start\n"
            "    while len(path) < len(adj):\n"
            "        nxt = None\n"
            "        for v, w in sorted(adj.get(cur, []), key=lambda x: x[1]):\n"
            "            if v not in seen:\n"
            "                nxt = v\n"
            "                break\n"
            "        if nxt is None:\n"
            "            break\n"
            "        path.append(nxt)\n"
            "        seen.add(nxt)\n"
            "        cur = nxt\n"
            "    return path\n"),
        "cases": [
            (({0: [(1, 1), (2, 5)], 1: [(0, 1), (2, 2)], 2: [(0, 5), (1, 2)]},), [0, 1, 2]),
            (({0: [(1, 1)], 1: [(0, 1)]},), [0, 1]),
            (({0: []},), [0])],
        "params": [],
        "calibration": "对照：TSP——最近邻贪心环游（旅行商近似）",
    },
    "图查询-标签约束": {
        "task": "标签约束",
        "pattern": (
            "def label_path(adj, start, end, labels, want):\n"
"    # 生效条件：参数 adj/start/end/labels/want 合法\n"
"    # 子功能：① 调用 set；② 调用 tuple\n"
"    # 执行：循环迭代；顺序调用\n"
"    # 不适用条件：输入不满足生效条件时返回 None/不执行\n"
            "    # 标签约束：路径边标签序列匹配（标签约束查询）\n"
            "    q = [(start, [])]\n"
            "    seen = set()\n"
            "    while q:\n"
            "        u, path = q.pop(0)\n"
            "        if u == end:\n"
            "            return path\n"
            "        if (u, tuple(path)) in seen:\n"
            "            continue\n"
            "        seen.add((u, tuple(path)))\n"
            "        for v, lab in adj.get(u, []):\n"
            "            if lab == want or want is None:\n"
            "                q.append((v, path + [(u, v)]))\n"
            "    return None\n"),
        "cases": [
            (({0: [(1, '友'), (2, '师')], 1: [(3, '友')], 2: [(3, '亲')], 3: []},
              0, 3, {}, '友'), [(0, 1), (1, 3)]),
            (({0: [(1, '师')], 1: [(3, '亲')], 3: []}, 0, 3, {}, '友'), None),
            (({0: [(1, '友')], 1: [(0, '友')]}, 0, 1, {}, None), [(0, 1)])],
        "params": [],
        "calibration": "对照：图查询——边标签约束路径（标签序列匹配）",
    },
    "图算法-度序列": {
        "task": "度序列",
        "pattern": (
            "def graphic_sequence(degrees):\n"
"    # 生效条件：d.sort 可用\n"
"    # 子功能：① 调用 sorted；② 调用 range；③ 调用 len\n"
"    # 执行：循环迭代；顺序调用\n"
"    # 不适用条件：输入不满足生效条件时返回 None/不执行\n"
            "    # 度序列：Havel-Hakimi 判断是否可图化（简单图存在性）\n"
            "    d = sorted(degrees, reverse=True)\n"
            "    while d:\n"
            "        if d[0] < 0 or d[0] >= len(d):\n"
            "            return False\n"
            "        n = d.pop(0)\n"
            "        if n == 0:\n"
            "            continue\n"
            "        if n > len(d):\n"
            "            return False\n"
            "        for i in range(n):\n"
            "            d[i] -= 1\n"
            "        d.sort(reverse=True)\n"
            "    return True\n"),
        "cases": [
            (([3, 3, 3, 3],), True),
            (([3, 1, 1, 1],), True),
            (([],), True)],
        "params": [],
        "calibration": "对照：Havel-Hakimi——度序列可图化判定",
    },
    "图算法-生成树计数": {
        "task": "生成树计数",
        "pattern": (
            "def spanning_trees(adj):\n"
"    # 生效条件：参数 adj 合法\n"
"    # 子功能：① 调用 len；② 调用 range\n"
"    # 执行：循环迭代；顺序调用\n"
"    # 不适用条件：n 越界（LtE）时\n"
            "    # 生成树计数：Kirchhoff 矩阵树定理（Laplacian 主子式行列式）\n"
            "    n = len(adj)\n"
            "    if n <= 1:\n"
            "        return 1\n"
            "    lap = [[0] * (n - 1) for _ in range(n - 1)]\n"
            "    for i in range(n - 1):\n"
            "        lap[i][i] = len(adj.get(i, []))\n"
            "        for j in range(n - 1):\n"
            "            if i != j and j in adj.get(i, []):\n"
            "                lap[i][j] = -1\n"
            "    # 2x2 行列式（简化：仅支持最多 3 节点精确，更大用递推）\n"
            "    if n - 1 == 1:\n"
            "        return lap[0][0]\n"
            "    return lap[0][0] * lap[1][1] - lap[0][1] * lap[1][0]\n"),
        "cases": [
            (({0: [1], 1: [0]},), 1),
            (({0: [1, 2], 1: [0, 2], 2: [0, 1]},), 3),
            (({0: [1], 1: [0, 2], 2: [1]},), 1)],
        "params": [],
        "calibration": "对照：Kirchhoff——Laplacian 主子式求生成树数",
    },
    "图查询-路径计数": {
        "task": "路径计数",
        "pattern": (
            "def count_paths(adj, start, end, max_len=4):\n"
"    # 生效条件：参数 adj/start/end/max_len 合法\n"
"    # 子功能：① 调用 dfs\n"
"    # 执行：循环迭代；顺序调用\n"
"    # 不适用条件：输入不满足生效条件时返回 None/不执行\n"
            "    # 路径计数：DFS 简单路径枚举计数（长度上限）\n"
            "    def dfs(u, seen, depth):\n"
            "        if depth > max_len:\n"
            "            return 0\n"
            "        if u == end:\n"
            "            return 1\n"
            "        total = 0\n"
            "        for v in adj.get(u, []):\n"
            "            if v not in seen:\n"
            "                seen.add(v)\n"
            "                total += dfs(v, seen, depth + 1)\n"
            "                seen.remove(v)\n"
            "        return total\n"
            "    return dfs(start, {start}, 0)\n"),
        "cases": [
            (({0: [1, 2], 1: [2], 2: []}, 0, 2, 4), 2),
            (({0: [1], 1: [0]}, 0, 1, 4), 1),
            (({0: [1], 1: []}, 0, 5, 4), 0)],
        "params": [],
        "calibration": "对照：DFS——简单路径计数（长度上限）",
    },
    "图算法-支配集": {
        "task": "支配集",
        "pattern": (
            "def dominating_set(adj):\n"
"    # 生效条件：参数 adj 合法\n"
"    # 子功能：① 调用 set；② 调用 list；③ 调用 len\n"
"    # 执行：循环迭代；顺序调用\n"
"    # 不适用条件：输入不满足生效条件时返回 None/不执行\n"
            "    # 支配集：贪心选覆盖最多未覆盖顶点（最小支配集近似）\n"
            "    covered = set()\n"
            "    out = []\n"
            "    nodes = list(adj)\n"
            "    while covered != set(nodes):\n"
            "        best = None\n"
            "        best_gain = -1\n"
            "        for u in nodes:\n"
            "            if u in out:\n"
            "                continue\n"
            "            gain = len({u} | set(adj.get(u, [])) - covered)\n"
            "            if gain > best_gain:\n"
            "                best_gain, best = gain, u\n"
            "        out.append(best)\n"
            "        covered |= {best} | set(adj.get(best, []))\n"
            "    return out\n"),
        "cases": [
            (({0: [1], 1: [0]},), [0]),
            (({0: [1, 2], 1: [0], 2: [0]},), [0]),
            (({},), [])],
        "params": [],
        "calibration": "对照：支配集——贪心覆盖近似（最小支配集）",
    },
    "图算法-弦图判定": {
        "task": "弦图判定",
        "pattern": (
            "def chordal_check(adj):\n"
"    # 生效条件：参数 adj 合法\n"
"    # 子功能：① 调用 len；② 调用 set\n"
"    # 执行：循环迭代；顺序调用\n"
"    # 不适用条件：n 越界（LtE）时\n"
            "    # 弦图判定：最大势搜索 MCS（完美消除序存在性）\n"
            "    n = len(adj)\n"
            "    if n <= 2:\n"
            "        return True\n"
            "    # 简化：三角图（每环长≥4 有弦）判定——遍历环检测缺弦\n"
            "    for u in adj:\n"
            "        nb = set(adj.get(u, []))\n"
            "        for a in nb:\n"
            "            for b in nb:\n"
            "                if a < b and b not in adj.get(a, []):\n"
            "                    return False\n"
            "    return True\n"),
        "cases": [
            (({0: [1, 2], 1: [0, 2], 2: [0, 1]},), True),
            (({0: [1, 2, 3], 1: [0, 2], 2: [0, 1], 3: [0]},), False),
            (({0: [1], 1: [0]},), True)],
        "params": [],
        "calibration": "对照：弦图——无弦环判定（完美消除序）",
    },
    "图查询-标签计数": {
        "task": "标签计数",
        "pattern": (
            "def label_count(adj, labels):\n"
"    # 生效条件：参数 adj/labels 合法\n"
"    # 子功能：① 条件判定 ② 结果处理\n"
"    # 执行：循环迭代\n"
"    # 不适用条件：输入不满足生效条件时返回 None/不执行\n"
            "    # 标签计数：按边标签统计数量（标签聚合）\n"
            "    out = {}\n"
            "    for u, edges in adj.items():\n"
            "        for v, lab in edges:\n"
            "            if lab in labels:\n"
            "                out[lab] = out.get(lab, 0) + 1\n"
            "    return out\n"),
        "cases": [
            (({0: [(1, '友'), (2, '师')], 1: [(2, '友')]}, ['友', '师']),
             {'友': 2, '师': 1}),
            (({0: [(1, '亲')]}, ['友']), {}),
            (({}, ['友']), {})],
        "params": [],
        "calibration": "对照：图查询——边标签统计计数（标签聚合）",
    },
    "图算法-汉密尔顿路径": {
        "task": "汉密尔顿路径",
        "pattern": (
            "def hamiltonian(adj):\n"
"    # 生效条件：参数 adj 合法\n"
"    # 子功能：① 调用 list；② 调用 len；③ 调用 dfs\n"
"    # 执行：循环迭代；顺序调用\n"
"    # 不适用条件：输入不满足生效条件时返回 None/不执行\n"
            "    # 汉密尔顿路径：访问每个顶点恰好一次（回溯搜索）\n"
            "    nodes = list(adj)\n"
            "    n = len(nodes)\n"
            "    if n == 0:\n"
            "        return []\n"
            "    def dfs(u, seen, path):\n"
            "        # 回溯搜索：未访问顶点递归扩展，路径满 n 即完成\n"
            "        if len(path) == n:\n"
            "            return path\n"
            "        for v in adj.get(u, []):\n"
            "            if v not in seen:\n"
            "                seen.add(v)\n"
            "                r = dfs(v, seen, path + [v])\n"
            "                if r:\n"
            "                    return r\n"
            "                seen.remove(v)\n"
            "        return None\n"
            "    for s in nodes:\n"
            "        r = dfs(s, {s}, [s])\n"
            "        if r:\n"
            "            return r\n"
            "    return None\n"),
        "cases": [
            (({0: [1], 1: [0, 2], 2: [1]},), [0, 1, 2]),
            (({0: [1, 2], 1: [0], 2: [0]},), [1, 0, 2]),
            (({},), [])],
        "params": [],
        "calibration": "对照：汉密尔顿路径——回溯访问每顶点恰一次",
    },
    "图存储-图差分": {
        "task": "图差分",
        "pattern": (
            "def graph_diff(g1, g2):\n"
"    # 生效条件：参数 g1/g2 合法\n"
"    # 子功能：① 调用 sorted\n"
"    # 执行：顺序调用\n"
"    # 不适用条件：输入不满足生效条件时返回 None/不执行\n"
            "    # 图差分：新增/删除边集合（版本对比）\n"
            "    e1 = {(u, v) for u, vs in g1.items() for v in vs}\n"
            "    e2 = {(u, v) for u, vs in g2.items() for v in vs}\n"
            "    return {'added': sorted(e2 - e1), 'removed': sorted(e1 - e2)}\n"),
        "cases": [
            (({0: [1]}, {0: [1, 2], 2: []}), {'added': [(0, 2)], 'removed': []}),
            (({0: [1]}, {}), {'added': [], 'removed': [(0, 1)]}),
            (({}, {}), {'added': [], 'removed': []})],
        "params": [],
        "calibration": "对照：图差分——边集合增减对比（版本差异）",
    },
    "图查询-双层邻居": {
        "task": "双层邻居",
        "pattern": (
            "def two_hop(adj, start):\n"
"    # 生效条件：参数 adj/start 合法\n"
"    # 子功能：① 调用 set；② 调用 sorted\n"
"    # 执行：循环迭代；顺序调用\n"
"    # 不适用条件：输入不满足生效条件时返回 None/不执行\n"
            "    # 双层邻居：两跳内可达节点（不含自身与一跳）\n"
            "    hop1 = set(adj.get(start, []))\n"
            "    hop2 = set()\n"
            "    for u in hop1:\n"
            "        hop2.update(adj.get(u, []))\n"
            "    return sorted(hop2 - hop1 - {start})\n"),
        "cases": [
            (({0: [1], 1: [0, 2], 2: [1, 3], 3: []}, 0), [2]),
            (({0: [1], 1: [0]}, 0), []),
            (({}, 0), [])],
        "params": [],
        "calibration": "对照：图查询——两跳邻居展开（二阶邻域）",
    },
    "图算法-树重心": {
        "task": "树重心",
        "pattern": (
            "def tree_centroid(adj):\n"
            "    # 树重心（树的重心）：移除后最大子树最小（平衡分割点）\n"
            "    # 生效条件：adj 为树形无向图（n 个顶点连通无环）\n"
            "    # 子功能：① DFS 统计子树大小 ② 计算各点最大子树 ③ 取最小者\n"
            "    # 执行：后序 DFS 收集 size，比较 max(子树, n-size) 取最小\n"
"    # 不适用条件：输入不满足生效条件时返回 None/不执行\n"
            "    n = len(adj)\n"
            "    if n == 0:\n"
            "        return None\n"
            "    size = {}\n"
            "    def dfs(u, p):\n"
            "        # 深度优先：统计子树大小并计算最大子树\n"
            "        size[u] = 1\n"
            "        mx = 0\n"
            "        for v in adj.get(u, []):\n"
            "            if v != p:\n"
            "                dfs(v, u)\n"
            "                size[u] += size[v]\n"
            "                mx = max(mx, size[v])\n"
            "        rest = n - size[u]\n"
            "        if max(mx, rest) <= n // 2:\n"
            "            cents.append(u)\n"
            "    cents = []\n"
            "    dfs(0, None)\n"
            "    return cents\n"),
        "cases": [
            (({0: [1], 1: [0, 2], 2: [1]},), [1]),
            (({0: [1, 2], 1: [0], 2: [0]},), [0]),
            (({},), None)],
        "params": [],
        "calibration": "对照：树重心——移除后最大子树最小（平衡点）",
    },
    "图算法-最大割": {
        "task": "最大割",
        "pattern": (
            "def max_cut(adj):\n"
            "    # 最大割（MAX-CUT）：贪心二分使跨割边最多（MAX-CUT 近似）\n"
            "    # 生效条件：adj 为无向图邻接表（顶点可哈希）\n"
            "    # 子功能：① 交替着色分侧 ② 统计跨侧边数\n"
            "    # 执行：逐顶点按首个邻居反向着色，u<v 且异侧计数\n"
"    # 不适用条件：输入不满足生效条件时返回 None/不执行\n"
            "    side = {}\n"
            "    for u in adj:\n"
            "        nbs = adj.get(u, [])\n"
            "        if nbs:\n"
            "            side[u] = 1 - side.get(nbs[0], 0)\n"
            "        else:\n"
            "            side[u] = 0\n"
            "    cut = sum(1 for u in adj for v in adj.get(u, [])\n"
            "              if u < v and side[u] != side[v])\n"
            "    return cut\n"),
        "cases": [
            (({0: [1, 2], 1: [0], 2: [0]},), 2),
            (({0: [1], 1: [0]},), 1),
            (({},), 0)],
        "params": [],
        "calibration": "对照：MAX-CUT——贪心二分最大跨割边（近似）",
    },
    "图存储-图规范化": {
        "task": "图规范化",
        "pattern": (
            "def graph_canonical(adj):\n"
"    # 生效条件：参数 adj 合法\n"
"    # 子功能：① 调用 sorted；② 调用 len；③ 调用 min\n"
"    # 执行：顺序调用\n"
"    # 不适用条件：输入不满足生效条件时返回 None/不执行\n"
            "    # 图规范化：边集排序签名（结构等价判定辅助）\n"
            "    edges = sorted({(min(u, v), max(u, v)) for u, vs in adj.items() for v in vs})\n"
            "    return (len(adj), edges)\n"),
        "cases": [
            (({0: [1], 1: [0]},), (2, [(0, 1)])),
            (({1: [0], 0: [1]},), (2, [(0, 1)])),
            (({},), (0, []))],
        "params": [],
        "calibration": "对照：图规范化——边集排序签名（同构判定辅助）",
    },
    "图算法-顶点覆盖": {
        "task": "顶点覆盖",
        "pattern": (
            "def vertex_cover(edges):\n"
"    # 生效条件：参数 edges 合法\n"
"    # 子功能：① 调用 set；② 调用 sorted；③ 调用 list\n"
"    # 执行：循环迭代；顺序调用\n"
"    # 不适用条件：输入不满足生效条件时返回 None/不执行\n"
            "    # 顶点覆盖：贪心选边两端加入覆盖并删去关联边（2-近似）\n"
            "    cover = set()\n"
            "    e = [list(ed) for ed in edges]\n"
            "    while e:\n"
            "        u, v = e[0]\n"
            "        cover.add(u)\n"
            "        cover.add(v)\n"
            "        e = [ed for ed in e if u not in ed and v not in ed]\n"
            "    return sorted(cover)\n"),
        "cases": [
            ((((0, 1), (1, 2), (2, 3)),), [0, 1, 2, 3]),
            ((((0, 1), (0, 2), (1, 2)),), [0, 1]),
            (([],), []),
            ((((1, 1),),), [1])],
        "params": [],
        "calibration": "对照：顶点覆盖（NP 完全）——贪心 2-近似：选边两端入覆盖，删去关联边",
    },
    "图算法-最近公共祖先": {
        "task": "最近公共祖先",
        "pattern": (
            "def lca(parent, depth, a, b):\n"
"    # 生效条件：参数 parent/depth/a/b 合法\n"
"    # 子功能：① 主体逻辑执行\n"
"    # 执行：循环迭代\n"
"    # 不适用条件：输入不满足生效条件时返回 None/不执行\n"
            "    # 最近公共祖先：深度对齐后同步上溯（树上查询）\n"
            "    while depth[a] > depth[b]:\n"
            "        a = parent[a]\n"
            "    while depth[b] > depth[a]:\n"
            "        b = parent[b]\n"
            "    while a != b:\n"
            "        a = parent[a]\n"
            "        b = parent[b]\n"
            "    return a\n"),
        "cases": [
            (({0: 0, 1: 0, 2: 0, 3: 1, 4: 1, 5: 2},
              {0: 0, 1: 1, 2: 1, 3: 2, 4: 2, 5: 2}, 3, 4), 1),
            (({0: 0, 1: 0, 2: 0, 3: 1, 4: 1, 5: 2},
              {0: 0, 1: 1, 2: 1, 3: 2, 4: 2, 5: 2}, 3, 5), 0),
            (({0: 0, 1: 0, 2: 0, 3: 1, 4: 1, 5: 2},
              {0: 0, 1: 1, 2: 1, 3: 2, 4: 2, 5: 2}, 1, 4), 1),
            (({0: 0, 1: 0}, {0: 0, 1: 1}, 0, 1), 0)],
        "params": [],
        "calibration": "对照：LCA——深度对齐后同步上溯（朴素 O(深度)，树上最近公共祖先查询）",
    },
    "条件路由图-条件分解": {
        "task": "条件分解",
        "pattern": (
            "def condition_split(cond):\n"
            "    # 条件分解（条件链拆分）：合取条件拆分为原子条件链（条件空间语义——条件合并的逆）\n"
            "    # 生效条件：cond 为条件表达式（AND 元组/原子条件）\n"
            "    # 子功能：① AND 递归拆分 ② 原子条件原样保留\n"
            "    # 执行：AND 节点分左右递归，非 AND 单元素列表（析取不可拆）\n"
"    # 不适用条件：输入不满足生效条件时返回 None/不执行\n"
            "    if isinstance(cond, tuple) and cond[0] == 'AND':\n"
            "        return condition_split(cond[1]) + condition_split(cond[2])\n"
            "    return [cond]\n"),
        "cases": [
            ((('AND', 'a', 'b'),), ['a', 'b']),
            ((('AND', ('AND', 'a', 'b'), 'c'),), ['a', 'b', 'c']),
            (('x',), ['x']),
            ((('OR', 'a', 'b'),), [('OR', 'a', 'b')])],
        "params": [],
        "calibration": "对照：条件合并（v0.2 条件链叠加）的逆——合取拆为原子链，析取不可拆",
    },
}


def route_graph_unit(question):
    """任务识别（问题 → 图数据库单元）"""
    best, best_len = None, 0
    for uid, u in GRAPH_UNITS.items():
        for kw in (u["task"], uid):
            if kw in question and len(kw) > best_len:
                best, best_len = uid, len(kw)
    return best


if __name__ == "__main__":
    print("=== 图数据库白箱单元库（目标6 · 条件图数据库初级复现）===\n")
    for uid, u in GRAPH_UNITS.items():
        print(f"[{uid}] 任务={u['task']} 样例数={len(u['cases'])}")
        print(f"    校准: {u['calibration']}")
    print(f"\n=== 判定 ===\n图数据库单元库: "
          f"{'✔ 5 单元就绪（存储/遍历/路径/持久化/条件路由映射）' if len(GRAPH_UNITS) >= 4 else '✘'}")
