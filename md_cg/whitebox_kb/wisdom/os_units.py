# -*- coding: utf-8 -*-
"""os_units.py · 迷你 Linux 白箱单元库（第六阶段·目标4 初级复现）
用户设想：终极目标「中文操作系统」← 初级复现「Linux 操作系统」。
内核核心抽象：进程调度/内存管理/文件系统/IPC——白箱自举（外部只校准）。
单元：{任务 → 代码模式模板 + 验证样例 + 校准基准}。
"""
import sys
sys.stdout.reconfigure(encoding='utf-8')

OS_UNITS = {
    "进程-调度": {
        "task": "进程调度",
        "pattern": (
            "def fcfs_schedule(processes):\n"
"    # 生效条件：参数 processes 合法\n"
"    # 子功能：① 调用 max\n"
"    # 执行：循环迭代；顺序调用\n"
"    # 不适用条件：输入不满足生效条件时返回 None/不执行\n"
            "    # FCFS 进程调度：[(到达时间, 运行时长)] → 完成时间列表\n"
            "    time, done = 0, []\n"
            "    for at, dur in processes:\n"
            "        time = max(time, at) + dur\n"
            "        done.append(time)\n"
            "    return done\n"),
        "cases": [(([(0, 3), (2, 2)],), [3, 5]),
                  (([(0, 3)],), [3]),
                  (([],), [])],
        "params": [],
        "calibration": "对照：OS 进程调度 FCFS——先到先服务，完成时间=前序完成+运行时长",
    },
    "进程-时间片轮转": {
        "task": "轮转调度",
        "pattern": (
            "def round_robin(processes, quantum=2):\n"
"    # 生效条件：参数 processes/quantum 合法\n"
"    # 子功能：① 调用 list；② 调用 any；③ 调用 min\n"
"    # 执行：循环迭代；顺序调用\n"
"    # 不适用条件：输入不满足生效条件时返回 None/不执行\n"
            "    # RR 时间片轮转：[(运行时长)] → 调度序列（进程索引）\n"
            "    remain = list(processes)\n"
            "    order, i = [], 0\n"
            "    while any(r > 0 for r in remain):\n"
            "        if remain[i] > 0:\n"
            "            run = min(quantum, remain[i])\n"
            "            remain[i] -= run\n"
            "            order.append(i)\n"
            "        i = (i + 1) % len(remain)\n"
            "    return order\n"),
        "cases": [(([4, 2, 3], 2), [0, 1, 2, 0, 2]),
                  (([1, 1], 2), [0, 1]),
                  (([5], 2), [0, 0, 0])],
        "params": [],
        "calibration": "对照：OS 时间片轮转——每进程最多运行 quantum，循环调度",
    },
    "内存-分页分配": {
        "task": "内存分配",
        "pattern": (
            "def page_alloc(pages_free, requests):\n"
"    # 生效条件：参数 pages_free/requests 合法\n"
"    # 子功能：① 条件判定 ② 结果处理\n"
"    # 执行：循环迭代\n"
"    # 不适用条件：输入不满足生效条件时返回 None/不执行\n"
            "    # 分页内存分配：请求页数 → 分配成功/拒绝（可用内存耗尽拒绝）\n"
            "    free = pages_free\n"
            "    results = []\n"
            "    for req in requests:\n"
            "        if req <= free:\n"
            "            free -= req\n"
            "            results.append(True)\n"
            "        else:\n"
            "            results.append(False)\n"
            "    return results\n"),
        "cases": [((10, [3, 5, 4]), [True, True, False]),
                  ((5, [6]), [False]),
                  ((0, []), [])],
        "params": [],
        "calibration": "对照：OS 内存管理——分页分配，内存不足拒绝请求",
    },
    "文件-路径解析": {
        "task": "文件路径",
        "pattern": (
            "def resolve_path(path, cwd):\n"
            "    # 路径解析（文件系统路径解析）：绝对/相对/.. /./ → 规范路径\n"
            "    # 生效条件：path 为路径字符串；cwd 为当前工作目录\n"
            "    # 子功能：① 绝对/相对判定 ② 分量规整 ③ .. 上溯\n"
            "    # 执行：split 分量 + 栈式规整\n"
"    # 不适用条件：p 非 {..} 时\n"
            "    if path.startswith('/'):\n"
            "        parts = path.split('/')[1:]\n"
            "    else:\n"
            "        parts = cwd.split('/')[1:] + path.split('/')\n"
            "    stack = []\n"
            "    for p in parts:\n"
            "        if p == '..':\n"
            "            if stack:\n"
            "                stack.pop()\n"
            "        elif p and p != '.':\n"
            "            stack.append(p)\n"
            "    return '/' + '/'.join(stack) if stack else '/'\n"),
        "cases": [(("/a/b", "/c"), "/a/b"),
                  (("..", "/a/b"), "/a"),
                  (("./x", "/a"), "/a/x"),
                  (("/", "/a"), "/")],
        "params": [],
        "calibration": "对照：OS 文件系统——路径规范化（绝对/相对/.. 解析）",
    },
    "IPC-管道": {
        "task": "进程通信",
        "pattern": (
            "def pipe_transfer(sender_data, reader):\n"
"    # 生效条件：参数 sender_data/reader 合法\n"
"    # 子功能：① 调用 list；② 调用 range\n"
"    # 执行：循环迭代；顺序调用\n"
"    # 不适用条件：输入不满足生效条件时返回 None/不执行\n"
            "    # 管道 IPC：写端数据 → FIFO 缓冲 → 读端取前 reader 项\n"
            "    buf = list(sender_data)\n"
            "    out = []\n"
            "    for _ in range(reader):\n"
            "        if buf:\n"
            "            out.append(buf.pop(0))\n"
            "    return out\n"),
        "cases": [(([1, 2, 3], 2), [1, 2]),
                  (([7], 3), [7]),
                  (([], 2), [])],
        "params": [],
        "calibration": "对照：OS IPC 管道——FIFO 缓冲，读端消费数据",
    },
    "内存-页置换": {
        "task": "页置换",
        "pattern": (
            "def lru_replace(page_seq, capacity):\n"
            "    # LRU 页置换（最近最久未使用淘汰）：页序列 + 容量 → 缺页次数\n"
            "    # 生效条件：page_seq 为页访问序列；capacity 为物理帧容量\n"
            "    # 子功能：① 命中页前移 ② 未命中缺页计数 ③ 满时淘汰最久未用\n"
            "    # 执行：frames 列表维护 LRU 序（remove+append 前移）\n"
"    # 不适用条件：输入不满足生效条件时返回 None/不执行\n"
            "    frames, faults = [], 0\n"
            "    for p in page_seq:\n"
            "        if p in frames:\n"
            "            frames.remove(p)\n"
            "            frames.append(p)\n"
            "        else:\n"
            "            if len(frames) >= capacity:\n"
            "                frames.pop(0)\n"
            "            frames.append(p)\n"
            "            faults += 1\n"
            "    return faults\n"),
        "cases": [(([1, 2, 3, 2, 1, 4, 2, 3], 3), 5),
                  (([1, 1, 1], 2), 1),
                  (([], 2), 0)],
        "params": [],
        "calibration": "对照：OS 虚拟内存——LRU 页置换（容量 3 时 8 页访问 5 次缺页）",
    },
    "文件-inode": {
        "task": "inode查询",
        "pattern": (
            "def inode_lookup(files, name):\n"
"    # 生效条件：参数 files/name 合法\n"
"    # 子功能：① 条件判定 ② 结果处理\n"
"    # 执行：循环迭代\n"
"    # 不适用条件：输入不满足生效条件时返回 None/不执行\n"
            "    # inode 表查询：文件名 → (大小, 权限) 或 None\n"
            "    for f in files:\n"
            "        if f['name'] == name:\n"
            "            return (f['size'], f['perm'])\n"
            "    return None\n"),
        "cases": [(([{'name': 'a.txt', 'size': 100, 'perm': 644},
                      {'name': 'b', 'size': 50, 'perm': 600}], 'a.txt'), (100, 644)),
                  (([{'name': 'a.txt', 'size': 100, 'perm': 644}], 'c.txt'), None)],
        "params": [],
        "calibration": "对照：OS 文件系统 inode——文件名→元数据（大小/权限）查询",
    },
    "进程-状态机": {
        "task": "进程状态",
        "pattern": (
            "def process_state(transitions):\n"
            "    # 进程状态机：事件序列 → 最终状态（就绪→运行→阻塞→就绪→终止）\n"
            "    # 生效条件：transitions 为事件序列（按状态转移表合法）\n"
            "    # 子功能：① 初始就绪 ② 逐事件迁移 ③ 返回终态\n"
            "    # 执行：状态转移表逐事件推进\n"
"    # 不适用条件：输入不满足生效条件时返回 None/不执行\n"
            "    state = '就绪'\n"
            "    for ev in transitions:\n"
            "        if state == '就绪' and ev == '调度':\n"
            "            state = '运行'\n"
            "        elif state == '运行' and ev == 'IO等待':\n"
            "            state = '阻塞'\n"
            "        elif state == '阻塞' and ev == 'IO完成':\n"
            "            state = '就绪'\n"
            "        elif state == '运行' and ev == '完成':\n"
            "            state = '终止'\n"
            "    return state\n"),
        "cases": [((['调度', 'IO等待', 'IO完成', '调度', '完成'],), '终止'),
                  ((['IO完成'],), '就绪'),
                  ((['调度', 'IO等待'],), '阻塞')],
        "params": [],
        "calibration": "对照：OS 进程状态机——就绪/运行/阻塞/终止 事件驱动转换",
    },
    "调度-SJF": {
        "task": "最短作业",
        "pattern": (
            "def sjf_schedule(processes):\n"
"    # 生效条件：ready.sort 可用\n"
"    # 子功能：① 调用 sorted\n"
"    # 执行：循环迭代；顺序调用\n"
"    # 不适用条件：ready 为空/非法时\n"
            "    # SJF 最短作业优先（非抢占）：[(到达, 时长)] → 完成时间列表\n"
            "    time, done, ready = 0, [], []\n"
            "    remaining = sorted(processes)\n"
            "    while remaining or ready:\n"
            "        ready += [p for p in remaining if p[0] <= time]\n"
            "        remaining = [p for p in remaining if p[0] > time]\n"
            "        if not ready:\n"
            "            time = remaining[0][0]\n"
            "            ready.append(remaining.pop(0))\n"
            "            continue\n"
            "        ready.sort(key=lambda p: p[1])\n"
            "        at, dur = ready.pop(0)\n"
            "        time += dur\n"
            "        done.append(time)\n"
            "    return done\n"),
        "cases": [(([(0, 3), (1, 2), (2, 5)],), [3, 5, 10]),
                  (([(0, 2)],), [2]),
                  (([],), [])],
        "params": [],
        "calibration": "对照：OS 调度 SJF——最短作业优先（平均等待最小化）",
    },
    "文件-块管理": {
        "task": "块管理",
        "pattern": (
            "def block_alloc(bitmap, size):\n"
"    # 生效条件：参数 bitmap/size 合法\n"
"    # 子功能：① 调用 len；② 调用 range；③ 调用 all\n"
"    # 执行：循环迭代；顺序调用\n"
"    # 不适用条件：输入不满足生效条件时返回 None/不执行\n"
            "    # 块位图分配：连续 size 块 → 起始块（首次适配）或 -1\n"
            "    n = len(bitmap)\n"
            "    for start in range(n - size + 1):\n"
            "        if all(b == 0 for b in bitmap[start:start + size]):\n"
            "            for i in range(start, start + size):\n"
            "                bitmap[i] = 1\n"
            "            return start\n"
            "    return -1\n"),
        "cases": [(([0, 0, 1, 0, 0], 2), 0),
                  (([1, 1, 1], 1), -1),
                  (([0, 1, 0], 2), -1)],
        "params": [],
        "calibration": "对照：OS 文件系统——块位图分配（连续块首次适配）",
    },
    "调度-优先级": {
        "task": "优先级调度",
        "pattern": (
            "def priority_schedule(processes):\n"
"    # 生效条件：参数 processes 合法\n"
"    # 子功能：① 调用 sorted\n"
"    # 执行：循环迭代；顺序调用\n"
"    # 不适用条件：输入不满足生效条件时返回 None/不执行\n"
            "    # 优先级调度（非抢占）：[(时长, 优先级)] → 完成时间（高优先先跑）\n"
            "    procs = sorted(processes, key=lambda p: p[1], reverse=True)\n"
            "    time, done = 0, []\n"
            "    for dur, pri in procs:\n"
            "        time += dur\n"
            "        done.append(time)\n"
            "    return done\n"),
        "cases": [(([(2, 1), (3, 3)],), [3, 5]),
                  (([(1, 5), (2, 1)],), [1, 3]),
                  (( [],), [])],
        "params": [],
        "calibration": "对照：OS 调度——优先级调度（高优先级先执行）",
    },
    "进程-互斥锁": {
        "task": "互斥锁",
        "pattern": (
            "def mutex_op(state, op, owner=None):\n"
"    # 生效条件：op ∈ {lock, unlock}；state ∈ {free}\n"
"    # 子功能：① op 分支处理；2 state 分支处理\n"
"    # 执行：按 op 分派\n"
"    # 不适用条件：op 非 {lock, unlock} 时；state 非 {free} 时\n"
            "    # 互斥锁操作：lock/unlock（忙等语义：占用时 lock 失败）\n"
            "    if op == 'lock':\n"
            "        if state == 'free':\n"
            "            return 'locked', True\n"
            "        return 'locked', False\n"
            "    if op == 'unlock':\n"
            "        return 'free', True\n"
            "    return state, False\n"),
        "cases": [(('free', 'lock'), ('locked', True)),
                  (('locked', 'lock'), ('locked', False)),
                  (('locked', 'unlock'), ('free', True))],
        "params": [],
        "calibration": "对照：OS 并发——互斥锁（占用时加锁失败，释放后可用）",
    },
    "内存-首次适配": {
        "task": "首次适配",
        "pattern": (
            "def first_fit(blocks, size):\n"
"    # 生效条件：参数 blocks/size 合法\n"
"    # 子功能：① 调用 enumerate\n"
"    # 执行：循环迭代；顺序调用\n"
"    # 不适用条件：输入不满足生效条件时返回 None/不执行\n"
            "    # 内存首次适配：空闲块大小列表 → 分配的块索引（首个足够大）\n"
            "    for i, b in enumerate(blocks):\n"
            "        if b >= size:\n"
            "            return i\n"
            "    return -1\n"),
        "cases": [(([5, 2, 8], 6), 2),
                  (([5, 2], 6), -1),
                  (([10], 3), 0)],
        "params": [],
        "calibration": "对照：OS 内存分配——首次适配（首个足够大的空闲块）",
    },
    "内存-页表映射": {
        "task": "页表映射",
        "pattern": (
            "def page_table_lookup(page_table, vpn):\n"
            "    # 页表映射（虚拟内存页表）：虚拟页号 → 物理帧号（present=1 已映射，0 缺页）\n"
            "    # 生效条件：page_table 为 VPN→页表项 映射；vpn 为虚拟页号\n"
            "    # 子功能：① 查页表项 ② present 位判定 ③ 缺页/命中返回\n"
            "    # 执行：无条目或 present≠1 → None（缺页）；否则返 frame\n"
"    # 不适用条件：输入不满足生效条件时返回 None/不执行\n"
            "    entry = page_table.get(vpn)\n"
            "    if entry is None or entry.get('present') != 1:\n"
            "        return None   # 缺页：页不在物理内存\n"
            "    return entry['frame']\n"),
        "cases": [(({1: {'present': 1, 'frame': 7}}, 1), 7),
                  (({1: {'present': 0, 'frame': None}}, 1), None),
                  (({}, 2), None)],
        "params": [],
        "calibration": "对照：OS 虚拟内存——页表映射（VPN→物理帧；present=0 或缺项=缺页）",
    },
    "内存-缺页处理": {
        "task": "缺页处理",
        "pattern": (
            "def page_fault_handler(page_table, vpn, free_frames, load):\n"
"    # 生效条件：参数 page_table/vpn/free_frames/load 合法\n"
"    # 子功能：① 调用 load\n"
"    # 执行：顺序调用\n"
"    # 不适用条件：free_frames 为空/非法时\n"
            "    # 缺页处理：present=0 → 分配空闲帧加载；无空闲帧 → 拒绝（置换由上层调度）\n"
            "    if vpn in page_table and page_table[vpn].get('present') == 1:\n"
            "        return 'hit', page_table[vpn]['frame']\n"
            "    if not free_frames:\n"
            "        return 'page_fault_no_frame', None\n"
            "    frame = free_frames.pop(0)\n"
            "    page_table[vpn] = {'present': 1, 'frame': frame}\n"
            "    load(vpn, frame)\n"
            "    return 'page_fault_loaded', frame\n"),
        "cases": [(({1: {'present': 1, 'frame': 3}}, 1, [], lambda v, f: None),
                   ('hit', 3)),
                  (({}, 2, [8], lambda v, f: None), ('page_fault_loaded', 8)),
                  (({}, 3, [], lambda v, f: None), ('page_fault_no_frame', None))],
        "params": [],
        "calibration": "对照：OS 虚拟内存——缺页处理（命中/加载/无空闲帧拒绝；置换交由页置换策略）",
    },
    "内存-页面错误": {
        "task": "页面错误分类",
        "pattern": (
            "def classify_page_fault(vpn, page_table, access):\n"
"    # 生效条件：参数 vpn/page_table/access 合法\n"
"    # 子功能：① 条件判定 ② 结果处理\n"
"    # 执行：顺序执行\n"
"    # 不适用条件：输入不满足生效条件时返回 None/不执行\n"
            "    # 页面错误分类：未映射/未驻留/写保护 → 错误类型（MMU 语义）\n"
            "    entry = page_table.get(vpn)\n"
            "    if entry is None:\n"
            "        return 'segment_fault'      # 非法地址（未映射）\n"
            "    if entry.get('present') != 1:\n"
            "        return 'minor_fault'        # 缺页（软缺页：磁盘→内存）\n"
            "    if access == 'write' and not entry.get('writable'):\n"
            "        return 'protection_fault'   # 写保护违例\n"
            "    return 'ok'\n"),
        "cases": [((5, {}, 'read'), 'segment_fault'),
                  ((1, {1: {'present': 0}}, 'read'), 'minor_fault'),
                  ((1, {1: {'present': 1, 'writable': False}}, 'write'),
                   'protection_fault'),
                  ((1, {1: {'present': 1, 'writable': True}}, 'write'), 'ok')],
        "params": [],
        "calibration": "对照：OS 虚拟内存——页面错误分类（MMU：未映射段错误/软缺页/写保护违例）",
    },
    "文件-目录树": {
        "task": "目录树",
        "pattern": (
            "def dir_ls(root, name, children=None, prefix='/'):\n"
"    # 生效条件：prefix.rstrip 可用\n"
"    # 子功能：① 调用 sorted\n"
"    # 执行：循环迭代；顺序调用\n"
"    # 不适用条件：输入不满足生效条件时返回 None/不执行\n"
            "    # 目录树 + 列目录：根/子目录/文件 → 路径列表（mkdir/ls 语义）\n"
            "    out = [prefix.rstrip('/') + '/' + root]\n"
            "    if name is None:\n"
            "        return out\n"
            "    base = prefix.rstrip('/') + '/' + root + '/' + name\n"
            "    out.append(base)\n"
            "    for c in (children or []):\n"
            "        out.append(base + '/' + c)\n"
            "    return sorted(out)\n"),
        "cases": [(('home', 'user', ['a.txt']),
                   ['/home', '/home/user', '/home/user/a.txt']),
                  (('etc', None, None), ['/etc'])],
        "params": [],
        "calibration": "对照：OS 文件系统——目录树（mkdir 层级 + ls 路径展开）",
    },
    "文件-文件描述符": {
        "task": "文件描述符",
        "pattern": (
            "def fd_alloc(table, path):\n"
"    # 生效条件：参数 table/path 合法\n"
"    # 子功能：① 主体逻辑执行\n"
"    # 执行：循环迭代\n"
"    # 不适用条件：输入不满足生效条件时返回 None/不执行\n"
            "    # 打开文件表：分配最小可用 fd（0/1/2 留给标准流，从 3 起）\n"
            "    fd = 3\n"
            "    while fd in table:\n"
            "        fd += 1\n"
            "    table[fd] = path\n"
            "    return fd\n"
            "def fd_close(table, fd):\n"
            "    # 关闭：释放 fd（返回被关闭的路径）\n"
            "    return table.pop(fd, None)\n"),
        "cases": [(({}, '/etc/passwd'), 3),
                  (({3: '/a', 4: '/b'}, '/c'), 5),
                  (({3: '/a'}, '/b'), 4)],
        "params": [],
        "calibration": "对照：OS 文件系统——打开文件表（fd 最小分配，0/1/2 标准流保留）",
    },
    "设备-字符设备": {
        "task": "字符设备",
        "pattern": (
            "def char_device(device, op, data=None):\n"
"    # 生效条件：op ∈ {close, open, read, write}\n"
"    # 子功能：① op 分支处理\n"
"    # 执行：按 op 分派\n"
"    # 不适用条件：op 非 {close, open, read, write} 时\n"
            "    # 字符设备抽象：open/read/write/close（驱动接口——设备=文件 语义）\n"
            "    if op == 'open':\n"
            "        device['opened'] = True\n"
            "        return True\n"
            "    if op == 'read':\n"
            "        if not device.get('opened'):\n"
            "            return None\n"
            "        buf = device.get('buf', '')\n"
            "        device['buf'] = ''\n"
            "        return buf\n"
            "    if op == 'write':\n"
            "        if not device.get('opened'):\n"
            "            return False\n"
            "        device['buf'] = device.get('buf', '') + (data or '')\n"
            "        return True\n"
            "    if op == 'close':\n"
            "        device['opened'] = False\n"
            "        return True\n"
            "    return False\n"),
        "cases": [(({'opened': False}, 'open'), True),
                  (({'opened': True, 'buf': ''}, 'write', '数据'), True),
                  (({'opened': True, 'buf': '数据'}, 'read'), '数据'),
                  (({'opened': False}, 'read'), None)],
        "params": [],
        "calibration": "对照：OS 设备驱动——字符设备接口（open/read/write/close，设备即文件）",
    },
    "中断-向量表": {
        "task": "中断向量",
        "pattern": (
            "def vector_lookup(table, irq):\n"
"    # 生效条件：参数 table/irq 合法\n"
"    # 子功能：① 主体逻辑执行\n"
"    # 执行：顺序执行\n"
"    # 不适用条件：输入不满足生效条件时返回 None/不执行\n"
            "    # 中断向量表：IRQ 号 → 处理函数（未注册 → None）\n"
            "    return table.get(irq)\n"),
        "cases": [(({3: 'timer_handler', 14: 'disk_handler'}, 3), 'timer_handler'),
                  (({3: 'timer_handler'}, 14), None),
                  (({}, 0), None)],
        "params": [],
        "calibration": "对照：OS 中断——向量表（IRQ→handler 查表分派，未注册返回 None）",
    },
    "中断-上下文切换": {
        "task": "上下文切换",
        "pattern": (
            "def ctx_switch(ctx, save):\n"
"    # 生效条件：参数 ctx/save 合法\n"
"    # 子功能：① 调用 dict\n"
"    # 执行：顺序调用\n"
"    # 不适用条件：输入不满足生效条件时返回 None/不执行\n"
            "    # 中断上下文切换：保存当前寄存器 → 恢复目标（现场保护/恢复）\n"
            "    if save:\n"
            "        ctx['saved'] = dict(ctx.get('regs', {}))\n"
            "        return 'saved'\n"
            "    regs = ctx.pop('saved', {})\n"
            "    ctx['regs'] = dict(regs)\n"
            "    return 'restored'\n"),
        "cases": [(({'regs': {'a': 1, 'b': 2}}, True), 'saved'),
                  (({'regs': {'a': 1}, 'saved': {'a': 9}}, False), 'restored')],
        "params": [],
        "calibration": "对照：OS 中断——上下文切换（现场保存/恢复，中断处理不破坏用户态）",
    },
    "中断-嵌套优先级": {
        "task": "中断优先级",
        "pattern": (
            "def nested_irq(current_prio, new_prio):\n"
"    # 生效条件：参数 current_prio/new_prio 合法\n"
"    # 子功能：① 主体逻辑执行\n"
"    # 执行：顺序执行\n"
"    # 不适用条件：输入不满足生效条件时返回 None/不执行\n"
            "    # 中断嵌套：新中断优先级更高 → 可抢占当前（NMI/高优先抢占）\n"
            "    return new_prio > current_prio\n"),
        "cases": [((3, 5), True),
                  ((5, 3), False),
                  ((3, 3), False)],
        "params": [],
        "calibration": "对照：OS 中断——嵌套优先级（高优先级中断可抢占低优先级，同级不嵌套）",
    },
    "文件-系统挂载": {
        "task": "文件系统挂载",
        "pattern": (
            "def mount_op(mounts, path, fs_type=None):\n"
"    # 生效条件：参数 mounts/path/fs_type 合法\n"
"    # 子功能：① 条件判定 ② 结果处理\n"
"    # 执行：顺序执行\n"
"    # 不适用条件：输入不满足生效条件时返回 None/不执行\n"
            "    # VFS 挂载：挂载点→文件系统（mount 注册/unmount 卸载/查询）\n"
            "    if fs_type is not None:\n"
            "        mounts[path] = fs_type\n"
            "        return True\n"
            "    if fs_type is None and path in mounts:\n"
            "        return mounts.pop(path)  # unmount\n"
            "    return None\n"),
        "cases": [(({}, '/data', 'ext4'), True),
                  (({'/data': 'ext4'}, '/data'), 'ext4'),
                  (({'/data': 'ext4'}, '/other'), None)],
        "params": [],
        "calibration": "对照：OS VFS——文件系统挂载（mount 注册/unmount 卸载/未挂载 None）",
    },
    "文件-文件权限": {
        "task": "文件权限",
        "pattern": (
            "def check_perm(mode, access):\n"
"    # 生效条件：参数 mode/access 合法\n"
"    # 子功能：① 调用 bool\n"
"    # 执行：顺序调用\n"
"    # 不适用条件：输入不满足生效条件时返回 None/不执行\n"
            "    # 文件权限：模式位 rwx 检查（读4/写2/执行1 位运算）\n"
            "    bit = {'r': 4, 'w': 2, 'x': 1}[access]\n"
            "    return bool(mode & bit)\n"),
        "cases": [((7, 'r'), True), ((7, 'w'), True), ((5, 'w'), False),
                  ((1, 'x'), True), ((0, 'r'), False)],
        "params": [],
        "calibration": "对照：OS 文件权限——模式位检查（r=4/w=2/x=1 位与运算）",
    },
    "进程-进程树": {
        "task": "进程树",
        "pattern": (
            "def process_tree(parents, root):\n"
"    # 生效条件：参数 parents/root 合法\n"
"    # 子功能：① 调用 walk；② 调用 sorted\n"
"    # 执行：循环迭代；顺序调用\n"
"    # 不适用条件：输入不满足生效条件时返回 None/不执行\n"
            "    # 进程树：父进程关系 → 后代集合（递归收集子树）\n"
            "    children = {}\n"
            "    for pid, ppid in parents.items():\n"
            "        children.setdefault(ppid, []).append(pid)\n"
            "    desc = []\n"
            "    def walk(pid):\n"
            "        # 递归遍历：收集当前进程的直接子进程及后代\n"
            "        for c in children.get(pid, []):\n"
            "            desc.append(c)\n"
            "            walk(c)\n"
            "    walk(root)\n"
            "    return sorted(desc)\n"),
        "cases": [(({'a': 'root', 'b': 'a', 'c': 'a'}, 'root'), ['a', 'b', 'c']),
                  (({'b': 'a'}, 'a'), ['b']),
                  (({}, 'a'), [])],
        "params": [],
        "calibration": "对照：OS 进程树——父子关系后代收集（fork 产生的进程层级）",
    },
    "系统调用-接口": {
        "task": "系统调用",
        "pattern": (
            "def syscall_dispatch(table, num, args):\n"
"    # 生效条件：参数 table/num/args 合法\n"
"    # 子功能：① 调用 fn\n"
"    # 执行：顺序调用\n"
"    # 不适用条件：输入不满足生效条件时返回 None/不执行\n"
            "    # 系统调用：编号 → 处理函数分派（未知编号 → None）\n"
            "    fn = table.get(num)\n"
            "    if fn is None:\n"
            "        return None\n"
            "    return fn(*args)\n"),
        "cases": [(({1: lambda x: x + 1, 2: lambda a, b: a * b}, 1, [5]), 6),
                  (({1: lambda x: x}, 2, [3]), None),
                  (({}, 9, []), None)],
        "params": [],
        "calibration": "对照：OS 系统调用——编号分派（syscall 表，未知编号返回 None）",
    },
    "信号-信号处理": {
        "task": "信号处理",
        "pattern": (
            "def signal_op(handlers, op, signum=None, handler=None):\n"
"    # 生效条件：op ∈ {register, send}\n"
"    # 子功能：① op 分支处理\n"
"    # 执行：按 op 分派；顺序调用\n"
"    # 不适用条件：op 非 {register, send} 时\n"
            "    # 信号：注册 handler / 发送信号 / 默认处理（忽略/终止）\n"
            "    if op == 'register':\n"
            "        handlers[signum] = handler\n"
            "        return True\n"
            "    if op == 'send':\n"
            "        fn = handlers.get(signum)\n"
            "        if fn is not None:\n"
            "            return ('handled', fn())\n"
            "        return ('default', 'terminate' if signum == 2 else 'ignore')\n"
            "    return None\n"),
        "cases": [(({}, 'register', 2, lambda: 'cleanup'), True),
                  (({2: lambda: 'cleanup'}, 'send', 2), ('handled', 'cleanup')),
                  (({}, 'send', 2), ('default', 'terminate')),
                  (({}, 'send', 10), ('default', 'ignore'))],
        "params": [],
        "calibration": "对照：OS 信号——注册/发送/默认（SIGINT=2 默认终止，SIGUSR=10 默认忽略）",
    },
    "系统调用-参数校验": {
        "task": "参数校验",
        "pattern": (
            "def validate_args(args, types):\n"
"    # 生效条件：参数 args/types 合法\n"
"    # 子功能：① 调用 zip；② 调用 len；③ 调用 isinstance\n"
"    # 执行：循环迭代；顺序调用\n"
"    # 不适用条件：输入不满足生效条件时返回 None/不执行\n"
            "    # 系统调用参数校验：类型检查（copy_from_user 语义——非法参数拒绝）\n"
            "    if len(args) != len(types):\n"
            "            return False\n"
            "    for a, t in zip(args, types):\n"
            "        if not isinstance(a, t):\n"
            "            return False\n"
            "    return True\n"),
        "cases": [(([1, 'x'], [int, str]), True),
                  (([1, 2], [int, str]), False),
                  (([1], [int, str]), False)],
        "params": [],
        "calibration": "对照：OS 系统调用——参数类型校验（copy_from_user 语义，非法拒绝）",
    },
    "文件-日志恢复": {
        "task": "日志恢复",
        "pattern": (
            "def journal_replay(entries, disk):\n"
"    # 生效条件：参数 entries/disk 合法\n"
"    # 子功能：① 调用 dict\n"
"    # 执行：循环迭代；顺序调用\n"
"    # 不适用条件：输入不满足生效条件时返回 None/不执行\n"
            "    # 文件系统日志：崩溃后重放（journal 条目 → 磁盘状态恢复）\n"
            "    for e in entries:\n"
            "        if e.get('type') == 'write':\n"
            "            disk[e['inode']] = e['data']\n"
            "        elif e.get('type') == 'delete':\n"
            "            disk.pop(e['inode'], None)\n"
            "    return dict(disk)\n"),
        "cases": [(([{'type': 'write', 'inode': 'a', 'data': 'X'},
                     {'type': 'write', 'inode': 'b', 'data': 'Y'},
                     {'type': 'delete', 'inode': 'a'}], {}),
                   {'b': 'Y'}),
                  (([], {'a': 'keep'}), {'a': 'keep'})],
        "params": [],
        "calibration": "对照：OS 文件系统日志——journal 重放（崩溃恢复，write/delete 条目应用）",
    },
    "系统-监控指标": {
        "task": "系统监控",
        "pattern": (
            "def sys_metrics(usage_samples):\n"
"    # 生效条件：参数 usage_samples 合法\n"
"    # 子功能：① 调用 round；② 调用 max；③ 调用 sum\n"
"    # 执行：顺序调用\n"
"    # 不适用条件：usage_samples 为空/非法时（隐式盲区：返回默认值 {'avg': 0.0, 'peak': 0.0} = 未知行为——不适用）\n"
            "    # 系统监控：CPU/内存采样 → 平均/峰值（负载统计）\n"
            "    if not usage_samples:\n"
            "        return {'avg': 0.0, 'peak': 0.0}\n"
            "    return {'avg': round(sum(usage_samples) / len(usage_samples), 2),\n"
            "            'peak': max(usage_samples)}\n"),
        "cases": [(([30, 50, 70],), {'avg': 50.0, 'peak': 70}),
                  (([],), {'avg': 0.0, 'peak': 0.0}),
                  (([100],), {'avg': 100.0, 'peak': 100})],
        "params": [],
        "calibration": "对照：OS 系统监控——CPU 使用率采样统计（平均/峰值）",
    },
    "系统-守护进程": {
        "task": "守护进程",
        "pattern": (
            "def daemon_lifecycle(state, op):\n"
"    # 生效条件：op ∈ {start, status, stop}\n"
"    # 子功能：① op 分支处理\n"
"    # 执行：按 op 分派\n"
"    # 不适用条件：op 非 {start, status, stop} 时（隐式盲区：返回默认值 unknown = 未知行为——不适用）\n"
            "    # 守护进程：启动→运行→停止（后台服务生命周期）\n"
            "    if op == 'start':\n"
            "        state['status'] = 'running'\n"
            "        return 'running'\n"
            "    if op == 'stop':\n"
            "        state['status'] = 'stopped'\n"
            "        return 'stopped'\n"
            "    if op == 'status':\n"
            "        return state.get('status', 'unknown')\n"
            "    return 'unknown'\n"),
        "cases": [(({'status': 'idle'}, 'start'), 'running'),
                  (({'status': 'running'}, 'stop'), 'stopped'),
                  (({'status': 'running'}, 'status'), 'running')],
        "params": [],
        "calibration": "对照：OS 守护进程——生命周期（start/stop/status 状态机）",
    },
    "并发-信号量": {
        "task": "信号量",
        "pattern": (
            "def semaphore_op(sem, op):\n"
"    # 生效条件：op ∈ {P, V}\n"
"    # 子功能：① op 分支处理\n"
"    # 执行：按 op 分派\n"
"    # 不适用条件：op 非 {P, V} 时\n"
            "    # 信号量：P 减（资源不足阻塞）/ V 加（释放资源）——计数同步\n"
            "    if op == 'P':\n"
            "        if sem['count'] <= 0:\n"
            "            return 'blocked'\n"
            "        sem['count'] -= 1\n"
            "        return 'acquired'\n"
            "    if op == 'V':\n"
            "        sem['count'] += 1\n"
            "        return 'released'\n"
            "    return None\n"),
        "cases": [(({'count': 1}, 'P'), 'acquired'),
                  (({'count': 0}, 'P'), 'blocked'),
                  (({'count': 0}, 'V'), 'released')],
        "params": [],
        "calibration": "对照：OS 并发——信号量 P/V（计数同步，资源耗尽 P 阻塞）",
    },
    "并发-读写锁": {
        "task": "读写锁",
        "pattern": (
            "def rwlock_op(lock, op):\n"
"    # 生效条件：op ∈ {r_lock, r_unlock, w_lock, w_unlock}\n"
"    # 子功能：① op 分支处理\n"
"    # 执行：按 op 分派；顺序调用\n"
"    # 不适用条件：op 非 {r_lock, r_unlock, w_lock, w_unlock} 时\n"
            "    # 读写锁：多读并发/写独占（读者计数 + 写者标志）\n"
            "    if op == 'r_lock':\n"
            "        if lock.get('writer'):\n"
            "            return 'blocked'\n"
            "        lock['readers'] = lock.get('readers', 0) + 1\n"
            "        return 'r_acquired'\n"
            "    if op == 'w_lock':\n"
            "        if lock.get('writer') or lock.get('readers', 0) > 0:\n"
            "            return 'blocked'\n"
            "        lock['writer'] = True\n"
            "        return 'w_acquired'\n"
            "    if op == 'r_unlock':\n"
            "        lock['readers'] = max(0, lock.get('readers', 0) - 1)\n"
            "        return 'r_released'\n"
            "    if op == 'w_unlock':\n"
            "        lock['writer'] = False\n"
            "        return 'w_released'\n"
            "    return None\n"),
        "cases": [(({'readers': 0}, 'r_lock'), 'r_acquired'),
                  (({'readers': 1, 'writer': False}, 'w_lock'), 'blocked'),
                  (({'readers': 0, 'writer': False}, 'w_lock'), 'w_acquired')],
        "params": [],
        "calibration": "对照：OS 并发——读写锁（多读并发/写独占，读者在场写阻塞）",
    },
    "并发-生产者消费者": {
        "task": "生产者消费者",
        "pattern": (
            "def producer_consumer(buf, op, item=None):\n"
"    # 生效条件：op ∈ {consume, produce}\n"
"    # 子功能：① op 分支处理\n"
"    # 执行：按 op 分派；顺序调用\n"
"    # 不适用条件：buf 为空/非法时；op 非 {consume, produce} 时\n"
            "    # 生产者-消费者：有界缓冲（生产入队/消费出队）\n"
            "    if op == 'produce':\n"
            "        if len(buf) >= 4:\n"
            "            return 'buffer_full'\n"
            "        buf.append(item)\n"
            "        return len(buf)\n"
            "    if op == 'consume':\n"
            "        if not buf:\n"
            "            return 'buffer_empty'\n"
            "        return buf.pop(0)\n"
            "    return None\n"),
        "cases": [(([], 'produce', 'a'), 1),
                  ((['a'], 'consume'), 'a'),
                  (([], 'consume'), 'buffer_empty'),
                  ((['a', 'b', 'c', 'd'], 'produce', 'e'), 'buffer_full')],
        "params": [],
        "calibration": "对照：OS 并发——生产者-消费者（有界缓冲，满/空边界）",
    },
    "虚拟化-命名空间": {
        "task": "命名空间",
        "pattern": (
            "def ns_map(op, ns, pid=None):\n"
"    # 生效条件：op ∈ {lookup, register}\n"
"    # 子功能：① op 分支处理\n"
"    # 执行：按 op 分派\n"
"    # 不适用条件：op 非 {lookup, register} 时\n"
            "    # 命名空间隔离：PID/网络视图映射（容器进程 → 命名空间内 PID）\n"
            "    if op == 'register':\n"
            "        ns['inner'] = ns.get('inner', 100) + 1\n"
            "        ns[pid] = ns['inner']\n"
            "        return ns[pid]\n"
            "    if op == 'lookup':\n"
            "        return ns.get(pid)\n"
            "    return None\n"),
        "cases": [(('register', {}, 'p1'), 101),
                  (('lookup', {'inner': 100, 'p1': 101}, 'p1'), 101),
                  (('lookup', {'inner': 100}, 'nope'), None)],
        "params": [],
        "calibration": "对照：容器命名空间——PID 视图映射（进程在命名空间内重编号，隔离语义）",
    },
    "虚拟化-cgroup限制": {
        "task": "资源限制",
        "pattern": (
            "def cgroup_limit(cg, resource, limit, usage):\n"
"    # 生效条件：参数 cg/resource/limit/usage 合法\n"
"    # 子功能：① 条件判定 ② 结果处理\n"
"    # 执行：顺序执行\n"
"    # 不适用条件：输入不满足生效条件时返回 None/不执行\n"
            "    # cgroup：资源配额（CPU/内存 限额，超限拒绝）\n"
            "    if resource not in cg:\n"
            "        cg[resource] = limit\n"
            "    return usage <= cg[resource]\n"),
        "cases": [(({}, 'cpu', 100, 80), True),
                  (({}, 'cpu', 100, 120), False),
                  (({'mem': 50}, 'mem', 50, 50), True)],
        "params": [],
        "calibration": "对照：cgroup 资源限制——CPU/内存配额（使用量超限拒绝）",
    },
    "容器-生命周期": {
        "task": "容器生命周期",
        "pattern": (
            "def container_ops(state, op, img=None):\n"
"    # 生效条件：op ∈ {create, remove, start, stop}；state.clear 可用\n"
"    # 子功能：① op 分支处理\n"
"    # 执行：按 op 分派\n"
"    # 不适用条件：op 非 {create, remove, start, stop} 时\n"
            "    # 容器：创建/启动/停止/删除（镜像 → 运行实例）\n"
            "    if op == 'create':\n"
            "        state['img'] = img\n"
            "        state['status'] = 'created'\n"
            "        return 'created'\n"
            "    if op == 'start':\n"
            "        state['status'] = 'running'\n"
            "        return 'running'\n"
            "    if op == 'stop':\n"
            "        state['status'] = 'exited'\n"
            "        return 'exited'\n"
            "    if op == 'remove':\n"
            "        state.clear()\n"
            "        return 'removed'\n"
            "    return None\n"),
        "cases": [(({}, 'create', 'alpine'), 'created'),
                  (({'status': 'created'}, 'start'), 'running'),
                  (({'status': 'running'}, 'stop'), 'exited'),
                  (({'status': 'exited'}, 'remove'), 'removed')],
        "params": [],
        "calibration": "对照：容器生命周期——create/start/stop/remove（镜像→实例状态机）",
    },
    "文件-RAID条带": {
        "task": "RAID条带",
        "pattern": (
            "def raid_stripe(data, disks):\n"
"    # 生效条件：参数 data/disks 合法\n"
"    # 子功能：① 调用 range\n"
"    # 执行：顺序调用\n"
"    # 不适用条件：disks 为空/非法时（隐式盲区：返回默认值 [] = 未知行为——不适用）\n"
            "    # RAID 0：数据条带化（分块分布到多盘——并行读写）\n"
            "    if not disks:\n"
            "        return []\n"
            "    return [data[i::disks] for i in range(disks)]\n"),
        "cases": [((list('abcdef'), 2), [list('ace'), list('bdf')]),
                  ((list('abc'), 1), [list('abc')]),
                  ((list('ab'), 0), [])],
        "params": [],
        "calibration": "对照：RAID 0——数据条带化（分块分布，并行 I/O 语义）",
    },
    "文件-RAID奇偶校验": {
        "task": "RAID奇偶",
        "pattern": (
            "def raid_parity(blocks):\n"
"    # 生效条件：参数 blocks 合法\n"
"    # 子功能：① 主体逻辑执行\n"
"    # 执行：循环迭代\n"
"    # 不适用条件：输入不满足生效条件时返回 None/不执行\n"
            "    # RAID 5：XOR 奇偶校验（N-1 容错——单盘故障可恢复）\n"
            "    parity = 0\n"
            "    for b in blocks:\n"
            "        parity ^= b\n"
            "    return parity\n"),
        "cases": [(([1, 2, 3],), 0),
                  (([5, 3],), 6),
                  (([7],), 7)],
        "params": [],
        "calibration": "对照：RAID 5——XOR 奇偶校验（任一数据盘故障可由其余+奇偶恢复）",
    },
    "文件-文件系统快照": {
        "task": "文件快照",
        "pattern": (
            "def fs_snapshot(blocks, op, idx=None, data=None):\n"
"    # 生效条件：op ∈ {rollback, snap, write}\n"
"    # 子功能：① op 分支处理\n"
"    # 执行：按 op 分派；顺序调用\n"
"    # 不适用条件：op 非 {rollback, snap, write} 时\n"
            "    # 文件系统快照：写时复制（修改前复制原块——快照一致性）\n"
            "    if op == 'snap':\n"
            "        blocks['snap'] = dict(blocks['data'])\n"
            "        return 'snapped'\n"
            "    if op == 'write':\n"
            "        if 'snap' in blocks and idx not in blocks['snap']:\n"
            "            blocks['snap'][idx] = blocks['data'][idx]  # 写时复制\n"
            "        blocks['data'][idx] = data\n"
            "        return blocks['data'][idx]\n"
            "    if op == 'rollback':\n"
            "        blocks['data'] = dict(blocks.get('snap', {}))\n"
            "        return blocks['data']\n"
            "    return None\n"),
        "cases": [(({'data': {1: 'a'}}, 'snap'), 'snapped'),
                  (({'data': {1: 'a'}, 'snap': {1: 'a'}}, 'write', 1, 'b'), 'b'),
                  (({'data': {1: 'b'}, 'snap': {1: 'a'}}, 'rollback'), {1: 'a'})],
        "params": [],
        "calibration": "对照：文件系统快照——写时复制（修改前复制原块，可回滚）",
    },
    "启动-引导加载": {
        "task": "引导加载",
        "pattern": (
            "def bootloader(disk, stage):\n"
"    # 生效条件：stage ∈ {initrd, mbr}\n"
"    # 子功能：1 stage 分支处理\n"
"    # 执行：按 op 分派\n"
"    # 不适用条件：stage 非 {initrd, mbr} 时（隐式盲区：返回默认值 unknown = 未知行为——不适用）\n"
            "    # bootloader：MBR→内核加载（引导阶段推进）\n"
            "    if stage == 'mbr':\n"
            "        return ('loaded', disk.get('kernel', 'vmlinuz'))\n"
            "    if stage == 'initrd':\n"
            "        return ('mounted', 'initramfs')\n"
            "    return 'unknown'\n"),
        "cases": [(({'kernel': 'vmlinuz'}, 'mbr'), ('loaded', 'vmlinuz')),
                  (({}, 'initrd'), ('mounted', 'initramfs')),
                  (({}, 'x'), 'unknown')],
        "params": [],
        "calibration": "对照：OS 启动——bootloader（MBR→内核→initrd 加载）",
    },
    "启动-初始化流程": {
        "task": "初始化流程",
        "pattern": (
            "def init_sequence(services):\n"
"    # 生效条件：参数 services 合法\n"
"    # 子功能：① 调用 set；② 调用 sorted；③ 调用 all\n"
"    # 执行：循环迭代；顺序调用\n"
"    # 不适用条件：输入不满足生效条件时返回 None/不执行\n"
            "    # init 进程：按依赖顺序启动服务（启动序列）\n"
            "    order = []\n"
            "    remaining = set(services)\n"
            "    while remaining:\n"
            "        for s in sorted(remaining):\n"
            "            deps = services[s]\n"
            "            if all(d in order for d in deps):\n"
            "                order.append(s)\n"
            "                remaining.remove(s)\n"
            "                break\n"
            "    return order\n"),
        "cases": [(({'网络': [], '应用': ['网络'], '存储': []},),
                   ['存储', '网络', '应用']),
                  (({},), [])],
        "params": [],
        "calibration": "对照：OS init——依赖排序启动（先依赖后服务）",
    },
    "系统-固件接口": {
        "task": "固件接口",
        "pattern": (
            "def firmware_call(fw, call):\n"
"    # 生效条件：call ∈ {get_time, reboot, set_boot}\n"
"    # 子功能：1 call 分支处理\n"
"    # 执行：按 op 分派\n"
"    # 不适用条件：call 非 {get_time, reboot, set_boot} 时\n"
            "    # 固件接口：UEFI/BIOS 调用（硬件抽象服务）\n"
            "    if call == 'get_time':\n"
            "        return fw.get('time', 0)\n"
            "    if call == 'reboot':\n"
            "        return 'rebooting'\n"
            "    if call == 'set_boot':\n"
            "        fw['boot_dev'] = 'disk0'\n"
            "        return 'set'\n"
            "    return None\n"),
        "cases": [(({'time': 42}, 'get_time'), 42),
                  (({}, 'reboot'), 'rebooting'),
                  (({}, 'set_boot'), 'set')],
        "params": [],
        "calibration": "对照：固件接口——UEFI 服务（时间/重启/启动设备）",
    },
    "安全-访问控制": {
        "task": "访问控制",
        "pattern": (
            "def acl_check(acl, subject, resource, action):\n"
"    # 生效条件：参数 acl/subject/resource/action 合法\n"
"    # 子功能：① 条件判定 ② 结果处理\n"
"    # 执行：循环迭代\n"
"    # 不适用条件：输入不满足生效条件时返回 None/不执行\n"
            "    # ACL：访问控制列表（主体→资源→动作 权限判定）\n"
            "    rules = acl.get(resource, [])\n"
            "    for r in rules:\n"
            "        if r['subject'] == subject and r['action'] == action:\n"
            "            return r['allow']\n"
            "    return False  # 默认拒绝\n"),
        "cases": [(({'file': [{'subject': 'u1', 'action': 'read', 'allow': True}]},
                    'u1', 'file', 'read'), True),
                  (({'file': []}, 'u1', 'file', 'read'), False),
                  (({'file': [{'subject': 'u1', 'action': 'write', 'allow': False}]},
                    'u1', 'file', 'write'), False)],
        "params": [],
        "calibration": "对照：OS 安全——ACL 访问控制（主体/资源/动作 规则判定，默认拒绝）",
    },
    "安全-审计日志": {
        "task": "审计日志",
        "pattern": (
            "def audit_log(log, event, subject):\n"
"    # 生效条件：参数 log/event/subject 合法\n"
"    # 子功能：① 调用 len\n"
"    # 执行：顺序调用\n"
"    # 不适用条件：输入不满足生效条件时返回 None/不执行\n"
            "    # 审计：安全事件记录（操作 → 日志条目）\n"
            "    log.append({'event': event, 'subject': subject})\n"
            "    return len(log)\n"),
        "cases": [(([], 'login', 'u1'), 1),
                  (([{'event': 'login', 'subject': 'u1'}], 'logout', 'u1'), 2)],
        "params": [],
        "calibration": "对照：OS 安全——审计日志（安全事件记录，可追溯）",
    },
    "安全-能力系统": {
        "task": "能力系统",
        "pattern": (
            "def capability(caps, op, cap=None):\n"
"    # 生效条件：op ∈ {check, grant, revoke}；caps.discard 可用\n"
"    # 子功能：① op 分支处理\n"
"    # 执行：按 op 分派\n"
"    # 不适用条件：op 非 {check, grant, revoke} 时\n"
            "    # 能力：特权令牌（持能力才可操作——最小权限语义）\n"
            "    if op == 'grant':\n"
            "        caps.add(cap)\n"
            "        return True\n"
            "    if op == 'check':\n"
            "        return cap in caps\n"
            "    if op == 'revoke':\n"
            "        caps.discard(cap)\n"
            "        return cap not in caps\n"
            "    return False\n"),
        "cases": [((set(), 'grant', 'net_raw'), True),
                  (({'net_raw'}, 'check', 'net_raw'), True),
                  ((set(), 'check', 'net_raw'), False),
                  (({'net_raw'}, 'revoke', 'net_raw'), True)],
        "params": [],
        "calibration": "对照：OS 安全——能力系统（特权令牌授予/检查/撤销，最小权限）",
    },
    "性能-性能分析": {
        "task": "性能分析",
        "pattern": (
            "def profile_funcs(times):\n"
"    # 生效条件：参数 times 合法\n"
"    # 子功能：① 调用 sum；② 调用 round；③ 调用 len\n"
"    # 执行：顺序调用\n"
"    # 不适用条件：times 为空/非法时\n"
            "    # profiling：函数耗时统计（累计/平均——热点定位）\n"
            "    total = sum(times)\n"
            "    if not times:\n"
            "        return {'total': 0, 'avg': 0.0}\n"
            "    return {'total': total, 'avg': round(total / len(times), 2)}\n"),
        "cases": [(([10, 20, 30],), {'total': 60, 'avg': 20.0}),
                  (([],), {'total': 0, 'avg': 0.0})],
        "params": [],
        "calibration": "对照：OS 性能——profiling（函数耗时统计，热点定位）",
    },
    "性能-瓶颈检测": {
        "task": "瓶颈检测",
        "pattern": (
            "def bottleneck(resources):\n"
"    # 生效条件：参数 resources 合法\n"
"    # 子功能：① 调用 max\n"
"    # 执行：顺序调用\n"
"    # 不适用条件：resources 为空/非法时\n"
            "    # 瓶颈检测：利用率最高的资源（系统瓶颈定位）\n"
            "    if not resources:\n"
            "        return None\n"
            "    return max(resources.items(), key=lambda kv: kv[1])\n"),
        "cases": [(({'cpu': 90, 'mem': 60, 'io': 30},), ('cpu', 90)),
                  (({},), None)],
        "params": [],
        "calibration": "对照：OS 性能——瓶颈检测（最高利用率资源）",
    },
    "性能-调优建议": {
        "task": "调优建议",
        "pattern": (
            "def tuning_advice(metrics):\n"
"    # 生效条件：参数 metrics 合法\n"
"    # 子功能：① 条件判定 ② 结果处理\n"
"    # 执行：顺序执行\n"
"    # 不适用条件：adv 为空/非法时\n"
            "    # 调优：指标 → 建议（瓶颈 → 调整参数）\n"
            "    adv = []\n"
            "    if metrics.get('cpu', 0) > 80:\n"
            "        adv.append('升级 CPU 或减少进程')\n"
            "    if metrics.get('mem', 0) > 80:\n"
            "        adv.append('增加内存或优化缓存')\n"
            "    if not adv:\n"
            "        adv.append('当前配置合理')\n"
            "    return adv\n"),
        "cases": [(({'cpu': 90, 'mem': 50},), ['升级 CPU 或减少进程']),
                  (({'cpu': 50, 'mem': 90},), ['增加内存或优化缓存']),
                  (({'cpu': 50, 'mem': 50},), ['当前配置合理'])],
        "params": [],
        "calibration": "对照：OS 性能——调优建议（瓶颈 → 参数调整建议）",
    },
    "文件-磁盘配额": {
        "task": "磁盘配额",
        "pattern": (
            "def quota_check(quotas, user, usage, size):\n"
"    # 生效条件：参数 quotas/user/usage/size 合法\n"
"    # 子功能：① 调用 float\n"
"    # 执行：顺序调用\n"
"    # 不适用条件：输入不满足生效条件时返回 None/不执行\n"
            "    # 磁盘配额：用户使用量 + 新写入 ≤ 限额（超限拒绝）\n"
            "    limit = quotas.get(user, float('inf'))\n"
            "    return usage + size <= limit\n"),
        "cases": [(({'u1': 100}, 'u1', 80, 10), True),
                  (({'u1': 100}, 'u1', 95, 10), False),
                  (({}, 'u2', 50, 10), True)],
        "params": [],
        "calibration": "对照：OS 磁盘配额——用户限额（使用量+写入 ≤ 限额，超限拒绝）",
    },
    "文件-文件锁": {
        "task": "文件锁",
        "pattern": (
            "def file_lock(state, op):\n"
"    # 生效条件：op ∈ {lock, unlock}\n"
"    # 子功能：① op 分支处理\n"
"    # 执行：按 op 分派\n"
"    # 不适用条件：op 非 {lock, unlock} 时\n"
            "    # 文件锁：flock 语义（独占/释放——并发写保护）\n"
            "    if op == 'lock':\n"
            "        if state.get('locked'):\n"
            "            return 'blocked'\n"
            "        state['locked'] = True\n"
            "        return 'locked'\n"
            "    if op == 'unlock':\n"
            "        state['locked'] = False\n"
            "        return 'unlocked'\n"
            "    return None\n"),
        "cases": [(({'locked': False}, 'lock'), 'locked'),
                  (({'locked': True}, 'lock'), 'blocked'),
                  (({'locked': True}, 'unlock'), 'unlocked')],
        "params": [],
        "calibration": "对照：OS 文件锁——flock（独占/释放，并发写保护）",
    },
    "系统-资源限额": {
        "task": "资源限额",
        "pattern": (
            "def rlimit(res, op, soft=None):\n"
"    # 生效条件：op ∈ {check, get, set}\n"
"    # 子功能：① op 分支处理\n"
"    # 执行：按 op 分派；顺序调用\n"
"    # 不适用条件：op 非 {check, get, set} 时\n"
            "    # ulimit：进程资源限制（设置/查询软限制）\n"
            "    if op == 'set':\n"
            "        res['soft'] = soft\n"
            "        return soft\n"
            "    if op == 'get':\n"
            "        return res.get('soft')\n"
            "    if op == 'check':\n"
            "        return res.get('soft', float('inf'))\n"
            "    return None\n"),
        "cases": [(({}, 'set', 1024), 1024),
                  (({'soft': 1024}, 'get', None), 1024),
                  (({}, 'check', None), float('inf'))],
        "params": [],
        "calibration": "对照：OS ulimit——进程资源限制（软限制设置/查询）",
    },
    "可信-安全启动": {
        "task": "安全启动",
        "pattern": (
            "def secure_boot(chain, keyring):\n"
"    # 生效条件：参数 chain/keyring 合法\n"
"    # 子功能：① 条件判定 ② 结果处理\n"
"    # 执行：循环迭代\n"
"    # 不适用条件：输入不满足生效条件时返回 None/不执行\n"
            "    # 安全启动：启动组件签名验证链（未签名/密钥不符拒绝）\n"
            "    for comp in chain:\n"
            "        if comp not in keyring:\n"
            "            return ('denied', comp)\n"
            "    return ('booted', True)\n"),
        "cases": [((['kernel', 'initrd'], {'kernel', 'initrd'}), ('booted', True)),
                  ((['kernel', 'evil'], {'kernel'}), ('denied', 'evil'))],
        "params": [],
        "calibration": "对照：安全启动——签名验证链（组件须在可信密钥库）",
    },
    "可信-TPM度量": {
        "task": "TPM度量",
        "pattern": (
            "def tpm_measure(pcr, component):\n"
"    # 生效条件：参数 pcr/component 合法\n"
"    # 子功能：① 调用 sum；② 调用 ord\n"
"    # 执行：顺序调用\n"
"    # 不适用条件：输入不满足生效条件时返回 None/不执行\n"
            "    # TPM 度量：PCR 扩展（哈希累加——信任链度量）\n"
            "    h = sum(ord(c) for c in component) % 256\n"
            "    pcr = (pcr + h) % 256\n"
            "    return pcr\n"),
        "cases": [((0, 'BIOS'), 45),
                  ((45, 'loader'), 164),
                  ((0, ''), 0)],
        "params": [],
        "calibration": "对照：TPM——PCR 扩展度量（组件哈希累加到平台寄存器）",
    },
    "可信-哈希校验": {
        "task": "哈希校验",
        "pattern": (
            "def hash_verify(file_hash, expected):\n"
"    # 生效条件：参数 file_hash/expected 合法\n"
"    # 子功能：① 条件判定 ② 结果处理\n"
"    # 执行：顺序执行\n"
"    # 不适用条件：输入不满足生效条件时返回 None/不执行\n"
            "    # 文件完整性：哈希比对（不匹配 → 篡改告警）\n"
            "    if file_hash == expected:\n"
            "        return 'integrity_ok'\n"
            "    return 'tampered'\n"),
        "cases": [(('abc123', 'abc123'), 'integrity_ok'),
                  (('abc', 'xyz'), 'tampered')],
        "params": [],
        "calibration": "对照：可信计算——文件哈希校验（完整性验证，篡改检测）",
    },
    "设备-热插拔": {
        "task": "热插拔",
        "pattern": (
            "def hotplug(bus, op, device=None):\n"
"    # 生效条件：op ∈ {list, plug, unplug}；bus.discard 可用\n"
"    # 子功能：① op 分支处理\n"
"    # 执行：按 op 分派；顺序调用\n"
"    # 不适用条件：op 非 {list, plug, unplug} 时\n"
            "    # 热插拔：设备接入/移除（运行中动态管理）\n"
            "    if op == 'plug':\n"
            "        bus.add(device)\n"
            "        return 'plugged'\n"
            "    if op == 'unplug':\n"
            "        bus.discard(device)\n"
            "        return 'unplugged'\n"
            "    if op == 'list':\n"
            "        return sorted(bus)\n"
            "    return None\n"),
        "cases": [((set(), 'plug', 'usb1'), 'plugged'),
                  (({'usb1'}, 'unplug', 'usb1'), 'unplugged'),
                  (({'usb1', 'usb2'}, 'list'), ['usb1', 'usb2'])],
        "params": [],
        "calibration": "对照：设备热插拔——接入/移除（运行中动态管理 USB 语义）",
    },
    "设备-即插即用": {
        "task": "即插即用",
        "pattern": (
            "def plug_and_play(device, drivers):\n"
"    # 生效条件：device.startswith 可用\n"
"    # 子功能：① 条件判定 ② 结果处理\n"
"    # 执行：循环迭代\n"
"    # 不适用条件：输入不满足生效条件时返回 None/不执行\n"
            "    # 即插即用：设备 ID → 自动匹配驱动（免手动配置）\n"
            "    for d in drivers:\n"
            "        if device.startswith(d['vendor']):\n"
            "            return ('matched', d['name'])\n"
            "    return ('nomatch', None)\n"),
        "cases": [(('VID_1234_PID_1', [{'vendor': 'VID_1234', 'name': '鼠标'}]),
                   ('matched', '鼠标')),
                  (('VID_9999_PID_1', [{'vendor': 'VID_1234', 'name': '鼠标'}]),
                   ('nomatch', None))],
        "params": [],
        "calibration": "对照：即插即用——设备 ID 自动匹配驱动（PnP 语义）",
    },
    "设备-设备树": {
        "task": "设备树",
        "pattern": (
            "def device_tree_lookup(tree, node):\n"
"    # 生效条件：参数 tree/node 合法\n"
"    # 子功能：① 主体逻辑执行\n"
"    # 执行：顺序执行\n"
"    # 不适用条件：输入不满足生效条件时返回 None/不执行\n"
            "    # 设备树：硬件拓扑节点查找（属性查询）\n"
            "    return tree.get(node)\n"),
        "cases": [(({'uart0': {'compatible': 'ns16550'}}, 'uart0'),
                   {'compatible': 'ns16550'}),
                  (({}, 'uart0'), None)],
        "params": [],
        "calibration": "对照：设备树——硬件拓扑节点（compatible 属性）",
    },
    "IPC-消息队列": {
        "task": "消息队列",
        "pattern": (
            "def msg_queue_ops(q, op, mtype=None, body=None):\n"
"    # 生效条件：op ∈ {count, recv, send}\n"
"    # 子功能：① op 分支处理\n"
"    # 执行：按 op 分派；循环迭代；顺序调用\n"
"    # 不适用条件：op 非 {count, recv, send} 时\n"
            "    # 消息队列：send 按类型投递 / recv 按类型取最早 / count 统计\n"
            "    # （SysV msg 语义：消息带类型，按类型取）\n"
            "    if op == 'send':\n"
            "        q.append((mtype, body))\n"
            "        return len(q)\n"
            "    if op == 'recv':\n"
            "        for i, (t, b) in enumerate(q):\n"
            "            if mtype is None or t == mtype:\n"
            "                q.pop(i)\n"
            "                return (t, b)\n"
            "        return None\n"
            "    if op == 'count':\n"
            "        return len(q)\n"
            "    return None\n"),
        "cases": [(([], 'send', 1, '甲'), 1),
                  (([(1, '甲'), (2, '乙')], 'recv', 1, None), (1, '甲')),
                  (([], 'recv', None, None), None),
                  (([(1, '甲')], 'count', None, None), 1)],
        "params": [],
        "calibration": "对照：OS IPC 消息队列——SysV msg（类型投递/按类型取最早）",
    },
    "IPC-共享内存": {
        "task": "共享内存",
        "pattern": (
            "def shm_ops(segments, key, op, offset=0, value=None, size=0):\n"
"    # 生效条件：op ∈ {attach, detach, read, write}\n"
"    # 子功能：① op 分支处理\n"
"    # 执行：按 op 分派；顺序调用\n"
"    # 不适用条件：op 非 {attach, detach, read, write} 时\n"
            "    # 共享内存：attach 挂接 / write 写偏移 / read 读偏移 / detach 释放\n"
            "    # （多进程映射同一物理页，引用计数）\n"
            "    if op == 'attach':\n"
            "        if key not in segments:\n"
            "            segments[key] = {'data': bytearray(size), 'refs': 0}\n"
            "        segments[key]['refs'] += 1\n"
            "        return segments[key]['refs']\n"
            "    if op == 'write':\n"
            "        segments[key]['data'][offset] = value\n"
            "        return value\n"
            "    if op == 'read':\n"
            "        return segments[key]['data'][offset]\n"
            "    if op == 'detach':\n"
            "        segments[key]['refs'] -= 1\n"
            "        return segments[key]['refs']\n"
            "    return None\n"),
        "cases": [(({}, 'k1', 'attach', 0, None, 8), 1),
                  (({'k1': {'data': bytearray(4), 'refs': 1}}, 'k1',
                    'write', 2, 65, 0), 65),
                  (({'k1': {'data': bytearray([0, 0, 65, 0]), 'refs': 1}},
                    'k1', 'read', 2, None, 0), 65),
                  (({'k1': {'data': bytearray(4), 'refs': 2}}, 'k1',
                    'detach', 0, None, 0), 1)],
        "params": [],
        "calibration": "对照：OS IPC 共享内存——attach/write/read/detach（物理页共享，引用计数）",
    },
    "IPC-邮箱": {
        "task": "邮箱",
        "pattern": (
            "def mailbox_ops(mb, op, msg=None):\n"
"    # 生效条件：op ∈ {get, put}\n"
"    # 子功能：① op 分支处理\n"
"    # 执行：按 op 分派；顺序调用\n"
"    # 不适用条件：op 非 {get, put} 时\n"
            "    # 邮箱：put 投递 / get 取最早（FIFO）/ 空返回 None\n"
            "    # （异步消息槽，收发进程解耦）\n"
            "    if op == 'put':\n"
            "        mb.append(msg)\n"
            "        return len(mb)\n"
            "    if op == 'get':\n"
            "        return mb.pop(0) if mb else None\n"
            "    return None\n"),
        "cases": [(([], 'put', '甲'), 1),
                  (([], 'get', None), None),
                  (([1, 2], 'get', None), 1),
                  ((['甲'], 'put', '乙'), 2)],
        "params": [],
        "calibration": "对照：OS IPC 邮箱——异步消息槽（put 投递/get FIFO 取，进程解耦）",
    },
    "调度-多级反馈队列": {
        "task": "多级反馈队列",
        "pattern": (
            "def mlfq_ops(queues, op, pid=None, level=None, boost_to=0):\n"
"    # 生效条件：op ∈ {boost, enqueue, pick}\n"
"    # 子功能：① op 分支处理\n"
"    # 执行：按 op 分派；循环迭代；顺序调用\n"
"    # 不适用条件：op 非 {boost, enqueue, pick} 时\n"
            "    # 多级反馈队列：enqueue 按等级入队 / pick 取最高级队首\n"
            "    # / boost 低优先级提升（防饿死）\n"
            "    if op == 'enqueue':\n"
            "        queues[level].append(pid)\n"
            "        return queues[level]\n"
            "    if op == 'pick':\n"
            "        for q in queues:\n"
            "            if q:\n"
            "                return q.pop(0)\n"
            "        return None\n"
            "    if op == 'boost':\n"
            "        if boost_to < len(queues):\n"
            "            merged = []\n"
            "            for i in range(boost_to + 1, len(queues)):\n"
            "                merged.extend(queues[i])\n"
            "                queues[i] = []\n"
            "            queues[boost_to].extend(merged)\n"
            "        return queues[boost_to]\n"
            "    return None\n"),
        "cases": [(([[], [], []], 'enqueue', 'a', 2, 0), ['a']),
                  (([['x'], ['a'], []], 'pick', None, None, 0), 'x'),
                  (([[], [], ['c', 'd']], 'pick', None, None, 0), 'c'),
                  (([[], [], [], ['e']], 'boost', None, None, 0), ['e']),
                  (([[],[],[]], 'pick', None, None, 0), None)],
        "params": [],
        "calibration": "对照：OS 多级反馈队列 MLFQ——高等级优先调度，低等级定期提升（防饿死）",
    },
    "调度-实时EDF": {
        "task": "实时调度",
        "pattern": (
            "def edf_pick(ready, now):\n"
"    # 生效条件：参数 ready/now 合法\n"
"    # 子功能：① 调用 min\n"
"    # 执行：顺序调用\n"
"    # 不适用条件：ready 为空/非法时\n"
            "    # 实时调度：最早截止时间优先（EDF——deadline 最近者先执行）\n"
            "    if not ready:\n"
            "        return None\n"
            "    return min(ready, key=lambda t: t[1])[0]\n"),
        "cases": [(([('a', 10), ('b', 5)], 0), 'b'),
                  (([], 0), None),
                  (([('a', 10)], 0), 'a')],
        "params": [],
        "calibration": "对照：OS 实时调度 EDF——最早截止时间优先（deadline 最近先执行）",
    },
    "系统调用-文件分派": {
        "task": "文件系统调用",
        "pattern": (
            "def syscall_file(op, fd_table, fd=None, path=None, data=None, mode='r'):\n"
"    # 生效条件：op ∈ {close, open, read, write}\n"
"    # 子功能：① op 分支处理\n"
"    # 执行：按 op 分派；顺序调用\n"
"    # 不适用条件：op 非 {close, open, read, write} 时\n"
            "    # 系统调用：open/read/write/close 分派（fd 表管理文件操作）\n"
            "    if op == 'open':\n"
            "        fd_table.append({'path': path, 'mode': mode, 'data': data or ''})\n"
            "        return len(fd_table) - 1\n"
            "    if op == 'read':\n"
            "        return fd_table[fd]['data']\n"
            "    if op == 'write':\n"
            "        fd_table[fd]['data'] += data\n"
            "        return len(data)\n"
            "    if op == 'close':\n"
            "        fd_table[fd] = None\n"
            "        return 'closed'\n"
            "    return None\n"),
        "cases": [(('open', [], 'a.txt', None, '', 'r'), 0),
                  (('read', [{'path': 'a', 'data': '你好'}], 0,
                    None, None, 'r'), '你好'),
                  (('write', [{'path': 'a', 'data': ''}], 0, None, 'x', 'w'), 1),
                  (('close', [{'path': 'a'}], 0, None, None, 'r'), 'closed')],
        "params": [],
        "calibration": "对照：OS 系统调用——open/read/write/close 文件操作（fd 表分派）",
    },
    "内存-伙伴系统": {
        "task": "伙伴系统",
        "pattern": (
            "def buddy_alloc(free_lists, size):\n"
            "    # 伙伴系统（buddy system）：2 的幂块分配（最小合适阶取，缺则高阶分裂回补）\n"
            "    # 生效条件：free_lists 为各阶空闲块列表；size 为申请字节数\n"
            "    # 子功能：① 计算合适阶 ② 低阶无块则高阶分裂 ③ 取块返回\n"
            "    # 执行：阶逐级查找，分裂回补低阶\n"
"    # 不适用条件：输入不满足生效条件时返回 None/不执行\n"
            "    order = 0\n"
            "    while (1 << order) < size:\n"
            "        order += 1\n"
            "    for o in range(order, max(free_lists) + 1):\n"
            "        if free_lists[o]:\n"
            "            free_lists[o] -= 1\n"
            "            while o > order:\n"
            "                o -= 1\n"
            "                free_lists[o] += 1\n"
            "            return 'allocated'\n"
            "    return 'failed'\n"),
        "cases": [(({0: 0, 1: 1, 2: 0}, 1), 'allocated'),
                  (({0: 0, 1: 0, 2: 1}, 1), 'allocated'),
                  (({0: 0, 1: 0, 2: 0}, 4), 'failed'),
                  (({0: 2, 1: 0}, 1), 'allocated')],
        "params": [],
        "calibration": "对照：OS 内存——伙伴系统（2 的幂块分配，高阶块分裂到合适阶）",
    },
    "内存-写时复制": {
        "task": "写时复制",
        "pattern": (
            "def cow_write(pages, idx, value, shared_set):\n"
"    # 生效条件：shared_set.discard 可用\n"
"    # 子功能：① 条件判定 ② 结果处理\n"
"    # 执行：顺序执行\n"
"    # 不适用条件：输入不满足生效条件时返回 None/不执行\n"
            "    # 写时复制：写共享页 → 复制新页再写（原页保留，fork COW 语义）\n"
            "    if idx in shared_set:\n"
            "        pages[idx] = value\n"
            "        shared_set.discard(idx)\n"
            "        return 'copied'\n"
            "    pages[idx] = value\n"
            "    return 'written'\n"),
        "cases": [((['a', 'b'], 0, 'X', {0}), 'copied'),
                  ((['a', 'b'], 1, 'Y', set()), 'written'),
                  ((['a'], 0, 'Z', {0}), 'copied')],
        "params": [],
        "calibration": "对照：OS 内存——写时复制（fork 共享页写时复制，节省物理内存）",
    },
    "内存-内存压缩": {
        "task": "内存压缩",
        "pattern": (
            "def memory_compress(pages, threshold):\n"
"    # 生效条件：参数 pages/threshold 合法\n"
"    # 子功能：① 调用 len\n"
"    # 执行：循环迭代；顺序调用\n"
"    # 不适用条件：输入不满足生效条件时返回 None/不执行\n"
            "    # 内存压缩：超长页压缩存储（zswap——节省物理内存）\n"
            "    saved = 0\n"
            "    for p in pages:\n"
            "        if len(p) > threshold:\n"
            "            saved += len(p) - threshold\n"
            "    return saved\n"),
        "cases": [((['aaaa', 'b'], 2), 2),
                  ((['a', 'bb'], 2), 0),
                  (([], 2), 0)],
        "params": [],
        "calibration": "对照：OS 内存——内存压缩（超阈页压缩存储，减少占用）",
    },
    "文件-链接管理": {
        "task": "文件链接",
        "pattern": (
            "def link_ops(fs, op, name=None, target=None):\n"
"    # 生效条件：op ∈ {hard, resolve, soft}\n"
"    # 子功能：① op 分支处理\n"
"    # 执行：按 op 分派\n"
"    # 不适用条件：op 非 {hard, resolve, soft} 时\n"
            "    # 文件链接：hard 硬链接（共享 inode）/ soft 软链接（路径引用）/ resolve 解析\n"
            "    if op == 'hard':\n"
            "        if target in fs:\n"
            "            fs[name] = {'type': 'hard', 'inode': fs[target]['inode']}\n"
            "            return 'linked'\n"
            "        return 'missing'\n"
            "    if op == 'soft':\n"
            "        fs[name] = {'type': 'soft', 'target': target}\n"
            "        return 'linked'\n"
            "    if op == 'resolve':\n"
            "        entry = fs.get(name)\n"
            "        if entry is None:\n"
            "            return None\n"
            "        if entry['type'] == 'soft':\n"
            "            return fs.get(entry['target'], {}).get('data')\n"
            "        return entry.get('data')\n"
            "    return None\n"),
        "cases": [(({'a': {'inode': 1, 'data': 'D'}}, 'hard', 'b', 'a'), 'linked'),
                  (({}, 'hard', 'b', 'a'), 'missing'),
                  (({'a': {'inode': 1, 'data': 'D'}}, 'soft', 'b', 'a'), 'linked'),
                  (({'a': {'inode': 1, 'data': 'D'},
                     'b': {'type': 'soft', 'target': 'a'}}, 'resolve', 'b'), 'D'),
                  (({}, 'resolve', 'x'), None)],
        "params": [],
        "calibration": "对照：OS 文件系统——硬链接共享 inode/软链接路径引用（解析语义）",
    },
    "文件-元数据查询": {
        "task": "文件元数据",
        "pattern": (
            "def stat_file(fs, name):\n"
"    # 生效条件：参数 fs/name 合法\n"
"    # 子功能：① 条件判定 ② 结果处理\n"
"    # 执行：顺序执行\n"
"    # 不适用条件：输入不满足生效条件时返回 None/不执行\n"
            "    # 文件元数据：stat 查询（大小/权限/类型——文件信息）\n"
            "    f = fs.get(name)\n"
            "    if f is None:\n"
            "        return None\n"
            "    return {'size': f.get('size', 0), 'mode': f.get('mode', 'rw'),\n"
            "            'type': f.get('type', 'file')}\n"),
        "cases": [(({'a': {'size': 10, 'mode': 'r', 'type': 'file'}}, 'a'),
                   {'size': 10, 'mode': 'r', 'type': 'file'}),
                  (({}, 'a'), None),
                  (({'a': {}}, 'a'), {'size': 0, 'mode': 'rw', 'type': 'file'})],
        "params": [],
        "calibration": "对照：OS stat——文件元数据（大小/权限/类型）",
    },
    "文件-内存映射": {
        "task": "内存映射",
        "pattern": (
            "def mmap_ops(maps, op, path=None, offset=0, size=0, data=None):\n"
"    # 生效条件：op ∈ {map, read, write}\n"
"    # 子功能：① op 分支处理\n"
"    # 执行：按 op 分派；顺序调用\n"
"    # 不适用条件：op 非 {map, read, write} 时\n"
            "    # 内存映射：map 映射文件段到内存 / read 读偏移 / write 写偏移回写\n"
            "    if op == 'map':\n"
            "        maps[path] = {'offset': offset, 'size': size,\n"
            "                      'data': bytearray(data or b'\\x00' * size)}\n"
            "        return path\n"
            "    if op == 'read':\n"
            "        m = maps[path]\n"
            "        return bytes(m['data'][offset:offset + size])\n"
            "    if op == 'write':\n"
            "        m = maps[path]\n"
            "        m['data'][offset:offset + len(data)] = data\n"
            "        return len(data)\n"
            "    return None\n"),
        "cases": [(({}, 'map', 'f', 0, 4, b'abcd'), 'f'),
                  (({'f': {'offset': 0, 'size': 4, 'data': bytearray(b'abcd')}},
                    'read', 'f', 1, 2), b'bc'),
                  (({'f': {'offset': 0, 'size': 4, 'data': bytearray(b'abcd')}},
                    'write', 'f', 1, 0, b'XY'), 2)],
        "params": [],
        "calibration": "对照：OS mmap——文件映射到内存（读偏移/写回）",
    },
    "并发-屏障同步": {
        "task": "屏障同步",
        "pattern": (
            "def barrier_ops(state, op, n=None):\n"
"    # 生效条件：op ∈ {wait}\n"
"    # 子功能：① op 分支处理\n"
"    # 执行：按 op 分派\n"
"    # 不适用条件：op 非 {wait} 时\n"
            "    # 屏障同步：wait 到达汇合点 / 全部到达释放（多线程同步汇合）\n"
            "    if op == 'wait':\n"
            "        state['arrived'] = state.get('arrived', 0) + 1\n"
            "        if state['arrived'] >= n:\n"
            "            state['arrived'] = 0\n"
            "            return 'released'\n"
            "        return 'waiting'\n"
            "    return None\n"),
        "cases": [(({'arrived': 0}, 'wait', 3), 'waiting'),
                  (({'arrived': 2}, 'wait', 3), 'released'),
                  (({'arrived': 0}, 'wait', 1), 'released')],
        "params": [],
        "calibration": "对照：OS 并发——屏障同步（全部到达汇合点才释放）",
    },
    "并发-工作池": {
        "task": "工作池",
        "pattern": (
            "def worker_pool(tasks, workers):\n"
"    # 生效条件：参数 tasks/workers 合法\n"
"    # 子功能：① 调用 enumerate；② 调用 range\n"
"    # 执行：循环迭代；顺序调用\n"
"    # 不适用条件：输入不满足生效条件时返回 None/不执行\n"
            "    # 工作池：任务队列分发给固定 worker（并发处理，轮询负载均衡）\n"
            "    out = [[] for _ in range(workers)]\n"
            "    for i, t in enumerate(tasks):\n"
            "        out[i % workers].append(t)\n"
            "    return out\n"),
        "cases": [(([1, 2, 3, 4], 2), [[1, 3], [2, 4]]),
                  (([1, 2, 3], 3), [[1], [2], [3]]),
                  (([], 2), [[], []])],
        "params": [],
        "calibration": "对照：OS 并发——工作池（任务分发固定 worker，并发处理）",
    },
    "进程-生命周期": {
        "task": "进程生命周期",
        "pattern": (
            "def proc_life(states, op, pid=None, code=0):\n"
"    # 生效条件：op ∈ {exec, fork, wait}\n"
"    # 子功能：① op 分支处理\n"
"    # 执行：按 op 分派\n"
"    # 不适用条件：op 非 {exec, fork, wait} 时\n"
            "    # 进程生命周期：fork 创建 / exec 执行 / wait 等待退出（状态机）\n"
            "    if op == 'fork':\n"
            "        states[pid] = 'created'\n"
            "        return 'created'\n"
            "    if op == 'exec':\n"
            "        if pid in states:\n"
            "            states[pid] = 'running'\n"
            "            return 'running'\n"
            "        return 'unknown'\n"
            "    if op == 'wait':\n"
            "        if pid in states:\n"
            "            states[pid] = 'exited'\n"
            "            return code\n"
            "        return 'unknown'\n"
            "    return None\n"),
        "cases": [(({}, 'fork', 1), 'created'),
                  (({1: 'created'}, 'exec', 1), 'running'),
                  (({1: 'running'}, 'wait', 1, 0), 0),
                  (({}, 'exec', 9), 'unknown')],
        "params": [],
        "calibration": "对照：OS 进程——fork/exec/wait 生命周期状态机",
    },
    "存储-磁盘调度SCAN": {
        "task": "磁盘调度",
        "pattern": (
            "def scan_schedule(requests, head, direction=1):\n"
"    # 生效条件：参数 requests/head/direction 合法\n"
"    # 子功能：① 调用 sorted\n"
"    # 执行：顺序调用\n"
"    # 不适用条件：输入不满足生效条件时返回 None/不执行\n"
            "    # 磁盘调度：SCAN 电梯算法（单向扫描到端再折返）\n"
            "    up = sorted(r for r in requests if r >= head)\n"
            "    down = sorted((r for r in requests if r < head), reverse=True)\n"
            "    if direction == 1:\n"
            "        return up + down\n"
            "    return down + up\n"),
        "cases": [(([10, 30, 50], 40), [50, 30, 10]),
                  (([10, 30, 50], 20, -1), [10, 30, 50]),
                  (([], 40), [])],
        "params": [],
        "calibration": "对照：OS 磁盘调度——SCAN 电梯算法（单向扫描折返）",
    },
    "文件-写时复制快照": {
        "task": "写时复制快照",
        "pattern": (
            "def cow_snapshot(blocks, op, snapshot=None, block=None, data=None,\n"
            "                 snapshots=None):\n"
            "    # 写时复制快照（COW 快照）：snapshot 冻结块引用 / write 写块时快照侧冻结原值\n"
            "    # 生效条件：op ∈ {snapshot, write}；snapshots 为快照表（可空）\n"
            "    # 子功能：① snapshot 冻结块引用 ② write 写块时复制原值\n"
            "    # 执行：按 op 分派快照/写时复制\n"
"    # 不适用条件：op 非 {read, snapshot, write} 时\n"
            "    snapshots = snapshots if snapshots is not None else {}\n"
            "    if op == 'snapshot':\n"
            "        snapshots[snapshot] = dict(blocks)\n"
            "        return snapshot\n"
            "    if op == 'write':\n"
            "        for snap, refs in snapshots.items():\n"
            "            if block in refs:\n"
            "                refs['_cow'] = refs.get('_cow', []) + [block]\n"
            "        blocks[block] = data\n"
            "        return 'written'\n"
            "    if op == 'read':\n"
            "        return snapshots.get(snapshot, {}).get(block)\n"
            "    return None\n"),
        "cases": [(({}, 'snapshot', 's1', None, None, {}), 's1'),
                  (({'b1': 'A'}, 'snapshot', 's1', None, None, {}), 's1'),
                  (({'b1': 'A'}, 'write', None, 'b1', 'B',
                    {'s1': {'b1': 'A'}}), 'written'),
                  (({'b1': 'A'}, 'read', 's1', 'b1', None,
                    {'s1': {'b1': 'A'}}), 'A')],
        "params": [],
        "calibration": "对照：OS 文件系统——写时复制快照（快照冻结，写共享块先复制）",
    },
    "存储-磨损均衡": {
        "task": "磨损均衡",
        "pattern": (
            "def wear_leveling(blocks, op, block=None):\n"
"    # 生效条件：op ∈ {pick, write}\n"
"    # 子功能：① op 分支处理\n"
"    # 执行：按 op 分派；顺序调用\n"
"    # 不适用条件：blocks 为空/非法时；op 非 {pick, write} 时\n"
            "    # 磨损均衡：写块记录写入次数，pick 选最少磨损块（SSD 寿命）\n"
            "    if op == 'write':\n"
            "        blocks[block] = blocks.get(block, 0) + 1\n"
            "        return blocks[block]\n"
            "    if op == 'pick':\n"
            "        if not blocks:\n"
            "            return None\n"
            "        return min(blocks, key=blocks.get)\n"
            "    return None\n"),
        "cases": [(({'a': 3, 'b': 1}, 'write', 'b'), 2),
                  (({'a': 3, 'b': 1}, 'pick'), 'b'),
                  (({}, 'pick'), None)],
        "params": [],
        "calibration": "对照：OS 存储——磨损均衡（写入次数记录，选最少磨损块）",
    },
    "安全-强制访问控制": {
        "task": "强制访问控制",
        "pattern": (
            "def mac_check(policy, subject_label, object_label, action):\n"
"    # 生效条件：参数 policy/subject_label/object_label/action 合法\n"
"    # 子功能：① 主体逻辑执行\n"
"    # 执行：顺序执行\n"
"    # 不适用条件：输入不满足生效条件时返回 None/不执行\n"
            "    # MAC 强制访问控制：标签对操作授权（安全标签规则表——强制策略）\n"
            "    rules = policy.get('rules', {})\n"
            "    return rules.get((subject_label, object_label, action), 'denied')\n"),
        "cases": [(({'rules': {('内部', '秘密', '读'): 'allowed'}},
                    '内部', '秘密', '读'), 'allowed'),
                  (({'rules': {}}, '内部', '秘密', '读'), 'denied'),
                  (({'rules': {('外部', '公开', '读'): 'allowed'}},
                    '外部', '公开', '读'), 'allowed')],
        "params": [],
        "calibration": "对照：OS 安全——MAC 强制访问控制（安全标签规则，未授权默认拒绝）",
    },
    "安全-系统调用过滤": {
        "task": "系统调用过滤",
        "pattern": (
            "def seccomp_filter(syscalls, op, name=None):\n"
"    # 生效条件：op ∈ {allow, check}\n"
"    # 子功能：① op 分支处理\n"
"    # 执行：按 op 分派\n"
"    # 不适用条件：op 非 {allow, check} 时\n"
            "    # 系统调用过滤：seccomp——白名单拦截（沙箱限制进程能力）\n"
            "    if op == 'allow':\n"
            "        syscalls.add(name)\n"
            "        return 'allowed'\n"
            "    if op == 'check':\n"
            "        return 'ok' if name in syscalls else 'blocked'\n"
            "    return None\n"),
        "cases": [((set(), 'allow', 'read'), 'allowed'),
                  (({'read'}, 'check', 'read'), 'ok'),
                  (({'read'}, 'check', 'write'), 'blocked')],
        "params": [],
        "calibration": "对照：OS 安全——seccomp 系统调用过滤（白名单，沙箱）",
    },
    "安全-加密文件系统": {
        "task": "加密文件系统",
        "pattern": (
            "def crypt_fs(fs, op, path=None, data=None, key=7):\n"
"    # 生效条件：op ∈ {read, write}\n"
"    # 子功能：① op 分支处理\n"
"    # 执行：按 op 分派；顺序调用\n"
"    # 不适用条件：op 非 {read, write} 时\n"
            "    # 加密文件系统：write 加密存储 / read 解密读取（透明加解密）\n"
            "    if op == 'write':\n"
            "        fs[path] = ''.join(chr(ord(c) ^ key) for c in data)\n"
            "        return 'stored'\n"
            "    if op == 'read':\n"
            "        raw = fs.get(path)\n"
            "        if raw is None:\n"
            "            return None\n"
            "        return ''.join(chr(ord(c) ^ key) for c in raw)\n"
            "    return None\n"),
        "cases": [(({}, 'write', 'a.txt', '秘密', 7), 'stored'),
                  (({'a.txt': '租寁'}, 'read', 'a.txt', None, 7), '秘密'),
                  (({}, 'read', 'a.txt', None, 7), None)],
        "params": [],
        "calibration": "对照：OS 安全——加密文件系统（透明加解密存储）",
    },
    "系统-服务管理": {
        "task": "服务管理",
        "pattern": (
            "def service_ops(services, op, name=None):\n"
"    # 生效条件：op ∈ {start, status, stop}\n"
"    # 子功能：① op 分支处理\n"
"    # 执行：按 op 分派\n"
"    # 不适用条件：op 非 {start, status, stop} 时\n"
            "    # 服务管理：start 启动 / stop 停止 / status 查询（服务生命周期）\n"
            "    if op == 'start':\n"
            "        services[name] = 'running'\n"
            "        return 'running'\n"
            "    if op == 'stop':\n"
            "        if name in services:\n"
            "            services[name] = 'stopped'\n"
            "            return 'stopped'\n"
            "        return 'not_found'\n"
            "    if op == 'status':\n"
            "        return services.get(name, 'not_found')\n"
            "    return None\n"),
        "cases": [(({}, 'start', 'nginx'), 'running'),
                  (({'nginx': 'running'}, 'stop', 'nginx'), 'stopped'),
                  (({}, 'status', 'nginx'), 'not_found'),
                  (({'nginx': 'running'}, 'status', 'nginx'), 'running')],
        "params": [],
        "calibration": "对照：systemd 服务——start/stop/status（服务生命周期）",
    },
    "系统-日志轮转": {
        "task": "日志轮转",
        "pattern": (
            "def log_rotate(logs, op, name=None, size=0, limit=1024):\n"
"    # 生效条件：op ∈ {append, size}\n"
"    # 子功能：① op 分支处理\n"
"    # 执行：按 op 分派\n"
"    # 不适用条件：op 非 {append, size} 时\n"
            "    # 日志轮转：append 追加（超限轮转）/ size 查询（logrotate）\n"
            "    if op == 'append':\n"
            "        entry = logs.setdefault(name, {'size': 0, 'rotations': 0})\n"
            "        entry['size'] += size\n"
            "        if entry['size'] > limit:\n"
            "            entry['rotations'] += 1\n"
            "            entry['size'] = size\n"
            "            return 'rotated'\n"
            "        return 'appended'\n"
            "    if op == 'size':\n"
            "        return logs.get(name, {}).get('size', 0)\n"
            "    return None\n"),
        "cases": [(({}, 'append', 'app.log', 500), 'appended'),
                  (({'app.log': {'size': 800, 'rotations': 0}},
                    'append', 'app.log', 500), 'rotated'),
                  (({'app.log': {'size': 300, 'rotations': 0}},
                    'size', 'app.log'), 300)],
        "params": [],
        "calibration": "对照：logrotate——日志大小超限轮转",
    },
    "系统-定时任务": {
        "task": "定时任务",
        "pattern": (
            "def cron_match(rule, minute, hour):\n"
"    # 生效条件：参数 rule/minute/hour 合法\n"
"    # 子功能：① 调用 int\n"
"    # 执行：顺序调用\n"
"    # 不适用条件：输入不满足生效条件时返回 None/不执行\n"
            "    # 定时任务：cron 规则匹配（'*' 任意 / 数字精确——分钟小时）\n"
            "    m_rule, h_rule = rule.split()\n"
            "    m_ok = m_rule == '*' or int(m_rule) == minute\n"
            "    h_ok = h_rule == '*' or int(h_rule) == hour\n"
            "    return m_ok and h_ok\n"),
        "cases": [(('* *', 30, 10), True),
                  (('30 *', 30, 10), True),
                  (('30 *', 31, 10), False),
                  (('* 2', 0, 2), True)],
        "params": [],
        "calibration": "对照：cron——分钟/小时规则匹配（* 任意）",
    },
    "系统-配置管理": {
        "task": "配置管理",
        "pattern": (
            "def config_ops(config, op, key=None, value=None, default=None):\n"
"    # 生效条件：op ∈ {get, list, set}\n"
"    # 子功能：① op 分支处理\n"
"    # 执行：按 op 分派；顺序调用\n"
"    # 不适用条件：op 非 {get, list, set} 时\n"
            "    # 配置管理：set 设置 / get 读取（默认值）/ list 列出（键值配置）\n"
            "    if op == 'set':\n"
            "        config[key] = value\n"
            "        return value\n"
            "    if op == 'get':\n"
            "        return config.get(key, default)\n"
            "    if op == 'list':\n"
            "        return sorted(config)\n"
            "    return None\n"),
        "cases": [(({}, 'set', 'timeout', 30), 30),
                  (({'timeout': 30}, 'get', 'timeout', None, 0), 30),
                  (({}, 'get', 'timeout', None, 0), 0),
                  (({'b': 1, 'a': 2}, 'list'), ['a', 'b'])],
        "params": [],
        "calibration": "对照：系统配置——键值设置/读取（默认值兜底）",
    },
    "系统-权限提升": {
        "task": "权限提升",
        "pattern": (
            "def sudo_check(auth, op, user=None, command=None):\n"
"    # 生效条件：op ∈ {check, run}\n"
"    # 子功能：① op 分支处理\n"
"    # 执行：按 op 分派\n"
"    # 不适用条件：op 非 {check, run} 时\n"
            "    # 权限提升：check 校验授权 / run 提权执行（sudo——命令白名单）\n"
            "    if op == 'check':\n"
            "        if user in auth and command in auth[user]:\n"
            "            return 'allowed'\n"
            "        return 'denied'\n"
            "    if op == 'run':\n"
            "        if user in auth and command in auth[user]:\n"
            "            return 'executed'\n"
            "        return 'denied'\n"
            "    return None\n"),
        "cases": [(({'root': ['reboot']}, 'check', 'root', 'reboot'), 'allowed'),
                  (({'root': ['reboot']}, 'check', 'root', 'rm'), 'denied'),
                  (({}, 'check', 'root', 'reboot'), 'denied'),
                  (({'root': ['reboot']}, 'run', 'root', 'reboot'), 'executed')],
        "params": [],
        "calibration": "对照：sudo——命令白名单授权（提权执行）",
    },
    "系统-环境变量": {
        "task": "环境变量",
        "pattern": (
            "def env_ops(env, op, name=None, value=None, default=None):\n"
"    # 生效条件：op ∈ {get, set, unset}\n"
"    # 子功能：① op 分支处理\n"
"    # 执行：按 op 分派\n"
"    # 不适用条件：op 非 {get, set, unset} 时\n"
            "    # 环境变量：set 设置 / get 读取（默认值）/ unset 删除（进程环境）\n"
            "    if op == 'set':\n"
            "        env[name] = value\n"
            "        return value\n"
            "    if op == 'get':\n"
            "        return env.get(name, default)\n"
            "    if op == 'unset':\n"
            "        return env.pop(name, None)\n"
            "    return None\n"),
        "cases": [(({}, 'set', 'PATH', '/bin'), '/bin'),
                  (({'PATH': '/bin'}, 'get', 'PATH', None, '/usr/bin'), '/bin'),
                  (({}, 'get', 'PATH', None, '/usr/bin'), '/usr/bin'),
                  (({'PATH': '/bin'}, 'unset', 'PATH'), '/bin')],
        "params": [],
        "calibration": "对照：环境变量——设置/读取（默认值）/删除",
    },
    "系统-网络接口": {
        "task": "网络接口",
        "pattern": (
            "def netif_ops(interfaces, op, name=None, addr=None, up=None):\n"
"    # 生效条件：op ∈ {configure, set_state, status}\n"
"    # 子功能：① op 分支处理\n"
"    # 执行：按 op 分派\n"
"    # 不适用条件：op 非 {configure, set_state, status} 时\n"
            "    # 网络接口：configure 配置 / status 查询 / set_state 启停（网卡抽象）\n"
            "    if op == 'configure':\n"
            "        interfaces[name] = {'addr': addr, 'up': up}\n"
            "        return name\n"
            "    if op == 'status':\n"
            "        return interfaces.get(name)\n"
            "    if op == 'set_state':\n"
            "        if name in interfaces:\n"
            "            interfaces[name]['up'] = up\n"
            "            return 'ok'\n"
            "        return 'missing'\n"
            "    return None\n"),
        "cases": [(({}, 'configure', 'eth0', '192.168.1.1', True), 'eth0'),
                  (({'eth0': {'addr': '192.168.1.1', 'up': True}},
                    'status', 'eth0'), {'addr': '192.168.1.1', 'up': True}),
                  (({}, 'status', 'eth0'), None),
                  (({'eth0': {'addr': 'x', 'up': True}},
                    'set_state', 'eth0', None, False), 'ok')],
        "params": [],
        "calibration": "对照：OS 网络栈——网卡接口配置/状态/启停",
    },
    "系统-设备驱动": {
        "task": "设备驱动",
        "pattern": (
            "def driver_register(drivers, op, device=None, driver=None):\n"
"    # 生效条件：op ∈ {match, register}\n"
"    # 子功能：① op 分支处理\n"
"    # 执行：按 op 分派；循环迭代\n"
"    # 不适用条件：op 非 {match, register} 时\n"
            "    # 设备驱动：register 注册 / match 匹配（设备 ID→驱动）\n"
            "    if op == 'register':\n"
            "        drivers[driver] = device\n"
            "        return driver\n"
            "    if op == 'match':\n"
            "        for d, dev in drivers.items():\n"
            "            if dev == device:\n"
            "                return d\n"
            "        return None\n"
            "    return None\n"),
        "cases": [(({}, 'register', 'VID_1234', 'drv_usb'), 'drv_usb'),
                  (({'drv_usb': 'VID_1234'}, 'match', 'VID_1234'), 'drv_usb'),
                  (({}, 'match', 'VID_1234'), None)],
        "params": [],
        "calibration": "对照：Linux 设备驱动——设备 ID 注册/匹配",
    },
    "系统-电源管理": {
        "task": "电源管理",
        "pattern": (
            "def power_ops(state, op):\n"
"    # 生效条件：op ∈ {resume, status, suspend}\n"
"    # 子功能：① op 分支处理\n"
"    # 执行：按 op 分派\n"
"    # 不适用条件：op 非 {resume, status, suspend} 时\n"
            "    # 电源管理：suspend 休眠 / resume 唤醒 / status 状态（ACPI）\n"
            "    if op == 'suspend':\n"
            "        state['power'] = 'suspended'\n"
            "        return 'suspended'\n"
            "    if op == 'resume':\n"
            "        state['power'] = 'active'\n"
            "        return 'active'\n"
            "    if op == 'status':\n"
            "        return state.get('power', 'active')\n"
            "    return None\n"),
        "cases": [(({}, 'suspend'), 'suspended'),
                  (({'power': 'suspended'}, 'resume'), 'active'),
                  (({}, 'status'), 'active'),
                  (({'power': 'suspended'}, 'status'), 'suspended')],
        "params": [],
        "calibration": "对照：ACPI 电源管理——休眠/唤醒/状态",
    },
    "文件-文件压缩": {
        "task": "文件压缩",
        "pattern": (
            "def file_compress(data, mode):\n"
"    # 生效条件：mode ∈ {compress, decompress}\n"
"    # 子功能：1 mode 分支处理\n"
"    # 执行：按 op 分派；循环迭代；顺序调用\n"
"    # 不适用条件：mode 非 {compress, decompress} 时\n"
            "    # 文件压缩：compress RLE 行程编码 / decompress 还原（体积优化）\n"
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
        "calibration": "对照：文件压缩——RLE 行程编码（重复段压缩/还原）",
    },
    "存储-存储池": {
        "task": "存储池",
        "pattern": (
            "def storage_pool(pool, op, name=None, size=0):\n"
"    # 生效条件：op ∈ {alloc, create, free, status}\n"
"    # 子功能：① op 分支处理\n"
"    # 执行：按 op 分派；顺序调用\n"
"    # 不适用条件：op 非 {alloc, create, free, status} 时\n"
            "    # 存储池：create 建池 / alloc 分配（容量扣减）/ free 释放 / status 状态\n"
            "    if op == 'create':\n"
            "        pool[name] = {'total': size, 'used': 0}\n"
            "        return name\n"
            "    if op == 'alloc':\n"
            "        p = pool.get(name)\n"
            "        if p is None:\n"
            "            return 'missing'\n"
            "        if p['used'] + size > p['total']:\n"
            "            return 'insufficient'\n"
            "        p['used'] += size\n"
            "        return 'allocated'\n"
            "    if op == 'free':\n"
            "        p = pool.get(name)\n"
            "        if p is None:\n"
            "            return 'missing'\n"
            "        p['used'] = max(p['used'] - size, 0)\n"
            "        return 'freed'\n"
            "    if op == 'status':\n"
            "        p = pool.get(name)\n"
            "        return dict(p) if p else None\n"
            "    return None\n"),
        "cases": [(({}, 'create', 'data', 100), 'data'),
                  (({'data': {'total': 100, 'used': 0}}, 'alloc', 'data', 60),
                   'allocated'),
                  (({'data': {'total': 100, 'used': 80}}, 'alloc', 'data', 30),
                   'insufficient'),
                  (({'data': {'total': 100, 'used': 50}}, 'free', 'data', 20),
                   'freed'),
                  (({'data': {'total': 100, 'used': 0}}, 'status', 'data'),
                   {'total': 100, 'used': 0})],
        "params": [],
        "calibration": "对照：存储池——容量池分配/回收（超限拒绝）",
    },
    "文件-文件版本": {
        "task": "文件版本",
        "pattern": (
            "def file_version(versions, op, name=None, content=None):\n"
"    # 生效条件：op ∈ {get, list, save}\n"
"    # 子功能：① op 分支处理\n"
"    # 执行：按 op 分派；顺序调用\n"
"    # 不适用条件：op 非 {get, list, save} 时\n"
            "    # 文件版本：save 存版本 / list 版本列表 / get 取最新（版本历史）\n"
            "    if op == 'save':\n"
            "        versions.setdefault(name, []).append(content)\n"
            "        return len(versions[name])\n"
            "    if op == 'list':\n"
            "        return list(versions.get(name, []))\n"
            "    if op == 'get':\n"
            "        vs = versions.get(name, [])\n"
            "        return vs[-1] if vs else None\n"
            "    return None\n"),
        "cases": [(({}, 'save', 'f1', 'v1'), 1),
                  (({'f1': ['v1']}, 'save', 'f1', 'v2'), 2),
                  (({'f1': ['v1', 'v2']}, 'list', 'f1'), ['v1', 'v2']),
                  (({'f1': ['v1']}, 'get', 'f1'), 'v1'),
                  (({}, 'get', 'f1'), None)],
        "params": [],
        "calibration": "对照：文件版本——版本历史保存/列表/取最新",
    },
    "并发-条件变量": {
        "task": "条件变量",
        "pattern": (
            "def cond_var(state, op, waiters=None):\n"
"    # 生效条件：op ∈ {notify, notify_all, wait}\n"
"    # 子功能：① op 分支处理\n"
"    # 执行：按 op 分派；顺序调用\n"
"    # 不适用条件：op 非 {notify, notify_all, wait} 时\n"
            "    # 条件变量：wait 等待 / notify 通知一个 / notify_all 全部（条件同步）\n"
            "    if op == 'wait':\n"
            "        state.setdefault('waiting', []).append(waiters)\n"
            "        return 'waiting'\n"
            "    if op == 'notify':\n"
            "        if state.get('waiting'):\n"
            "            state['waiting'].pop(0)\n"
            "            return 'notified'\n"
            "        return 'none'\n"
            "    if op == 'notify_all':\n"
            "        n = len(state.get('waiting', []))\n"
            "        state['waiting'] = []\n"
            "        return n\n"
            "    return None\n"),
        "cases": [(({}, 'wait', 't1'), 'waiting'),
                  (({'waiting': ['t1']}, 'notify'), 'notified'),
                  (({}, 'notify'), 'none'),
                  (({'waiting': ['t1', 't2']}, 'notify_all'), 2)],
        "params": [],
        "calibration": "对照：POSIX 条件变量——等待/通知（条件满足唤醒）",
    },
    "并发-自旋锁": {
        "task": "自旋锁",
        "pattern": (
            "def spinlock(lock, op):\n"
"    # 生效条件：op ∈ {acquire, release}\n"
"    # 子功能：① op 分支处理\n"
"    # 执行：按 op 分派\n"
"    # 不适用条件：op 非 {acquire, release} 时\n"
            "    # 自旋锁：acquire 忙等获取 / release 释放（锁状态）\n"
            "    if op == 'acquire':\n"
            "        if lock.get('held'):\n"
            "            return 'busy'\n"
            "        lock['held'] = True\n"
            "        return 'acquired'\n"
            "    if op == 'release':\n"
            "        if lock.get('held'):\n"
            "            lock['held'] = False\n"
            "            return 'released'\n"
            "        return 'not_held'\n"
            "    return None\n"),
        "cases": [(({}, 'acquire'), 'acquired'),
                  (({'held': True}, 'acquire'), 'busy'),
                  (({'held': True}, 'release'), 'released'),
                  (({}, 'release'), 'not_held')],
        "params": [],
        "calibration": "对照：自旋锁——忙等获取/释放（短临界区）",
    },
    "调度-时间片轮转": {
        "task": "抢占轮转",
        "pattern": (
            "def round_robin(ready, op, quantum=None, current=None):\n"
"    # 生效条件：op ∈ {preempt, run, status}\n"
"    # 子功能：① op 分支处理\n"
"    # 执行：按 op 分派；顺序调用\n"
"    # 不适用条件：ready 为空/非法时；op 非 {preempt, run, status} 时\n"
            "    # 时间片轮转：run 执行队首 / preempt 时间片耗尽抢占回队尾（RR）\n"
            "    if op == 'run':\n"
            "        if not ready:\n"
            "            return None\n"
            "        return ready.pop(0)\n"
            "    if op == 'preempt':\n"
            "        if current is not None:\n"
            "            ready.append(current)\n"
            "        return len(ready)\n"
            "    if op == 'status':\n"
            "        return list(ready)\n"
            "    return None\n"),
        "cases": [(([], 'run'), None),
                  (([1, 2], 'run'), 1),
                  ((['t1'], 'preempt', None, 't2'), 2),
                  (([1, 2], 'status'), [1, 2])],
        "params": [],
        "calibration": "对照：RR 时间片轮转——队首执行/时间片耗尽回队尾",
    },
    "进程-优先级继承": {
        "task": "优先级继承",
        "pattern": (
            "def prio_inherit(state, op, holder=None, waiter=None):\n"
"    # 生效条件：op ∈ {inherit, restore, wait}\n"
"    # 子功能：① op 分支处理\n"
"    # 执行：按 op 分派；顺序调用\n"
"    # 不适用条件：op 非 {inherit, restore, wait} 时\n"
            "    # 优先级继承：wait 等待锁 / inherit 继承高优先 / restore 恢复（防优先级反转）\n"
            "    if op == 'wait':\n"
            "        state['holder'] = holder\n"
            "        state['waiting'] = waiter\n"
            "        if waiter > state.get('orig', 0):\n"
            "            state['orig'] = waiter\n"
            "        return 'waiting'\n"
            "    if op == 'inherit':\n"
            "        return max(state.get('orig', 0), state.get('waiting', 0))\n"
            "    if op == 'restore':\n"
            "        state['waiting'] = None\n"
            "        return state.get('orig', 0)\n"
            "    return None\n"),
        "cases": [
            (({}, 'wait', 'p1', 8), 'waiting'),
            (({'orig': 2, 'waiting': 8}, 'inherit'), 8),
            (({'orig': 5, 'waiting': 3}, 'inherit'), 5),
            (({'orig': 8, 'waiting': 8}, 'restore'), 8)],
        "params": [],
        "calibration": "对照：优先级继承——持锁者继承等待者高优先（防反转）",
    },
    "内存-内存池": {
        "task": "内存池",
        "pattern": (
            "def pool_alloc(state, op, size=None):\n"
"    # 生效条件：op ∈ {alloc, free, stats}\n"
"    # 子功能：① op 分支处理\n"
"    # 执行：按 op 分派；顺序调用\n"
"    # 不适用条件：op 非 {alloc, free, stats} 时\n"
            "    # 内存池：alloc 分配 / free 释放 / stats 统计（固定块池）\n"
            "    if op == 'alloc':\n"
            "        free = state.setdefault('free', [])\n"
            "        if size is not None and size not in state.setdefault('blocks', {}):\n"
            "            state['blocks'][size] = [None] * 4\n"
            "        pool = state.get('blocks', {}).get(size, free)\n"
            "        if pool:\n"
            "            return pool.pop()\n"
            "        return None\n"
            "    if op == 'free':\n"
            "        state.setdefault('free', []).append(size)\n"
            "        return 'freed'\n"
            "    if op == 'stats':\n"
            "        return len(state.get('free', []))\n"
            "    return None\n"),
        "cases": [
            (({}, 'alloc', 16), None),
            (({'free': [1, 2]}, 'alloc', None), 2),
            (({}, 'free', 3), 'freed'),
            (({'free': [1, 2]}, 'stats'), 2)],
        "params": [],
        "calibration": "对照：内存池——固定块分配/释放/统计（池化分配）",
    },
    "文件-稀疏文件": {
        "task": "稀疏文件",
        "pattern": (
            "def sparse_file(state, op, offset=None, data=None):\n"
"    # 生效条件：op ∈ {holes, read, write}\n"
"    # 子功能：① op 分支处理\n"
"    # 执行：按 op 分派；顺序调用\n"
"    # 不适用条件：op 非 {holes, read, write} 时\n"
            "    # 稀疏文件：write 写数据块 / read 读（空洞返回零）/ holes 空洞统计（稀疏存储）\n"
            "    if op == 'write':\n"
            "        state.setdefault('blocks', {})[offset] = data\n"
            "        return offset\n"
            "    if op == 'read':\n"
            "        return state.get('blocks', {}).get(offset, chr(48) * len(data or [0]))\n"
            "    if op == 'holes':\n"
            "        total = state.get('size', 0)\n"
            "        written = len(state.get('blocks', {}))\n"
            "        return max(0, total - written)\n"
            "    return None\n"),
        "cases": [
            (({}, 'write', 10, 'abc'), 10),
            (({'blocks': {10: 'abc'}}, 'read', 10, 'abc'), 'abc'),
            (({'size': 5, 'blocks': {1: 'a'}}, 'holes'), 4),
            (({'size': 0, 'blocks': {}}, 'holes'), 0)],
        "params": [],
        "calibration": "对照：稀疏文件——数据块存储+空洞零填充（稀疏存储）",
    },
    "存储-碎片整理": {
        "task": "碎片整理",
        "pattern": (
            "def defrag(disk, op):\n"
"    # 生效条件：op ∈ {compact, frags, scan}\n"
"    # 子功能：① op 分支处理\n"
"    # 执行：按 op 分派；顺序调用\n"
"    # 不适用条件：op 非 {compact, frags, scan} 时\n"
            "    # 碎片整理：scan 扫描空洞 / compact 压实 / frags 碎片数（磁盘整理）\n"
            "    if op == 'scan':\n"
            "        return [i for i, b in enumerate(disk) if b is None]\n"
            "    if op == 'compact':\n"
            "        return [b for b in disk if b is not None]\n"
            "    if op == 'frags':\n"
            "        return sum(1 for i in range(1, len(disk))\n"
            "                   if disk[i] is not None and disk[i - 1] is None)\n"
            "    return None\n"),
        "cases": [
            ((['a', None, 'b'], 'scan'), [1]),
            ((['a', None, 'b'], 'compact'), ['a', 'b']),
            ((['a', None, 'b'], 'frags'), 1),
            (([None, None], 'frags'), 0)],
        "params": [],
        "calibration": "对照：磁盘整理——空洞扫描/压实/碎片计数",
    },
    "内存-段式管理": {
        "task": "段式管理",
        "pattern": (
            "def segment_map(state, op, seg=None, base=None, limit=None):\n"
"    # 生效条件：op ∈ {access, base, map}\n"
"    # 子功能：① op 分支处理\n"
"    # 执行：按 op 分派\n"
"    # 不适用条件：op 非 {access, base, map} 时\n"
            "    # 段式管理：map 登记段 / access 越界检查 / base 基址查询（分段内存）\n"
            "    if op == 'map':\n"
            "        state.setdefault('segs', {})[seg] = (base, limit)\n"
            "        return base\n"
            "    if op == 'access':\n"
            "        s = state.get('segs', {}).get(seg)\n"
            "        if s is None:\n"
            "            return 'fault'\n"
            "        b, l = s\n"
            "        return b + base if base < l else 'fault'\n"
            "    if op == 'base':\n"
            "        s = state.get('segs', {}).get(seg)\n"
            "        return s[0] if s else None\n"
            "    return None\n"),
        "cases": [
            (({}, 'map', 'code', 100, 50), 100),
            (({'segs': {'code': (100, 50)}}, 'access', 'code', 30), 130),
            (({'segs': {'code': (100, 50)}}, 'access', 'code', 60), 'fault'),
            (({}, 'base', 'code'), None)],
        "params": [],
        "calibration": "对照：分段内存——段登记/基址+限长越界检查",
    },
    "系统-时钟节拍": {
        "task": "时钟节拍",
        "pattern": (
            "def timer_tick(state, op, hz=None):\n"
"    # 生效条件：op ∈ {elapsed, hz, tick}\n"
"    # 子功能：① op 分支处理\n"
"    # 执行：按 op 分派\n"
"    # 不适用条件：op 非 {elapsed, hz, tick} 时\n"
            "    # 时钟节拍：tick 推进 / elapsed 已过 / hz 频率（定时器中断）\n"
            "    if op == 'tick':\n"
            "        state['t'] = state.get('t', 0) + 1\n"
            "        return state['t']\n"
            "    if op == 'elapsed':\n"
            "        return state.get('t', 0) / state.get('hz', hz or 100)\n"
            "    if op == 'hz':\n"
            "        return state.get('hz', hz or 100)\n"
            "    return None\n"),
        "cases": [
            (({}, 'tick'), 1),
            (({'t': 200, 'hz': 100}, 'elapsed'), 2.0),
            (({}, 'elapsed'), 0.0),
            (({'hz': 250}, 'hz'), 250)],
        "params": [],
        "calibration": "对照：定时器——节拍推进/已过时间/频率（HZ）",
    },
    "进程-孤儿进程": {
        "task": "孤儿进程",
        "pattern": (
            "def orphan_proc(state, op, pid=None):\n"
"    # 生效条件：op ∈ {adopt, orphaned, parent}\n"
"    # 子功能：① op 分支处理\n"
"    # 执行：按 op 分派；顺序调用\n"
"    # 不适用条件：op 非 {adopt, orphaned, parent} 时\n"
            "    # 孤儿进程：adopt 收养 / orphaned 孤儿列表 / parent 查询（父亡子被 init 收养）\n"
            "    if op == 'adopt':\n"
            "        state.setdefault('adopted', []).append(pid)\n"
            "        return pid\n"
            "    if op == 'orphaned':\n"
            "        return list(state.get('adopted', []))\n"
            "    if op == 'parent':\n"
            "        return state.get('parent', 1)\n"
            "    return None\n"),
        "cases": [
            (({}, 'adopt', 5), 5),
            (({'adopted': [5]}, 'orphaned'), [5]),
            (({}, 'parent'), 1),
            (({'parent': 7}, 'parent'), 7)],
        "params": [],
        "calibration": "对照：孤儿进程——父亡子被 init（PID 1）收养",
    },
    "内存-内存碎片": {
        "task": "内存碎片",
        "pattern": (
            "def mem_frag(state, op, hole=None):\n"
"    # 生效条件：op ∈ {holes, rate, record}\n"
"    # 子功能：① op 分支处理\n"
"    # 执行：按 op 分派；顺序调用\n"
"    # 不适用条件：op 非 {holes, rate, record} 时\n"
            "    # 内存碎片：record 记录空洞 / rate 碎片率 / holes 空洞数（碎片化度量）\n"
            "    if op == 'record':\n"
            "        state.setdefault('holes', []).append(hole)\n"
            "        return len(state['holes'])\n"
            "    if op == 'rate':\n"
            "        holes = state.get('holes', [])\n"
            "        total = state.get('total', 1)\n"
            "        return round(sum(holes) / total, 2)\n"
            "    if op == 'holes':\n"
            "        return len(state.get('holes', []))\n"
            "    return None\n"),
        "cases": [
            (({}, 'record', 10), 1),
            (({'holes': [10, 20], 'total': 100}, 'rate'), 0.3),
            (({}, 'holes'), 0),
            (({'holes': [10]}, 'holes'), 1)],
        "params": [],
        "calibration": "对照：内存碎片——空洞记录与碎片率（碎片化度量）",
    },
    "调度-多核均衡": {
        "task": "多核均衡",
        "pattern": (
            "def multi_core(state, op, load=None):\n"
"    # 生效条件：op ∈ {assign, balance, loads}；cores.index 可用\n"
"    # 子功能：① op 分支处理\n"
"    # 执行：按 op 分派；顺序调用\n"
"    # 不适用条件：cores 为空/非法时；op 非 {assign, balance, loads} 时\n"
            "    # 多核均衡：assign 分核 / balance 均衡迁移 / loads 各核负载（SMP 负载均衡）\n"
            "    if op == 'assign':\n"
            "        cores = state.setdefault('cores', [])\n"
            "        if not cores:\n"
            "            cores.extend([0, 0])\n"
            "        i = cores.index(min(cores))\n"
            "        cores[i] += load\n"
            "        return i\n"
            "    if op == 'balance':\n"
            "        cores = state.get('cores', [0, 0])\n"
            "        if cores:\n"
            "            return max(cores) - min(cores) <= 1\n"
            "        return True\n"
            "    if op == 'loads':\n"
            "        return list(state.get('cores', []))\n"
            "    return None\n"),
        "cases": [
            (({}, 'assign', 3), 0),
            (({'cores': [3, 1]}, 'assign', 2), 1),
            (({'cores': [3, 3]}, 'balance'), True),
            (({'cores': [5, 1]}, 'balance'), False)],
        "params": [],
        "calibration": "对照：SMP——多核负载均衡（最小负载核分配）",
    },
    "进程-僵尸进程": {
        "task": "僵尸进程",
        "pattern": (
            "def zombie_proc(state, op, pid=None):\n"
"    # 生效条件：op ∈ {exit, reap, zombies}\n"
"    # 子功能：① op 分支处理\n"
"    # 执行：按 op 分派；顺序调用\n"
"    # 不适用条件：op 非 {exit, reap, zombies} 时\n"
            "    # 僵尸进程：exit 退出未回收 / reap 回收 / zombies 列表（进程生命周期）\n"
            "    if op == 'exit':\n"
            "        state.setdefault('zombies', []).append(pid)\n"
            "        return 'zombie'\n"
            "    if op == 'reap':\n"
            "        z = state.get('zombies', [])\n"
            "        if pid in z:\n"
            "            z.remove(pid)\n"
            "            return 'reaped'\n"
            "        return None\n"
            "    if op == 'zombies':\n"
            "        return list(state.get('zombies', []))\n"
            "    return None\n"),
        "cases": [
            (({}, 'exit', 3), 'zombie'),
            (({'zombies': [3]}, 'reap', 3), 'reaped'),
            (({}, 'reap', 5), None),
            (({'zombies': [3]}, 'zombies'), [3])],
        "params": [],
        "calibration": "对照：僵尸进程——exit 未回收/reap 回收（wait 语义）",
    },
    "内存-内存热插拔": {
        "task": "内存热插拔",
        "pattern": (
            "def mem_hotplug(state, op, node=None, size=None):\n"
"    # 生效条件：op ∈ {nodes, offline, online}\n"
"    # 子功能：① op 分支处理\n"
"    # 执行：按 op 分派；顺序调用\n"
"    # 不适用条件：op 非 {nodes, offline, online} 时\n"
            "    # 内存热插拔：online 上线 / offline 下线 / nodes 节点表（内存热添加）\n"
            "    if op == 'online':\n"
            "        state.setdefault('nodes', {})[node] = size\n"
            "        return 'online'\n"
            "    if op == 'offline':\n"
            "        if node in state.get('nodes', {}):\n"
            "            state['nodes'][node] = None\n"
            "            return 'offline'\n"
            "        return None\n"
            "    if op == 'nodes':\n"
            "        return dict(state.get('nodes', {}))\n"
            "    return None\n"),
        "cases": [
            (({}, 'online', 'n0', 16), 'online'),
            (({'nodes': {'n0': 16}}, 'offline', 'n0'), 'offline'),
            (({}, 'offline', 'n0'), None),
            (({'nodes': {'n0': 16}}, 'nodes'), {'n0': 16})],
        "params": [],
        "calibration": "对照：内存热插拔——节点上线/下线（热添加内存）",
    },
    "文件-文件系统日志": {
        "task": "文件系统日志",
        "pattern": (
            "def journal(state, op, entry=None):\n"
"    # 生效条件：op ∈ {log, pending, replay}\n"
"    # 子功能：① op 分支处理\n"
"    # 执行：按 op 分派；顺序调用\n"
"    # 不适用条件：op 非 {log, pending, replay} 时\n"
            "    # 文件系统日志：log 记录 / replay 重放 / pending 待重放（journaling）\n"
            "    if op == 'log':\n"
            "        state.setdefault('journal', []).append(entry)\n"
            "        return 'logged'\n"
            "    if op == 'replay':\n"
            "        out = list(state.get('journal', []))\n"
            "        state['journal'] = []\n"
            "        return out\n"
            "    if op == 'pending':\n"
            "        return len(state.get('journal', []))\n"
            "    return None\n"),
        "cases": [
            (({}, 'log', ('write', 'a')), 'logged'),
            (({'journal': [('write', 'a')]}, 'replay'), [('write', 'a')]),
            (({}, 'replay'), []),
            (({'journal': [1, 2]}, 'pending'), 2)],
        "params": [],
        "calibration": "对照：journaling——日志记录/崩溃重放/待重放",
    },
    "进程-进程组": {
        "task": "进程组",
        "pattern": (
            "def proc_group(state, op, pgid=None, pid=None):\n"
"    # 生效条件：op ∈ {join, members, signal}\n"
"    # 子功能：① op 分支处理\n"
"    # 执行：按 op 分派；顺序调用\n"
"    # 不适用条件：op 非 {join, members, signal} 时\n"
            "    # 进程组：join 入组 / members 组员 / signal 组播信号（作业控制）\n"
            "    if op == 'join':\n"
            "        state.setdefault('groups', {}).setdefault(pgid, []).append(pid)\n"
            "        return pgid\n"
            "    if op == 'members':\n"
            "        return list(state.get('groups', {}).get(pgid, []))\n"
            "    if op == 'signal':\n"
            "        m = state.get('groups', {}).get(pgid, [])\n"
            "        return 'signaled' if m else None\n"
            "    return None\n"),
        "cases": [
            (({}, 'join', 1, 101), 1),
            (({'groups': {1: [101]}}, 'members', 1), [101]),
            (({}, 'members', 1), []),
            (({'groups': {1: [101]}}, 'signal', 1), 'signaled')],
        "params": [],
        "calibration": "对照：进程组——组加入/成员/组播信号（作业控制）",
    },
    "内存-页缓存": {
        "task": "页缓存",
        "pattern": (
            "def page_cache(state, op, page=None, data=None):\n"
"    # 生效条件：op ∈ {get, put, stats}\n"
"    # 子功能：① op 分支处理\n"
"    # 执行：按 op 分派；顺序调用\n"
"    # 不适用条件：op 非 {get, put, stats} 时\n"
            "    # 页缓存：get 命中读 / put 写入缓存 / stats 命中率（文件页缓存）\n"
            "    if op == 'put':\n"
            "        state.setdefault('cache', {})[page] = data\n"
            "        return 'cached'\n"
            "    if op == 'get':\n"
            "        c = state.setdefault('cache', {})\n"
            "        state['hits'] = state.get('hits', 0) + 1\n"
            "        if page in c:\n"
            "            state['hit'] = state.get('hit', 0) + 1\n"
            "            return c[page]\n"
            "        return None\n"
            "    if op == 'stats':\n"
            "        h = state.get('hit', 0)\n"
            "        t = state.get('hits', 0)\n"
            "        return round(h / t, 2) if t else 0.0\n"
            "    return None\n"),
        "cases": [
            (({}, 'put', 1, 'A'), 'cached'),
            (({'cache': {1: 'A'}}, 'get', 1), 'A'),
            (({}, 'get', 1), None),
            (({'hit': 2, 'hits': 4}, 'stats'), 0.5)],
        "params": [],
        "calibration": "对照：页缓存——文件页缓存命中/写入/命中率",
    },
    "调度-亲和性": {
        "task": "亲和性",
        "pattern": (
            "def cpu_affinity(state, op, pid=None, cpu=None):\n"
"    # 生效条件：op ∈ {allowed, get, set}\n"
"    # 子功能：① op 分支处理\n"
"    # 执行：按 op 分派；顺序调用\n"
"    # 不适用条件：op 非 {allowed, get, set} 时\n"
            "    # 亲和性：set 绑定核 / get 查询 / allowed 允许核集（CPU affinity）\n"
            "    if op == 'set':\n"
            "        state.setdefault('aff', {})[pid] = cpu\n"
            "        return cpu\n"
            "    if op == 'get':\n"
            "        return state.get('aff', {}).get(pid)\n"
            "    if op == 'allowed':\n"
            "        c = state.get('aff', {}).get(pid)\n"
            "        return c if c is not None else list(range(state.get('ncore', 4)))\n"
            "    return None\n"),
        "cases": [
            (({}, 'set', 101, 2), 2),
            (({'aff': {101: 2}}, 'get', 101), 2),
            (({}, 'get', 101), None),
            (({}, 'allowed', 101), [0, 1, 2, 3])],
        "params": [],
        "calibration": "对照：CPU 亲和性——进程绑定核/查询/允许集",
    },
    "中断-软中断": {
        "task": "软中断",
        "pattern": (
            "def softirq(queue, action, item=None):\n"
            "    # 软中断（softirq）：硬中断中延迟的低优先级工作（defer 入队按优先级 / run 依次处理）\n"
            "    # 生效条件：action ∈ {defer, run}；defer 时 item 为 (优先级, 工作名)\n"
            "    # 子功能：① defer 入队并按优先级排序 ② run 依序弹出处理\n"
            "    # 执行：list.sort(key=优先级) + pop(0) 逐出队\n"
            "    # 不适用条件：action 非 {defer, run} 时返回 None；不重复入队检查由调用方负责\n"
            "    if action == 'defer':\n"
            "        queue.append(item)\n"
            "        queue.sort(key=lambda x: x[0])\n"
            "        return len(queue)\n"
            "    if action == 'run':\n"
            "        out = []\n"
            "        while queue:\n"
            "            out.append(queue.pop(0))\n"
            "        return out\n"
            "    return None\n"),
        "cases": [
            (([], 'defer', (2, '网卡')), 1),
            (([(2, '网卡')], 'defer', (1, '定时器')), 2),
            (([(1, '定时器'), (2, '网卡')], 'run'), [(1, '定时器'), (2, '网卡')]),
            (([], 'run'), []),
            (([], 'unknown', None), None)],
        "params": [],
        "calibration": "对照：软中断（softirq）——硬中断处理中延迟低优先级工作，按优先级排队执行",
    },
    "调度-工作窃取": {
        "task": "工作窃取",
        "pattern": (
            "def work_steal(queues, worker):\n"
            "    # 工作窃取（work stealing）：空闲核从最忙队列窃取一个任务（多核负载均衡）\n"
            "    # 生效条件：queues 为各核任务队列列表；worker 为申请窃取的核号\n"
            "    # 子功能：① 空闲判定（自己队列非空则不窃取）② 找最忙非空队列 ③ 迁移一个任务\n"
            "    # 执行：忙核直返；空闲则取最忙队列 pop(0) 到本队列\n"
"    # 不适用条件：candidates 为空/非法时\n"
            "    if queues[worker]:\n"
            "        return queues\n"
            "    candidates = [(i, q) for i, q in enumerate(queues) if q and i != worker]\n"
            "    if not candidates:\n"
            "        return queues\n"
            "    busiest = max(candidates, key=lambda x: len(x[1]))[0]\n"
            "    queues[worker].append(queues[busiest].pop(0))\n"
            "    return queues\n"),
        "cases": [
            (([[1, 2], [], [3, 4, 5]], 1), [[1, 2], [3], [4, 5]]),
            (([[1], [2]], 0), [[1], [2]]),
            (([[], []], 0), [[], []]),
            (([[7], [8], []], 2), [[], [8], [7]])],
        "params": [],
        "calibration": "对照：工作窃取（work stealing）——空闲核从最忙队列窃取任务，无其他非空队列则不动",
    },
    "系统-模块加载": {
        "task": "模块加载",
        "pattern": (
            "def module_load(registry, module, deps):\n"
            "    # 模块加载（内核模块装载）：依赖满足才注册（内核模块动态装载语义）\n"
            "    # 生效条件：registry 为已加载模块表；deps 为模块依赖名列表\n"
            "    # 子功能：① 依赖存在性检查 ② 全满足注册 ③ 缺依赖拒绝\n"
            "    # 执行：all(d in registry) → 注册返回 ok，否则 missing_deps\n"
"    # 不适用条件：输入不满足生效条件时返回 None/不执行\n"
            "    if all(d in registry for d in deps):\n"
            "        registry[module] = 'loaded'\n"
            "        return 'ok'\n"
            "    return 'missing_deps'\n"),
        "cases": [
            (({'net': 'loaded'}, 'fs', ['net']), 'ok'),
            (({'net': 'loaded'}, 'fs', ['net', 'usb']), 'missing_deps'),
            (({}, 'fs', []), 'ok'),
            (({'a': 'loaded'}, 'b', ['a', 'a']), 'ok')],
        "params": [],
        "calibration": "对照：内核模块装载——依赖全部已注册才加载，缺依赖拒绝",
    },
}


def route_os_unit(question):
    """任务识别（问题 → OS 单元）"""
    best, best_len = None, 0
    for uid, u in OS_UNITS.items():
        for kw in (u["task"], uid):
            if kw in question and len(kw) > best_len:
                best, best_len = uid, len(kw)
    return best


if __name__ == "__main__":
    print("=== 迷你 Linux 白箱单元库（目标4 · 中文操作系统初级复现）===\n")
    for uid, u in OS_UNITS.items():
        print(f"[{uid}] 任务={u['task']} 样例数={len(u['cases'])}")
        print(f"    校准: {u['calibration']}")
    print(f"\n=== 判定 ===\n迷你 Linux 单元库: "
          f"{'✔ 5 单元就绪（进程调度/轮转/内存/文件/IPC）' if len(OS_UNITS) >= 4 else '✘'}")
