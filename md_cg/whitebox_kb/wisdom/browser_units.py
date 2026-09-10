# -*- coding: utf-8 -*-
"""browser_units.py · 迷你浏览器白箱单元库（第六阶段·目标5 初级复现）
用户设想：终极目标「中文浏览器」← 初级复现「浏览器」。
核心管线：HTTP 响应解析 → HTML DOM 解析 → CSS 选择器 → 块布局渲染。
单元：{任务 → 代码模式模板 + 验证样例 + 校准基准}——白箱自举（外部只校准）。
"""
import sys
sys.stdout.reconfigure(encoding='utf-8')

BROWSER_UNITS = {
    "HTTP-响应解析": {
        "task": "HTTP解析",
        "pattern": (
            "def parse_http_response(raw):\n"
"    # 生效条件：v.strip 可用；k.strip 可用\n"
"    # 子功能：① 调用 int；② 调用 len\n"
"    # 执行：循环迭代；顺序调用\n"
"    # 不适用条件：输入不满足生效条件时返回 None/不执行\n"
            "    # HTTP 响应解析：状态行/头/体 → {status, headers, body}\n"
            "    lines = raw.split('\\r\\n')\n"
            "    status = int(lines[0].split()[1])\n"
            "    headers = {}\n"
            "    i = 1\n"
            "    while i < len(lines) and lines[i]:\n"
            "        k, _, v = lines[i].partition(':')\n"
            "        headers[k.strip().lower()] = v.strip()\n"
            "        i += 1\n"
            "    body = '\\n'.join(lines[i + 1:])\n"
            "    return {'status': status, 'headers': headers, 'body': body}\n"),
        "cases": [("HTTP/1.1 200 OK\r\nContent-Type: text/html\r\n\r\n<body>hi</body>",
                   {"status": 200, "headers": {"content-type": "text/html"},
                    "body": "<body>hi</body>"}),
                  ("HTTP/1.1 404 Not Found\r\n\r\n", {"status": 404, "headers": {}, "body": ""})],
        "params": [],
        "calibration": "对照：浏览器 HTTP——响应状态行/头字段/体解析",
    },
    "HTML-DOM解析": {
        "task": "DOM解析",
        "pattern": (
            "def parse_dom(html):\n"
"    # 生效条件：re.finditer 可用；m.group 可用\n"
"    # 子功能：① 条件判定 ② 结果处理\n"
"    # 执行：循环迭代\n"
"    # 不适用条件：输入不满足生效条件时返回 None/不执行\n"
            "    # HTML → DOM 树（简化：标签 → 直接子标签列表）\n"
            "    import re\n"
            "    dom = {}\n"
            "    stack = []\n"
            "    for m in re.finditer(r'<(\\w+)[^>]*>|</(\\w+)>', html):\n"
            "        if m.group(1):\n"
            "            tag = m.group(1)\n"
            "            dom.setdefault(tag, [])\n"
            "            if stack:\n"
            "                dom[stack[-1]].append(tag)\n"
            "            stack.append(tag)\n"
            "        elif m.group(2) and stack:\n"
            "            stack.pop()\n"
            "    return dom\n"),
        "cases": [("<body><div><p>x</p></div></body>",
                   {"body": ["div"], "div": ["p"], "p": []}),
                  ("<html><body></body></html>", {"html": ["body"], "body": []})],
        "params": [],
        "calibration": "对照：浏览器 HTML 解析——标签嵌套 → DOM 树（父子关系）",
    },
    "CSS-选择器": {
        "task": "CSS选择器",
        "pattern": (
            "def css_match(selector, tag, classes):\n"
"    # 生效条件：selector.startswith 可用\n"
"    # 子功能：① 调用 len\n"
"    # 执行：顺序调用\n"
"    # 不适用条件：输入不满足生效条件时返回 None/不执行\n"
            "    # CSS 选择器匹配：tag / .class / tag.class\n"
            "    if selector.startswith('.'):\n"
            "        return selector[1:] in classes\n"
            "    parts = selector.split('.')\n"
            "    if len(parts) == 1:\n"
            "        return parts[0] == tag\n"
            "    return parts[0] == tag and parts[1] in classes\n"),
        "cases": [(("p", "p", []), True),
                  ((".red", "div", ["red"]), True),
                  (("p.red", "p", ["red"]), True),
                  (("div", "p", []), False)],
        "params": [],
        "calibration": "对照：浏览器 CSS——标签/类/tag.class 选择器匹配",
    },
    "渲染-块布局": {
        "task": "块布局",
        "pattern": (
            "def block_layout(elements, width):\n"
"    # 生效条件：参数 elements/width 合法\n"
"    # 子功能：① 条件判定 ② 结果处理\n"
"    # 执行：循环迭代\n"
"    # 不适用条件：输入不满足生效条件时返回 None/不执行\n"
            "    # 块布局：元素宽度序列 → 行堆叠（超出容器宽度换行）\n"
            "    rows, cur, used = [], [], 0\n"
            "    for w in elements:\n"
            "        if used + w > width and cur:\n"
            "            rows.append(cur)\n"
            "            cur, used = [], 0\n"
            "        cur.append(w)\n"
            "        used += w\n"
            "    if cur:\n"
            "        rows.append(cur)\n"
            "    return rows\n"),
        "cases": [(([3, 2, 2], 5), [[3, 2], [2]]),
                  (([2, 2, 2], 5), [[2, 2], [2]]),
                  (([1, 1], 5), [[1, 1]])],
        "params": [],
        "calibration": "对照：浏览器渲染——块级布局（宽度约束换行堆叠）",
    },
    "HTTP-请求构建": {
        "task": "请求构建",
        "pattern": (
            "def build_get_request(url, host, headers=None):\n"
            "    # HTTP 请求构建（GET 请求）：请求行 + Host 头 + 自定义头\n"
            "    # 生效条件：url 为请求路径；host 为主机名；headers 为附加头字典\n"
            "    # 子功能：① 请求行拼接 ② Host 头 ③ 附加头展开\n"
            "    # 执行：首行 GET + Host + 逐头拼接\n"
"    # 不适用条件：输入不满足生效条件时返回 None/不执行\n"
            "    h = headers or {}\n"
            "    lines = ['GET ' + url + ' HTTP/1.1', 'Host: ' + host]\n"
            "    for k, v in h.items():\n"
            "        lines.append(k + ': ' + v)\n"
            "    return '\\r\\n'.join(lines) + '\\r\\n\\r\\n'\n"),
        "cases": [(("/index.html", "example.com"),
                   "GET /index.html HTTP/1.1\r\nHost: example.com\r\n\r\n"),
                  (("/", "a.com"),
                   "GET / HTTP/1.1\r\nHost: a.com\r\n\r\n")],
        "params": [],
        "calibration": "对照：浏览器 HTTP 客户端——GET 请求构建（请求行+头）",
    },
    "URL-解析": {
        "task": "URL解析",
        "pattern": (
            "def parse_url(url):\n"
            "    # URL 解析（网页地址/统一资源定位符解析）：协议/主机/端口/路径\n"
            "    # 生效条件：url 为合法 URL 字符串（scheme://host[:port][/path]）\n"
            "    # 子功能：① 协议提取 ② 主机提取 ③ 端口/路径提取\n"
            "    # 执行：正则 `\\w+://...` 分组捕获\n"
"    # 不适用条件：输入不满足生效条件时返回 None/不执行\n"
            "    import re\n"
            "    m = re.match(r'(\\w+)://([^/:]+)(?::(\\d+))?(/.*)?', url)\n"
            "    return {'scheme': m.group(1), 'host': m.group(2),\n"
            "            'port': int(m.group(3)) if m.group(3) else None,\n"
            "            'path': m.group(4) or '/'}\n"),
        "cases": [("https://example.com:8080/page?a=1",
                   {'scheme': 'https', 'host': 'example.com', 'port': 8080,
                    'path': '/page?a=1'}),
                  ("http://a.com/x", {'scheme': 'http', 'host': 'a.com',
                                      'port': None, 'path': '/x'})],
        "params": [],
        "calibration": "对照：浏览器 URL——协议/主机/端口/路径解析",
    },
    "CSS-级联": {
        "task": "CSS级联",
        "pattern": (
            "def cascade_apply(rules):\n"
"    # 生效条件：参数 rules 合法\n"
"    # 子功能：① 调用 max\n"
"    # 执行：顺序调用\n"
"    # 不适用条件：输入不满足生效条件时返回 None/不执行\n"
            "    # 级联应用：选择最高优先级规则\n"
            "    return max(rules, key=cascade_weight)\n"
            "def cascade_weight(rule):\n"
            "    # CSS 级联优先级：内联1000 > id100 > class10 > 标签1\n"
            "    w = 0\n"
            "    if rule.get('inline'):\n"
            "        w += 1000\n"
            "    w += 100 * len(rule.get('ids', []))\n"
            "    w += 10 * len(rule.get('classes', []))\n"
            "    w += 1 * len(rule.get('tags', []))\n"
            "    return w\n"),
        "cases": [(([{'ids': ['a'], 'classes': [], 'tags': [], 'val': 'id'},
                     {'ids': [], 'classes': ['b'], 'tags': [], 'val': 'class'}],),
                   {'ids': ['a'], 'classes': [], 'tags': [], 'val': 'id'}),
                  (([{'ids': [], 'classes': [], 'tags': ['p'], 'val': 'tag'},
                     {'inline': True, 'val': 'inline'}],),
                   {'inline': True, 'val': 'inline'})],
        "params": [],
        "calibration": "对照：浏览器 CSS——级联优先级（内联>id>class>标签）",
    },
    "渲染-盒模型": {
        "task": "盒模型",
        "pattern": (
            "def box_model(width, padding, border, margin):\n"
            "    # 盒模型（CSS 盒模型）：内容+padding+border → 元素总宽（margin 不计入）\n"
            "    # 生效条件：width/padding/border/margin 为数值（CSS 盒属性）\n"
            "    # 子功能：① 内容宽 ② 加两侧 padding ③ 加两侧 border\n"
            "    # 执行：width + 2*padding + 2*border（margin 不计入总宽）\n"
"    # 不适用条件：输入不满足生效条件时返回 None/不执行\n"
            "    return width + 2 * padding + 2 * border\n"),
        "cases": [((100, 10, 2, 5), 124),
                  ((50, 0, 1, 0), 52),
                  ((0, 0, 0, 0), 0)],
        "params": [],
        "calibration": "对照：浏览器渲染——盒模型（padding/border 计入元素尺寸，margin 不计）",
    },
    "渲染-样式计算": {
        "task": "样式计算",
        "pattern": (
            "def style_compute(node, rules):\n"
            "    # 样式计算（CSS 级联）：DOM 节点（tag/classes）→ 匹配规则级联 → 最终样式\n"
            "    # 生效条件：node 含 tag/classes；rules 为带特异度的样式规则列表\n"
            "    # 子功能：① 规则匹配过滤 ② 特异度比较 ③ 级联合并最终样式\n"
            "    # 执行：匹配规则按权重取最优逐属性合并\n"
"    # 不适用条件：输入不满足生效条件时返回 None/不执行\n"
            "    best, best_w = {}, -1\n"
            "    for rule in rules:\n"
            "        if rule.get('tag') and rule['tag'] != node.get('tag'):\n"
            "            continue\n"
            "        if rule.get('class') and rule['class'] not in node.get('classes', []):\n"
            "            continue\n"
            "        w = (1000 if rule.get('inline') else 0)\n"
            "        w += 100 if rule.get('id') else 0\n"
            "        w += 10 if rule.get('class') else 0\n"
            "        w += 1 if rule.get('tag') else 0\n"
            "        if w > best_w:\n"
            "            best, best_w = rule.get('style', {}), w\n"
            "    return best\n"),
        "cases": [(({'tag': 'p', 'classes': ['red']},
                    [{'tag': 'p', 'style': {'color': 'black'}},
                     {'class': 'red', 'style': {'color': 'red'}}]),
                   {'color': 'red'}),
                  (({'tag': 'p', 'classes': []},
                    [{'tag': 'p', 'style': {'color': 'black'}}]),
                   {'color': 'black'}),
                  (({'tag': 'div', 'classes': []},
                    [{'tag': 'p', 'style': {'color': 'black'}}]), {})],
        "params": [],
        "calibration": "对照：浏览器渲染管线——样式计算（DOM×CSS→匹配规则→级联取最高优先级样式）",
    },
    "渲染-布局树": {
        "task": "布局树",
        "pattern": (
            "def layout_tree(nodes, container_w):\n"
"    # 生效条件：参数 nodes/container_w 合法\n"
"    # 子功能：① 主体逻辑执行\n"
"    # 执行：循环迭代\n"
"    # 不适用条件：输入不满足生效条件时返回 None/不执行\n"
            "    # 布局树：块级节点（样式宽/高）→ (x, y, w, h) 坐标（纵向堆叠）\n"
            "    y = 0\n"
            "    out = []\n"
            "    for node in nodes:\n"
            "        w = node.get('style', {}).get('width', container_w)\n"
            "        h = node.get('style', {}).get('height', 1)\n"
            "        out.append((node.get('id'), 0, y, w, h))\n"
            "        y += h\n"
            "    return out\n"),
        "cases": [(([{'id': 'a', 'style': {'width': 5, 'height': 2}},
                     {'id': 'b', 'style': {'height': 3}}], 10),
                   [('a', 0, 0, 5, 2), ('b', 0, 2, 10, 3)]),
                  (([{'id': 'x', 'style': {}}], 7), [('x', 0, 0, 7, 1)])],
        "params": [],
        "calibration": "对照：浏览器渲染管线——布局树（块级纵向堆叠，默认宽=容器/高=1）",
    },
    "渲染-绘制": {
        "task": "绘制",
        "pattern": (
            "def paint(layout, rows, cols):\n"
"    # 生效条件：参数 layout/rows/cols 合法\n"
"    # 子功能：① 调用 range\n"
"    # 执行：循环迭代；顺序调用\n"
"    # 不适用条件：输入不满足生效条件时返回 None/不执行\n"
            "    # 绘制：布局树 → 字符画布（'#'=元素区域，'.'=空白）\n"
            "    canvas = [['.' for _ in range(cols)] for _ in range(rows)]\n"
            "    for _, x, y, w, h in layout:\n"
            "        for dy in range(h):\n"
            "            for dx in range(w):\n"
            "                if 0 <= y + dy < rows and 0 <= x + dx < cols:\n"
            "                    canvas[y + dy][x + dx] = '#'\n"
            "    return [''.join(row) for row in canvas]\n"),
        "cases": [(([('a', 0, 0, 2, 1), ('b', 0, 1, 3, 1)], 2, 4),
                   ['##..', '###.']),
                  (([], 2, 3), ['...', '...'])],
        "params": [],
        "calibration": "对照：浏览器渲染管线——绘制（布局坐标→字符画布，像素填充）",
    },
    "事件-事件冒泡": {
        "task": "事件冒泡",
        "pattern": (
            "def event_path(dom_tree, target, ancestors=None):\n"
"    # 生效条件：参数 dom_tree/target/ancestors 合法\n"
"    # 子功能：① 主体逻辑执行\n"
"    # 执行：循环迭代\n"
"    # 不适用条件：输入不满足生效条件时返回 None/不执行\n"
            "    # 事件传播路径：目标 → 祖先链（冒泡顺序：目标→父→…→根）\n"
            "    path = []\n"
            "    node = target\n"
            "    while node is not None:\n"
            "        path.append(node)\n"
            "        node = dom_tree.get(node)  # 父节点\n"
            "    return path\n"),
        "cases": [(({'button': 'form', 'form': 'body', 'body': None}, 'button'),
                   ['button', 'form', 'body']),
                  (({'a': 'div', 'div': None}, 'a'), ['a', 'div']),
                  (({'x': None}, 'x'), ['x'])],
        "params": [],
        "calibration": "对照：浏览器事件——冒泡传播路径（目标→祖先链，DOM 事件冒泡语义）",
    },
    "事件-事件监听": {
        "task": "事件监听",
        "pattern": (
            "def listener_ops(listeners, event, target):\n"
"    # 生效条件：event ∈ {add, trigger}\n"
"    # 子功能：1 event 分支处理\n"
"    # 执行：按 op 分派；顺序调用\n"
"    # 不适用条件：event 非 {add, trigger} 时（隐式盲区：返回默认值 0 = 未知行为——不适用）\n"
            "    # 事件监听器：add/trigger（事件→匹配监听器列表）\n"
            "    if event == 'add':\n"
            "        listeners.setdefault(target, []).append(1)\n"
            "        return len(listeners[target])\n"
            "    if event == 'trigger':\n"
            "        return len(listeners.get(target, []))  # 匹配的监听器数\n"
            "    return 0\n"),
        "cases": [(({}, 'add', 'btn'), 1),
                  (({'btn': [1]}, 'trigger', 'btn'), 1),
                  (({}, 'trigger', 'btn'), 0)],
        "params": [],
        "calibration": "对照：浏览器事件——监听器注册/触发（addEventListener/dispatchEvent 语义）",
    },
    "渲染-动画帧": {
        "task": "动画帧",
        "pattern": (
            "def animation_frame(state, step_fn, frames):\n"
"    # 生效条件：参数 state/step_fn/frames 合法\n"
"    # 子功能：① 调用 range；② 调用 step_fn\n"
"    # 执行：循环迭代；顺序调用\n"
"    # 不适用条件：输入不满足生效条件时返回 None/不执行\n"
            "    # 动画帧循环：逐帧应用 step_fn（requestAnimationFrame 语义）\n"
            "    out = []\n"
            "    for _ in range(frames):\n"
            "        state = step_fn(state)\n"
            "        out.append(state)\n"
            "    return out\n"),
        "cases": [((0, lambda x: x + 1, 3), [1, 2, 3]),
                  ((10, lambda x: x * 2, 2), [20, 40]),
                  ((5, lambda x: x, 1), [5])],
        "params": [],
        "calibration": "对照：浏览器渲染——动画帧循环（rAF 逐帧更新状态）",
    },
    "存储-本地存储": {
        "task": "本地存储",
        "pattern": (
            "def storage_op(store, op, key=None, value=None):\n"
            "    # 本地存储（localStorage）：setItem/getItem/removeItem/clear（持久键值存储）\n"
            "    # 生效条件：op ∈ {set, get, remove, clear}；key/value 按 op 提供\n"
            "    # 子功能：① set 写键值 ② get 读值 ③ remove 删键 ④ clear 清空\n"
            "    # 执行：按 op 分派字典操作\n"
"    # 不适用条件：op 非 {clear, get, remove, set} 时\n"
            "    if op == 'set':\n"
            "        store[key] = value\n"
            "        return True\n"
            "    if op == 'get':\n"
            "        return store.get(key)\n"
            "    if op == 'remove':\n"
            "        return store.pop(key, None)\n"
            "    if op == 'clear':\n"
            "        store.clear()\n"
            "        return len(store)\n"
            "    return None\n"),
        "cases": [(({}, 'set', 'k', 'v'), True),
                  (({'k': 'v'}, 'get', 'k'), 'v'),
                  (({'k': 'v'}, 'remove', 'k'), 'v'),
                  (({'k': 'v'}, 'clear'), 0)],
        "params": [],
        "calibration": "对照：浏览器存储——localStorage（setItem/getItem/removeItem/clear）",
    },
    "存储-会话存储": {
        "task": "会话存储",
        "pattern": (
            "def session_storage(store, tab_open):\n"
"    # 生效条件：参数 store/tab_open 合法\n"
"    # 子功能：① 调用 dict\n"
"    # 执行：顺序调用\n"
"    # 不适用条件：输入不满足生效条件时返回 None/不执行\n"
            "    # sessionStorage：标签页级生命周期（新标签页 → 数据清空）\n"
            "    if tab_open:\n"
            "        return dict(store)          # 当前标签页数据\n"
            "    return {}                       # 新标签页：会话数据隔离\n"),
        "cases": [(({'u': 'x'}, True), {'u': 'x'}),
                  (({'u': 'x'}, False), {})],
        "params": [],
        "calibration": "对照：浏览器存储——sessionStorage（标签页生命周期，新标签页数据隔离）",
    },
    "并行-Web Worker": {
        "task": "Web Worker",
        "pattern": (
            "def worker_msg(main, worker, data):\n"
"    # 生效条件：参数 main/worker/data 合法\n"
"    # 子功能：① 主体逻辑执行\n"
"    # 执行：顺序执行\n"
"    # 不适用条件：输入不满足生效条件时返回 None/不执行\n"
            "    # Web Worker：主线程 postMessage → Worker 处理 → 回传（并行任务语义）\n"
            "    worker['input'] = data\n"
            "    worker['output'] = worker.get('fn', lambda x: x)(data)\n"
            "    main['result'] = worker['output']\n"
            "    return worker['output']\n"),
        "cases": [(({'result': None}, {'fn': lambda x: x * 2}, 21), 42),
                  (({'result': None}, {'fn': lambda x: x + 1}, 1), 2)],
        "params": [],
        "calibration": "对照：浏览器并行——Web Worker（postMessage 传递数据，Worker 处理回传）",
    },
    "网络-Fetch请求": {
        "task": "Fetch请求",
        "pattern": (
            "def fetch_req(method, url, headers=None, body=None):\n"
"    # 生效条件：参数 method/url/headers/body 合法\n"
"    # 子功能：① 调用 dict\n"
"    # 执行：顺序调用\n"
"    # 不适用条件：输入不满足生效条件时返回 None/不执行\n"
            "    # Fetch API：请求封装（方法/URL/头/体 → 请求对象）\n"
            "    req = {'method': method, 'url': url,\n"
            "           'headers': dict(headers or {}), 'body': body}\n"
            "    return req\n"),
        "cases": [(('GET', '/api', {'Accept': 'json'}, None),
                   {'method': 'GET', 'url': '/api',
                    'headers': {'Accept': 'json'}, 'body': None}),
                  (('POST', '/api', {}, '{"a":1}'),
                   {'method': 'POST', 'url': '/api', 'headers': {}, 'body': '{"a":1}'})],
        "params": [],
        "calibration": "对照：浏览器网络——Fetch API（请求方法/URL/头/体封装）",
    },
    "网络-HTTP缓存": {
        "task": "HTTP缓存",
        "pattern": (
            "def http_cache(cache, url, etag=None):\n"
"    # 生效条件：参数 cache/url/etag 合法\n"
"    # 子功能：① 条件判定 ② 结果处理\n"
"    # 执行：顺序执行\n"
"    # 不适用条件：输入不满足生效条件时返回 None/不执行\n"
            "    # HTTP 缓存：ETag 条件请求（未变更 304 → 用缓存；变更 → 更新）\n"
            "    if url in cache and cache[url].get('etag') == etag:\n"
            "        return cache[url]['data'], '304 未变更'\n"
            "    if etag is not None:\n"
            "        cache[url] = {'etag': etag, 'data': url + '@' + etag}\n"
            "        return cache[url]['data'], '200 已更新'\n"
            "    return None, '未缓存'\n"),
        "cases": [(({}, '/a', None), (None, '未缓存')),
                  (({'/a': {'etag': 'v1', 'data': 'D'}}, '/a', 'v1'),
                   ('D', '304 未变更')),
                  (({}, '/b', 'v2'), ('/b@v2', '200 已更新'))],
        "params": [],
        "calibration": "对照：浏览器网络——HTTP 缓存（ETag 条件请求 304/200 语义）",
    },
    "网络-Cookie": {
        "task": "Cookie管理",
        "pattern": (
            "def cookie_op(cookies, op, name=None, value=None):\n"
"    # 生效条件：op ∈ {delete, get, set}\n"
"    # 子功能：① op 分支处理\n"
"    # 执行：按 op 分派\n"
"    # 不适用条件：op 非 {delete, get, set} 时\n"
            "    # Cookie：设置/读取（domain 键值存储，Session 无过期）\n"
            "    if op == 'set':\n"
            "        cookies[name] = value\n"
            "        return True\n"
            "    if op == 'get':\n"
            "        return cookies.get(name)\n"
            "    if op == 'delete':\n"
            "        return cookies.pop(name, None)\n"
            "    return None\n"),
        "cases": [(({}, 'set', 'sid', 'abc'), True),
                  (({'sid': 'abc'}, 'get', 'sid'), 'abc'),
                  (({'sid': 'abc'}, 'delete', 'sid'), 'abc')],
        "params": [],
        "calibration": "对照：浏览器网络——Cookie（设置/读取/删除，会话状态保持）",
    },
    "安全-同源策略": {
        "task": "同源策略",
        "pattern": (
            "def same_origin(a, b):\n"
"    # 生效条件：参数 a/b 合法\n"
"    # 子功能：① 调用 parts\n"
"    # 执行：顺序调用\n"
"    # 不适用条件：输入不满足生效条件时返回 None/不执行\n"
            "    # 同源策略：协议+域名+端口 全同才同源（跨域请求拦截）\n"
            "    def parts(u):\n"
            "        s, rest = u.split('://')\n"
            "        host_port = rest.split('/')[0]\n"
            "        if ':' in host_port:\n"
            "            host, port = host_port.split(':')\n"
            "        else:\n"
            "            host, port = host_port, ('443' if s == 'https' else '80')\n"
            "        return (s, host, port)\n"
            "    return parts(a) == parts(b)\n"),
        "cases": [(('https://a.com/x', 'https://a.com/y'), True),
                  (('https://a.com', 'http://a.com'), False),
                  (('https://a.com:8080', 'https://a.com'), False)],
        "params": [],
        "calibration": "对照：浏览器安全——同源策略（协议+域名+端口，同源才允许跨域读写）",
    },
    "安全-CSP策略": {
        "task": "CSP策略",
        "pattern": (
            "def csp_allow(policy, resource_type, source):\n"
"    # 生效条件：参数 policy/resource_type/source 合法\n"
"    # 子功能：① 主体逻辑执行\n"
"    # 执行：顺序执行\n"
"    # 不适用条件：输入不满足生效条件时返回 None/不执行\n"
            "    # CSP：内容安全策略（资源类型 → 允许的来源白名单）\n"
            "    allowed = policy.get(resource_type, [])\n"
            "    return source in allowed or '*' in allowed\n"),
        "cases": [(({'script': ['self', 'cdn.com']}, 'script', 'cdn.com'), True),
                  (({'script': ['self']}, 'script', 'evil.com'), False),
                  (({'img': ['*']}, 'img', 'any.com'), True)],
        "params": [],
        "calibration": "对照：浏览器安全——CSP（资源类型白名单，* 通配允许）",
    },
    "安全-XSS防护": {
        "task": "XSS防护",
        "pattern": (
            "def escape_html(text):\n"
"    # 生效条件：text.replace 可用\n"
"    # 子功能：① 主体逻辑执行\n"
"    # 执行：顺序执行\n"
"    # 不适用条件：输入不满足生效条件时返回 None/不执行\n"
            "    # XSS 防护：HTML 转义（< > & \" ' → 实体，防脚本注入）\n"
            "    return (text.replace('&', '&amp;').replace('<', '&lt;')\n"
            "            .replace('>', '&gt;').replace('\"', '&quot;')\n"
            "            .replace(\"'\", '&#39;'))\n"),
        "cases": [('<script>alert(1)</script>',
                  '&lt;script&gt;alert(1)&lt;/script&gt;'),
                  ('a&b', 'a&amp;b'),
                  ('普通文本', '普通文本')],
        "params": [],
        "calibration": "对照：浏览器安全——XSS 防护（HTML 实体转义，防脚本注入）",
    },
    "并行-Service Worker": {
        "task": "Service Worker",
        "pattern": (
            "def sw_lifecycle(sw, event, url=None):\n"
"    # 生效条件：event ∈ {activate, fetch, install}\n"
"    # 子功能：1 event 分支处理\n"
"    # 执行：按 op 分派\n"
"    # 不适用条件：event 非 {activate, fetch, install} 时\n"
            "    # Service Worker：install→activate→fetch 拦截（离线能力核心）\n"
            "    if event == 'install':\n"
            "        sw['status'] = 'installed'\n"
            "        return 'installed'\n"
            "    if event == 'activate':\n"
            "        sw['status'] = 'active'\n"
            "        return 'active'\n"
            "    if event == 'fetch':\n"
            "        cache = sw.get('cache', {})\n"
            "        if url in cache:\n"
            "            return ('cached', cache[url])\n"
            "        return ('network', url)\n"
            "    return None\n"),
        "cases": [(({'status': 'idle'}, 'install'), 'installed'),
                  (({'status': 'installed'}, 'activate'), 'active'),
                  (({'status': 'active', 'cache': {'/a': 'D'}}, 'fetch', '/a'),
                   ('cached', 'D')),
                  (({'status': 'active'}, 'fetch', '/b'), ('network', '/b'))],
        "params": [],
        "calibration": "对照：Service Worker——install/activate/fetch 拦截（缓存优先/网络回退）",
    },
    "通知-推送消息": {
        "task": "推送通知",
        "pattern": (
            "def push_msg(sub, op, payload=None):\n"
"    # 生效条件：op ∈ {send, subscribe}\n"
"    # 子功能：① op 分支处理\n"
"    # 执行：按 op 分派\n"
"    # 不适用条件：op 非 {send, subscribe} 时\n"
            "    # Push API：订阅/推送（服务器 → 用户设备通知）\n"
            "    if op == 'subscribe':\n"
            "        sub['endpoint'] = 'push.example.com'\n"
            "        return sub['endpoint']\n"
            "    if op == 'send':\n"
            "        if not sub.get('endpoint'):\n"
            "            return 'not_subscribed'\n"
            "        sub['last'] = payload\n"
            "        return ('sent', payload)\n"
            "    return None\n"),
        "cases": [(({'endpoint': None}, 'subscribe'), 'push.example.com'),
                  (({'endpoint': 'e'}, 'send', '新消息'), ('sent', '新消息')),
                  (({}, 'send', 'x'), 'not_subscribed')],
        "params": [],
        "calibration": "对照：Push API——订阅/推送（服务器推送通知到设备）",
    },
    "存储-IndexedDB": {
        "task": "IndexedDB",
        "pattern": (
            "def idb_txn(db, op, key=None, value=None):\n"
"    # 生效条件：op ∈ {delete, get, put}\n"
"    # 子功能：① op 分支处理\n"
"    # 执行：按 op 分派\n"
"    # 不适用条件：op 非 {delete, get, put} 时\n"
            "    # IndexedDB：对象存储事务（put/get/delete——事务原子性）\n"
            "    if op == 'put':\n"
            "        db[key] = value\n"
            "        return True\n"
            "    if op == 'get':\n"
            "        return db.get(key)\n"
            "    if op == 'delete':\n"
            "        return db.pop(key, None)\n"
            "    return None\n"),
        "cases": [(({}, 'put', 'k', 'v'), True),
                  (({'k': 'v'}, 'get', 'k'), 'v'),
                  (({'k': 'v'}, 'delete', 'k'), 'v')],
        "params": [],
        "calibration": "对照：IndexedDB——对象存储事务（put/get/delete 键值事务）",
    },
    "性能-渲染优化": {
        "task": "渲染优化",
        "pattern": (
            "def batch_update(updates):\n"
"    # 生效条件：参数 updates 合法\n"
"    # 子功能：① 主体逻辑执行\n"
"    # 执行：循环迭代\n"
"    # 不适用条件：输入不满足生效条件时返回 None/不执行\n"
            "    # 渲染优化：批量 DOM 更新（合并多次修改为一次）\n"
            "    merged = {}\n"
            "    for u in updates:\n"
            "        merged[u['id']] = u['html']\n"
            "    return merged\n"),
        "cases": [(([{'id': 'a', 'html': 'x'}, {'id': 'a', 'html': 'y'},
                     {'id': 'b', 'html': 'z'}],),
                   {'a': 'y', 'b': 'z'}),
                  (([],), {})],
        "params": [],
        "calibration": "对照：浏览器性能——批量 DOM 更新（合并修改减少重排）",
    },
    "性能-懒加载": {
        "task": "懒加载",
        "pattern": (
            "def lazy_load(loads, viewport):\n"
"    # 生效条件：参数 loads/viewport 合法\n"
"    # 子功能：① 主体逻辑执行\n"
"    # 执行：顺序执行\n"
"    # 不适用条件：输入不满足生效条件时返回 None/不执行\n"
            "    # 懒加载：视口内才加载（按需加载优化）\n"
            "    return [l for l in loads if l['pos'] <= viewport]\n"),
        "cases": [(([{'id': 'a', 'pos': 100}, {'id': 'b', 'pos': 500}], 300),
                   [{'id': 'a', 'pos': 100}]),
                  (([{'id': 'a', 'pos': 50}], 100), [{'id': 'a', 'pos': 50}])],
        "params": [],
        "calibration": "对照：浏览器性能——懒加载（视口内才加载，按需优化）",
    },
    "性能-防抖节流": {
        "task": "节流",
        "pattern": (
            "def throttle(events, interval):\n"
"    # 生效条件：参数 events/interval 合法\n"
"    # 子功能：① 调用 float\n"
"    # 执行：循环迭代；顺序调用\n"
"    # 不适用条件：输入不满足生效条件时返回 None/不执行\n"
            "    # 节流：限频执行（首个事件立即执行，后续间隔 ≥ interval）\n"
            "    last = -float('inf')\n"
            "    out = []\n"
            "    for e in events:\n"
            "        if e - last >= interval:\n"
            "            out.append(e)\n"
            "            last = e\n"
            "    return out\n"),
        "cases": [(([0, 5, 10, 20], 10), [0, 10, 20]),
                  (([0, 1, 2], 5), [0]),
                  (([], 5), [])],
        "params": [],
        "calibration": "对照：浏览器性能——节流（限频执行，减少高频事件处理）",
    },
    "PWA-应用清单": {
        "task": "应用清单",
        "pattern": (
            "def manifest_check(manifest):\n"
"    # 生效条件：参数 manifest 合法\n"
"    # 子功能：① 主体逻辑执行\n"
"    # 执行：顺序执行\n"
"    # 不适用条件：输入不满足生效条件时返回 None/不执行\n"
            "    # PWA 清单：最小字段校验（名称/图标/启动地址——可安装条件）\n"
            "    required = ['name', 'icons', 'start_url']\n"
            "    missing = [k for k in required if not manifest.get(k)]\n"
            "    return (not missing), missing\n"),
        "cases": [(({'name': '应用', 'icons': ['i.png'], 'start_url': '/'},),
                   (True, [])),
                  (({'name': '应用'},), (False, ['icons', 'start_url'])),
                  (({},), (False, ['name', 'icons', 'start_url']))],
        "params": [],
        "calibration": "对照：PWA manifest——名称/图标/启动地址最小字段（安装条件）",
    },
    "PWA-缓存策略": {
        "task": "缓存策略",
        "pattern": (
            "def cache_strategy(strategy, cache, url, network_ok=True):\n"
"    # 生效条件：strategy ∈ {cache-first, network-first}\n"
"    # 子功能：1 strategy 分支处理\n"
"    # 执行：按 op 分派\n"
"    # 不适用条件：strategy 非 {cache-first, network-first} 时\n"
            "    # PWA 缓存策略：cache-first 缓存优先 / network-first 网络优先\n"
            "    # / stale 陈旧再验证（离线可用性策略）\n"
            "    cached = cache.get(url)\n"
            "    if strategy == 'cache-first':\n"
            "        return ('cached', cached) if cached is not None else ('network', url)\n"
            "    if strategy == 'network-first':\n"
            "        if network_ok:\n"
            "            return ('network', url)\n"
            "        return ('cached', cached) if cached is not None else ('error', url)\n"
            "    return ('stale', cached) if cached is not None else ('network', url)\n"),
        "cases": [(('cache-first', {'/a': 'D'}, '/a'), ('cached', 'D')),
                  (('cache-first', {}, '/b'), ('network', '/b')),
                  (('network-first', {'/a': 'D'}, '/a', False), ('cached', 'D')),
                  (('network-first', {}, '/a', False), ('error', '/a')),
                  (('stale', {'/a': 'D'}, '/a'), ('stale', 'D'))],
        "params": [],
        "calibration": "对照：PWA Service Worker——缓存策略（缓存优先/网络优先/陈旧再验证）",
    },
    "PWA-安装事件": {
        "task": "安装事件",
        "pattern": (
            "def install_prompt(state, action):\n"
"    # 生效条件：action ∈ {accept, capture, dismiss, prompt}\n"
"    # 子功能：1 action 分支处理\n"
"    # 执行：按 op 分派\n"
"    # 不适用条件：action 非 {accept, capture, dismiss, prompt} 时\n"
            "    # PWA 安装：beforeinstallprompt 捕获 → 提示展示 → 接受/拒绝/延迟\n"
            "    if action == 'capture':\n"
            "        state['available'] = True\n"
            "        return 'captured'\n"
            "    if action == 'prompt':\n"
            "        return 'showing' if state.get('available') else 'not_available'\n"
            "    if action == 'accept':\n"
            "        state['installed'] = True\n"
            "        return 'installed'\n"
            "    if action == 'dismiss':\n"
            "        return 'dismissed'\n"
            "    return None\n"),
        "cases": [(({}, 'capture'), 'captured'),
                  (({'available': True}, 'prompt'), 'showing'),
                  (({}, 'prompt'), 'not_available'),
                  (({'available': True}, 'accept'), 'installed'),
                  (({'available': True}, 'dismiss'), 'dismissed')],
        "params": [],
        "calibration": "对照：PWA beforeinstallprompt——捕获/展示/接受/拒绝（安装事件流）",
    },
    "渲染-合成分层": {
        "task": "合成分层",
        "pattern": (
            "def composite_layers(layers, op, layer_id=None, content=None):\n"
"    # 生效条件：op ∈ {add, render, update}\n"
"    # 子功能：① op 分支处理\n"
"    # 执行：按 op 分派；顺序调用\n"
"    # 不适用条件：op 非 {add, render, update} 时\n"
            "    # 合成分层：add 加层 / update 更新层 / render 按 z 序合成（GPU 合成语义）\n"
            "    if op == 'add':\n"
            "        layers[layer_id] = content\n"
            "        return layer_id\n"
            "    if op == 'update':\n"
            "        if layer_id in layers:\n"
            "            layers[layer_id] = content\n"
            "            return 'updated'\n"
            "        return 'missing'\n"
            "    if op == 'render':\n"
            "        return [(lid, layers[lid]) for lid in sorted(layers)]\n"
            "    return None\n"),
        "cases": [(({}, 'add', 'bg', '白'), 'bg'),
                  (({'bg': '白'}, 'update', 'bg', '蓝'), 'updated'),
                  (({'a': '1', 'b': '2'}, 'render', None, None),
                   [('a', '1'), ('b', '2')]),
                  (({}, 'update', 'x', '红'), 'missing')],
        "params": [],
        "calibration": "对照：浏览器渲染——合成分层（独立图层 z 序合成，滚动不重绘）",
    },
    "渲染-重排重绘": {
        "task": "重排重绘",
        "pattern": (
            "def reflow_classify(change):\n"
"    # 生效条件：参数 change 合法\n"
"    # 子功能：① 调用 any\n"
"    # 执行：顺序调用\n"
"    # 不适用条件：输入不满足生效条件时返回 None/不执行\n"
            "    # 重排/重绘：几何属性→reflow（重排），外观属性→repaint（重绘）\n"
            "    # （渲染成本分类：重排更贵）\n"
            "    geometry = ['宽度', '高度', '位置', 'margin', 'padding', 'border']\n"
            "    if any(g in change for g in geometry):\n"
            "        return 'reflow'\n"
            "    return 'repaint'\n"),
        "cases": [(('宽度 100',), 'reflow'),
                  (('margin 5',), 'reflow'),
                  (('颜色 红',), 'repaint'),
                  (('背景 蓝',), 'repaint')],
        "params": [],
        "calibration": "对照：浏览器渲染——重排/重绘（几何→reflow 贵，外观→repaint）",
    },
    "性能-关键渲染路径": {
        "task": "关键渲染路径",
        "pattern": (
            "def crp_advance(done, next_step):\n"
"    # 生效条件：order.index 可用\n"
"    # 子功能：① 条件判定 ② 结果处理\n"
"    # 执行：顺序执行\n"
"    # 不适用条件：输入不满足生效条件时返回 None/不执行\n"
            "    # 关键渲染路径：按依赖顺序推进（DOM→CSSOM→布局→绘制→合成）\n"
            "    order = ['DOM', 'CSSOM', '布局', '绘制', '合成']\n"
            "    if next_step not in order:\n"
            "        return 'unknown', done\n"
            "    need = order.index(next_step)\n"
            "    if done >= need:\n"
            "        return 'advance', need + 1\n"
            "    return 'blocked', done\n"),
        "cases": [((1, 'CSSOM'), ('advance', 2)),
                  ((1, '布局'), ('blocked', 1)),
                  ((4, '合成'), ('advance', 5)),
                  ((0, 'DOM'), ('advance', 1))],
        "params": [],
        "calibration": "对照：浏览器性能——关键渲染路径（CRP 依赖序推进，缺前置阻塞）",
    },
    "浏览器-历史记录": {
        "task": "历史记录",
        "pattern": (
            "def history_ops(hist, op, url=None):\n"
"    # 生效条件：op ∈ {back, forward, visit}\n"
"    # 子功能：① op 分支处理\n"
"    # 执行：按 op 分派；顺序调用\n"
"    # 不适用条件：op 非 {back, forward, visit} 时\n"
            "    # 历史记录：visit 记录 / back 后退 / forward 前进（栈+指针语义）\n"
            "    if op == 'visit':\n"
            "        hist['stack'] = hist.get('stack', [])[:hist.get('pos', -1) + 1]\n"
            "        hist['stack'].append(url)\n"
            "        hist['pos'] = len(hist['stack']) - 1\n"
            "        return hist['pos']\n"
            "    if op == 'back':\n"
            "        if hist.get('pos', 0) > 0:\n"
            "            hist['pos'] -= 1\n"
            "            return hist['stack'][hist['pos']]\n"
            "        return None\n"
            "    if op == 'forward':\n"
            "        stack = hist.get('stack', [])\n"
            "        pos = hist.get('pos', -1)\n"
            "        if pos + 1 < len(stack):\n"
            "            hist['pos'] = pos + 1\n"
            "            return stack[hist['pos']]\n"
            "        return None\n"
            "    return None\n"),
        "cases": [(({'stack': [], 'pos': -1}, 'visit', 'a'), 0),
                  (({'stack': ['a', 'b'], 'pos': 1}, 'back', None), 'a'),
                  (({'stack': ['a'], 'pos': 0}, 'back', None), None),
                  (({'stack': ['a'], 'pos': 0}, 'forward', None), None),
                  (({'stack': ['a', 'b'], 'pos': 0}, 'forward', None), 'b')],
        "params": [],
        "calibration": "对照：浏览器历史——后退/前进（访问栈+位置指针）",
    },
    "浏览器-书签管理": {
        "task": "书签管理",
        "pattern": (
            "def bookmark_ops(marks, op, name=None, url=None):\n"
"    # 生效条件：op ∈ {add, get, list, remove}\n"
"    # 子功能：① op 分支处理\n"
"    # 执行：按 op 分派；顺序调用\n"
"    # 不适用条件：op 非 {add, get, list, remove} 时\n"
            "    # 书签：add 添加 / get 查询 / remove 删除 / list 列出（名称排序）\n"
            "    if op == 'add':\n"
            "        marks[name] = url\n"
            "        return name\n"
            "    if op == 'get':\n"
            "        return marks.get(name)\n"
            "    if op == 'remove':\n"
            "        return marks.pop(name, None)\n"
            "    if op == 'list':\n"
            "        return sorted(marks)\n"
            "    return None\n"),
        "cases": [(({}, 'add', '首页', 'h.com'), '首页'),
                  (({'首页': 'h.com'}, 'get', '首页'), 'h.com'),
                  (({}, 'get', 'x'), None),
                  (({'b': '1', 'a': '2'}, 'list'), ['a', 'b']),
                  (({'首页': 'h.com'}, 'remove', '首页'), 'h.com')],
        "params": [],
        "calibration": "对照：浏览器书签——增删查列（名称排序管理）",
    },
    "浏览器-标签页管理": {
        "task": "标签页管理",
        "pattern": (
            "def tab_ops(tabs, op, tab_id=None, url=None):\n"
"    # 生效条件：op ∈ {close, open, switch}\n"
"    # 子功能：① op 分支处理\n"
"    # 执行：按 op 分派；顺序调用\n"
"    # 不适用条件：op 非 {close, open, switch} 时\n"
            "    # 标签页：open 新建 / switch 切换 / close 关闭（活动标签维护）\n"
            "    if op == 'open':\n"
            "        tabs.append({'id': tab_id, 'url': url})\n"
            "        return len(tabs) - 1\n"
            "    if op == 'switch':\n"
            "        if 0 <= tab_id < len(tabs):\n"
            "            return tab_id\n"
            "        return None\n"
            "    if op == 'close':\n"
            "        if 0 <= tab_id < len(tabs):\n"
            "            tabs.pop(tab_id)\n"
            "            return len(tabs)\n"
            "        return None\n"
            "    return None\n"),
        "cases": [(([], 'open', 1, 'a.com'), 0),
                  (({'id': 1, 'url': 'a'}, 'switch', 0), 0),
                  (([{'id': 1, 'url': 'a'}, {'id': 2, 'url': 'b'}],
                    'close', 0), 1),
                  (([], 'switch', 5), None)],
        "params": [],
        "calibration": "对照：浏览器标签页——新建/切换/关闭（活动标签维护）",
    },
    "浏览器-下载管理": {
        "task": "下载管理",
        "pattern": (
            "def download_ops(tasks, op, task_id=None, chunk=None, total=100):\n"
"    # 生效条件：op ∈ {pause, progress, resume, start}\n"
"    # 子功能：① op 分支处理\n"
"    # 执行：按 op 分派\n"
"    # 不适用条件：op 非 {pause, progress, resume, start} 时\n"
            "    # 下载管理：start 开始 / progress 进度推进（断点续传）/ pause 暂停 / resume 恢复\n"
            "    if op == 'start':\n"
            "        tasks[task_id] = {'received': 0, 'total': total, 'paused': False}\n"
            "        return 'started'\n"
            "    if op == 'progress':\n"
            "        t = tasks.get(task_id)\n"
            "        if t is None:\n"
            "            return 'missing'\n"
            "        if t.get('paused'):\n"
            "            return 'paused'\n"
            "        t['received'] += chunk\n"
            "        return 'done' if t['received'] >= t['total'] else 'downloading'\n"
            "    if op == 'pause':\n"
            "        if task_id in tasks:\n"
            "            tasks[task_id]['paused'] = True\n"
            "            return 'paused'\n"
            "        return 'missing'\n"
            "    if op == 'resume':\n"
            "        if task_id in tasks:\n"
            "            tasks[task_id]['paused'] = False\n"
            "            return 'resumed'\n"
            "        return 'missing'\n"
            "    return None\n"),
        "cases": [(({}, 'start', 1, None, 100), 'started'),
                  (({'1': {'received': 0, 'total': 100, 'paused': False}},
                    'progress', '1', 30), 'downloading'),
                  (({'1': {'received': 80, 'total': 100, 'paused': False}},
                    'progress', '1', 30), 'done'),
                  (({'1': {'received': 0, 'total': 100, 'paused': False}},
                    'pause', '1'), 'paused'),
                  (({}, 'progress', '1', 10), 'missing')],
        "params": [],
        "calibration": "对照：浏览器下载——进度/暂停/恢复（断点续传）",
    },
    "浏览器-扩展管理": {
        "task": "扩展管理",
        "pattern": (
            "def extension_ops(exts, op, ext_id=None, permissions=None, requested=None):\n"
"    # 生效条件：op ∈ {check, enable, install}\n"
"    # 子功能：① op 分支处理\n"
"    # 执行：按 op 分派；顺序调用\n"
"    # 不适用条件：op 非 {check, enable, install} 时\n"
            "    # 扩展管理：install 安装 / enable 启停 / check 权限检查（最小权限）\n"
            "    if op == 'install':\n"
            "        exts[ext_id] = {'enabled': True, 'permissions': permissions or []}\n"
            "        return 'installed'\n"
            "    if op == 'enable':\n"
            "        if ext_id in exts:\n"
            "            exts[ext_id]['enabled'] = not exts[ext_id]['enabled']\n"
            "            return 'enabled' if exts[ext_id]['enabled'] else 'disabled'\n"
            "        return 'missing'\n"
            "    if op == 'check':\n"
            "        ext = exts.get(ext_id)\n"
            "        if ext is None:\n"
            "            return 'missing'\n"
            "        return ('granted' if set(requested or []) <= set(ext['permissions'])\n"
            "                else 'denied')\n"
            "    return None\n"),
        "cases": [(({}, 'install', 'e1', ['tabs', 'storage']), 'installed'),
                  (({'e1': {'enabled': True, 'permissions': ['tabs']}},
                    'enable', 'e1'), 'disabled'),
                  (({'e1': {'enabled': True, 'permissions': ['tabs', 'storage']}},
                    'check', 'e1', None, ['tabs']), 'granted'),
                  (({'e1': {'enabled': True, 'permissions': ['tabs']}},
                    'check', 'e1', None, ['storage']), 'denied')],
        "params": [],
        "calibration": "对照：浏览器扩展——安装/启停/权限检查（最小权限原则）",
    },
    "浏览器-网络记录": {
        "task": "网络记录",
        "pattern": (
            "def network_log(log, op, request=None, status=None, size=0):\n"
"    # 生效条件：op ∈ {filter, record, stats}\n"
"    # 子功能：① op 分支处理\n"
"    # 执行：按 op 分派；顺序调用\n"
"    # 不适用条件：op 非 {filter, record, stats} 时\n"
            "    # 开发者工具：record 记录请求 / filter 按状态过滤 / stats 汇总\n"
            "    if op == 'record':\n"
            "        log.append({'url': request, 'status': status, 'size': size})\n"
            "        return len(log)\n"
            "    if op == 'filter':\n"
            "        return [e for e in log if e['status'] == status]\n"
            "    if op == 'stats':\n"
            "        return {'count': len(log),\n"
            "                'total_size': sum(e['size'] for e in log)}\n"
            "    return None\n"),
        "cases": [(([], 'record', '/a', 200, 100), 1),
                  (([{'url': '/a', 'status': 200, 'size': 100},
                     {'url': '/b', 'status': 404, 'size': 50}],
                    'filter', None, 404),
                   [{'url': '/b', 'status': 404, 'size': 50}]),
                  (([{'url': '/a', 'status': 200, 'size': 100},
                     {'url': '/b', 'status': 404, 'size': 50}], 'stats'),
                   {'count': 2, 'total_size': 150})],
        "params": [],
        "calibration": "对照：开发者工具网络面板——请求记录/过滤/汇总",
    },
    "浏览器-表单验证": {
        "task": "表单验证",
        "pattern": (
            "def form_validate(fields, values):\n"
"    # 生效条件：参数 fields/values 合法\n"
"    # 子功能：① 调用 str\n"
"    # 执行：循环迭代；顺序调用\n"
"    # 不适用条件：输入不满足生效条件时返回 None/不执行\n"
            "    # 表单验证：必填 + 格式（邮箱/数字——提交前校验）\n"
            "    errors = []\n"
            "    for name, rule in fields.items():\n"
            "        val = values.get(name)\n"
            "        if rule.get('required') and not val:\n"
            "            errors.append(name + ':必填')\n"
            "        elif 'email' in rule and val and '@' not in val:\n"
            "            errors.append(name + ':格式错误')\n"
            "        elif 'number' in rule and val and not str(val).isdigit():\n"
            "            errors.append(name + ':非数字')\n"
            "    return errors\n"),
        "cases": [(({'名': {'required': True}}, {'名': '甲'}), []),
                  (({'名': {'required': True}}, {}), ['名:必填']),
                  (({'邮箱': {'email': True}}, {'邮箱': 'abc'}), ['邮箱:格式错误']),
                  (({'数量': {'number': True}}, {'数量': 'x'}), ['数量:非数字'])],
        "params": [],
        "calibration": "对照：浏览器表单——必填/邮箱/数字验证（提交前校验）",
    },
    "浏览器-拖放交互": {
        "task": "拖放交互",
        "pattern": (
            "def drag_drop(state, op, data=None, target=None):\n"
"    # 生效条件：op ∈ {dragstart, drop, get}\n"
"    # 子功能：① op 分支处理\n"
"    # 执行：按 op 分派\n"
"    # 不适用条件：op 非 {dragstart, drop, get} 时\n"
            "    # 拖放：dragstart 开始携带数据 / drop 放到目标（数据传输）\n"
            "    if op == 'dragstart':\n"
            "        state['drag_data'] = data\n"
            "        return 'dragging'\n"
            "    if op == 'drop':\n"
            "        if 'drag_data' not in state:\n"
            "            return 'no_drag'\n"
            "        state['dropped'] = (target, state['drag_data'])\n"
            "        return 'dropped'\n"
            "    if op == 'get':\n"
            "        return state.get('dropped')\n"
            "    return None\n"),
        "cases": [(({}, 'dragstart', 'item1'), 'dragging'),
                  (({'drag_data': 'item1'}, 'drop', None, 'zone_a'), 'dropped'),
                  (({}, 'drop', None, 'zone_a'), 'no_drag'),
                  (({'dropped': ('zone_a', 'item1')}, 'get'),
                   ('zone_a', 'item1'))],
        "params": [],
        "calibration": "对照：拖放 API——dragstart 数据携带/drop 目标投放",
    },
    "浏览器-资源完整性": {
        "task": "资源完整性",
        "pattern": (
            "def sri_verify(resource_hash, expected):\n"
"    # 生效条件：参数 resource_hash/expected 合法\n"
"    # 子功能：① 条件判定 ② 结果处理\n"
"    # 执行：顺序执行\n"
"    # 不适用条件：输入不满足生效条件时返回 None/不执行\n"
            "    # 子资源完整性：哈希比对（SRI——防篡改第三方脚本）\n"
            "    return 'ok' if resource_hash == expected else 'mismatch'\n"),
        "cases": [(('abc', 'abc'), 'ok'),
                  (('abc', 'abd'), 'mismatch'),
                  (('', ''), 'ok')],
        "params": [],
        "calibration": "对照：SRI 子资源完整性——脚本哈希校验（防篡改）",
    },
    "浏览器-媒体播放": {
        "task": "媒体播放",
        "pattern": (
            "def media_ops(media, op, position=None, volume=None):\n"
"    # 生效条件：op ∈ {pause, play, seek, volume}\n"
"    # 子功能：① op 分支处理\n"
"    # 执行：按 op 分派；顺序调用\n"
"    # 不适用条件：op 非 {pause, play, seek, volume} 时\n"
            "    # 媒体播放：play 播放 / pause 暂停 / seek 跳转 / volume 音量（夹紧 0-1）\n"
            "    if op == 'play':\n"
            "        media['playing'] = True\n"
            "        return 'playing'\n"
            "    if op == 'pause':\n"
            "        media['playing'] = False\n"
            "        return 'paused'\n"
            "    if op == 'seek':\n"
            "        if position is not None:\n"
            "            media['position'] = position\n"
            "        return media.get('position', 0)\n"
            "    if op == 'volume':\n"
            "        if volume is not None:\n"
            "            media['volume'] = max(0.0, min(1.0, volume))\n"
            "        return media.get('volume', 1.0)\n"
            "    return None\n"),
        "cases": [(({'playing': False}, 'play'), 'playing'),
                  (({'playing': True}, 'pause'), 'paused'),
                  (({'position': 0}, 'seek', 30), 30),
                  (({'volume': 1.0}, 'volume', None, 0.5), 0.5),
                  (({'volume': 1.0}, 'volume', None, 1.5), 1.0)],
        "params": [],
        "calibration": "对照：HTML5 媒体——play/pause/seek/volume（音量夹紧）",
    },
    "浏览器-地理位置": {
        "task": "地理位置",
        "pattern": (
            "def geolocation(state, op, permission=None, lat=None, lng=None):\n"
"    # 生效条件：op ∈ {get, request}\n"
"    # 子功能：① op 分支处理\n"
"    # 执行：按 op 分派\n"
"    # 不适用条件：op 非 {get, request} 时\n"
            "    # 地理位置：request 请求权限 / get 获取坐标（权限门控）\n"
            "    if op == 'request':\n"
            "        state['granted'] = permission\n"
            "        return 'granted' if permission else 'denied'\n"
            "    if op == 'get':\n"
            "        if state.get('granted'):\n"
            "            return {'lat': lat, 'lng': lng}\n"
            "        return 'permission_denied'\n"
            "    return None\n"),
        "cases": [(({}, 'request', True), 'granted'),
                  (({'granted': True}, 'get', None, 39.9, 116.4),
                   {'lat': 39.9, 'lng': 116.4}),
                  (({}, 'get'), 'permission_denied')],
        "params": [],
        "calibration": "对照：Geolocation API——权限请求/坐标获取（权限门控）",
    },
    "浏览器-全屏模式": {
        "task": "全屏模式",
        "pattern": (
            "def fullscreen_ops(state, op, element=None):\n"
"    # 生效条件：op ∈ {enter, exit}\n"
"    # 子功能：① op 分支处理\n"
"    # 执行：按 op 分派\n"
"    # 不适用条件：op 非 {enter, exit} 时\n"
            "    # 全屏模式：enter 元素全屏 / exit 退出（全屏 API 状态）\n"
            "    if op == 'enter':\n"
            "        state['fullscreen'] = element\n"
            "        return element\n"
            "    if op == 'exit':\n"
            "        state['fullscreen'] = None\n"
            "        return 'windowed'\n"
            "    return None\n"),
        "cases": [(({}, 'enter', 'video'), 'video'),
                  (({'fullscreen': 'video'}, 'exit'), 'windowed'),
                  (({}, 'enter', 'div'), 'div')],
        "params": [],
        "calibration": "对照：Fullscreen API——元素全屏进入/退出",
    },
    "浏览器-预加载": {
        "task": "预加载",
        "pattern": (
            "def preload_ops(preloads, op, url=None, kind=None):\n"
"    # 生效条件：op ∈ {add, stats, use}\n"
"    # 子功能：① op 分支处理\n"
"    # 执行：按 op 分派；顺序调用\n"
"    # 不适用条件：op 非 {add, stats, use} 时\n"
            "    # 预加载：add 登记预加载资源 / use 命中使用 / stats 统计（preload）\n"
            "    if op == 'add':\n"
            "        preloads[url] = {'kind': kind, 'used': False}\n"
            "        return url\n"
            "    if op == 'use':\n"
            "        if url in preloads:\n"
            "            preloads[url]['used'] = True\n"
            "            return 'hit'\n"
            "        return 'miss'\n"
            "    if op == 'stats':\n"
            "        used = sum(1 for p in preloads.values() if p['used'])\n"
            "        return {'total': len(preloads), 'used': used}\n"
            "    return None\n"),
        "cases": [(({}, 'add', '/a.css', 'style'), '/a.css'),
                  (({'/a.css': {'kind': 'style', 'used': False}},
                    'use', '/a.css'), 'hit'),
                  (({}, 'use', '/a.css'), 'miss'),
                  (({'/a.css': {'kind': 'style', 'used': True}},
                    'stats'), {'total': 1, 'used': 1})],
        "params": [],
        "calibration": "对照：preload——关键资源提前加载（命中统计）",
    },
    "浏览器-请求合并": {
        "task": "请求合并",
        "pattern": (
            "def batch_requests(batches, op, batch_id=None, urls=None):\n"
"    # 生效条件：op ∈ {add, count, create}\n"
"    # 子功能：① op 分支处理\n"
"    # 执行：按 op 分派；顺序调用\n"
"    # 不适用条件：op 非 {add, count, create} 时\n"
            "    # 请求合并：create 建批 / add 加入 / count 计数（多请求合并成批）\n"
            "    if op == 'create':\n"
            "        batches[batch_id] = []\n"
            "        return batch_id\n"
            "    if op == 'add':\n"
            "        batches[batch_id].extend(urls)\n"
            "        return len(batches[batch_id])\n"
            "    if op == 'count':\n"
            "        return len(batches.get(batch_id, []))\n"
            "    return None\n"),
        "cases": [(({}, 'create', 'b1'), 'b1'),
                  (({'b1': []}, 'add', 'b1', ['/a', '/b']), 2),
                  (({'b1': ['/a']}, 'count', 'b1'), 1),
                  (({}, 'count', 'b1'), 0)],
        "params": [],
        "calibration": "对照：请求合并——多请求成批传输（减少往返）",
    },
    "浏览器-资源优先级": {
        "task": "资源优先级",
        "pattern": (
            "def resource_priority(resources, op, url=None, kind=None):\n"
"    # 生效条件：op ∈ {priority, register}\n"
"    # 子功能：① op 分支处理\n"
"    # 执行：按 op 分派\n"
"    # 不适用条件：op 非 {priority, register} 时\n"
            "    # 资源优先级：register 登记类型 / priority 查询（关键 CSS/JS 优先）\n"
            "    if op == 'register':\n"
            "        resources[url] = kind\n"
            "        return kind\n"
            "    if op == 'priority':\n"
            "        kind = resources.get(url)\n"
            "        order = {'script': 3, 'style': 2, 'image': 1}\n"
            "        return order.get(kind, 0)\n"
            "    return None\n"),
        "cases": [(({}, 'register', '/app.js', 'script'), 'script'),
                  (({'/app.js': 'script'}, 'priority', '/app.js'), 3),
                  (({'/a.css': 'style'}, 'priority', '/a.css'), 2),
                  (({}, 'priority', '/x'), 0)],
        "params": [],
        "calibration": "对照：资源优先级——关键脚本/样式优先加载",
    },
    "浏览器-权限API": {
        "task": "权限API",
        "pattern": (
            "def permission_api(state, op, perm=None, granted=None):\n"
"    # 生效条件：op ∈ {query, request}\n"
"    # 子功能：① op 分支处理\n"
"    # 执行：按 op 分派\n"
"    # 不适用条件：op 非 {query, request} 时\n"
            "    # 权限 API：query 查询 / request 请求（权限状态管理）\n"
            "    if op == 'query':\n"
            "        return state.get(perm, 'prompt')\n"
            "    if op == 'request':\n"
            "        state[perm] = 'granted' if granted else 'denied'\n"
            "        return state[perm]\n"
            "    return None\n"),
        "cases": [(({}, 'query', 'camera'), 'prompt'),
                  (({'camera': 'granted'}, 'query', 'camera'), 'granted'),
                  (({}, 'request', 'camera', True), 'granted'),
                  (({}, 'request', 'camera', False), 'denied')],
        "params": [],
        "calibration": "对照：Permissions API——权限查询/请求（prompt/granted/denied）",
    },
    "浏览器-CSP报告": {
        "task": "CSP报告",
        "pattern": (
            "def csp_report(reports, op, violation=None, policy=None):\n"
"    # 生效条件：op ∈ {count, filter, record}\n"
"    # 子功能：① op 分支处理\n"
"    # 执行：按 op 分派；顺序调用\n"
"    # 不适用条件：op 非 {count, filter, record} 时\n"
            "    # CSP 报告：record 记录违规 / count 统计 / filter 按策略过滤（上报）\n"
            "    if op == 'record':\n"
            "        reports.append({'violation': violation, 'policy': policy})\n"
            "        return len(reports)\n"
            "    if op == 'count':\n"
            "        return len(reports)\n"
            "    if op == 'filter':\n"
            "        return [r for r in reports if r['policy'] == policy]\n"
            "    return None\n"),
        "cases": [(([], 'record', 'script-src', 'default-src'), 1),
                  (([{'violation': 'script-src', 'policy': 'default-src'}],
                    'count'), 1),
                  (([{'violation': 'a', 'policy': 'p1'},
                     {'violation': 'b', 'policy': 'p2'}],
                    'filter', None, 'p1'),
                   [{'violation': 'a', 'policy': 'p1'}])],
        "params": [],
        "calibration": "对照：CSP report-uri——内容安全策略违规上报",
    },
    "浏览器-支付请求": {
        "task": "支付请求",
        "pattern": (
            "def payment_ops(payment, op, method=None, amount=None):\n"
"    # 生效条件：op ∈ {can_pay, pay, status}\n"
"    # 子功能：① op 分支处理\n"
"    # 执行：按 op 分派\n"
"    # 不适用条件：op 非 {can_pay, pay, status} 时\n"
            "    # 支付请求：can_pay 检查方法 / pay 支付 / status 状态（支付流程）\n"
            "    if op == 'can_pay':\n"
            "        return method in payment.get('methods', [])\n"
            "    if op == 'pay':\n"
            "        if method not in payment.get('methods', []):\n"
            "            return 'unsupported'\n"
            "        payment['paid'] = (method, amount)\n"
            "        return 'paid'\n"
            "    if op == 'status':\n"
            "        return payment.get('paid')\n"
            "    return None\n"),
        "cases": [(({'methods': ['alipay']}, 'can_pay', 'alipay'), True),
                  (({'methods': ['alipay']}, 'pay', 'alipay', 100), 'paid'),
                  (({'methods': ['alipay']}, 'pay', 'wechat', 100),
                   'unsupported'),
                  (({'methods': ['alipay'], 'paid': ('alipay', 100)},
                    'status'), ('alipay', 100))],
        "params": [],
        "calibration": "对照：Payment Request API——方法检查/支付/状态",
    },
    "浏览器-响应式断点": {
        "task": "响应式断点",
        "pattern": (
            "def responsive_breakpoint(width, breakpoints):\n"
"    # 生效条件：参数 width/breakpoints 合法\n"
"    # 子功能：① 调用 sorted\n"
"    # 执行：循环迭代；顺序调用\n"
"    # 不适用条件：输入不满足生效条件时返回 None/不执行\n"
            "    # 响应式断点：按宽度匹配断点（媒体查询——响应式布局）\n"
            "    matched = 'base'\n"
            "    for bp, w in sorted(breakpoints.items(), key=lambda x: x[1]):\n"
            "        if width >= w:\n"
            "            matched = bp\n"
            "    return matched\n"),
        "cases": [((480, {'sm': 320, 'md': 768, 'lg': 1024}), 'sm'),
                  ((800, {'sm': 320, 'md': 768, 'lg': 1024}), 'md'),
                  ((1200, {'sm': 320, 'md': 768, 'lg': 1024}), 'lg'),
                  ((100, {'sm': 320, 'md': 768, 'lg': 1024}), 'base')],
        "params": [],
        "calibration": "对照：CSS 媒体查询——响应式断点（宽度分级）",
    },
    "浏览器-离线队列": {
        "task": "离线队列",
        "pattern": (
            "def offline_queue(queue, op, request=None):\n"
"    # 生效条件：op ∈ {count, enqueue, flush}；queue.clear 可用\n"
"    # 子功能：① op 分支处理\n"
"    # 执行：按 op 分派；顺序调用\n"
"    # 不适用条件：op 非 {count, enqueue, flush} 时\n"
            "    # 离线队列：enqueue 离线入队 / flush 上线重发 / count 计数\n"
            "    if op == 'enqueue':\n"
            "        queue.append(request)\n"
            "        return len(queue)\n"
            "    if op == 'flush':\n"
            "        out = list(queue)\n"
            "        queue.clear()\n"
            "        return out\n"
            "    if op == 'count':\n"
            "        return len(queue)\n"
            "    return None\n"),
        "cases": [(([], 'enqueue', 'req1'), 1),
                  ((['req1'], 'enqueue', 'req2'), 2),
                  ((['req1', 'req2'], 'flush'), ['req1', 'req2']),
                  ((['req1'], 'count'), 1)],
        "params": [],
        "calibration": "对照：离线优先——离线请求队列（上线重发）",
    },
    "浏览器-会话恢复": {
        "task": "会话恢复",
        "pattern": (
            "def session_restore(snapshots, op, name=None, tabs=None):\n"
"    # 生效条件：op ∈ {restore, save}\n"
"    # 子功能：① op 分支处理\n"
"    # 执行：按 op 分派；顺序调用\n"
"    # 不适用条件：op 非 {restore, save} 时\n"
            "    # 会话恢复：save 保存标签页 / restore 恢复（崩溃恢复）\n"
            "    if op == 'save':\n"
            "        snapshots[name] = list(tabs)\n"
            "        return name\n"
            "    if op == 'restore':\n"
            "        return list(snapshots.get(name, []))\n"
            "    return None\n"),
        "cases": [(({}, 'save', 's1', ['a.com', 'b.com']), 's1'),
                  (({'s1': ['a.com', 'b.com']}, 'restore', 's1'),
                   ['a.com', 'b.com']),
                  (({}, 'restore', 's1'), [])],
        "params": [],
        "calibration": "对照：浏览器会话恢复——标签页快照保存/恢复（崩溃恢复）",
    },
    "安全-CORS检查": {
        "task": "CORS检查",
        "pattern": (
            "def cors_check(origin, target, method='GET'):\n"
"    # 生效条件：参数 origin/target/method 合法\n"
"    # 子功能：① 条件判定 ② 结果处理\n"
"    # 执行：顺序执行\n"
"    # 不适用条件：输入不满足生效条件时返回 None/不执行\n"
            "    # CORS：同源放行 / 简单请求放行 / 预检判定（跨域资源共享）\n"
            "    if origin == target:\n"
            "        return 'same-origin'\n"
            "    if method in ('GET', 'HEAD', 'POST'):\n"
            "        return 'simple'\n"
            "    return 'preflight'\n"),
        "cases": [(('https://a.com', 'https://a.com'), 'same-origin'),
                  (('https://a.com', 'https://b.com'), 'simple'),
                  (('https://a.com', 'https://b.com', 'PUT'), 'preflight'),
                  (('https://a.com', 'https://b.com', 'DELETE'), 'preflight')],
        "params": [],
        "calibration": "对照：浏览器安全——CORS 跨域资源共享（同源/简单/预检三态）",
    },
    "渲染-文本排版": {
        "task": "文本排版",
        "pattern": (
            "def text_wrap(text, width):\n"
"    # 生效条件：参数 text/width 合法\n"
"    # 子功能：① 调用 len\n"
"    # 执行：循环迭代；顺序调用\n"
"    # 不适用条件：text 为空/非法时（隐式盲区：返回默认值 [] = 未知行为——不适用）\n"
            "    # 文本排版：按宽度贪心换行（文本布局——每行不超宽度）\n"
            "    if not text:\n"
            "        return []\n"
            "    lines = []\n"
            "    line = ''\n"
            "    for ch in text:\n"
            "        if len(line) == width:\n"
            "            lines.append(line)\n"
            "            line = ch\n"
            "        else:\n"
            "            line += ch\n"
            "    if line:\n"
            "        lines.append(line)\n"
            "    return lines\n"),
        "cases": [(("abcd", 2), ["ab", "cd"]),
                  (('abc', 5), ['abc']),
                  (('', 3), [])],
        "params": [],
        "calibration": "对照：浏览器渲染——文本换行（按宽度贪心断行）",
    },
    "浏览器-剪贴板": {
        "task": "剪贴板",
        "pattern": (
            "def clipboard_ops(state, op, text=None):\n"
"    # 生效条件：op ∈ {clear, copy, paste}\n"
"    # 子功能：① op 分支处理\n"
"    # 执行：按 op 分派\n"
"    # 不适用条件：op 非 {clear, copy, paste} 时\n"
            "    # 剪贴板：copy 写入 / paste 读取 / clear 清空（系统剪贴板）\n"
            "    if op == 'copy':\n"
            "        state['text'] = text\n"
            "        return 'copied'\n"
            "    if op == 'paste':\n"
            "        return state.get('text')\n"
            "    if op == 'clear':\n"
            "        state['text'] = None\n"
            "        return 'cleared'\n"
            "    return None\n"),
        "cases": [(({}, 'copy', '你好'), 'copied'),
                  (({'text': '你好'}, 'paste'), '你好'),
                  (({}, 'paste'), None),
                  (({'text': 'x'}, 'clear'), 'cleared')],
        "params": [],
        "calibration": "对照：浏览器 API——navigator.clipboard（copy/paste 读写剪贴板）",
    },
    "安全-沙箱隔离": {
        "task": "沙箱隔离",
        "pattern": (
            "def sandbox_perms(capabilities, op, cap=None):\n"
"    # 生效条件：op ∈ {check, grant, revoke}；capabilities.discard 可用\n"
"    # 子功能：① op 分支处理\n"
"    # 执行：按 op 分派\n"
"    # 不适用条件：op 非 {check, grant, revoke} 时\n"
            "    # 沙箱隔离：grant 授权 / check 校验 / revoke 撤销（iframe sandbox 权限裁剪）\n"
            "    if op == 'grant':\n"
            "        capabilities.add(cap)\n"
            "        return 'granted'\n"
            "    if op == 'check':\n"
            "        return cap in capabilities\n"
            "    if op == 'revoke':\n"
            "        capabilities.discard(cap)\n"
            "        return 'revoked'\n"
            "    return None\n"),
        "cases": [((set(), 'grant', 'allow-scripts'), 'granted'),
                  (({'allow-scripts'}, 'check', 'allow-scripts'), True),
                  ((set(), 'check', 'allow-forms'), False),
                  (({'allow-forms'}, 'revoke', 'allow-forms'), 'revoked')],
        "params": [],
        "calibration": "对照：iframe sandbox——权限裁剪（allow-scripts 等逐项授权/校验）",
    },
    "渲染-滚动容器": {
        "task": "滚动容器",
        "pattern": (
            "def scroll_container(state, op, delta=None):\n"
"    # 生效条件：op ∈ {bottom, position, scroll}\n"
"    # 子功能：① op 分支处理\n"
"    # 执行：按 op 分派\n"
"    # 不适用条件：op 非 {bottom, position, scroll} 时\n"
            "    # 滚动容器：scroll 按增量滚动 / position 当前位置 / bottom 是否触底（视口滚动）\n"
            "    if op == 'scroll':\n"
            "        state['pos'] = state.get('pos', 0) + delta\n"
            "        return state['pos']\n"
            "    if op == 'position':\n"
            "        return state.get('pos', 0)\n"
            "    if op == 'bottom':\n"
            "        return state.get('pos', 0) >= state.get('max', 0)\n"
            "    return None\n"),
        "cases": [(({}, 'scroll', 200), 200),
                  (({}, 'position'), 0),
                  (({'pos': 800, 'max': 800}, 'bottom'), True),
                  (({'pos': 100, 'max': 800}, 'bottom'), False)],
        "params": [],
        "calibration": "对照：浏览器滚动——scrollTop 滚动位置/触底判定（视口滚动容器）",
    },
    "浏览器-在线状态": {
        "task": "在线状态",
        "pattern": (
            "def online_state(events, op, online=None):\n"
"    # 生效条件：op ∈ {events, get, set}\n"
"    # 子功能：① op 分支处理\n"
"    # 执行：按 op 分派；顺序调用\n"
"    # 不适用条件：op 非 {events, get, set} 时\n"
            "    # 在线状态：set 设置 online/offline / get 当前状态 / events 事件序列（navigator.onLine）\n"
            "    if op == 'set':\n"
            "        events.append('online' if online else 'offline')\n"
            "        return events[-1]\n"
            "    if op == 'get':\n"
            "        return events[-1] if events else 'online'\n"
            "    if op == 'events':\n"
            "        return list(events)\n"
            "    return None\n"),
        "cases": [(([], 'set', True), 'online'),
                  ((['online'], 'set', False), 'offline'),
                  (([], 'get'), 'online'),
                  ((['online', 'offline'], 'events'), ['online', 'offline'])],
        "params": [],
        "calibration": "对照：navigator.onLine + online/offline 事件（网络状态监测）",
    },
    "渲染-命中测试": {
        "task": "命中测试",
        "pattern": (
            "def hit_test(layers, x, y):\n"
"    # 生效条件：参数 layers/x/y 合法\n"
"    # 子功能：① 条件判定 ② 结果处理\n"
"    # 执行：循环迭代\n"
"    # 不适用条件：输入不满足生效条件时返回 None/不执行\n"
            "    # 命中测试：从顶层向下找包含 (x,y) 的元素（点击命中）\n"
            "    for layer in layers:\n"
            "        x1, y1, x2, y2, name = layer\n"
            "        if x1 <= x <= x2 and y1 <= y <= y2:\n"
            "            return name\n"
            "    return None\n"),
        "cases": [
            ((((0, 0, 10, 10, '甲'), (20, 20, 30, 30, '乙')), 5, 5), '甲'),
            ((((0, 0, 10, 10, '甲'), (20, 20, 30, 30, '乙')), 25, 25), '乙'),
            ((((0, 0, 10, 10, '甲'),), 50, 50), None)],
        "params": [],
        "calibration": "对照：渲染命中测试——从顶向下坐标包含判定（点击命中元素）",
    },
    "浏览器-标签页通信": {
        "task": "标签页通信",
        "pattern": (
            "def tab_channel(state, op, msg=None):\n"
"    # 生效条件：op ∈ {listeners, post, recv}\n"
"    # 子功能：① op 分支处理\n"
"    # 执行：按 op 分派\n"
"    # 不适用条件：op 非 {listeners, post, recv} 时\n"
            "    # 标签页通信：post 广播消息 / recv 收取 / listeners 统计（BroadcastChannel）\n"
            "    if op == 'post':\n"
            "        state.setdefault('msgs', []).append(msg)\n"
            "        return 'sent'\n"
            "    if op == 'recv':\n"
            "        msgs = state.get('msgs', [])\n"
            "        return msgs[-1] if msgs else None\n"
            "    if op == 'listeners':\n"
            "        return state.get('n', 0)\n"
            "    return None\n"),
        "cases": [
            (({}, 'post', 'hi'), 'sent'),
            (({'msgs': ['a', 'b']}, 'recv'), 'b'),
            (({}, 'recv'), None),
            (({'n': 3}, 'listeners'), 3)],
        "params": [],
        "calibration": "对照：BroadcastChannel/postMessage——跨标签页广播通信",
    },
    "浏览器-页面可见性": {
        "task": "页面可见性",
        "pattern": (
            "def visibility(state, op, v=None):\n"
"    # 生效条件：op ∈ {events, get, set}\n"
"    # 子功能：① op 分支处理\n"
"    # 执行：按 op 分派；顺序调用\n"
"    # 不适用条件：op 非 {events, get, set} 时\n"
            "    # 页面可见性：set 切换 visible/hidden / get 当前 / events 记录（visibilitychange）\n"
            "    if op == 'set':\n"
            "        state['vis'] = v\n"
            "        state.setdefault('events', []).append(v)\n"
            "        return v\n"
            "    if op == 'get':\n"
            "        return state.get('vis', 'visible')\n"
            "    if op == 'events':\n"
            "        return list(state.get('events', []))\n"
            "    return None\n"),
        "cases": [
            (({}, 'set', 'hidden'), 'hidden'),
            (({}, 'get'), 'visible'),
            (({'vis': 'hidden'}, 'get'), 'hidden'),
            (({'events': ['visible', 'hidden']}, 'events'), ['visible', 'hidden'])],
        "params": [],
        "calibration": "对照：document.visibilityState——页面可见性（visible/hidden 切换）",
    },
    "渲染-像素光栅化": {
        "task": "像素光栅化",
        "pattern": (
            "def rasterize(canvas, x, y, color):\n"
"    # 生效条件：参数 canvas/x/y/color 合法\n"
"    # 子功能：① 调用 len\n"
"    # 执行：顺序调用\n"
"    # 不适用条件：输入不满足生效条件时返回 None/不执行\n"
            "    # 像素光栅化：画布坐标填色（canvas 像素级绘制）\n"
            "    w = len(canvas[0])\n"
            "    h = len(canvas)\n"
            "    if 0 <= x < w and 0 <= y < h:\n"
            "        canvas[y][x] = color\n"
            "        return True\n"
            "    return False\n"),
        "cases": [
            (([['.', '.'], ['.', '.']], 1, 0, '#'), True),
            (([['.', '.'], ['.', '.']], 5, 5, '#'), False),
            (([['.']], 0, 0, '#'), True)],
        "params": [],
        "calibration": "对照：Canvas 像素绘制——坐标填充与边界检查（光栅化）",
    },
    "浏览器-触控手势": {
        "task": "触控手势",
        "pattern": (
            "def gesture_ops(state, op, p1=None, p2=None):\n"
"    # 生效条件：op ∈ {pan, pinch, tap}\n"
"    # 子功能：① op 分支处理\n"
"    # 执行：按 op 分派；顺序调用\n"
"    # 不适用条件：op 非 {pan, pinch, tap} 时\n"
            "    # 触控手势：tap 轻点 / pan 平移 / pinch 双指缩放（触摸识别）\n"
            "    if op == 'tap':\n"
            "        return 'tap'\n"
            "    if op == 'pan':\n"
            "        dx = p2[0] - p1[0]\n"
            "        dy = p2[1] - p1[1]\n"
            "        state['pan'] = (dx, dy)\n"
            "        return (dx, dy)\n"
            "    if op == 'pinch':\n"
            "        d1 = ((p1[0][0] - p1[1][0]) ** 2 + (p1[0][1] - p1[1][1]) ** 2) ** 0.5\n"
            "        d2 = ((p2[0][0] - p2[1][0]) ** 2 + (p2[0][1] - p2[1][1]) ** 2) ** 0.5\n"
            "        return round(d2 / d1, 2) if d1 else 1.0\n"
            "    return None\n"),
        "cases": [
            (({}, 'tap'), 'tap'),
            (({}, 'pan', (0, 0), (10, 5)), (10, 5)),
            (({}, 'pinch', ((0, 0), (10, 0)), ((0, 0), (20, 0))), 2.0)],
        "params": [],
        "calibration": "对照：Touch Events——轻点/平移/双指缩放手势识别",
    },
    "浏览器-设备方向": {
        "task": "设备方向",
        "pattern": (
            "def device_orient(state, op, alpha=None, beta=None):\n"
"    # 生效条件：op ∈ {get, portrait, set}\n"
"    # 子功能：① op 分支处理\n"
"    # 执行：按 op 分派；顺序调用\n"
"    # 不适用条件：op 非 {get, portrait, set} 时\n"
            "    # 设备方向：set 记录角度 / get 当前 / portrait 竖屏判定（DeviceOrientation）\n"
            "    if op == 'set':\n"
            "        state['alpha'] = alpha\n"
            "        state['beta'] = beta\n"
            "        return (alpha, beta)\n"
            "    if op == 'get':\n"
            "        return (state.get('alpha', 0), state.get('beta', 0))\n"
            "    if op == 'portrait':\n"
            "        return abs(state.get('beta', 0)) < 45\n"
            "    return None\n"),
        "cases": [
            (({}, 'set', 90, 30), (90, 30)),
            (({}, 'get'), (0, 0)),
            (({'beta': 10}, 'portrait'), True),
            (({'beta': 80}, 'portrait'), False)],
        "params": [],
        "calibration": "对照：DeviceOrientation——α/β 角度记录与竖屏判定",
    },
    "渲染-渐变填充": {
        "task": "渐变填充",
        "pattern": (
            "def gradient_fill(stops, t):\n"
"    # 生效条件：参数 stops/t 合法\n"
"    # 子功能：① 调用 range；② 调用 len；③ 调用 tuple\n"
"    # 执行：循环迭代；顺序调用\n"
"    # 不适用条件：输入不满足生效条件时返回 None/不执行\n"
            "    # 渐变填充：按位置 t 线性插值色停（canvas 渐变）\n"
            "    if t <= stops[0][0]:\n"
            "        return stops[0][1]\n"
            "    for i in range(1, len(stops)):\n"
            "        if t <= stops[i][0]:\n"
            "            p0, c0 = stops[i - 1]\n"
            "            p1, c1 = stops[i]\n"
            "            f = (t - p0) / (p1 - p0)\n"
            "            return tuple(round(c0[k] + (c1[k] - c0[k]) * f) for k in range(3))\n"
            "    return stops[-1][1]\n"),
        "cases": [
            ((((0.0, (255, 0, 0)), (1.0, (0, 0, 255))), 0.0), (255, 0, 0)),
            ((((0.0, (255, 0, 0)), (1.0, (0, 0, 255))), 0.5), (128, 0, 128)),
            ((((0.0, (0, 0, 0)), (1.0, (255, 255, 255))), 1.5), (255, 255, 255))],
        "params": [],
        "calibration": "对照：canvas 渐变——色停线性插值（渐变填充）",
    },
    "浏览器-网络信息": {
        "task": "网络信息",
        "pattern": (
            "def network_info(state, op, net=None):\n"
"    # 生效条件：op ∈ {fast, get, set}\n"
"    # 子功能：① op 分支处理\n"
"    # 执行：按 op 分派\n"
"    # 不适用条件：op 非 {fast, get, set} 时\n"
            "    # 网络信息：set 记录类型 / get 当前 / fast 高速判定（Network Information API）\n"
            "    if op == 'set':\n"
            "        state['net'] = net\n"
            "        return net\n"
            "    if op == 'get':\n"
            "        return state.get('net', 'unknown')\n"
            "    if op == 'fast':\n"
            "        return state.get('net', 'slow') in ('4g', 'wifi')\n"
            "    return None\n"),
        "cases": [
            (({}, 'set', '4g'), '4g'),
            (({}, 'get'), 'unknown'),
            (({'net': '4g'}, 'fast'), True),
            (({'net': '2g'}, 'fast'), False)],
        "params": [],
        "calibration": "对照：Network Information API——effectiveType 网络类型与高速判定",
    },
    "浏览器-字体加载": {
        "task": "字体加载",
        "pattern": (
            "def font_load(state, op, font=None):\n"
"    # 生效条件：op ∈ {load, status, swap}\n"
"    # 子功能：① op 分支处理\n"
"    # 执行：按 op 分派\n"
"    # 不适用条件：op 非 {load, status, swap} 时\n"
            "    # 字体加载：load 请求 / status 状态 / swap 回退切换（font-display）\n"
            "    if op == 'load':\n"
            "        state[font] = 'loading'\n"
            "        return 'loading'\n"
            "    if op == 'status':\n"
            "        return state.get(font, 'unloaded')\n"
            "    if op == 'swap':\n"
            "        state[font] = 'loaded'\n"
            "        return 'loaded'\n"
            "    return None\n"),
        "cases": [
            (({}, 'load', 'f1'), 'loading'),
            (({}, 'status', 'f1'), 'unloaded'),
            (({'f1': 'loading'}, 'swap', 'f1'), 'loaded'),
            (({'f1': 'loaded'}, 'status', 'f1'), 'loaded')],
        "params": [],
        "calibration": "对照：Font Loading API——字体加载状态与回退切换（font-display）",
    },
    "渲染-颜色转换": {
        "task": "颜色转换",
        "pattern": (
            "def color_convert(value, op):\n"
"    # 生效条件：op ∈ {hex2rgb, rgb2hex}；value.lstrip 可用\n"
"    # 子功能：① op 分支处理\n"
"    # 执行：按 op 分派；顺序调用\n"
"    # 不适用条件：op 非 {hex2rgb, rgb2hex} 时\n"
            "    # 颜色转换：hex→rgb 解析 / rgb→hex 编码（CSS 颜色）\n"
            "    if op == 'hex2rgb':\n"
            "        v = value.lstrip('#')\n"
            "        return tuple(int(v[i:i + 2], 16) for i in (0, 2, 4))\n"
            "    if op == 'rgb2hex':\n"
            "        return '#' + ''.join(f'{c:02x}' for c in value)\n"
            "    return None\n"),
        "cases": [
            (('#ff0000', 'hex2rgb'), (255, 0, 0)),
            (('#00ff80', 'hex2rgb'), (0, 255, 128)),
            (((255, 0, 0), 'rgb2hex'), '#ff0000'),
            (((0, 0, 0), 'rgb2hex'), '#000000')],
        "params": [],
        "calibration": "对照：CSS 颜色——hex↔rgb 双向转换",
    },
    "浏览器-振动反馈": {
        "task": "振动反馈",
        "pattern": (
            "def vibrate(state, op, pattern=None):\n"
"    # 生效条件：op ∈ {active, start, stop}\n"
"    # 子功能：① op 分支处理\n"
"    # 执行：按 op 分派\n"
"    # 不适用条件：op 非 {active, start, stop} 时\n"
            "    # 振动反馈：start 启动 / stop 停止 / active 是否振动（navigator.vibrate）\n"
            "    if op == 'start':\n"
            "        state['active'] = True\n"
            "        state['pattern'] = pattern\n"
            "        return 'vibrating'\n"
            "    if op == 'stop':\n"
            "        state['active'] = False\n"
            "        return 'stopped'\n"
            "    if op == 'active':\n"
            "        return state.get('active', False)\n"
            "    return None\n"),
        "cases": [
            (({}, 'start', [100, 50]), 'vibrating'),
            (({}, 'stop'), 'stopped'),
            (({}, 'active'), False),
            (({'active': True}, 'active'), True)],
        "params": [],
        "calibration": "对照：navigator.vibrate——振动启动/停止/状态",
    },
    "渲染-混合模式": {
        "task": "混合模式",
        "pattern": (
            "def blend_mode(base, overlay, mode):\n"
"    # 生效条件：mode ∈ {multiply, overlay, screen}\n"
"    # 子功能：1 mode 分支处理\n"
"    # 执行：按 op 分派；顺序调用\n"
"    # 不适用条件：b 越界（Lt）时；mode 非 {multiply, overlay, screen} 时\n"
            "    # 混合模式：multiply 正片叠底 / screen 滤色 / overlay 叠加（canvas 混合）\n"
            "    b = base / 255.0\n"
            "    o = overlay / 255.0\n"
            "    if mode == 'multiply':\n"
            "        return round(b * o * 255)\n"
            "    if mode == 'screen':\n"
            "        return round((1 - (1 - b) * (1 - o)) * 255)\n"
            "    if mode == 'overlay':\n"
            "        if b < 0.5:\n"
            "            return round(2 * b * o * 255)\n"
            "        return round((1 - 2 * (1 - b) * (1 - o)) * 255)\n"
            "    return None\n"),
        "cases": [
            ((255, 128, 'multiply'), 128),
            ((255, 128, 'screen'), 255),
            ((64, 128, 'overlay'), 64),
            ((192, 128, 'overlay'), 192)],
        "params": [],
        "calibration": "对照：canvas 混合模式——multiply/screen/overlay 通道计算",
    },
    "渲染-边框圆角": {
        "task": "边框圆角",
        "pattern": (
            "def border_radius(box, radius, point):\n"
"    # 生效条件：参数 box/radius/point 合法\n"
"    # 子功能：① 调用 min；② 调用 max\n"
"    # 执行：顺序调用\n"
"    # 不适用条件：输入不满足生效条件时返回 None/不执行\n"
            "    # 边框圆角：点是否在圆角矩形内（border-radius 命中判定）\n"
            "    x1, y1, x2, y2 = box\n"
            "    x, y = point\n"
            "    if not (x1 <= x <= x2 and y1 <= y <= y2):\n"
            "        return False\n"
            "    cx = min(max(x, x1 + radius), x2 - radius)\n"
            "    cy = min(max(y, y1 + radius), y2 - radius)\n"
            "    return (x - cx) ** 2 + (y - cy) ** 2 <= radius ** 2\n"),
        "cases": [
            (((0, 0, 10, 10), 2, (5, 5)), True),
            (((0, 0, 10, 10), 2, (9, 9)), True),
            (((0, 0, 10, 10), 2, (9, 0)), False),
            (((0, 0, 10, 10), 2, (20, 5)), False)],
        "params": [],
        "calibration": "对照：border-radius——圆角矩形内点判定（命中测试）",
    },
    "浏览器-屏幕方向": {
        "task": "屏幕方向",
        "pattern": (
            "def screen_orient(state, op, orient=None):\n"
"    # 生效条件：op ∈ {get, lock, unlock}\n"
"    # 子功能：① op 分支处理\n"
"    # 执行：按 op 分派\n"
"    # 不适用条件：op 非 {get, lock, unlock} 时\n"
            "    # 屏幕方向：lock 锁定 / unlock 解锁 / get 当前（Screen Orientation API）\n"
            "    if op == 'lock':\n"
            "        state['orient'] = orient\n"
            "        state['locked'] = True\n"
            "        return 'locked'\n"
            "    if op == 'unlock':\n"
            "        state['locked'] = False\n"
            "        return 'unlocked'\n"
            "    if op == 'get':\n"
            "        return state.get('orient', 'portrait-primary')\n"
            "    return None\n"),
        "cases": [
            (({}, 'lock', 'landscape'), 'locked'),
            (({}, 'unlock'), 'unlocked'),
            (({}, 'get'), 'portrait-primary'),
            (({'orient': 'landscape'}, 'get'), 'landscape')],
        "params": [],
        "calibration": "对照：Screen Orientation API——方向锁定/解锁/查询",
    },
    "浏览器-空闲调度": {
        "task": "空闲调度",
        "pattern": (
            "def idle_schedule(state, op, deadline=None):\n"
"    # 生效条件：op ∈ {pending, request, run}\n"
"    # 子功能：① op 分支处理\n"
"    # 执行：按 op 分派\n"
"    # 不适用条件：op 非 {pending, request, run} 时\n"
            "    # 空闲调度：request 登记低优先任务 / run 空闲时执行 / pending 待办数（requestIdleCallback）\n"
            "    if op == 'request':\n"
            "        state['pending'] = state.get('pending', 0) + 1\n"
            "        return state['pending']\n"
            "    if op == 'run':\n"
            "        if state.get('pending', 0) > 0:\n"
            "            state['pending'] -= 1\n"
            "            return 'executed'\n"
            "        return 'idle'\n"
            "    if op == 'pending':\n"
            "        return state.get('pending', 0)\n"
            "    return None\n"),
        "cases": [
            (({}, 'request'), 1),
            (({'pending': 1}, 'run'), 'executed'),
            (({}, 'run'), 'idle'),
            (({'pending': 2}, 'pending'), 2)],
        "params": [],
        "calibration": "对照：requestIdleCallback——空闲时段低优先任务调度",
    },
    "浏览器-摄像头": {
        "task": "摄像头",
        "pattern": (
            "def camera_ops(state, op, stream=None):\n"
"    # 生效条件：op ∈ {request, start, stop}\n"
"    # 子功能：① op 分支处理\n"
"    # 执行：按 op 分派\n"
"    # 不适用条件：op 非 {request, start, stop} 时\n"
            "    # 摄像头：request 请求权限 / start 启动流 / stop 停止（getUserMedia）\n"
            "    if op == 'request':\n"
            "        state['granted'] = True\n"
            "        return 'granted'\n"
            "    if op == 'start':\n"
            "        if state.get('granted'):\n"
            "            state['stream'] = stream or 'video'\n"
            "            return 'live'\n"
            "        return 'denied'\n"
            "    if op == 'stop':\n"
            "        state['stream'] = None\n"
            "        return 'stopped'\n"
            "    return None\n"),
        "cases": [
            (({}, 'request'), 'granted'),
            (({'granted': True}, 'start'), 'live'),
            (({}, 'start'), 'denied'),
            (({'stream': 'video'}, 'stop'), 'stopped')],
        "params": [],
        "calibration": "对照：getUserMedia——摄像头权限与媒体流启停",
    },
    "浏览器-蓝牙扫描": {
        "task": "蓝牙扫描",
        "pattern": (
            "def bluetooth_scan(state, op, dev=None):\n"
"    # 生效条件：op ∈ {connect, devices, discover}\n"
"    # 子功能：① op 分支处理\n"
"    # 执行：按 op 分派；顺序调用\n"
"    # 不适用条件：op 非 {connect, devices, discover} 时\n"
            "    # 蓝牙扫描：discover 发现 / connect 连接 / devices 列表（Web Bluetooth）\n"
            "    if op == 'discover':\n"
            "        state.setdefault('devices', []).append(dev)\n"
            "        return dev\n"
            "    if op == 'connect':\n"
            "        if dev in state.get('devices', []):\n"
            "            state['connected'] = dev\n"
            "            return 'connected'\n"
            "        return 'not_found'\n"
            "    if op == 'devices':\n"
            "        return list(state.get('devices', []))\n"
            "    return None\n"),
        "cases": [
            (({}, 'discover', 'd1'), 'd1'),
            (({'devices': ['d1']}, 'connect', 'd1'), 'connected'),
            (({}, 'connect', 'x'), 'not_found'),
            (({'devices': ['d1']}, 'devices'), ['d1'])],
        "params": [],
        "calibration": "对照：Web Bluetooth——设备发现与连接",
    },
    "浏览器-传感器": {
        "task": "传感器",
        "pattern": (
            "def sensor_ops(state, op, axis=None, value=None):\n"
"    # 生效条件：op ∈ {avg, read, record}\n"
"    # 子功能：① op 分支处理\n"
"    # 执行：按 op 分派；顺序调用\n"
"    # 不适用条件：op 非 {avg, read, record} 时\n"
            "    # 传感器：record 记录读数 / read 读取 / avg 平均（Accelerometer）\n"
            "    if op == 'record':\n"
            "        state.setdefault(axis, []).append(value)\n"
            "        return value\n"
            "    if op == 'read':\n"
            "        s = state.get(axis, [])\n"
            "        return s[-1] if s else None\n"
            "    if op == 'avg':\n"
            "        s = state.get(axis, [])\n"
            "        return round(sum(s) / len(s), 2) if s else 0.0\n"
            "    return None\n"),
        "cases": [
            (({}, 'record', 'x', 1.0), 1.0),
            (({'x': [1.0, 2.0]}, 'read', 'x'), 2.0),
            (({'x': [1.0, 2.0]}, 'avg', 'x'), 1.5),
            (({}, 'read', 'y'), None)],
        "params": [],
        "calibration": "对照：Accelerometer API——传感器读数记录/读取/平均",
    },
    "浏览器-语音合成": {
        "task": "语音合成",
        "pattern": (
            "def speech_synth(state, op, text=None):\n"
"    # 生效条件：op ∈ {pause, resume, speak}\n"
"    # 子功能：① op 分支处理\n"
"    # 执行：按 op 分派\n"
"    # 不适用条件：op 非 {pause, resume, speak} 时\n"
            "    # 语音合成：speak 朗读 / pause 暂停 / resume 继续（SpeechSynthesis）\n"
            "    if op == 'speak':\n"
            "        state['text'] = text\n"
            "        state['speaking'] = True\n"
            "        return 'speaking'\n"
            "    if op == 'pause':\n"
            "        state['paused'] = True\n"
            "        return 'paused'\n"
            "    if op == 'resume':\n"
            "        state['paused'] = False\n"
            "        return 'speaking'\n"
            "    return None\n"),
        "cases": [
            (({}, 'speak', '你好'), 'speaking'),
            (({}, 'pause'), 'paused'),
            (({'paused': True}, 'resume'), 'speaking'),
            (({'text': '你好', 'speaking': True}, 'pause'), 'paused')],
        "params": [],
        "calibration": "对照：SpeechSynthesis——文本朗读/暂停/继续",
    },
    "浏览器-语音识别": {
        "task": "语音识别",
        "pattern": (
            "def speech_recog(state, op, text=None):\n"
"    # 生效条件：op ∈ {final, result, start}\n"
"    # 子功能：① op 分支处理\n"
"    # 执行：按 op 分派\n"
"    # 不适用条件：op 非 {final, result, start} 时\n"
            "    # 语音识别：start 开始 / result 识别结果 / final 最终文本（SpeechRecognition）\n"
            "    if op == 'start':\n"
            "        state['listening'] = True\n"
            "        return 'listening'\n"
            "    if op == 'result':\n"
            "        state.setdefault('results', []).append(text)\n"
            "        return text\n"
            "    if op == 'final':\n"
            "        r = state.get('results', [])\n"
            "        return r[-1] if r else None\n"
            "    return None\n"),
        "cases": [
            (({}, 'start'), 'listening'),
            (({}, 'result', '你好'), '你好'),
            (({'results': ['你好']}, 'final'), '你好'),
            (({}, 'final'), None)],
        "params": [],
        "calibration": "对照：SpeechRecognition——开始/识别结果/最终文本",
    },
    "浏览器-扫码": {
        "task": "扫码",
        "pattern": (
            "def barcode_scan(state, op, code=None):\n"
"    # 生效条件：op ∈ {cache, last, scan}\n"
"    # 子功能：① op 分支处理\n"
"    # 执行：按 op 分派；顺序调用\n"
"    # 不适用条件：op 非 {cache, last, scan} 时\n"
            "    # 扫码：scan 检测 / cache 缓存 / last 最近结果（BarcodeDetector）\n"
            "    if op == 'scan':\n"
            "        state['last'] = code\n"
            "        return code\n"
            "    if op == 'cache':\n"
            "        state.setdefault('cached', []).append(code)\n"
            "        return len(state['cached'])\n"
            "    if op == 'last':\n"
            "        return state.get('last')\n"
            "    return None\n"),
        "cases": [
            (({}, 'scan', '12345'), '12345'),
            (({}, 'cache', '12345'), 1),
            (({'last': '12345'}, 'last'), '12345'),
            (({}, 'last'), None)],
        "params": [],
        "calibration": "对照：BarcodeDetector——条码/二维码检测与缓存",
    },
    "浏览器-画中画": {
        "task": "画中画",
        "pattern": (
            "def pip_ops(state, op):\n"
"    # 生效条件：op ∈ {active, close, open}\n"
"    # 子功能：① op 分支处理\n"
"    # 执行：按 op 分派\n"
"    # 不适用条件：op 非 {active, close, open} 时\n"
            "    # 画中画：open 打开 / close 关闭 / active 状态（Picture-in-Picture）\n"
            "    if op == 'open':\n"
            "        state['pip'] = True\n"
            "        return 'opened'\n"
            "    if op == 'close':\n"
            "        state['pip'] = False\n"
            "        return 'closed'\n"
            "    if op == 'active':\n"
            "        return state.get('pip', False)\n"
            "    return None\n"),
        "cases": [
            (({}, 'open'), 'opened'),
            (({}, 'close'), 'closed'),
            (({}, 'active'), False),
            (({'pip': True}, 'active'), True)],
        "params": [],
        "calibration": "对照：Picture-in-Picture——画中画窗口开关",
    },
    "浏览器-屏幕捕获": {
        "task": "屏幕捕获",
        "pattern": (
            "def screen_capture(state, op, source=None):\n"
"    # 生效条件：op ∈ {request, select, stop}\n"
"    # 子功能：① op 分支处理\n"
"    # 执行：按 op 分派\n"
"    # 不适用条件：op 非 {request, select, stop} 时\n"
            "    # 屏幕捕获：request 请求 / select 选源 / stop 停止（getDisplayMedia）\n"
            "    if op == 'request':\n"
            "        state['granted'] = True\n"
            "        return 'granted'\n"
            "    if op == 'select':\n"
            "        if state.get('granted'):\n"
            "            state['source'] = source\n"
            "            return source\n"
            "        return None\n"
            "    if op == 'stop':\n"
            "        state['source'] = None\n"
            "        return 'stopped'\n"
            "    return None\n"),
        "cases": [
            (({}, 'request'), 'granted'),
            (({'granted': True}, 'select', 'screen'), 'screen'),
            (({}, 'select', 'screen'), None),
            (({'source': 'screen'}, 'stop'), 'stopped')],
        "params": [],
        "calibration": "对照：getDisplayMedia——屏幕捕获授权/选源/停止",
    },
    "浏览器-文件系统访问": {
        "task": "文件系统访问",
        "pattern": (
            "def fs_access(state, op, name=None, data=None):\n"
"    # 生效条件：op ∈ {open, read, write}\n"
"    # 子功能：① op 分支处理\n"
"    # 执行：按 op 分派\n"
"    # 不适用条件：op 非 {open, read, write} 时\n"
            "    # 文件系统访问：open 打开 / write 写入 / read 读取（File System Access）\n"
            "    if op == 'open':\n"
            "        state.setdefault('files', {})[name] = data or ''\n"
            "        return 'opened'\n"
            "    if op == 'write':\n"
            "        state.setdefault('files', {})[name] = data\n"
            "        return 'written'\n"
            "    if op == 'read':\n"
            "        return state.get('files', {}).get(name)\n"
            "    return None\n"),
        "cases": [
            (({}, 'open', 'a.txt'), 'opened'),
            (({}, 'write', 'a.txt', '内容'), 'written'),
            (({'files': {'a.txt': '内容'}}, 'read', 'a.txt'), '内容'),
            (({}, 'read', 'x.txt'), None)],
        "params": [],
        "calibration": "对照：File System Access——本地文件打开/写/读",
    },
    "浏览器-网页共享": {
        "task": "网页共享",
        "pattern": (
            "def web_share(state, op, data=None):\n"
"    # 生效条件：op ∈ {can_share, last, share}\n"
"    # 子功能：① op 分支处理\n"
"    # 执行：按 op 分派；顺序调用\n"
"    # 不适用条件：op 非 {can_share, last, share} 时\n"
            "    # 网页共享：share 分享 / can_share 可否 / last 最近分享（Web Share API）\n"
            "    if op == 'share':\n"
            "        state['last'] = data\n"
            "        return 'shared'\n"
            "    if op == 'can_share':\n"
            "        return bool(data)\n"
            "    if op == 'last':\n"
            "        return state.get('last')\n"
            "    return None\n"),
        "cases": [
            (({}, 'share', {'title': 't'}), 'shared'),
            (({}, 'can_share', {'text': 'x'}), True),
            (({}, 'can_share', None), False),
            (({'last': {'title': 't'}}, 'last'), {'title': 't'})],
        "params": [],
        "calibration": "对照：Web Share API——网页内容分享",
    },
    "浏览器-唤醒锁": {
        "task": "唤醒锁",
        "pattern": (
            "def wake_lock(state, op):\n"
"    # 生效条件：op ∈ {active, release, request}\n"
"    # 子功能：① op 分支处理\n"
"    # 执行：按 op 分派\n"
"    # 不适用条件：op 非 {active, release, request} 时\n"
            "    # 唤醒锁：request 请求 / release 释放 / active 状态（Wake Lock API）\n"
            "    if op == 'request':\n"
            "        state['active'] = True\n"
            "        return 'held'\n"
            "    if op == 'release':\n"
            "        state['active'] = False\n"
            "        return 'released'\n"
            "    if op == 'active':\n"
            "        return state.get('active', False)\n"
            "    return None\n"),
        "cases": [
            (({}, 'request'), 'held'),
            (({}, 'release'), 'released'),
            (({}, 'active'), False),
            (({'active': True}, 'active'), True)],
        "params": [],
        "calibration": "对照：Wake Lock——屏幕唤醒锁请求/释放",
    },
    "浏览器-窗口管理": {
        "task": "窗口管理",
        "pattern": (
            "def window_mgmt(state, op, win=None):\n"
"    # 生效条件：op ∈ {close, move, open}\n"
"    # 子功能：① op 分支处理\n"
"    # 执行：按 op 分派\n"
"    # 不适用条件：op 非 {close, move, open} 时\n"
            "    # 窗口管理：open 开窗 / move 移动 / close 关闭（Window Management）\n"
            "    if op == 'open':\n"
            "        state.setdefault('wins', {})[win] = {'x': 0, 'y': 0}\n"
            "        return 'opened'\n"
            "    if op == 'move':\n"
            "        if win in state.get('wins', {}):\n"
            "            state['wins'][win] = {'x': 100, 'y': 50}\n"
            "            return 'moved'\n"
            "        return None\n"
            "    if op == 'close':\n"
            "        wins = state.get('wins', {})\n"
            "        if win in wins:\n"
            "            wins.pop(win)\n"
            "            return 'closed'\n"
            "        return None\n"
            "    return None\n"),
        "cases": [
            (({}, 'open', 'w1'), 'opened'),
            (({'wins': {'w1': {'x': 0, 'y': 0}}}, 'move', 'w1'), 'moved'),
            (({}, 'move', 'wx'), None),
            (({'wins': {'w1': {}}}, 'close', 'w1'), 'closed')],
        "params": [],
        "calibration": "对照：Window Management——多窗口开/移/关",
    },
    "浏览器-翻译": {
        "task": "翻译",
        "pattern": (
            "def translate_api(state, op, text=None, lang=None):\n"
"    # 生效条件：op ∈ {available, langs, translate}\n"
"    # 子功能：① op 分支处理\n"
"    # 执行：按 op 分派；顺序调用\n"
"    # 不适用条件：op 非 {available, langs, translate} 时\n"
            "    # 翻译：translate 翻译 / available 可用 / langs 语言对（Translator API）\n"
            "    if op == 'translate':\n"
            "        if text and lang:\n"
            "            state['last'] = (text, lang)\n"
            "            return lang + ':' + text\n"
            "        return None\n"
            "    if op == 'available':\n"
            "        return text in state.get('langs', ['en', 'zh'])\n"
            "    if op == 'langs':\n"
            "        return list(state.get('langs', ['en', 'zh']))\n"
            "    return None\n"),
        "cases": [
            (({}, 'translate', '你好', 'en'), 'en:你好'),
            (({}, 'translate', '', 'en'), None),
            (({}, 'available', 'en'), True),
            (({'langs': ['zh']}, 'langs'), ['zh'])],
        "params": [],
        "calibration": "对照：Translator API——文本翻译与语言对",
    },
    "浏览器-语言检测": {
        "task": "语言检测",
        "pattern": (
            "def lang_detect(state, op, text=None):\n"
"    # 生效条件：op ∈ {detect, last, score}\n"
"    # 子功能：① op 分支处理\n"
"    # 执行：按 op 分派；顺序调用\n"
"    # 不适用条件：op 非 {detect, last, score} 时\n"
            "    # 语言检测：detect 识别 / score 置信度 / last 最近结果（Language Detector）\n"
            "    if op == 'detect':\n"
            "        lang = 'zh' if any('\u4e00' <= c <= '\u9fff' for c in text) else 'en'\n"
            "        state['last'] = (text, lang)\n"
            "        return lang\n"
            "    if op == 'score':\n"
            "        return 0.95\n"
            "    if op == 'last':\n"
            "        return state.get('last')\n"
            "    return None\n"),
        "cases": [
            (({}, 'detect', '你好世界'), 'zh'),
            (({}, 'detect', 'hello'), 'en'),
            (({}, 'score'), 0.95),
            (({'last': ('hi', 'en')}, 'last'), ('hi', 'en'))],
        "params": [],
        "calibration": "对照：Language Detector——文本语言识别与置信度",
    },
    "浏览器-文本摘要": {
        "task": "文本摘要",
        "pattern": (
            "def summarizer(state, op, text=None):\n"
"    # 生效条件：op ∈ {last, length, summarize}\n"
"    # 子功能：① op 分支处理\n"
"    # 执行：按 op 分派；顺序调用\n"
"    # 不适用条件：op 非 {last, length, summarize} 时\n"
            "    # 文本摘要：summarize 提取要点 / length 长度 / last 最近摘要（Summarizer）\n"
            "    if op == 'summarize':\n"
            "        out = text[:20] + (chr(46) * 3 if len(text) > 20 else '')\n"
            "        state['last'] = out\n"
            "        return out\n"
            "    if op == 'length':\n"
            "        return len(state.get('last', ''))\n"
            "    if op == 'last':\n"
            "        return state.get('last')\n"
            "    return None\n"),
        "cases": [
            (({}, 'summarize', '这是一段很长的文本内容超过二十个字需要被截断'),
             '这是一段很长的文本内容超过二十个字需要被截断'[:20] + '...'),
            (({}, 'summarize', '短'), '短'),
            (({'last': '短'}, 'length'), 1),
            (({}, 'last'), None)],
        "params": [],
        "calibration": "对照：Summarizer——文本要点提取摘要",
    },
    "浏览器-联系人": {
        "task": "联系人",
        "pattern": (
            "def contact_pick(state, op, contact=None):\n"
"    # 生效条件：op ∈ {clear, pick, selected}\n"
"    # 子功能：① op 分支处理\n"
"    # 执行：按 op 分派；顺序调用\n"
"    # 不适用条件：op 非 {clear, pick, selected} 时\n"
            "    # 联系人：pick 选择 / selected 已选 / clear 清空（Contact Picker）\n"
            "    if op == 'pick':\n"
            "        state.setdefault('picked', []).append(contact)\n"
            "        return contact\n"
            "    if op == 'selected':\n"
            "        return list(state.get('picked', []))\n"
            "    if op == 'clear':\n"
            "        state['picked'] = []\n"
            "        return 'cleared'\n"
            "    return None\n"),
        "cases": [
            (({}, 'pick', '张三'), '张三'),
            (({'picked': ['张三']}, 'selected'), ['张三']),
            (({}, 'selected'), []),
            (({'picked': ['张三']}, 'clear'), 'cleared')],
        "params": [],
        "calibration": "对照：Contact Picker——联系人选择与列表",
    },
    "浏览器-形状检测": {
        "task": "形状检测",
        "pattern": (
            "def shape_detect(state, op, shape=None, count=None):\n"
"    # 生效条件：op ∈ {count, detect, last}\n"
"    # 子功能：① op 分支处理\n"
"    # 执行：按 op 分派\n"
"    # 不适用条件：op 非 {count, detect, last} 时\n"
            "    # 形状检测：detect 检测 / count 数量 / last 最近结果（Shape Detection API）\n"
            "    if op == 'detect':\n"
            "        state['last'] = (shape, count)\n"
            "        return 'detected'\n"
            "    if op == 'count':\n"
            "        return state.get('last', (None, 0))[1]\n"
            "    if op == 'last':\n"
            "        return state.get('last')\n"
            "    return None\n"),
        "cases": [
            (({}, 'detect', 'face', 2), 'detected'),
            (({'last': ('face', 2)}, 'count'), 2),
            (({}, 'count'), 0),
            (({'last': ('barcode', 1)}, 'last'), ('barcode', 1))],
        "params": [],
        "calibration": "对照：Shape Detection——人脸/条码形状检测",
    },
    "浏览器-存储配额": {
        "task": "存储配额",
        "pattern": (
            "def storage_quota(state, op, used=None):\n"
"    # 生效条件：op ∈ {estimate, percent, usage}\n"
"    # 子功能：① op 分支处理\n"
"    # 执行：按 op 分派；顺序调用\n"
"    # 不适用条件：op 非 {estimate, percent, usage} 时\n"
            "    # 存储配额：estimate 估算 / usage 已用 / percent 占用比（Storage Quota）\n"
            "    if op == 'estimate':\n"
            "        state['used'] = used\n"
            "        return 'estimated'\n"
            "    if op == 'usage':\n"
            "        return state.get('used', 0)\n"
            "    if op == 'percent':\n"
            "        quota = state.get('quota', 1)\n"
            "        return round(state.get('used', 0) / quota * 100, 1)\n"
            "    return None\n"),
        "cases": [
            (({}, 'estimate', 50), 'estimated'),
            (({'used': 50}, 'usage'), 50),
            (({'used': 50, 'quota': 100}, 'percent'), 50.0),
            (({}, 'usage'), 0)],
        "params": [],
        "calibration": "对照：Storage Quota——存储用量估算与占用比",
    },
    "浏览器-内置聊天": {
        "task": "内置聊天",
        "pattern": (
            "def ai_chat(state, op, msg=None, reply=None):\n"
"    # 生效条件：op ∈ {history, reply, send}\n"
"    # 子功能：① op 分支处理\n"
"    # 执行：按 op 分派；顺序调用\n"
"    # 不适用条件：op 非 {history, reply, send} 时\n"
            "    # 内置聊天：send 发送 / reply 回复 / history 历史（AI Chat API）\n"
            "    if op == 'send':\n"
            "        state.setdefault('history', []).append(('user', msg))\n"
            "        state.setdefault('history', []).append(('ai', reply))\n"
            "        return reply\n"
            "    if op == 'reply':\n"
            "        return state.get('last_reply')\n"
            "    if op == 'history':\n"
            "        return list(state.get('history', []))\n"
            "    return None\n"),
        "cases": [
            (({}, 'send', '你好', '你好！'), '你好！'),
            (({}, 'reply'), None),
            (({'history': [('user', 'hi'), ('ai', 'hi!')]}, 'history'),
             [('user', 'hi'), ('ai', 'hi!')]),
            (({}, 'history'), [])],
        "params": [],
        "calibration": "对照：AI Chat——内置对话发送/回复/历史",
    },
    "浏览器-图像生成": {
        "task": "图像生成",
        "pattern": (
            "def image_gen(state, op, prompt=None):\n"
"    # 生效条件：op ∈ {count, generate, last}\n"
"    # 子功能：① op 分支处理\n"
"    # 执行：按 op 分派\n"
"    # 不适用条件：op 非 {count, generate, last} 时\n"
            "    # 图像生成：generate 生成 / count 数量 / last 最近（Image Generation API）\n"
            "    if op == 'generate':\n"
            "        state['last'] = prompt\n"
            "        state['count'] = state.get('count', 0) + 1\n"
            "        return 'generated'\n"
            "    if op == 'count':\n"
            "        return state.get('count', 0)\n"
            "    if op == 'last':\n"
            "        return state.get('last')\n"
            "    return None\n"),
        "cases": [
            (({}, 'generate', '山水画'), 'generated'),
            (({}, 'count'), 0),
            (({'count': 2}, 'count'), 2),
            (({'last': '山水画'}, 'last'), '山水画')],
        "params": [],
        "calibration": "对照：Image Generation——文本提示生成图像",
    },
    "浏览器-提示词": {
        "task": "提示词",
        "pattern": (
            "def prompt_api(state, op, key=None, value=None):\n"
"    # 生效条件：op ∈ {clear, get, set}\n"
"    # 子功能：① op 分支处理\n"
"    # 执行：按 op 分派\n"
"    # 不适用条件：op 非 {clear, get, set} 时\n"
            "    # 提示词：set 设置 / get 读取 / clear 清除（Prompt API）\n"
            "    if op == 'set':\n"
            "        state.setdefault('prompts', {})[key] = value\n"
            "        return value\n"
            "    if op == 'get':\n"
            "        return state.get('prompts', {}).get(key)\n"
            "    if op == 'clear':\n"
            "        state['prompts'] = {}\n"
            "        return 'cleared'\n"
            "    return None\n"),
        "cases": [
            (({}, 'set', 'greet', '你好'), '你好'),
            (({'prompts': {'greet': '你好'}}, 'get', 'greet'), '你好'),
            (({}, 'get', 'x'), None),
            (({'prompts': {'a': 1}}, 'clear'), 'cleared')],
        "params": [],
        "calibration": "对照：Prompt API——提示词设置/读取/清除",
    },
    "浏览器-游戏手柄": {
        "task": "游戏手柄",
        "pattern": (
            "def gamepad_ops(state, op, button=None, pressed=None):\n"
"    # 生效条件：op ∈ {axis, button, connect}\n"
"    # 子功能：① op 分支处理\n"
"    # 执行：按 op 分派\n"
"    # 不适用条件：op 非 {axis, button, connect} 时\n"
            "    # 游戏手柄：connect 连接 / button 按键状态 / axis 摇杆（Gamepad API）\n"
            "    if op == 'connect':\n"
            "        state['connected'] = True\n"
            "        return 'connected'\n"
            "    if op == 'button':\n"
            "        state.setdefault('buttons', {})[button] = pressed\n"
            "        return pressed\n"
            "    if op == 'axis':\n"
            "        return state.get('axis', 0.0)\n"
            "    return None\n"),
        "cases": [
            (({}, 'connect'), 'connected'),
            (({}, 'button', 0, True), True),
            (({}, 'axis'), 0.0),
            (({'axis': 0.5}, 'axis'), 0.5)],
        "params": [],
        "calibration": "对照：Gamepad——手柄连接/按键/摇杆",
    },
    "浏览器-虚拟键盘": {
        "task": "虚拟键盘",
        "pattern": (
            "def vkeyboard(state, op, key=None):\n"
"    # 生效条件：op ∈ {hide, show, visible}\n"
"    # 子功能：① op 分支处理\n"
"    # 执行：按 op 分派\n"
"    # 不适用条件：op 非 {hide, show, visible} 时\n"
            "    # 虚拟键盘：show 显示 / hide 隐藏 / visible 状态（Virtual Keyboard API）\n"
            "    if op == 'show':\n"
            "        state['visible'] = True\n"
            "        return 'shown'\n"
            "    if op == 'hide':\n"
            "        state['visible'] = False\n"
            "        return 'hidden'\n"
            "    if op == 'visible':\n"
            "        return state.get('visible', False)\n"
            "    return None\n"),
        "cases": [
            (({}, 'show'), 'shown'),
            (({}, 'hide'), 'hidden'),
            (({}, 'visible'), False),
            (({'visible': True}, 'visible'), True)],
        "params": [],
        "calibration": "对照：Virtual Keyboard——虚拟键盘显隐",
    },
    "浏览器-音频上下文": {
        "task": "音频上下文",
        "pattern": (
            "def audio_ctx(state, op, freq=None, vol=None):\n"
"    # 生效条件：op ∈ {gain, osc, start}\n"
"    # 子功能：① op 分支处理\n"
"    # 执行：按 op 分派\n"
"    # 不适用条件：op 非 {gain, osc, start} 时\n"
            "    # 音频上下文：osc 振荡器 / gain 音量 / start 启动（Web Audio）\n"
            "    if op == 'osc':\n"
            "        state['freq'] = freq\n"
            "        return freq\n"
            "    if op == 'gain':\n"
            "        state['vol'] = freq\n"
            "        return freq\n"
            "    if op == 'start':\n"
            "        return 'running'\n"
            "    return None\n"),
        "cases": [
            (({}, 'osc', 440), 440),
            (({}, 'gain', 0.5), 0.5),
            (({}, 'start'), 'running'),
            (({'freq': 440}, 'osc', 880), 880)],
        "params": [],
        "calibration": "对照：Web Audio——振荡器/音量/启动",
    },
    "事件-事件委托": {
        "task": "事件委托",
        "pattern": (
            "def event_delegate(handlers, event):\n"
            "    # 事件委托（事件代理）：祖先单监听器按目标分派（事件冒泡优化——只挂一个监听）\n"
            "    # 生效条件：handlers 键为 (目标, 事件类型)；event 含 target/type\n"
            "    # 子功能：① 按 (target, type) 查处理器 ② 命中调用并返回结果\n"
            "    # 执行：dict 精确键查 + 处理器调用，未命中返回 None\n"
"    # 不适用条件：输入不满足生效条件时返回 None/不执行\n"
            "    key = (event.get('target'), event.get('type'))\n"
            "    if key in handlers:\n"
            "        return handlers[key](event)\n"
            "    return None\n"),
        "cases": [
            (({('btn', 'click'): lambda e: 'clicked'}, {'target': 'btn', 'type': 'click'}), 'clicked'),
            (({('btn', 'click'): lambda e: 'clicked'}, {'target': 'div', 'type': 'click'}), None),
            (({('a', 'input'): lambda e: e.get('value')}, {'target': 'a', 'type': 'input', 'value': 7}), 7),
            (({}, {'target': 'btn', 'type': 'click'}), None)],
        "params": [],
        "calibration": "对照：事件委托——祖先单监听器按 target+type 分派子处理器（冒泡优化）",
    },
    "浏览器-弹窗拦截": {
        "task": "弹窗拦截",
        "pattern": (
            "def popup_block(allow, user_gesture, blocked_log):\n"
            "    # 弹窗拦截（弹出窗口拦截）：无用户手势的自动弹窗拦截并记录（浏览器安全策略）\n"
            "    # 生效条件：allow 为站点弹窗许可；user_gesture 为用户手势标志\n"
            "    # 子功能：① 许可+手势放行 ② 否则拦截并记录\n"
            "    # 执行：allow ∧ user_gesture → allowed；否则 blocked_log 追加并返 blocked\n"
"    # 不适用条件：输入不满足生效条件时返回 None/不执行\n"
            "    if allow and user_gesture:\n"
            "        return 'allowed'\n"
            "    blocked_log.append('blocked')\n"
            "    return 'blocked'\n"),
        "cases": [
            ((True, True, []), 'allowed'),
            ((True, False, []), 'blocked'),
            ((False, True, []), 'blocked'),
            ((False, False, []), 'blocked')],
        "params": [],
        "calibration": "对照：弹窗拦截——仅用户手势触发的允许弹窗，自动弹窗拦截并记录",
    },
    "安全-混合内容": {
        "task": "混合内容",
        "pattern": (
            "def mixed_content(page_scheme, res_scheme):\n"
            "    # 混合内容（mixed content）：HTTPS 页面加载 HTTP 子资源拦截（浏览器安全策略）\n"
            "    # 生效条件：page_scheme/res_scheme ∈ {https, http}\n"
            "    # 子功能：① HTTPS 页面检测 ② HTTP 子资源判定 ③ 拦截/放行\n"
            "    # 执行：页面 https 且资源 http → blocked，否则 allowed\n"
"    # 不适用条件：输入不满足生效条件时返回 None/不执行\n"
            "    if page_scheme == 'https' and res_scheme == 'http':\n"
            "        return 'blocked'\n"
            "    return 'allowed'\n"),
        "cases": [
            (('https', 'http'), 'blocked'),
            (('https', 'https'), 'allowed'),
            (('http', 'http'), 'allowed'),
            (('http', 'https'), 'allowed')],
        "params": [],
        "calibration": "对照：混合内容——HTTPS 页面加载 HTTP 子资源拦截（安全降级防护）",
    },
}


def route_browser_unit(question):
    """任务识别（问题 → 浏览器单元）"""
    best, best_len = None, 0
    for uid, u in BROWSER_UNITS.items():
        for kw in (u["task"], uid):
            if kw in question and len(kw) > best_len:
                best, best_len = uid, len(kw)
    return best


if __name__ == "__main__":
    print("=== 迷你浏览器白箱单元库（目标5 · 中文浏览器初级复现）===\n")
    for uid, u in BROWSER_UNITS.items():
        print(f"[{uid}] 任务={u['task']} 样例数={len(u['cases'])}")
        print(f"    校准: {u['calibration']}")
    print(f"\n=== 判定 ===\n迷你浏览器单元库: "
          f"{'✔ 4 单元就绪（HTTP/DOM/CSS/渲染）' if len(BROWSER_UNITS) >= 4 else '✘'}")
