# -*- coding: utf-8 -*-
# 功能名：paths.json 解析失败时不得无声回落默认记忆库（issue #352-D）
# 生效条件：python -X utf8 -m md_cg.test_issue352_pathsjson [--mutate]；被测面=md_cg/datapath.py 的 _read_user_paths/_user_paths/mdcg_root/data_root/set_user_root + src/lib/datapath.ts 的 readUserPaths/mdcgRoot
# 子功能：A 组=UTF-8 BOM 与非法转义两类常见写坏在 Python 侧与插件侧都不得无声回落；K 组=非恒真对照（合法配置照常生效、无文件时仍回落默认库、三态口径、set_user_root 不冲掉其余键、原子写）；E 组=源码面单点
# 执行：每个变体建独立临时沙箱，先在自定义根写一条既有记忆，再写 paths.json（合法/BOM/非法转义/错形状），用子进程读 mdcg_root()+MdCGOS；插件侧用 node 直接 import src/lib/datapath.ts
# 验证方式：全部 PASS 即通过；--mutate 走镜像树定点变异，变异后红项必须**恰为**预期集合
# 不适用条件：①**坏配置 ⇒ 插件激活失败与各 CLI 退出是刻意的 fail-closed 选择**（本处按 #161 先例：静默回落会造成「原有记忆消失 + 新写入分叉」的数据分叉，比「起不来」严重）；退路（console.error + describeDataPaths/op=info 点名后回落）实现成本一处——PathsConfigError 的 code/pathsFile 已留好——**是否切换归维护者裁定**，本守卫两种口径下都成立（断言只要求「不静默」）②不判路径本身是否合法/可建（保留设备名由 _abs_host_path 另管，见 test_issue354_p2_datapath_clock）③不判 paths.json 的取值优先级（env > paths.json > 默认，既有面未改）
"""issue #352-D 守卫：坏 paths.json 不得无声回落默认库。

病象（修前）：Python `_user_paths()` 与插件 `readUserPaths()` 都用一个「吞掉
一切异常的 except」把「文件不存在」与「文件存在但坏了」混成同一个 `{}`——于是
`mcg_root()` 无声回落到默认库：用户看到「原有记忆没了」，新写入分叉进另一个库
（插件侧仍按 config 走，两边就此分成两个库）。Windows 上两种常见写坏：
  · 记事本 / PowerShell 5 的 `Set-Content -Encoding UTF8` 写出 UTF-8 BOM；
  · 照抄资源管理器路径时反斜杠未转义——Windows 路径分隔符在 JSON 串里
    必须写成双反斜杠或改用正斜杠，单写即非法转义序列。

处置（**响亮失败**，本仓先例 #161「打包面静默坏包 ⇒ 改为响亮失败」，Lead 本轮
指定按同一精神）：
  1. BOM 属编码形态而非语法错 ⇒ 两侧都剥掉（Python `utf-8-sig`、TS
     `replace(/^\uFEFF/, '')`），**能解析就正常生效**——不是「有 BOM 就报错」
     （K3 就是这条的口径对照，M2 证明它有判别力）；
  2. 真正解析不了（含顶层非对象）⇒ 抛 `PathsConfigError`，绝不回落；
  3. `set_user_root` 读到坏文件时**拒绝写**（改前会用空表覆写，把用户其余键
     一并冲掉），落盘改走 `fsutil.atomic_write`（改前非原子，崩溃留下的截断件
     正是下一条「解析失败」的来源）。

★**过度收紧方向**：K1（合法配置照常生效）、K2（无文件时仍回落默认库）、
K6（TS 侧无文件时仍回落）三条盯住「修复没把正常面一起关掉」。
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _REPO)
from md_cg import datapath as _dp                          # noqa: E402

FAILS = []
_SKIPPED = []
_TMP = tempfile.mkdtemp(prefix="iss352d_")
_NODE = shutil.which("node")


def _check(name, cond, detail=""):
    if cond:
        print("  PASS " + name)
    else:
        print("  FAIL " + name + "  " + str(detail)[:400])
        FAILS.append(name)


_SEED = (
    "import sys; sys.path.insert(0, sys.argv[1]);"
    "from md_cg.mdcos import MdCGOS;"
    "c = MdCGOS(sys.argv[2], autoflush=1);"
    "c.add('old_pref', 'PASSED 旧偏置：用户对花生过敏', layer='knowledge');"
    " c.close()")

_CHILD = '''
import json, sys
sys.path.insert(0, sys.argv[1])
out = {"raised": None, "root": None, "configured": None, "seen": None,
       "msg_ok": None}
try:
    from md_cg import datapath
except Exception as e:
    out["raised"] = "import:" + type(e).__name__
    print(json.dumps(out, ensure_ascii=False)); raise SystemExit(0)
try:
    out["root"] = datapath.mdcg_root()
    out["configured"] = datapath.mdcg_root_configured()
    from md_cg.mdcos import MdCGOS
    cg = MdCGOS(out["root"], autoflush=1)
    out["seen"] = bool(cg.get("old_pref"))
    cg.close()
except datapath.PathsConfigError as e:
    out["raised"] = "PathsConfigError"
    out["msg_ok"] = ("paths.json" in str(e))
except Exception as e:
    out["raised"] = type(e).__name__
print(json.dumps(out, ensure_ascii=False))
'''

_NODEJS = '''
import { pathToFileURL } from 'node:url'
const mod = await import(pathToFileURL(process.argv[2]).href)
const out = { raised: null, root: null, msg_ok: null }
try {
  out.root = mod.mdcgRoot('')
} catch (e) {
  out.raised = e.name
  out.msg_ok = String(e.message).includes('paths.json')
}
console.log(JSON.stringify(out))
'''


def _py_env(t, extra=None):
    env = {k: v for k, v in os.environ.items()
           if not k.startswith(("MDCG_", "DSH_", "PYTHON"))}
    env.update({"HOME": t, "MDCG_STATE_ROOT": os.path.join(t, "state"),
                # 末段不得是 Windows 保留设备名（aux/con/nul…）——_abs_host_path
                # 会据此 fail-closed 拒启（test_issue354_p2_datapath_clock 同一判据）。
                "MDCG_AUX_ROOT": os.path.join(t, "auxstore"), "MDCG_SLEEP": "0",
                "PYTHONUTF8": "1", "PYTHONPATH": _REPO})
    if extra:
        env.update(extra)
    return env


def _py_case(tag, writer, seed=True):
    """跑一个 Python 变体：返回子进程读数 dict（含 testdir）。"""
    t = tempfile.mkdtemp(prefix="iss352d_%s_" % tag, dir=_TMP)
    state = os.path.join(t, "state")
    os.makedirs(state, exist_ok=True)
    custom = os.path.join(t, "MyMemory")
    env = _py_env(t)
    if seed:
        subprocess.run([sys.executable, "-c", _SEED, _REPO, custom], env=env,
                       check=True, capture_output=True)
    writer(os.path.join(state, "paths.json"), custom)
    p = subprocess.run([sys.executable, "-c", _CHILD, _REPO], env=env,
                       capture_output=True, text=True, encoding="utf-8",
                       errors="replace")
    try:
        out = json.loads(p.stdout.strip().splitlines()[-1])
    except Exception:                                      # noqa: BLE001
        out = {"raised": "NOJSON", "stdout": (p.stdout or "")[-160:],
               "stderr": (p.stderr or "")[-160:]}
    out["custom"] = custom
    out["testdir"] = t
    return out


def _w_raw(data, name="paths.json"):
    def _w(pf, custom):
        with open(pf, "wb") as f:
            f.write(data(custom) if callable(data) else data)
    return _w


def _w_obj(fn):
    def _w(pf, custom):
        with open(pf, "w", encoding="utf-8") as f:
            json.dump(fn(custom), f, ensure_ascii=False)
    return _w


def _node_case(tag, mkpaths):
    """跑一个 TS 变体：node 直接 import src/lib/datapath.ts。"""
    if _NODE is None:
        return None
    t = tempfile.mkdtemp(prefix="iss352d_%s_" % tag, dir=_TMP)
    state = os.path.join(t, "state")
    os.makedirs(state, exist_ok=True)
    custom = os.path.join(t, "MyMemory")
    js = os.path.join(_TMP, "ts_%s.mjs" % tag)
    with open(js, "w", encoding="utf-8") as f:
        f.write(_NODEJS)
    if mkpaths is not None:
        mkpaths(os.path.join(state, "paths.json"), custom)
    env = {k: v for k, v in os.environ.items()
           if k not in ("MDCG_ROOT", "MDCG_DATA_ROOT")}
    env["MDCG_STATE_ROOT"] = state
    p = subprocess.run([_NODE, js, os.path.join(_REPO, "src", "lib",
                                                "datapath.ts")],
                       capture_output=True, text=True, encoding="utf-8",
                       errors="replace", env=env, cwd=_REPO)
    try:
        out = json.loads(p.stdout.strip().splitlines()[-1])
    except Exception:                                      # noqa: BLE001
        out = {"raised": "NOJSON", "stdout": (p.stdout or "")[-160:],
               "stderr": (p.stderr or "")[-200:]}
    out["custom"] = custom
    return out


def _same(a, b):
    return bool(a) and os.path.normcase(os.path.abspath(a)) == \
        os.path.normcase(os.path.abspath(b))


_BOM = lambda c: b"\xef\xbb\xbf" + json.dumps({"root": c}).encode("utf-8")


def _bad_escape(c):
    # 未转义反斜杠：\M 非法转义（照抄资源管理器路径的常见形态）
    return ('{"root": "%s"}' % c.replace(os.sep, "\\")).encode("utf-8")


print("== A 组：坏/带 BOM 的 paths.json 不得无声回落 ==")

# --- D1：UTF-8 BOM + 合法 JSON ⇒ BOM 属编码形态，应正常生效（不是「有 BOM 就报错」）
_d1 = _py_case("d1", _w_raw(_BOM))
print("   [读数] D1 BOM 合法配置 → raised=%s root==custom=%s 既有记忆可读=%s"
      % (_d1.get("raised"), _same(_d1.get("root"), _d1["custom"]),
         _d1.get("seen")))
_check("D1 UTF-8 BOM 的 paths.json：正常生效（root==自定义根、既有记忆读得到），"
       "不回落默认库",
       _d1.get("raised") is None and _same(_d1.get("root"), _d1["custom"])
       and _d1.get("configured") is True and _d1.get("seen") is True, _d1)

# --- D2：非法转义（真语法错）⇒ 响亮失败，不静默回落
_d2 = _py_case("d2", _w_raw(_bad_escape))
print("   [读数] D2 非法转义 → raised=%s 消息含 paths.json=%s root=%s"
      % (_d2.get("raised"), _d2.get("msg_ok"), _d2.get("root")))
_check("D2 非法转义的 paths.json：响亮失败（PathsConfigError，消息点名 paths.json），"
       "**不**静默回落到默认库",
       _d2.get("raised") == "PathsConfigError" and _d2.get("msg_ok") is True
       and _d2.get("root") is None, _d2)

# --- D4：合法 JSON、错形状（顶层数组）⇒ 同一口径响亮失败
_d4 = _py_case("d4", _w_raw(b'["not", "an", "object"]'))
print("   [读数] D4 顶层数组 → raised=%s" % _d4.get("raised"))
_check("D4 顶层非 JSON 对象：同一口径响亮失败（不按「解析成功」放行）",
       _d4.get("raised") == "PathsConfigError" and _d4.get("root") is None, _d4)

# --- D3/D5/K6：插件侧（node 直接 import src/lib/datapath.ts）
_ts_bom = _node_case("tsbom", _w_raw(_BOM))
_ts_bad = _node_case("tsbad", _w_raw(b'{"root": '))
_ts_none = _node_case("tsnone", None)
if _ts_bom is None:
    _SKIPPED.append("D3/D5/K6")
    print("  [跳过] 插件侧腿：本机无 node")
else:
    print("   [读数] D3 TS BOM → raised=%s root==custom=%s"
          % (_ts_bom.get("raised"), _same(_ts_bom.get("root"), _ts_bom["custom"])))
    _check("D3 插件侧 UTF-8 BOM 的 paths.json：正常生效（root==自定义根）",
           _ts_bom.get("raised") is None
           and _same(_ts_bom.get("root"), _ts_bom["custom"]), _ts_bom)
    print("   [读数] D5 TS 语法错 → raised=%s 消息含 paths.json=%s"
          % (_ts_bad.get("raised"), _ts_bad.get("msg_ok")))
    _check("D5 插件侧无法解析的 paths.json：抛 PathsConfigError（不无声回落默认根）",
           _ts_bad.get("raised") == "PathsConfigError"
           and _ts_bad.get("msg_ok") is True and _ts_bad.get("root") is None,
           _ts_bad)

# ========================================================= K 组：非恒真对照
print("== K 组：非恒真对照（含**过度收紧**方向）==")

# --- K1：合法 paths.json 正常生效（不过度收紧）
_k1 = _py_case("k1", _w_obj(lambda c: {"root": c}))
print("   [读数] K1 合法配置 → root==custom=%s configured=%s seen=%s"
      % (_same(_k1.get("root"), _k1["custom"]), _k1.get("configured"),
         _k1.get("seen")))
_check("K1 合法 paths.json 照常生效（root==自定义根、既有记忆读得到、无异常）",
       _k1.get("raised") is None and _same(_k1.get("root"), _k1["custom"])
       and _k1.get("configured") is True and _k1.get("seen") is True, _k1)

# --- K2：**没有** paths.json 时必须照旧回落默认库（过度收紧方向）
_k2 = _py_case("k2", lambda pf, custom: None, seed=False)
_k2_dflt = os.path.join(_k2["testdir"], "state", "data", "mdcg")
print("   [读数] K2 无配置文件 → raised=%s root=%s"
      % (_k2.get("raised"), _k2.get("root")))
_check("K2 无 paths.json（文件不存在）时仍回落默认库——不把「没配过」也判成坏配置",
       _k2.get("raised") is None and _same(_k2.get("root"), _k2_dflt)
       and _k2.get("configured") is False, (_k2, _k2_dflt))

# --- K3：三态读取单点（missing / ok / bad 三分，不再混成 {}）
def _states():
    res = {}
    t = tempfile.mkdtemp(prefix="iss352d_k3_", dir=_TMP)
    state = os.path.join(t, "state")
    os.makedirs(state)
    old = os.environ.get("MDCG_STATE_ROOT")
    os.environ["MDCG_STATE_ROOT"] = state
    try:
        res["missing"] = _dp._read_user_paths()[1]
        with open(os.path.join(state, "paths.json"), "wb") as f:
            f.write(_BOM(os.path.join(t, "My")))
        res["bom_ok"] = _dp._read_user_paths()[1]
        with open(os.path.join(state, "paths.json"), "wb") as f:
            f.write(_bad_escape(os.path.join(t, "My")))
        res["bad_escape"] = _dp._read_user_paths()[1]
        res["raises"] = None
        try:
            _dp._user_paths()
        except _dp.PathsConfigError:
            res["raises"] = "PathsConfigError"
    finally:
        if old is None:
            os.environ.pop("MDCG_STATE_ROOT", None)
        else:
            os.environ["MDCG_STATE_ROOT"] = old
    return res


_k3 = _states()
print("   [读数] K3 三态=%s 严格读抛=%s" % (_k3, _k3["raises"]))
_check("K3 三态口径单点：missing / ok（BOM 剥得掉）/ bad（真语法错）三分，"
       "且 strict 读对 bad 抛错",
       _k3["missing"] == "missing" and _k3["bom_ok"] == "ok"
       and _k3["bad_escape"] == "bad"
       and _k3["raises"] == "PathsConfigError", _k3)

# --- K4：set_user_root 对坏文件拒写且**不冲掉**其余键
_k4t = tempfile.mkdtemp(prefix="iss352d_k4_", dir=_TMP)
_k4state = os.path.join(_k4t, "state")
os.makedirs(_k4state)
_k4pf = os.path.join(_k4state, "paths.json")
_k4raw = ('{"root": "%s", "extra": "KEEP-ME"}'
          % os.path.join(_k4t, "My")).replace(os.sep, "\\")
with open(_k4pf, "wb") as f:
    f.write(_k4raw.encode("utf-8"))
_old = os.environ.get("MDCG_STATE_ROOT")
os.environ["MDCG_STATE_ROOT"] = _k4state
try:
    try:
        _dp.set_user_root("E:/new", "data_root")
        _k4r = "写了"
    except _dp.PathsConfigError:
        _k4r = "PathsConfigError"
finally:
    if _old is None:
        os.environ.pop("MDCG_STATE_ROOT", None)
    else:
        os.environ["MDCG_STATE_ROOT"] = _old
_k4after = open(_k4pf, "rb").read().decode("utf-8")
print("   [读数] K4 坏文件 set_user_root=%s 原文未动=%s"
      % (_k4r, _k4after == _k4raw))
_check("K4 set_user_root 读到坏文件时拒绝写，且**不冲掉**用户其余键（字节不变）",
       _k4r == "PathsConfigError" and _k4after == _k4raw, (_k4r, _k4after[:60]))

# --- K5：set_user_root 对好文件正常写入、原子落盘可读回
_k5t = tempfile.mkdtemp(prefix="iss352d_k5_", dir=_TMP)
_k5state = os.path.join(_k5t, "state")
os.makedirs(_k5state)
_old = os.environ.get("MDCG_STATE_ROOT")
os.environ["MDCG_STATE_ROOT"] = _k5state
try:
    _w = _dp.set_user_root(os.path.join(_k5t, "My"), "root")
    _d = json.load(open(_w, encoding="utf-8"))
finally:
    if _old is None:
        os.environ.pop("MDCG_STATE_ROOT", None)
    else:
        os.environ["MDCG_STATE_ROOT"] = _old
print("   [读数] K5 写入路径在用户级=%s 键齐=%s"
      % (_w == os.path.join(_k5state, "paths.json"), sorted(_d)))
_check("K5 set_user_root 对好文件正常写入（用户级位置、含 _comment 与目标键、"
       "可解析回来）",
       _w == os.path.join(_k5state, "paths.json")
       and _d.get("root") == os.path.join(_k5t, "My").replace(os.sep, "/")
       and "_comment" in _d, (_w, sorted(_d)))

if _ts_none is not None:
    _ts_dflt = os.path.join(_ts_none["custom"], "..", "state", "data", "mdcg")
    print("   [读数] K6 TS 无配置文件 → raised=%s root=%s"
          % (_ts_none.get("raised"), _ts_none.get("root")))
    _check("K6 插件侧无 paths.json 时仍回落默认根（过度收紧方向）",
           _ts_none.get("raised") is None
           and _same(_ts_none.get("root"), _ts_dflt), _ts_none)

# ========================================================= E 组：源码面单点
print("== E 组：源码面单点 ==")
_dp_src = open(os.path.join(_REPO, "md_cg", "datapath.py"),
               encoding="utf-8").read()
_ts_src = open(os.path.join(_REPO, "src", "lib", "datapath.ts"),
               encoding="utf-8").read()
_check("E1 三态读取是唯一读取点（_user_paths 走 _read_user_paths，两者分开）",
       "def _read_user_paths():" in _dp_src
       and "d, st = _read_user_paths()" in _dp_src
       and "class PathsConfigError(RuntimeError):" in _dp_src)
_check("E2 BOM 口径：Python 侧以 utf-8-sig 读 paths.json",
       'open(pf, encoding="utf-8-sig")' in _dp_src)
_check("E3 插件侧：BOM 剥离 + PathsConfigError 抛出（与 Python 侧同一口径）",
       "replace(/^\\uFEFF/, '')" in _ts_src
       and "export class PathsConfigError extends Error" in _ts_src)
_check("E4 set_user_root 原子落盘（fsutil.atomic_write，不再裸 open('w')）",
       "fsutil.atomic_write(pf," in _dp_src)

shutil.rmtree(_TMP, ignore_errors=True)

print("")
if FAILS:
    print("issue #352-D 结果：%d 失败 → %s" % (len(FAILS), ", ".join(FAILS)))
else:
    print("issue #352-D 结果：全部通过（跳过腿：%s）"
          % (",".join(_SKIPPED) or "无"))

# ------------------------------------------------------------- 定点变异（镜像树）
_MUTATIONS = (
    ("M1 摘掉 Python 侧坏配置的响亮失败（回到静默返回 {}）",
     (("md_cg/datapath.py",
       ['    if st == "bad":',
        '        if strict:',
        '            raise PathsConfigError(_paths_config_message())',
        '        return {}'],
       ['    if st == "bad":',
        '        return {}']),),
     # K3 也红：它断言 strict 读对 bad 抛错（三态单点的行为面）。
     ("D2", "D4", "K3")),
    ("M2 摘掉 BOM 兼容（utf-8-sig 回 utf-8）——把「编码形态」误判成坏配置",
     (("md_cg/datapath.py",
       ['        with open(pf, encoding="utf-8-sig") as f:'],
       ['        with open(pf, encoding="utf-8") as f:']),),
     ("D1", "K3", "E2")),
    ("M3 摘掉 missing 分支（把「文件不存在」也判成坏配置）——过度收紧方向",
     (("md_cg/datapath.py",
       ['    if not os.path.isfile(pf):',
        '        return {}, "missing"'],
       ['    if False:',
        '        return {}, "missing"']),),
     # K3 也红：它的 missing 腿（文件不存在 ⇒ "missing"）被这条变异一起改掉。
     ("K2", "K3")),
    ("M4 摘掉 set_user_root 对坏文件的拒写（回到用空表覆写、冲掉其余键）",
     (("md_cg/datapath.py",
       ['    if st == "bad":',
        '        raise PathsConfigError('],
       ['    if False:',
        '        raise PathsConfigError(']),),
     ("K4",)),
    ("M5 摘掉插件侧 BOM 剥离",
     (("src/lib/datapath.ts",
       ["    parsed = JSON.parse(raw.replace(/^\\uFEFF/, ''))"],
       ["    parsed = JSON.parse(raw)"]),),
     ("D3", "E3")),
    ("M6 摘掉插件侧「文件不存在」短路（把没配过也判成坏配置）——过度收紧方向",
     (("src/lib/datapath.ts",
       ["  if (!existsSync(pf)) return {}"],
       ["  if (false) return {}"]),),
     ("K6",)),
    ("M7 摘掉插件侧解析失败的抛出（回到静默空表回落）",
     (("src/lib/datapath.ts",
       ["    throw new PathsConfigError(pathsConfigMessage(pf, String(e)), pf)"],
       ["    parsed = {}"]),),
     ("D5",)),
)


def _mirror_build():
    dst = tempfile.mkdtemp(prefix="iss352d_mut_")
    for name in ("md_cg", "scripts", "src"):
        src = os.path.join(_REPO, name)
        if os.path.isdir(src):
            shutil.copytree(src, os.path.join(dst, name),
                            ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    for name in sorted(os.listdir(_REPO)):
        p = os.path.join(_REPO, name)
        if os.path.isfile(p) and (name.endswith(".py")
                                  or name in ("package.json", "tsconfig.json")):
            shutil.copy2(p, os.path.join(dst, name))
    return dst


def _nl_of(path):
    with open(path, "rb") as fh:
        raw = fh.read(8192)
    return "\r\n" if b"\r\n" in raw else "\n"


def _run_in(tree):
    env = dict(os.environ)
    env["PYTHONPATH"] = tree
    env["PYTHONUTF8"] = "1"
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    pr = subprocess.run([sys.executable, "-X", "utf8", "-m",
                         "md_cg.test_issue352_pathsjson"],
                        capture_output=True, text=True, encoding="utf-8",
                        errors="replace", cwd=tree, env=env, timeout=1800)
    out = (pr.stdout or "") + (pr.stderr or "")
    reds = [ln.split("FAIL ", 1)[1].strip()
            for ln in out.splitlines() if "FAIL " in ln]
    return pr.returncode, reds, out


def _mutate():
    print("!! 定点变异自证：把修复点改回改动前形态，守卫必须转红")
    tree = _mirror_build()
    try:
        rc, reds, out = _run_in(tree)
        print("  未变异镜像基线：rc=%d 红项=%d（必须 rc=0 且 0 红）" % (rc, len(reds)))
        if rc != 0 or reds:
            print(chr(10).join(out.splitlines()[-30:]))
        for ln in out.splitlines():
            if "[读数]" in ln:
                print("  修后读数（未变异镜像）：" + ln.strip())
        okc, bad = 0, []
        for desc, edits, exp in _MUTATIONS:
            backups, miss = [], []
            for rel, oldp, newp in edits:
                p = os.path.join(tree, rel)
                nl = _nl_of(p)
                old, new = nl.join(oldp), nl.join(newp)
                with open(p, encoding="utf-8", newline="") as fh:
                    t = fh.read()
                if t.count(old) != 1:
                    miss.append("%s —— 锚点命中 %d 次" % (rel, t.count(old)))
                    continue
                backups.append((p, t))
                with open(p, "w", encoding="utf-8", newline="") as fh:
                    fh.write(t.replace(old, new, 1))
            if miss:
                bad.append("%s —— %s" % (desc, "；".join(miss)))
                print("  ANCHOR-MISS " + desc)
                for p, t in backups:
                    with open(p, "w", encoding="utf-8", newline="") as fh:
                        fh.write(t)
                continue
            rc2, reds2, out2 = _run_in(tree)
            for p, t in backups:
                with open(p, "w", encoding="utf-8", newline="") as fh:
                    fh.write(t)
            hit = sorted({e for r in reds2 for e in exp if r.startswith(e + " ")})
            if rc2 != 0 and hit == sorted(exp) and len(reds2) == len(exp):
                okc += 1
                print("  OK   %s  红项=%d 指定命中=%d/%d"
                      % (desc, len(reds2), len(hit), len(exp)))
            else:
                bad.append(desc)
                print("  MISMATCH %s  红项=%d 指定命中=%d/%d rc=%d"
                      % (desc, len(reds2), len(hit), len(exp), rc2))
                for r in reds2[:14]:
                    print("        FAIL " + r)
        print("定点变异自证：%s（%d 条不合格）"
              % ("PASS" if not bad else "FAIL", len(bad)))
        for b in bad:
            print("  不合格：" + b)
    finally:
        shutil.rmtree(tree, ignore_errors=True)


def main():
    if "--mutate" in sys.argv:
        _mutate()
        return 1 if FAILS else 0
    return 0 if not FAILS else 1


if __name__ == "__main__":
    sys.exit(main())
