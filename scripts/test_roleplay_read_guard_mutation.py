# -*- coding: utf-8 -*-
"""scripts/test_roleplay_read_guard_mutation.py · issue #490 守卫的定点变异自证。

对 src/lib/roleplay_web.ts 逐臂注入缺陷（或撤前端头 / 过度收紧），运行
test/roleplay_read_guard.test.ts，要求**指定断言恰好转红**；每臂结束字节级还原。
环境依赖：node_modules/tsx（npm ci 安装）；缺失时打印 SKIP 行并退 0。
"""
import os
import subprocess
import sys

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_SRC = os.path.join(_REPO, "src", "lib", "roleplay_web.ts")

_AUTH = chr(10).join([
    "                    if (!requireEditKey(req)) {",
    "                        res.writeHead(403, { 'Content-Type': 'application/json; charset=utf-8' });",
    "                        res.end(JSON.stringify({ ok: false, error: editKeyHint() }));",
    "                        return;",
    "                    }",
])

_ARMS = [
    ("M1", chr(10).join([
        "                    // issue #490：读端点与写面同款 fail-closed 鉴权——本面返回三导入",
        "                    // 私有正文/完整转录/翻译表，默认部署不得对任意本机客户端裸奔。",
        _AUTH,
        "                    const role = decodeURIComponent(url.pathname.split('/')[4]);",
    ]),
     "                    const role = decodeURIComponent(url.pathname.split('/')[4]);",
     "items 应 403"),
    ("M2", chr(10).join([
        "                    // issue #490：读端点鉴权（翻译表属私有数据）。",
        _AUTH,
        "                    const role = url.searchParams.get('role_id') || 'protocol-guide';",
        "                    const settings = readTransSettings();",
    ]),
     "                    const role = url.searchParams.get('role_id') || 'protocol-guide';" + chr(10)
     + "                    const settings = readTransSettings();",
     "translate 应 403"),
    ("M3", chr(10).join([
        "                    // issue #490：读端点鉴权（完整对话转录属私有数据）。",
        _AUTH,
        "                    const role = url.searchParams.get('role_id') || 'protocol-guide';",
        "                    // P1 完善（会话隔离）：按客户端实例读各自转录",
    ]),
     "                    const role = url.searchParams.get('role_id') || 'protocol-guide';" + chr(10)
     + "                    // P1 完善（会话隔离）：按客户端实例读各自转录",
     "history 应 403"),
    ("M4",
     "const r = await fetch('/roleplay/api/translate?role_id=' + encodeURIComponent(role), { headers: apiHeaders() }).then(x => x.json());",
     "const r = await fetch('/roleplay/api/translate?role_id=' + encodeURIComponent(role)).then(x => x.json());",
     "前端读请求须带 apiHeaders"),
    ("M5",
     "                if (req.method === 'GET' && url.pathname === '/roleplay/api/roles') {",
     "                if (req.method === 'GET' && url.pathname === '/roleplay/api/roles') {" + chr(10) + _AUTH,
     "/roleplay/api/roles 对照仍应 200"),
]


def _run_test():
    r = subprocess.run(
        ["node", "--import", "tsx", "--test", "test/roleplay_read_guard.test.ts"],
        cwd=_REPO, capture_output=True, text=True, encoding="utf-8",
        errors="replace", timeout=600)
    return r.returncode, (r.stdout or "") + (r.stderr or "")


def main():
    if not os.path.isdir(os.path.join(_REPO, "node_modules", "tsx")):
        print("[SKIP] node_modules/tsx 不存在——先 npm ci（本件守卫需 tsx 运行 TS 测试）")
        return 0
    rc, out = _run_test()
    if rc != 0:
        print("[FAIL] 基线（修复态）测试未通过：" + chr(10) + out[-2000:])
        return 1
    with open(_SRC, "rb") as fh:
        orig = fh.read()
    red = 0
    try:
        for mid, old, new, needle in _ARMS:
            text = orig.decode("utf-8")
            nl = "\r\n" if "\r\n" in text else "\n"
            norm = text.replace("\r\n", "\n")
            if norm.count(old) != 1:
                print("[ANCHOR-MISS] %s：锚点命中 %d 次（期望 1）" % (mid, norm.count(old)))
                return 2
            with open(_SRC, "wb") as fh:
                fh.write(norm.replace(old, new).replace("\n", nl).encode("utf-8"))
            rc2, out2 = _run_test()
            if rc2 != 0 and needle in out2:
                print("[MUTATE-OK]   %s：指定断言转红（%s）" % (mid, needle))
            else:
                print("[MUTATE-FAIL] %s：期望断言转红（%s），实际 rc=%s" % (mid, needle, rc2))
                print(out2[-1600:])
                red += 1
            with open(_SRC, "wb") as fh:
                fh.write(orig)
    finally:
        with open(_SRC, "wb") as fh:
            fh.write(orig)
    print("反证结果：%d 条变异，%s" % (len(_ARMS), "全部恰好命中" if red == 0 else "%d 条未命中" % red))
    return 1 if red else 0


if __name__ == "__main__":
    sys.exit(main())
