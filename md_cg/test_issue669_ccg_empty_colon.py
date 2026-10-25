# -*- coding: utf-8 -*-
"""issue #669 守卫：CCG 要素行「带冒号空值 + 换行正文」必须在写入闸门被拒。

病象：取值面 ccg_field_value 只看冒号后同一行（得空串），剥除面 _strip_ccg_segments
见冒号算非空只剥标题行 ⇒ 列表项残留进 body ⇒ _ban_hit(body, neg) 命中自身声明残片
⇒ verdict=REJECT / conflicts.type=self_negation / score=1.0（假「条件自相矛盾」）。

本守卫钉住：①坏形态 fail-closed 且给出两种修法；②三种合法形态一律放行；
③合规单行（含真正不相交的负条件）不再产生 self_negation（阳性对照：真冲突仍 ctor 命中）。
"""
from __future__ import annotations

import tempfile

from .mdcg import MdCG


def main():
    ok = bad = 0

    def chk(cond, label):
        nonlocal ok, bad
        if cond:
            ok += 1
            print("  PASS", label)
        else:
            bad += 1
            print("  FAIL", label)

    cg = MdCG(tempfile.mkdtemp(prefix="f669_"))

    def try_add(cid, content):
        try:
            cg.add(cid, content, layer="knowledge")
            return None
        except ValueError as exc:
            return str(exc)

    # ---------- ① 坏形态：fail-closed + 两种修法都在文案里 ----------
    msg = try_add("bad1", "# 功能名：甲\n# 不适用条件：\n- 批量\n- 本人出镜")
    chk(msg is not None, "#669 带冒号空值 + 列表 → 写入被拒（fail-closed）")
    chk(msg is not None and "单行" in msg and "non_applicable_conditions" in msg,
        "#669 拒绝文案给出两种修法（单行 / frontmatter 列表）")
    chk(msg is not None and "第 2 行" in msg, "#669 文案点名具体行号")

    # ---------- ② 合法形态一律放行 ----------
    chk(try_add("good1", "# 功能名：甲\n# 不适用条件：批量；本人出镜") is None,
        "#669 带冒号单行（多项用；分隔）放行")
    chk(try_add("good2", "# 功能名：甲\n# 不适用条件\n批量；本人出镜") is None,
        "#669 裸标题 + 单行值（CCG 文档形态）放行")
    chk(try_add("good3", "# 功能名：甲\n# 不适用条件：\n# 执行：乙") is None,
        "#669 带冒号空值但紧跟下一要素（值为空）放行")

    # ---------- ③ 合规写法不再假 REJECT ----------
    from .consistency import check
    body = ("# 功能名：甲\n# 生效条件：用户问代码怎么写\n"
            "# 执行：给示例\n# 不适用条件：本人出镜；涉密材料")
    rec = check(cg, content=body, condition_space={"domain": "code"}, layer="knowledge")
    types = [c.get("type") for c in (rec.get("conflicts") or [])]
    chk("self_negation" not in types,
        "#669 合规单行（负条件与自身不相交）不再判 self_negation（实际 %s）" % (types,))

    print("=" * 56)
    print("issue #669 守卫：%d 通过 / %d 失败" % (ok, bad))
    return 0 if bad == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
