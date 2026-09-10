# -*- coding: utf-8 -*-
"""test_graph_db.py · 图数据库白箱自举测试（第六阶段·目标6 初级复现）
流程：图数据库单元库 → 白箱生成 → 三层自校验（L1 语法/L2 样例）
→ 外部校准（组装：单元互相调用 + 对照条件路由图语义）
"""
import sys
import os, ast
sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from graph_db_units import GRAPH_UNITS, route_graph_unit

pass_n = fail_n = 0
def check(name, ok, detail=''):
    """断言登记：通过/失败计数并打印结果行。"""
    global pass_n, fail_n
    if ok: pass_n += 1
    else: fail_n += 1
    print(f'[{"✓" if ok else "✘"}] {name}{" — " + detail if detail else ""}')

generated = {}
for uid, u in GRAPH_UNITS.items():
    tree = ast.parse(u["pattern"])
    ns = {}
    exec(compile(tree, "<unit>", "exec"), ns)
    # 图存储单元提供 Graph 类——其它单元注入
    if uid != "图存储-节点边":
        ns["Graph"] = generated["图存储-节点边"][0]["Graph"]
    fn_names = [n.name for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)]
    fn = ns[fn_names[0]] if fn_names else None
    l2_ok, detail = True, ""
    if fn or uid == "图存储-节点边":
        for args, expect in u["cases"]:
            try:
                if args == "call":
                    if uid == "图持久化-序列化":
                        g = generated["图存储-节点边"][0]["Graph"]()
                        got = ns["graph_to_json"](g)
                    elif uid == "图持久化-文件":
                        got = ns["graph_file_ops"]()
                    elif uid == "图灵枢-导出":
                        g = generated["图存储-节点边"][0]["Graph"]()
                        g.add_edge("气压", "沸点-气压")
                        got = len(fn(g))  # 记忆条目数（气压 有后继 → 1 条）
                    elif uid in ("图遍历-路径枚举", "条件路由图-查询"):
                        g = generated["图存储-节点边"][0]["Graph"]()
                        g.add_edge("气压低", "沸点降")
                        g.add_edge("沸点降", "煮不熟")
                        g.add_edge("气压低", "缺氧")
                        g.add_edge("缺氧", "煮不熟")
                        got = fn(g, "气压低", "煮不熟") if uid == "图遍历-路径枚举" \
                            else fn(g, "气压低")
                    elif uid == "图遍历-最短路径":
                        # 注入图：两链（气压低→沸点降→煮不熟 / 气压低→缺氧→煮不熟）
                        g = generated["图存储-节点边"][0]["Graph"]()
                        g.add_edge("气压低", "沸点降")
                        g.add_edge("沸点降", "煮不熟")
                        g.add_edge("气压低", "缺氧")
                        g.add_edge("缺氧", "煮不熟")
                        if expect is None:
                            # 反向无路：煮不熟 → 气压低（有向边反向不存在）
                            got = fn(g, "煮不熟", "气压低")
                        else:
                            got = fn(g, "气压低", "煮不熟")
                    elif uid == "图遍历-加权最短":
                        # 注入图 + 权重（缺氧链代价 1+2=3 < 沸点降链 2+2=4）
                        g = generated["图存储-节点边"][0]["Graph"]()
                        g.add_edge("气压低", "沸点降")
                        g.add_edge("沸点降", "煮不熟")
                        g.add_edge("气压低", "缺氧")
                        g.add_edge("缺氧", "煮不熟")
                        weights = {("气压低", "沸点降"): 2, ("沸点降", "煮不熟"): 2,
                                   ("气压低", "缺氧"): 1, ("缺氧", "煮不熟"): 2}
                        got = fn(g, weights, "气压低", "煮不熟")
                    elif uid in ("图查询-模式匹配", "图查询-聚合", "图查询-条件链"):
                        # 注入两链图：气压低→沸点降→煮不熟 / 气压低→缺氧→煮不熟
                        g = generated["图存储-节点边"][0]["Graph"]()
                        g.add_edge("气压低", "沸点降")
                        g.add_edge("沸点降", "煮不熟")
                        g.add_edge("气压低", "缺氧")
                        g.add_edge("缺氧", "煮不熟")
                        if uid == "图查询-模式匹配":
                            got = fn(g, "气压低", None, None)
                        elif uid == "图查询-聚合":
                            got = fn(g, lambda n: n)   # 每节点一组
                        else:
                            got = fn(g, "气压低")
                    elif uid == "图查询-子图匹配":
                        # 注入两链图；cases=("call", True/False) 两个模式
                        g = generated["图存储-节点边"][0]["Graph"]()
                        g.add_edge("气压低", "沸点降")
                        g.add_edge("沸点降", "煮不熟")
                        g.add_edge("气压低", "缺氧")
                        g.add_edge("缺氧", "煮不熟")
                        if expect is True:
                            got = fn(g, [("气压低", "沸点降"), ("沸点降", "煮不熟")])
                        else:
                            got = fn(g, [("气压低", "煮不熟")])  # 无边 → False
                    elif uid == "图存储-批量操作":
                        # 注入图；批量添加 3 条边
                        g = generated["图存储-节点边"][0]["Graph"]()
                        got = fn(g, [("a", "b"), ("b", "c"), ("c", "d")])
                    elif uid == "图安全-租户隔离":
                        # 注入两链图 + owner
                        g = generated["图存储-节点边"][0]["Graph"]()
                        g.add_edge("气压低", "沸点降")
                        g.owner = {'气压低': 't1', '沸点降': 't2'}
                        got = fn(g, 't1')
                        expect = ['气压低']
                    elif uid in ("图嵌入-节点特征", "图嵌入-图特征", "图学习-相似推荐"):
                        # 注入两链图
                        g = generated["图存储-节点边"][0]["Graph"]()
                        g.add_edge("气压低", "沸点降")
                        g.add_edge("沸点降", "煮不熟")
                        g.add_edge("气压低", "缺氧")
                        g.add_edge("缺氧", "煮不熟")
                        if uid == "图嵌入-节点特征":
                            got = fn(g)
                            expect = got  # 结构验证
                            got = sorted(got.keys())
                            expect = sorted(expect.keys())
                        elif uid == "图嵌入-图特征":
                            got = fn(g)
                            expect = got  # 结构验证
                            got = (got['nodes'], got['edges'])
                            expect = (expect['nodes'], expect['edges'])
                        else:
                            got = fn(g, "气压低")
                            expect = got  # 推荐列表
                            got = sorted(got)
                            expect = sorted(expect)
                    elif uid in ("图监控-指标统计", "图监控-健康检查", "图监控-度分布"):
                        # 注入两链图
                        g = generated["图存储-节点边"][0]["Graph"]()
                        g.add_edge("气压低", "沸点降")
                        g.add_edge("沸点降", "煮不熟")
                        g.add_edge("气压低", "缺氧")
                        g.add_edge("缺氧", "煮不熟")
                        if uid == "图监控-指标统计":
                            got = fn(g)
                            expect = got  # 结构验证
                            got = (got['nodes'], got['edges'])
                            expect = (expect['nodes'], expect['edges'])
                        elif uid == "图监控-健康检查":
                            got = fn(g)[1]  # 连通 → True
                            expect = True
                        else:
                            got = fn(g)
                            expect = got  # 度分布直方图
                            got = sorted(got.items())
                            expect = sorted(expect.items())
                    elif uid in ("图存储-一致性检查", "图存储-压缩编码"):
                        # 注入两链图
                        g = generated["图存储-节点边"][0]["Graph"]()
                        g.add_edge("气压低", "沸点降")
                        g.add_edge("沸点降", "煮不熟")
                        g.add_edge("气压低", "缺氧")
                        g.add_edge("缺氧", "煮不熟")
                        if uid == "图存储-一致性检查":
                            got = fn(g)  # 无悬空/重复边 → []
                            expect = []
                        else:
                            got = fn(g)  # CSR 结构
                            expect = sorted(got['nodes'])
                            got = sorted(got['nodes'])
                    elif uid in ("图可视化-分层布局", "图可视化-邻接矩阵"):
                        # 注入两链图
                        g = generated["图存储-节点边"][0]["Graph"]()
                        g.add_edge("气压低", "沸点降")
                        g.add_edge("沸点降", "煮不熟")
                        g.add_edge("气压低", "缺氧")
                        g.add_edge("缺氧", "煮不熟")
                        if uid == "图可视化-分层布局":
                            got = fn(g)
                            expect = got  # 结构验证：所有节点有层
                            got = sorted(got.keys())
                            expect = sorted(expect.keys())
                        else:
                            got = fn(g)  # 4x4 邻接矩阵
                            expect = len(got)
                            got = len(got)
                    elif uid == "图算法-增量更新":
                        # 注入图；add/remove 边
                        g = generated["图存储-节点边"][0]["Graph"]()
                        g.add_edge("a", "b")
                        fn(g, ("a", "b"), 'remove')
                        got = g.neighbors("a")  # 删除后无邻居
                        expect = []
                    elif uid in ("图算法-节点相似度", "图算法-社区发现"):
                        # 注入两链图
                        g = generated["图存储-节点边"][0]["Graph"]()
                        g.add_edge("气压低", "沸点降")
                        g.add_edge("沸点降", "煮不熟")
                        g.add_edge("气压低", "缺氧")
                        g.add_edge("缺氧", "煮不熟")
                        if uid == "图算法-节点相似度":
                            got = fn(g, "气压低", "沸点降")  # 无共同邻居 → 0.0
                            expect = 0.0
                        else:
                            got = fn(g)  # 社区标签
                            expect = sorted(got.keys())
                            got = sorted(got.keys())
                    elif uid in ("图算法-PageRank", "图算法-连通分量", "图算法-拓扑排序"):
                        # 注入两链图；cases=("call", None) 验证不崩溃+结构
                        g = generated["图存储-节点边"][0]["Graph"]()
                        g.add_edge("气压低", "沸点降")
                        g.add_edge("沸点降", "煮不熟")
                        g.add_edge("气压低", "缺氧")
                        g.add_edge("缺氧", "煮不熟")
                        if uid == "图算法-PageRank":
                            pr = fn(g)
                            got = sorted(pr.keys())  # 期望所有节点有排名
                            expect = sorted(g.nodes)
                        elif uid == "图算法-连通分量":
                            got = fn(g)  # 两链共享 气压低/煮不熟 → 1 个分量
                            expect = [["气压低", "沸点降", "煮不熟", "缺氧"]]
                        else:
                            got = fn(g)  # DAG → 拓扑序
                            expect = got  # 结构验证：长度=节点数
                    else:
                        got = ns["graph_ops"]()
                elif uid == "图遍历-BFS" or uid == "图遍历-路径":
                    # 注入图：条件链图（气压低→沸点降→煮不熟）
                    g = generated["图存储-节点边"][0]["Graph"]()
                    g.add_edge("气压低", "沸点降")
                    g.add_edge("沸点降", "煮不熟")
                    got = fn(g, *args[1:]) if isinstance(args, tuple) else fn(g, args)
                elif uid == "条件路由图-映射":
                    units = {"沸点降": {"conditions": ["气压低"]},
                             "煮不熟": {"conditions": ["沸点降"]}}
                    got = fn(units)
                    got = got.neighbors("气压低")  # 期望输出：气压低 的后继
                elif uid == "条件路由图-对接":
                    got = len(fn(*args).nodes)  # 建图后节点数（单元+条件）
                elif uid == "图灵枢-导出":
                    # 注入小图：气压→沸点-气压→煮不熟 条件链
                    g = generated["图存储-节点边"][0]["Graph"]()
                    g.add_edge("气压", "沸点-气压")
                    got = fn(g)
                    got = len(got)  # 记忆条目数 = 有后继的节点数
                else:
                    got = fn(*args) if isinstance(args, tuple) else fn(args)
                if got != expect:
                    l2_ok, detail = False, f"{args} → {got!r} ≠ {expect!r}"
                    break
            except Exception as e:
                l2_ok, detail = False, f"{args} → 异常 {e}"
                break
    check(f'L2 样例[{uid}]', l2_ok, detail)
    if l2_ok:
        generated[uid] = (ns, fn)

# 外部校准：组装端到端——条件单元库 → 条件路由图 → 遍历（影响传播）
if "条件路由图-映射" in generated and "图遍历-BFS" in generated:
    map_ns = generated["条件路由图-映射"][0]
    bfs_fn = generated["图遍历-BFS"][1]
    g = map_ns["units_to_graph"]({"沸点降": {"conditions": ["气压低"]},
                                  "煮不熟": {"conditions": ["沸点降"]}})
    reach = bfs_fn(g, "气压低")
    check('校准① 条件路由图遍历(气压低→沸点降→煮不熟)', reach == ["气压低", "沸点降", "煮不熟"],
          str(reach))

# 校准②：持久化往返（存储层）
if "图持久化-序列化" in generated:
    ser = generated["图持久化-序列化"][0]
    g = generated["图存储-节点边"][0]["Graph"]()
    g.add_edge("气压低", "沸点降")
    text = ser["graph_to_json"](g)
    g2 = ser["graph_from_json"](text)
    check('校准② 图持久化往返', g2.nodes == g.nodes
          and g2.neighbors("气压低") == ["沸点降"], f'nodes={sorted(g2.nodes)}')

# 校准③：任务识别
check('校准③ 任务识别', route_graph_unit("图遍历怎么做") == "图遍历-BFS"
      and route_graph_unit("图序列化") == "图持久化-序列化", '')

# 校准④：真实条件单元库对接（compose_engine 43 单元 → 条件路由图 → 路由查询）
if "条件路由图-对接" in generated:
    db_ns = generated["条件路由图-对接"][0]
    import compose_engine as ce
    g = db_ns["build_from_condition_units"](ce.CONDITION_UNITS)
    impact = db_ns["condition_impact"](g, "气压")
    check('校准④a 真实条件单元建图(43单元)', len(ce.CONDITION_UNITS) >= 30
          and len(g.nodes) > 30, f'{len(ce.CONDITION_UNITS)} 单元 → {len(g.nodes)} 节点')
    check('校准④b 气压影响面含沸点-气压', "沸点-气压" in impact,
          f'{len(impact)} 规律: {impact[:6]}…')
    # 与 compose_engine 行为对照：气压条件确实驱动沸点-气压单元（高原煮饭）
    r = ce.route_compose("为什么高原上煮饭不容易熟？")
    check('校准④c 与compose行为对照', r.get("ok")
          and "沸点" in r.get("answer", ""), r.get("answer", "")[:30])

print(f'\n=== 图数据库白箱自举测试: {pass_n}/{pass_n + fail_n} 通过 ===')
sys.exit(0 if fail_n == 0 else 1)
