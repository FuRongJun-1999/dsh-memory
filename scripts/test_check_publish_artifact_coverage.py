# -*- coding: utf-8 -*-
"""test_check_publish_artifact_coverage —— N251 扫描覆盖面守卫（未扫 ≠ 已扫且干净）

背景（2026-10-05 缺陷 N251，severity=high）：`scripts/check_publish_artifact.py` 被自述为
发版链路的最后一道（`prepublishOnly`→`npm run gate`），但它的**内容面**只覆盖「读得进来」
的那部分清单条目：
  · `read_local_text_if_needed` 三处静默 `return None`（`os.stat` 失败 / 超
    `TEXT_SIZE_LIMIT` / `open` 失败）＋ `local_mode` 调用侧 `if text is None: continue`
  · registry 侧同族：成员收集处 `is_text_path(rel) and (m.size or 0) <= TEXT_SIZE_LIMIT`
    过滤，扫描处 `texts.get(rel)` 为 None 即 `continue`
两者都把「未扫」与「已扫且干净」压成同一个可观测态——被跳过的子集零 NOTE、零计数，
`R1 内容面=0`、`VERDICT=PASS`、exit 0。

本轮实测两种形态（哑凭据，非真实密钥）：
  · 超限腿：3,145,764 B 的 `lib/big.txt`（> TEXT_SIZE_LIMIT=3,145,728 B）在 npm **全形态**
    清单内（path/size/mode 齐备、size=3145764）→ 修前 R1 PASS / 内容面=0 / exit 0；
    同一令牌放进 53 B 的小文件则 R1 FAIL——判据随文件大小翻转。
    （在 53 B 小文件上有效、在 4 MB 同内容上失效的判据，不是判据。）
  · postpack 删除腿：`package.json` `files:["lib"]`、`postpack` 删 `lib/gone.txt` 后，
    npm 清单**仍列**该件（全形态、size 在场）而盘上已无 → 修前同样静默。

守卫断言面（核心断言全哑数据/临时仓，与仓库真实内容解耦）：
  C1 单元：清单内超限文本件 → 报「未扫成因」（修前无成因概念 → 红）
  C2 单元：清单内却读不到（盘上无）文本件 → 报「未扫成因」，且成因与 C1 可区分（按成因记账）
  C3 单元：非文本扩展名 → 按设计不扫（无成因；不得把设计面当缺陷刷屏）
  C4 单元：根内普通文本件照读且无成因（不误伤）
  C5 前提坐实：被跳过的超限内容若真被扫，R1 内容面**会**命中（证明逃逸的是实质命中）
  L1 E2E 本地模式·超限腿：清单内 3 MB+ 文本件携带真令牌 → exit 1 / VERDICT=FAIL / R7 判负
     （修前 exit 0 / VERDICT=PASS）
  L2 E2E 本地模式·postpack 删除腿：清单仍列而盘上已无 → exit 1 / R7 判负（修前静默）
  L4 E2E 本地模式·对照腿：同令牌放进 53 B 小文件 → R1 判负且 R7 PASS（与 L1 成对，
     坐实「判据随文件大小翻转」已消除）
  L3 E2E 本地模式·反向腿：干净仓（含普通文本件）→ exit 0 / VERDICT=PASS / R7 PASS
     （新判据不误伤发版链路）
  R1 E2E registry 模式（桩 http 层，无网络）：tarball 内超限文本件 → R7 判负，且 R0 保持 PASS
     （成因隔离：判负来自未扫，不是来自 tarball 一致性）
  R2 E2E registry 模式·反向腿：tarball 内普通文本件 → R7 PASS
  S1 脚本内置 `--selftest` 全绿（含本轮新增的未扫成因断言）

运行：python -X utf8 scripts/test_check_publish_artifact_coverage.py
"""
import base64
import contextlib
import hashlib
import importlib.util
import io
import json
import os
import shutil
import subprocess
import sys
import tarfile
import tempfile

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)

_GATE = os.path.join(HERE, "scripts", "check_publish_artifact.py")

#: 哑凭据形态（与既有守卫同款样串，非真实密钥）
_REAL_TOKEN = "sk-" + "9f3aK2mQ8vLpR4sT1uWz7yB6nH0cX5dE"

passed = failed = skipped = 0


def check(name, cond, detail=""):
    global passed, failed
    if cond:
        passed += 1
        print("  [PASS] " + name)
    else:
        failed += 1
        print("  [FAIL] " + name + "  "
              + str(detail).replace("\n", " | ")[:400])


def skip(name, why):
    global skipped
    skipped += 1
    print("  [SKIP] %s（%s）" % (name, why))


def _env():
    return dict(os.environ, PYTHONUTF8="1")


def _load_mod():
    spec = importlib.util.spec_from_file_location("cpa_coverage_guard", _GATE)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _probe(mod, root, rel):
    """→ (text, cause)。

    成因单点：优先取 `read_local_text_detail`（本轮新增）。修前不存在该函数——返回
    `(text, None)`，即「没有成因概念」，正是本守卫要红的形态。
    """
    fn = getattr(mod, "read_local_text_detail", None)
    if fn is None:
        return mod.read_local_text_if_needed(root, rel), None
    return fn(root, rel)


def _make_repo(root, pkg, files):
    os.makedirs(root, exist_ok=True)
    with open(os.path.join(root, "package.json"), "w", encoding="utf-8") as fh:
        json.dump(pkg, fh, indent=2)
    for rel, body in files.items():
        fp = os.path.join(root, *rel.split("/"))
        os.makedirs(os.path.dirname(fp), exist_ok=True)
        with open(fp, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(body)
    env = _env()
    subprocess.run(["git", "init", "-q", "."], cwd=root, check=True, env=env)
    subprocess.run(["git", "add", "-A"], cwd=root, check=True, env=env)
    subprocess.run(["git", "-c", "user.email=t@t", "-c", "user.name=t",
                    "commit", "-qm", "init"], cwd=root, check=True, env=env)


def _run_gate(root, args=()):
    return subprocess.run(
        [sys.executable, "-X", "utf8", _GATE, "--root", root] + list(args),
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        env=_env(), cwd=HERE, timeout=600)


def _build_tarball(files):
    """{rel: str|bytes} → tgz 字节（包内前缀 package/）。"""
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tf:
        for rel, data in files.items():
            raw = data if isinstance(data, bytes) else data.encode("utf-8")
            ti = tarfile.TarInfo(name="package/" + rel)
            ti.size = len(raw)
            tf.addfile(ti, io.BytesIO(raw))
    return buf.getvalue()


def _registry_with_blob(mod, root, blob, file_count):
    """桩 http 层跑 registry_mode → (stdout, report, rc)。R0 保持 PASS（成因隔离）。"""
    shasum = hashlib.sha1(blob).hexdigest()
    integrity = "sha512-" + base64.b64encode(hashlib.sha512(blob).digest()).decode("ascii")
    calls = {"n": 0}

    def _get_json(url):
        calls["n"] += 1
        if calls["n"] == 1:
            return {"name": "p", "time": {"1.0.0": "2026-10-05T00:00:00.000Z"}}
        return {"dist": {"tarball": "https://reg.example/p/-/p-1.0.0.tgz",
                         "shasum": shasum, "integrity": integrity,
                         "fileCount": file_count}}

    mod.http_get_json = _get_json
    mod.http_get_bytes = lambda url: blob
    report = mod.CheckReport(5)
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = mod.registry_mode(root, "1.0.0", report)
    return buf.getvalue(), report, rc


def unit(mod):
    print("[1] 未扫成因单点（read_local_text_detail；哑数据）")
    with tempfile.TemporaryDirectory() as tmp:
        root = os.path.join(tmp, "repo")
        os.makedirs(root)
        limit = mod.TEXT_SIZE_LIMIT
        big_body = _REAL_TOKEN + "\n" + "A" * (limit + 13)
        fp = os.path.join(root, "big.txt")
        with open(fp, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(big_body)
        # C5 前提坐实：同一内容若真被扫，R1 内容面会命中（不是「本来就干净」）
        scanned, _ = mod.scan_text_hits(open(fp, encoding="utf-8").read(),
                                        mod.R1_CONTENT_RULES, "big.txt")
        check("C5 前提坐实：超限内容本身含真形态令牌（若被扫即命中）",
              len(scanned) == 1, scanned)
        check("C5 前提坐实：该件确实超 TEXT_SIZE_LIMIT（否则断言无意义）",
              os.path.getsize(fp) > limit, (os.path.getsize(fp), limit))
        t_big, c_big = _probe(mod, root, "big.txt")
        check("C1 清单内超限文本件 → 报未扫成因（修前：None 且无成因）",
              t_big is None and bool(c_big), (t_big, c_big))

        # C2：清单内却读不到（盘上无）
        t_miss, c_miss = _probe(mod, root, "gone.txt")
        check("C2 清单内却读不到 → 报未扫成因（修前静默）",
              t_miss is None and bool(c_miss), (t_miss, c_miss))
        check("C2 成因按类区分：超限 ≠ 读不到",
              bool(c_big) and bool(c_miss) and c_big != c_miss, (c_big, c_miss))

        # C3：非文本扩展名按设计不扫
        with open(os.path.join(root, "img.png"), "wb") as fh:
            fh.write(b"\x89PNG\r\n\x1a\n" + b"\x00" * 8)
        t_bin, c_bin = _probe(mod, root, "img.png")
        check("C3 非文本扩展名 → 按设计不扫（无成因，不刷屏）",
              t_bin is None and c_bin is None, (t_bin, c_bin))

        # C4：根内普通文本件照读
        with open(os.path.join(root, "note.md"), "w", encoding="utf-8",
                  newline="\n") as fh:
            fh.write("根内普通正文\n")
        t_ok, c_ok = _probe(mod, root, "note.md")
        check("C4 根内普通文本件照读且无成因",
              (t_ok or "").rstrip("\r\n") == "根内普通正文" and c_ok is None,
              (t_ok, c_ok))

        # 兼容面：既有 API 语义不变（越根不读、根内照读）
        check("C4 既有 API 语义不变：越根不读（read_local_text_if_needed）",
              mod.read_local_text_if_needed(root, "../outside.md") is None)
        check("C4 既有 API 语义不变：根内普通文本件照读",
              (mod.read_local_text_if_needed(root, "note.md") or "").strip()
              == "根内普通正文")


def e2e_local():
    print("[2] E2E 本地模式（临时 git 仓 + 真实 npm）")
    if shutil.which("npm") is None or shutil.which("git") is None:
        skip("L1/L2/L3 E2E", "本机无 npm 或 git")
        return
    limit = 3 * 1024 * 1024
    with tempfile.TemporaryDirectory() as tmp:
        # L1：超限腿——真令牌整条放进 3MB+ 文本件（判定面只此一件，成因隔离到 R7）
        over = os.path.join(tmp, "oversize")
        body = (_REAL_TOKEN + "\n" + "A" * (limit + 13))
        _make_repo(over, {"name": "n251-oversize", "version": "1.0.0",
                          "private": True, "files": ["lib"]},
                   {"lib/big.txt": body})
        got = _run_gate(over)
        out = got.stdout or ""
        check("L1 超限腿 exit 1（修前 exit 0）", got.returncode == 1,
              "rc=%s\n%s" % (got.returncode, out[-600:]))
        check("L1 VERDICT=FAIL（修前 PASS）", "VERDICT=FAIL" in out, out[-400:])
        check("L1 R7 判负并点名未扫件", "R7 扫描面完整性 命中=" in out and "lib/big.txt" in out,
              out[-800:])

        # L2：postpack 删除腿——npm 清单仍列 lib/gone.txt，盘上已无
        gone = os.path.join(tmp, "postpack")
        deleter = ("node -e \"require('fs').rmSync('lib/gone.txt',{force:true})\"")
        _make_repo(gone, {"name": "n251-postpack", "version": "1.0.0",
                          "private": True, "files": ["lib"],
                          "scripts": {"postpack": deleter}},
                   {"lib/keep.txt": "keep\n", "lib/gone.txt": "gone\n"})
        got = _run_gate(gone)
        out = got.stdout or ""
        check("L2 postpack 删除腿 exit 1（修前 exit 0）", got.returncode == 1,
              "rc=%s\n%s" % (got.returncode, out[-600:]))
        check("L2 R7 判负并点名 lib/gone.txt",
              "R7 扫描面完整性 命中=" in out and "lib/gone.txt" in out, out[-800:])
        check("L2 现场核对：postpack 后盘上确无 lib/gone.txt（前提坐实）",
              not os.path.isfile(os.path.join(gone, "lib", "gone.txt")))

        # L4：对照腿——同一令牌放进 53 B 小文件 → R1 判负（修前亦然），且 R7 PASS。
        # 与 L1 成对，坐实「判据随文件大小翻转」已消除：两形态都判负，差异只在判负的规则。
        small = os.path.join(tmp, "small")
        _make_repo(small, {"name": "n251-small", "version": "1.0.0",
                           "private": True, "files": ["lib"]},
                   {"lib/small.txt": _REAL_TOKEN + "\n"})
        got = _run_gate(small)
        out = got.stdout or ""
        check("L4 对照腿：同一令牌在小文件 → R1 判负",
              got.returncode == 1 and "[FAIL] R1 凭据/密钥面 命中=1" in out,
              out[-600:])
        check("L4 对照腿：小文件形态 R7 PASS（未扫=0，成因隔离）",
              "R7 扫描面完整性" in out and "[FAIL] R7" not in out, out[-500:])

        # L3：反向腿——干净仓必须仍然绿（新判据不误伤发版链路）
        clean = os.path.join(tmp, "clean")
        _make_repo(clean, {"name": "n251-clean", "version": "1.0.0",
                           "private": True, "files": ["lib"]},
                   {"lib/keep.txt": "普通正文\n"})
        got = _run_gate(clean)
        out = got.stdout or ""
        check("L3 反向腿 exit 0", got.returncode == 0,
              "rc=%s\n%s" % (got.returncode, out[-600:]))
        check("L3 VERDICT=PASS", "VERDICT=PASS" in out, out[-400:])
        check("L3 R7 PASS（未扫=0）", "R7 扫描面完整性" in out
              and "[FAIL] R7" not in out, out[-600:])


def e2e_registry(mod):
    print("[3] E2E registry 模式（桩 http 层，无网络）")
    limit = 3 * 1024 * 1024
    with tempfile.TemporaryDirectory() as tmp:
        with open(os.path.join(tmp, "package.json"), "w", encoding="utf-8") as fh:
            json.dump({"name": "p", "version": "1.0.0"}, fh)
        pkg = "{\"name\":\"p\",\"version\":\"1.0.0\"}\n"

        # R1：超限文本件（tarball 内）
        big = _REAL_TOKEN + "\n" + "A" * (limit + 13)
        blob = _build_tarball({"package.json": pkg, "lib/big.txt": big})
        out, report, rc = _registry_with_blob(mod, tmp, blob, 2)
        check("R1 registry 前置：桩链路走通（rc=0，非环境错误）", rc == 0,
              "rc=%s\n%s" % (rc, out[-500:]))
        check("R1 registry 成因隔离：R0 发布件一致性 PASS",
              "R0 发布件一致性" in out and "[FAIL] R0" not in out, out[-500:])
        check("R1 registry 超限文本件 → R7 判负（修前静默）",
              "R7 扫描面完整性 命中=" in out and "lib/big.txt" in out, out[-700:])
        check("R1 registry 判负进入结论（report.failed）", report.failed is True)

        # R2：反向腿——普通文本件不得误报
        blob2 = _build_tarball({"package.json": pkg, "lib/small.txt": "普通正文\n"})
        out2, report2, rc2 = _registry_with_blob(mod, tmp, blob2, 2)
        check("R2 registry 反向腿 rc=0", rc2 == 0, "rc=%s\n%s" % (rc2, out2[-400:]))
        check("R2 registry 反向腿 R7 PASS（未扫=0）",
              "R7 扫描面完整性" in out2 and "[FAIL] R7" not in out2, out2[-500:])


def selftest_green():
    print("[4] 脚本内置自检")
    got = subprocess.run([sys.executable, "-X", "utf8", _GATE, "--selftest"],
                         capture_output=True, text=True, encoding="utf-8",
                         errors="replace", env=_env(), cwd=HERE, timeout=300)
    check("S1 --selftest exit 0（含本轮未扫成因断言）", got.returncode == 0,
          (got.stdout or "")[-500:])


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    mod = _load_mod()
    unit(mod)
    e2e_local()
    e2e_registry(mod)
    selftest_green()
    print("\n%d passed, %d failed, %d skipped" % (passed, failed, skipped))
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
