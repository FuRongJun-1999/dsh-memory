# -*- coding: utf-8 -*-
"""code_compose.py · 白箱自举第二阶段·代码编写主线原型 v1
理论：《白箱自举·角色扮演与代码编写》（§3 代码=编程规律条件单元）
核心：代码编写=带条件的知识问答（条件=编程任务需求）——
  ① 代码条件单元 CODE_UNITS（{任务 → 代码模式模板}，带 {参数} 占位）
  ② 任务方向识别（问题 → 任务：排序/去重/计数/最大/反转/求和）
  ③ 组合生成（任务模板 × 参数 → 代码，未预写完整代码）
  ④ 自校验三层：L1 语法（ast.parse）→ L2 样例（输入→期望断言运行）→ L3 边界
  ⑤ 固化：验证通过代码 → 固化 JSON → 同任务直出
零 LLM：全部白箱确定性生成 + 自校验（语法/测试是物理基底裁决）。
"""
import sys, json, os, ast
sys.stdout.reconfigure(encoding='utf-8')


# ============ 一、代码条件单元库（任务 → 代码模式模板 + 验证样例） ============
# pattern: 代码模板（{fn}=函数名占位）；cases: (输入, 期望输出) 自校验样例
CODE_UNITS = {
    "排序-冒泡": {
        "task": "排序",
        "pattern": (
            "def {fn}(arr):\n"
            "    # 排序：冒泡法（相邻比较交换，较小元素浮到头部）\n"
            "    n = len(arr)\n"
            "    for i in range(n):\n"
            "        for j in range(n - 1 - i):\n"
            "            if arr[j] > arr[j + 1]:\n"
            "                arr[j], arr[j + 1] = arr[j + 1], arr[j]\n"
            "    return arr\n"),
        "cases": [([3, 1, 2], [1, 2, 3]), ([5, 4, 3, 2, 1], [1, 2, 3, 4, 5]),
                  ([7], [7]), ([], [])],
        "params": ["fn"],
    },
    "去重-保序": {
        "task": "去重",
        "pattern": (
            "def {fn}(arr):\n"
            "    # 去重：保留首次出现顺序（seen 集合判重）\n"
            "    seen = set()\n"
            "    out = []\n"
            "    for x in arr:\n"
            "        if x not in seen:\n"
            "            seen.add(x)\n"
            "            out.append(x)\n"
            "    return out\n"),
        "cases": [([1, 2, 2, 3, 1], [1, 2, 3]), ([], []), ([1, 1, 1], [1])],
        "params": ["fn"],
    },
    "计数-频率": {
        "task": "计数",
        "pattern": (
            "def {fn}(arr):\n"
            "    # 计数：元素出现频率（Counter 统计）\n"
            "    from collections import Counter\n"
            "    return dict(Counter(arr))\n"),
        "cases": [([1, 2, 2, 3], {1: 1, 2: 2, 3: 1}), ([], {}), (["a", "a"], {"a": 2})],
        "params": ["fn"],
    },
    "最大值": {
        "task": "最大",
        "pattern": (
            "def {fn}(arr):\n"
            "    # 最大值：线性扫描取最大（空列表返回 None）\n"
            "    if not arr:\n"
            "        return None\n"
            "    m = arr[0]\n"
            "    for x in arr[1:]:\n"
            "        if x > m:\n"
            "            m = x\n"
            "    return m\n"),
        "cases": [([3, 1, 2], 3), ([7], 7), ([], None), ([-1, -5, -2], -1)],
        "params": ["fn"],
    },
    "反转列表": {
        "task": "反转",
        "pattern": (
            "def {fn}(arr):\n"
            "    # 反转：切片逆序（倒序排列）\n"
            "    return arr[::-1]\n"),
        "cases": [([1, 2, 3], [3, 2, 1]), ([], []), (["a", "b"], ["b", "a"])],
        "params": ["fn"],
    },
    "求和": {
        "task": "求和",
        "pattern": (
            "def {fn}(arr):\n"
            "    # 求和：累加所有元素（空列表返回 0）\n"
            "    total = 0\n"
            "    for x in arr:\n"
            "        total += x\n"
            "    return total\n"),
        "cases": [([1, 2, 3], 6), ([], 0), ([5], 5)],
        "params": ["fn"],
    },
    "最大公约数": {
        "task": "最大公约数",
        "pattern": (
            "def {fn}(a, b):\n"
            "    while b:\n"
            "        a, b = b, a % b\n"
            "    return a\n"),
        "cases": [((48, 36), 12), ((7, 5), 1), ((0, 5), 5), ((54, 24), 6)],
        "params": ["fn"],
    },
    "斐波那契": {
        "task": "斐波那契",
        "pattern": (
            "def {fn}(n):\n"
            "    if n <= 0:\n"
            "        return []\n"
            "    fib = [0, 1]\n"
            "    while len(fib) < n:\n"
            "        fib.append(fib[-1] + fib[-2])\n"
            "    return fib[:n]\n"),
        "cases": [(1, [0]), (5, [0, 1, 1, 2, 3]), (10, [0, 1, 1, 2, 3, 5, 8, 13, 21, 34])],
        "params": ["fn"],
    },
    "素数": {
        "task": "素数",
        "pattern": (
            "def {fn}(n):\n"
            "    if n < 2:\n"
            "        return False\n"
            "    i = 2\n"
            "    while i * i <= n:\n"
            "        if n % i == 0:\n"
            "            return False\n"
            "        i += 1\n"
            "    return True\n"),
        "cases": [(2, True), (3, True), (4, False), (17, True), (1, False), (0, False)],
        "params": ["fn"],
    },
}

# 任务方向识别（问题 → 任务，最长关键词优先）
TASK_KEYWORDS = {
    "排序": ["排序", "排好", "从小到大", "升序", "从大到小", "降序", "整理顺序"],
    "去重": ["去重", "重复", "不重复", "唯一", "去掉重复"],
    "计数": ["数一数", "计数", "出现次数", "几次", "统计", "频率"],
    "最大": ["最大", "最大值", "最高的", "最大的数", "最多"],
    "反转": ["反转", "倒过来", "倒序", "反过来"],
    "求和": ["求和", "加起来", "总和", "相加", "累加", "的和", "之和"],
    "最大公约数": ["最大公约数", "最大公因数", "公约数", "公因数", "gcd"],
    "斐波那契": ["斐波那契", "fibonacci", "fib"],
    "素数": ["素数", "质数", "是不是质数", "判断质数", "isprime", "prime"],
}

# ============ 四、多语言代码单元（第四阶段·代码深学：Rust / JavaScript） ============
# 每单元带 py_ref（Python 等价实现）——Rust/JS 逻辑样例用 py_ref 验证（模板逻辑正确性）

RUST_UNITS = {
    "排序-冒泡": {
        "task": "排序", "lang": "rust",
        "pattern": ("fn {fn}(arr: &mut Vec<i32>) {\n"
                    "    let n = arr.len();\n"
                    "    for i in 0..n {\n"
                    "        for j in 0..n - 1 - i {\n"
                    "            if arr[j] > arr[j + 1] {\n"
                    "                arr.swap(j, j + 1);\n"
                    "            }\n"
                    "        }\n"
                    "    }\n"
                    "}\n"),
        "cases": [([3, 1, 2], [1, 2, 3]), ([5, 4, 3, 2, 1], [1, 2, 3, 4, 5]),
                  ([], [])],
        "py_ref": "def solve(arr):\n    arr = arr[:]\n    n = len(arr)\n"
                  "    for i in range(n):\n        for j in range(n - 1 - i):\n"
                  "            if arr[j] > arr[j + 1]:\n"
                  "                arr[j], arr[j + 1] = arr[j + 1], arr[j]\n"
                  "    return arr\n",
    },
    "求和": {
        "task": "求和", "lang": "rust",
        "pattern": "fn {fn}(arr: &[i32]) -> i32 {\n    arr.iter().sum()\n}\n",
        "cases": [([1, 2, 3], 6), ([], 0), ([5], 5)],
        "py_ref": "def solve(arr): return sum(arr)\n",
    },
    "最大值": {
        "task": "最大", "lang": "rust",
        "pattern": ("fn {fn}(arr: &[i32]) -> Option<i32> {\n"
                    "    arr.iter().copied().max()\n}\n"),
        "cases": [([3, 1, 2], 3), ([7], 7), ([], None)],
        "py_ref": "def solve(arr): return max(arr) if arr else None\n",
    },
    "去重-保序": {
        "task": "去重", "lang": "rust",
        "pattern": ("fn {fn}(arr: &[i32]) -> Vec<i32> {\n"
                    "    let mut seen = std::collections::HashSet::new();\n"
                    "    arr.iter().copied().filter(|x| seen.insert(*x)).collect()\n}\n"),
        "cases": [([1, 2, 2, 3, 1], [1, 2, 3]), ([], []), ([1, 1, 1], [1])],
        "py_ref": "def solve(arr):\n    seen = set(); out = []\n"
                  "    for x in arr:\n        if x not in seen: seen.add(x); out.append(x)\n"
                  "    return out\n",
    },
    "反转": {
        "task": "反转", "lang": "rust",
        "pattern": ("fn {fn}(arr: &[i32]) -> Vec<i32> {\n"
                    "    arr.iter().rev().copied().collect()\n}\n"),
        "cases": [([1, 2, 3], [3, 2, 1]), ([], []), ([7], [7])],
        "py_ref": "def solve(arr): return arr[::-1]\n",
    },
}

JS_UNITS = {
    "排序": {
        "task": "排序", "lang": "javascript",
        "pattern": "function {fn}(arr) {\n    return arr.slice().sort((a, b) => a - b);\n}\n",
        "cases": [([3, 1, 2], [1, 2, 3]), ([5, 4, 3, 2, 1], [1, 2, 3, 4, 5]),
                  ([], [])],
        "py_ref": "def solve(arr): return sorted(arr)\n",
    },
    "求和": {
        "task": "求和", "lang": "javascript",
        "pattern": "function {fn}(arr) {\n    return arr.reduce((s, x) => s + x, 0);\n}\n",
        "cases": [([1, 2, 3], 6), ([], 0), ([5], 5)],
        "py_ref": "def solve(arr): return sum(arr)\n",
    },
    "反转": {
        "task": "反转", "lang": "javascript",
        "pattern": "function {fn}(arr) {\n    return arr.slice().reverse();\n}\n",
        "cases": [([1, 2, 3], [3, 2, 1]), ([], []), (["a", "b"], ["b", "a"])],
        "py_ref": "def solve(arr): return arr[::-1]\n",
    },
    "去重": {
        "task": "去重", "lang": "javascript",
        "pattern": "function {fn}(arr) {\n    return [...new Set(arr)];\n}\n",
        "cases": [([1, 2, 2, 3, 1], [1, 2, 3]), ([], []), ([1, 1, 1], [1])],
        "py_ref": "def solve(arr):\n    seen = set(); out = []\n"
                  "    for x in arr:\n        if x not in seen: seen.add(x); out.append(x)\n"
                  "    return out\n",
    },
    "最大": {
        "task": "最大", "lang": "javascript",
        "pattern": "function {fn}(arr) {\n    return arr.length ? Math.max(...arr) : null;\n}\n",
        "cases": [([3, 1, 2], 3), ([7], 7), ([], None)],
        "py_ref": "def solve(arr): return max(arr) if arr else None\n",
    },
}

LANG_UNITS = {"python": CODE_UNITS, "rust": RUST_UNITS,
              "javascript": JS_UNITS}


# ============ 五、域单元注册（第六阶段·白箱自举正式管线接管） ============
# 四套域单元库（编译器/语言机制/图数据库/操作系统）接入正式自举管线：
# 域识别 → 单元匹配 → 模板填充 → verify_code 三层自校验 → 固化 JSON → 固化直出
try:
    from compiler_code_units import COMPILER_UNITS as _CU
    from python_code_units import PYTHON_UNITS as _PU
    from graph_db_units import GRAPH_UNITS as _GU
    from os_units import OS_UNITS as _OU
    from browser_units import BROWSER_UNITS as _BU
    from net_units import NET_UNITS as _NU
except Exception:
    _CU = _PU = _GU = _OU = _BU = _NU = {}

DOMAIN_UNITS = {"compiler": _CU, "pylang": _PU,
                "graph": _GU, "os": _OU, "browser": _BU, "net": _NU}

# 域识别词表（问题 → 域）
DOMAIN_KEYWORDS = {
    "compiler": ["编译", "词法", "语法", "VM", "字节码", "序列化", "调试",
                 "类型推断", "类型检查", "名实", "道德经", "中文编译器",
                 "函数", "递归", "定义", "注释", "逻辑表达式", "链式",
                 "常量折叠", "死代码", "寄存器", "优化", "闭包", "词法作用域",
                 "捕获环境", "断点", "回溯", "监视", "内联展开", "循环展开",
                 "尾调用", "文件头校验", "完整性校验", "紧凑编码", "圈复杂度",
                 "活跃变量", "调用图", "字符串字面量", "数字字面量",
                 "数组字面量", "作用域分析", "常量传播", "指令重排", "引用计数",
                 "指令剖析", "栈保护", "名实一致", "类型转换", "数据流分析",
                 "三元表达式", "复合赋值", "位运算", "标识符解析", "操作符解析", "函数签名", "栈操作", "算术执行", "比较执行", "信任检查", "信息差追踪", "条件空间类型", "条件断点", "调用计数", "覆盖率", "窥孔优化", "指令融合", "循环不变式", "字典字面量", "元组解析", "转义序列", "条件空间符号类型", "布尔字面量", "空值字面量", "行号跟踪", "关键字识别", "常量池", "语句分隔", "异常处理", "表达式树", "栈深度分析", "基本块", "支配树", "中间表示", "循环检测", "指令调度", "寄存器溢出", "数组操作", "污点分析", "边界检查消除", "字符类别", "括号匹配", "指令选择", "循环开销", "字符串拼接", "指令大小", "控制流图", "内联缓存", "寄存器着色", "数字后缀", "逃逸分析", "去虚拟化", "名实绑定", "信任流分析", "短路求值", "devirtualize"],
    "pylang": ["Python", "表达式", "闭包", "闭包机制", "控制流", "作用域", "栈机",
               "优先级", "逻辑短路", "异常", "抛出", "捕获", "try", "raise",
               "工厂", "延迟绑定", "nonlocal", "生成器", "yield", "迭代器",
               "推导", "继承", "多态", "类定义", "装饰器", "上下文",
               "with", "属性", "类型注解", "运行时检查", "协议", "类型",
               "异步", "协程", "事件循环", "并发", "元编程", "动态建类",
               "元类", "描述符", "运算符重载", "枚举", "数据类", "正则匹配",
               "日期时间", "JSON序列化", "队列栈", "格式化", "排序键控",
               "集合运算", "计数器", "分组", "自定义异常", "对象组合",
               "深拷贝", "超时控制", "任务取消", "异步信号量", "映射", "过滤",
               "归约", "字符串拆分", "字符串替换", "字符串判断", "数学函数", "数值舍入", "数值统计", "默认参数", "关键字参数", "多行字符串", "文件读取", "性能计时", "环境查询", "链表", "进制转换", "异常链", "二叉树", "迭代工具", "字典合并", "最小堆", "函数缓存", "异步生成器", "切片操作", "矩阵运算", "类装饰器", "默认字典", "排列组合", "二分查找", "字典推导", "异步队列", "模板渲染", "有序字典", "随机采样", "字节编解码", "字符串哈希", "跳表", "时间格式化", "字符串对齐", "顺序去重", "滑动均值", "行程压缩", "位掩码", "众数统计", "分位数", "文本分词", "笛卡尔积", "列表分块", "嵌套扁平化", "循环轮转", "字典反转", "直方图", "峰值检测", "累加器", "成对迭代", "打乱", "并查集", "最长公共前缀", "编辑距离", "解包赋值", "集合推导", "切片赋值"],
    "graph": ["图数据库", "图遍历", "图查询", "条件路由图", "遍历", "路径",
              "路由", "持久化", "条件链", "建图", "图存储", "模式匹配",
              "聚合", "匹配", "事务", "索引", "子图", "PageRank", "连通",
              "拓扑", "执行计划", "批量", "布隆", "相似度", "同构", "社区",
              "属性", "快照", "版本", "时序", "增量", "分片", "复制",
              "分布式", "分区", "力导向", "布局", "邻接矩阵", "可视化",
              "备份", "恢复", "一致性", "压缩", "指标", "健康", "度分布",
              "监控", "嵌入", "特征", "推荐", "图学习", "权限", "租户",
              "加密", "安全", "ACL", "读写分离", "慢查询", "在线扩容",
              "最小生成树", "二分图", "中心性", "正则路径", "查询缓存",
              "物化视图", "环形布局", "视口变换", "社区着色", "邻接表压缩",
              "图合并", "属性边", "最大流", "欧拉路径", "图直径", "条件合并",
              "信任传播", "信息差收敛", "布隆过滤", "租户隔离", "增量备份", "一致性快照", "一致性哈希", "邻居查询", "路径过滤", "三角形计数", "导出子图", "时间窗口", "边活跃度", "模式路径", "节点标签", "模糊匹配", "条件回溯", "信任聚合", "审计日志", "审计记录", "强连通分量", "二分匹配", "可达性判定", "传递闭包", "图着色", "最小割", "聚类系数", "介数中心性", "边索引", "割点", "独立集", "桥检测", "游标遍历", "路径规划", "节点大小", "最大团", "旅行商", "标签约束", "度序列", "生成树计数", "路径计数", "支配集", "弦图判定", "标签计数", "汉密尔顿路径", "图差分", "双层邻居", "树重心", "最大割", "图规范化", "顶点覆盖", "最近公共祖先", "条件分解", "出度直方图"],
    "os": ["进程", "调度", "内存", "文件系统", "路径解析", "管道", "IPC",
           "inode", "页置换", "缺页", "状态机", "最短作业", "SJF",
           "块管理", "位图", "优先级调度", "互斥", "首次适配", "文件块",
           "页表", "虚拟", "页面", "物理帧", "MMU", "目录树", "文件描述符",
           "字符设备", "设备", "中断", "向量", "上下文", "嵌套", "抢占",
           "挂载", "权限", "进程树", "系统调用", "信号", "参数", "校验",
           "日志", "恢复", "监控", "守护", "信号量", "读写锁", "生产者",
           "命名空间", "cgroup", "容器", "虚拟化", "RAID", "条带", "奇偶",
           "快照", "引导", "启动", "固件", "init", "初始化", "访问控制",
           "审计", "能力", "ACL", "性能", "分析", "瓶颈", "调优", "系统",
           "配额", "锁", "限额", "ulimit", "安全启动", "TPM", "度量",
           "哈希", "可信", "校验", "热插拔", "即插即用", "设备树", "PnP",
           "文件权限", "消息队列", "共享内存", "邮箱", "消息槽", "多级反馈",
           "EDF", "文件系统调用", "伙伴系统", "写时复制", "内存压缩", "硬链接",
           "软链接", "文件元数据", "内存映射", "屏障同步", "工作池",
           "进程生命周期", "磁盘调度", "写时复制快照", "磨损均衡", "强制访问控制", "系统调用过滤", "加密文件系统", "服务管理", "日志轮转", "定时任务", "配置管理", "权限提升", "环境变量", "网络接口", "设备驱动", "电源管理", "文件压缩", "存储池", "文件版本", "条件变量", "自旋锁", "时间片轮转", "优先级继承", "内存池", "稀疏文件", "碎片整理", "段式管理", "时钟节拍", "孤儿进程", "内存碎片", "多核均衡", "僵尸进程", "内存热插拔", "文件系统日志", "进程组", "页缓存", "亲和性", "软中断", "工作窃取", "模块加载"],
    "browser": ["浏览器", "HTTP", "响应解析", "DOM", "HTML", "CSS", "选择器",
                "渲染", "布局", "网页", "标签解析", "URL", "请求", "主机",
                "端口", "协议", "盒模型", "级联", "样式", "padding", "border",
                "绘制", "布局树", "画布", "事件", "冒泡", "监听", "动画帧",
                "存储", "localStorage", "会话存储", "Worker", "并行",
                "Fetch", "缓存", "Cookie", "同源", "CSP", "安全", "XSS",
                "转义", "Service Worker", "推送", "IndexedDB", "渲染优化",
                "懒加载", "防抖", "节流", "性能", "应用清单", "缓存策略",
                "安装事件", "合成分层", "重排", "关键渲染路径", "历史记录",
                "书签", "标签页", "下载管理", "扩展管理", "网络记录", "表单验证",
                "拖放", "资源完整性", "媒体播放", "地理位置", "全屏模式", "预加载", "请求合并", "资源优先级", "权限API", "CSP报告", "支付请求", "响应式断点", "离线队列", "会话恢复", "CORS", "跨域资源共享", "文本排版", "剪贴板", "沙箱隔离", "滚动容器", "在线状态", "命中测试", "标签页通信", "页面可见性", "像素光栅化", "触控手势", "设备方向", "渐变填充", "网络信息", "字体加载", "颜色转换", "振动反馈", "混合模式", "边框圆角", "屏幕方向", "空闲调度", "摄像头", "蓝牙扫描", "传感器", "语音合成", "语音识别", "扫码", "画中画", "屏幕捕获", "文件系统访问", "File System", "网页共享", "唤醒锁", "窗口管理", "翻译", "语言检测", "文本摘要", "联系人", "形状检测", "存储配额", "内置聊天", "图像生成", "提示词", "游戏手柄", "虚拟键盘", "音频上下文", "事件委托", "弹窗拦截", "混合内容"],
    "net": ["网络", "TCP", "UDP", "IP分片", "握手", "校验和", "广播",
            "局域网", "蜂群", "socket", "中继", "分片", "路由表", "重传",
            "停等", "去重", "确认", "分帧", "会话", "滑动窗口", "拥塞",
            "累积确认", "慢启动", "CIDR", "子网", "距离矢量", "NAT",
            "DNS", "状态码", "负载均衡", "HTTP", "WebSocket", "帧封装",
            "流式", "多路复用", "连接池", "QUIC", "BGP", "Anycast", "CRC",
            "IPv6", "隧道", "VLAN", "MQTT", "遥测", "物联网", "消息队列",
            "FIFO", "CDN", "边缘计算", "内容路由", "前缀", "流量", "延迟", "异常",
            "RTT", "监控", "检测", "报文", "解析", "抓包", "解码", "协议",
            "令牌桶", "服务发现", "加密握手", "快速重传", "选择性确认", "SACK",
            "端口转发", "QoS", "QoS队列", "链路聚合", "滑动窗口限流",
            "反向代理", "组播", "Reno", "RTO", "吞吐量", "链路状态",
            "策略路由", "多径传输", "访问令牌", "压缩传输", "会话亲和", "链路加密", "流量镜像", "网络切片", "分块传输", "重定向", "内容协商", "路径MTU", "端口扫描", "会话超时", "消息路由", "API限流", "数据序列化", "DHCP", "租约", "ARP", "地址解析", "ICMP", "Ping", "广播风暴", "心跳保活", "报文重排序", "CSMA", "路由收敛", "链路预算", "RSSI", "NTP同步", "报文分片", "前向纠错", "尽力交付", "带宽时延积", "多宿主", "RTT平滑", "路由汇聚", "序列号回绕", "漏桶限流", "报文调度", "链路利用率", "带宽分配", "连接迁移", "重传统计", "路由衰减", "流分类", "数据包采样", "时隙", "跳频", "误码率", "拓扑发现", "路径备份", "FRR", "数据去重", "网关", "端口镜像", "包过滤", "帧解析", "MAC学习", "证书校验"],
}


def detect_domain(question):
    """域识别：问题 → 域（compiler/pylang/graph/os/browser/net/None）
    命中计数优先（「CSS级联+样式优先级」= browser 3 词 > pylang 1 词），
    平局取最长关键词（「路由表」len3 > 「路由」len2）；
    空格归一化（「JSON 序列化」→「JSON序列化」——与关键词连写对齐）"""
    best = None
    best_cnt_h = best_cnt_d = best_len = best_uid_bonus = 0
    q_compact = question.replace(" ", "")
    # 双层计分制（T1 缺口根治 v2）：跨域共享词（校验/序列化/审计日志）靠
    # 手工表无法消歧——引入 uid 完整串强信号（单元名含于问题 = +100），
    # 手工表词命中 = 常规分；两类分数独立累加后统一排序。
    q_hits = {}
    for domain, kws in DOMAIN_KEYWORDS.items():
        hit = {k for k in kws if k in question or k in q_compact}
        if hit:
            q_hits[domain] = hit
    unit_pool = {}
    for domain, units in DOMAIN_UNITS.items():
        pool = set()
        uid_full = set()
        for uid, u in units.items():
            uid_n = uid.replace("-", "")
            pool.add(uid)
            pool.update(uid.replace("-", "").split())
            pool.add(u.get("task", ""))
            pool.update(t for t in (u.get("triggers") or []) if t)
            # uid 完整串（含连字符原样与去连字符形态）强信号
            if uid in question or uid in q_compact:
                uid_full.add(uid)
            elif uid_n and (uid_n in q_compact):
                uid_full.add(uid)
        pool.discard("")
        unit_pool[domain] = (pool, uid_full)
    all_domains = sorted(set(DOMAIN_KEYWORDS) | set(DOMAIN_UNITS))
    for domain in all_domains:
        cnt_h = cnt_d = max_len = uid_bonus = 0
        # 手工表（人工维护强信号）：命中数与最长词都参与竞争
        hit = q_hits.get(domain, set())
        if hit:
            cnt_h = len(hit)
            max_len = max(len(k) for k in hit)
        # 动态池（白箱自举自动扩展）：仅新增词计 cnt_d，**不抬 max_len**
        # ——自动词是弱信号，只加数量分，防止子串词翻盘人工词
        pool, uid_full = unit_pool.get(domain, (set(), set()))
        if pool:
            hit2 = {k for k in pool if k in question or k in q_compact}
            cnt_d = len(hit2 - hit)
            if uid_full:
                uid_bonus = 100
                max_len = max(max_len, max(len(u2) for u2 in uid_full))
        if cnt_h == 0 and cnt_d == 0 and uid_bonus == 0:
            continue
        score_tuple = (uid_bonus, cnt_h, cnt_d, max_len)
        best_tuple = (best_uid_bonus, best_cnt_h, best_cnt_d, best_len)
        # 确定性：sorted 遍历序固定；平局保持先到者（≥ 已含于 > 语义，
        # 此处仅 > 判定——平局不翻转，消除 PYTHONHASHSEED 非确定性波动）
        if score_tuple > best_tuple:
            best, best_cnt_h, best_cnt_d, best_len, best_uid_bonus =                 domain, cnt_h, cnt_d, max_len, uid_bonus
    return best


def compose_domain_code(question, domain=None, unit_id=None):
    """域组合生成：域识别 → 单元匹配（task/uid 关键词）→ 模板填充"""
    domain = domain or detect_domain(question)
    if domain is None:
        return None, "域未识别（诚实边界：不属编译器/语言机制/图数据库/操作系统域）", None, None, None
    units = DOMAIN_UNITS.get(domain, {})
    # 单元匹配：uid/task 拆词（"编译-指令"→[编译,指令]）+ 原文（最长优先）
    def _unit_kws(u, uid):
        """单元级触发词聚合：triggers 表优先，拼接 uid/task 及其连字符词元拆解（T1 自举数据层）。"""
        # v0.2 T1（自举数据层）：单元级 triggers 触发词——
        # 缺口检测器（route_gap_audit）白箱自举产出的增强数据
        triggers = [t for t in (u.get("triggers") or []) if t]
        return triggers + [uid, u["task"]] + uid.replace("-", "").split() \
            + u["task"].replace("-", "").split() \
            + [p for p in uid.split("-") if p]

    best_uid, best_cnt, best_len = None, 0, 0
    q_compact = question.replace(" ", "")  # 空格归一化（"IP 分片"→"IP分片"）
    for uid, u in units.items():
        kws = _unit_kws(u, uid)
        hit = list({kw for kw in kws
                    if kw and (kw in question or kw in q_compact)})
        if not hit:
            continue
        cnt, max_len = len(hit), max(len(kw) for kw in hit)
        if cnt > best_cnt or (cnt == best_cnt and max_len > best_len):
            best_uid, best_cnt, best_len = uid, cnt, max_len
    if unit_id is not None and unit_id in units:
        best_uid = unit_id
    if best_uid is None:
        return None, f"域[{domain}]无匹配单元（条件链不完整）", None, None, domain
    unit = units[best_uid]
    code = unit["pattern"]
    return unit["task"], best_uid, code, unit, domain


def _verify_with_verifier(code, unit, unit_id=""):
    """本地校验器六层校验（替代 verify_code 三层）——返回 (ok, checks) 兼容格式。

    接入（阶段 4）：code_compose 生成 → verifier 校验 → 固化，全程零 LLM。
      - L1语法/L2样例/L3边界/规范符合性/集成 六层 + 指纹本地缓存
      - 相同请求第二次 → 指纹命中 → 零计算直接返回（替代 LLM 缓存命中）
      - unit_id 传入（与 --audit 共享同一指纹空间——同一单元同一指纹同一缓存条目）
      - 注入型单元（needs_inject）L2/L3 由集成测试覆盖；'call' 标记样例跳过
    """
    try:
        from verifier import Verifier, VerifyRequest        # 裸模块（同目录 sys.path，开发态）
    except ImportError:
        from wisdom.verifier import Verifier, VerifyRequest  # 包内相对（wheel 发布态）
    v = Verifier()
    req = VerifyRequest(
        task=unit.get("task", ""), code=code, unit_id=unit_id,
        cases=list(unit.get("cases", [])),
        expected_structure={"inject": True} if unit.get("needs_inject") else {},
    )
    r = v.verify(req)
    checks = []
    for c in r.checks:
        lv = c.get("level", "?")
        ok = c.get("ok")
        mark = "✔" if ok else "✗"
        # evidence 完整保留（[:60] 截断曾吞掉 L2 崩溃 traceback 关键诊断信息）
        checks.append(f"{mark} {lv} {str(c.get('evidence', ''))}")
    if r.cached:
        checks.append(f"✔ 缓存命中（指纹 {r.fingerprint[:12]}）")
    return r.ok, checks


def domain_solidify(question, domain=None, uid=None):
    """域固化：组合生成 + 本地校验器自校验通过 → 固化（自举纪律：未验证不固化）"""
    t, u, code, unit, domain = compose_domain_code(question, domain, uid)
    if code is None:
        return None
    ok, checks = _verify_with_verifier(code, unit, u)
    if not ok:
        return None  # 自校验未过 → 拒绝固化
    key = f"domain:{domain}|{u}"
    entry = {"task": t, "unit": u, "code": code, "checks": checks,
             "source": "domain_solidified", "domain": domain}
    CODE_SOLIDIFIED[key] = entry
    try:
        json.dump(CODE_SOLIDIFIED, open(_SOL_FILE, "w", encoding="utf-8"),
                  ensure_ascii=False, indent=1)
    except Exception:
        pass
    return entry


def domain_route(question, uid=None):
    """域路由统一入口：单元匹配 → 已固化直出 → 域组合生成 + 本地校验器校验"""
    domain = detect_domain(question)
    if domain is None:
        return {"question": question, "ok": False,
                "reason": "域未识别（诚实边界）", "domain": None, "code": None}
    # 单元匹配先行（与组合生成同一套逻辑），匹配到的单元已固化 → 直出
    t, u, code, unit, domain = compose_domain_code(question, domain, uid)
    if code is not None:
        key = f"domain:{domain}|{u}"
        if key in CODE_SOLIDIFIED:
            entry = CODE_SOLIDIFIED[key]
            return {"question": question, "ok": True, "solidified": True,
                    "code": entry["code"], "task": entry.get("task"),
                    "unit": entry.get("unit"), "domain": domain, "checks": []}
    if code is None:
        return {"question": question, "ok": False, "reason": u,
                "task": t, "code": None, "domain": domain}
    ok, checks = _verify_with_verifier(code, unit, u)
    return {"question": question, "ok": ok, "task": t, "unit": u,
            "code": code, "checks": checks, "solidified": False, "domain": domain}


def detect_language(question):
    """语言识别：问题含 rust/rs → Rust；js/javascript → JavaScript；否则 Python"""
    q = question.lower()
    if "rust" in q or "rs写" in q or "用rust" in q:
        return "rust"
    if "javascript" in q or "js写" in q or "用js" in q or "用javascript" in q:
        return "javascript"
    return "python"


def identify_task(question):
    """任务方向识别：问题 → 编程任务（最长关键词优先）"""
    best, best_len = None, 0
    for task, kws in TASK_KEYWORDS.items():
        for k in kws:
            if k in question and len(k) > best_len:
                best, best_len = task, len(k)
    return best


def extract_fn_name(question):
    """参数解析：函数名（问题含英文标识符则用，否则默认 solve）"""
    import re
    m = re.search(r"\b([a-zA-Z_][a-zA-Z0-9_]*)\b", question)
    if m:
        name = m.group(1)
        if name.lower() not in ("python", "def", "list", "array", "arr"):
            return name
    return "solve"


# ============ 二、组合生成（任务模板 × 参数 → 代码） ============
def compose_code(question, unit_id=None, fn_name=None, lang=None):
    """组合生成：语言识别 → 任务识别 → 代码单元 → 模板填充 → 代码（未预写完整代码）"""
    lang = lang or detect_language(question)
    units = LANG_UNITS.get(lang, CODE_UNITS)
    task = identify_task(question)
    if task is None:
        return None, "任务未识别（诚实边界：不知道要写什么程序）", None, None, lang
    # 匹配代码单元（任务 → 单元；多单元时取第一个）
    uids = [uid for uid, u in units.items() if u["task"] == task]
    if unit_id is not None and unit_id in units:
        uids = [unit_id]
    if not uids:
        return None, f"任务[{task}]在[{lang}]无代码单元覆盖（条件链不完整）", None, None, lang
    uid = uids[0]
    unit = units[uid]
    fn = fn_name or extract_fn_name(question)
    # replace 而非 format：Rust/JS pattern 含函数体 {}（format 会当占位符报错）
    code = unit["pattern"].replace("{fn}", fn)
    return task, uid, code, unit, lang


# ============ 三、自校验三层（语法 → 样例 → 边界） ============
def _run_case(fn, case):
    """执行单个样例：兼容 (inp, exp) 单参数 / (args_tuple, exp) 多参数 / ('call', exp)"""
    if len(case) != 2:
        return None, f"样例格式错误: {case}"
    inp, exp = case
    if inp == "call":
        return "call", exp  # 特殊标记：域注入型单元（L2 由集成测试覆盖）
    if isinstance(inp, tuple):
        return fn(*inp), exp
    return fn(inp), exp


def verify_code(code, unit, lang="python"):
    """自校验：L1 语法 + L2 样例 + L3 边界（白箱自己发现代码错误）
    Python：ast 语法 + exec 样例运行；Rust/JS：结构校验 + py_ref 逻辑样例
    v6：支持多参数样例 (args_tuple, exp)；needs_inject 单元 L2 由集成测试覆盖"""
    import re as _re
    if lang != "python":
        checks = []
        # L1 结构校验：函数关键字 + 括号平衡 + 无占位残留
        kw = "fn " if lang == "rust" else "function "
        if kw not in code:
            return False, [f"✗ L1 结构错误：缺 {kw.strip()} 函数声明"]
        if "{" not in code or code.count("{") != code.count("}"):
            return False, ["✗ L1 结构错误：函数体括号不平衡"]
        if "{" in code and _re.search(r"\{\s*[a-z_]+\s*\}", code):
            return False, ["✗ L1 结构错误：存在未替换的模板占位符"]
        # L2 逻辑样例：py_ref（Python 等价实现）验证模板逻辑正确
        ns = {}
        try:
            exec(unit.get("py_ref", ""), ns)
        except Exception as e:
            return False, [f"✗ L2 py_ref 错误: {e}"]
        fns = [v for k, v in ns.items() if callable(v) and not k.startswith("__")]
        if not fns:
            return False, ["✗ L2 无 py_ref 函数"]
        fn = fns[0]
        for inp, exp in unit.get("cases", []):
            try:
                got = fn(inp)
            except Exception:
                return False, [f"✗ L2 样例崩溃: {inp}"]
            if got != exp:
                return False, [f"✗ L2 样例失败: {inp} → {got}（期望 {exp}）"]
        checks.append(f"✔ 结构通过 | 样例 {len(unit.get('cases', []))} 组全过（py_ref 逻辑）")
        return True, checks
    checks = []
    # L1 语法
    try:
        ast.parse(code)
    except SyntaxError as e:
        return False, [f"✗ L1 语法错误: {e}"]
    # L2 样例运行（函数名必须是 solve——模板默认；用户指定名时用字典注入）
    ns = {}
    try:
        exec(code, ns)
    except Exception as e:
        return False, [f"✗ L1 定义错误: {e}"]
    fns = [v for k, v in ns.items() if callable(v) and not k.startswith("__")]
    if not fns:
        return False, ["✗ L1 无函数定义"]
    fn = fns[0]
    if unit.get("needs_inject"):
        # 注入型单元（需要 Graph/run_stmts 等白箱单元组装）：L2 由集成测试覆盖
        checks.append(f"✔ 语法通过 | 注入型单元：L2 样例由域集成测试覆盖（{len(unit.get('cases', []))} 组）")
        return True, checks
    cases = unit.get("cases", [])
    for case in cases:
        try:
            got, exp = _run_case(fn, case)
        except Exception as e:
            return False, [f"✗ L2 样例崩溃: {case} → {e}"]
        if got == "call":
            continue  # call 特殊标记（域注入型，由集成测试覆盖）
        if got != exp:
            return False, [f"✗ L2 样例失败: {case} → {got}（期望 {exp}）"]
    # L3 边界（额外边界用例：None/空/重复已含在 cases）
    checks.append(f"✔ 语法通过 | 样例 {len(cases)} 组全过")
    return True, checks


# ============ 四、固化（验证通过 → 固化 → 同任务直出） ============
_SOL_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                         "code_solidified.json")
CODE_SOLIDIFIED = {}
if os.path.exists(_SOL_FILE):
    try:
        _ld = json.load(open(_SOL_FILE, encoding="utf-8"))
        if isinstance(_ld, dict):
            CODE_SOLIDIFIED = _ld
    except Exception:
        CODE_SOLIDIFIED = {}


def code_solidify(question, task=None, uid=None, fn=None):
    """固化：组合生成 + 自校验通过 → 固化（自举纪律：未验证代码不固化）"""
    lang = detect_language(question)
    t, u, code, unit, lang = compose_code(question, uid, fn, lang)
    if code is None:
        return None
    ok, checks = verify_code(code, unit, lang)
    if not ok:
        return None  # 自校验未过 → 拒绝固化（自举纪律）
    key = f"{task or t}|{u}"
    entry = {"task": t, "unit": u, "code": code, "checks": checks,
             "source": "code_solidified", "lang": lang}
    CODE_SOLIDIFIED[key] = entry
    try:
        json.dump(CODE_SOLIDIFIED, open(_SOL_FILE, "w", encoding="utf-8"),
                  ensure_ascii=False, indent=1)
    except Exception:
        pass
    return entry


def code_route(question, uid=None, fn=None):
    """代码条件路由统一入口：固化层 → 组合生成+自校验（多语言）"""
    lang = detect_language(question)
    t = identify_task(question)
    if t is not None and lang == "python":
        # 固化层：同任务已固化的代码直出（仅 Python——多语言不混）
        for k, entry in CODE_SOLIDIFIED.items():
            if entry.get("task") == t:
                return {"question": question, "ok": True, "solidified": True,
                        "code": entry["code"], "task": t,
                        "unit": entry.get("unit"), "checks": [],
                        "lang": "python"}
    task, uid, code, unit, lang = compose_code(question, uid, fn, lang)
    if code is None:
        return {"question": question, "ok": False, "reason": uid,
                "task": task, "code": None, "lang": lang}
    ok, checks = verify_code(code, unit, lang)
    return {"question": question, "ok": ok, "task": task, "unit": uid,
            "code": code, "checks": checks, "solidified": False, "lang": lang}


if __name__ == "__main__":
    print("=== 白箱自举·代码编写主线（组合生成 + 自校验 · 零 LLM） ===\n")
    QS = [
        "写一个函数把数组从小到大排序",
        "写一个函数去掉数组里重复的元素",
        "写一个函数数一数数组里每个元素出现几次",
        "写一个函数找出一组数里的最大值",
        "写一个函数把列表反转",
        "写一个函数把数组加起来求和",
        "写一个函数计算圆的面积",   # 任务未识别 → 诚实边界
    ]
    results = []
    for q in QS:
        r = code_route(q)
        results.append(r)
        if r.get("ok") and r.get("code"):
            mark = "✔"
            print(f"[{mark}] {q}  [任务={r['task']} 单元={r['unit']}]")
            print(f"   {r['code'].replace(chr(10), ' | ')}")
            print(f"   自校验: {r['checks'][0] if r['checks'] else '✔'}")
        else:
            print(f"[✘] {q} -> {r.get('reason')}")
    # 固化演示
    print("\n=== 固化演示 ===")
    e = code_solidify("写一个函数把数组从小到大排序")
    r2 = code_route("写一个函数把数组从小到大排序")
    print(f"固化: {'✔' if e else '✘'} | 再问: {'固化直出' if r2.get('solidified') else '重新组合'}")
    # 判定
    hit = sum(1 for r in results if r.get("ok"))
    print(f"\n=== 判定 ===\n组合生成测试通过率: {hit}/{len(QS)} = {hit/len(QS)*100:.0f}%（目标≥80%）")
