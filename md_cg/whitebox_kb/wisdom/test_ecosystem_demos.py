# -*- coding: utf-8 -*-
"""test_ecosystem_demos.py · 第七阶段：7 终极目标逐项目运行演示
每个终极目标 = 白箱单元组装成可运行 demo（域内全链路），验证生态完整。
"""
import sys
import os
sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from code_compose import domain_route

pass_n = fail_n = 0
def check(name, ok, detail=''):
    """断言登记：通过/失败计数并打印结果行。"""
    global pass_n, fail_n
    if ok: pass_n += 1
    else: fail_n += 1
    print(f'[{"✓" if ok else "✘"}] {name}{" — " + detail if detail else ""}')

def get(q, fn_name):
    """域管线生成单元 → 提取函数"""
    r = domain_route(q)
    assert r.get('ok') and r.get('code'), f'{q} 生成失败: {r.get("reason")}'
    ns = {}
    exec(r['code'], ns)
    return ns[fn_name]

# ============ 目标1 中文编程语言（pylang：表达式→闭包→异常） ============
try:
    prec = get('写一个优先级计算单元（表达式求值）', 'precedence')
    r1 = prec("2+3*4")
    check('目标1 中文编程语言: 表达式优先级 2+3*4=14', r1 == 14, f'={r1}')
except Exception as e:
    check('目标1 中文编程语言: 表达式优先级 2+3*4=14', False, str(e)[:50])

# ============ 目标2 中文编译器（compiler：循环编译→VM 执行） ============
try:
    compile_loop = get('写一个循环编译单元（当条件执行 while）', 'compile_loop')
    vm_run_loop = get('写一个 VM 循环执行单元（while 循环运行）', 'vm_run_loop')
    code = compile_loop([('LOAD', 'i'), ('PUSH', 4), ('CMP_LT', None)],
                        [('LOAD', 's'), ('LOAD', 'i'), ('ADD', None), ('STORE', 's'),
                         ('LOAD', 'i'), ('PUSH', 1), ('ADD', None), ('STORE', 'i')])
    res = vm_run_loop(code, {'i': 0, 's': 0})
    check('目标2 中文编译器: 当循环 0+1+2+3=6', res['symbols']['s'] == 6,
          f's={res["symbols"]["s"]}')
except Exception as e:
    check('目标2 中文编译器: 当循环 0+1+2+3=6', False, str(e)[:50])

# 目标2b 中文编译器：递归函数（真实 protocol-compiler 编译执行）
try:
    sys.path.insert(0, __import__('os').environ.get('AEIS_PROTOCOL_COMPILER') or __import__('os').path.join(__import__('os').path.dirname(__import__('os').path.dirname(__import__('os').path.abspath(__file__))), __import__('os').pardir, 'protocol-compiler'))
    from core.compiler import compile_source
    from core.condition_vm import ConditionVM
    src_fac = '''
定义 阶乘（n）：若 n 小于 2，则 返回 1，否则 返回 n 乘 阶乘（n 减 1）；
结果 = 阶乘（5）；
止。
'''
    code_fac, r_fac = compile_source(src_fac, strict=False)
    if r_fac["ok"]:
        st_fac = ConditionVM().run(code_fac)
        fac = st_fac["symbols"].get("结果")
        check('目标2b 中文递归函数: 阶乘(5)=120（真实编译器）',
              fac == 120.0, f'阶乘(5)={fac}')
    else:
        check('目标2b 中文递归函数: 阶乘(5)=120（真实编译器）', False,
              str(r_fac["errors"])[:40])
except Exception as e:
    check('目标2b 中文递归函数: 阶乘(5)=120（真实编译器）', False, str(e)[:50])

# 目标2c 中文编译器：双递归函数（斐波那契——CALL 帧深度嵌套）
try:
    src_fib = '''
定义 斐波那契（n）：若 n 小于 2，则 返回 n，否则 返回 斐波那契（n 减 1）加 斐波那契（n 减 2）；
结果 = 斐波那契（6）；
止。
'''
    code_fib, r_fib = compile_source(src_fib, strict=False)
    if r_fib["ok"]:
        st_fib = ConditionVM().run(code_fib)
        fib = st_fib["symbols"].get("结果")
        check('目标2c 中文双递归: 斐波那契(6)=8（真实编译器）',
              fib == 8.0, f'斐波那契(6)={fib}')
    else:
        check('目标2c 中文双递归: 斐波那契(6)=8（真实编译器）', False,
              str(r_fib["errors"])[:40])
except Exception as e:
    check('目标2c 中文双递归: 斐波那契(6)=8（真实编译器）', False, str(e)[:50])

# 目标2d 中文编译器：多参数递归（欧几里得 gcd——嵌套若则 × 双参数 × 递归）
try:
    src_gcd = '''
定义 最大公约数（甲，乙）：若 甲 等于 乙，则 返回 甲，否则 若 甲 大于 乙，则 返回 最大公约数（甲 减 乙，乙），否则 返回 最大公约数（甲，乙 减 甲）；
结果 = 最大公约数（48，36）；
止。
'''
    code_gcd, r_gcd = compile_source(src_gcd, strict=False)
    if r_gcd["ok"]:
        st_gcd = ConditionVM().run(code_gcd)
        gcd = st_gcd["symbols"].get("结果")
        check('目标2d 中文多参数递归: gcd(48,36)=12（真实编译器）',
              gcd == 12.0, f'gcd(48,36)={gcd}')
    else:
        check('目标2d 中文多参数递归: gcd(48,36)=12（真实编译器）', False,
              str(r_gcd["errors"])[:40])
except Exception as e:
    check('目标2d 中文多参数递归: gcd(48,36)=12（真实编译器）', False, str(e)[:50])

# ============ 目标3 中文分析器（compiler：类型推断） ============
try:
    infer = get('写一个类型推断单元（编译期类型流）', 'infer_types')
    r3 = infer([("assign", "甲", 3), ("assign", "乙", "文本"),
                ("assign", "丙", True), ("COND", "条件空间为伴侣 则 德 0.5", [], [])])
    types3, spaces3 = r3['types'], r3['spaces']
    ok3 = (types3.get('甲') == '数值' and types3.get('乙') == '文本'
           and types3.get('丙') == '布尔' and spaces3.get('伴侣') == '已声明')
    check('目标3 中文分析器: 类型推断（数值/文本/布尔）+条件空间登记', ok3,
          f'types={types3} spaces={spaces3}')
except Exception as e:
    check('目标3 中文分析器: 类型推断（数值/文本/布尔）+条件空间登记', False, str(e)[:50])

# ============ 目标4 中文操作系统（os：调度→内存→文件） ============
try:
    fcfs = get('写一个进程调度单元（FCFS 完成时间）', 'fcfs_schedule')
    page_alloc = get('写一个内存分页分配单元（请求分配）', 'page_alloc')
    resolve = get('写一个文件路径解析单元（路径规范化）', 'resolve_path')
    done = fcfs([(0, 3), (2, 2)])
    alloc = page_alloc(10, [3, 5, 4])
    path = resolve('/a/b', '/c')
    check('目标4 中文操作系统: 调度[3,5]+内存[✓✓✗]+路径/a/b',
          done == [3, 5] and alloc == [True, True, False] and path == '/a/b',
          f'sched={done} mem={alloc} path={path}')
except Exception as e:
    check('目标4 中文操作系统: 调度[3,5]+内存[✓✓✗]+路径/a/b', False, str(e)[:50])

# ============ 目标5 中文浏览器（browser：URL→请求→DOM→CSS→布局→绘制） ============
try:
    parse_url = get('写一个 URL 解析单元（协议主机端口路径）', 'parse_url')
    build_get = get('写一个 HTTP 请求构建单元（GET 请求行和头）', 'build_get_request')
    box = get('写一个盒模型单元（padding/border 总尺寸）', 'box_model')
    paint = get('写一个绘制单元（布局到画布）', 'paint')
    u = parse_url('https://example.com:8080/page')
    req = build_get(u['path'], u['host'])
    w = box(100, 10, 2, 5)
    cv = paint([('a', 0, 0, 2, 1)], 1, 3)
    ok5 = (u['scheme'] == 'https' and u['port'] == 8080
           and 'GET /page HTTP/1.1' in req and 'Host: example.com' in req
           and w == 124 and cv == ['##.'])
    check('目标5 中文浏览器: URL→请求→盒模型→绘制 全链路', ok5,
          f'url={u["scheme"]} w={w} cv={cv}')
except Exception as e:
    check('目标5 中文浏览器: URL→请求→盒模型→绘制 全链路', False, str(e)[:50])

# ============ 目标6 条件图数据库（graph：建图→遍历→查询） ============
try:
    graph_ops = get('写一个图存储单元（节点和边）', 'graph_ops')
    reachable = get('写一个图遍历单元（BFS 可达节点）', 'reachable')
    shortest = get('写一个图最短路径单元（BFS 最少跳数）', 'shortest_path')
    # graph_ops 返回 (nodes, neighbors)；需注入 Graph 类——用最短路径单元自带
    Graph = None
    r_g = domain_route('写一个图存储单元（节点和边）')
    ns_g = {}
    exec(r_g['code'], ns_g)
    Graph = ns_g['Graph']
    g = Graph()
    g.add_edge('气压低', '沸点降')
    g.add_edge('沸点降', '煮不熟')
    sp = shortest(g, '气压低', '煮不熟')
    check('目标6 条件图数据库: 建图→最短路径', sp == ['气压低', '沸点降', '煮不熟'],
          f'path={"→".join(sp)}')
except Exception as e:
    check('目标6 条件图数据库: 建图→最短路径', False, str(e)[:50])

# ============ 目标7 蜂群连接网络（net：握手→分帧→会话→可靠传输） ============
try:
    handshake = get('写一个 TCP 握手单元（三次握手状态）', 'tcp_handshake')
    frame_decode = get('写一个蜂群消息分帧单元（字节流分隔）', 'frame_decode')
    session = get('写一个蜂群会话状态单元（连接建立关闭）', 'session_step')
    sw = get('写一个 TCP 滑动窗口单元（ACK 窗口前移）', 'sliding_window')
    hs = handshake(['SYN', 'SYN-ACK'])
    frames, rest = frame_decode(b'SYN\r\nACK\r\nFIN\r\n')
    state = 'LISTEN'
    for f in frames:
        state = session({'state': state}, f.decode())
    win = sw(0, 0, 3, 3)
    ok7 = (hs == 'ESTABLISHED' and state == 'CLOSED'
           and win['window'] == [3, 4, 5])
    check('目标7 蜂群连接网络: 握手→分帧→会话→窗口', ok7,
          f'hs={hs} state={state} win={win["window"]}')
except Exception as e:
    check('目标7 蜂群连接网络: 握手→分帧→会话→窗口', False, str(e)[:50])

print(f'\n=== 第七阶段 7 终极目标逐项目演示: {pass_n}/{pass_n + fail_n} 通过 ===')
sys.exit(0 if fail_n == 0 else 1)
