# -*- coding: utf-8 -*-
"""第七阶段: 7 终极目标 × 7 初级复现 生态盘点 + 跨域组装验证"""
import sys
import os, io, re
sys.stdout.reconfigure(encoding='utf-8')

TOOLS = os.path.dirname(os.path.abspath(__file__))
MODS = [
    ('compiler', 'compiler_code_units.py'),
    ('pylang', 'python_code_units.py'),
    ('graph', 'graph_db_units.py'),
    ('os', 'os_units.py'),
    ('browser', 'browser_units.py'),
    ('net', 'net_units.py'),
]
TARGET = {
    'compiler': '2 中文编译器', 'pylang': '1 中文编程语言',
    'graph': '6 条件图数据库', 'os': '4 中文操作系统',
    'browser': '5 中文浏览器', 'net': '7 蜂群连接网络',
}

print('=' * 60)
print('第七阶段 · 7 终极目标 × 7 初级复现 生态盘点')
print('=' * 60)
total = 0
for name, fn in MODS:
    src = io.open(f'{TOOLS}\\{fn}', encoding='utf-8').read()
    # 精确匹配单元 dict 键: 行首 4 空格 + "域-名(可含空格)": {
    uids = re.findall(r'^    "([^"]+)":\s*\{', src, re.M)
    total += len(uids)
    print(f'  {TARGET[name]:14s} {name:9s} {len(uids):3d} 单元')
print('-' * 60)
print(f'  六域合计: {total} 单元')

# 核对：正则盘点 vs code_compose 正式注册表（防正则漏匹配——含空格 uid 如
# "异步-async await" / "并行-Service Worker" 曾被 \S+ 漏掉）
sys.path.insert(0, TOOLS)
from code_compose import DOMAIN_UNITS
reg_total = sum(len(DOMAIN_UNITS[n]) for n, _ in MODS)
if total == reg_total:
    print(f'  注册表核对: 正则 {total} == DOMAIN_UNITS {reg_total} ✔')
else:
    print(f'  注册表核对: 正则 {total} != DOMAIN_UNITS {reg_total} ✘（正则漏匹配）')

# ============ 跨域组装验证 ============
print()
print('=' * 60)
print('跨域组装: 条件路由图(graph) → 图查询 → 网络可靠传输(net)')
print('           → 操作系统内存(os) → 浏览器绘制(browser)')
print('=' * 60)
from code_compose import domain_route

def get(uid, q):
    r = domain_route(q)
    assert r.get('ok') and r.get('code'), f'{uid} 生成失败: {r}'
    ns = {}
    exec(r['code'], ns)
    return ns

# ① graph: 建图（条件链）
ns_g = get('图存储-节点边', '写一个图存储单元（节点和边）')
Graph = ns_g['Graph']
g = Graph()
g.add_edge('气压低', '沸点降')
g.add_edge('沸点降', '煮不熟')
g.add_edge('气压低', '缺氧')
g.add_edge('缺氧', '煮不熟')

# ② graph: 最短路径 + 条件链查询
ns_sp = get('图遍历-最短路径', '写一个图最短路径单元（BFS 最少跳数）')
sp = ns_sp['shortest_path'](g, '气压低', '煮不熟')
print(f'  ① 条件链最短路径: {" → ".join(sp)}')

# ③ net: 滑动窗口可靠传输（把条件链当消息帧传）
ns_sw = get('网络-滑动窗口', '写一个 TCP 滑动窗口单元（ACK 窗口前移）')
ns_ca = get('网络-累积确认', '写一个 TCP 累积确认单元（连续序号推进）')
recv, acks = set(), []
for i, node in enumerate(sp, 1):
    ack = ns_ca['cum_ack'](recv, i)
    acks.append(ack)
win = ns_sw['sliding_window'](0, 0, 3, max(acks))
print(f'  ② 条件链作为消息帧传输: 累积确认 ack={max(acks)} 窗口={win["window"]}')

# ④ os: 为每个节点分配内存页（页表映射）
ns_pt = get('内存-页表映射', '写一个页表映射单元（虚拟页到物理帧）')
ns_pf = get('内存-缺页处理', '写一个缺页处理单元（空闲帧加载）')
pt, frames = {}, list(range(10, 10 + len(sp)))
for vpn, node in enumerate(sp):
    r = ns_pf['page_fault_handler'](pt, vpn, frames, lambda v, f: None)
print(f'  ③ 条件链节点驻留内存: {len(pt)} 页 已映射 {sorted(pt)}')

# ⑤ browser: 把条件链绘制到画布（可视化）
ns_pn = get('渲染-绘制', '写一个绘制单元（布局到画布）')
layout = [(i, 0, i, 1, 1) for i in range(len(sp))]
canvas = ns_pn['paint'](layout, len(sp), len(sp))
print(f'  ④ 条件链可视化画布: {canvas}')

# ⑥ compiler: 用中文循环语义验证链遍历次数
ns_cl = get('编译-循环', '写一个循环编译单元（当条件执行 while）')
loop_code = ns_cl['compile_loop'](
    [('LOAD', 'i'), ('PUSH', len(sp)), ('CMP_LT', None)],
    [('LOAD', 's'), ('LOAD', 'i'), ('ADD', None), ('STORE', 's'),
     ('LOAD', 'i'), ('PUSH', 1), ('ADD', None), ('STORE', 'i')])
ns_vm = get('VM-循环执行', '写一个 VM 循环执行单元（while 循环运行）')
res = ns_vm['vm_run_loop'](loop_code, {'i': 0, 's': 0})
print(f'  ⑤ 中文循环语义: 链节点数 0..{len(sp)-1} 累积和 s={res["symbols"]["s"]}')

# ⑦ 真实中文编译器输出贯穿全链：gcd(48,36)=12 → 网络传输 → 内存 → 图存储 → 可视化
sys.path.insert(0, __import__('os').environ.get('AEIS_PROTOCOL_COMPILER') or __import__('os').path.join(__import__('os').path.dirname(__import__('os').path.dirname(__import__('os').path.abspath(__file__))), __import__('os').pardir, 'protocol-compiler'))
from core.compiler import compile_source as pc_compile
from core.condition_vm import ConditionVM
src_gcd = '''
定义 最大公约数（甲，乙）：若 甲 等于 乙，则 返回 甲，否则 若 甲 大于 乙，则 返回 最大公约数（甲 减 乙，乙），否则 返回 最大公约数（甲，乙 减 甲）；
结果 = 最大公约数（48，36）；
止。
'''
code_gcd, r_gcd = pc_compile(src_gcd, strict=False)
st_gcd = ConditionVM().run(code_gcd)
gcd_val = st_gcd['symbols'].get('结果', 0)
print(f'  ⑥ 中文编译器计算 gcd(48,36)={gcd_val}')

# ⑦a 结果作为消息帧经滑动窗口传输
recv2, acks2 = set(), []
for i in range(1, int(gcd_val) + 1):
    ack = ns_ca['cum_ack'](recv2, i)
    acks2.append(ack)
win2 = ns_sw['sliding_window'](0, 0, 4, max(acks2))
print(f'  ⑦ 结果经滑动窗口传输: ack={max(acks2)} 窗口={win2["window"]}')

# ⑦b 结果驻留内存页
pt2, frames2 = {}, list(range(20, 20 + int(gcd_val)))
for vpn in range(int(gcd_val)):
    ns_pf['page_fault_handler'](pt2, vpn, frames2, lambda v, f: None)
print(f'  ⑧ 结果驻留内存: {len(pt2)} 页')

# ⑦c 结果存入条件路由图（12 个节点链）
g2 = Graph()
for i in range(1, int(gcd_val)):
    g2.add_edge(f'步{i}', f'步{i+1}')
sp2 = ns_sp['shortest_path'](g2, '步1', f'步{int(gcd_val)}')
print(f'  ⑨ 结果存入条件路由图: 12 步链 {"→".join(sp2[:3])}…')

# ⑦d 结果可视化
layout2 = [(i, 0, i, 1, 1) for i in range(min(len(sp2), 4))]
canvas2 = ns_pn['paint'](layout2, 4, 4)
print(f'  ⑩ 结果可视化画布: {canvas2}')

ok2 = (gcd_val == 12.0 and win2['window'] == [12, 13, 14, 15]
       and len(pt2) == 12 and len(sp2) == 12)

ok = (sp == ['气压低', '沸点降', '煮不熟'] and win['window'] == [3, 4, 5]
      and len(pt) == len(sp) and res['symbols']['s'] == 3
      and canvas == ['#..', '#..', '#..'] and ok2)
print()
print('=' * 60)
print(f'跨域组装判定: {"✔ 六域单元互相配合形成完整演示生态（含真实中文编译器输出贯穿全链）" if ok else "✘ 存在偏差"}')
print('=' * 60)
sys.exit(0 if ok else 1)
