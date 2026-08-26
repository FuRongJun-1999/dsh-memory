# -*- coding: utf-8 -*-
"""诊断：TypeScript 问题为什么返回重复文本——检查 encode 命中哪个 REVERSE_DAILY 键"""
import sys
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, r"C:\Users\FuRongJun\AppData\Local\Programs\Python\Python310\lib\site-packages")
sys.path.insert(0, r"D:\Program Files\2_ai\CommonTrustProtocol\aeis\wisdom")

try:
    import semantic_translate as st
    print("semantic_translate 导入 OK")
except Exception as e:
    print("导入失败:", e)
    sys.exit(1)

# 1. encode 结果
for q in ["TypeScript 是什么", "什么是 TypeScript", "TypeScript 和 JavaScript 什么区别"]:
    print(f"\n=== {q} ===")
    try:
        fp = st.encode(q)
        print("encode:", fp)
        # 哪些是 REVERSE_DAILY 键
        hits = [t for t in fp if t in st.REVERSE_DAILY]
        print("REVERSE_DAILY 命中:", hits)
        for h in hits:
            print(f"  '{h}' → {st.REVERSE_DAILY[h][:150]}...")
    except Exception as e:
        print("encode 异常:", e)

# 2. REVERSE_DAILY 里有没有 TypeScript 相关键
print("\n=== REVERSE_DAILY 键总数:", len(st.REVERSE_DAILY))
ts_keys = [k for k in st.REVERSE_DAILY if "Type" in k or "type" in k.lower() or "JS" in k or "Java" in k]
print("Type/JS/Java 相关键:", ts_keys)
for k in ts_keys[:5]:
    print(f"  '{k}': {st.REVERSE_DAILY[k][:120]}...")
