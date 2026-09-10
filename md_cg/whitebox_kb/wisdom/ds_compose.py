# -*- coding: utf-8 -*-
"""ds_compose.py · 数据结构/算法概念条件单元（第四阶段·代码深学·数据结构方向）
数据结构概念 = 条件单元（{条件→规律}）：问题「数组和链表有什么区别/
为什么用哈希表/排序为什么是 O(n log n)」→ 方向识别 → 概念单元 → 组合生成。
条件细化：单字方向词排除冲突（「图」不命中「图片/图像/图形」）。
零 LLM 确定性——数据结构知识白箱化。
"""
import sys
sys.stdout.reconfigure(encoding='utf-8')


# ============ 一、数据结构/算法概念单元 ============
DS_UNITS = {
    "数组": {
        "direction": "数组",
        "conditions": ["数组", "连续内存", "下标"],
        "rule": "连续内存 → 随机访问O(1) → 固定大小 → 插入/删除O(n)",
        "conclusion": ("{数组}分配连续内存 → 按下标随机访问 O(1) → 大小固定"
                       " → 中间插入/删除需搬移元素 O(n) → 适合读多写少"),
        "core": ["数组", "连续", "O(1)", "下标", "随机"],
        "examples": ["什么是数组", "数组和链表区别", "为什么数组快"],
    },
    "链表": {
        "direction": "链表",
        "conditions": ["链表", "节点", "指针"],
        "rule": "节点+指针 → 插入/删除O(1) → 随机访问O(n) → 无需连续内存",
        "conclusion": ("{链表}由节点+指针串联 → 已知位置插入/删除 O(1) → "
                       "随机访问要遍历 O(n) → 不要求连续内存 → 适合写多读少"),
        "core": ["链表", "节点", "指针", "O(n)", "插入"],
        "examples": ["什么是链表", "链表为什么插入快", "单链表双链表"],
    },
    "栈": {
        "direction": "栈",
        "conditions": ["栈", "后进先出", "LIFO"],
        "rule": "后进先出LIFO → 压栈/弹栈 → 递归调用/撤销 → 深度优先",
        "conclusion": ("{栈}是后进先出（LIFO）结构 → 压栈/弹栈都在栈顶 O(1) → "
                       "天然承载递归调用与撤销操作 → 深度优先遍历的骨架"),
        "core": ["栈", "LIFO", "后进先出", "递归", "栈顶"],
        "examples": ["什么是栈", "栈和队列区别", "递归为什么用栈"],
    },
    "队列": {
        "direction": "队列",
        "conditions": ["队列", "先进先出", "FIFO"],
        "rule": "先进先出FIFO → 入队/出队 → 排队/任务调度 → 广度优先",
        "conclusion": ("{队列}是先进先出（FIFO）结构 → 入队尾部/出队头部 O(1) → "
                       "天然承载排队与任务调度 → 广度优先遍历的骨架"),
        "core": ["队列", "FIFO", "先进先出", "排队", "调度"],
        "examples": ["什么是队列", "栈和队列区别", "消息队列"],
    },
    "树": {
        "direction": "树",
        "conditions": ["树", "二叉树", "层次"],
        "rule": "层次结构（根/子节点）→ 二叉搜索树 → 查找O(log n) → 平衡保证",
        "conclusion": ("{树}是层次结构（根/子节点，无环）→ 二叉搜索树左小右大 "
                       "→ 查找/插入 O(log n) → 靠平衡（AVL/红黑）保证不退化"),
        "core": ["树", "节点", "层次", "O(log n)", "查找"],
        "examples": ["什么是二叉树", "二叉搜索树", "为什么树查找快"],
    },
    "图": {
        "direction": "图",
        "conditions": ["图", "边", "路径", "图论"],
        "rule": "节点+边 → 路径/连通性 → DFS/BFS遍历 → 最短路径",
        "conclusion": ("{图}由节点+边构成（可带权/有向）→ 研究路径与连通性 "
                       "→ 深度/广度优先遍历 → 最短路径（Dijkstra 等）"),
        "core": ["图", "节点", "边", "路径", "遍历"],
        "examples": ["什么是图数据结构", "图论是什么", "最短路径算法"],
    },
    "哈希表": {
        "direction": "哈希表",
        "conditions": ["哈希", "散列", "键值"],
        "rule": "键→值映射 → 平均O(1)查找 → 冲突需解决 → 无序但快",
        "conclusion": ("{哈希表}把键映射到桶（散列函数）→ 查找/插入平均 O(1) "
                       "→ 冲突需解决（链地址/开放寻址）→ 快但无序 → 适合按键直查"),
        "core": ["哈希", "键", "O(1)", "冲突", "映射"],
        "examples": ["什么是哈希表", "哈希冲突怎么解决", "字典实现"],
    },
    "排序": {
        "direction": "排序",
        "conditions": ["排序", "冒泡", "快排", "归并"],
        "rule": "比较排序下界O(n log n) → 稳定排序保持相对顺序 → 按场景选算法",
        "conclusion": ("{排序}把序列按比较键排好 → 比较排序最优下界 O(n log n)"
                       " → 稳定排序保持相等元素相对顺序 → 按场景选（快排/归并/堆排序）"),
        "core": ["排序", "O(n log n)", "比较", "稳定", "归并"],
        "examples": ["排序为什么是 nlogn", "快排是什么", "稳定排序"],
    },
    "复杂度": {
        "direction": "复杂度",
        "conditions": ["复杂度", "大O", "渐进"],
        "rule": "大O度量规模增长 → 时间/空间权衡 → 渐进分析忽略常数",
        "conclusion": ("{复杂度}用大 O 度量输入规模增长的量级 → 渐进分析忽略常数与低阶 "
                       "→ 时间/空间权衡（省时费空间或反之）→ 描述增长趋势非精确耗时"),
        "core": ["复杂度", "O(", "规模", "渐进", "权衡"],
        "examples": ["什么是时间复杂度", "大O是什么", "空间复杂度"],
    },
}

# 方向识别（问题 → 数据结构概念）；单字「图」排除 图片/图像/图形
DS_EXCLUDE_GRAPH = ["图片", "图像", "图形", "图画", "地图绘制"]
DS_DIRECTIONS = {
    "数组": ["数组", "连续内存", "下标访问", "随机访问"],
    "链表": ["链表", "linked list", "单链表", "双链表", "指针节点"],
    "栈": ["栈", "堆栈", "LIFO", "后进先出", "压栈", "弹栈"],
    "队列": ["队列", "queue", "FIFO", "先进先出", "消息队列"],
    "树": ["树", "二叉树", "二叉搜索", "红黑树", "BST", "层次结构"],
    "图": ["图论", "最短路径", "图的遍历", "邻接表", "邻接矩阵", "有向图", "图"],
    "哈希表": ["哈希", "散列", "hash", "键值映射", "字典"],
    "排序": ["排序", "冒泡", "快排", "归并", "堆排序", "稳定排序"],
    "复杂度": ["复杂度", "大O", "时间复杂度", "空间复杂度", "渐进分析"],
}


def identify_ds_direction(question):
    """数据结构概念识别（最长关键词优先 + 平局取最后 + 图域排除）"""
    best, best_len = None, 0
    for direction, kws in DS_DIRECTIONS.items():
        for k in kws:
            if k not in question:
                continue
            if direction == "图" and any(e in question for e in DS_EXCLUDE_GRAPH):
                continue
            if len(k) >= best_len:
                best, best_len = direction, len(k)
    return best


def ds_route(question):
    """数据结构概念组合生成：方向识别 → 概念单元 → 模板生成 → 自校验"""
    direction = identify_ds_direction(question)
    if direction is None:
        return {"question": question, "ok": False,
                "reason": "数据结构概念未识别（落回通用域）"}
    unit = None
    for uid, u in DS_UNITS.items():
        if u["direction"] == direction:
            unit = u
            break
    if unit is None:
        return {"question": question, "ok": False,
                "reason": f"概念[{direction}]无单元覆盖"}
    # 组合生成（占位符代入概念名）
    answer = unit["conclusion"].replace("{数组}", "数组").replace(
        "{链表}", "链表").replace("{栈}", "栈").replace("{队列}", "队列").replace(
        "{树}", "树").replace("{图}", "图").replace("{哈希表}", "哈希表").replace(
        "{排序}", "排序").replace("{复杂度}", "复杂度")
    # 自校验：答案含概念核心词（白箱确定性）
    core_hit = sum(1 for c in unit["core"] if c in answer)
    ok = core_hit >= 2
    checks = [] if ok else [f"✗ 概念自校验失败：核心词命中 {core_hit}/{len(unit['core'])}"]
    return {"question": question, "direction": direction,
            "ok": ok, "answer": answer, "checks": checks,
            "core_hit": core_hit, "unit": [u for u, x in DS_UNITS.items() if x is unit][0]}


if __name__ == "__main__":
    print("=== 数据结构/算法概念条件单元（代码深学 · 零 LLM）===\n")
    QS = [
        "什么是数组？", "链表和数组有什么区别？", "什么是栈？",
        "队列有什么用？", "什么是二叉树？", "什么是图数据结构？",
        "为什么用哈希表？", "排序为什么是 O(n log n)？", "什么是时间复杂度？",
    ]
    ok_n = 0
    for q in QS:
        r = ds_route(q)
        if r.get("ok"):
            ok_n += 1
        mark = "✔" if r.get("ok") else "✘"
        print(f"[{mark}] ({r.get('direction')}) {q}")
        print(f"   -> {r.get('answer', r.get('reason'))}")
        for c in r.get("checks", []):
            print(f"   {c}")
    # 未识别回落
    r = ds_route("什么是碳中和？")
    print(f"\n[{'✔' if not r.get('ok') else '✘'}] 非数据结构问题回落: {r.get('reason')}")
    # 单字排除
    r = ds_route("图片处理有哪些步骤？")
    print(f"[{'✔' if not r.get('ok') else '✘'}] 单字排除（图片不命中图域）: {r.get('reason')}")
    print(f"\n=== 判定 ===\n数据结构概念命中: {ok_n}/{len(QS)}")
