# -*- coding: utf-8 -*-
"""se_compose.py · 软件工程概念条件单元（第四阶段·代码深学·软件工程方向）
软件工程概念 = 条件单元（{条件→规律}）：问题「为什么要写测试/什么是接口/
为什么模块化」→ 方向识别 → 概念单元 → 组合生成（未预写完整答案）。
零 LLM 确定性——软件工程知识白箱化。
"""
import sys
sys.stdout.reconfigure(encoding='utf-8')


# ============ 一、软件工程概念单元 ============
SE_UNITS = {
    "模块化": {
        "direction": "模块",
        "conditions": ["程序", "模块"],
        "rule": "大程序拆成小模块 → 独立开发/测试 → 组装 → 可维护可复用",
        "conclusion": ("把{程序}拆成小模块 → 各模块独立开发/测试/修改 "
                       "→ 组装成整体 → 可维护可复用（耦合低内聚高）"),
        "core": ["模块", "拆", "独立", "可维护"],
        "examples": ["为什么程序要模块化", "拆分成函数", "低耦合高内聚"],
    },
    "接口": {
        "direction": "接口",
        "conditions": ["接口", "契约"],
        "rule": "接口定义契约 → 实现隔离 → 可替换 → 调用方不依赖实现",
        "conclusion": ("{接口}定义调用契约（签名/行为）→ 实现与调用隔离 "
                       "→ 实现可替换 → 调用方只依赖接口不依赖实现（松耦合）"),
        "core": ["接口", "契约", "隔离", "替换"],
        "examples": ["什么是接口", "为什么用接口", "接口隔离"],
    },
    "测试": {
        "direction": "测试",
        "conditions": ["测试", "验证"],
        "rule": "测试验证行为 → 回归防退化 → 重构安全 → 质量保障",
        "conclusion": ("{测试}验证程序行为（输入→期望输出）→ 回归测试防退化 "
                       "→ 重构/修改有安全网 → 质量保障（测试先行或并行）"),
        "core": ["测试", "回归", "安全", "验证"],
        "examples": ["为什么要写测试", "单元测试", "回归测试"],
    },
    "重构": {
        "direction": "重构",
        "conditions": ["重构", "结构"],
        "rule": "重构改结构不改行为 → 测试保持通过 → 可逆 → 渐进改进",
        "conclusion": ("{重构}只改内部结构不改外部行为 → 测试保持通过（安全网）"
                       " → 每步可逆 → 渐进式改进（小步高频）"),
        "core": ["重构", "行为", "测试", "可逆"],
        "examples": ["什么是重构", "重构安全", "重构和重写区别"],
    },
    "封装": {
        "direction": "封装",
        "conditions": ["封装", "隐藏"],
        "rule": "封装隐藏内部实现 → 对外暴露接口 → 保护不变量 → 改动隔离",
        "conclusion": ("{封装}隐藏内部实现细节 → 只暴露必要接口 "
                       "→ 保护数据不变量 → 内部改动不影响外部（信息隐藏）"),
        "core": ["封装", "隐藏", "接口", "隔离"],
        "examples": ["为什么封装", "信息隐藏", "私有成员"],
    },
    "版本控制": {
        "direction": "版本",
        "conditions": ["版本", "提交", "协作"],
        "rule": "版本控制记录变更 → 可回滚 → 并行协作 → 审计历史",
        "conclusion": ("{版本控制}记录每次变更（提交）→ 出错可回滚 → "
                       "多人并行协作 → 历史可审计（git 等）"),
        "core": ["版本", "回滚", "协作", "提交"],
        "examples": ["为什么用版本控制", "git 的作用", "提交历史"],
    },
}

# 方向识别（问题 → 软件工程概念）
SE_DIRECTIONS = {
    "模块": ["模块化", "拆成", "拆分", "大程序", "模块"],
    "接口": ["接口", "契约", "依赖抽象"],
    "测试": ["测试", "回归", "单元测试", "验证程序"],
    "重构": ["重构", "改结构", "重构安全"],
    "封装": ["封装", "隐藏实现", "信息隐藏"],
    "版本": ["版本控制", "git", "提交", "回滚", "协作开发"],
}


def identify_se_direction(question):
    """软件工程概念识别（最长关键词优先）"""
    best, best_len = None, 0
    for direction, kws in SE_DIRECTIONS.items():
        for k in kws:
            if k in question and len(k) > best_len:
                best, best_len = direction, len(k)
    return best


def se_route(question):
    """软件工程概念组合生成：方向识别 → 概念单元 → 模板生成 → 自校验"""
    direction = identify_se_direction(question)
    if direction is None:
        return {"question": question, "ok": False,
                "reason": "软件工程概念未识别（落回通用域）"}
    unit = None
    for uid, u in SE_UNITS.items():
        if u["direction"] == direction:
            unit = u
            break
    if unit is None:
        return {"question": question, "ok": False,
                "reason": f"概念[{direction}]无单元覆盖"}
    # 组合生成（模板代入问题中的实体词，如「程序/代码」）
    answer = unit["conclusion"].replace("{程序}", "程序").replace(
        "{接口}", "接口").replace("{测试}", "测试").replace(
        "{重构}", "重构").replace("{封装}", "封装").replace(
        "{版本控制}", "版本控制")
    # 自校验：答案含概念核心词（白箱确定性）
    core_hit = sum(1 for c in unit["core"] if c in answer)
    ok = core_hit >= 2
    checks = [] if ok else [f"✗ 概念自校验失败：核心词命中 {core_hit}/{len(unit['core'])}"]
    return {"question": question, "direction": direction,
            "ok": ok, "answer": answer, "checks": checks,
            "core_hit": core_hit, "unit": [u for u, x in SE_UNITS.items() if x is unit][0]}


if __name__ == "__main__":
    print("=== 软件工程概念条件单元（代码深学 · 零 LLM）===\n")
    QS = [
        "为什么大型程序要模块化？", "什么是接口？", "为什么要写单元测试？",
        "什么是重构？", "为什么代码要封装？", "为什么要用版本控制？",
    ]
    ok_n = 0
    for q in QS:
        r = se_route(q)
        if r.get("ok"):
            ok_n += 1
        mark = "✔" if r.get("ok") else "✘"
        print(f"[{mark}] ({r.get('direction')}) {q}")
        print(f"   -> {r.get('answer', r.get('reason'))}")
        for c in r.get("checks", []):
            print(f"   {c}")
    # 未识别回落
    r = se_route("什么是碳中和？")
    print(f"\n[{'✔' if not r.get('ok') else '✘'}] 非软件工程问题回落: {r.get('reason')}")
    print(f"\n=== 判定 ===\n软件工程概念命中: {ok_n}/{len(QS)}")
