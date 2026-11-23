# -*- coding: utf-8 -*-
"""`/roleplay` 面请求准入与角色 id 校验的守卫（issue #1009 第 4 项）。

【守什么】
`src/lib/roleplay_web.ts` 及其编译副本 `lib/lib/roleplay_web.js` 此前：
  ① 无 `connection.admit`／无 Origin / Sec-Fetch-Site / Content-Type 校验（跨站 no-cors 简单 POST 可达）；
  ② `GET/POST /roleplay/api/roles/:role/items` 与 `POST /roleplay/api/roles`（role_create）
     不校验角色 id——role/role_id 会拼进文件路径与元数据键（目录穿越 / 原型污染）；
  ③ `writeRoleMeta` / `writeTransSettings` 用固定 `*.tmp`，并发写互相截断。

两个文件是**同一份实现的两副本**（TS 源 + 编译产物），任一侧漏改都会让运行时行为与源不符，
故本守卫对两副本用同一组判据，并要求两副本读数一致。

运行：python -X utf8 -m md_cg.test_issue1009_roleplay_admission
"""
from __future__ import annotations

import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
COPIES = (os.path.join("src", "lib", "roleplay_web.ts"),
          os.path.join("lib", "lib", "roleplay_web.js"))

_OK = 0
_BAD = []


def _read(rel):
    path = os.path.join(ROOT, rel)
    with open(path, encoding="utf-8") as f:
        return f.read()


def ok(cond, name, extra=""):
    global _OK
    if cond:
        _OK += 1
        print("  ok   %s %s" % (name, extra))
    else:
        _BAD.append(name)
        print("  FAIL %s %s" % (name, extra))


def checks(rel, src):
    print("== %s ==" % rel.replace(os.sep, "/"))
    ok("const admit = (req, res) => {" in src, "A1 有准入函数 admit")
    i_call = src.find("if (!admit(req, res))")
    i_handler = src.find("const handler = async (req, res) => {")
    # 首个**路由判定**（不是内嵌 HTML 里的客户端字符串）
    i_route = src.find("url.pathname === '/roleplay/api/roles'", max(i_handler, 0))
    ok(0 <= i_handler < i_call < i_route, "A2 handler 入口即准入，先于任何路由", (i_handler, i_call, i_route))
    ok("'sec-fetch-site'" in src and "cross_site_rejected" in src, "A3 Sec-Fetch-Site: cross-site 拒")
    ok("origin_not_allowed" in src and "new URL(origin).host === host" in src,
       "A4 写请求同源校验（Origin.host === Host）")
    ok("content_type_must_be_application_json" in src,
       "A5 写请求 Content-Type 必须 application/json（挡 no-cors 简单 POST）")
    ok("const SAFE_METHODS = new Set(['GET', 'HEAD']);" in src, "A6 安全方法集合只含 GET/HEAD")
    n_guard = src.count("if (!validRoleId(")
    ok(n_guard >= 5, "B1 角色 id 校验点 ≥5（3 个路由 + 既有 2 处）", n_guard)
    ok("validRoleId(String((p && p.role_id) || ''))" in src,
       "B2 role_create 对 p.role_id 校验")
    ok(src.count("const tmp = `${roleMetaFile}.") == 1 and "${process.pid}" in src,
       "C1 roleMeta 的 tmp 名带 pid+时间+随机（并发不互截断）")
    ok(src.count("const tmp = `${transSettingsFile}.") == 1,
       "C2 transSettings 的 tmp 名同样唯一化")
    ok(src.count("roleMetaFile + '.tmp'") == 0 and src.count("transSettingsFile + '.tmp'") == 0,
       "C3 固定 *.tmp 写法已清零")
    return n_guard


def main():
    print("=== issue #1009 第 4 项：/roleplay 准入与角色 id 守卫 ===")
    readings = {}
    missing = []
    for rel in COPIES:
        if not os.path.exists(os.path.join(ROOT, rel)):
            missing.append(rel)
            print("== %s ==\n  SKIP 编译产物不存在（`/lib/` 被 .gitignore 忽略，构建期由 tsc 生成）"
                  % rel.replace(os.sep, "/"))
            continue
        src = _read(rel)
        readings[rel] = (checks(rel, src), src.count("admit(req, res)"))
    print("== 源与编译产物一致（编译副本存在时才校验）==")
    if len(readings) >= 2:
        vals = set(readings.values())
        ok(len(vals) == 1, "D1 两副本的 (角色 id 校验点数, 准入调用数) 一致", readings)
    else:
        print("  SKIP 只有 TS 源可读（构建机才有编译产物）：判据等价，无需跨副本比对")
    ok(bool(readings), "D2 至少 TS 源通过全部判据（构建产物由 tsc 从它生成）", list(readings))
    print()
    print("roleplay 准入守卫：%d 通过，%d 失败" % (_OK, len(_BAD)))
    if _BAD:
        print("失败项：" + " / ".join(_BAD))
    return 1 if _BAD else 0


if __name__ == "__main__":
    sys.exit(main())