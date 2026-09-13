# -*- coding: utf-8 -*-
"""build_standard_en.py · 英文标准库构建器（语素表 + 词条 → standard_en.json）

词条语素带显式英文注 (zh_morph, en_gloss)，规避单字歧义（月=month/moon、生=person/living）。
构建即验证：标准英文必须等于语素英文的 snake_case 直拼。
"""
import collections
import json, io, os, re

MORPHEMES = {}
def M(zh, en):
    MORPHEMES[zh] = en

# 动物
for zh, en in [("牛","cow"),("猪","pig"),("羊","sheep"),("鸡","chicken"),("鸭","duck"),("马","horse"),("狗","dog"),("猫","cat"),("鱼","fish"),("鸟","bird")]:
    M(zh, en)
# 食
for zh, en in [("肉","meat"),("奶","milk"),("蛋","egg"),("米","rice"),("菜","vegetable"),("果","fruit"),("油","oil"),("盐","salt"),("糖","sugar"),("茶","tea"),("酒","wine"),("水","water")]:
    M(zh, en)
# 时间
for zh, en in [("年","year"),("月","month"),("日","day"),("天","day"),("周","week"),("期","period"),("时","hour"),("分","minute"),("秒","second"),("春","spring"),("秋","autumn"),("冬","winter"),("夏","summer"),("今","this"),("明","next"),("去","past")]:
    M(zh, en)
# 数
for zh, en in [("一","one"),("二","two"),("三","three"),("四","four"),("五","five"),("六","six"),("七","seven"),("八","eight"),("九","nine"),("十","ten"),("百","hundred"),("千","thousand")]:
    M(zh, en)
# 亲
for zh, en in [("父","father"),("母","mother"),("兄","elder_brother"),("弟","younger_brother"),("姐","elder_sister"),("妹","younger_sister"),("儿","son"),("女","daughter")]:
    M(zh, en)
# 身
for zh, en in [("头","head"),("手","hand"),("脚","foot"),("眼","eye"),("口","mouth"),("耳","ear"),("鼻","nose"),("心","heart"),("血","blood"),("骨","bone"),("皮","skin"),("脏","organ")]:
    M(zh, en)
# 自然
for zh, en in [("山","mountain"),("水","water"),("火","fire"),("土","soil"),("木","wood"),("金","metal"),("光","light"),("电","electric"),("风","wind"),("雨","rain"),("雪","snow"),("星","star"),("海","sea"),("河","river"),("石","stone"),("云","cloud"),("月","moon")]:
    M(zh, en)
# 器
for zh, en in [("车","vehicle"),("船","boat"),("机","machine"),("器","device"),("刀","knife"),("笔","pen"),("书","book"),("门","door"),("窗","window"),("桥","bridge"),("路","road"),("池","cell")]:
    M(zh, en)
# 动（基形）
for zh, en in [("走","walk"),("来","come"),("看","see"),("听","listen"),("吃","eat"),("喝","drink"),("说","speak"),("读","read"),("写","write"),("买","buy"),("卖","sell"),("学","study"),("教","teach"),("做","make"),("跑","run"),("飞","fly"),("睡","sleep"),("想","think"),("爱","love"),("用","use"),("开","open"),("关","close")]:
    M(zh, en)
# 形
for zh, en in [("大","big"),("小","small"),("高","high"),("低","low"),("新","new"),("旧","old"),("好","good"),("坏","bad"),("长","long"),("短","short"),("快","fast"),("慢","slow"),("热","hot"),("冷","cold"),("多","many"),("少","few"),("重","heavy"),("轻","light"),("深","deep")]:
    M(zh, en)
# 抽象
for zh, en in [("力","force"),("气","gas"),("道","way"),("理","principle"),("文","text"),("化","transform"),("话","speech"),("影","shadow"),("音","sound"),("名","name"),("国","country"),("家","home"),("城","city"),("王","king"),("民","people"),("军","army"),("医","medicine"),("药","drug"),("病","disease"),("课","lesson"),("题","question"),("工","work"),("师","master"),("律","law"),("图","graph"),("谱","map"),("数","number"),("物","thing"),("地","earth"),("人","person"),("脑","brain"),("视","view")]:
    M(zh, en)
# 多字语素（化石词 / 复合单位）
for zh, en in [("星期","week"),("经济","economy"),("逻辑","logic"),("沙发","sofa"),("咖啡","coffee"),("巧克力","chocolate"),("知识","knowledge"),("工作","work"),("纪律","discipline"),("记忆","memory"),("认知","cognition"),("月光","moon_light"),("十二","twelve"),("兄弟","brothers"),("姐妹","sisters"),("汽","gas")]:
    M(zh, en)

# 词条：(zh, [(语素, 英文注)...], 标准英文, legacy 别名, class)
E = []
DEFAULT_CLS = "compositional"


def A(zh, glosses, std, legacy, cls=DEFAULT_CLS):
    E.append((zh, glosses, std, legacy, cls))

# 食物（语素直拼）
A("牛肉", [("牛","cow"),("肉","meat")], "cow_meat", ["beef"])
A("猪肉", [("猪","pig"),("肉","meat")], "pig_meat", ["pork"])
A("羊肉", [("羊","sheep"),("肉","meat")], "sheep_meat", ["mutton"])
A("鸡肉", [("鸡","chicken"),("肉","meat")], "chicken_meat", ["chicken"])
A("鸭肉", [("鸭","duck"),("肉","meat")], "duck_meat", [])
A("牛奶", [("牛","cow"),("奶","milk")], "cow_milk", ["milk"])
A("鸡蛋", [("鸡","chicken"),("蛋","egg")], "chicken_egg", ["egg"])
A("牛肉面", [("牛","cow"),("肉","meat"),("面","noodle")], "cow_meat_noodle", [])
# 时间
A("月份", [("月","month")], "month", [], "compositional")          # 份=名物化后缀，剔
A("一月", [("一","one"),("月","month")], "one_month", ["January"])
A("二月", [("二","two"),("月","month")], "two_month", ["February"])
A("三月", [("三","three"),("月","month")], "three_month", ["March"])
A("十二月", [("十二","twelve"),("月","month")], "twelve_month", ["December"])
A("星期一", [("星期","week"),("一","one")], "week_one", ["Monday"])
A("星期日", [("星期","week"),("日","sun")], "week_sun", ["Sunday"])
A("今天", [("今","this"),("天","day")], "this_day", ["today"])
A("明天", [("明","next"),("天","day")], "next_day", ["tomorrow"])
A("今年", [("今","this"),("年","year")], "this_year", [])
A("明年", [("明","next"),("年","year")], "next_year", [])
A("去年", [("去","past"),("年","year")], "past_year", ["last year"])
A("春天", [("春","spring")], "spring", ["spring"])                  # 天=季节后缀，剔
A("冬天", [("冬","winter")], "winter", ["winter"])
# 家庭
A("父亲", [("父","father")], "father", ["father"])                  # 亲=亲缘标记，剔
A("母亲", [("母","mother")], "mother", ["mother"])
A("兄弟", [("兄弟","brothers")], "brothers", ["brothers"], "compositional")  # 复数是语义本身
A("姐妹", [("姐妹","sisters")], "sisters", ["sisters"], "compositional")
A("儿子", [("儿","son")], "son", ["son"])
A("女儿", [("女","daughter")], "daughter", ["daughter"])
# 身体
A("眼睛", [("眼","eye")], "eye", ["eye"])                          # 睛=瞳，并入 eye
A("心脏", [("心","heart"),("脏","organ")], "heart_organ", ["heart"])
# 自然
A("火山", [("火","fire"),("山","mountain")], "fire_mountain", ["volcano"])
A("海水", [("海","sea"),("水","water")], "sea_water", ["seawater"])
A("月光", [("月","moon"),("光","light")], "moon_light", ["moonlight"])
A("雪山", [("雪","snow"),("山","mountain")], "snow_mountain", ["snow mountain"])
# 科技
A("电脑", [("电","electric"),("脑","brain")], "electric_brain", ["computer"])
A("电话", [("电","electric"),("话","speech")], "electric_speech", ["telephone"])
A("电视", [("电","electric"),("视","view")], "electric_view", ["television"])
A("电影", [("电","electric"),("影","shadow")], "electric_shadow", ["movie", "film"])
A("电池", [("电","electric"),("池","cell")], "electric_cell", ["battery"])
A("火车", [("火","fire"),("车","vehicle")], "fire_vehicle", ["train"])
A("汽车", [("汽","gas"),("车","vehicle")], "gas_vehicle", ["car"])
A("飞机", [("飞","fly"),("机","machine")], "fly_machine", ["airplane"])
A("手机", [("手","hand"),("机","machine")], "hand_machine", ["mobile phone"])
# 学科
A("数学", [("数","number"),("学","study")], "number_study", ["mathematics"])
A("化学", [("化","transform"),("学","study")], "transform_study", ["chemistry"])
A("物理学", [("物","thing"),("理","principle"),("学","study")], "thing_principle_study", ["physics"])
A("地理学", [("地","earth"),("理","principle"),("学","study")], "earth_principle_study", ["geography"])
A("生物学", [("生","living"),("物","thing"),("学","study")], "living_thing_study", ["biology"])
A("热力学", [("热","heat"),("力","force"),("学","study")], "heat_force_study", ["thermodynamics"])
# 人物
A("医生", [("医","medicine"),("生","person")], "medicine_person", ["doctor"])
A("学生", [("学","study"),("生","person")], "study_person", ["student"])
A("律师", [("律","law"),("师","master")], "law_master", ["lawyer"])
A("工人", [("工","work"),("人","person")], "work_person", ["worker"])
# 领域词（认知图相关）
A("知识图谱", [("知识","knowledge"),("图","graph"),("谱","map")], "knowledge_graph_map", ["knowledge graph"])
A("认知图", [("认知","cognition"),("图","graph")], "cognition_graph", [])
A("工作纪律", [("工作","work"),("纪律","discipline")], "work_discipline", [])
A("记忆库", [("记忆","memory"),("库","store")], "memory_store", [])
# 化石词（音译/古典，稳定单语素，保留既有英文）
A("经济", [("经济","economy")], "economy", ["economy"], "opaque")
A("逻辑", [("逻辑","logic")], "logic", ["logic"], "opaque")
A("沙发", [("沙发","sofa")], "sofa", ["sofa"], "opaque")
A("咖啡", [("咖啡","coffee")], "coffee", ["coffee"], "opaque")
A("巧克力", [("巧克力","chocolate")], "chocolate", ["chocolate"], "opaque")


def main():
    problems = []
    entries = []
    for zh, glosses, std, legacy, cls in E:
        join_zh = "".join(z for z, _ in glosses)
        if not zh.startswith(join_zh):
            problems.append("%s: 语素拼合 %s != 词条 %s" % (zh, join_zh, zh))
            continue
        join_en = "_".join(e for _, e in glosses)
        if join_en != std:
            problems.append("%s: 标准英文 %s != 语素拼接 %s" % (zh, std, join_en))
            continue
        if re.search(r"[A-Z]", std):
            problems.append("%s: 标准英文含大写（违 snake_case）" % zh)
            continue
        entries.append({"zh": zh, "glosses": [{"zh": z, "en": e} for z, e in glosses],
                        "standard_en": std, "legacy_en": legacy, "class": cls})
    out = {
        "meta": {"name": "lingshu-standard-en", "version": "0.1.0", "rules": "RULES.md",
                 "note": "英文标准 = 中文语素序直拼（snake_case）；屈折归零；虚词不入名；音译化石词保留为 opaque；四问皆否不入库"},
        "morphemes": MORPHEMES,
        "entries": entries,
    }
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "standard_en.json")
    with io.open(path, "w", encoding="utf-8", newline="\n") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    cls_cnt = collections.Counter(e["class"] for e in entries)
    print("entries=%d morphemes=%d classes=%s problems=%d" % (
        len(entries), len(MORPHEMES), dict(cls_cnt), len(problems)))
    for p in problems:
        print("  !", p)
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
