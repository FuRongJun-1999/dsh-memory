# -*- coding: utf-8 -*-
"""md_cg · 角色化读取视图（第四阶段 6.1，计划文档 §4）

【为什么】同一认知图对不同消费角色应呈现不同侧面：主代理要「结论与
修正历史」，验证端要「判据面与环境陷阱」，回执审计要「命令与预期输出」。
三者的候选资格不同，但都建立在同一节点集上——视图是读取面的资格过滤，
不是数据的第二副本（与超边的派生视图正交：超边是图结构增补，视图是
候选资格过滤；计划 §3）。

【设计】
  - ROLE_VIEWS：声明式规则表（唯一真源），每个 view 声明四维资格：
      content_kinds —— content_kind 必须落在集合内（None=不限）
      layers        —— layer 必须落在集合内（None=不限）
      roles         —— 非 None 时作为正向白名单（role 必须命中，
                       短路返回；receipt 用）
      include_work  —— False 时 role 落在工作角色（tool-output/
                       command/edit）即一票否决（与候选池默认
                       include_work=False 同口径）
  - matches(fm, view)：单点谓词。fm 接受扁平 entry 或 frontmatter
    字典（两者对 role/layer/content_kind 三键同名）。
  - 非法 view 一律 ValueError（fail-closed，不静默回落）——合法性
    判定单点在本模块；与节点缺字段 fail-open（缺 content_kind 按
    "text" 对待）是两回事，后者是读取面惯例。

【边界】
  - 零内部依赖（不 import 本包其它模块，防循环导入）。规则表内的
    工作角色白名单与 mdcos.WORK_ROLES 字面一致，一致性由
    test_role_views 守卫断言钉住（防两处漂移）。
  - 初版规则是类型启发，bench_role_views.py 的对照校准是法定修正
    通道（改规则必须复跑对照，计划 §7.3）。
"""

# 规则表内的工作角色白名单，字面与 mdcos.WORK_ROLES 保持一致
# （一致性由 test_role_views 守卫断言钉住，防两处漂移）。
_WORK_ROLES = ("tool-output", "command", "edit")

ROLE_VIEWS = {
    # 主代理视图：结论与修正历史（正文/工作结论落在 knowledge 层）
    "main": {
        "content_kinds": ("text", "work_done"),
        "layers": ("knowledge",),
        "roles": None,
        "include_work": False,
    },
    # 验证端视图：判据面与环境陷阱（marks 条目 + 知识正文，含 contextual）
    "verifier": {
        "content_kinds": ("ccg_marks", "text"),
        "layers": ("knowledge", "contextual"),
        "roles": None,
        "include_work": False,
    },
    # 回执审计视图：恰是默认候选池剔除的工作角色节点（include_work
    # 默认 False 的补集），roles 白名单短路命中即保留
    "receipt": {
        "content_kinds": None,
        "layers": None,
        "roles": _WORK_ROLES,
        "include_work": True,
    },
}


def views():
    """合法视图名（排序稳定，供错误信息与文档引用）。"""
    return tuple(sorted(ROLE_VIEWS))


def matches(fm, view):
    """节点元数据是否满足视图资格（单点谓词）。

    fm：扁平 entry 或 frontmatter 字典（role/layer/content_kind 同名键）。
    view：ROLE_VIEWS 键之一；非法值 ValueError（fail-closed）。
    """
    spec = ROLE_VIEWS.get(view)
    if spec is None:
        raise ValueError(
            "非法 view：%r（合法三值：%s）" % (view, ", ".join(views())))
    if spec["roles"] is not None:            # 正向白名单视图（receipt）
        return fm.get("role") in spec["roles"]
    ck = fm.get("content_kind")
    if spec["content_kinds"] is not None \
            and (ck or "text") not in spec["content_kinds"]:
        return False
    if spec["layers"] is not None \
            and fm.get("layer") not in spec["layers"]:
        return False
    if not spec["include_work"] and fm.get("role") in _WORK_ROLES:
        return False
    return True
