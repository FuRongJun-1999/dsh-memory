#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""灵枢 · 原子级中英序列化器

语义原子（中文）→ 标准英文原子序列
不是翻译，是原子的一对一映射。每个中文原子有唯一英文原子对应。

用法：
    from zh_en_atoms import serialize
    result = serialize("我昨天吃牛肉")
    # → "i yester day eat cow meat"

    result = serialize("灵枢记忆库")
    # → "soul hub memory store"
"""
import re

ZH_EN = {}

def M(zh, en):
    ZH_EN[zh] = en

# ---- 代词 ----
for zh, en in [("我","i"),("你","you"),("他","he"),("她","she"),("我们","we"),("他们","they")]:
    M(zh, en)

# ---- 动作（基形，无时态）----
for zh, en in [("吃","eat"),("喝","drink"),("看","see"),("听","hear"),("读","read"),
               ("写","write"),("走","walk"),("跑","run"),("飞","fly"),("来","come"),
               ("去","go"),("买","buy"),("卖","sell"),("说","speak"),("想","think"),
               ("开","open"),("关","close"),("睡","sleep"),("爱","love"),("做","do"),
               ("学","study"),("教","teach"),("用","use"),("找","find"),("给","give")]:
    M(zh, en)

# ---- 时间（复合→原子序列）----
M("昨天", "yester day"); M("今天", "to day"); M("明天", "next day"); M("现在", "now")
for zh, en in [("年","year"),("月","month"),("日","day"),("天","day"),("周","week"),
               ("时","hour"),("分","minute"),("秒","second"),
               ("春","spring"),("夏","summer"),("秋","autumn"),("冬","winter"),
               ("早","morning"),("晚","evening"),("夜","night")]:
    M(zh, en)

# ---- 数 ----
for zh, en in [("一","one"),("二","two"),("三","three"),("四","four"),("五","five"),
               ("六","six"),("七","seven"),("八","eight"),("九","nine"),("十","ten"),
               ("百","hundred"),("千","thousand"),("零","zero")]:
    M(zh, en)

# ---- 自然 ----
for zh, en in [("牛","cow"),("猪","pig"),("羊","sheep"),("鸡","chicken"),("鸭","duck"),
               ("马","horse"),("狗","dog"),("猫","cat"),("鱼","fish"),("鸟","bird"),
               ("肉","meat"),("奶","milk"),("蛋","egg"),("水","water"),("火","fire"),
               ("山","mountain"),("海","sea"),("河","river"),("树","tree"),("花","flower"),
               ("光","light"),("电","electric"),("风","wind"),("雨","rain"),("雪","snow"),
               ("星","star"),("石","stone"),("云","cloud"),("土","soil"),("金","metal")]:
    M(zh, en)

# ---- 身体 ----
for zh, en in [("头","head"),("手","hand"),("脚","foot"),("眼","eye"),("口","mouth"),
               ("耳","ear"),("鼻","nose"),("心","heart"),("血","blood"),("骨","bone"),("皮","skin")]:
    M(zh, en)

# ---- 亲属 ----
for zh, en in [("父","father"),("母","mother"),("兄","elder_brother"),("弟","younger_brother"),
               ("姐","elder_sister"),("妹","younger_sister"),("儿","son"),("女","daughter")]:
    M(zh, en)

# ---- 器物 ----
for zh, en in [("车","vehicle"),("船","boat"),("机","machine"),("刀","knife"),("笔","pen"),
               ("书","book"),("门","door"),("窗","window"),("桥","bridge"),("路","road"),
               ("池","cell")]:
    M(zh, en)

# ---- 形容词 ----
for zh, en in [("大","big"),("小","small"),("高","high"),("低","low"),("新","new"),("旧","old"),
               ("好","good"),("坏","bad"),("长","long"),("短","short"),("快","fast"),("慢","slow"),
               ("热","hot"),("冷","cold"),("多","many"),("少","few"),("重","heavy"),("轻","light"),
               ("深","deep"),("真","true")]:
    M(zh, en)

# ---- 抽象 ----
for zh, en in [("知识","knowledge"),("工作","work"),("纪律","discipline"),("记忆","memory"),
               ("认知","cognition"),("力","force"),("气","gas"),("道","way"),("理","principle"),
               ("文","text"),("化","transform"),("话","speech"),("影","shadow"),("音","sound"),
               ("名","name"),("国","country"),("家","home"),("城","city"),("民","people"),
               ("字","word"),("灵","soul"),("枢","hub"),("数","number"),("物","thing"),
               ("地","earth"),("人","person"),("脑","brain"),("视","view"),("脏","organ"),
               ("汽","gas"),("魂","soul")]:
    M(zh, en)

# ---- 复合词（→ 原子序列）----
for zh, en in [("电脑","electric brain"),("电话","electric speech"),("电视","electric view"),
               ("电影","electric shadow"),("电池","electric cell"),("火车","fire vehicle"),
               ("汽车","gas vehicle"),("飞机","fly machine"),("手机","hand machine"),
               ("牛肉","cow meat"),("猪肉","pig meat"),("羊肉","sheep meat"),
               ("鸡肉","chicken meat"),("牛奶","cow milk"),("鸡蛋","chicken egg"),
               ("火山","fire mountain"),("海水","sea water"),("月光","moon light"),
               ("雪山","snow mountain"),("知识图谱","knowledge graph map"),
               ("认知图","cognition graph"),("工作纪律","work discipline"),
               ("记忆库","memory store"),("灵枢","soul hub"),
               ("数学","number study"),("化学","transform study"),
               ("物理学","thing principle study"),("生物学","living thing study"),
               ("地理学","earth principle study"),("热力学","heat force study")]:
    M(zh, en)

# ---- 贪心最长匹配 ----
_sorted = sorted(ZH_EN.keys(), key=len, reverse=True)

def segment(text):
    """贪心最长匹配：文本 → 原子列表"""
    result = []
    pos = 0
    while pos < len(text):
        matched = False
        for key in _sorted:
            if text.startswith(key, pos):
                result.append(key)
                pos += len(key)
                matched = True
                break
        if not matched:
            result.append(text[pos])
            pos += 1
    return result


def serialize(text):
    """中文文本 → 标准英文原子序列"""
    return " ".join(ZH_EN.get(a, "[" + a + "]") for a in segment(text))


if __name__ == "__main__":
    import sys
    q = " ".join(sys.argv[1:]) if len(sys.argv) > 1 else "灵枢记忆库"
    print("中文:", q)
    print("标准英文:", serialize(q))
