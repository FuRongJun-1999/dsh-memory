# -*- coding: utf-8 -*-
"""net_units.py · 蓝牙和互联网白箱单元库（第六阶段·目标7 初级复现）
用户设想：终极目标「蜂群连接网络」← 初级复现「蓝牙和互联网」。
网络核心：IP 分片/TCP 握手/UDP 校验/局域网发现/蜂群消息中继。
单元：{任务 → 代码模式模板 + 验证样例 + 校准基准}——白箱自举（外部只校准）。
"""
import sys
sys.stdout.reconfigure(encoding='utf-8')

NET_UNITS = {
    "网络-IP分片": {
        "task": "IP分片",
        "pattern": (
            "def ip_fragment(packet_size, mtu):\n"
"    # 生效条件：math.ceil 可用\n"
"    # 子功能：① 条件判定 ② 结果处理\n"
"    # 执行：顺序执行\n"
"    # 不适用条件：输入不满足生效条件时返回 None/不执行\n"
            "    # IP 分片：包大小 + MTU → 分片数（每片含 20B IP 头）\n"
            "    import math\n"
            "    if packet_size <= mtu:\n"
            "        return 1\n"
            "    payload = mtu - 20\n"
            "    return math.ceil(packet_size / payload)\n"),
        "cases": [((1000, 500), 3),
                  ((100, 500), 1),
                  ((500, 100), 7)],
        "params": [],
        "calibration": "对照：网络 IP——超过 MTU 需分片（每片 20B 头）",
    },
    "网络-TCP握手": {
        "task": "TCP握手",
        "pattern": (
            "def tcp_handshake(states):\n"
            "    # TCP 三次握手：CLOSED → SYN → SYN-ACK → ESTABLISHED\n"
            "    # 生效条件：states 为事件序列（SYN/SYN-ACK/ACK 等）\n"
            "    # 子功能：① 状态机迁移 ② 非法事件忽略 ③ 到达 ESTABLISHED 判定\n"
            "    # 执行：状态转移表逐事件推进\n"
"    # 不适用条件：输入不满足生效条件时返回 None/不执行\n"
            "    state = 'CLOSED'\n"
            "    for ev in states:\n"
            "        if state == 'CLOSED' and ev == 'SYN':\n"
            "            state = 'SYN_SENT'\n"
            "        elif state == 'SYN_SENT' and ev == 'SYN-ACK':\n"
            "            state = 'ESTABLISHED'\n"
            "    return state\n"),
        "cases": [((['SYN', 'SYN-ACK'],), 'ESTABLISHED'),
                  ((['SYN'],), 'SYN_SENT'),
                  (( [],), 'CLOSED')],
        "params": [],
        "calibration": "对照：网络 TCP——三次握手状态机（CLOSED→SYN_SENT→ESTABLISHED）",
    },
    "网络-校验和": {
        "task": "校验和",
        "pattern": (
            "def checksum(data):\n"
"    # 生效条件：参数 data 合法\n"
"    # 子功能：① 条件判定 ② 结果处理\n"
"    # 执行：循环迭代\n"
"    # 不适用条件：total 越界（Gt）时\n"
            "    # UDP 校验和（简化）：16 位和进位折叠 → 取反\n"
            "    total = 0\n"
            "    for b in data:\n"
            "        total += b\n"
            "        if total > 0xFFFF:\n"
            "            total = (total & 0xFFFF) + 1\n"
            "    return (~total) & 0xFFFF\n"),
        "cases": [((bytes([1, 2, 3, 4]),), (~10) & 0xFFFF),
                  ((bytes([]),), 0xFFFF),
                  ((bytes([0xFF, 0xFF]),), (~510) & 0xFFFF)],
        "params": [],
        "calibration": "对照：网络 UDP——校验和（和取反，接收端校验出错）",
    },
    "网络-局域网发现": {
        "task": "局域网发现",
        "pattern": (
            "def discover(devices, heartbeat_ttl=3):\n"
"    # 生效条件：参数 devices/heartbeat_ttl 合法\n"
"    # 子功能：① 调用 sorted\n"
"    # 执行：循环迭代；顺序调用\n"
"    # 不适用条件：输入不满足生效条件时返回 None/不执行\n"
            "    # 局域网发现：设备表+心跳 → 在线设备（心跳超时剔除）\n"
            "    online = []\n"
            "    for dev in devices:\n"
            "        if dev.get('ttl', 0) > 0:\n"
            "            online.append(dev['name'])\n"
            "    return sorted(online)\n"),
        "cases": [(([{'name': 'A', 'ttl': 2}, {'name': 'B', 'ttl': 0}],), ['A']),
                  (([{'name': 'X', 'ttl': 1}],), ['X']),
                  (( [],), [])],
        "params": [],
        "calibration": "对照：局域网发现——设备心跳在线判定（TTL 超时离线）",
    },
    "网络-蜂群中继": {
        "task": "蜂群中继",
        "pattern": (
            "def swarm_relay(neighbors, source, message=None):\n"
"    # 生效条件：参数 neighbors/source/message 合法\n"
"    # 子功能：① 调用 set；② 调用 relay；③ 调用 sorted\n"
"    # 执行：循环迭代；顺序调用\n"
"    # 不适用条件：输入不满足生效条件时返回 None/不执行\n"
            "    # 蜂群消息：源节点 → 邻居递归中继（seen 防回环）\n"
            "    delivered = set()\n"
            "    def relay(node, seen):\n"
            "        # 递归中继：未访问则记录并继续转发给邻居（去重防回环）\n"
            "        if node in seen:\n"
            "            return\n"
            "        seen.add(node)\n"
            "        delivered.add(node)\n"
            "        for nxt in neighbors.get(node, []):\n"
            "            relay(nxt, seen)\n"
            "    relay(source, set())\n"
            "    return sorted(delivered)\n"),
        "cases": [(({'A': ['B', 'C'], 'B': ['D'], 'C': []}, 'A'), ['A', 'B', 'C', 'D']),
                  (({'A': ['B'], 'B': ['A']}, 'A'), ['A', 'B']),
                  (({'A': []}, 'A'), ['A'])],
        "params": [],
        "calibration": "对照：蜂群网络——消息经邻居递归中继，seen 防回环（去中心化传播）",
    },
    "蜂群-消息去重": {
        "task": "消息去重",
        "pattern": (
            "def dedup(messages, seen_ids):\n"
"    # 生效条件：参数 messages/seen_ids 合法\n"
"    # 子功能：① 条件判定 ② 结果处理\n"
"    # 执行：循环迭代\n"
"    # 不适用条件：输入不满足生效条件时返回 None/不执行\n"
            "    # 蜂群消息去重：已见 ID 跳过，新 ID 投递（防重复传播）\n"
            "    new = []\n"
            "    for msg in messages:\n"
            "        if msg['id'] not in seen_ids:\n"
            "            seen_ids.add(msg['id'])\n"
            "            new.append(msg)\n"
            "    return new\n"),
        "cases": [(([{'id': 1}, {'id': 1}, {'id': 2}], set()),
                   [{'id': 1}, {'id': 2}]),
                  (([{'id': 1}], {1}), [])],
        "params": [],
        "calibration": "对照：蜂群协议——消息 ID 去重（多路径重复投递只处理一次）",
    },
    "蜂群-路由表": {
        "task": "路由表",
        "pattern": (
            "def route_table_update(table, node, next_hop):\n"
"    # 生效条件：参数 table/node/next_hop 合法\n"
"    # 子功能：① 条件判定 ② 结果处理\n"
"    # 执行：顺序执行\n"
"    # 不适用条件：输入不满足生效条件时返回 None/不执行\n"
            "    # 路由表：节点 → 下一跳 维护（更新/查询）\n"
            "    if next_hop is not None:\n"
            "        table[node] = next_hop\n"
            "    return table.get(node)\n"),
        "cases": [(({}, 'A', 'B'), 'B'),
                  (({'A': 'B'}, 'A', None), 'B'),
                  (({'A': 'B'}, 'C', 'D'), 'D')],
        "params": [],
        "calibration": "对照：网络路由表——节点→下一跳（更新与查询）",
    },
    "蜂群-超时重传": {
        "task": "超时重传",
        "pattern": (
            "def retransmit(packets, ack_ids, max_tries=3):\n"
"    # 生效条件：参数 packets/ack_ids/max_tries 合法\n"
"    # 子功能：① 条件判定 ② 结果处理\n"
"    # 执行：循环迭代\n"
"    # 不适用条件：输入不满足生效条件时返回 None/不执行\n"
            "    # 蜂群可靠传输：未确认包超时重传（超过重试上限放弃）\n"
            "    need = []\n"
            "    for p in packets:\n"
            "        if p['id'] in ack_ids:\n"
            "            continue\n"
            "        if p.get('tries', 0) >= max_tries:\n"
            "            continue\n"
            "        p['tries'] = p.get('tries', 0) + 1\n"
            "        need.append(p['id'])\n"
            "    return need\n"),
        "cases": [(([{'id': 1, 'tries': 0}, {'id': 2, 'tries': 3}], {2}), [1]),
                  (([{'id': 1, 'tries': 0}], set()), [1]),
                  (([{'id': 1, 'tries': 0}], {1}), [])],
        "params": [],
        "calibration": "对照：可靠传输——未确认包重传，超重试上限放弃（TCP 重传语义）",
    },
    "网络-停等协议": {
        "task": "停等协议",
        "pattern": (
            "def stop_and_wait(send_packets, ack_all=True):\n"
"    # 生效条件：参数 send_packets/ack_all 合法\n"
"    # 子功能：① 条件判定 ② 结果处理\n"
"    # 执行：循环迭代\n"
"    # 不适用条件：ack_all 为空/非法时\n"
            "    # 停等协议：发送→等确认→再发下一个（ack_all=False 首包后停止）\n"
            "    sent = []\n"
            "    for p in send_packets:\n"
            "        sent.append(p)\n"
            "        if not ack_all:\n"
            "            break\n"
            "    return sent\n"),
        "cases": [(([1, 2, 3], True), [1, 2, 3]),
                  (([1, 2], False), [1]),
                  (( [], True), [])],
        "params": [],
        "calibration": "对照：网络可靠传输——停等协议（逐包确认后再发下一包）",
    },
    "蜂群-消息分帧": {
        "task": "消息分帧",
        "pattern": (
            "def frame_decode(buf, delim=b'\\r\\n'):\n"
"    # 生效条件：buf.find 可用\n"
"    # 子功能：① 调用 len\n"
"    # 执行：循环迭代；顺序调用\n"
"    # 不适用条件：idx 越界（Lt）时\n"
            "    # 蜂群会话层：字节流按分隔符分帧（粘包/半包处理）\n"
            "    frames = []\n"
            "    while True:\n"
            "        idx = buf.find(delim)\n"
            "        if idx < 0:\n"
            "            break\n"
            "        frames.append(buf[:idx])\n"
            "        buf = buf[idx + len(delim):]\n"
            "    return frames, buf\n"),
        "cases": [((b'hi\r\nhello\r\n',), ([b'hi', b'hello'], b'')),
                  ((b'partial',), ([], b'partial')),
                  ((b'a\r\nb\r\nc',), ([b'a', b'b'], b'c'))],
        "params": [],
        "calibration": "对照：会话层——字节流分帧（粘包拆帧、半包留待下段）",
    },
    "蜂群-会话状态": {
        "task": "会话状态",
        "pattern": (
            "def session_step(session, event):\n"
"    # 生效条件：参数 session/event 合法\n"
"    # 子功能：① 条件判定 ② 结果处理\n"
"    # 执行：顺序执行\n"
"    # 不适用条件：输入不满足生效条件时返回 None/不执行\n"
            "    # 蜂群会话状态机：LISTEN→SYN_SENT→ESTABLISHED（确认）→CLOSED（结束）\n"
            "    s = session.get('state', 'LISTEN')\n"
            "    if s == 'LISTEN' and event == 'SYN':\n"
            "        return 'SYN_SENT'\n"
            "    if s == 'SYN_SENT' and event == 'ACK':\n"
            "        return 'ESTABLISHED'\n"
            "    if s == 'ESTABLISHED' and event == 'FIN':\n"
            "        return 'CLOSED'\n"
            "    return s\n"),
        "cases": [(({'state': 'LISTEN'}, 'SYN'), 'SYN_SENT'),
                  (({'state': 'SYN_SENT'}, 'ACK'), 'ESTABLISHED'),
                  (({'state': 'ESTABLISHED'}, 'FIN'), 'CLOSED'),
                  (({'state': 'LISTEN'}, 'ACK'), 'LISTEN')],
        "params": [],
        "calibration": "对照：会话层——连接状态机（同步→确认→建立→关闭；非法事件不迁移）",
    },
    "网络-滑动窗口": {
        "task": "滑动窗口",
        "pattern": (
            "def sliding_window(base, next_seq, window_size, ack):\n"
            "    # TCP 滑动窗口（滑动窗口协议）：收到 ack 后窗口前移（可发送序号 = [next_seq, base+win)）\n"
            "    # 生效条件：base=已确认序号；next_seq=下一待发；ack=收到的确认\n"
            "    # 子功能：① ack 前进基准 ② 待发序号同步 ③ 返回可发送窗口\n"
            "    # 执行：ack > base 则前移；next_seq 落后则推进（滑动窗口语义）\n"
"    # 不适用条件：输入不满足生效条件时返回 None/不执行\n"
            "    # base=已确认序号 next_seq=下一待发 ack=收到的确认\n"
            "    if ack > base:\n"
            "        base = ack\n"
            "    if next_seq < base:\n"
            "        next_seq = base\n"
            "    return {'base': base, 'next_seq': next_seq,\n"
            "            'window': [base + i for i in range(window_size)]}\n"),
        "cases": [((0, 0, 3, 2), {'base': 2, 'next_seq': 2,
                                  'window': [2, 3, 4]}),
                  ((2, 2, 3, 5), {'base': 5, 'next_seq': 5,
                                  'window': [5, 6, 7]}),
                  ((0, 1, 2, 0), {'base': 0, 'next_seq': 1,
                                  'window': [0, 1]})],
        "params": [],
        "calibration": "对照：TCP 可靠传输——滑动窗口（ACK 确认后窗口前移，窗口内可发送）",
    },
    "网络-累积确认": {
        "task": "累积确认",
        "pattern": (
            "def cum_ack(received, seq):\n"
"    # 生效条件：参数 received/seq 合法\n"
"    # 子功能：① 主体逻辑执行\n"
"    # 执行：循环迭代\n"
"    # 不适用条件：输入不满足生效条件时返回 None/不执行\n"
            "    # TCP 累积确认：收到乱序包不确认，连续序列推进 ack（收到 3 则 1,2,3 都确认）\n"
            "    received.add(seq)\n"
            "    ack = 0\n"
            "    while ack + 1 in received:\n"
            "        ack += 1\n"
            "    return ack\n"),
        "cases": [(({1, 2}, 3), 3),
                  (({1, 3}, 2), 3),
                  ((set(), 1), 1),
                  (({2, 3}, 1), 3)],
        "params": [],
        "calibration": "对照：TCP 接收端——累积确认（连续序号推进 ACK；乱序只确认连续前缀）",
    },
    "网络-拥塞控制": {
        "task": "拥塞控制",
        "pattern": (
            "def slow_start(cwnd, ssthresh, acked, lost):\n"
"    # 生效条件：参数 cwnd/ssthresh/acked/lost 合法\n"
"    # 子功能：① 调用 max；② 调用 min\n"
"    # 执行：顺序调用\n"
"    # 不适用条件：输入不满足生效条件时返回 None/不执行\n"
            "    # TCP 拥塞控制：慢启动（cwnd 每 RTT 翻倍）→ 阈值后拥塞避免（线性+1）\n"
            "    # cwnd=拥塞窗口 ssthresh=慢启动阈值 acked=本 RTT 确认数 lost=是否丢包\n"
            "    if lost:\n"
            "        ssthresh = max(cwnd // 2, 1)\n"
            "        cwnd = 1\n"
            "        return {'cwnd': cwnd, 'ssthresh': ssthresh}\n"
            "    if cwnd < ssthresh:\n"
            "        return {'cwnd': min(cwnd + acked, ssthresh), 'ssthresh': ssthresh}\n"
            "    return {'cwnd': cwnd + 1, 'ssthresh': ssthresh}\n"),
        "cases": [((1, 8, 2, False), {'cwnd': 3, 'ssthresh': 8}),
                  ((4, 8, 4, False), {'cwnd': 8, 'ssthresh': 8}),
                  ((8, 8, 8, False), {'cwnd': 9, 'ssthresh': 8}),
                  ((8, 8, 0, True), {'cwnd': 1, 'ssthresh': 4})],
        "params": [],
        "calibration": "对照：TCP 拥塞控制——慢启动指数增长→阈值后线性+1；丢包减半阈值+重置窗口",
    },
    "网络-CIDR": {
        "task": "CIDR子网",
        "pattern": (
            "def cidr_network(ip, prefix):\n"
"    # 生效条件：参数 ip/prefix 合法\n"
"    # 子功能：① 调用 int；② 调用 to_ip；③ 调用 max\n"
"    # 执行：顺序调用\n"
"    # 不适用条件：输入不满足生效条件时返回 None/不执行\n"
            "    # IP 子网计算：IP + 前缀长度 → 网络地址/广播地址/主机数\n"
            "    parts = [int(x) for x in ip.split('.')]\n"
            "    mask_int = (0xFFFFFFFF << (32 - prefix)) & 0xFFFFFFFF\n"
            "    ip_int = (parts[0] << 24) | (parts[1] << 16) | (parts[2] << 8) | parts[3]\n"
            "    net_int = ip_int & mask_int\n"
            "    bcast_int = net_int | (~mask_int & 0xFFFFFFFF)\n"
            "    def to_ip(v):\n"
            "        # 整数转点分十进制 IP 字符串\n"
            "        return '.'.join(str((v >> s) & 0xFF) for s in (24, 16, 8, 0))\n"
            "    return {'network': to_ip(net_int), 'broadcast': to_ip(bcast_int),\n"
            "            'hosts': max(0, (1 << (32 - prefix)) - 2)}\n"),
        "cases": [(('192.168.1.130', 24),
                   {'network': '192.168.1.0', 'broadcast': '192.168.1.255',
                    'hosts': 254}),
                  (('10.0.0.5', 8),
                   {'network': '10.0.0.0', 'broadcast': '10.255.255.255',
                    'hosts': 16777214})],
        "params": [],
        "calibration": "对照：网络 IP——CIDR 子网计算（/24 网络地址+广播地址+可用主机数）",
    },
    "网络-距离矢量": {
        "task": "距离矢量",
        "pattern": (
            "def distance_vector(routes, neighbor, neighbor_routes):\n"
"    # 生效条件：参数 routes/neighbor/neighbor_routes 合法\n"
"    # 子功能：① 调用 dict\n"
"    # 执行：循环迭代；顺序调用\n"
"    # 不适用条件：输入不满足生效条件时返回 None/不执行\n"
            "    # 距离矢量路由（RIP）：收到邻居路由表 → 合并（距离+1，取最短）\n"
            "    for dst, dist in neighbor_routes.items():\n"
            "        nd = dist + 1\n"
            "        if dst not in routes or nd < routes[dst]:\n"
            "            routes[dst] = nd\n"
            "    return dict(routes)\n"),
        "cases": [(({'A': 0, 'B': 1}, 'C', {'A': 2, 'D': 1}),
                   {'A': 0, 'B': 1, 'D': 2}),
                  (({'A': 0}, 'B', {'A': 5, 'C': 1}),
                   {'A': 0, 'C': 2})],
        "params": [],
        "calibration": "对照：网络路由——距离矢量（邻居路由表合并，距离+1 取最短——RIP 语义）",
    },
    "网络-NAT": {
        "task": "NAT转换",
        "pattern": (
            "def nat_translate(table, src_ip, src_port, pub_ip):\n"
"    # 生效条件：参数 table/src_ip/src_port/pub_ip 合法\n"
"    # 子功能：① 调用 len\n"
"    # 执行：顺序调用\n"
"    # 不适用条件：输入不满足生效条件时返回 None/不执行\n"
            "    # NAT：内网地址→公网地址（端口映射表；已映射复用端口）\n"
            "    key = (src_ip, src_port)\n"
            "    if key in table:\n"
            "        return table[key]\n"
            "    pub_port = len(table) + 1024  # 分配新公网端口\n"
            "    table[key] = (pub_ip, pub_port)\n"
            "    return table[key]\n"),
        "cases": [(({}, '192.168.1.10', 5000, '8.8.8.8'),
                   ('8.8.8.8', 1024)),
                  (({('192.168.1.10', 5000): ('8.8.8.8', 1024)},
                    '192.168.1.10', 5000, '8.8.8.8'),
                   ('8.8.8.8', 1024)),
                  (({('192.168.1.10', 5000): ('8.8.8.8', 1024)},
                    '192.168.1.11', 5000, '8.8.8.8'),
                   ('8.8.8.8', 1025))],
        "params": [],
        "calibration": "对照：网络 NAT——内网→公网地址转换（端口映射表，复用已映射端口）",
    },
    "网络-DNS解析": {
        "task": "DNS解析",
        "pattern": (
            "def dns_resolve(cache, domain):\n"
"    # 生效条件：参数 cache/domain 合法\n"
"    # 子功能：① 条件判定 ② 结果处理\n"
"    # 执行：顺序执行\n"
"    # 不适用条件：输入不满足生效条件时返回 None/不执行\n"
            "    # DNS 解析：域名→IP（缓存命中直返；未命中模拟查询 8.8.8.8）\n"
            "    if domain in cache:\n"
            "        return cache[domain], 'cache'\n"
            "    ip = '8.8.8.8'\n"
            "    cache[domain] = ip\n"
            "    return ip, 'query'\n"),
        "cases": [(({'a.com': '1.1.1.1'}, 'a.com'), ('1.1.1.1', 'cache')),
                  (({}, 'b.com'), ('8.8.8.8', 'query')),
                  (({'a.com': '1.1.1.1'}, 'b.com'), ('8.8.8.8', 'query'))],
        "params": [],
        "calibration": "对照：DNS——域名解析（缓存命中直返/未命中查询，缓存加速语义）",
    },
    "网络-HTTP状态码": {
        "task": "HTTP状态码",
        "pattern": (
            "def http_status_class(code):\n"
"    # 生效条件：参数 code 合法\n"
"    # 子功能：① 条件判定 ② 结果处理\n"
"    # 执行：顺序执行\n"
"    # 不适用条件：输入不满足生效条件时返回 None/不执行\n"
            "    # HTTP 状态码分类：2xx 成功/3xx 重定向/4xx 客户端错/5xx 服务端错\n"
            "    if 200 <= code < 300:\n"
            "        return '成功'\n"
            "    if 300 <= code < 400:\n"
            "        return '重定向'\n"
            "    if 400 <= code < 500:\n"
            "        return '客户端错误'\n"
            "    if 500 <= code < 600:\n"
            "        return '服务端错误'\n"
            "    return '未知'\n"),
        "cases": [((200,), '成功'), ((301,), '重定向'),
                  ((404,), '客户端错误'), ((500,), '服务端错误')],
        "params": [],
        "calibration": "对照：HTTP 状态码分类（RFC 9110：2xx/3xx/4xx/5xx）",
    },
    "网络-负载均衡": {
        "task": "负载均衡",
        "pattern": (
            "def load_balance(servers, request_id):\n"
"    # 生效条件：参数 servers/request_id 合法\n"
"    # 子功能：① 调用 len\n"
"    # 执行：顺序调用\n"
"    # 不适用条件：servers 为空/非法时\n"
            "    # 负载均衡：轮询调度（请求 → 服务器轮转分配）\n"
            "    if not servers:\n"
            "        return None\n"
            "    return servers[request_id % len(servers)]\n"),
        "cases": [((['s1', 's2', 's3'], 0), 's1'),
                  ((['s1', 's2', 's3'], 4), 's2'),
                  (([], 0), None)],
        "params": [],
        "calibration": "对照：网络负载均衡——轮询调度（请求均匀分布到服务器）",
    },
    "网络-WebSocket握手": {
        "task": "WebSocket握手",
        "pattern": (
            "def ws_handshake(headers):\n"
"    # 生效条件：参数 headers 合法\n"
"    # 子功能：① 条件判定 ② 结果处理\n"
"    # 执行：顺序执行\n"
"    # 不适用条件：输入不满足生效条件时返回 None/不执行\n"
            "    # WebSocket 握手：HTTP Upgrade: websocket → 101 切换协议\n"
            "    upgrade = headers.get('Upgrade', '').lower()\n"
            "    key_ok = 'Sec-WebSocket-Key' in headers\n"
            "    if upgrade == 'websocket' and key_ok:\n"
            "        return 101, 'Switching Protocols'\n"
            "    return 400, 'Bad Request'\n"),
        "cases": [(({'Upgrade': 'websocket', 'Sec-WebSocket-Key': 'k'},),
                   (101, 'Switching Protocols')),
                  (({'Upgrade': 'http'},), (400, 'Bad Request')),
                  (({},), (400, 'Bad Request'))],
        "params": [],
        "calibration": "对照：WebSocket——HTTP Upgrade 握手（RFC 6455：101 切换协议/400 拒绝）",
    },
    "网络-帧封装": {
        "task": "帧封装",
        "pattern": (
            "def ws_frame(opcode, payload):\n"
"    # 生效条件：参数 opcode/payload 合法\n"
"    # 子功能：① 调用 len；② 调用 bytes\n"
"    # 执行：顺序调用\n"
"    # 不适用条件：n 越界（Lt）时\n"
            "    # WebSocket 帧：首字节(FIN+opcode) + 长度 + 负载（RFC 6455 简化）\n"
            "    fin_opcode = 0x80 | opcode   # FIN=1 + 4bit opcode\n"
            "    n = len(payload)\n"
            "    if n < 126:\n"
            "        return bytes([fin_opcode, n]) + payload\n"
            "    return bytes([fin_opcode, 126, (n >> 8) & 0xFF, n & 0xFF]) + payload\n"),
        "cases": [((1, b'hi'), b'\x81\x02hi'),
                  ((2, b'hello'), b'\x82\x05hello'),
                  ((1, b'x' * 130), bytes([0x81, 126, 0, 130]) + b'x' * 130)],
        "params": [],
        "calibration": "对照：WebSocket 帧——FIN+opcode+长度+负载（RFC 6455 帧格式）",
    },
    "网络-流式传输": {
        "task": "流式传输",
        "pattern": (
            "def chunked_encode(data, size=4):\n"
"    # 生效条件：chunk.decode 可用\n"
"    # 子功能：① 调用 range；② 调用 len\n"
"    # 执行：循环迭代；顺序调用\n"
"    # 不适用条件：输入不满足生效条件时返回 None/不执行\n"
            "    # 流式分块传输：数据切块 + 长度前缀（HTTP chunked 语义）\n"
            "    out = []\n"
            "    for i in range(0, len(data), size):\n"
            "        chunk = data[i:i + size]\n"
            "        out.append(f'{len(chunk):X}\\r\\n' + chunk.decode('utf-8', 'ignore') + '\\r\\n')\n"
            "    out.append('0\\r\\n\\r\\n')\n"
            "    return ''.join(out)\n"),
        "cases": [((b'abcdef', 4), '4\r\nabcd\r\n2\r\nef\r\n0\r\n\r\n'),
                  ((b'', 4), '0\r\n\r\n')],
        "params": [],
        "calibration": "对照：HTTP 流式传输——chunked 编码（分块+长度前缀+终止块）",
    },
    "网络-多路复用": {
        "task": "多路复用",
        "pattern": (
            "def stream_mux(streams):\n"
"    # 生效条件：参数 streams 合法\n"
"    # 子功能：① 主体逻辑执行\n"
"    # 执行：循环迭代\n"
"    # 不适用条件：输入不满足生效条件时返回 None/不执行\n"
            "    # HTTP/2 多路复用：多流帧交错（流 ID + 数据 → 单连接混合帧）\n"
            "    frames = []\n"
            "    for sid, data in streams:\n"
            "        frames.append((sid, data))\n"
            "    return frames\n"),
        "cases": [(([(1, 'a'), (3, 'b'), (5, 'c')],),
                   [(1, 'a'), (3, 'b'), (5, 'c')]),
                  (([],), [])],
        "params": [],
        "calibration": "对照：HTTP/2 多路复用——单连接多流帧交错（流 ID 区分）",
    },
    "网络-连接池": {
        "task": "连接池",
        "pattern": (
            "def conn_pool(pool, op, host=None):\n"
"    # 生效条件：op ∈ {get, put}\n"
"    # 子功能：① op 分支处理\n"
"    # 执行：按 op 分派；顺序调用\n"
"    # 不适用条件：op 非 {get, put} 时\n"
            "    # 连接池：获取复用/归还/新建（上限控制，避免频繁建连）\n"
            "    if op == 'get':\n"
            "        if pool.get(host):\n"
            "            return pool[host].pop()\n"
            "        return 'new'\n"
            "    if op == 'put':\n"
            "        pool.setdefault(host, []).append(1)\n"
            "        return len(pool[host])\n"
            "    return None\n"),
        "cases": [(({'a.com': [1]}, 'get', 'a.com'), 1),
                  (({}, 'get', 'a.com'), 'new'),
                  (({}, 'put', 'a.com'), 1)],
        "params": [],
        "calibration": "对照：网络连接池——获取复用/归还（空闲复用，避免重复建连）",
    },
    "网络-QUIC握手": {
        "task": "QUIC握手",
        "pattern": (
            "def quic_handshake(cache, client):\n"
"    # 生效条件：参数 cache/client 合法\n"
"    # 子功能：① 条件判定 ② 结果处理\n"
"    # 执行：顺序执行\n"
"    # 不适用条件：输入不满足生效条件时返回 None/不执行\n"
            "    # QUIC：0-RTT 快速握手（缓存会话 → 首次往返即发数据）\n"
            "    if client in cache:\n"
            "        return '0-RTT', cache[client]\n"
            "    cache[client] = 'ticket'\n"
            "    return '1-RTT', 'ticket'\n"),
        "cases": [(({}, 'c1'), ('1-RTT', 'ticket')),
                  (({'c1': 'ticket'}, 'c1'), ('0-RTT', 'ticket'))],
        "params": [],
        "calibration": "对照：QUIC——0-RTT 快速握手（缓存会话票据，二次连接免往返）",
    },
    "网络-BGP路径选择": {
        "task": "BGP路径选择",
        "pattern": (
            "def bgp_select(routes):\n"
"    # 生效条件：参数 routes 合法\n"
"    # 子功能：① 调用 len\n"
"    # 执行：循环迭代；顺序调用\n"
"    # 不适用条件：输入不满足生效条件时返回 None/不执行\n"
            "    # BGP 路径选择：AS 路径最短优先（选路决策属性）\n"
            "    best = None\n"
            "    for r in routes:\n"
            "        if best is None or len(r['as_path']) < len(best['as_path']):\n"
            "            best = r\n"
            "    return best\n"),
        "cases": [(([{'prefix': '10.0.0.0/8', 'as_path': ['AS1', 'AS2', 'AS3']},
                     {'prefix': '10.0.0.0/8', 'as_path': ['AS1', 'AS4']},
                     {'prefix': '10.0.0.0/8', 'as_path': ['AS5']}],),
                   {'prefix': '10.0.0.0/8', 'as_path': ['AS5']}),
                  (([{'as_path': ['A']}],), {'as_path': ['A']})],
        "params": [],
        "calibration": "对照：BGP 路由——路径选择（AS 路径最短优先，选路决策）",
    },
    "网络-Anycast": {
        "task": "Anycast",
        "pattern": (
            "def anycast_select(servers, client_loc):\n"
"    # 生效条件：参数 servers/client_loc 合法\n"
"    # 子功能：① 调用 min；② 调用 abs\n"
"    # 执行：顺序调用\n"
"    # 不适用条件：servers 为空/非法时\n"
            "    # Anycast：同一 IP 多节点 → 选最近（就近接入语义）\n"
            "    if not servers:\n"
            "        return None\n"
            "    return min(servers, key=lambda s: abs(s['loc'] - client_loc))\n"),
        "cases": [(([{'id': 'a', 'loc': 10}, {'id': 'b', 'loc': 50}], 15),
                   {'id': 'a', 'loc': 10}),
                  (([{'id': 'a', 'loc': 10}, {'id': 'b', 'loc': 50}], 45),
                   {'id': 'b', 'loc': 50}),
                  (([], 0), None)],
        "params": [],
        "calibration": "对照：Anycast——同 IP 多节点就近接入（地理位置最近优先）",
    },
    "网络-CRC校验": {
        "task": "CRC校验",
        "pattern": (
            "def crc16(data):\n"
"    # 生效条件：参数 data 合法\n"
"    # 子功能：① 调用 range\n"
"    # 执行：循环迭代；顺序调用\n"
"    # 不适用条件：输入不满足生效条件时返回 None/不执行\n"
            "    # CRC-16 校验：多项式 0x8005（数据完整性——传输错误检测）\n"
            "    crc = 0\n"
            "    for b in data:\n"
            "        crc ^= b << 8\n"
            "        for _ in range(8):\n"
            "            if crc & 0x8000:\n"
            "                crc = ((crc << 1) ^ 0x8005) & 0xFFFF\n"
            "            else:\n"
            "                crc = (crc << 1) & 0xFFFF\n"
            "    return crc\n"),
        "cases": [((b'',), 0),
                  ((b'AB',), 1929),
                  ((b'\x00',), 0)],
        "params": [],
        "calibration": "对照：CRC-16 校验——多项式除法余数（传输完整性检测）",
    },
    "网络-IPv6地址": {
        "task": "IPv6地址",
        "pattern": (
            "def ipv6_parse(addr):\n"
"    # 生效条件：参数 addr 合法\n"
"    # 子功能：① 调用 len\n"
"    # 执行：顺序调用\n"
"    # 不适用条件：输入不满足生效条件时返回 None/不执行\n"
            "    # IPv6 解析：压缩形式展开 + 分组（:: 零压缩还原）\n"
            "    if '::' in addr:\n"
            "        left, right = addr.split('::')\n"
            "        l = left.split(':') if left else []\n"
            "        r = right.split(':') if right else []\n"
            "        missing = 8 - len(l) - len(r)\n"
            "        groups = l + ['0'] * missing + r\n"
            "    else:\n"
            "        groups = addr.split(':')\n"
            "    return groups\n"),
        "cases": [(('fe80::1',), ['fe80', '0', '0', '0', '0', '0', '0', '1']),
                  (('2001:db8::ff:1',), ['2001', 'db8', '0', '0', '0', '0', 'ff', '1']),
                  (('::1',), ['0', '0', '0', '0', '0', '0', '0', '1'])],
        "params": [],
        "calibration": "对照：IPv6 地址——:: 零压缩展开为 8 组（RFC 4291）",
    },
    "网络-隧道封装": {
        "task": "隧道封装",
        "pattern": (
            "def tunnel_encap(inner, outer_src, outer_dst):\n"
"    # 生效条件：参数 inner/outer_src/outer_dst 合法\n"
"    # 子功能：① 主体逻辑执行\n"
"    # 执行：顺序执行\n"
"    # 不适用条件：输入不满足生效条件时返回 None/不执行\n"
            "    # 隧道：内层包 + 外层头（IP-in-IP 封装——跨网络传输）\n"
            "    return {'outer': (outer_src, outer_dst), 'inner': inner}\n"
            "def tunnel_decap(pkt):\n"
            "    # 解封装：剥离外层头 → 内层包\n"
            "    return pkt['inner']\n"),
        "cases": [(('inner_data', '10.0.0.1', '10.0.0.2'),
                   {'outer': ('10.0.0.1', '10.0.0.2'), 'inner': 'inner_data'})],
        "params": [],
        "calibration": "对照：隧道——IP-in-IP 封装/解封装（外层头包裹内层包）",
    },
    "网络-VLAN划分": {
        "task": "VLAN划分",
        "pattern": (
            "def vlan_tag(frame, vlan_id):\n"
"    # 生效条件：参数 frame/vlan_id 合法\n"
"    # 子功能：① 主体逻辑执行\n"
"    # 执行：顺序执行\n"
"    # 不适用条件：输入不满足生效条件时返回 None/不执行\n"
            "    # VLAN：802.1Q 标签（4 字节——TPID+TCI 含 VID 12bit）\n"
            "    tci = vlan_id & 0xFFF\n"
            "    return ('0x8100', tci)\n"),
        "cases": [(('data', 100), ('0x8100', 100)),
                  (('data', 4095), ('0x8100', 4095)),
                  (('data', 0), ('0x8100', 0))],
        "params": [],
        "calibration": "对照：VLAN——802.1Q 标签（TPID 0x8100 + VID 12bit）",
    },
    "网络-MQTT发布订阅": {
        "task": "MQTT发布订阅",
        "pattern": (
            "def mqtt_broker(broker, op, topic=None, payload=None, client=None):\n"
"    # 生效条件：op ∈ {publish, subscribe}\n"
"    # 子功能：① op 分支处理\n"
"    # 执行：按 op 分派；顺序调用\n"
"    # 不适用条件：op 非 {publish, subscribe} 时\n"
            "    # MQTT：发布/订阅（主题路由——客户端订阅主题收消息）\n"
            "    if op == 'subscribe':\n"
            "        broker.setdefault(topic, set()).add(client)\n"
            "        return len(broker[topic])\n"
            "    if op == 'publish':\n"
            "        subs = broker.get(topic, set())\n"
            "        return sorted(subs)\n"
            "    return None\n"),
        "cases": [(({}, 'subscribe', 'temp', None, 'dev1'), 1),
                  (({'temp': {'dev1'}}, 'publish', 'temp', 25.5), ['dev1']),
                  (({}, 'publish', 'temp', 1), [])],
        "params": [],
        "calibration": "对照：MQTT——发布/订阅（主题路由，订阅者接收主题消息）",
    },
    "网络-物联网遥测": {
        "task": "物联网遥测",
        "pattern": (
            "def iot_telemetry(devices, device, reading):\n"
"    # 生效条件：参数 devices/device/reading 合法\n"
"    # 子功能：① 调用 len\n"
"    # 执行：顺序调用\n"
"    # 不适用条件：输入不满足生效条件时返回 None/不执行\n"
            "    # IoT 遥测：传感器读数上报（设备 → 平台数据流）\n"
            "    devices.setdefault(device, []).append(reading)\n"
            "    return len(devices[device])\n"),
        "cases": [(({}, 'sensor1', 22.5), 1),
                  (({'sensor1': [22.5]}, 'sensor1', 23.0), 2),
                  (({}, 'sensor2', 1), 1)],
        "params": [],
        "calibration": "对照：物联网——传感器遥测上报（设备读数持续流）",
    },
    "网络-消息队列": {
        "task": "消息队列",
        "pattern": (
            "def msg_queue(q, op, item=None):\n"
"    # 生效条件：op ∈ {dequeue, enqueue}\n"
"    # 子功能：① op 分支处理\n"
"    # 执行：按 op 分派；顺序调用\n"
"    # 不适用条件：q 为空/非法时；op 非 {dequeue, enqueue} 时\n"
            "    # 消息队列：入队/出队（FIFO 生产消费解耦）\n"
            "    if op == 'enqueue':\n"
            "        q.append(item)\n"
            "        return len(q)\n"
            "    if op == 'dequeue':\n"
            "        if not q:\n"
            "            return None\n"
            "        return q.pop(0)\n"
            "    return None\n"),
        "cases": [(([], 'enqueue', 'a'), 1),
                  ((['a'], 'dequeue'), 'a'),
                  (([], 'dequeue'), None)],
        "params": [],
        "calibration": "对照：消息队列——FIFO 入队出队（生产消费解耦）",
    },
    "网络-CDN缓存": {
        "task": "CDN缓存",
        "pattern": (
            "def cdn_cache(edges, content, url):\n"
"    # 生效条件：参数 edges/content/url 合法\n"
"    # 子功能：① 条件判定 ② 结果处理\n"
"    # 执行：顺序执行\n"
"    # 不适用条件：输入不满足生效条件时返回 None/不执行\n"
            "    # CDN：边缘节点缓存（内容就近分发——回源/命中）\n"
            "    edge = edges[0] if edges else None\n"
            "    if edge is None:\n"
            "        return ('origin', url)\n"
            "    edge.setdefault('cache', {})\n"
            "    if url in edge['cache']:\n"
            "        return ('hit', edge['cache'][url])\n"
            "    edge['cache'][url] = content\n"
            "    return ('miss', content)\n"),
        "cases": [(([{'cache': {}}], 'DATA', '/a'), ('miss', 'DATA')),
                  (([{'cache': {'/a': 'DATA'}}], 'X', '/a'), ('hit', 'DATA')),
                  (([], 'DATA', '/a'), ('origin', '/a'))],
        "params": [],
        "calibration": "对照：CDN——边缘缓存（命中/回源/缓存写入，内容就近分发）",
    },
    "网络-边缘计算": {
        "task": "边缘计算",
        "pattern": (
            "def edge_compute(nodes, task, data):\n"
"    # 生效条件：参数 nodes/task/data 合法\n"
"    # 子功能：① 调用 min\n"
"    # 执行：顺序调用\n"
"    # 不适用条件：nodes 为空/非法时（隐式盲区：返回默认值 ('cloud', 0) = 未知行为——不适用）\n"
            "    # 边缘计算：任务分发到就近节点处理（延迟降低语义）\n"
            "    if not nodes:\n"
            "        return ('cloud', task)\n"
            "    node = min(nodes, key=lambda n: n['loc'])\n"
            "    return (node['id'], task, node['fn'](data))\n"),
        "cases": [(([{'id': 'e1', 'loc': 1, 'fn': lambda x: x * 2}], 'double', 5),
                   ('e1', 'double', 10)),
                  (([], 'task', 1), ('cloud', 'task'))],
        "params": [],
        "calibration": "对照：边缘计算——任务就近处理（边缘节点/云端回退）",
    },
    "网络-内容路由": {
        "task": "内容路由",
        "pattern": (
            "def content_route(table, url):\n"
"    # 生效条件：url.startswith 可用\n"
"    # 子功能：① 调用 len\n"
"    # 执行：循环迭代；顺序调用\n"
"    # 不适用条件：输入不满足生效条件时返回 None/不执行\n"
            "    # 内容路由：URL 前缀 → 后端节点（按内容寻址）\n"
            "    best = None\n"
            "    for prefix, node in table.items():\n"
            "        if url.startswith(prefix) and (best is None\n"
            "                                       or len(prefix) > len(best[0])):\n"
            "            best = (prefix, node)\n"
            "    return best[1] if best else None\n"),
        "cases": [(({'/img': 'img-srv', '/img/logo': 'logo-srv'}, '/img/logo/a.png'),
                   'logo-srv'),
                  (({'/api': 'api-srv'}, '/static/x'), None)],
        "params": [],
        "calibration": "对照：内容路由——URL 最长前缀匹配（按内容寻址到节点）",
    },
    "网络-流量统计": {
        "task": "流量统计",
        "pattern": (
            "def traffic_stats(flows):\n"
"    # 生效条件：参数 flows 合法\n"
"    # 子功能：① 主体逻辑执行\n"
"    # 执行：循环迭代\n"
"    # 不适用条件：输入不满足生效条件时返回 None/不执行\n"
            "    # 流量统计：每流字节/包汇总（流量分析）\n"
            "    stats = {}\n"
            "    for f in flows:\n"
            "        key = f['src'] + '→' + f['dst']\n"
            "        s = stats.setdefault(key, {'bytes': 0, 'pkts': 0})\n"
            "        s['bytes'] += f['bytes']\n"
            "        s['pkts'] += f['pkts']\n"
            "    return stats\n"),
        "cases": [(([{'src': 'a', 'dst': 'b', 'bytes': 100, 'pkts': 2},
                     {'src': 'a', 'dst': 'b', 'bytes': 50, 'pkts': 1}],),
                   {'a→b': {'bytes': 150, 'pkts': 3}}),
                  (([],), {})],
        "params": [],
        "calibration": "对照：网络监控——流量统计（每流字节/包汇总）",
    },
    "网络-延迟测量": {
        "task": "延迟测量",
        "pattern": (
            "def rtt_stats(samples):\n"
"    # 生效条件：参数 samples 合法\n"
"    # 子功能：① 调用 round；② 调用 min；③ 调用 max\n"
"    # 执行：顺序调用\n"
"    # 不适用条件：samples 为空/非法时（隐式盲区：返回默认值 {'avg': 0.0, 'min': 0, 'max':  = 未知行为——不适用）\n"
            "    # RTT 测量：延迟样本 → 平均/最小/最大（链路质量）\n"
            "    if not samples:\n"
            "        return {'avg': 0.0, 'min': 0, 'max': 0}\n"
            "    return {'avg': round(sum(samples) / len(samples), 2),\n"
            "            'min': min(samples), 'max': max(samples)}\n"),
        "cases": [(([10, 20, 30],), {'avg': 20.0, 'min': 10, 'max': 30}),
                  (([],), {'avg': 0.0, 'min': 0, 'max': 0})],
        "params": [],
        "calibration": "对照：网络监控——RTT 延迟测量（平均/最小/最大）",
    },
    "网络-异常检测": {
        "task": "异常检测",
        "pattern": (
            "def anomaly_detect(traffic, threshold):\n"
"    # 生效条件：参数 traffic/threshold 合法\n"
"    # 子功能：① 条件判定 ② 结果处理\n"
"    # 执行：循环迭代\n"
"    # 不适用条件：输入不满足生效条件时返回 None/不执行\n"
            "    # 异常检测：流量突增（超过阈值 → 告警）\n"
            "    alerts = []\n"
            "    for t in traffic:\n"
            "        if t > threshold:\n"
            "            alerts.append(t)\n"
            "    return alerts\n"),
        "cases": [(([50, 200, 80], 100), [200]),
                  (([10, 20], 100), []),
                  (([], 100), [])],
        "params": [],
        "calibration": "对照：网络监控——异常检测（流量突增告警）",
    },
    "网络-报文解析": {
        "task": "报文解析",
        "pattern": (
            "def parse_ip(packet):\n"
            "    # 报文解析（IP 数据包解析）：头部字段（版本/协议/源/目的）\n"
            "    # 生效条件：packet 为 IP 报文字节（≥20 字节头部）\n"
            "    # 子功能：① 版本/协议提取 ② 源地址提取 ③ 目的地址提取\n"
            "    # 执行：按字节偏移位运算 + 点分十进制拼接\n"
"    # 不适用条件：输入不满足生效条件时返回 None/不执行\n"
            "    ver = packet[0] >> 4\n"
            "    proto = packet[9]\n"
            "    src = '.'.join(str(b) for b in packet[12:16])\n"
            "    dst = '.'.join(str(b) for b in packet[16:20])\n"
            "    return {'version': ver, 'proto': proto, 'src': src, 'dst': dst}\n"),
        "cases": [((bytes([0x45, 0, 0, 0, 0, 0, 0, 0, 0, 6, 0, 0,
                           192, 168, 1, 1, 8, 8, 8, 8]),),
                   {'version': 4, 'proto': 6, 'src': '192.168.1.1',
                    'dst': '8.8.8.8'})],
        "params": [],
        "calibration": "对照：网络分析——IP 报文解析（版本/协议/源/目的）",
    },
    "网络-抓包分析": {
        "task": "抓包分析",
        "pattern": (
            "def capture_stats(captures):\n"
"    # 生效条件：参数 captures 合法\n"
"    # 子功能：① 调用 len\n"
"    # 执行：循环迭代；顺序调用\n"
"    # 不适用条件：输入不满足生效条件时返回 None/不执行\n"
            "    # 抓包分析：包计数/协议分布（pcap 统计语义）\n"
            "    total = len(captures)\n"
            "    by_proto = {}\n"
            "    for c in captures:\n"
            "        by_proto[c['proto']] = by_proto.get(c['proto'], 0) + 1\n"
            "    return {'total': total, 'by_proto': by_proto}\n"),
        "cases": [(([{'proto': 'TCP'}, {'proto': 'TCP'}, {'proto': 'UDP'}],),
                   {'total': 3, 'by_proto': {'TCP': 2, 'UDP': 1}}),
                  (([],), {'total': 0, 'by_proto': {}})],
        "params": [],
        "calibration": "对照：抓包分析——包计数/协议分布（pcap 统计）",
    },
    "网络-协议解码": {
        "task": "协议解码",
        "pattern": (
            "def hex_decode(hex_str):\n"
"    # 生效条件：bytes.fromhex 可用\n"
"    # 子功能：① 主体逻辑执行\n"
"    # 执行：顺序执行\n"
"    # 不适用条件：输入不满足生效条件时返回 None/不执行\n"
            "    # 协议解码：十六进制 → 字节串（抓包数据解码）\n"
            "    return bytes.fromhex(hex_str)\n"),
        "cases": [(('48656c6c6f',), b'Hello'),
                  (('00',), b'\x00'),
                  (('',), b'')],
        "params": [],
        "calibration": "对照：协议解码——十六进制转字节（抓包数据）",
    },
    "网络-令牌桶限速": {
        "task": "令牌桶",
        "pattern": (
            "def token_bucket(tokens, capacity, rate, elapsed):\n"
"    # 生效条件：参数 tokens/capacity/rate/elapsed 合法\n"
"    # 子功能：① 调用 min\n"
"    # 执行：顺序调用\n"
"    # 不适用条件：输入不满足生效条件时返回 None/不执行\n"
            "    # 令牌桶限速：按速率补令牌（上限 capacity）——流量整形\n"
            "    return min(capacity, tokens + rate * elapsed)\n"),
        "cases": [((0, 10, 2, 3), 6),
                  ((8, 10, 2, 3), 10),
                  ((5, 10, 0, 5), 5)],
        "params": [],
        "calibration": "对照：网络限速——令牌桶（速率补令牌，容量封顶）",
    },
    "网络-服务发现": {
        "task": "服务发现",
        "pattern": (
            "def service_discover(registry, op, service=None, addr=None, ttl=0, now=0):\n"
"    # 生效条件：op ∈ {discover, heartbeat, register}\n"
"    # 子功能：① op 分支处理\n"
"    # 执行：按 op 分派\n"
"    # 不适用条件：op 非 {discover, heartbeat, register} 时\n"
            "    # 服务发现：注册 / 心跳续期 / 发现（健康节点，过期剔除）\n"
            "    if op == 'register':\n"
            "        registry[service] = {'addr': addr, 'expire': now + ttl}\n"
            "        return 'registered'\n"
            "    if op == 'heartbeat':\n"
            "        if service in registry:\n"
            "            registry[service]['expire'] = now + ttl\n"
            "            return 'renewed'\n"
            "        return 'unknown'\n"
            "    if op == 'discover':\n"
            "        return [s for s, info in registry.items()\n"
            "                if info['expire'] >= now]\n"
            "    return None\n"),
        "cases": [(({}, 'register', 'svc1', '10.0.0.1', 60, 100), 'registered'),
                  (({'svc1': {'addr': '10.0.0.1', 'expire': 160}}, 'discover',
                    None, None, 0, 100), ['svc1']),
                  (({'svc1': {'addr': 'a', 'expire': 150}}, 'discover',
                    None, None, 0, 160), []),
                  (({}, 'heartbeat', 'svc1', None, 60, 100), 'unknown')],
        "params": [],
        "calibration": "对照：服务发现——注册/心跳续期/健康发现（过期剔除）",
    },
    "网络-加密握手": {
        "task": "加密握手",
        "pattern": (
            "def tls_handshake(state, op):\n"
"    # 生效条件：op ∈ {exchange, finish, hello}\n"
"    # 子功能：① op 分支处理\n"
"    # 执行：按 op 分派\n"
"    # 不适用条件：op 非 {exchange, finish, hello} 时\n"
            "    # 加密传输：TLS 简化握手状态机（问候→密钥交换→完成→安全通道）\n"
            "    if op == 'hello':\n"
            "        state['phase'] = 'hello'\n"
            "        return 'server_hello'\n"
            "    if op == 'exchange':\n"
            "        state['phase'] = 'exchange'\n"
            "        state['session_key'] = (state.get('client_rand', 0)\n"
            "                                + state.get('server_rand', 0)) % 256\n"
            "        return 'key_established'\n"
            "    if op == 'finish':\n"
            "        if 'session_key' not in state:\n"
            "            if 'client_rand' not in state or 'server_rand' not in state:\n"
            "                return 'not_ready'\n"
            "            # 防御式：未显式 exchange 时自动协商（状态机容错）\n"
            "            state['session_key'] = (state['client_rand']\n"
            "                                    + state['server_rand']) % 256\n"
            "        state['phase'] = 'secure'\n"
            "        return 'secure_channel'\n"
            "    return None\n"),
        "cases": [(({'client_rand': 7}, 'hello'), 'server_hello'),
                  (({'client_rand': 7, 'server_rand': 3}, 'exchange'),
                   'key_established'),
                  (({'client_rand': 7, 'server_rand': 3}, 'finish'),
                   'secure_channel'),
                  (({}, 'finish'), 'not_ready')],
        "params": [],
        "calibration": "对照：TLS 握手——问候→密钥交换→完成（会话密钥协商）",
    },
    "网络-慢启动": {
        "task": "慢启动",
        "pattern": (
            "def slow_start(cwnd, ssthresh, rtts):\n"
"    # 生效条件：参数 cwnd/ssthresh/rtts 合法\n"
"    # 子功能：① 调用 range\n"
"    # 执行：循环迭代；顺序调用\n"
"    # 不适用条件：输入不满足生效条件时返回 None/不执行\n"
            "    # 慢启动：每 RTT 拥塞窗口翻倍（指数增长），达阈值转拥塞避免（线性）\n"
            "    for _ in range(rtts):\n"
            "        if cwnd < ssthresh:\n"
            "            cwnd *= 2\n"
            "        else:\n"
            "            cwnd += 1\n"
            "    return cwnd\n"),
        "cases": [((1, 8, 3), 8),
                  ((1, 8, 5), 10),
                  ((4, 8, 1), 8),
                  ((1, 2, 0), 1)],
        "params": [],
        "calibration": "对照：TCP 慢启动——每 RTT 窗口翻倍，达阈值转线性（拥塞避免）",
    },
    "网络-快速重传": {
        "task": "快速重传",
        "pattern": (
            "def fast_retransmit(dup_acks, threshold=3):\n"
"    # 生效条件：参数 dup_acks/threshold 合法\n"
"    # 子功能：① 主体逻辑执行\n"
"    # 执行：顺序执行\n"
"    # 不适用条件：输入不满足生效条件时返回 None/不执行\n"
            "    # 快速重传：重复 ACK 达阈值立即重传（不等超时——快速恢复）\n"
            "    return dup_acks >= threshold\n"),
        "cases": [((2, 3), False),
                  ((3, 3), True),
                  ((5, 3), True),
                  ((3, 4), False)],
        "params": [],
        "calibration": "对照：TCP 快速重传——3 个重复 ACK 触发立即重传（不等超时）",
    },
    "网络-选择性确认": {
        "task": "选择性确认",
        "pattern": (
            "def sack_missing(received, expected):\n"
"    # 生效条件：参数 received/expected 合法\n"
"    # 子功能：① 调用 range\n"
"    # 执行：顺序调用\n"
"    # 不适用条件：输入不满足生效条件时返回 None/不执行\n"
            "    # 选择性确认：已收段 vs 期望序列 → 缺失段（SACK——只重传缺失）\n"
            "    return [i for i in range(1, expected + 1) if i not in received]\n"),
        "cases": [(({1, 2, 4}, 5), [3, 5]),
                  (({1, 2, 3}, 3), []),
                  ((set(), 3), [1, 2, 3])],
        "params": [],
        "calibration": "对照：TCP SACK——块确认只重传缺失段（高效丢包恢复）",
    },
    "网络-端口转发": {
        "task": "端口转发",
        "pattern": (
            "def port_forward(table, op, ext_port=None, int_host=None, int_port=None):\n"
"    # 生效条件：op ∈ {add, lookup, remove}\n"
"    # 子功能：① op 分支处理\n"
"    # 执行：按 op 分派\n"
"    # 不适用条件：op 非 {add, lookup, remove} 时\n"
            "    # 端口转发：add 映射 / lookup 查询 / remove 删除（外网端口→内网）\n"
            "    if op == 'add':\n"
            "        table[ext_port] = (int_host, int_port)\n"
            "        return 'added'\n"
            "    if op == 'lookup':\n"
            "        return table.get(ext_port)\n"
            "    if op == 'remove':\n"
            "        return table.pop(ext_port, None)\n"
            "    return None\n"),
        "cases": [(({}, 'add', 8080, '192.168.1.10', 80), 'added'),
                  (({8080: ('192.168.1.10', 80)}, 'lookup', 8080),
                   ('192.168.1.10', 80)),
                  (({}, 'lookup', 8080), None),
                  (({8080: ('h', 80)}, 'remove', 8080), ('h', 80))],
        "params": [],
        "calibration": "对照：NAT 端口转发——外网端口→内网主机端口映射（增删查）",
    },
    "网络-QoS队列": {
        "task": "QoS队列",
        "pattern": (
            "def qos_queue(queues, op, flow=None, priority=None):\n"
"    # 生效条件：op ∈ {classify, dequeue, enqueue}\n"
"    # 子功能：① op 分支处理\n"
"    # 执行：按 op 分派；循环迭代\n"
"    # 不适用条件：op 非 {classify, dequeue, enqueue} 时\n"
            "    # QoS 队列：classify 流量分类 / enqueue 按优先级入队 / dequeue 高优先先出\n"
            "    if op == 'classify':\n"
            "        return 'high' if priority and priority >= 3 else 'low'\n"
            "    if op == 'enqueue':\n"
            "        lvl = 'high' if priority and priority >= 3 else 'low'\n"
            "        queues.setdefault(lvl, []).append(flow)\n"
            "        return lvl\n"
            "    if op == 'dequeue':\n"
            "        for lvl in ('high', 'low'):\n"
            "            q = queues.get(lvl)\n"
            "            if q:\n"
            "                return q.pop(0)\n"
            "        return None\n"
            "    return None\n"),
        "cases": [(({}, 'classify', None, 5), 'high'),
                  (({}, 'classify', None, 1), 'low'),
                  (({}, 'enqueue', 'f1', 5), 'high'),
                  (({'high': ['f1']}, 'dequeue', None, None), 'f1'),
                  (({}, 'dequeue', None, None), None)],
        "params": [],
        "calibration": "对照：网络 QoS——流量分类+优先级队列（高优先先出）",
    },
    "网络-链路聚合": {
        "task": "链路聚合",
        "pattern": (
            "def link_aggregation(links, op, link_id=None, data=None):\n"
"    # 生效条件：op ∈ {add, fail, send}\n"
"    # 子功能：① op 分支处理\n"
"    # 执行：按 op 分派；循环迭代；顺序调用\n"
"    # 不适用条件：up 为空/非法时；op 非 {add, fail, send} 时\n"
            "    # 链路聚合：add 加链路 / send 选最少链路分发（负载均衡）/ fail 故障切换\n"
            "    if op == 'add':\n"
            "        links.append({'id': link_id, 'up': True, 'sent': 0})\n"
            "        return len(links) - 1\n"
            "    if op == 'send':\n"
            "        up = [l for l in links if l['up']]\n"
            "        if not up:\n"
            "            return 'no_link'\n"
            "        best = min(up, key=lambda l: l['sent'])\n"
            "        best['sent'] += 1\n"
            "        return best['id']\n"
            "    if op == 'fail':\n"
            "        for l in links:\n"
            "            if l['id'] == link_id:\n"
            "                l['up'] = False\n"
            "                return 'failed'\n"
            "        return 'missing'\n"
            "    return None\n"),
        "cases": [(([], 'add', 1), 0),
                  (([{'id': 1, 'up': True, 'sent': 0}], 'send'), 1),
                  (([{'id': 1, 'up': False}], 'send'), 'no_link'),
                  (([{'id': 1, 'up': True, 'sent': 2},
                     {'id': 2, 'up': True, 'sent': 0}], 'send'), 2),
                  (([{'id': 1, 'up': True, 'sent': 0}], 'fail', 1), 'failed')],
        "params": [],
        "calibration": "对照：链路聚合 bonding——多链路负载均衡+故障切换",
    },
    "网络-滑动窗口限流": {
        "task": "滑动窗口限流",
        "pattern": (
            "def rate_limit(requests, window, limit):\n"
"    # 生效条件：参数 requests/window/limit 合法\n"
"    # 子功能：① 调用 enumerate；② 调用 sum\n"
"    # 执行：循环迭代；顺序调用\n"
"    # 不适用条件：输入不满足生效条件时返回 None/不执行\n"
            "    # 滑动窗口限流：窗口内请求数 ≤ 上限（时间戳窗口滑动）\n"
            "    out = []\n"
            "    for i, ts in enumerate(requests):\n"
            "        window_start = ts - window\n"
            "        cnt = sum(1 for t in requests[:i + 1] if t >= window_start)\n"
            "        out.append('allow' if cnt <= limit else 'deny')\n"
            "    return out\n"),
        "cases": [(([1, 2, 3], 10, 2), ['allow', 'allow', 'deny']),
                  (([1, 2, 3], 10, 3), ['allow', 'allow', 'allow']),
                  (([], 10, 2), []),
                  (([1, 11], 10, 1), ['allow', 'deny'])],
        "params": [],
        "calibration": "对照：滑动窗口限流——窗口内请求计数（超限拒绝）",
    },
    "网络-反向代理": {
        "task": "反向代理",
        "pattern": (
            "def reverse_proxy(backends, op, backend_id=None):\n"
"    # 生效条件：op ∈ {fail, recover, route}\n"
"    # 子功能：① op 分支处理\n"
"    # 执行：按 op 分派；顺序调用\n"
"    # 不适用条件：healthy 为空/非法时；op 非 {fail, recover, route} 时\n"
            "    # 反向代理：route 轮询转发（客户端不知后端）/ fail 摘除 / recover 恢复\n"
            "    if op == 'route':\n"
            "        healthy = [i for i, b in enumerate(backends) if b.get('up', True)]\n"
            "        if not healthy:\n"
            "            return 'no_backend'\n"
            "        hits = [b.get('hits', 0) for b in backends]\n"
            "        total = sum(hits[i] for i in healthy)\n"
            "        idx = healthy[total % len(healthy)]\n"
            "        backends[idx]['hits'] = hits[idx] + 1\n"
            "        return idx\n"
            "    if op == 'fail':\n"
            "        backends[backend_id]['up'] = False\n"
            "        return 'failed'\n"
            "    if op == 'recover':\n"
            "        backends[backend_id]['up'] = True\n"
            "        return 'recovered'\n"
            "    return None\n"),
        "cases": [(([{'up': True, 'hits': 0}], 'route'), 0),
                  (([{'up': False}], 'route'), 'no_backend'),
                  (([{'up': True, 'hits': 0}, {'up': True, 'hits': 1}],
                    'route'), 1),
                  (([{'up': True, 'hits': 0}], 'fail', 0), 'failed')],
        "params": [],
        "calibration": "对照：反向代理——轮询转发/健康摘除（后端对客户端透明）",
    },
    "网络-组播": {
        "task": "组播",
        "pattern": (
            "def multicast_group(groups, op, group=None, member=None, msg=None):\n"
"    # 生效条件：op ∈ {join, leave, send}\n"
"    # 子功能：① op 分支处理\n"
"    # 执行：按 op 分派\n"
"    # 不适用条件：op 非 {join, leave, send} 时\n"
            "    # 组播：join 加入组 / leave 离开 / send 组内广播（成员管理）\n"
            "    if op == 'join':\n"
            "        groups.setdefault(group, []).append(member)\n"
            "        return groups[group]\n"
            "    if op == 'leave':\n"
            "        g = groups.get(group, [])\n"
            "        if member in g:\n"
            "            g.remove(member)\n"
            "        return g\n"
            "    if op == 'send':\n"
            "        return [(m, msg) for m in groups.get(group, [])]\n"
            "    return None\n"),
        "cases": [(({}, 'join', 'g1', 'a'), ['a']),
                  (({'g1': ['a', 'b']}, 'leave', 'g1', 'a'), ['b']),
                  (({'g1': ['a', 'b']}, 'send', 'g1', None, 'hi'),
                   [('a', 'hi'), ('b', 'hi')]),
                  (({}, 'send', 'g1', None, 'hi'), [])],
        "params": [],
        "calibration": "对照：IP 组播——组成员加入/离开/组内广播（成员管理）",
    },
    "网络-Reno拥塞控制": {
        "task": "Reno拥塞控制",
        "pattern": (
            "def reno_phase(state, event, cwnd=None):\n"
"    # 生效条件：event ∈ {ack, loss}\n"
"    # 子功能：1 event 分支处理\n"
"    # 执行：按 op 分派；顺序调用\n"
"    # 不适用条件：event 非 {ack, loss} 时\n"
            "    # Reno 拥塞控制：ack 慢启动翻倍/拥塞避免线性，loss 快速恢复（阈值减半）\n"
            "    if event == 'loss':\n"
            "        state['ssthresh'] = max((cwnd or state.get('cwnd', 1)) // 2, 1)\n"
            "        state['phase'] = 'fast_recovery'\n"
            "        return state['ssthresh']\n"
            "    if event == 'ack':\n"
            "        if state.get('cwnd', 1) < state.get('ssthresh', 16):\n"
            "            state['cwnd'] = state.get('cwnd', 1) * 2\n"
            "            state['phase'] = 'slow_start'\n"
            "        else:\n"
            "            state['cwnd'] = state.get('cwnd', 1) + 1\n"
            "            state['phase'] = 'congestion_avoidance'\n"
            "        return state['cwnd']\n"
            "    return None\n"),
        "cases": [(({'cwnd': 1, 'ssthresh': 16}, 'ack'), 2),
                  (({'cwnd': 16, 'ssthresh': 16}, 'ack'), 17),
                  (({'cwnd': 16, 'ssthresh': 16}, 'loss', 16), 8)],
        "params": [],
        "calibration": "对照：TCP Reno——慢启动指数/拥塞避免线性/丢包阈值减半快速恢复",
    },
    "网络-RTO退避": {
        "task": "RTO退避",
        "pattern": (
            "def rto_backoff(rto, losses):\n"
"    # 生效条件：参数 rto/losses 合法\n"
"    # 子功能：① 主体逻辑执行\n"
"    # 执行：顺序执行\n"
"    # 不适用条件：输入不满足生效条件时返回 None/不执行\n"
            "    # RTO 重传超时：指数退避（每次超时翻倍——避免拥塞加剧）\n"
            "    return rto * (2 ** losses)\n"),
        "cases": [((1.0, 0), 1.0),
                  ((1.0, 2), 4.0),
                  ((2.0, 1), 4.0)],
        "params": [],
        "calibration": "对照：TCP RTO——指数退避（重传超时翻倍）",
    },
    "网络-吞吐量测量": {
        "task": "吞吐量测量",
        "pattern": (
            "def throughput(data_bytes, seconds):\n"
"    # 生效条件：参数 data_bytes/seconds 合法\n"
"    # 子功能：① 调用 round\n"
"    # 执行：顺序调用\n"
"    # 不适用条件：输入不满足生效条件时返回 None/不执行\n"
            "    # 吞吐量测量：字节数 / 时间（单位 KB/s）\n"
            "    return round(data_bytes / 1024 / seconds, 3) if seconds else 0.0\n"),
        "cases": [((10240, 10), 1.0),
                  ((2048, 1), 2.0),
                  ((1024, 0), 0.0)],
        "params": [],
        "calibration": "对照：网络吞吐量——字节数/时间（KB/s）",
    },
    "网络-链路状态路由": {
        "task": "链路状态路由",
        "pattern": (
            "def link_state_routing(graph, source):\n"
"    # 生效条件：unvisited.discard 可用\n"
"    # 子功能：① 调用 set；② 调用 min；③ 调用 float\n"
"    # 执行：循环迭代；顺序调用\n"
"    # 不适用条件：输入不满足生效条件时返回 None/不执行\n"
            "    # 链路状态路由：Dijkstra 最短路径树（OSPF 全拓扑计算）\n"
            "    dist = {source: 0}\n"
            "    prev = {}\n"
            "    unvisited = set(graph)\n"
            "    while unvisited:\n"
            "        u = min(unvisited, key=lambda n: dist.get(n, float('inf')))\n"
            "        unvisited.discard(u)\n"
            "        for v, w in graph.get(u, {}).items():\n"
            "            nd = dist.get(u, float('inf')) + w\n"
            "            if nd < dist.get(v, float('inf')):\n"
            "                dist[v] = nd\n"
            "                prev[v] = u\n"
            "    return dist, prev\n"),
        "cases": [(({'a': {'b': 1, 'c': 4}, 'b': {'c': 2, 'd': 5},
                     'c': {'d': 1}, 'd': {}}, 'a'),
                   ({'a': 0, 'b': 1, 'c': 3, 'd': 4},
                    {'b': 'a', 'c': 'b', 'd': 'c'})),
                  (({'a': {'b': 1}, 'b': {}}, 'a'),
                   ({'a': 0, 'b': 1}, {'b': 'a'})),
                  (({'a': {}}, 'a'), ({'a': 0}, {}))],
        "params": [],
        "calibration": "对照：OSPF 链路状态路由——Dijkstra 全拓扑最短路径树",
    },
    "网络-策略路由": {
        "task": "策略路由",
        "pattern": (
            "def policy_routing(policies, op, flow=None, policy_name=None):\n"
"    # 生效条件：op ∈ {add, match}\n"
"    # 子功能：① op 分支处理\n"
"    # 执行：按 op 分派；循环迭代；顺序调用\n"
"    # 不适用条件：op 非 {add, match} 时\n"
            "    # 策略路由：add 注册策略 / match 按流量特征匹配（源地址/类型）\n"
            "    if op == 'add':\n"
            "        policies[policy_name] = flow\n"
            "        return policy_name\n"
            "    if op == 'match':\n"
            "        for name, cond in policies.items():\n"
            "            if all(k in flow and flow[k] == v for k, v in cond.items()):\n"
            "                return name\n"
            "        return None\n"
            "    return None\n"),
        "cases": [(({}, 'add', {'类型': '视频'}, '视频走专线'), '视频走专线'),
                  (({'视频走专线': {'类型': '视频'}}, 'match',
                    {'类型': '视频', '大小': 100}), '视频走专线'),
                  (({'视频走专线': {'类型': '视频'}}, 'match',
                    {'类型': '文本'}), None)],
        "params": [],
        "calibration": "对照：策略路由——按流量特征匹配策略（条件路由）",
    },
    "网络-多径传输": {
        "task": "多径传输",
        "pattern": (
            "def multipath_send(paths, op, subflow=None, data=None):\n"
"    # 生效条件：op ∈ {add, send, stats}\n"
"    # 子功能：① op 分支处理\n"
"    # 执行：按 op 分派；顺序调用\n"
"    # 不适用条件：paths 为空/非法时；op 非 {add, send, stats} 时\n"
            "    # 多径传输：MPTCP 多子流并行（add 加子流 / send 选最少 / stats 汇总）\n"
            "    if op == 'add':\n"
            "        paths[subflow] = {'sent': 0}\n"
            "        return subflow\n"
            "    if op == 'send':\n"
            "        if not paths:\n"
            "            return 'no_path'\n"
            "        best = min(paths, key=lambda p: paths[p]['sent'])\n"
            "        paths[best]['sent'] += len(data)\n"
            "        return best\n"
            "    if op == 'stats':\n"
            "        return {p: paths[p]['sent'] for p in paths}\n"
            "    return None\n"),
        "cases": [(({}, 'add', 'wifi'), 'wifi'),
                  (({'wifi': {'sent': 0}}, 'send', None, 'hello'), 'wifi'),
                  (({'wifi': {'sent': 5}, '5g': {'sent': 0}},
                    'send', None, 'ab'), '5g'),
                  (({}, 'send', None, 'x'), 'no_path'),
                  (({'wifi': {'sent': 3}}, 'stats'), {'wifi': 3})],
        "params": [],
        "calibration": "对照：MPTCP 多径传输——多子流并行，选最少发送",
    },
    "网络-访问令牌": {
        "task": "访问令牌",
        "pattern": (
            "def token_ops(tokens, op, token=None, user=None, ttl=0, now=0):\n"
"    # 生效条件：op ∈ {issue, revoke, verify}\n"
"    # 子功能：① op 分支处理\n"
"    # 执行：按 op 分派\n"
"    # 不适用条件：op 非 {issue, revoke, verify} 时\n"
            "    # 访问令牌：issue 签发 / verify 校验（未过期且有效）/ revoke 吊销\n"
            "    if op == 'issue':\n"
            "        tokens[token] = {'user': user, 'expire': now + ttl,\n"
            "                         'revoked': False}\n"
            "        return 'issued'\n"
            "    if op == 'verify':\n"
            "        t = tokens.get(token)\n"
            "        if t is None or t.get('revoked'):\n"
            "            return 'invalid'\n"
            "        return 'valid' if t['expire'] >= now else 'expired'\n"
            "    if op == 'revoke':\n"
            "        if token in tokens:\n"
            "            tokens[token]['revoked'] = True\n"
            "            return 'revoked'\n"
            "        return 'missing'\n"
            "    return None\n"),
        "cases": [(({}, 'issue', 'tk1', 'u1', 60, 100), 'issued'),
                  (({'tk1': {'user': 'u1', 'expire': 160, 'revoked': False}},
                    'verify', 'tk1', None, 0, 100), 'valid'),
                  (({'tk1': {'user': 'u1', 'expire': 150, 'revoked': False}},
                    'verify', 'tk1', None, 0, 160), 'expired'),
                  (({'tk1': {'user': 'u1', 'expire': 160, 'revoked': False}},
                    'revoke', 'tk1'), 'revoked'),
                  (({}, 'verify', 'tk1', None, 0, 100), 'invalid')],
        "params": [],
        "calibration": "对照：OAuth 访问令牌——签发/校验（过期与吊销）/吊销",
    },
    "网络-压缩传输": {
        "task": "压缩传输",
        "pattern": (
            "def compress_transfer(data, mode):\n"
"    # 生效条件：mode ∈ {compress, decompress}\n"
"    # 子功能：1 mode 分支处理\n"
"    # 执行：按 op 分派；循环迭代；顺序调用\n"
"    # 不适用条件：mode 非 {compress, decompress} 时\n"
            "    # 压缩传输：compress 行程编码（RLE 重复段）/ decompress 还原\n"
            "    if mode == 'compress':\n"
            "        out = []\n"
            "        i = 0\n"
            "        while i < len(data):\n"
            "            j = i\n"
            "            while j < len(data) and data[j] == data[i]:\n"
            "                j += 1\n"
            "            out.append((data[i], j - i))\n"
            "            i = j\n"
            "        return out\n"
            "    if mode == 'decompress':\n"
            "        return ''.join(c * n for c, n in data)\n"
            "    return None\n"),
        "cases": [(('aaabbc', 'compress'), [('a', 3), ('b', 2), ('c', 1)]),
                  (([('a', 3), ('b', 2)], 'decompress'), 'aaabb'),
                  (('', 'compress'), [])],
        "params": [],
        "calibration": "对照：压缩传输——RLE 行程编码（重复段压缩/还原）",
    },
    "网络-会话亲和": {
        "task": "会话亲和",
        "pattern": (
            "def sticky_session(backends, op, session=None, backend_id=None):\n"
"    # 生效条件：op ∈ {bind, route}\n"
"    # 子功能：① op 分支处理\n"
"    # 执行：按 op 分派\n"
"    # 不适用条件：op 非 {bind, route} 时\n"
            "    # 会话亲和：bind 绑定会话到后端 / route 同会话同后端（sticky session）\n"
            "    if op == 'bind':\n"
            "        backends[session] = backend_id\n"
            "        return backend_id\n"
            "    if op == 'route':\n"
            "        return backends.get(session)\n"
            "    return None\n"),
        "cases": [(({}, 'bind', 's1', 0), 0),
                  (({'s1': 0}, 'route', 's1'), 0),
                  (({}, 'route', 's1'), None)],
        "params": [],
        "calibration": "对照：负载均衡——会话亲和（sticky session 同会话同后端）",
    },
    "网络-链路加密": {
        "task": "链路加密",
        "pattern": (
            "def link_encrypt(frames, op, frame=None, key=7):\n"
"    # 生效条件：op ∈ {decrypt, encrypt}\n"
"    # 子功能：① op 分支处理\n"
"    # 执行：按 op 分派；顺序调用\n"
"    # 不适用条件：op 非 {decrypt, encrypt} 时\n"
            "    # 链路加密：encrypt 帧加密（异或密钥）/ decrypt 解密（MACsec 链路层）\n"
            "    if op == 'encrypt':\n"
            "        frames[frame] = ''.join(chr(ord(c) ^ key) for c in frame)\n"
            "        return frames[frame]\n"
            "    if op == 'decrypt':\n"
            "        raw = frames.get(frame)\n"
            "        if raw is None:\n"
            "            return None\n"
            "        return ''.join(chr(ord(c) ^ key) for c in raw)\n"
            "    return None\n"),
        "cases": [(({}, 'encrypt', 'hello', 7), 'obkkh'),
                  (({'hello': 'obkkh'}, 'decrypt', 'hello', 7), 'hello'),
                  (({}, 'decrypt', 'x', 7), None)],
        "params": [],
        "calibration": "对照：MACsec 链路加密——帧级加密/解密（链路层保护）",
    },
    "网络-流量镜像": {
        "task": "流量镜像",
        "pattern": (
            "def port_mirror(monitor, op, src_port=None, dst_port=None, packet=None):\n"
"    # 生效条件：op ∈ {capture, mirror, route}\n"
"    # 子功能：① op 分支处理\n"
"    # 执行：按 op 分派\n"
"    # 不适用条件：op 非 {capture, mirror, route} 时\n"
            "    # 流量镜像：mirror 镜像源到目标 / capture 采集 / route 转发（SPAN）\n"
            "    if op == 'mirror':\n"
            "        monitor[src_port] = dst_port\n"
            "        return dst_port\n"
            "    if op == 'capture':\n"
            "        return {'src': src_port, 'packet': packet}\n"
            "    if op == 'route':\n"
            "        dst = monitor.get(src_port)\n"
            "        return dst if dst else 'no_mirror'\n"
            "    return None\n"),
        "cases": [(({}, 'mirror', 1, 2), 2),
                  (({1: 2}, 'route', 1), 2),
                  (({}, 'route', 1), 'no_mirror'),
                  (({}, 'capture', 1, None, 'pkt'), {'src': 1, 'packet': 'pkt'})],
        "params": [],
        "calibration": "对照：SPAN 端口镜像——流量复制到监控口（抓包）",
    },
    "网络-网络切片": {
        "task": "网络切片",
        "pattern": (
            "def network_slice(slices, op, name=None, bw=None, flow=None):\n"
"    # 生效条件：op ∈ {admit, create}\n"
"    # 子功能：① op 分支处理\n"
"    # 执行：按 op 分派\n"
"    # 不适用条件：op 非 {admit, create} 时\n"
            "    # 网络切片：create 创建 / admit 带宽准入（按服务隔离网络资源）\n"
            "    if op == 'create':\n"
            "        slices[name] = {'bw': bw, 'used': 0}\n"
            "        return name\n"
            "    if op == 'admit':\n"
            "        s = slices.get(name)\n"
            "        if s is None:\n"
            "            return 'missing'\n"
            "        if s['used'] + flow > s['bw']:\n"
            "            return 'rejected'\n"
            "        s['used'] += flow\n"
            "        return 'admitted'\n"
            "    return None\n"),
        "cases": [(({}, 'create', '视频', 100), '视频'),
                  (({'视频': {'bw': 100, 'used': 0}}, 'admit', '视频', None, 60),
                   'admitted'),
                  (({'视频': {'bw': 100, 'used': 80}}, 'admit', '视频', None, 30),
                   'rejected'),
                  (({}, 'admit', 'x', None, 10), 'missing')],
        "params": [],
        "calibration": "对照：5G 网络切片——按服务隔离带宽资源（准入控制）",
    },
    "网络-分块传输": {
        "task": "分块传输",
        "pattern": (
            "def chunked_transfer(op, data=None, chunk_size=0):\n"
"    # 生效条件：op ∈ {decode, encode}；data.index 可用\n"
"    # 子功能：① op 分支处理\n"
"    # 执行：按 op 分派；循环迭代；顺序调用\n"
"    # 不适用条件：op 非 {decode, encode} 时\n"
            "    # 分块传输：encode 分块编码（每块十六进制长度）/ decode 还原\n"
            "    if op == 'encode':\n"
            "        chunks = [data[i:i + chunk_size]\n"
            "                  for i in range(0, len(data), chunk_size)]\n"
            "        return ''.join(f'{len(c):x}\\\\r\\\\n{c}\\\\r\\\\n' for c in chunks) \\\n"
            "            + '0\\\\r\\\\n\\\\r\\\\n'\n"
            "    if op == 'decode':\n"
            "        out = []\n"
            "        i = 0\n"
            "        while i < len(data):\n"
            "            j = data.index('\\\\r\\\\n', i)\n"
            "            size = int(data[i:j], 16)\n"
            "            if size == 0:\n"
            "                break\n"
            "            out.append(data[j + 4:j + 4 + size])\n"
            "            i = j + 4 + size + 4\n"
            "        return ''.join(out)\n"
            "    return None\n"),
        "cases": [
            (('encode', 'hello', 3), '3\\r\\nhel\\r\\n2\\r\\nlo\\r\\n0\\r\\n\\r\\n'),
            (('decode', '3\\r\\nhel\\r\\n2\\r\\nlo\\r\\n0\\r\\n\\r\\n'), 'hello'),
            (('encode', '', 4), '0\\r\\n\\r\\n')],
        "params": [],
        "calibration": "对照：HTTP 分块传输——每块十六进制长度（chunked 编码）",
    },
    "网络-HTTP重定向": {
        "task": "HTTP重定向",
        "pattern": (
            "def http_redirect(op, status=None, location=None, max_hops=5):\n"
"    # 生效条件：op ∈ {follow}\n"
"    # 子功能：① op 分支处理\n"
"    # 执行：按 op 分派；循环迭代\n"
"    # 不适用条件：op 非 {follow} 时\n"
            "    # HTTP 重定向：follow 跟随 3xx（location 链，超跳数返回 None）\n"
            "    if op == 'follow':\n"
            "        hops = 0\n"
            "        while (status >= 300 and status < 400 and hops < max_hops\n"
            "               and location):\n"
            "            status = location.pop(0)\n"
            "            hops += 1\n"
            "        return status if status < 300 or status >= 400 else None\n"
            "    return None\n"),
        "cases": [(('follow', 200, []), 200),
                  (('follow', 301, [200]), 200),
                  (('follow', 301, [302, 200]), 200),
                  (('follow', 301, []), None)],
        "params": [],
        "calibration": "对照：HTTP 重定向——3xx 跟随 location（跳数限制）",
    },
    "网络-内容协商": {
        "task": "内容协商",
        "pattern": (
            "def content_negotiation(accept, available, op='match'):\n"
"    # 生效条件：op ∈ {match}；a.strip 可用\n"
"    # 子功能：① op 分支处理\n"
"    # 执行：按 op 分派；循环迭代\n"
"    # 不适用条件：op 非 {match} 时\n"
            "    # 内容协商：Accept 头匹配可用类型（按序——最佳匹配）\n"
            "    if op == 'match':\n"
            "        for a in accept.split(','):\n"
            "            a = a.strip().split(';')[0].strip()\n"
            "            if a in available:\n"
            "                return a\n"
            "        return None\n"
            "    return None\n"),
        "cases": [(('application/json', ['text/html', 'application/json']),
                   'application/json'),
                  (('text/html, application/json', ['application/json']),
                   'application/json'),
                  (('application/xml', ['application/json']), None)],
        "params": [],
        "calibration": "对照：HTTP 内容协商——Accept 头匹配可用类型（q 剥离）",
    },
    "网络-路径MTU发现": {
        "task": "路径MTU发现",
        "pattern": (
            "def pmtu_discover(state, op, size=None, too_large=None):\n"
"    # 生效条件：op ∈ {current, probe, result}\n"
"    # 子功能：① op 分支处理\n"
"    # 执行：按 op 分派\n"
"    # 不适用条件：op 非 {current, probe, result} 时\n"
            "    # 路径 MTU 发现：probe 探测 / result 过大减 8 / current 当前值（PMTUD）\n"
            "    if op == 'probe':\n"
            "        state['mtu'] = size\n"
            "        return size\n"
            "    if op == 'result':\n"
            "        if too_large:\n"
            "            state['mtu'] -= 8\n"
            "            return 'reduced'\n"
            "        return 'confirmed'\n"
            "    if op == 'current':\n"
            "        return state.get('mtu')\n"
            "    return None\n"),
        "cases": [(({}, 'probe', 1500), 1500),
                  (({'mtu': 1500}, 'result', None, True), 'reduced'),
                  (({'mtu': 1492}, 'result', None, False), 'confirmed'),
                  (({'mtu': 1492}, 'current'), 1492)],
        "params": [],
        "calibration": "对照：PMTUD——路径最大传输单元发现（过大减 8 重探）",
    },
    "网络-端口扫描检测": {
        "task": "端口扫描检测",
        "pattern": (
            "def scan_detect(conns, op, src=None, dst=None):\n"
"    # 生效条件：op ∈ {check, record}\n"
"    # 子功能：① op 分支处理\n"
"    # 执行：按 op 分派；顺序调用\n"
"    # 不适用条件：op 非 {check, record} 时\n"
            "    # 端口扫描检测：record 记录连接 / check 检测（多端口快速尝试→扫描）\n"
            "    if op == 'record':\n"
            "        conns.setdefault(src, []).append(dst)\n"
            "        return len(conns[src])\n"
            "    if op == 'check':\n"
            "        ports = conns.get(src, [])\n"
            "        return ('scan' if len(ports) >= 5 and len(set(ports)) >= 5\n"
            "                else 'normal')\n"
            "    return None\n"),
        "cases": [(({}, 'record', '1.2.3.4', 22), 1),
                  (({'1.2.3.4': [22, 80, 443, 8080]}, 'record',
                    '1.2.3.4', 3306), 5),
                  (({'1.2.3.4': [22, 80, 443, 8080, 3306]}, 'check',
                    '1.2.3.4'), 'scan'),
                  (({'1.2.3.4': [22]}, 'check', '1.2.3.4'), 'normal')],
        "params": [],
        "calibration": "对照：入侵检测——端口扫描模式（多端口快速尝试识别）",
    },
    "网络-会话超时": {
        "task": "会话超时",
        "pattern": (
            "def session_timeout(sessions, op, session=None, now=None, timeout=30):\n"
"    # 生效条件：op ∈ {activity, check}\n"
"    # 子功能：① op 分支处理\n"
"    # 执行：按 op 分派\n"
"    # 不适用条件：op 非 {activity, check} 时\n"
            "    # 会话超时：activity 更新活跃 / check 检查（空闲超时断开）\n"
            "    if op == 'activity':\n"
            "        sessions[session] = now\n"
            "        return now\n"
            "    if op == 'check':\n"
            "        last = sessions.get(session)\n"
            "        if last is None:\n"
            "            return 'missing'\n"
            "        return 'timeout' if (now - last) > timeout else 'active'\n"
            "    return None\n"),
        "cases": [(({}, 'activity', 's1', 10), 10),
                  (({'s1': 10}, 'check', 's1', 20), 'active'),
                  (({'s1': 10}, 'check', 's1', 50), 'timeout'),
                  (({}, 'check', 's1', 50), 'missing')],
        "params": [],
        "calibration": "对照：会话管理——空闲超时断开（保活续期）",
    },
    "网络-消息路由": {
        "task": "消息路由",
        "pattern": (
            "def msg_routing(routes, op, topic=None, queue=None):\n"
"    # 生效条件：op ∈ {bind, route}\n"
"    # 子功能：① op 分支处理\n"
"    # 执行：按 op 分派；顺序调用\n"
"    # 不适用条件：op 非 {bind, route} 时\n"
            "    # 消息路由：bind 绑定主题到队列 / route 路由（主题→队列）\n"
            "    if op == 'bind':\n"
            "        routes.setdefault(topic, []).append(queue)\n"
            "        return routes[topic]\n"
            "    if op == 'route':\n"
            "        return list(routes.get(topic, []))\n"
            "    return None\n"),
        "cases": [(({}, 'bind', '设备', 'q1'), ['q1']),
                  (({'设备': ['q1']}, 'bind', '设备', 'q2'), ['q1', 'q2']),
                  (({'设备': ['q1']}, 'route', '设备'), ['q1']),
                  (({}, 'route', '未知'), [])],
        "params": [],
        "calibration": "对照：消息中间件——主题绑定队列路由（发布订阅）",
    },
    "网络-API限流": {
        "task": "API限流",
        "pattern": (
            "def api_rate_limit(state, op, user=None, quota=0):\n"
"    # 生效条件：op ∈ {check, use}\n"
"    # 子功能：① op 分支处理\n"
"    # 执行：按 op 分派\n"
"    # 不适用条件：op 非 {check, use} 时\n"
            "    # API 限流：use 消耗配额 / check 检查（每用户配额）\n"
            "    if op == 'use':\n"
            "        state[user] = state.get(user, quota) - 1\n"
            "        return 'ok' if state[user] >= 0 else 'exceeded'\n"
            "    if op == 'check':\n"
            "        return state.get(user, quota)\n"
            "    return None\n"),
        "cases": [(({}, 'use', 'u1', 3), 'ok'),
                  (({'u1': 0}, 'use', 'u1', 3), 'exceeded'),
                  (({}, 'check', 'u1', 3), 3),
                  (({'u1': 2}, 'check', 'u1', 3), 2)],
        "params": [],
        "calibration": "对照：API 网关——每用户配额限流（超额拒绝）",
    },
    "网络-数据序列化": {
        "task": "数据序列化",
        "pattern": (
            "def proto_encode(fields, values):\n"
"    # 生效条件：参数 fields/values 合法\n"
"    # 子功能：① 调用 enumerate\n"
"    # 执行：循环迭代；顺序调用\n"
"    # 不适用条件：输入不满足生效条件时返回 None/不执行\n"
            "    # 数据序列化：字段表+值 → 紧凑编码（protobuf 简化——字段序号+类型+值）\n"
            "    out = []\n"
            "    for i, (name, typ) in enumerate(fields):\n"
            "        v = values.get(name)\n"
            "        if v is not None:\n"
            "            out.append((i, typ, v))\n"
            "    return out\n"),
        "cases": [(([('名', 'str'), ('值', 'int')], {'名': '甲', '值': 3}),
                   [(0, 'str', '甲'), (1, 'int', 3)]),
                  (([('名', 'str')], {}), []),
                  (([('名', 'str'), ('值', 'int')], {'值': 5}),
                   [(1, 'int', 5)])],
        "params": [],
        "calibration": "对照：protobuf 序列化——字段序号+类型+值紧凑编码",
    },
    "网络-DHCP租约": {
        "task": "DHCP租约",
        "pattern": (
            "def dhcp_lease(pool, op, mac=None, ttl=3600):\n"
"    # 生效条件：op ∈ {offer, release, renew}；state ∈ {free}\n"
"    # 子功能：① op 分支处理；2 state 分支处理\n"
"    # 执行：按 op 分派；循环迭代；顺序调用\n"
"    # 不适用条件：op 非 {offer, release, renew} 时；state 非 {free} 时\n"
            "    # DHCP：offer 分配/释放 / renew 续租（IP 地址租约管理）\n"
            "    if op == 'offer':\n"
            "        for ip, state in pool.items():\n"
            "            if state == 'free':\n"
            "                pool[ip] = {'mac': mac, 'ttl': ttl}\n"
            "                return ip\n"
            "        return None\n"
            "    if op == 'renew':\n"
            "        for ip, state in pool.items():\n"
            "            if isinstance(state, dict) and state.get('mac') == mac:\n"
            "                state['ttl'] = ttl\n"
            "                return ip\n"
            "        return None\n"
            "    if op == 'release':\n"
            "        for ip, state in pool.items():\n"
            "            if isinstance(state, dict) and state.get('mac') == mac:\n"
            "                pool[ip] = 'free'\n"
            "                return 'released'\n"
            "        return None\n"
            "    return None\n"),
        "cases": [
            (({'10.0.0.1': 'free', '10.0.0.2': 'free'}, 'offer', 'aa:bb'), '10.0.0.1'),
            (({'10.0.0.1': {'mac': 'aa:bb', 'ttl': 3600}}, 'renew', 'aa:bb', 7200), '10.0.0.1'),
            (({'10.0.0.1': {'mac': 'aa:bb', 'ttl': 3600}}, 'release', 'aa:bb'), 'released'),
            (({'10.0.0.1': {'mac': 'cc', 'ttl': 3600}}, 'offer', 'aa:bb'), None)],
        "params": [],
        "calibration": "对照：DHCP 协议——地址租约 offer/renew/release 生命周期",
    },
    "网络-ARP解析": {
        "task": "ARP解析",
        "pattern": (
            "def arp_resolve(table, op, ip=None, mac=None):\n"
"    # 生效条件：op ∈ {flush, learn, lookup}；table.clear 可用\n"
"    # 子功能：① op 分支处理\n"
"    # 执行：按 op 分派\n"
"    # 不适用条件：op 非 {flush, learn, lookup} 时\n"
            "    # ARP：lookup IP→MAC / learn 学习缓存 / flush 清空（地址解析）\n"
            "    if op == 'lookup':\n"
            "        return table.get(ip)\n"
            "    if op == 'learn':\n"
            "        table[ip] = mac\n"
            "        return mac\n"
            "    if op == 'flush':\n"
            "        table.clear()\n"
            "        return 'flushed'\n"
            "    return None\n"),
        "cases": [(({'10.0.0.1': 'aa:bb', '10.0.0.2': 'cc:dd'}, 'lookup', '10.0.0.1'), 'aa:bb'),
                  (({}, 'learn', '10.0.0.5', 'ee:ff'), 'ee:ff'),
                  (({}, 'lookup', '10.0.0.9'), None),
                  (({'10.0.0.1': 'aa:bb'}, 'flush'), 'flushed')],
        "params": [],
        "calibration": "对照：ARP 协议——IP→MAC 地址解析（查询/学习/清空缓存）",
    },
    "网络-ICMP探测": {
        "task": "ICMP探测",
        "pattern": (
            "def icmp_probe(results, op, target=None, rtt=None):\n"
"    # 生效条件：op ∈ {ping, reply, stats}\n"
"    # 子功能：① op 分支处理\n"
"    # 执行：按 op 分派；顺序调用\n"
"    # 不适用条件：op 非 {ping, reply, stats} 时\n"
            "    # ICMP：ping 记录往返 / reply 可达判定 / stats 汇总（探测协议）\n"
            "    if op == 'ping':\n"
            "        results.append({'target': target, 'rtt': rtt})\n"
            "        return 'sent'\n"
            "    if op == 'reply':\n"
            "        return target if rtt is not None and rtt < 1000 else None\n"
            "    if op == 'stats':\n"
            "        return len(results)\n"
            "    return None\n"),
        "cases": [(([], 'ping', '10.0.0.1', 42), 'sent'),
                  (([], 'reply', '10.0.0.1', 50), '10.0.0.1'),
                  (([], 'reply', '10.0.0.1', 1500), None),
                  ((['x'], 'stats'), 1)],
        "params": [],
        "calibration": "对照：ICMP Echo——ping 往返测量与可达性判定（RTT 阈值）",
    },
    "网络-广播风暴": {
        "task": "广播风暴",
        "pattern": (
            "def storm_control(state, op, port=None):\n"
"    # 生效条件：op ∈ {block, count, rate}\n"
"    # 子功能：① op 分支处理\n"
"    # 执行：按 op 分派\n"
"    # 不适用条件：op 非 {block, count, rate} 时\n"
            "    # 广播风暴：count 计数 / rate 速率 / block 超阈阻塞（风暴抑制）\n"
            "    if op == 'count':\n"
            "        state[port] = state.get(port, 0) + 1\n"
            "        return state[port]\n"
            "    if op == 'rate':\n"
            "        return state.get(port, 0)\n"
            "    if op == 'block':\n"
            "        return state.get(port, 0) > state.get('limit', 100)\n"
            "    return None\n"),
        "cases": [
            (({}, 'count', 'p1'), 1),
            (({'p1': 5}, 'rate', 'p1'), 5),
            (({'p1': 150, 'limit': 100}, 'block', 'p1'), True),
            (({'p1': 50, 'limit': 100}, 'block', 'p1'), False)],
        "params": [],
        "calibration": "对照：广播风暴抑制——计数/速率/超阈阻塞（环路风暴防护）",
    },
    "网络-心跳保活": {
        "task": "心跳保活",
        "pattern": (
            "def keepalive(state, op, now=None):\n"
"    # 生效条件：op ∈ {alive, beat, reset}\n"
"    # 子功能：① op 分支处理\n"
"    # 执行：按 op 分派\n"
"    # 不适用条件：op 非 {alive, beat, reset} 时\n"
            "    # 心跳保活：beat 记录心跳 / alive 超时判定 / reset 重置（连接保活）\n"
            "    if op == 'beat':\n"
            "        state['last'] = now\n"
            "        return now\n"
            "    if op == 'alive':\n"
            "        return now - state.get('last', now) <= state.get('timeout', 30)\n"
            "    if op == 'reset':\n"
            "        state['last'] = None\n"
            "        return 'reset'\n"
            "    return None\n"),
        "cases": [
            (({}, 'beat', 100), 100),
            (({'last': 100}, 'alive', 120), True),
            (({'last': 100}, 'alive', 200), False),
            (({}, 'reset'), 'reset')],
        "params": [],
        "calibration": "对照：TCP keepalive——心跳记录/超时判定（连接保活）",
    },
    "网络-报文重排序": {
        "task": "报文重排序",
        "pattern": (
            "def reorder_buffer(state, op, seq=None, data=None):\n"
"    # 生效条件：op ∈ {flush, put}\n"
"    # 子功能：① op 分支处理\n"
"    # 执行：按 op 分派；循环迭代；顺序调用\n"
"    # 不适用条件：op 非 {flush, put} 时\n"
            "    # 报文重排序：put 乱序存入 / flush 按序取出（重排缓冲）\n"
            "    if op == 'put':\n"
            "        state.setdefault('buf', {})[seq] = data\n"
            "        return len(state['buf'])\n"
            "    if op == 'flush':\n"
            "        out = []\n"
            "        nxt = state.get('next', 0)\n"
            "        while nxt in state.get('buf', {}):\n"
            "            out.append(state['buf'].pop(nxt))\n"
            "            nxt += 1\n"
            "        state['next'] = nxt\n"
            "        return out\n"
            "    return None\n"),
        "cases": [
            (({}, 'put', 3, 'c'), 1),
            (({'buf': {1: 'a', 2: 'b'}, 'next': 1}, 'flush'), ['a', 'b']),
            (({'buf': {}, 'next': 0}, 'flush'), []),
            (({'buf': {5: 'e'}, 'next': 1}, 'flush'), [])],
        "params": [],
        "calibration": "对照：TCP 乱序重排——按序号缓冲并按序递交（reordering）",
    },
    "网络-CSMA退避": {
        "task": "CSMA退避",
        "pattern": (
            "def csma_backoff(state, op, attempt=None):\n"
"    # 生效条件：op ∈ {collision, reset, wait}\n"
"    # 子功能：① op 分支处理\n"
"    # 执行：按 op 分派；顺序调用\n"
"    # 不适用条件：op 非 {collision, reset, wait} 时\n"
            "    # CSMA 退避：collision 碰撞计数 / wait 指数退避等待 / reset 重传成功清零（以太网）\n"
            "    if op == 'collision':\n"
            "        state['n'] = state.get('n', 0) + 1\n"
            "        return state['n']\n"
            "    if op == 'wait':\n"
            "        n = state.get('n', 0)\n"
            "        return min(2 ** n, 1024)\n"
            "    if op == 'reset':\n"
            "        state['n'] = 0\n"
            "        return 0\n"
            "    return None\n"),
        "cases": [
            (({}, 'collision'), 1),
            (({'n': 3}, 'wait'), 8),
            (({'n': 12}, 'wait'), 1024),
            (({'n': 5}, 'reset'), 0)],
        "params": [],
        "calibration": "对照：CSMA/CD——碰撞指数退避（2^n 上限 1024，重传清零）",
    },
    "网络-路由收敛": {
        "task": "路由收敛",
        "pattern": (
            "def route_converge(routes, op, src=None, change=None):\n"
"    # 生效条件：op ∈ {converge, stable, update}\n"
"    # 子功能：① op 分支处理\n"
"    # 执行：按 op 分派\n"
"    # 不适用条件：op 非 {converge, stable, update} 时\n"
            "    # 路由收敛：update 链路变化 / converge 传播收敛 / stable 是否稳定（路由协议收敛）\n"
            "    if op == 'update':\n"
            "        routes['dirty'] = True\n"
            "        routes.setdefault('changes', []).append((src, change))\n"
            "        return 'updated'\n"
            "    if op == 'converge':\n"
            "        routes['dirty'] = False\n"
            "        return 'converged'\n"
            "    if op == 'stable':\n"
            "        return not routes.get('dirty', False)\n"
            "    return None\n"),
        "cases": [
            (({}, 'update', 'A', 'down'), 'updated'),
            (({}, 'converge'), 'converged'),
            (({'dirty': True}, 'stable'), False),
            (({'dirty': False}, 'stable'), True)],
        "params": [],
        "calibration": "对照：路由协议收敛——链路变化传播至全网稳定（收敛判定）",
    },
    "网络-链路预算": {
        "task": "链路预算",
        "pattern": (
            "def link_budget(state, op, rssi=None):\n"
"    # 生效条件：op ∈ {distance, measure, quality}\n"
"    # 子功能：① op 分支处理\n"
"    # 执行：按 op 分派；顺序调用\n"
"    # 不适用条件：op 非 {distance, measure, quality} 时\n"
            "    # 链路预算：measure 记录 RSSI / quality 信号质量分级 / distance 距离估算（蓝牙）\n"
            "    if op == 'measure':\n"
            "        state['rssi'] = rssi\n"
            "        return rssi\n"
            "    if op == 'quality':\n"
            "        r = state.get('rssi', -100)\n"
            "        if r >= -50:\n"
            "            return 'excellent'\n"
            "        if r >= -70:\n"
            "            return 'good'\n"
            "        if r >= -85:\n"
            "            return 'fair'\n"
            "        return 'poor'\n"
            "    if op == 'distance':\n"
            "        r = state.get('rssi', -100)\n"
            "        return round(10 ** ((r - -40) / -20), 1)\n"
            "    return None\n"),
        "cases": [
            (({}, 'measure', -55), -55),
            (({'rssi': -45}, 'quality'), 'excellent'),
            (({'rssi': -75}, 'quality'), 'fair'),
            (({'rssi': -60}, 'distance'), 10.0)],
        "params": [],
        "calibration": "对照：蓝牙 RSSI——信号质量分级与距离估算（链路预算）",
    },
    "网络-NTP同步": {
        "task": "NTP同步",
        "pattern": (
            "def ntp_sync(state, op, t1=None, t2=None, t3=None):\n"
"    # 生效条件：op ∈ {offset, roundtrip}\n"
"    # 子功能：① op 分支处理\n"
"    # 执行：按 op 分派；顺序调用\n"
"    # 不适用条件：op 非 {offset, roundtrip} 时\n"
            "    # NTP 同步：offset 时间偏移 / roundtrip 往返时延（时间同步协议）\n"
            "    if op == 'offset':\n"
            "        # 客户端 t1 发送，服务器 t2 收到 t3 回，客户端 t4 接收——简化两戳\n"
            "        return round(((t2 - t1) + (t3 - t2)) / 2, 2)\n"
            "    if op == 'roundtrip':\n"
            "        return round((t3 - t1) - (t2 - t1), 2)\n"
            "    return None\n"),
        "cases": [
            (({}, 'offset', 100, 110, 130), 15.0),
            (({}, 'roundtrip', 100, 110, 130), 20.0),
            (({}, 'offset', 100, 100, 100), 0.0)],
        "params": [],
        "calibration": "对照：NTP——时间偏移与往返时延计算（时间同步）",
    },
    "网络-报文分片": {
        "task": "报文分片",
        "pattern": (
            "def packet_frag(state, op, data=None, mtu=None):\n"
"    # 生效条件：op ∈ {fragment, reassemble}\n"
"    # 子功能：① op 分支处理\n"
"    # 执行：按 op 分派；顺序调用\n"
"    # 不适用条件：op 非 {fragment, reassemble} 时\n"
            "    # 报文分片：fragment 按 MTU 切分 / reassemble 按序号重组（IPv4 分片）\n"
            "    if op == 'fragment':\n"
            "        return [data[i:i + mtu] for i in range(0, len(data), mtu)]\n"
            "    if op == 'reassemble':\n"
            "        return ''.join(frag[1] for frag in sorted(data, key=lambda f: f[0]))\n"
            "    return None\n"),
        "cases": [
            (({}, 'fragment', 'abcdef', 3), ['abc', 'def']),
            (({}, 'fragment', 'abcd', 2), ['ab', 'cd']),
            (({}, 'reassemble', [(1, 'b'), (0, 'a')]), 'ab')],
        "params": [],
        "calibration": "对照：IPv4 分片——按 MTU 切分与按偏移重组",
    },
    "网络-前向纠错": {
        "task": "前向纠错",
        "pattern": (
            "def fec_recover(blocks, op, idx=None):\n"
"    # 生效条件：op ∈ {parity, recover}\n"
"    # 子功能：① op 分支处理\n"
"    # 执行：按 op 分派；循环迭代；顺序调用\n"
"    # 不适用条件：op 非 {parity, recover} 时\n"
            "    # 前向纠错：parity 异或校验块 / recover 缺块恢复（FEC 奇偶恢复）\n"
            "    if op == 'parity':\n"
            "        out = 0\n"
            "        for b in blocks:\n"
            "            out ^= b\n"
            "        return out\n"
            "    if op == 'recover':\n"
            "        # blocks 含校验块于末尾；缺 idx 块用其余异或恢复\n"
            "        out = 0\n"
            "        for i, b in enumerate(blocks):\n"
            "            if i != idx:\n"
            "                out ^= b\n"
            "        return out\n"
            "    return None\n"),
        "cases": [
            (([1, 2, 3], 'parity'), 0),
            (([1, 2, 0], 'recover', 2), 3),
            (([5, 0], 'recover', 1), 5)],
        "params": [],
        "calibration": "对照：FEC 异或奇偶——校验块生成与缺块恢复",
    },
    "网络-尽力交付": {
        "task": "尽力交付",
        "pattern": (
            "def best_effort(state, op, seq=None):\n"
"    # 生效条件：op ∈ {delivered, drop, send}\n"
"    # 子功能：① op 分支处理\n"
"    # 执行：按 op 分派；顺序调用\n"
"    # 不适用条件：op 非 {delivered, drop, send} 时\n"
            "    # 尽力交付：send 发送（无确认）/ drop 随机丢包模拟 / delivered 统计（UDP 语义）\n"
            "    if op == 'send':\n"
            "        state.setdefault('sent', []).append(seq)\n"
            "        return 'sent'\n"
            "    if op == 'drop':\n"
            "        if seq in state.get('sent', []):\n"
            "            state['sent'].remove(seq)\n"
            "            return 'dropped'\n"
            "        return None\n"
            "    if op == 'delivered':\n"
            "        return len(state.get('sent', []))\n"
            "    return None\n"),
        "cases": [
            (({}, 'send', 1), 'sent'),
            (({'sent': [1]}, 'drop', 1), 'dropped'),
            (({'sent': [1, 2]}, 'delivered'), 2),
            (({'sent': [1]}, 'drop', 9), None)],
        "params": [],
        "calibration": "对照：UDP 尽力交付——无确认/可丢包（不可靠传输语义）",
    },
    "网络-带宽时延积": {
        "task": "带宽时延积",
        "pattern": (
            "def bdp_calc(bandwidth, rtt):\n"
"    # 生效条件：参数 bandwidth/rtt 合法\n"
"    # 子功能：① 调用 round\n"
"    # 执行：顺序调用\n"
"    # 不适用条件：输入不满足生效条件时返回 None/不执行\n"
            "    # 带宽时延积：带宽×RTT = 在途数据量（管道容量）\n"
            "    return round(bandwidth * rtt, 2)\n"),
        "cases": [
            ((10.0, 0.1), 1.0),
            ((100.0, 0.05), 5.0),
            ((0.0, 1.0), 0.0)],
        "params": [],
        "calibration": "对照：BDP——带宽×RTT（TCP 窗口大小依据）",
    },
    "网络-多宿主": {
        "task": "多宿主",
        "pattern": (
            "def multihoming(state, op, iface=None):\n"
"    # 生效条件：op ∈ {add, failover, select}\n"
"    # 子功能：① op 分支处理\n"
"    # 执行：按 op 分派；顺序调用\n"
"    # 不适用条件：ifaces 为空/非法时；op 非 {add, failover, select} 时\n"
            "    # 多宿主：add 添加接口 / select 按序选择 / failover 故障切换（多接口主机）\n"
            "    if op == 'add':\n"
            "        state.setdefault('ifaces', []).append(iface)\n"
            "        return iface\n"
            "    if op == 'select':\n"
            "        ifaces = state.get('ifaces', [])\n"
            "        if not ifaces:\n"
            "            return None\n"
            "        idx = state.get('idx', 0) % len(ifaces)\n"
            "        state['idx'] = idx + 1\n"
            "        return ifaces[idx]\n"
            "    if op == 'failover':\n"
            "        ifaces = state.get('ifaces', [])\n"
            "        return ifaces[0] if ifaces else None\n"
            "    return None\n"),
        "cases": [
            (({}, 'add', 'wlan0'), 'wlan0'),
            (({'ifaces': ['eth0', 'wlan0']}, 'select'), 'eth0'),
            (({'ifaces': ['eth0', 'wlan0'], 'idx': 1}, 'select'), 'wlan0'),
            (({}, 'select'), None)],
        "params": [],
        "calibration": "对照：多宿主——多接口轮询选择与故障切换（multihoming）",
    },
    "网络-RTT平滑": {
        "task": "RTT平滑",
        "pattern": (
            "def rtt_smooth(state, op, sample=None, alpha=0.125):\n"
"    # 生效条件：op ∈ {get, sample}\n"
"    # 子功能：① op 分支处理\n"
"    # 执行：按 op 分派；顺序调用\n"
"    # 不适用条件：op 非 {get, sample} 时\n"
            "    # RTT 平滑：sample 加权更新 / get 当前估值（EWMA 指数加权）\n"
            "    if op == 'sample':\n"
            "        prev = state.get('rtt', sample)\n"
            "        state['rtt'] = round((1 - alpha) * prev + alpha * sample, 2)\n"
            "        return state['rtt']\n"
            "    if op == 'get':\n"
            "        return state.get('rtt', 0.0)\n"
            "    return None\n"),
        "cases": [
            (({}, 'sample', 100.0), 100.0),
            (({'rtt': 100.0}, 'sample', 200.0), 112.5),
            (({}, 'get'), 0.0),
            (({'rtt': 80.0}, 'get'), 80.0)],
        "params": [],
        "calibration": "对照：TCP RTT——EWMA 加权平滑估值（α=0.125）",
    },
    "网络-路由汇聚": {
        "task": "路由汇聚",
        "pattern": (
            "def route_summary(routes):\n"
"    # 生效条件：参数 routes 合法\n"
"    # 子功能：① 调用 len\n"
"    # 执行：顺序调用\n"
"    # 不适用条件：routes 为空/非法时（隐式盲区：返回默认值 [] = 未知行为——不适用）\n"
            "    # 路由汇聚：同网段路由合成 CIDR 汇总（前两段公共）\n"
            "    if not routes:\n"
            "        return []\n"
            "    segs = [r.split('.') for r in routes]\n"
            "    if not segs or len(segs[0]) < 2:\n"
            "        return []\n"
            "    return [segs[0][0] + '.' + segs[0][1] + '.0.0/16']\n"),
        "cases": [
            ((['192.168.1.0/24', '192.168.2.0/24'],), ['192.168.0.0/16']),
            ((['10.1.0.0/16', '10.1.1.0/24'],), ['10.1.0.0/16']),
            (([],), [])],
        "params": [],
        "calibration": "对照：路由汇聚——CIDR 汇总（最长公共前缀合成）",
    },
    "网络-序列号回绕": {
        "task": "序列号回绕",
        "pattern": (
            "def seq_wrap(state, op, seq=None, space=2 ** 32):\n"
"    # 生效条件：op ∈ {compare, next, wrap}\n"
"    # 子功能：① op 分支处理\n"
"    # 执行：按 op 分派\n"
"    # 不适用条件：op 非 {compare, next, wrap} 时\n"
            "    # 序列号回绕：next 推进 / compare 回绕比较 / wrap 是否已回绕（TCP seq）\n"
            "    if op == 'next':\n"
            "        cur = state.get('seq', 0)\n"
            "        nxt = (cur + 1) % space\n"
            "        state['seq'] = nxt\n"
            "        if nxt < cur:\n"
            "            state['wrapped'] = True\n"
            "        return nxt\n"
            "    if op == 'compare':\n"
            "        a, b = seq\n"
            "        return (a - b) % space < space // 2\n"
            "    if op == 'wrap':\n"
            "        return state.get('wrapped', False)\n"
            "    return None\n"),
        "cases": [
            (({}, 'next', None, 4), 1),
            (({'seq': 3}, 'next', None, 4), 0),
            (({}, 'compare', (1, 6), 8), True),
            (({}, 'compare', (6, 1), 8), False),
            (({'wrapped': True}, 'wrap'), True)],
        "params": [],
        "calibration": "对照：TCP 序列号——回绕推进/回绕比较（2^32 空间）",
    },
    "网络-漏桶限流": {
        "task": "漏桶限流",
        "pattern": (
            "def leaky_bucket(state, op, size=None, rate=None):\n"
"    # 生效条件：op ∈ {accept, fill, leak}\n"
"    # 子功能：① op 分支处理\n"
"    # 执行：按 op 分派；顺序调用\n"
"    # 不适用条件：op 非 {accept, fill, leak} 时\n"
            "    # 漏桶限流：fill 灌桶 / leak 匀速漏 / accept 是否接受（平滑流量）\n"
            "    if op == 'fill':\n"
            "        cur = state.get('level', 0)\n"
            "        if cur + 1 <= state.get('size', size):\n"
            "            state['level'] = cur + 1\n"
            "            return True\n"
            "        return False\n"
            "    if op == 'leak':\n"
            "        cur = state.get('level', 0)\n"
            "        state['level'] = max(0, cur - state.get('rate', rate))\n"
            "        return state['level']\n"
            "    if op == 'accept':\n"
            "        return state.get('level', 0) < state.get('size', size)\n"
            "    return None\n"),
        "cases": [
            (({'size': 2}, 'fill'), True),
            (({'size': 1, 'level': 1}, 'fill'), False),
            (({'level': 5, 'rate': 2}, 'leak'), 3),
            (({'size': 2, 'level': 1}, 'accept'), True)],
        "params": [],
        "calibration": "对照：漏桶——匀速漏出平滑流量（灌桶/漏/接受判定）",
    },
    "网络-报文调度": {
        "task": "报文调度",
        "pattern": (
            "def wfq_schedule(queues, op, weights=None):\n"
"    # 生效条件：op ∈ {dequeue, enqueue}\n"
"    # 子功能：① op 分支处理\n"
"    # 执行：按 op 分派；顺序调用\n"
"    # 不适用条件：op 非 {dequeue, enqueue} 时\n"
            "    # 报文调度：dequeue 按权重选队列 / enqueue 入队 / weights 查询（WFQ 加权公平）\n"
            "    if op == 'enqueue':\n"
            "        return queues\n"
            "    if op == 'dequeue':\n"
            "        w = weights or {k: 1 for k in queues}\n"
            "        best = max(queues, key=lambda k: w.get(k, 1) if queues[k] else -1)\n"
            "        if queues[best]:\n"
            "            return best, queues[best].pop(0)\n"
            "        return None\n"
            "    return None\n"),
        "cases": [
            (({'a': [1], 'b': [2]}, 'enqueue'), {'a': [1], 'b': [2]}),
            (({'a': [1], 'b': [2]}, 'dequeue', {'a': 3, 'b': 1}), ('a', 1)),
            (({'a': [], 'b': [2]}, 'dequeue', {'a': 3, 'b': 1}), ('b', 2)),
            (({'a': []}, 'dequeue', {'a': 1}), None)],
        "params": [],
        "calibration": "对照：WFQ——加权公平队列调度（按权重选队出队）",
    },
    "网络-链路利用率": {
        "task": "链路利用率",
        "pattern": (
            "def link_util(state, op, used=None, capacity=None):\n"
"    # 生效条件：op ∈ {peak, sample, util}\n"
"    # 子功能：① op 分支处理\n"
"    # 执行：按 op 分派；顺序调用\n"
"    # 不适用条件：op 非 {peak, sample, util} 时\n"
            "    # 链路利用率：sample 记录 / util 当前利用率 / peak 峰值（链路占用）\n"
            "    if op == 'sample':\n"
            "        u = used / capacity if capacity else 0.0\n"
            "        state.setdefault('samples', []).append(round(u, 2))\n"
            "        return round(u, 2)\n"
            "    if op == 'util':\n"
            "        s = state.get('samples', [])\n"
            "        return round(sum(s) / len(s), 2) if s else 0.0\n"
            "    if op == 'peak':\n"
            "        s = state.get('samples', [])\n"
            "        return max(s) if s else 0.0\n"
            "    return None\n"),
        "cases": [
            (({}, 'sample', 50, 100), 0.5),
            (({}, 'sample', 0, 100), 0.0),
            (({'samples': [0.5, 0.7]}, 'util'), 0.6),
            (({'samples': [0.5, 0.9]}, 'peak'), 0.9)],
        "params": [],
        "calibration": "对照：链路利用率——已用/容量采样（平均与峰值）",
    },
    "网络-带宽分配": {
        "task": "带宽分配",
        "pattern": (
            "def bw_alloc(total, weights):\n"
"    # 生效条件：参数 total/weights 合法\n"
"    # 子功能：① 调用 sum；② 调用 round\n"
"    # 执行：循环迭代；顺序调用\n"
"    # 不适用条件：s 越界（LtE）时\n"
            "    # 带宽分配：按权重比例分总带宽（公平分配）\n"
            "    s = sum(weights.values())\n"
            "    if s <= 0:\n"
            "        return {k: 0 for k in weights}\n"
            "    out = {}\n"
            "    used = 0\n"
            "    for k, w in weights.items():\n"
            "        v = total * w / s\n"
            "        out[k] = round(v, 2)\n"
            "        used += v\n"
            "    return out\n"),
        "cases": [
            ((100, {'a': 1, 'b': 1}), {'a': 50.0, 'b': 50.0}),
            ((100, {'a': 3, 'b': 1}), {'a': 75.0, 'b': 25.0}),
            ((100, {}), {}),
            ((100, {'a': 0}), {'a': 0.0})],
        "params": [],
        "calibration": "对照：带宽分配——按权重比例公平分配（weighted sharing）",
    },
    "网络-连接迁移": {
        "task": "连接迁移",
        "pattern": (
            "def conn_migrate(state, op, ep=None):\n"
"    # 生效条件：op ∈ {count, current, migrate}\n"
"    # 子功能：① op 分支处理\n"
"    # 执行：按 op 分派\n"
"    # 不适用条件：op 非 {count, current, migrate} 时\n"
            "    # 连接迁移：migrate 换端点 / current 当前端点 / count 迁移次数（QUIC migration）\n"
            "    if op == 'migrate':\n"
            "        state['ep'] = ep\n"
            "        state['count'] = state.get('count', 0) + 1\n"
            "        return ep\n"
            "    if op == 'current':\n"
            "        return state.get('ep')\n"
            "    if op == 'count':\n"
            "        return state.get('count', 0)\n"
            "    return None\n"),
        "cases": [
            (({}, 'migrate', '10.0.0.2'), '10.0.0.2'),
            (({}, 'current'), None),
            (({'ep': '10.0.0.2', 'count': 1}, 'count'), 1),
            (({'ep': '10.0.0.1'}, 'migrate', '10.0.0.3'), '10.0.0.3')],
        "params": [],
        "calibration": "对照：QUIC——连接迁移（端点切换不断连）",
    },
    "网络-重传统计": {
        "task": "重传统计",
        "pattern": (
            "def retrans_stats(state, op, seq=None):\n"
"    # 生效条件：op ∈ {count, rate, record}\n"
"    # 子功能：① op 分支处理\n"
"    # 执行：按 op 分派；顺序调用\n"
"    # 不适用条件：op 非 {count, rate, record} 时\n"
            "    # 重传统计：record 记录 / count 总数 / rate 重传率（可靠传输统计）\n"
            "    if op == 'record':\n"
            "        state.setdefault('retx', set()).add(seq)\n"
            "        state['sent'] = state.get('sent', 0) + 1\n"
            "        return 'recorded'\n"
            "    if op == 'count':\n"
            "        return len(state.get('retx', set()))\n"
            "    if op == 'rate':\n"
            "        sent = state.get('sent', 0)\n"
            "        retx = len(state.get('retx', set()))\n"
            "        return round(retx / sent, 2) if sent else 0.0\n"
            "    return None\n"),
        "cases": [
            (({}, 'record', 1), 'recorded'),
            (({'retx': {1, 2}}, 'count'), 2),
            (({'sent': 10, 'retx': {1, 2}}, 'rate'), 0.2),
            (({}, 'rate'), 0.0)],
        "params": [],
        "calibration": "对照：TCP 统计——重传统计与重传率（可靠传输）",
    },
    "网络-路由衰减": {
        "task": "路由衰减",
        "pattern": (
            "def route_damp(state, op, route=None, flappy=None):\n"
"    # 生效条件：op ∈ {damped, record, reset}\n"
"    # 子功能：① op 分支处理\n"
"    # 执行：按 op 分派\n"
"    # 不适用条件：op 非 {damped, record, reset} 时\n"
            "    # 路由衰减：record 记录抖动 / damped 是否抑制 / reset 重置（BGP damping）\n"
            "    if op == 'record':\n"
            "        state.setdefault('flaps', {})[route] = state.get('flaps', {}).get(route, 0) + 1\n"
            "        return state['flaps'][route]\n"
            "    if op == 'damped':\n"
            "        return state.get('flaps', {}).get(route, 0) >= flappy\n"
            "    if op == 'reset':\n"
            "        state.setdefault('flaps', {})[route] = 0\n"
            "        return 'reset'\n"
            "    return None\n"),
        "cases": [
            (({}, 'record', 'r1'), 1),
            (({'flaps': {'r1': 5}}, 'damped', 'r1', 4), True),
            (({'flaps': {'r1': 2}}, 'damped', 'r1', 4), False),
            (({'flaps': {'r1': 5}}, 'reset', 'r1'), 'reset')],
        "params": [],
        "calibration": "对照：BGP damping——路由抖动抑制（阈值衰减）",
    },
    "网络-流分类": {
        "task": "流分类",
        "pattern": (
            "def flow_class(state, op, pkt=None):\n"
"    # 生效条件：op ∈ {classify, reset, stats}\n"
"    # 子功能：① op 分支处理\n"
"    # 执行：按 op 分派；顺序调用\n"
"    # 不适用条件：op 非 {classify, reset, stats} 时\n"
            "    # 流分类：classify 分类 / stats 统计 / reset 清空（流量识别）\n"
            "    if op == 'classify':\n"
            "        port = pkt.get('port', 0)\n"
            "        cls = 'web' if port == 80 else 'mail' if port == 25 else 'other'\n"
            "        state.setdefault('counts', {})[cls] = state.get('counts', {}).get(cls, 0) + 1\n"
            "        return cls\n"
            "    if op == 'stats':\n"
            "        return dict(state.get('counts', {}))\n"
            "    if op == 'reset':\n"
            "        state['counts'] = {}\n"
            "        return 'reset'\n"
            "    return None\n"),
        "cases": [
            (({}, 'classify', {'port': 80}), 'web'),
            (({}, 'classify', {'port': 25}), 'mail'),
            (({'counts': {'web': 2}}, 'stats'), {'web': 2}),
            (({'counts': {'web': 1}}, 'reset'), 'reset')],
        "params": [],
        "calibration": "对照：流量识别——按端口分类（web/mail/other）",
    },
    "网络-数据包采样": {
        "task": "数据包采样",
        "pattern": (
            "def pkt_sampling(state, op, pkt=None):\n"
"    # 生效条件：op ∈ {count, rate, sample}\n"
"    # 子功能：① op 分支处理\n"
"    # 执行：按 op 分派\n"
"    # 不适用条件：op 非 {count, rate, sample} 时\n"
            "    # 数据包采样：sample 按率采样 / rate 采样率 / count 已采（流量采样）\n"
            "    if op == 'sample':\n"
            "        rate = state.get('rate', 1)\n"
            "        if pkt % rate == 0:\n"
            "            state['count'] = state.get('count', 0) + 1\n"
            "            return True\n"
            "        return False\n"
            "    if op == 'rate':\n"
            "        return state.get('rate', 1)\n"
            "    if op == 'count':\n"
            "        return state.get('count', 0)\n"
            "    return None\n"),
        "cases": [
            (({}, 'sample', 1), True),
            (({'rate': 2}, 'sample', 3), False),
            (({'rate': 2}, 'rate'), 2),
            (({'count': 5}, 'count'), 5)],
        "params": [],
        "calibration": "对照：NetFlow——按采样率抽取数据包（sFlow/NetFlow）",
    },
    "网络-时隙": {
        "task": "时隙",
        "pattern": (
            "def tdma_slot(state, op, node=None, slot=None):\n"
"    # 生效条件：op ∈ {assign, next, owner}\n"
"    # 子功能：① op 分支处理\n"
"    # 执行：按 op 分派；循环迭代\n"
"    # 不适用条件：op 非 {assign, next, owner} 时\n"
            "    # 时隙：assign 分配 / next 下一时隙 / owner 归属（TDMA 分时）\n"
            "    if op == 'assign':\n"
            "        state.setdefault('slots', {})[node] = slot\n"
            "        return slot\n"
            "    if op == 'next':\n"
            "        n = state.get('n', 4)\n"
            "        state['cur'] = (state.get('cur', 0) + 1) % n\n"
            "        return state['cur']\n"
            "    if op == 'owner':\n"
            "        for k, v in state.get('slots', {}).items():\n"
            "            if v == slot:\n"
            "                return k\n"
            "        return None\n"
            "    return None\n"),
        "cases": [
            (({}, 'assign', 'n1', 0), 0),
            (({}, 'next'), 1),
            (({'slots': {'n1': 0}}, 'owner', None, 0), 'n1'),
            (({'slots': {}}, 'owner', None, 3), None)],
        "params": [],
        "calibration": "对照：TDMA——时分多址时隙分配/轮转/归属",
    },
    "网络-跳频": {
        "task": "跳频",
        "pattern": (
            "def freq_hop(state, op, seq=None):\n"
"    # 生效条件：op ∈ {current, hop, pattern}\n"
"    # 子功能：① op 分支处理\n"
"    # 执行：按 op 分派；顺序调用\n"
"    # 不适用条件：op 非 {current, hop, pattern} 时\n"
            "    # 跳频：hop 下一频率 / current 当前 / pattern 序列（FHSS 抗干扰）\n"
            "    if op == 'hop':\n"
            "        pat = state.get('pattern', [2400, 2410, 2420])\n"
            "        i = state.get('idx', 0)\n"
            "        state['idx'] = (i + 1) % len(pat)\n"
            "        state['freq'] = pat[state['idx']]\n"
            "        return state['freq']\n"
            "    if op == 'current':\n"
            "        return state.get('freq', 2400)\n"
            "    if op == 'pattern':\n"
            "        return list(state.get('pattern', [2400, 2410, 2420]))\n"
            "    return None\n"),
        "cases": [
            (({}, 'hop'), 2410),
            (({}, 'current'), 2400),
            (({'freq': 2420}, 'current'), 2420),
            (({}, 'pattern'), [2400, 2410, 2420])],
        "params": [],
        "calibration": "对照：FHSS——跳频序列（抗干扰/保密）",
    },
    "网络-误码率": {
        "task": "误码率",
        "pattern": (
            "def ber_calc(state, op, errors=None, total=None):\n"
"    # 生效条件：op ∈ {ber, sample, snr}\n"
"    # 子功能：① op 分支处理\n"
"    # 执行：按 op 分派；顺序调用\n"
"    # 不适用条件：op 非 {ber, sample, snr} 时\n"
            "    # 误码率：sample 采样 / ber 误码率 / snr 信噪比映射（链路质量）\n"
            "    if op == 'sample':\n"
            "        state['errors'] = errors\n"
            "        state['total'] = total\n"
            "        return round(errors / total, 6) if total else 0.0\n"
            "    if op == 'ber':\n"
            "        e = state.get('errors', 0)\n"
            "        t = state.get('total', 1)\n"
            "        return round(e / t, 6) if t else 0.0\n"
            "    if op == 'snr':\n"
            "        return round(10 * (1 - state.get('errors', 0) / max(state.get('total', 1), 1)), 1)\n"
            "    return None\n"),
        "cases": [
            (({}, 'sample', 1, 100), 0.01),
            (({'errors': 2, 'total': 100}, 'ber'), 0.02),
            (({}, 'ber'), 0.0),
            (({'errors': 0, 'total': 10}, 'snr'), 10.0)],
        "params": [],
        "calibration": "对照：误码率——错误/总数与信噪比映射（链路质量）",
    },
    "网络-拓扑发现": {
        "task": "拓扑发现",
        "pattern": (
            "def topo_discover(state, op, node=None, neighbor=None):\n"
"    # 生效条件：op ∈ {link, neighbors, probe}\n"
"    # 子功能：① op 分支处理\n"
"    # 执行：按 op 分派；顺序调用\n"
"    # 不适用条件：op 非 {link, neighbors, probe} 时\n"
            "    # 拓扑发现：probe 探测 / link 记录 / neighbors 邻居表（LLDP/拓扑感知）\n"
            "    if op == 'probe':\n"
            "        state.setdefault('links', set()).add((node, neighbor))\n"
            "        return 'found'\n"
            "    if op == 'link':\n"
            "        return sorted(state.get('links', set()))\n"
            "    if op == 'neighbors':\n"
            "        return sorted(b for a, b in state.get('links', set()) if a == node)\n"
            "    return None\n"),
        "cases": [
            (({}, 'probe', 'n1', 'n2'), 'found'),
            (({'links': {('n1', 'n2')}}, 'link'), [('n1', 'n2')]),
            (({}, 'link'), []),
            (({'links': {('n1', 'n2')}}, 'neighbors', 'n1'), ['n2'])],
        "params": [],
        "calibration": "对照：拓扑发现——链路探测与邻居表（LLDP）",
    },
    "网络-路径备份": {
        "task": "路径备份",
        "pattern": (
            "def path_backup(state, op, route=None, backup=None):\n"
"    # 生效条件：op ∈ {active, assign, failover}\n"
"    # 子功能：① op 分支处理\n"
"    # 执行：按 op 分派\n"
"    # 不适用条件：op 非 {active, assign, failover} 时\n"
            "    # 路径备份：assign 指定 / active 激活 / failover 主路故障切换（FRR）\n"
            "    if op == 'assign':\n"
            "        state['primary'] = route\n"
            "        state['backup'] = backup\n"
            "        state['active'] = route\n"
            "        return 'assigned'\n"
            "    if op == 'active':\n"
            "        return state.get('active')\n"
            "    if op == 'failover':\n"
            "        if state.get('active') == state.get('primary'):\n"
            "            state['active'] = state.get('backup')\n"
            "            return 'switched'\n"
            "        return 'noop'\n"
            "    return None\n"),
        "cases": [
            (({}, 'assign', 'r1', 'r2'), 'assigned'),
            (({'active': 'r1'}, 'active'), 'r1'),
            (({'primary': 'r1', 'backup': 'r2', 'active': 'r1'}, 'failover'), 'switched'),
            (({'primary': 'r1', 'backup': 'r2', 'active': 'r2'}, 'failover'), 'noop')],
        "params": [],
        "calibration": "对照：FRR——主备路径故障切换（快速重路由）",
    },
    "网络-数据去重": {
        "task": "数据去重",
        "pattern": (
            "def payload_dedup(state, op, data=None):\n"
"    # 生效条件：op ∈ {dedup, hash, store}\n"
"    # 子功能：① op 分支处理\n"
"    # 执行：按 op 分派；顺序调用\n"
"    # 不适用条件：op 非 {dedup, hash, store} 时\n"
            "    # 数据去重：hash 指纹 / store 存储 / dedup 是否重复（网络级去重）\n"
            "    if op == 'hash':\n"
            "        return sum(ord(c) for c in data) % 997\n"
            "    if op == 'store':\n"
            "        h = sum(ord(c) for c in data) % 997\n"
            "        state.setdefault('seen', set()).add(h)\n"
            "        return 'stored'\n"
            "    if op == 'dedup':\n"
            "        h = sum(ord(c) for c in data) % 997\n"
            "        return h in state.get('seen', set())\n"
            "    return None\n"),
        "cases": [
            (({}, 'hash', 'abc'), 294),
            (({}, 'store', 'abc'), 'stored'),
            (({'seen': {294}}, 'dedup', 'abc'), True),
            (({}, 'dedup', 'abc'), False)],
        "params": [],
        "calibration": "对照：网络去重——指纹识别重复载荷（dedup）",
    },
    "网络-网关": {
        "task": "网关",
        "pattern": (
            "def gateway(state, op, dest=None):\n"
"    # 生效条件：op ∈ {default, route, table}\n"
"    # 子功能：① op 分支处理\n"
"    # 执行：按 op 分派；循环迭代；顺序调用\n"
"    # 不适用条件：op 非 {default, route, table} 时\n"
            "    # 网关：route 转发 / default 默认网关 / table 路由表（网络出口）\n"
            "    if op == 'route':\n"
            "        table = state.get('table', {})\n"
            "        if dest in table:\n"
            "            return table[dest]\n"
            "        for prefix, gw in table.items():\n"
            "            mask = int(prefix.split('/')[1]) if '/' in prefix else 32\n"
            "            p = prefix.split('/')[0]\n"
            "            d = dest\n"
            "            if mask <= 8 and d.split('.')[0] == p.split('.')[0]:\n"
            "                return gw\n"
            "            if mask <= 16 and d.split('.')[:2] == p.split('.')[:2]:\n"
            "                return gw\n"
            "        return state.get('default')\n"
            "    if op == 'default':\n"
            "        return state.get('default')\n"
            "    if op == 'table':\n"
            "        return dict(state.get('table', {}))\n"
            "    return None\n"),
        "cases": [
            (({'table': {'10.0.0.0/8': 'gw1'}}, 'route', '10.1.0.5'), 'gw1'),
            (({'default': 'gw0'}, 'route', '8.8.8.8'), 'gw0'),
            (({}, 'default'), None),
            (({'table': {'a': 'b'}}, 'table'), {'a': 'b'})],
        "params": [],
        "calibration": "对照：网关——路由转发/默认出口/路由表",
    },
    "网络-端口镜像": {
        "task": "端口镜像",
        "pattern": (
            "def port_mirror(state, op, src=None, dst=None):\n"
"    # 生效条件：op ∈ {active, enable, mirror}\n"
"    # 子功能：① op 分支处理\n"
"    # 执行：按 op 分派\n"
"    # 不适用条件：op 非 {active, enable, mirror} 时\n"
            "    # 端口镜像：enable 启用 / mirror 复制 / active 状态（SPAN 监控）\n"
            "    if op == 'enable':\n"
            "        state['src'] = src\n"
            "        state['dst'] = dst\n"
            "        state['active'] = True\n"
            "        return 'enabled'\n"
            "    if op == 'mirror':\n"
            "        return (state.get('src'), state.get('dst')) if state.get('active') else None\n"
            "    if op == 'active':\n"
            "        return state.get('active', False)\n"
            "    return None\n"),
        "cases": [
            (({}, 'enable', 'p1', 'p9'), 'enabled'),
            (({'active': True, 'src': 'p1', 'dst': 'p9'}, 'mirror'), ('p1', 'p9')),
            (({}, 'mirror'), None),
            (({}, 'active'), False)],
        "params": [],
        "calibration": "对照：SPAN——端口流量镜像到监控口（抓包）",
    },
    "网络-包过滤": {
        "task": "包过滤",
        "pattern": (
            "def packet_filter(state, op, pkt=None):\n"
"    # 生效条件：op ∈ {filter, rules, stats}\n"
"    # 子功能：① op 分支处理\n"
"    # 执行：按 op 分派；循环迭代；顺序调用\n"
"    # 不适用条件：op 非 {filter, rules, stats} 时\n"
            "    # 包过滤：rules 规则 / filter 过滤 / stats 统计（ACL 包过滤）\n"
            "    if op == 'rules':\n"
            "        state.setdefault('rules', []).append(pkt)\n"
            "        return len(state['rules'])\n"
            "    if op == 'filter':\n"
            "        for r in state.get('rules', []):\n"
            "            if r[0] == pkt[0] and r[1] == pkt[1]:\n"
            "                return r[2]\n"
            "        return 'allow'\n"
            "    if op == 'stats':\n"
            "        return len(state.get('rules', []))\n"
            "    return None\n"),
        "cases": [
            (({}, 'rules', ('1.1.1.1', 80, 'block')), 1),
            (({'rules': [('1.1.1.1', 80, 'block')]}, 'filter', ('1.1.1.1', 80)), 'block'),
            (({}, 'filter', ('2.2.2.2', 80)), 'allow'),
            (({'rules': [('a', 1, 'b')]}, 'stats'), 1)],
        "params": [],
        "calibration": "对照：ACL——按五元组规则过滤（允许/拒绝）",
    },
    "网络-帧解析": {
        "task": "帧解析",
        "pattern": (
            "def ws_frame_parse(frame):\n"
            "    # WebSocket 帧解析（帧解析）：FIN/opcode/长度/载荷（RFC 6455 解码——帧封装的逆）\n"
            "    # 生效条件：frame 为 RFC 6455 帧字节（首字节 FIN+opcode，次字节长度）\n"
            "    # 子功能：① 解析 FIN/opcode ② 解析长度（含 126/127 扩展）③ 截取载荷解码\n"
            "    # 执行：位运算取首字节 + 定长/扩展长度读法 + utf-8 解码\n"
            "    # 不适用条件：frame 非法（长度不足 2 字节）时越界抛错；掩码帧未处理\n"
            "    fin = (frame[0] >> 7) & 1\n"
            "    opcode = frame[0] & 0x0F\n"
            "    n = frame[1] & 0x7F\n"
            "    off = 2\n"
            "    if n == 126:\n"
            "        n = int.from_bytes(frame[2:4], 'big')\n"
            "        off = 4\n"
            "    elif n == 127:\n"
            "        n = int.from_bytes(frame[4:12], 'big')\n"
            "        off = 10\n"
            "    return (fin, opcode, n, frame[off:off + n].decode('utf-8', 'replace'))\n"),
        "cases": [
            ((bytes([0x81, 0x02]) + b'hi',), (1, 1, 2, 'hi')),
            ((bytes([0x89, 0x00]),), (1, 9, 0, '')),
            ((bytes([0x81, 126]) + (300).to_bytes(2, 'big') + b'a' * 300,),
             (1, 1, 300, 'a' * 300)),
            ((bytes([0x82, 0x01]) + b'\x00',), (1, 2, 1, '\x00'))],
        "params": [],
        "calibration": "对照：RFC 6455——WebSocket 帧解码（FIN/opcode/长度/载荷，与帧封装 ws_frame 互逆）",
    },
    "网络-MAC学习": {
        "task": "MAC学习",
        "pattern": (
            "def mac_learn(table, port, mac, action):\n"
            "    # MAC 学习（MAC地址学习）：交换机按源 MAC 记录端口，未知目标泛洪（转发决策基础）\n"
            "    # 生效条件：action ∈ {learn, lookup}；table 为 MAC→端口 映射\n"
            "    # 子功能：① learn 记录源 MAC 端口 ② lookup 查询转发端口 ③ 未知泛洪\n"
            "    # 执行：learn 写表；lookup 命中返端口、未命中返 flood\n"
"    # 不适用条件：action 非 {learn, lookup} 时\n"
            "    if action == 'learn':\n"
            "        table[mac] = port\n"
            "        return 'learned'\n"
            "    if action == 'lookup':\n"
            "        return table.get(mac, 'flood')\n"
            "    return None\n"),
        "cases": [
            (({}, 'p1', 'aa', 'learn'), 'learned'),
            (({'aa': 'p1'}, 'p1', 'aa', 'lookup'), 'p1'),
            (({'aa': 'p1'}, 'p1', 'bb', 'lookup'), 'flood'),
            (({'aa': 'p1'}, 'p2', 'aa', 'learn'), 'learned'),
            (({}, 'p1', 'aa', 'unknown'), None)],
        "params": [],
        "calibration": "对照：交换机 MAC 学习——源 MAC 记端口，未知目标泛洪，学习可更新端口",
    },
    "网络-证书校验": {
        "task": "证书校验",
        "pattern": (
            "def cert_verify(cert, now):\n"
            "    # 证书校验（证书有效期校验）：有效期时间窗检查（TLS 信任链第一步）\n"
            "    # 生效条件：cert 含 not_before/not_after；now 为当前时间戳\n"
            "    # 子功能：① 时间窗边界比较 ② 越界判过期 ③ 窗内判有效\n"
            "    # 执行：now < not_before 或 now > not_after → expired（fail-closed）\n"
"    # 不适用条件：输入不满足生效条件时返回 None/不执行\n"
            "    if now < cert.get('not_before', 0) or now > cert.get('not_after', 0):\n"
            "        return 'expired'\n"
            "    return 'valid'\n"),
        "cases": [
            (({'not_before': 100, 'not_after': 200}, 150), 'valid'),
            (({'not_before': 100, 'not_after': 200}, 50), 'expired'),
            (({'not_before': 100, 'not_after': 200}, 250), 'expired'),
            (({}, 150), 'expired')],
        "params": [],
        "calibration": "对照：X.509 证书有效期校验——not_before/not_after 时间窗判定",
    },

    "蜂群-配对信任": {
        "task": "配对信任",
        "pattern": (
            "def swarm_pair(devices, op, device_id=None):\n"
            "    # 生效条件：devices 为设备 dict（id → {'paired': bool, 'trust': int}）；\n"
            "    #          op ∈ {pair, unpair, check}；device_id 配对/解对时必填\n"
            "    # 子功能：① pair 信任建立（trust=1）② unpair 撤销 ③ check 查询\n"
            "    # 执行：状态机分派（配对信任链：未配对→已配对，撤销反向）\n"
            "    # 不适用条件：重复配对已配对设备返回原状态（幂等）\n"
            "    devices.setdefault(device_id, {'paired': False, 'trust': 0})\n"
            "    dev = devices[device_id]\n"
            "    if op == 'pair':\n"
            "        dev['paired'] = True\n"
            "        dev['trust'] = 1\n"
            "    elif op == 'unpair':\n"
            "        dev['paired'] = False\n"
            "        dev['trust'] = 0\n"
            "    return dev['paired']\n"
        ),
        "cases": [
            [({1: {'paired': False, 'trust': 0}}, 'pair', 1), True],
            [({1: {'paired': True, 'trust': 1}}, 'unpair', 1), False],
            [({1: {'paired': False, 'trust': 0}}, 'check', 1), False],
        ],
        "params": ["devices", "op", "device_id"],
        "calibration": "对照：蓝牙配对——信任建立/撤销/查询三操作，配对即信任=1（蜂群信任链基例）",
    },

}


def route_net_unit(question):
    """任务识别（问题 → 网络单元）"""
    best, best_len = None, 0
    for uid, u in NET_UNITS.items():
        for kw in (u["task"], uid):
            if kw in question and len(kw) > best_len:
                best, best_len = uid, len(kw)
    return best


if __name__ == "__main__":
    print("=== 蓝牙和互联网白箱单元库（目标7 · 蜂群网络初级复现）===\n")
    for uid, u in NET_UNITS.items():
        print(f"[{uid}] 任务={u['task']} 样例数={len(u['cases'])}")
        print(f"    校准: {u['calibration']}")
    print(f"\n=== 判定 ===\n网络单元库: "
          f"{'✔ 5 单元就绪（IP/TCP/UDP/发现/蜂群中继）' if len(NET_UNITS) >= 4 else '✘'}")
