# -*- coding: utf-8 -*-
"""md_cg · #224/#222 token_store 透传与 schemastery 依赖形态的静态守卫

缺陷背景（PR #316 值守审阅拆分件③，返工重放）：
  · #224-① 租户不透传：cordis.yml 的 mdcg.tenant 设为非 default 时，自动签发
    令牌不带 tenant ⇒ md_cg 每次启动以退出码 3 拒启。修法：resolveToken 的
    分派处（src/index.ts）透传 config.mdcg.tenant，issueToken 对非 default
    租户追加 `--tenant`（md_cg/tokens.py issue 子命令确有该参数）。
  · #224-② config.env 不读：经 config.env 设 MDCG_AUX_ROOT 时密钥环路径
    不跟随。修法：auxRoot/defaultKeyringPath 接受 envOverride，分派处透传
    config.env；优先级「显式参数 > config.env > 进程 env > 缺省」与
    MDCG_TOKEN 的既有解析顺序同构。
  · #224-③ 密钥环不复核：令牌吊销后旧令牌被原样复用 ⇒ 插件永久拒启。修法：
    新增 verifyToken()（`python -m md_cg.tokens verify --token`，退出码 0=
    有效 / 2=TokenError 拒绝），resolveToken 复用密钥环令牌前先复核；
    「invalid」清环重签，「unverifiable」（校验器自身没跑成）不清环也不
    带病返回（fail-closed）。
  · #222 @deepseek-ai/schemastery 从 optional peerDependencies 移入
    dependencies：旧形态（optional peer + 入口静态 import）在干净安装下
    npm 不自动装 optional peer ⇒ ESM 解析不到 ⇒ 整包不可加载。值守另点名
    旧提交删掉了文件末尾换行——本守卫一并钉住。

守卫形态：**静态源码断言**（不加载 TS 运行时）——本机值守环境无已验证
node/pnpm 工具链的假设下仍可跑；若仓库 node_modules 内有本地 typescript
（`npm install --ignore-scripts` 即可得），追加一条**可选执行守卫**跑
`tsc --noEmit -p tsconfig.json`（退出码必须 0），编译器缺席则 SKIP 注明。

  [G1] package.json：可解析；dependencies 含 @deepseek-ai/schemastery；
       peerDependenciesMeta 与 peerDependencies 均不再含它（#222）。
  [G2] package.json：以换行结尾（值守点名的回归——旧提交删过末尾换行）。
  [G3] src/lib/token_store.ts：ResolveTokenOptions 含 tenant/envOverride 字段；
       auxRoot/defaultKeyringPath 接受 envOverride 且读 MDCG_AUX_ROOT；
       issueToken 的 spawn 参数表含「非 default 才传 --tenant」形态；
       verifyToken 导出存在且调 `tokens verify --token`；resolveToken 里
       密钥环令牌先复核（verifyToken(opts.python, fromRing)）、失效清环
       （clearKeyring）、签发调用透传 opts.tenant、密钥环路径经
       defaultKeyringPath(opts.envOverride)。
  [G4] src/index.ts：resolveToken({...}) 分派**调用点**附近（截取后 600
       字符）同时含 tenant: config.mdcg.tenant 与 envOverride: config.env；
       另钉启动日志同口径（auxRoot(config.env) / defaultKeyringPath(config.env)）。
  [G5] （可选，编译器在场才跑）tsc --noEmit 退出码 0。

运行：python -X utf8 -m md_cg.test_issue224_token_store_static_guard
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PKG = os.path.join(REPO, "package.json")
TOKEN_STORE = os.path.join(REPO, "src", "lib", "token_store.ts")
INDEX = os.path.join(REPO, "src", "index.ts")
TSC_JS = os.path.join(REPO, "node_modules", "typescript", "bin", "tsc")
TSC_TIMEOUT_S = 300

PASS = FAIL = SKIP = 0
FAILS = []


def check(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  [PASS] {name}" + (f" · {detail}" if detail else ""))
    else:
        FAIL += 1
        FAILS.append(f"{name} · {detail}" if detail else name)
        print(f"  [FAIL] {name}" + (f" · {detail}" if detail else ""))


def _read_text(path: str) -> str:
    with open(path, encoding="utf-8") as f:
        # CRLF/LF 归一：断言只关心源码形态，不关心行尾风格
        return f.read().replace("\r\n", "\n")


def main() -> int:
    print("=" * 68)
    print("#224/#222 token_store 透传 + schemastery 依赖形态（静态守卫）")
    print("=" * 68)

    # ---------- [G1] package.json：schemastery 移入 dependencies（#222） ----------
    print("\n[G1] package.json：dependencies 含 schemastery，peer 面不再含")
    try:
        with open(PKG, encoding="utf-8") as f:
            pkg_raw = f.read()
        pkg = json.loads(pkg_raw)
    except (OSError, ValueError) as e:
        check("[G1] package.json 可解析为 JSON 对象", False, repr(e))
        return _summary()
    check("[G1] package.json 可解析为 JSON 对象", isinstance(pkg, dict))
    deps = pkg.get("dependencies") or {}
    check("[G1] dependencies 含 @deepseek-ai/schemastery（#222：optional peer ⇒ 整包不可加载）",
          isinstance(deps.get("@deepseek-ai/schemastery"), str),
          f"dependencies={deps!r}")
    check("[G1] peerDependenciesMeta 不再含 @deepseek-ai/schemastery",
          "@deepseek-ai/schemastery" not in (pkg.get("peerDependenciesMeta") or {}))
    check("[G1] peerDependencies 不再含 @deepseek-ai/schemastery",
          "@deepseek-ai/schemastery" not in (pkg.get("peerDependencies") or {}))

    # ---------- [G2] package.json 末尾换行（值守点名的回归） ----------
    print("\n[G2] package.json 以换行结尾（旧提交 b4d8af8 删过末尾换行）")
    check("[G2] 文件末字节为换行（\\n 或 \\r\\n）",
          pkg_raw.endswith("\n"),
          f"末 8 字节={pkg_raw[-8:]!r}")

    # ---------- [G3] token_store.ts 源码形态（#224 三子缺陷） ----------
    print("\n[G3] src/lib/token_store.ts：tenant 透传 / envOverride / verifyToken")
    ts = _read_text(TOKEN_STORE)
    check("[G3] ResolveTokenOptions 含 tenant?: string（#224-①）",
          "  tenant?: string" in ts)
    check("[G3] ResolveTokenOptions 含 envOverride?: Record<...>（#224-②）",
          "envOverride?: Record<string, string | undefined>" in ts)
    check("[G3] auxRoot 接受 envOverride 且读 config 侧 MDCG_AUX_ROOT（#224-②）",
          "export function auxRoot(envOverride?" in ts
          and "envOverride?.MDCG_AUX_ROOT" in ts)
    check("[G3] defaultKeyringPath 接受 envOverride 并经 auxRoot(envOverride)（#224-②）",
          "export function defaultKeyringPath(envOverride?" in ts
          and "join(auxRoot(envOverride), 'token')" in ts)
    check("[G3] issueToken spawn 参数表含「非 default 才传 --tenant」形态（#224-①）",
          "tenant && tenant !== 'default' ? ['--tenant', tenant] : []" in ts)
    check("[G3] verifyToken 导出存在且调 `tokens verify --token`（#224-③）",
          "export function verifyToken(python: string, token: string)" in ts
          and "'verify', '--token', token" in ts)
    check("[G3] verifyToken 三态含 unverifiable（校验器没跑成不许清环）",
          "'unverifiable'" in ts and "if (r.error) return 'unverifiable'" in ts)
    check("[G3] resolveToken 复用密钥环令牌前先复核（#224-③）",
          "verifyToken(opts.python, fromRing)" in ts
          and "clearKeyring(keyringPath)" in ts)
    check("[G3] resolveToken 密钥环路径经 defaultKeyringPath(opts.envOverride)（#224-②）",
          "opts.keyringPath ?? defaultKeyringPath(opts.envOverride)" in ts)
    check("[G3] issueToken 调用透传 opts.tenant（#224-①）",
          "issueToken(opts.python, role, actor, clearance, opts.tenant)" in ts)

    # ---------- [G4] index.ts 分派点透传 ----------
    print("\n[G4] src/index.ts：resolveToken 分派点透传 tenant/envOverride")
    idx = _read_text(INDEX)
    pos = idx.find("resolveToken({")
    check("[G4] resolveToken({...}) 分派点在场", pos >= 0)
    if pos >= 0:
        site = idx[pos:pos + 600]           # 只认分派调用点，不认别处同名形态
        check("[G4] 分派点透传 tenant: config.mdcg.tenant（#224-①）",
              "tenant: config.mdcg.tenant," in site, f"调用点片段={site[:220]!r}")
        check("[G4] 分派点透传 envOverride: config.env（#224-②）",
              "envOverride: config.env," in site)
    check("[G4] 启动日志同口径：auxRoot(config.env) / defaultKeyringPath(config.env)",
          "auxRoot(config.env)" in idx and "defaultKeyringPath(config.env)" in idx)

    # ---------- [G5] 可选执行守卫：tsc --noEmit（编译器缺席则 SKIP） ----------
    print("\n[G5] TypeScript 编译面（可选：仓库本地 typescript 在场才跑）")
    node = shutil.which("node")
    if node and os.path.isfile(TSC_JS):
        try:
            r = subprocess.run([node, TSC_JS, "--noEmit", "-p", "tsconfig.json"],
                               cwd=REPO, capture_output=True, text=True,
                               encoding="utf-8", timeout=TSC_TIMEOUT_S)
            check("[G5] tsc --noEmit -p tsconfig.json 退出码 0", r.returncode == 0,
                  f"rc={r.returncode} stderr={(r.stderr or r.stdout or '')[-300:]!r}")
        except (OSError, subprocess.TimeoutExpired) as e:
            check("[G5] tsc --noEmit -p tsconfig.json 退出码 0", False, repr(e))
    else:
        global SKIP
        SKIP += 1
        print("  [SKIP] [G5] 本机无 node 或仓库 node_modules/typescript 缺席"
              "（npm install --ignore-scripts 可得）——编译面按 SKIP 记录，"
              "不判失败；G1–G4 静态断言不受影响。")

    return _summary()


def _summary() -> int:
    print("\n" + "=" * 68)
    print(f"PASS={PASS}  FAIL={FAIL}  SKIP={SKIP}")
    if FAILS:
        print("失败项：" + "；".join(FAILS))
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
