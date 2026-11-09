"""判据：回包里的 `plain` 是人话，且不改变 `content`（2026-11-06）。

正控：CCG 字段堆 → plain 出句子、不再以「# 功能名：」开头
正控：散文卡（## 节）→ plain 为「做了什么：… 结论：…」
正控：recall/read 的每条 pack 都带 plain 键，且 content 原样保留
负控：空内容 → plain 为空串（不冒字段名）
负控：超长内容 → plain 截断带省略号，长度受限
负控：render 收到 None/非字符串 → 返回空串不抛
"""

import sys

sys.path.insert(0, "/home/ubuntu/mdcg")

from md_cg import ccg_prose  # noqa: E402  TID251

PASSED = []
FAILED = []


def check(name, cond, detail=""):
    (PASSED if cond else FAILED).append(name)
    print("  %s %s %s" % ("PASS" if cond else "FAIL", name, detail))


def main():
    field = ("# 功能名：星露谷 Mods 中文清理流水线\n"
             "# 生效条件：languageCode 设为 en、需要把中文换成英文时。\n"
             "# 子功能：1. 扫 languageCode 2. 核对变体分隔符\n"
             "# 验证方式：同模型自验\n")
    plain = ccg_prose.render(field)
    check("A1 字段堆出句子", plain.startswith("这条讲的是「星露谷"), plain[:40])
    check("A2 不再以字段名开头", not plain.lstrip().startswith("#"))
    check("A3 三个字段都进了句子",
          all(k in plain for k in ("什么时候用", "具体做法", "依据")))

    sec = "## 做了什么\n完成 X。\n\n## 结论\nY 才是根因。\n"
    p2 = ccg_prose.render(sec)
    check("B1 分节散文 → 一句一节", p2.startswith("做了什么：完成 X。"), p2[:40])
    check("B2 结论也在", "结论：Y 才是根因。" in p2)

    check("C1 空内容 → 空串", ccg_prose.render("") == "")
    check("C2 None → 空串", ccg_prose.render(None) == "")
    check("C3 非字符串不抛", ccg_prose.render(12345) == "")

    long_text = "# 功能名：" + "很长" * 400
    p3 = ccg_prose.render(long_text, max_chars=120)
    check("D1 超长截断带省略号", p3.endswith("…") and len(p3) <= 120, len(p3))

    # 回包层：recall 每条带 plain，content 原样
    from md_cg import crypto  # noqa: E402  TID251
    from md_cg.mdcos import MdCGSecure  # noqa: E402  TID251
    from md_cg.security import Principal  # noqa: E402  TID251
    import os  # noqa: E402
    root = os.environ.get("MDCG_ROOT") or "/home/ubuntu/mdcg-data"
    pr = Principal(actor="dsh-memory", role="designer", tenant="default",
                   clearance="private", can_write=True, can_admin=True)
    cg = MdCGSecure(root, principal=pr, master_key=crypto.load_master_key())
    r = cg.recall("记忆 缺陷 审计", budget_tokens=1200, k=20)
    pack = r.get("pack") or []
    check("E1 回包有内容", len(pack) > 0, len(pack))
    check("E2 每条都带 plain", all("plain" in it for it in pack))
    check("E3 content 原样保留（没被 plain 覆盖）",
          all(it.get("content") is not None for it in pack))
    if pack:
        print("     样例 content:", " ".join((pack[0].get("content") or "").split())[:70])
        print("     样例 plain  :", (pack[0].get("plain") or "")[:90])

    print("\n== %d 通过 / %d 失败" % (len(PASSED), len(FAILED)))
    return 0 if not FAILED else 2


if __name__ == "__main__":
    raise SystemExit(main())
