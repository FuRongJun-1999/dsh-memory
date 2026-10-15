# -*- coding: utf-8 -*-
"""md_cg · #224/#222/#368 token_store 透传＋verifyToken 三态守卫（静态＋运行时＋定点变异）

缺陷背景（PR #316 值守审阅拆分件③ → PR #368 技术审返工重放）：
  · #224-① 租户不透传：cordis.yml 的 mdcg.tenant 设为非 default 时，自动签发
    令牌不带 tenant ⇒ md_cg 每次启动以退出码 3 拒启。修法：resolveToken 的
    分派处（src/index.ts）透传 config.mdcg.tenant，issueToken 对非 default
    租户追加 `--tenant`（md_cg/tokens.py issue 子命令确有该参数）。
  · #224-② config.env 不读：经 config.env 设 MDCG_AUX_ROOT 时密钥环路径
    不跟随。修法：auxRoot/defaultKeyringPath 接受 envOverride，分派处透传
    config.env；优先级「显式参数 > config.env > 进程 env > 缺省」与
    MDCG_TOKEN 的既有解析顺序同构。
  · #224-③ 密钥环不复核：令牌吊销后旧令牌被原样复用 ⇒ 插件永久拒启。修法：
    新增 verifyToken()（`python -m md_cg.tokens verify --token`）三态复核。
  · #368 复核追加的三条必须项（值守端到端复现后判「需改后重提」）：
      必须 1（数据破坏回归）：旧判据「status 非 0 即 invalid」把退出码 1/3/127
        （校验器自身崩坏/拒启类守卫/解释器找不到）全当真拒绝 ⇒ resolveToken
        清环 ⇒ **仍有效的密钥环令牌被清空**（值守复现：环 46 字节 → 0）。
        tokens.py 退出码契约：**只有 2 是 TokenError**；0 成功；1 校验器崩坏。
        修法：`r.status === 2` 才 'invalid'，其余非零（1/3/127/null/超时）
        归 'unverifiable'（不动环）。
      必须 2（端到端仍不通）：issueToken/verifyToken 两个 spawn 的 env 没有
        config.env ⇒ MDCG_AUX_ROOT 只在 cordis.yml 设过时，环写去 X、签发
        记录仍落 ~/.mdcg——环/记录分居两处。修法：两个 spawn 都合并
        envOverride（configEnvOverlay）。
      必须 3（清环时序）：旧实现「先清后签」——签发失败就永久丢环。修法：
        删除 eager 清环（clearKeyring 整体退场），唯一覆写点是
        「新令牌签发成功后 writeKeyring」：签成功才替换，签失败原样保留。
  · #222 @deepseek-ai/schemastery 从 optional peerDependencies 移入
    dependencies（optional peer + 入口静态 import ⇒ 干净安装不自动装 ⇒
    整包不可加载）。

守卫三层（#368 应做 ①② 的落地）：
  静态组 [G1]–[G5]：源码/依赖形态断言（不加载 TS 运行时）。
    [G2] 是对**当前 package.json 末字节**的实检（endswith 换行）——不是对
    diff 形态的推断；#368 应做 ② 点名的恒真断言形态已废除，且 G2 现在也
    被变异自证覆盖（--mutate M5：剥掉末尾换行必须打红 [G2]）。
  运行时组 [R1]–[R14]：`node --import tsx` ＋ 仓内 .tmp 沙箱。沙箱拷贝
    src/lib/{token_store,datapath}.ts（datapath.repoRoot() 由 package.json
    锚定到沙箱 ⇒ PYTHONPATH 让 `-m md_cg.tokens` 解析到**假校验器**——
    按 FAKE_VERIFY_RC/FAKE_ISSUE_RC 控退出码、按 MDCG_AUX_ROOT /
    PROBE_DEFAULT_AUX 控记录落点），对**真 spawnSync 路径**取读数：
    R1–R5  verifyToken 三态（rc=0/2/1/3/127 → ok/invalid/unverifiable…unverifiable）
    R6     rc=0 ⇒ 密钥环令牌原样复用（source=keyring）
    R7–R9  rc=1/3/127 ＋签发失败 ⇒ 环 PRESERVED 且不带病复用（#368 必须 1 负控）
    R10    rc=2 ＋签发失败 ⇒ 环 PRESERVED（#368 必须 3：签发失败不丢环）
    R11    rc=2 ＋签发成功 ⇒ 环被**新令牌**覆写（签成功才替换）
    R12    MDCG_AUX_ROOT 只经 envOverride ⇒ 环与记录**同落 X**、子进程 rc=0
           （#368 必须 2 端到端）
    R13    FAKE_VERIFY_RC 只经 envOverride ⇒ 复核子进程吃得到 config.env
    R14    rc=1 ＋签发成功 ⇒ source=issued（unverifiable fail-closed，不带病复用）
    node / node_modules/tsx / python 任一缺席 ⇒ 整组 SKIP 注明（同 G5 口径）。
  --mutate：**真**定点变异自证。#368 应做 ① 点名旧版 --mutate 是空转（无
    argv 解析，--mutate 输出与 plain 逐字节相同）。现改为 in-place 变异
    （_MUTATIONS 表，逐条「改盘上源 → 复跑套件必须转红 → finally 还原」），
    变异后字节级还原（CRLF 保持）；全表跑完再整体复跑一次证明恢复绿。
    变异面覆盖 #368 三条必须项＋fail-open 对抗面＋G2：
      M1 必须 1 三态判据回退（status===2 → status!==0）      预期红 >= 3
      M2 必须 2 spawn env 不再合并 config.env（两处全撤）      预期红 >= 2
      M3 必须 3 清环回退为先清后签（ok 分支后插 eager 清环）    预期红 >= 1
      M4 unverifiable → fail-open（rc≠0/2 也当 ok 复用）       预期红 >= 1
      M5 G2 package.json 剥末尾换行                            预期红 >= 1

运行：python -X utf8 -m md_cg.test_issue224_token_store_static_guard [--mutate|--list]
"""
from __future__ import annotations

import contextlib
import io
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
TSX_DIR = os.path.join(REPO, "node_modules", "tsx")
TSC_TIMEOUT_S = 300
RUNTIME_TIMEOUT_S = 300
SANDBOX = os.path.join(REPO, ".tmp", "issue224_guard_sandbox")

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
    with open(path, encoding="utf-8", newline="") as f:
        # CRLF/LF 归一：断言只关心源码形态，不关心行尾风格
        return f.read().replace("\r\n", "\n")


# ============================================================ 运行时组材料

_FAKE_TOKENS_PY = '''# -*- coding: utf-8 -*-
# 守卫沙箱专用假 md_cg.tokens：被沙箱拷贝的 token_store 经 PYTHONPATH=repoRoot
# （=沙箱根）解析到本文件。verify 按 FAKE_VERIFY_RC 退出（未设→127）；
# issue 在 FAKE_ISSUE_RC=0/未设时把记录行追加到 <aux>/_tokens.json 并打印
# token_store 期望的签发 JSON（aux = MDCG_AUX_ROOT 或 PROBE_DEFAULT_AUX——
# 后者是「子进程没吃到 config.env 时记录会落哪」的安全替身，不碰真实家目录）。
import json
import os
import sys


def _aux_root():
    return (os.environ.get("MDCG_AUX_ROOT")
            or os.environ.get("PROBE_DEFAULT_AUX")
            or os.path.expanduser("~/.mdcg"))


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    if cmd == "verify":
        rc = os.environ.get("FAKE_VERIFY_RC")
        sys.stdout.write(json.dumps({"ok": True, "aux_root_seen": _aux_root()}))
        sys.stdout.flush()
        sys.exit(int(rc) if rc not in (None, "") else 127)
    if cmd == "issue":
        rc = os.environ.get("FAKE_ISSUE_RC")
        if rc not in (None, "", "0"):
            sys.stderr.write("fake issue failure rc=%s" % rc)
            sys.exit(int(rc))
        aux = _aux_root()
        os.makedirs(aux, exist_ok=True)
        with open(os.path.join(aux, "_tokens.json"), "a", encoding="utf-8") as f:
            f.write(json.dumps({"probe": True, "argv": sys.argv[1:]}) + "\\n")
        sys.stdout.write(json.dumps({
            "token": "mdcg1.probe.probe1.s3cr3tvalue",
            "token_id": "probe1",
            "aux_root_seen": aux,
        }))
        sys.stdout.flush()
        sys.exit(0)
    sys.stderr.write("fake md_cg.tokens: unsupported cmd %r argv=%r\\n" % (cmd, sys.argv))
    sys.exit(64)


sys.exit(main())
'''

_PROBE_MJS = '''// issue224 guard runtime probe: sandbox real spawnSync readings, one JSON per case.
import { mkdirSync, writeFileSync, readFileSync, existsSync, rmSync } from 'node:fs'
import { join, dirname } from 'node:path'
import { fileURLToPath, pathToFileURL } from 'node:url'

const SB = dirname(fileURLToPath(import.meta.url))
const ts = await import(pathToFileURL(join(SB, 'src', 'lib', 'token_store.ts')).href)
const PY = process.env.PROBE_PYTHON || 'python'
const T1 = 'mdcg1.designer.before1.S3cr3tvalueBeforeProbe'

function freshCase(n) {
  const dir = join(SB, 'case-' + n)
  rmSync(dir, { recursive: true, force: true })
  for (const sub of ['aux', 'homeaux', 'run']) mkdirSync(join(dir, sub), { recursive: true })
  process.env.PROBE_DEFAULT_AUX = join(dir, 'homeaux')
  process.env.MDCG_CHILD_CWD = join(dir, 'run')
  return { dir, aux: join(dir, 'aux'), homeaux: join(dir, 'homeaux'), ring: join(dir, 'aux', 'token') }
}
function cleanEnv() {
  for (const k of ['MDCG_TOKEN', 'MDCG_AUX_ROOT', 'MDCG_AUTO_ISSUE',
                   'FAKE_VERIFY_RC', 'FAKE_ISSUE_RC']) delete process.env[k]
}
function ringText(p) { try { return readFileSync(p, 'utf-8') } catch { return '<ABSENT>' } }
const out = []

for (const rc of [0, 1, 2, 3, 127]) {
  const c = freshCase('verify-rc' + rc); cleanEnv()
  process.env.FAKE_VERIFY_RC = String(rc)
  out.push({ case: 'verify-rc' + rc, rc: rc, actual: ts.verifyToken(PY, T1) })
}

function ringScenario(name, verifyRc, issueRc) {
  const c = freshCase(name); cleanEnv()
  writeFileSync(c.ring, T1 + '\\n', 'utf-8')
  process.env.FAKE_VERIFY_RC = String(verifyRc)
  if (issueRc !== null) process.env.FAKE_ISSUE_RC = String(issueRc)
  const res = ts.resolveToken({ python: PY, keyringPath: c.ring,
                                envOverride: { MDCG_AUX_ROOT: c.aux } })
  const after = ringText(c.ring)
  out.push({ case: name, verify_rc: verifyRc, issue_rc: issueRc, source: res.source,
             ring_after_len: after.length, ring_preserved: after === T1 + '\\n',
             ring_overwritten_with_new: after.trim() === 'mdcg1.probe.probe1.s3cr3tvalue',
             record_in_aux: existsSync(join(c.aux, '_tokens.json')),
             record_in_homeaux: existsSync(join(c.homeaux, '_tokens.json')) })
}
ringScenario('ring-rc0', 0, 1)
ringScenario('ring-rc1-issuefail', 1, 1)
ringScenario('ring-rc3-issuefail', 3, 1)
ringScenario('ring-rc127-issuefail', 127, 1)
ringScenario('ring-rc2-issuefail', 2, 1)
ringScenario('ring-rc2-issueok', 2, 0)

{
  const c = freshCase('envoverride-e2e'); cleanEnv()
  process.env.FAKE_ISSUE_RC = '0'
  const res = ts.resolveToken({ python: PY, envOverride: { MDCG_AUX_ROOT: c.aux } })
  out.push({ case: 'envoverride-e2e', keyringPath: res.keyringPath,
             keyring_in_aux: res.keyringPath.startsWith(c.aux),
             ring_written_in_aux: existsSync(join(c.aux, 'token')),
             record_in_aux: existsSync(join(c.aux, '_tokens.json')),
             record_in_homeaux: existsSync(join(c.homeaux, '_tokens.json')),
             source: res.source })
}
{
  // 复核侧 envOverride：FAKE_VERIFY_RC 只经 envOverride 传（假校验器未读到
  // 该键时按 127 退出）——吃得到则 verdict=ok ⇒ source=keyring。
  const c = freshCase('verify-envoverride'); cleanEnv()
  writeFileSync(c.ring, T1 + '\\n', 'utf-8')
  const res = ts.resolveToken({ python: PY, keyringPath: c.ring,
                                envOverride: { MDCG_AUX_ROOT: c.aux, FAKE_VERIFY_RC: '0' } })
  out.push({ case: 'verify-envoverride', source: res.source })
}
{
  const c = freshCase('unverifiable-failclosed'); cleanEnv()
  writeFileSync(c.ring, T1 + '\\n', 'utf-8')
  process.env.FAKE_VERIFY_RC = '1'   // 签发未设失败 ⇒ 成功
  const res = ts.resolveToken({ python: PY, keyringPath: c.ring,
                                envOverride: { MDCG_AUX_ROOT: c.aux } })
  out.push({ case: 'unverifiable-failclosed', source: res.source })
}
cleanEnv()
for (const r of out) console.log(JSON.stringify(r))
'''

_R_NUM = {}
_R_ORDER = [
    ("verify-rc0", "R1"), ("verify-rc1", "R2"), ("verify-rc2", "R3"),
    ("verify-rc3", "R4"), ("verify-rc127", "R5"), ("ring-rc0", "R6"),
    ("ring-rc1-issuefail", "R7"), ("ring-rc3-issuefail", "R8"),
    ("ring-rc127-issuefail", "R9"), ("ring-rc2-issuefail", "R10"),
    ("ring-rc2-issueok", "R11"), ("envoverride-e2e", "R12"),
    ("verify-envoverride", "R13"), ("unverifiable-failclosed", "R14"),
]


def _r_expect(rec):
    c = rec.get("case")
    if c.startswith("verify-rc"):
        rc = rec.get("rc")
        want = "ok" if rc == 0 else "invalid" if rc == 2 else "unverifiable"
        return rec.get("actual") == want, f"rc={rc} ⇒ {want}，实得 {rec.get('actual')!r}"
    if c == "ring-rc0":
        ok = rec.get("source") == "keyring" and rec.get("ring_preserved")
        return ok, f"期望 source=keyring 且环保留，实得 source={rec.get('source')!r}"
    if c in ("ring-rc1-issuefail", "ring-rc3-issuefail", "ring-rc127-issuefail"):
        ok = (rec.get("ring_preserved") and rec.get("source") != "keyring"
              and rec.get("ring_after_len") == 46)
        return ok, (f"#368 必须1负控：rc={rec.get('verify_rc')} ⇒ 环 PRESERVED"
                    f"(len={rec.get('ring_after_len')}) 且不带病复用"
                    f"(source={rec.get('source')!r})")
    if c == "ring-rc2-issuefail":
        ok = rec.get("ring_preserved") and rec.get("source") == "none"
        return ok, (f"#368 必须3：rc=2 且签发失败 ⇒ 环 PRESERVED"
                    f"(len={rec.get('ring_after_len')}, source={rec.get('source')!r})")
    if c == "ring-rc2-issueok":
        ok = rec.get("ring_overwritten_with_new") and rec.get("source") == "issued"
        return ok, (f"签发成功后才覆写：new={rec.get('ring_overwritten_with_new')}, "
                    f"source={rec.get('source')!r}")
    if c == "envoverride-e2e":
        ok = (rec.get("keyring_in_aux") and rec.get("ring_written_in_aux")
              and rec.get("record_in_aux") and not rec.get("record_in_homeaux")
              and rec.get("source") == "issued")
        return ok, (f"#368 必须2：环与记录须同落 X（keyring_in_aux="
                    f"{rec.get('keyring_in_aux')}, record_in_aux={rec.get('record_in_aux')}, "
                    f"record_in_homeaux={rec.get('record_in_homeaux')}, "
                    f"source={rec.get('source')!r}）")
    if c == "verify-envoverride":
        ok = rec.get("source") == "keyring"
        return ok, f"复核子进程吃得到 envOverride（否则 rc=127⇒落签发），实得 {rec.get('source')!r}"
    if c == "unverifiable-failclosed":
        ok = rec.get("source") == "issued"
        return ok, f"unverifiable 不带病复用（期望 issued），实得 {rec.get('source')!r}"
    return False, f"未知用例 {c!r}"


def _prepare_sandbox() -> None:
    shutil.rmtree(SANDBOX, ignore_errors=True)
    for sub in (os.path.join("src", "lib"), "md_cg", "case"):
        os.makedirs(os.path.join(SANDBOX, sub), exist_ok=True)
    # 每次（含变异轮）都从盘上现拷——in-place 变异后沙箱即见变异态
    shutil.copyfile(TOKEN_STORE, os.path.join(SANDBOX, "src", "lib", "token_store.ts"))
    shutil.copyfile(os.path.join(REPO, "src", "lib", "datapath.ts"),
                    os.path.join(SANDBOX, "src", "lib", "datapath.ts"))
    # datapath.repoRoot() 向上找 package.json ⇒ 锚定沙箱 ⇒ PYTHONPATH 让
    # `-m md_cg.tokens` 命中假校验器（真仓 md_cg 排在其后，不会被用到）。
    with open(os.path.join(SANDBOX, "package.json"), "w", encoding="utf-8", newline="\n") as f:
        f.write('{"name":"issue224-guard-sandbox","private":true}\n')
    with open(os.path.join(SANDBOX, "md_cg", "__init__.py"), "w", encoding="utf-8", newline="\n") as f:
        f.write("")
    with open(os.path.join(SANDBOX, "md_cg", "tokens.py"), "w", encoding="utf-8", newline="\n") as f:
        f.write(_FAKE_TOKENS_PY)
    with open(os.path.join(SANDBOX, "probe.mjs"), "w", encoding="utf-8", newline="\n") as f:
        f.write(_PROBE_MJS)


def _runtime_available():
    node = shutil.which("node")
    py = shutil.which("python")
    if node and py and os.path.isdir(TSX_DIR):
        return node, py
    return None, None


def _run_runtime_group() -> None:
    global SKIP
    print("\n[R] 运行时组：node --import tsx ＋ 沙箱假校验器（真 spawnSync 读数）")
    node, py = _runtime_available()
    if not node:
        SKIP += 1
        print("  [SKIP] [R] 本机无 node / python 或仓库 node_modules/tsx 缺席"
              "（npm install 可得）——运行时面按 SKIP 记录，不判失败；"
              "静态组断言不受影响。")
        return
    try:
        _prepare_sandbox()
    except OSError as e:
        check("[R] 沙箱就绪", False, repr(e))
        return
    env = dict(os.environ)
    env["PROBE_PYTHON"] = py
    try:
        r = subprocess.run([node, "--import", "tsx",
                            os.path.join(SANDBOX, "probe.mjs")],
                           cwd=REPO, capture_output=True, text=True,
                           encoding="utf-8", timeout=RUNTIME_TIMEOUT_S, env=env)
    except (OSError, subprocess.TimeoutExpired) as e:
        check("[R] 探针进程可运行", False, repr(e))
        return
    if r.returncode != 0:
        check("[R] 探针进程退出码 0", False,
              f"rc={r.returncode} stderr={(r.stderr or '')[-400:]!r}")
        return
    recs = []
    for line in (r.stdout or "").splitlines():
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            recs.append(json.loads(line))
        except ValueError:
            pass
    by_case = {rec.get("case"): rec for rec in recs}
    for case, num in _R_ORDER:
        rec = by_case.get(case)
        if rec is None:
            check(f"[{num}] 用例 {case} 有读数", False, "探针输出缺该用例")
            continue
        ok, expect = _r_expect(rec)
        check(f"[{num}] {case}", ok, expect)


# ============================================================ 静态组

def _g1() -> None:
    print("\n[G1] package.json：dependencies 含 schemastery，peer 面不再含")
    with open(PKG, encoding="utf-8", newline="") as f:
        pkg_raw = f.read()
    pkg = json.loads(pkg_raw)
    check("[G1] package.json 可解析为 JSON 对象", isinstance(pkg, dict))
    deps = pkg.get("dependencies") or {}
    check("[G1] dependencies 含 @deepseek-ai/schemastery（#222：optional peer ⇒ 整包不可加载）",
          isinstance(deps.get("@deepseek-ai/schemastery"), str),
          f"dependencies={deps!r}")
    check("[G1] peerDependenciesMeta 不再含 @deepseek-ai/schemastery",
          "@deepseek-ai/schemastery" not in (pkg.get("peerDependenciesMeta") or {}))
    check("[G1] peerDependencies 不再含 @deepseek-ai/schemastery",
          "@deepseek-ai/schemastery" not in (pkg.get("peerDependencies") or {}))


def _g2() -> None:
    print("\n[G2] package.json 以换行结尾（对当前文件末字节的实检，#368 应做②）")
    with open(PKG, encoding="utf-8", newline="") as f:
        pkg_raw = f.read()
    check("[G2] 文件末字节为换行（\\n 或 \\r\\n）",
          pkg_raw.endswith("\n"),
          f"末 8 字节={pkg_raw[-8:]!r}")


def _g3() -> None:
    print("\n[G3] src/lib/token_store.ts：tenant 透传 / envOverride / verifyToken 三态")
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
    check("[G3] verifyToken 导出、签名带 envOverride 且调 `tokens verify --token`（#224-③＋#368 必须2）",
          "export function verifyToken(" in ts
          and "python: string, token: string, envOverride?" in ts
          and "'verify', '--token', token" in ts)
    check("[G3] verifyToken 三态判据：rc=0⇒ok、rc=2⇒invalid、其余非零⇒unverifiable（#368 必须1）",
          "if (r.status === 0) return 'ok'" in ts
          and "if (r.status === 2) return 'invalid'" in ts
          and "if (r.error) return 'unverifiable'" in ts)
    check("[G3] spawn env 两处都合并 configEnvOverlay(envOverride)（#368 必须2）",
          ts.count("...configEnvOverlay(envOverride),") == 2,
          f"出现次数={ts.count('...configEnvOverlay(envOverride),')}（应为 2：issue/verify）")
    check("[G3] resolveToken 复用密钥环令牌前先复核且透传 envOverride（#224-③＋#368 必须2）",
          "verifyToken(opts.python, fromRing, opts.envOverride)" in ts)
    check("[G3] 清环时序：clearKeyring 整体退场（#368 必须3：无 eager 清环）",
          "clearKeyring" not in ts,
          "源码中仍残留 clearKeyring 形态" if "clearKeyring" in ts else "")
    check("[G3] 清环时序：先拒失败再 writeKeyring 覆写（签成功才替换，#368 必须3）",
          "writeKeyring(keyringPath, r.token)" in ts
          and 0 <= ts.find("if (!r.token)") < ts.find("writeKeyring(keyringPath, r.token)"))
    check("[G3] issueToken 调用透传 opts.tenant 与 opts.envOverride（#224-①＋#368 必须2）",
          "issueToken(opts.python, role, actor, clearance, opts.tenant, opts.envOverride)" in ts)


def _g4() -> None:
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


def _g5() -> None:
    global SKIP
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
        SKIP += 1
        print("  [SKIP] [G5] 本机无 node 或仓库 node_modules/typescript 缺席"
              "（npm install --ignore-scripts 可得）——编译面按 SKIP 记录，"
              "不判失败；G1–G4 静态断言不受影响。")


def _run_all(include_g5: bool = True) -> int:
    global PASS, FAIL, SKIP, FAILS
    PASS = FAIL = SKIP = 0
    FAILS = []
    print("=" * 68)
    print("#224/#222/#368 token_store 透传＋verifyToken 三态（静态＋运行时守卫）")
    print("=" * 68)
    _g1()
    _g2()
    _g3()
    _g4()
    _run_runtime_group()
    if include_g5:
        _g5()
    print("\n" + "=" * 68)
    print(f"PASS={PASS}  FAIL={FAIL}  SKIP={SKIP}")
    if FAILS:
        print("失败项：" + "；".join(FAILS))
    return FAIL


# ============================================================ 定点变异

# (名称, 相对路径, 改动前形态, 变异态, 预期红数下限, 替换次数[None=全部])
# 锚点 = 布局无关的唯一子串；行尾按盘上文件实际 EOL 自适应（CRLF 保持）。
_MUTATIONS = (
    ("#368必须1·三态判据回退（非0即invalid）", "src/lib/token_store.ts",
     "  if (r.status === 2) return 'invalid'",
     "  if (r.status !== 0) return 'invalid'", 3, 1),
    ("#368必须2·spawn env 不再合并 config.env", "src/lib/token_store.ts",
     "          ...configEnvOverlay(envOverride),\n",
     "", 2, None),
    ("#368必须3·清环回退为先清后签（eager clear）", "src/lib/token_store.ts",
     "    if (verdict === 'ok') return { token: fromRing, source: 'keyring', keyringPath }\n",
     "    if (verdict === 'ok') return { token: fromRing, source: 'keyring', keyringPath }\n"
     "    if (verdict === 'invalid') writeFileSync(keyringPath, '', "
     "{ encoding: 'utf-8', mode: 0o600 })\n", 1, 1),
    ("对抗·unverifiable fail-open（带病复用）", "src/lib/token_store.ts",
     "  if (r.status === 2) return 'invalid'\n  return 'unverifiable'",
     "  if (r.status === 2) return 'invalid'\n  return 'ok'", 1, 1),
    ("G2·package.json 剥末尾换行", "package.json",
     '    "@deepseek-ai/schemastery": ">=3.0.0"\n  }\n}\n',
     '    "@deepseek-ai/schemastery": ">=3.0.0"\n  }\n}', 1, 1),
)


def _apply_mutation(rel: str, old: str, new: str, count):
    """把盘上源按 EOL 自适应做 in-place 定点变异；返回还原用闭包。

    字节纪律：newline='' 读写（不做 newline 翻译），行尾按文件实际 EOL 折算
    锚点，finally 还原原始字节——变异轮绝不留下 CRLF↔LF 的整文件漂移。"""
    path = os.path.join(REPO, rel.replace("/", os.sep))
    with open(path, encoding="utf-8", newline="") as f:
        raw = f.read()
    eol = "\r\n" if "\r\n" in raw else "\n"
    old_r, new_r = old.replace("\n", eol), new.replace("\n", eol)
    if old_r not in raw:
        return None, raw
    mut = raw.replace(old_r, new_r) if count is None else raw.replace(old_r, new_r, count)

    def _restore():
        with open(path, "w", encoding="utf-8", newline="") as f:
            f.write(raw)

    with open(path, "w", encoding="utf-8", newline="") as f:
        f.write(mut)
    return _restore, raw


def _mutate_mode(list_only: bool = False) -> int:
    print("!! 定点变异自证（#368 应做①：真变异，非空转）：逐条把生产源改成"
          "缺陷形态，套件必须转红，finally 字节级还原\n")
    if list_only:
        for name, rel, _o, _n, exp, cnt in _MUTATIONS:
            print("  %-46s expect_red>=%d  x%s  (%s)"
                  % (name, exp, "ALL" if cnt is None else cnt, rel))
        return 0

    with contextlib.redirect_stdout(buf := io.StringIO()):
        baseline = _run_all(include_g5=False)   # 编译面与变异判据正交，轮内不重编
    print("  未变异基线（G1–G4＋R）：失败=%d（必须为 0）" % baseline)
    if baseline:
        return 1

    anchor_miss, bad = [], []
    for name, rel, old, new, expect, cnt in _MUTATIONS:
        restore, _raw = _apply_mutation(rel, old, new, cnt)
        if restore is None:
            print("  ANCHOR-MISS %s —— 锚点在 %s 里找不到（实现改了却没同步"
                  "本表；锚点漂移不得静默）" % (name, rel))
            anchor_miss.append(name)
            continue
        try:
            with contextlib.redirect_stdout(mbuf := io.StringIO()):
                reds = _run_all(include_g5=False)
            red_items = [l for l in mbuf.getvalue().splitlines()
                         if l.strip().startswith("[FAIL]")]
        finally:
            restore()
        verdict = "红" if reds else "**仍全绿 = 该判据空转**"
        mark = "OK  " if reds >= expect else "MISMATCH"
        print("  %s %-46s 红项=%d 预期>=%d  %s" % (mark, name, reds, expect, verdict))
        for l in red_items[:6]:
            print("        " + l.strip()[6:])
        if reds < expect:
            bad.append("%s（红=%d 预期>=%d）" % (name, reds, expect))

    if anchor_miss:
        print("\nANCHOR-MISS：%s" % "、".join(anchor_miss))
        print("退出码 2（fail-closed）：变异表锚点漂移即判失败，不得静默跳过")
        return 2

    # 恢复绿两向的后半向：全部还原后整体复跑（含 G5 编译面）必须全绿
    with contextlib.redirect_stdout(rbuf := io.StringIO()):
        restored = _run_all(include_g5=True)
    r_summary = [l for l in rbuf.getvalue().splitlines()
                 if l.startswith("PASS=")]
    print("\n  还原后整体复跑（含 G5）：%s（必须 FAIL=0）"
          % (r_summary[-1] if r_summary else "?"))
    if restored:
        bad.append("还原后复跑失败=%d" % restored)

    print("\n定点变异自证：%s"
          % ("PASS（每处判据都被打红且还原后全绿）"
             if not bad else "FAIL —— " + "、".join(bad)))
    return 0 if not bad else 1


def main() -> int:
    if "--mutate" in sys.argv:
        return _mutate_mode("--list" in sys.argv)
    return 0 if _run_all() == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
