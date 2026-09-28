# -*- coding: utf-8 -*-
"""结果完整性锚密钥链**同源**守卫（N190 / C2b）：MCP 提交面 ↔ Rust serve 面同链同序。

背景（本批 C2b 实测缺口）：锚密钥链在 Rust 侧（`hive/src/keyres.rs`）已按 N190 收窄为
身份两环 `HIVE_ORCH_TOKEN` → `HIVE_ORCH_TOKEN_FILE` → None，且该文件头注明写「同链副本
（勿分叉）：`hive/hive_mcp/mcp_server.py::_result_anchor_key` 必须同步」；而 Python 提交面
的 `_RESULT_KEY_KEYS` 仍是三键（含模型网关密钥 `HIVE_API_KEY`）⇒ **两侧判据分叉**：

  只配 `HIVE_API_KEY` 的部署里，提交面 `_result_anchor_key()` 非 None → `_submit` 往
  status.json 写 `result_nonce`（任务声明「有锚预期」）；而 serve 侧
  `resolve_key_from_env()` 为 None → 不注入 `HIVE_RESULT_ANCHOR`、锚校验面不启用
  ⇒ 提交侧在签发、校验侧已无密钥（`hive/src/keyres.rs:24-26` 书面点名的正是这个副本）。

本文件把「同链」做成机械断言（18 项）：
  [A] 只配模型密钥（config 形态 / env 形态）→ `_result_anchor_key()` 为 None，
      `_submit` 落盘 **不含** `result_nonce`（旧格式 = 锚判据不启用）；
  [B] 配身份令牌 `HIVE_ORCH_TOKEN`（env / config）→ 取之，且 `_submit` 写 nonce；
  [C] 只配 `HIVE_ORCH_TOKEN_FILE`：env 形态按 Rust 语义**读文件全文 strip** 并写 nonce；
      config `{"file": path}` 形态同样取文件内容；config **直值路径**形态（部署实况）
      冻结为「非 None = 锚启用」（判据面只问启用与否，见 `_result_anchor_key` 诚实边界段）；
  [E] 键集结构：`_RESULT_KEY_KEYS` 与 Rust `resolve_key_from_env` 的两环**同名同序**
      （从 `hive/src/keyres.rs` 现场解析，不是抄一份常量），且不含 `HIVE_API_KEY`；
  [H] 文案口径：键集段与 `_result_anchor_key` docstring 不再有「三键」，且保留
      「与 rust keyres::resolve_key_from_env 同链」并标注 N190 收窄。

红基线（不靠推理，用 git HEAD 版覆盖临时副本）：
    python -X utf8 -m hive.test_result_anchor_chain --head-baseline
该模式把 `git show HEAD:hive/hive_mcp/mcp_server.py` 的字节写进临时假仓后跑**同一套**
check，并断言「红项集合 == 预期的 11 项分叉」（HEAD 仍是三键链，故 A/C1/E/H 组必红）；
绿态默认模式要求红项为零。

实验纪律：全程**哑值 + 系统临时目录**；mcp_server 与其依赖的 serve_start 复制进临时
「假仓」后装载（真仓 `hive_mcp/__pycache__` 不被写入、真 jobs 池/真 config.local.json/
真令牌库一概不读不碰）；不拉起任何 serve、不出网。运行：退出码 0 = 全绿。
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except AttributeError:
    pass

_HERE = os.path.dirname(os.path.abspath(__file__))
_REPO = os.path.dirname(_HERE)
if _REPO not in sys.path:
    sys.path.insert(0, _REPO)

MCP_REL = "hive/hive_mcp/mcp_server.py"
KEYRES_REL = "hive/src/keyres.rs"
TOKEN_FILE_KEY = "HIVE_ORCH_TOKEN_FILE"

# 哑值（**非真凭据**）：只用大写字母且与键名/环境变量名无共同 3 字窗——反查明文用。
MODEL_DUMMY = "ZKQXJVBWMPLRTNFHGDWY"
TOKEN_DUMMY = "QVBNZKXRTLMHWGDSJCPF"
TOKEN_FILE_DUMMY = "JWHZQXMVKBTGRDLSNFPC"

# 判据面环境键：每条 check 前一律剥掉再按需设值——本机真实 env（若配了真 token/key）
# 不得泄漏进判据，否则同一份代码在本机与 CI 得两个结论。
_SCRUB = ("HIVE_CONFIG", "HIVE_JOBS_DIR", "HIVE_ORCH_TOKEN", TOKEN_FILE_KEY,
          "HIVE_API_KEY")

# HEAD（三键链）下**应当**为红的项：A/C1/E/H 组分叉项，其余 6 项两态皆绿。
EXPECTED_RED = ("A1", "A2", "A3", "A4", "C1", "E1", "E2", "E3", "H1", "H2", "H3")


class _EnvScrub:
    """剥掉 `_SCRUB` 五键后按需设值；退出逐键恢复（原本不存在的键恢复为删除）。"""

    def __init__(self, **kv):
        self.kv = kv
        self.saved: dict[str, str | None] = {}

    def __enter__(self):
        for k in _SCRUB:
            self.saved[k] = os.environ.pop(k, None)
        for k, v in self.kv.items():
            if v is not None:
                os.environ[k] = v
        return self

    def __exit__(self, *_exc):
        for k in _SCRUB:
            os.environ.pop(k, None)
        for k, v in self.saved.items():
            if v is not None:
                os.environ[k] = v
        return False


def _fake_repo(tmp: str, source_bytes: bytes) -> str:
    """在临时目录搭「假仓」：repo/hive/hive_mcp/mcp_server.py + repo/hive/serve_start.py。

    为什么用假仓而不是原地 import 真文件：
      `mcp_server` 用 `__file__` 三级上溯求 REPO/HIVE_DIR（`mcp_server.py:76-77`），
      `_load_local_config` 又从 HIVE_DIR `import serve_start`（`:98-107`）——HEAD 副本
      放进临时目录后这两处仍须解析得到；落点放临时目录同时保证 `__pycache__` 与相对
      路径全部落在临时面内（真仓 `hive_mcp/__pycache__` 不被本守卫写入）。
      `serve_start.py` **逐字节复制**自真仓：同一解析函数（`load_config`/`resolve`），
      不是第二套实现。
    """
    root = os.path.join(tmp, "repo")
    pkg = os.path.join(root, "hive", "hive_mcp")
    os.makedirs(pkg, exist_ok=True)
    with open(os.path.join(pkg, "mcp_server.py"), "wb") as f:
        f.write(source_bytes)
    shutil.copyfile(os.path.join(_HERE, "serve_start.py"),
                    os.path.join(root, "hive", "serve_start.py"))
    return root


def _load(root: str, name: str):
    """按假仓路径装载 mcp_server（`__file__` 落假仓 ⇒ REPO/HIVE_DIR 同步落假仓）。"""
    sys.modules.pop("serve_start", None)   # 环归属由本次 HIVE_DIR 决定，不吃上一轮的缓存
    path = os.path.join(root, "hive", "hive_mcp", "mcp_server.py")
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _mk_config(tmp: str, name: str, obj: dict) -> str:
    p = os.path.join(tmp, name)
    with open(p, "w", encoding="utf-8") as f:
        json.dump(obj, f)
    return p


def _submit_status(mod, jobs: str, spec: dict) -> dict:
    """走真实提交路径 `_submit`（含 `result_nonce` 决策）并回读落盘 status.json。"""
    jid = mod._submit(jobs, spec)
    with open(os.path.join(jobs, jid, "status.json"), encoding="utf-8") as f:
        return json.load(f)


def _rust_chain() -> tuple:
    """从 Rust 真源现场解析锚链两环（`env("…")` 按出现序）——不抄一份常量。"""
    src = open(os.path.join(_HERE, "src", "keyres.rs"), encoding="utf-8").read()
    body = src.split("pub fn resolve_key_from_env", 1)[1].split("\n#[cfg(test)]", 1)[0]
    return tuple(re.findall(r'env\("([A-Z_]+)"\)', body))


def _anchor_region(src: str) -> str:
    """锚链段文本：`P11 结果完整性锚密钥链` 注释 → `_submit` 之前（键集+函数本体）。"""
    return src[src.index("P11 结果完整性锚密钥链"):
               src.index("# 生效条件：jobs 与 spec 给定")]


def _docstring_of(src: str, fname: str) -> str:
    i = src.index(f"def {fname}(")
    j = src.index('"""', i)
    return src[j + 3:src.index('"""', j + 3)]


def run_checks(source_bytes: bytes) -> list[tuple[str, bool, str]]:
    """对给定 mcp_server.py 源字节跑全套 check → [(id, ok, detail)]，全临时目录。"""
    out: list[tuple[str, bool, str]] = []
    # 行为面与文案面**同一份字节**（H 组不另读真仓文件——否则基线态会拿工作区文本
    # 去判 HEAD 行为，绿/红两态结论错位）
    src = source_bytes.decode("utf-8")

    def add(cid, ok, detail=""):
        out.append((cid, bool(ok), detail))

    tmp = tempfile.mkdtemp(prefix="n190_anchor_")
    try:
        root = _fake_repo(tmp, source_bytes)
        tok_path = os.path.join(tmp, "tok.txt")
        with open(tok_path, "w", encoding="utf-8") as f:
            f.write(f"  {TOKEN_FILE_DUMMY}  \n")
        cfg_model = _mk_config(tmp, "cfg_model.json", {"HIVE_API_KEY": MODEL_DUMMY})
        cfg_tok = _mk_config(tmp, "cfg_tok.json",
                             {"HIVE_ORCH_TOKEN": TOKEN_DUMMY})
        cfg_tokfile_ref = _mk_config(
            tmp, "cfg_tokfile_ref.json", {TOKEN_FILE_KEY: {"file": tok_path}})
        cfg_tokfile_raw = _mk_config(
            tmp, "cfg_tokfile_raw.json", {TOKEN_FILE_KEY: tok_path})
        cfg_absent = os.path.join(tmp, "不存在.json")
        SPEC = {"model": "dummy-model", "user_prompt": "dummy-prompt"}

        def probe(cid, env_kv, fn):
            """在给定环境面下装载 mcp_server 并执行 fn(mod)→(ok, detail)。"""
            with _EnvScrub(**env_kv):
                try:
                    mod = _load(root, f"n190_mcp_{cid}")
                except Exception as e:  # noqa: BLE001
                    return False, f"装载失败 {type(e).__name__}: {e}"
                try:
                    return fn(mod)
                except Exception as e:  # noqa: BLE001
                    return False, f"探针异常 {type(e).__name__}: {e}"

        def jobs_for(cid):
            d = os.path.join(tmp, f"jobs_{cid}")
            os.makedirs(d, exist_ok=True)
            return d

        # ---------------- [A] 只配模型密钥 → 锚判据不启用（旧格式回退）
        def a1(mod):
            k = mod._result_anchor_key()
            return k is None, f"key={k!r}（模型密钥不得再作锚）"
        ok, d = probe("A1", {"HIVE_CONFIG": cfg_model}, a1)
        add("A1", ok, d)

        def a2(mod):
            st = _submit_status(mod, jobs_for("A2"), SPEC)
            return ("result_nonce" not in st and st.get("state") == "pending"
                    and st.get("job_id"), f"status 键={sorted(st)}")
        ok, d = probe("A2", {"HIVE_CONFIG": cfg_model}, a2)
        add("A2", ok, d)

        def a3(mod):
            k = mod._result_anchor_key()
            return k is None, f"key={k!r}（env 形态同判）"
        ok, d = probe("A3", {"HIVE_CONFIG": cfg_absent,
                             "HIVE_API_KEY": MODEL_DUMMY}, a3)
        add("A3", ok, d)

        def a4(mod):
            st = _submit_status(mod, jobs_for("A4"), SPEC)
            return "result_nonce" not in st, f"status 键={sorted(st)}"
        ok, d = probe("A4", {"HIVE_CONFIG": cfg_absent,
                             "HIVE_API_KEY": MODEL_DUMMY}, a4)
        add("A4", ok, d)

        # ---------------- [B] 身份令牌直值环（env / config）
        def b1(mod):
            k = mod._result_anchor_key()
            return k == TOKEN_DUMMY, f"key={k!r}"
        ok, d = probe("B1", {"HIVE_CONFIG": cfg_absent,
                             "HIVE_ORCH_TOKEN": TOKEN_DUMMY}, b1)
        add("B1", ok, d)

        def b2(mod):
            st = _submit_status(mod, jobs_for("B2"), SPEC)
            n = st.get("result_nonce")
            return (isinstance(n, str) and len(n) == 32
                    and re.fullmatch(r"[0-9a-f]{32}", n) is not None
                    and n != TOKEN_DUMMY), f"nonce={n!r}"
        ok, d = probe("B2", {"HIVE_CONFIG": cfg_absent,
                             "HIVE_ORCH_TOKEN": TOKEN_DUMMY}, b2)
        add("B2", ok, d)

        def b3(mod):
            k = mod._result_anchor_key()
            return k == TOKEN_DUMMY, f"key={k!r}"
        ok, d = probe("B3", {"HIVE_CONFIG": cfg_tok}, b3)
        add("B3", ok, d)

        # ---------------- [C] 令牌文件环
        def c1(mod):
            k = mod._result_anchor_key()
            return (k == TOKEN_FILE_DUMMY,
                    f"key={k!r}（env 形态须读文件全文 strip；旧码返回路径串→红）")
        ok, d = probe("C1", {"HIVE_CONFIG": cfg_absent,
                             TOKEN_FILE_KEY: tok_path}, c1)
        add("C1", ok, d)

        def c2(mod):
            st = _submit_status(mod, jobs_for("C2"), SPEC)
            n = st.get("result_nonce")
            return (isinstance(n, str) and len(n) == 32,
                    f"nonce={n!r} status 键={sorted(st)}")
        ok, d = probe("C2", {"HIVE_CONFIG": cfg_absent,
                             TOKEN_FILE_KEY: tok_path}, c2)
        add("C2", ok, d)

        def c3(mod):
            k = mod._result_anchor_key()
            return k == TOKEN_FILE_DUMMY, f"key={k!r}（config {{\"file\":…}} 形态）"
        ok, d = probe("C3", {"HIVE_CONFIG": cfg_tokfile_ref}, c3)
        add("C3", ok, d)

        def c4(mod):
            k = mod._result_anchor_key()
            st = _submit_status(mod, jobs_for("C4"), SPEC)
            return (k is not None and isinstance(st.get("result_nonce"), str),
                    f"key non-None={k is not None} nonce={st.get('result_nonce')!r}"
                    "（config 直值路径形态：判据面只问『锚是否启用』）")
        ok, d = probe("C4", {"HIVE_CONFIG": cfg_tokfile_raw}, c4)
        add("C4", ok, d)

        # ---------------- [E] 键集结构 = Rust 两环同链同序
        def e1(mod):
            got = tuple(mod._RESULT_KEY_KEYS)
            want = _rust_chain()
            return got == want, f"python={got} rust={want}"
        ok, d = probe("E1", {"HIVE_CONFIG": cfg_absent}, e1)
        add("E1", ok, d)

        def e2(mod):
            return "HIVE_API_KEY" not in mod._RESULT_KEY_KEYS, \
                f"keys={tuple(mod._RESULT_KEY_KEYS)}"
        ok, d = probe("E2", {"HIVE_CONFIG": cfg_absent}, e2)
        add("E2", ok, d)

        def e3(mod):
            direct = tuple(getattr(mod, "_ENV_DIRECT_KEYS", ()))
            ok_ = direct == ("HIVE_ORCH_TOKEN",) and TOKEN_FILE_KEY not in direct
            return ok_, f"_ENV_DIRECT_KEYS={direct}（文件环键不得入 env 直值环）"
        ok, d = probe("E3", {"HIVE_CONFIG": cfg_absent}, e3)
        add("E3", ok, d)

        # ---------------- [H] 文案口径（键集段 + docstring）
        region = _anchor_region(src)
        add("H1", "三键" not in region,
            "锚链段仍含『三键』："
            f"{[l for l in region.splitlines() if '三键' in l][:1]}")
        ds = _docstring_of(src, "_result_anchor_key")
        add("H2",
            "keyres::resolve_key_from_env" in ds and "N190" in ds
            and "不再兜底" in ds,
            "docstring 须保留『与 rust keyres::resolve_key_from_env 同链』并标注"
            f"「N190：模型密钥不再兜底」；现 docstring={ds.strip()[:90]!r}")
        add("H3", ("两键" in region) or ("两环" in region),
            "锚链段须给出『两键/两环』的正向口径")
        # 结构面回归：改动只应落在键集与文案——`_submit` 的 nonce 决策点仍在原位
        add("H4",
            "nonce = uuid.uuid4().hex if _result_anchor_key() is not None" in src,
            "`_submit` 的锚启用判据（is not None）被改动或消失")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return out


def _head_source_bytes() -> bytes:
    r = subprocess.run(["git", "show", f"HEAD:{MCP_REL}"], cwd=_REPO,
                       capture_output=True)
    if r.returncode != 0:
        raise SystemExit(f"git show HEAD:{MCP_REL} 失败："
                         f"{r.stderr.decode('utf-8', 'replace')[:200]}")
    return r.stdout


def main() -> int:
    ap = argparse.ArgumentParser(description="结果完整性锚密钥链同源守卫（N190）")
    ap.add_argument("--head-baseline", action="store_true",
                    help="用 git HEAD 版 mcp_server.py 覆盖临时副本取红基线"
                         "（断言红项集合 == 预期分叉集）")
    args = ap.parse_args()

    if args.head_baseline:
        src_bytes = _head_source_bytes()
        print(f"[红基线] 源 = git HEAD:{MCP_REL}（写入临时假仓，不覆盖工作区文件）")
    else:
        src_bytes = open(os.path.join(_HERE, "hive_mcp", "mcp_server.py"),
                         "rb").read()
        print(f"[绿态] 源 = 工作区 {MCP_REL}")

    results = run_checks(src_bytes)
    reds = [cid for cid, ok, _ in results if not ok]
    for cid, ok, detail in results:
        print(f"  {'OK  ' if ok else 'FAIL'} {cid}"
              + ("" if ok else f"  {detail}"))

    print(f"\n结果：{len(results) - len(reds)} pass / {len(reds)} fail"
          f"（红项：{', '.join(reds) if reds else '无'}）")
    if args.head_baseline:
        if tuple(reds) == EXPECTED_RED:
            print("红基线符合预期：HEAD 三键链在与 Rust 两环同链面共 11 项分叉"
                  f"（{'、'.join(EXPECTED_RED)}）")
            return 0
        print("红基线与预期不符——预期红项：" + "、".join(EXPECTED_RED))
        return 1
    if reds:
        print("FAILED：" + "、".join(reds))
        return 1
    print("ALL OK：锚密钥链两侧同键同序，模型密钥不再作锚")
    return 0


if __name__ == "__main__":
    sys.exit(main())
