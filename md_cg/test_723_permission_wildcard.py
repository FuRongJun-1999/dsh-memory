# -*- coding: utf-8 -*-
# 功能名：前端 permissionNote 与服务端 _in_scope 的通配符判据一致性守卫（issue #723）
# 生效条件：python -X utf8 -m md_cg.test_723_permission_wildcard；被测面＝ui/minimal/payload/web/app.js 与 md_cg/security.py
# 子功能：
#   A. 服务端 `_in_scope` 认通配符 `*`（`"*" in allow or name in allow`）——这是**权威口径**
#   B. 前端 `permissionNote` 必须同样认 `*`（否则全权令牌 12/12 全部误报「未声明权限」）
#   C. 跨侧一致：两侧都必须处理 `*`，缺任一侧即红
# 执行：纯文本/源码断言，不建库、不写盘
# 验证方式：全部 PASS exit 0；每条注明「怎么让它红」
# 不适用条件：**不做浏览器端运行验证**（只断言源码口径）；不覆盖 `web/app.js`（那是构建产物，gitignore 排除，由源生成）
"""issue #723 的守卫。

用户报告：全权令牌（`ops_allow: ["*"]`）下，前端 12/12 预设全部误报「未声明 xx 权限」，
而服务端裁定照常放行——**同一份数据两侧判据不同口径**。

根因：服务端 `_in_scope` 写的是 `"*" in allow or name in allow`（认通配符），
前端 `permissionNote` 写的是 `allowed.includes(op)`（不认通配符）。

本守卫防的是「一侧改了、另一侧没跟上」——**跨侧口径一致性**，与 `test_rust_fold_parity` 同族。
"""
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

_PASS, _FAIL = [], []


def ok(cond, msg, detail=""):
    (_PASS if cond else _FAIL).append(msg)
    print(("  PASS " if cond else "  FAIL ") + msg + (("  <- " + str(detail)) if detail and not cond else ""))


def _read(rel):
    p = os.path.join(ROOT, rel.replace("/", os.sep))
    with open(p, encoding="utf-8") as f:
        return f.read()


def main():
    print("== A 服务端：_in_scope 认通配符（权威口径）")
    sec = _read("md_cg/security.py")
    ok('"*" in allow' in sec,
       "A1 security.py 的 _in_scope 含 `\"*\" in allow`（权威口径认通配符）",
       "未找到该判据")

    print("== B 前端：permissionNote 必须同样认通配符")
    js = _read("ui/minimal/payload/web/app.js")
    m = re.search(r"function\s+permissionNote\s*\(op\)\s*\{(.*?)\n\s*\}", js, re.S)
    ok(m is not None, "B1 能在 app.js 里定位到 permissionNote 函数体")
    body = m.group(1) if m else ""
    ok("'*'" in body or '"*"' in body,
       "B2 permissionNote 函数体里出现通配符 `*` 的判断（怎么让它红：删掉 `includes('*')` 这一支）",
       body[:160])
    ok("includes(" in body and "op" in body,
       "B3 仍保留 `includes(op)` 的具体操作判定（通配符不是替代，是补充）",
       body[:160])

    print("== C 跨侧一致：两侧都必须处理 *")
    ok(("*" in sec) and (("*" in body) if body else False),
       "C1 服务端与前端**同时**认通配符（任一侧缺失即红）",
       {"server": '"*" in allow' in sec, "frontend": "'*'" in body if body else False})

    print("== D 反例：不认通配符的旧写法必须被判红")
    legacy = "return allowed && !allowed.includes(op) ?"
    ok(legacy not in js,
       "D1 app.js 里已不存在旧写法 `!allowed.includes(op)`（怎么让它红：改回旧写法）",
       "仍存在旧写法")

    print()
    print("issue #723 守卫：%d 通过 / %d 失败" % (len(_PASS), len(_FAIL)))
    if _FAIL:
        for f in _FAIL:
            print("  -", f)
    return 0 if not _FAIL else 1


if __name__ == "__main__":
    raise SystemExit(main())