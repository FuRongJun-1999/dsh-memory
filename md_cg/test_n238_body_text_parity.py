# -*- coding: utf-8 -*-
"""N238 · `_body_text` 剥除判据须与 CCG 形态单点同源（冒号可有可无）。

运行：python -m md_cg.test_n238_body_text_parity

缺陷（本会话实跑复现）：
  `consistency._body_text` 的本地判据是「以 `#` 开头**且含冒号**」——
  无冒号形态的六要素（`# 不适用条件` + 换行 + 值行）不满足该条件，标题行
  与**值行**双双残留正文。后果：同一条内容
    带冒号 `# 不适用条件：不得把甲当作乙` → `_body_text == ''`、不命中；
    无冒号 `# 不适用条件` + `不得把甲当作乙` → body 含该短语 ⇒
    `_ban_hit(body, neg)` 恒 True ⇒ self_negation / conflict_strength=1.0
    ⇒ verdict=REJECT（writepipe 的 auto_flywheel 下合法节点被拦入
    review_queue 并自动建飞轮工单）。
  「冒号可有可无」已由单点 `nodefile._ccg_heading_rest` / `ccg_mark_present` /
  `ccg_field_value` 定案（`test_ccg_form_parity` 验收），本处是漏网的分叉。

修法：`_body_text` 复用单点判据，剥「标题行在即已声明」的**整段字段**——
行内带值（冒号式/前缀式）只剥该行；裸标题连同其后首个非空、非标题行
（值行，口径同 `nodefile.ccg_field_value`）一并剥除。

本套断言（纯行为，不做源码文本匹配）：
 ① 三种书写形态的声明段一律剥净（`_body_text == ''`），且判定结论同值
 ② 判别力自证：禁令短语真出现在**正文**时仍命中 self_negation（不同形态各测）
 ③ 值行剥除的边界（紧跟标题不吞／隔空行取值行／行内冒号不误剥后文）
 ④ 逐要素 × 逐形态机械对拍：只声明该要素 + 一行正文 ⇒ `_body_text == 正文`
 ⑤ 飞轮侧证据：合法无冒号节点不再触发 auto_flywheel 建单；真自否定仍触发
"""
from __future__ import annotations

import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from md_cg import consistency, nodefile

PASS = FAIL = 0
FAILS = []


# 生效条件：cond 为真时 PASS 加 1 并打印 [PASS]，否则 FAIL 加 1、把 label 记入 FAILS 并打印 [FAIL]。
def ok(cond, label):
    global PASS, FAIL
    if cond:
        PASS += 1
        print("  [PASS] %s" % label)
    else:
        FAIL += 1
        FAILS.append(label)
        print("  [FAIL] %s" % label)


MARKS = nodefile.CCG_MARKS                      # 六要素（真源，不另抄一份）
VALS = {"功能名": "测试条目", "生效条件": "载体/位置：本地源码仓；时间：全时窗",
        "子功能": "演示", "执行": "步骤一", "验证方式": "test",
        "不适用条件": "不得把甲当作乙"}


# 生效条件：form 取 "colon"／"bare"／"mixed"，返回按该形态书写的六要素声明段；
def decls(form: str) -> str:
    out = []
    for i, m in enumerate(MARKS):
        v = VALS[m]
        use_colon = (form == "colon") or (form == "mixed" and i % 2 == 0)
        out.append("# %s：%s\n" % (m, v) if use_colon else "# %s\n%s\n" % (m, v))
    return "".join(out)


class _CG:
    """最小 cg 替身：空索引（无从比对 ⇒ 判定只看新节点自身）+ 飞轮计数。"""

    def __init__(self, root):
        self.index = {"nodes": {}}
        self.root = root
        self.flywheel_calls = []

    def flywheel_step(self, payload):
        self.flywheel_calls.append(payload)
        return {"unresolved_id": "unr_test_%d" % len(self.flywheel_calls)}


def main() -> int:
    tmp = tempfile.mkdtemp()

    print("== ① 三种形态的声明段一律剥净，且判定结论同值 ==")
    verdicts = {}
    for form in ("colon", "bare", "mixed"):
        body = consistency._body_text(decls(form))
        ok(body == "", "①%s：_body_text 剥净（得到 %r）" % (form, body))
        cg = _CG(tmp)
        rec = consistency.check(cg, decls(form), log_write=False)
        verdicts[form] = (rec["verdict"], rec["conflict_strength"],
                          tuple((c["type"], c["score"]) for c in rec["conflicts"]))
        ok(not rec["conflicts"] and rec["conflict_strength"] == 0.0,
           "①%s：无硬冲突、strength=0.0（%s）" % (form, verdicts[form][:2]))
    ok(len(set(verdicts.values())) == 1,
       "①同内容三形态判定结论一致（%s）" % (verdicts,))

    print("== ② 判别力自证：禁令短语真在正文时仍判 self_negation ==")
    for form in ("colon", "bare", "mixed"):
        real = decls(form) + "本流程说明：不得把甲当作乙，否则告警。\n"
        body = consistency._body_text(real)
        ok(consistency._ban_hit(body, ["不得把甲当作乙"]),
           "②%s：正文残留行命中禁令短语" % form)
        rec = consistency.check(_CG(tmp), real, log_write=False)
        ok(rec["verdict"] == "REJECT" and rec["conflict_strength"] == 1.0
           and any(c["type"] == "self_negation" for c in rec["conflicts"]),
           "②%s：仍判 REJECT/self_negation/1.0（%s）"
           % (form, (rec["verdict"], rec["conflict_strength"])))

    print("== ③ 值行剥除的边界 ==")
    s = "# 功能名\n# 生效条件：x\n"
    ok(consistency._body_text(s) == "" and nodefile.ccg_field_value(s, "功能名") == "",
       "③裸标题后紧跟另一标题：值空、不吞下一要素")
    s = "# 执行\n\n真实值行\n后文行\n"
    ok(consistency._body_text(s) == "后文行\n"
       and nodefile.ccg_field_value(s, "执行") == "真实值行",
       "③裸标题后隔空行取值行：剥值行、留后文（与取值单点同口径）")
    s = "# 生效条件：条件A\n正文第一行\n正文第二行\n"
    ok(consistency._body_text(s) == "正文第一行\n正文第二行\n",
       "③行内冒号式：后续正文不被误剥")
    ok(consistency._body_text("") == "", "③空正文 → 空串")

    print("== ④ 逐要素 × 逐形态机械对拍（只声明该要素 + 一行正文）==")
    line = "正文一行\n"
    for form in ("colon", "bare", "mixed"):
        for i, m in enumerate(MARKS):
            v = VALS[m]
            use_colon = (form == "colon") or (form == "mixed" and i % 2 == 0)
            one = ("# %s：%s\n" % (m, v)) if use_colon else ("# %s\n%s\n" % (m, v))
            got = consistency._body_text(one + line)
            ok(got == line, "④%s「%s」：剥净该要素段（得到 %r）" % (form, m, got))

    print("== ⑤ 飞轮侧证据：合法无冒号节点不再自动建单 ==")
    cg_ok = _CG(tmp)
    rec = consistency.check(cg_ok, decls("bare"), auto_flywheel=True, log_write=False)
    ok(rec["verdict"] != "REJECT" and not cg_ok.flywheel_calls,
       "⑤合法无冒号节点：verdict=%s、flywheel_step 调用 %d 次（须 0，无工单）"
       % (rec["verdict"], len(cg_ok.flywheel_calls)))
    cg_bad = _CG(tmp)
    consistency.check(cg_bad, decls("bare") + "本流程说明：不得把甲当作乙。\n",
                      auto_flywheel=True, log_write=False)
    ok(len(cg_bad.flywheel_calls) == 1,
       "⑤真自否定仍建单：flywheel_step 调用 1 次（判别力未削弱）")

    print()
    print("ccg_body_text_n238: PASS=%d FAIL=%d" % (PASS, FAIL))
    if FAILS:
        print("FAILS: " + "; ".join(FAILS))
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
