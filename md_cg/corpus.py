# -*- coding: utf-8 -*-
"""P0/P1 验收共用的自建 md 文档语料（替代旧 sqlite 库作为测试基底）

14 个域（对齐 routing.BIG_DOMAINS 的大域划分）× 6 个知识点 × 4 个侧面 = 336 个
knowledge 节点，每个知识点 = 一个 md 节点文件。两种正文形态：

  · marks=True  → 完整 CCG 五要素正文（P0 用它验「节点是 md 文档形态」）
  · marks=False → 纯叙述正文、不含 MARKS 行（P1 用它模拟「旧库迁移来的节点」，
                 这样 health 的 CCG 完整度统计才有「不得虚报」的对照物）

按 domain: 标签分桶后：14 桶、期望扫描 = 1/14 ≈ 7.1% < 10%，最大桶 7.1% < 30%，
单例桶率 0 < 50% → 分区健康度自检通过，且「扫描量 < 全库 10%」的断言有真实余量。

分域刻意对齐 routing.BIG_DOMAINS（计算机科学/物理学/数学/生物学/…），
否则大域收敛与条件路由这两条链路会各测各的、互相掩盖问题。
"""
import os
import shutil

# 对齐 routing.BIG_DOMAINS 的 14 个大域
DOMAINS = [
    ("计算机科学", ["二分查找", "快速排序", "哈希表", "二叉树", "递归", "事务隔离"]),
    ("物理学", ["能量守恒", "牛顿第二定律", "熵增", "动量守恒", "简谐振动", "麦克斯韦方程组"]),
    ("数学", ["贝塞尔不等式", "泰勒展开", "矩阵秩", "特征值", "测度", "同余"]),
    ("生物学", ["细胞呼吸", "光合作用", "基因表达", "酶催化", "免疫应答", "种群增长"]),
    ("化学", ["化学平衡", "电负性", "氧化还原", "配位键", "反应速率", "摩尔浓度"]),
    ("材料科学", ["位错", "相图", "晶格缺陷", "疲劳强度", "热处理", "复合界面"]),
    ("机械工程", ["内力与截面法", "齿轮传动", "轴系平衡", "公差配合", "疲劳寿命", "液压回路"]),
    ("土木工程", ["弯矩", "混凝土配合比", "地基承载力", "抗震设防", "钢结构稳定", "施工缝"]),
    ("电子信息", ["采样定理", "调制解调", "根升余弦", "信道编码", "锁相环", "噪声系数"]),
    ("医学", ["血压调节", "药物代谢", "免疫耐受", "病理切片", "诊断阈值", "预后评估"]),
    ("经济学", ["边际效用", "供需均衡", "机会成本", "乘数效应", "通胀预期", "博弈均衡"]),
    ("语言学", ["音位", "句法树", "语义场", "语用预设", "形态变化", "方言分区"]),
    ("哲学", ["范畴", "因果性", "先验综合", "意向性", "范式", "证伪"]),
    ("体育", ["有氧耐力", "周期化训练", "运动损伤", "乳酸阈值", "核心稳定", "恢复策略"]),
]
ASPECTS = ("定义", "判据", "机制", "应用")
MARKS = ("# 功能名：", "# 生效条件：", "# 子功能：", "# 执行：", "# 验证方式：",
         "# 不适用条件：")
EXPECTED_NODES = sum(len(points) for _dom, points in DOMAINS) * len(ASPECTS)


def body(dom, point, aspect, marks=True):
    """节点正文。marks=True 给完整 CCG 五要素，否则给纯叙述正文（无 MARKS 行）。"""
    if marks:
        return (f"# 功能名：{dom}知识点·{point}·{aspect}\n"
                f"# 生效条件：问题涉及「{point}」的{aspect}时生效\n"
                f"# 子功能：{point} 的{aspect}条目（{dom}）\n"
                f"# 执行：{dom} 领域知识点「{point}」的{aspect}，"
                "用于条件化检索与召回对照。\n"
                "# 验证方式：教材（data）\n"
                "# 不适用条件：（无）\n\n"
                f"{point}（{dom}·{aspect}）知识点条目。\n")
    return (f"{point} 是 {dom} 领域的知识点，其{aspect}要点如下："
            f"在 {dom} 的教材叙述中，{point} 的{aspect}"
            "常用于条件化检索与召回对照。\n")


def node_id(di, pi, ai):
    return f"kp_{di:02d}_{pi:02d}_{ai}"


def seed(cg, marks=True, layer="knowledge", verification_basis="data"):
    """把整套语料写进 cg，返回写入节点数。幂等：节点 id 固定（同 id 原子覆盖）。"""
    n = 0
    for di, (dom, points) in enumerate(DOMAINS):
        for pi, point in enumerate(points):
            for ai, aspect in enumerate(ASPECTS):
                cg.add(node_id(di, pi, ai), body(dom, point, aspect, marks),
                       layer=layer,
                       tags=[f"domain:{dom}"],
                       importance=0.4 + 0.1 * ai,
                       condition_space={
                           "observation_position": f"{dom} 知识点（{point}·{aspect}）",
                           "observation_tool": "教材",
                           "existence_constraint": "公开",
                       },
                       verification_basis=verification_basis)
                n += 1
    cg.flush()
    return n


def reset_root(root, clean=False):
    """确保测试根存在：保证「重跑 ≡ 首跑」，且上一轮残留节点不会被当成先验。

    默认**不删目录**（对齐本仓已裁决的设计，见 docs/认知图_MD目录方案_v0.1.md
    「幂等性：迁移按 node id 原子覆盖写，可反复执行，**不需要先清空目录**」）：
    `seed()` 用固定 node id 原子覆盖，同一套语料重跑落在同一批文件上，集合封闭。

    清空不只是多余，而是**脆弱且失败不可见**：它依赖 `rmtree` 全量删除，
    在有批量删除安全策略的环境里会被拒并中断进程。实测 `_md_cg_p0_conc`
    累积 722 文件（> 阈值 500）时，test_p0 在**第一条断言之前**就被中断，
    输出只剩 443 字节且**没有任何 FAIL 项**——测试静默不可重跑，违反白箱
    可审计性（失败必须可见、可归因）。

    因此重跑不变性改由两个可观测事实共同守住：
      1. 写入侧同 id 原子覆盖（`seed` 固定 id；并发段用 w{轮}_{进程}_{序号}）；
      2. 各测试的**等号**断言（如 test_p0「索引节点数 == 语料期望数」）——
         一旦有残留污染，它会被打红，而不是被 `rmtree` 悄悄掩盖。

    clean=True 时才真删，仅供人工排障；同样可能被安全策略拦截。
    """
    if clean and os.path.isdir(root):
        shutil.rmtree(root)
    os.makedirs(root, exist_ok=True)
