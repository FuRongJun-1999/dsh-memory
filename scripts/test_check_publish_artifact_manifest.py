# -*- coding: utf-8 -*-
"""test_check_publish_artifact_manifest —— N216 发布清单可信性守卫

背景（2026-09-28 缺陷 N216，severity=high）：
  `.github/workflows/publish-artifact-check.yml:14/30` 与 `package.json:87-88`
  （prepublishOnly→npm run gate）把 `scripts/check_publish_artifact.py` 挂进
  发版链路；该门禁的「发布清单」取自 `npm pack --dry-run --json` 的 stdout，而
  npm 先跑生命周期脚本（prepare/prepack/postpack），其 stdout 排在 npm 自身清单
  **之前**，旧实现 `extract_first_json_value` 取「首个可解析 JSON 值」⇒
  `package.json` 的 `prepare` 打印一行 `[{"files":[{"path":"a.js"}]}]`（只列已
  追踪件以骗过 R4）即可把 R1 凭据/R2 私有数据/R3 隐私文本/R4 非追踪件四档的扫描
  面整体换成诱饵：真发布件里的凭据文件不再被检查、门禁打印 VERDICT=PASS/exit 0。
  同一解析面还让清单条目带 `..` 越过 `--root` 读任意可读文件并回显命中片段
  （`os.path.join(root, *rel.split('/'))`，:241）。

守卫断言面（核心断言全哑数据/临时仓，与仓库真实内容解耦）：
  M1  解析契约：诱饵清单在前、npm 真清单在后 → 取真清单（修前取诱饵）
  M2  诱饵被计入清单候选（R6 据此判负，不静默）
  M3  越根判据：`..` / 绝对 / 盘符 / UNC 一律不安全；包内相对路径放行
  M4  越根条目不进扫描面（`_manifest_paths`）
  M5  越根读兜底：`read_local_text_if_needed` 对根外文件返回 None（且不误伤根内）
  M6  E2E 攻击腿：临时 git 仓 + prepare 诱饵 + 真 .env → 门禁 exit 1 / VERDICT=FAIL /
      R1 命中 .env（修前：文件数=1、四档全 PASS、exit 0）
  M7  E2E 反向腿：干净临时仓（无诱饵无凭据）→ exit 0 / VERDICT=PASS（新判据不误伤）
  M8  内置 `--selftest` 全绿（含新增的诱饵负例）
  M9  E2E CI 形态：prepare 打印「跳过构建」纯文本（2026-09-20 CI 取证形态）→
      不得误判为冒充、门禁仍 exit 0

运行：python -X utf8 scripts/test_check_publish_artifact_manifest.py
"""
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)

_GATE = os.path.join(HERE, "scripts", "check_publish_artifact.py")

passed = failed = skipped = 0


def check(name, cond, detail=""):
    global passed, failed
    if cond:
        passed += 1
        print("  [PASS] " + name)
    else:
        failed += 1
        print("  [FAIL] " + name + "  " + str(detail)[:400])


def skip(name, why):
    global skipped
    skipped += 1
    print("  [SKIP] %s（%s）" % (name, why))


def _load_mod():
    spec = importlib.util.spec_from_file_location("cpa_manifest_guard", _GATE)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


_DECOY = '[{"files":[{"path":"a.js"}]}]'
_REAL = ('[\n  {\n    "id": "p@1.0.0",\n    "name": "p",\n'
         '    "version": "1.0.0",\n    "filename": "p-1.0.0.tgz",\n'
         '    "files": [\n      {"path": ".env", "size": 37, "mode": 420},\n'
         '      {"path": "a.js", "size": 5, "mode": 420}\n    ],\n'
         '    "entryCount": 2\n  }\n]\n')


def unit(mod):
    print("[1] 解析契约与越根判据（哑数据）")
    # M1：诱饵在前
    got, meta = mod.extract_pack_manifest(_DECOY + "\n" + _REAL)
    paths, unsafe = mod._manifest_paths(got)
    check("M1 诱饵在前 → 取 npm 真清单（含 .env）", paths == [".env", "a.js"], paths)
    # M1 反向：诱饵在后（postpack 形态）亦不得改变「全形态优先」
    got2, _meta2 = mod.extract_pack_manifest(_REAL + _DECOY + "\n")
    paths2, _ = mod._manifest_paths(got2)
    check("M1 诱饵在后 → 仍取全形态真清单", paths2 == [".env", "a.js"], paths2)
    # M2：多段清单候选被显式记账
    check("M2 清单候选计数=2 且形态档=full",
          meta["manifest_candidates"] == 2 and meta["shape_rank"] == "full", meta)
    check("M2 纯文本污染不产生清单候选（不误报）",
          mod.extract_pack_manifest("[prepare] 跳过构建\n")[1]["manifest_candidates"] == 0)
    # 无清单 → None（fail-closed 交调用方判 2）
    check("M2 无清单形态 JSON → None", mod.extract_pack_manifest('{"a": 1}')[0] is None)

    # M3：越根判据
    check("M3 '..' 段判不安全", mod.unsafe_rel_reason("../outside.md") is not None)
    check("M3 反斜杠形态归一后判不安全",
          mod.unsafe_rel_reason("..\\outside.md") is not None)
    check("M3 中段 '..' 判不安全", mod.unsafe_rel_reason("a/../../b.js") is not None)
    check("M3 绝对路径判不安全", mod.unsafe_rel_reason("/etc/passwd") is not None)
    check("M3 盘符路径判不安全", mod.unsafe_rel_reason("C:/x.txt") is not None)
    check("M3 包内相对路径放行", mod.unsafe_rel_reason("src/a.js") is None)

    # M4：越根条目不进扫描面
    esc_paths, esc_unsafe = mod._manifest_paths(
        [{"files": [{"path": "../outside.md", "size": 1, "mode": 420},
                    {"path": "a.js", "size": 1, "mode": 420}]}])
    check("M4 越根条目不进扫描面（只留 a.js）", esc_paths == ["a.js"], esc_paths)
    check("M4 越根条目记账 1 条", len(esc_unsafe) == 1, esc_unsafe)

    # M5：越根读兜底（真文件在 --root 之外）
    with tempfile.TemporaryDirectory() as tmp:
        root = os.path.join(tmp, "repo")
        os.makedirs(root)
        outside = os.path.join(tmp, "outside_secret.md")
        with open(outside, "w", encoding="utf-8", newline="\n") as fh:
            fh.write("token sk-" + "A" * 24 + "\n")
        check("M5 前提：根外文件确实存在且可读（否则断言无意义）",
              os.path.isfile(outside)
              and "sk-" in open(outside, encoding="utf-8").read())
        check("M5 根外文件（../ 形态）不读",
              mod.read_local_text_if_needed(root, "../outside_secret.md") is None)
        check("M5 根外文件（绝对路径形态）不读",
              mod.read_local_text_if_needed(root, outside) is None)
        inside = os.path.join(root, "note.md")
        with open(inside, "w", encoding="utf-8", newline="\n") as fh:
            fh.write("根内普通正文\n")
        check("M5 根内文件照读（不误伤）",
              (mod.read_local_text_if_needed(root, "note.md") or "").rstrip("\r\n")
              == "根内普通正文")


def _make_repo(root, pkg, files):
    os.makedirs(root, exist_ok=True)
    with open(os.path.join(root, "package.json"), "w", encoding="utf-8") as fh:
        json.dump(pkg, fh, indent=2)
    for rel, body in files.items():
        fp = os.path.join(root, *rel.split("/"))
        os.makedirs(os.path.dirname(fp), exist_ok=True)
        with open(fp, "w", encoding="utf-8") as fh:
            fh.write(body)
    env = dict(os.environ, PYTHONUTF8="1")
    subprocess.run(["git", "init", "-q", "."], cwd=root, check=True, env=env)
    subprocess.run(["git", "add", "-A"], cwd=root, check=True, env=env)
    subprocess.run(["git", "-c", "user.email=t@t", "-c", "user.name=t",
                    "commit", "-qm", "init"], cwd=root, check=True, env=env)


def _run_gate(root, args=()):
    env = dict(os.environ, PYTHONUTF8="1")
    return subprocess.run(
        [sys.executable, "-X", "utf8", _GATE, "--root", root] + list(args),
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        env=env, cwd=HERE, timeout=600)


def e2e():
    print("[2] E2E 攻击腿与反向腿（临时 git 仓 + 真实 npm）")
    if shutil.which("npm") is None or shutil.which("git") is None:
        skip("M6/M7 E2E", "本机无 npm 或 git")
        return
    with tempfile.TemporaryDirectory() as tmp:
        # M6：prepare 打印诱饵清单 + 真 .env（哑凭据形态，非真实密钥）
        atk = os.path.join(tmp, "attack")
        _make_repo(atk, {
            "name": "n216-guard-atk", "version": "1.0.0", "private": True,
            "scripts": {"prepare": "node -e \"console.log(JSON.stringify("
                                   "[{files:[{path:'a.js'}]}]))\""},
        }, {"a.js": "// a\n",
            ".env": "TOKEN_SK=sk-" + "9f3aK2mQ8vLpR4sT1uWz7yB6nH0cX5dE" + "\n"})
        got = _run_gate(atk)
        out = got.stdout or ""
        check("M6 攻击腿 exit 1（修前 exit 0）", got.returncode == 1,
              "rc=%s\n%s" % (got.returncode, out[-600:]))
        check("M6 VERDICT=FAIL", "VERDICT=FAIL" in out, out[-400:])
        check("M6 R1 命中 .env（真发布件被扫）", ".env（环境变量密文 .env）" in out, out[-800:])
        check("M6 文件数=3（诱饵的 1 件不再冒充）", "文件数=3" in out, out[-600:])
        check("M6 R6 判负并点出冒充候选", "R6 清单来源可信 命中=" in out, out[-600:])

        # M7：反向腿——干净仓必须仍然绿（新判据不误伤发版链路）
        ok = os.path.join(tmp, "clean")
        _make_repo(ok, {"name": "n216-guard-clean", "version": "1.0.0",
                        "private": True}, {"a.js": "// a\n", "lib/x.js": "// x\n"})
        got = _run_gate(ok)
        out = got.stdout or ""
        check("M7 反向腿 exit 0", got.returncode == 0,
              "rc=%s\n%s" % (got.returncode, out[-600:]))
        check("M7 VERDICT=PASS", "VERDICT=PASS" in out, out[-400:])
        check("M7 R5/R6 双双 PASS",
              "R5 清单路径安全" in out and "R6 清单来源可信" in out, out[-600:])

        # M9：CI 形态（本仓 prepare 同款、无 node_modules → 打印「跳过构建」文本行）
        # ——2026-09-20 CI 取证形态：纯文本污染不得产生清单候选、更不得误判 R6
        ci = os.path.join(tmp, "ci_shape")
        prepare = ("node -e \"const fs=require('fs');"
                   "const tsc='node_modules/typescript/bin/tsc';"
                   "fs.existsSync(tsc)?0:console.log('[prepare] 跳过构建：typescript "
                   "未安装（NODE_ENV=production 或 --omit=dev 会省略 "
                   "devDependencies）——需要构建请用 npm install --include=dev')\"")
        _make_repo(ci, {"name": "n216-guard-ci", "version": "1.0.0",
                        "private": True, "scripts": {"prepare": prepare}},
                   {"a.js": "// a\n"})
        got = _run_gate(ci)
        out = got.stdout or ""
        check("M9 CI 形态（prepare 打印跳过行）exit 0——不误伤发版链路",
              got.returncode == 0, "rc=%s\n%s" % (got.returncode, out[-600:]))
        check("M9 纯文本污染不产生清单候选（清单候选=1）",
              "清单候选=1" in out, out[-400:])


def selftest_green():
    print("[3] 脚本内置自检")
    env = dict(os.environ, PYTHONUTF8="1")
    got = subprocess.run([sys.executable, "-X", "utf8", _GATE, "--selftest"],
                         capture_output=True, text=True, encoding="utf-8",
                         errors="replace", env=env, cwd=HERE, timeout=300)
    check("M8 --selftest exit 0（含诱饵负例）", got.returncode == 0,
          (got.stdout or "")[-400:])


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    mod = _load_mod()
    unit(mod)
    e2e()
    selftest_green()
    print("\n%d passed, %d failed, %d skipped" % (passed, failed, skipped))
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
