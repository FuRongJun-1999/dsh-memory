# -*- coding: utf-8 -*-
r"""图像 Skill（Image Skill）· L1 能力子系统 · **本版最小实现（3 op）**。

契约真源：`docs/eval/图像Skill_接口契约_设计_v0.1.md` §九 定稿（2026-10-07，十项裁定）。
本模块按该定稿实现；凡定稿未逐字给出、需本实现自补之处，一律在 docstring 内标
「**本版解释**」，并列入交付说明的「待核实」清单——不自作主张改判契约。

本版范围（**只做三个 op**，其余留白）：
  * `inspect`  读元数据（format/width/height/bytes/mode/bit_depth/sha256）
  * `resize`   改尺寸（`width`/`height`/`filter`）
  * `convert`  转格式（`format`）

定稿 §五 表内其余 10 个 edit op（`thumbnail`/`crop`/`rotate`/`flip`/`flop`/
`adjust`/`blur`/`sharpen`/`composite`/`mask`）与 `export`/`extract`、L1 检测类、
L2 生成类**本版一律不做**：`op` 命中这些名字时返回 `E_UNSUPPORTED_OP`
（**「本版范围外」，不是出错**——见 §九-#5「协议面冻结在即，不因新能力扩大 op 面」）。

设计边界（沿定稿「实现边界」与 G5/G6/G7）：
  * **不碰资格/信任/写入面**——本模块**零 md_cg import**（连 `.fsutil` 也不引），
    只依赖标准库 + 后端（`magick` CLI / Pillow）。结构断言见 `test_imgskill.py` G5①。
  * **产物一律落调用方显式给的沙箱根**：无隐式默认根，未给即拒（§九-#8）。
  * **禁用裸 `convert`**：Windows 上 `convert` 恒解析到系统盘卷转换工具，不是
    ImageMagick；ImageMagick 侧一律走 `magick`（§3.5 + §六-G6 硬门）。
  * **错误一律 fail-closed**：环境/探测/参数错误都落明确错误码，绝不返回 `ok=true`。

错误码（定稿 §九-#9 八码 + 本版两个自补码）：
  `E_NOINPUT`｜`E_UNSUPPORTED_FORMAT`｜`E_TOOL_MISSING`｜`E_PERM`｜
  `E_PATH_OUT_OF_SCOPE`｜`E_BAD_PARAM`｜`E_BACKEND_FAIL`｜`E_DECODE`
  ＋ `E_LEVEL_DOWNGRADE`（定稿 §3.1「等级不可降级」点名，E7 面）
  ＋ `E_UNSUPPORTED_OP`（**本版新增**：op 属「本版范围外」，非出错）

幂等口径（定稿 §九-#6）：**像素级必达、位级可选**——同输入同参 → **像素相等**即判
幂等；位级恒等**不设为门**。实现手段仍用 `-strip`（magick）/ 不写 exif（Pillow），
故位级在本机**通常也相等**，但那不是门。

审计（定稿 §四）：每次操作（成功/失败皆然）往 `<根>/.imgskill/audit.jsonl` 追一行，
公共字段逐项在场；降级换后端时额外落 `backend_note`（§九-#11「降级必须落审计字段」）。

无 CLI：本模块只作库用；跑法见 `python -m md_cg.test_imgskill`。
"""
from __future__ import annotations

import hashlib
import json
import os
import platform
import shutil
import subprocess
import sys
import time

__all__ = [
    "run", "OPS_IMPL", "OPS_KNOWN", "LEVEL_MAP", "ERROR_CODES",
    "derive_level", "resolve_magick", "resolve_backend", "read_audit",
    "AUDIT_REL", "audit_path",
]

# ---------------------------------------------------------------- 常量

L0, L1, L2 = "L0", "L1", "L2"
_LEVEL_ORDER = {L0: 0, L1: 1, L2: 2}

#: 本版**实际实现**的 op（定稿 §五 表内的确定性、无模型子集的三件）
OPS_IMPL = ("inspect", "resize", "convert")

#: op → 派生等级（定稿 §五 表 + 其「不做的操作」表的 L1/L2 类，逐条照抄）。
#: 命中即「本版范围外」：L0 的其余 edit op 与 L1/L2 类在本版都返回 E_UNSUPPORTED_OP，
#: 但**等级映射先于实现面判定**（见 run 的校验次序注释）——否则「等级降级」无从判别。
LEVEL_MAP = {
    # —— 定稿 §五 表（edit 子集，全 L0）——
    "inspect": L0, "resize": L0, "thumbnail": L0, "crop": L0, "rotate": L0,
    "flip": L0, "flop": L0, "convert": L0, "adjust": L0, "blur": L0,
    "sharpen": L0, "composite": L0, "mask": L0, "export": L0, "extract": L0,
    # —— 定稿 §五「不做的操作」表的 L1 类（需模型 + model_version）——
    "detect": L1, "segment": L1, "ocr": L1, "bg_remove": L1,
    # —— 定稿 §五「不做的操作」表的 L2 类（生成式，走云）——
    "generate": L2, "inpaint": L2, "outpaint": L2, "style_transfer": L2,
    "i2i": L2,
}

#: 本版已知的全部 op 名（实现面 + 留白面）；不在此表 = 未知 op → E_UNSUPPORTED_OP
OPS_KNOWN = tuple(LEVEL_MAP)

E_NOINPUT = "E_NOINPUT"
E_UNSUPPORTED_FORMAT = "E_UNSUPPORTED_FORMAT"
E_TOOL_MISSING = "E_TOOL_MISSING"
E_PERM = "E_PERM"
E_PATH_OUT_OF_SCOPE = "E_PATH_OUT_OF_SCOPE"
E_BAD_PARAM = "E_BAD_PARAM"
E_BACKEND_FAIL = "E_BACKEND_FAIL"
E_DECODE = "E_DECODE"
E_LEVEL_DOWNGRADE = "E_LEVEL_DOWNGRADE"   # 定稿 §3.1
E_UNSUPPORTED_OP = "E_UNSUPPORTED_OP"     # 本版自补（范围外）

ERROR_CODES = (
    E_NOINPUT, E_UNSUPPORTED_FORMAT, E_TOOL_MISSING, E_PERM,
    E_PATH_OUT_OF_SCOPE, E_BAD_PARAM, E_BACKEND_FAIL, E_DECODE,
    E_LEVEL_DOWNGRADE, E_UNSUPPORTED_OP,
)

#: 审计台账相对沙箱根的落点（**本版解释**：定稿 §四只说「审计台账」，未给路径；
#: 沙箱根是调用方所有，台账随之落根内，不另开全局面）
AUDIT_REL = os.path.join(".imgskill", "audit.jsonl")

#: 后端可读写面（**本版解释**：定稿 §3.3 E_UNSUPPORTED_FORMAT 说「后端 identify -list
#: format 不含」；本版先以显式白名单实现该判据，等价且可复跑，避免每次探测子进程）
FMT_READ = ("png", "jpg", "jpeg", "webp", "gif", "bmp", "tif", "tiff")
FMT_WRITE = ("png", "jpg", "jpeg", "webp", "gif", "bmp", "tif", "tiff")

#: 扩展名 → 规范格式名（写面）
_EXT2FMT = {
    "png": "PNG", "jpg": "JPEG", "jpeg": "JPEG", "webp": "WEBP",
    "gif": "GIF", "bmp": "BMP", "tif": "TIFF", "tiff": "TIFF",
}
#: 规范格式名 → 扩展名（convert 派生 dst 用）
_FMT2EXT = {"PNG": "png", "JPEG": "jpg", "WEBP": "webp",
            "GIF": "gif", "BMP": "bmp", "TIFF": "tif"}

#: resize 滤波器 → magick `-filter` 名 / Pillow 重采样名（定稿 §五：参数 `filter`）
_FILTERS = {
    "lanczos": ("Lanczos", "LANCZOS"),
    "nearest": ("Point", "NEAREST"),
    "bilinear": ("Triangle", "BILINEAR"),
    "bicubic": ("Catrom", "BICUBIC"),
    "box": ("Box", "BOX"),
    "hamming": ("Hamming", "HAMMING"),
}
DEFAULT_FILTER = "lanczos"   # 定稿 §3.1 示例即 lanczos

#: magick `%[channels]` → 规范 mode（**本版解释**：定稿只给 mode 字段名，未给归一表）
_CH2MODE = {
    "srgb": "RGB", "srgba": "RGBA", "rgb": "RGB", "rgba": "RGBA",
    "gray": "L", "graya": "LA", "cmyk": "CMYK", "cmyka": "CMYKA",
}

#: Pillow mode → 位深（**本版解释**；非常规 mode 回落 8 并留痕，见 _pillow_bit_depth）
_MODE_BITS = {
    "1": 1, "L": 8, "P": 8, "LA": 8, "RGB": 8, "RGBA": 8, "CMYK": 8,
    "YCbCr": 8, "LAB": 8, "HSV": 8, "I": 32, "I;16": 16, "F": 32,
}

_ENV_MAGICK = "IMGSKILL_MAGICK"      # 显式 magick 可执行体路径（或安装目录）
_ENV_HOMES = ("MAGICK_HOME", "ImageMagick_HOME")
_ENV_BACKEND = "IMGSKILL_BACKEND"    # auto(缺省) | magick | pillow
_ENV_PILLOW_OFF = "IMGSKILL_PILLOW"  # "0" → 禁用 Pillow 后端（守卫造 E_TOOL_MISSING 用）
_MAGICK_TIMEOUT = 120.0


# ---------------------------------------------------------------- 错误

class SkillError(Exception):
    """带可判别错误码的内部异常；run() 顶层一网打成结构化出参。"""

    def __init__(self, code, message, detail=None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.detail = detail


def _bad(msg, detail=None):
    return SkillError(E_BAD_PARAM, msg, detail)


# ---------------------------------------------------------------- 路径

def _norm(p):
    return os.path.normcase(os.path.realpath(p))


def _rel(p):
    """相对路径统一回 `/` 分隔（定稿 §3.2 示例写法；UTF-8 文本面跨平台一致）。"""
    return p.replace(os.sep, "/") if isinstance(p, str) else p


def safe_join(root, rel, *, what):
    """把 `rel`（相对沙箱根，UTF-8）解析到根内绝对路径；越界即拒（fail-closed）。

    `rel` 为绝对路径、含 `..`、或经符号链接逃出 → `E_PATH_OUT_OF_SCOPE`
    （定稿 §3.3 + §六-G5③）。
    """
    if not isinstance(rel, str) or not rel.strip():
        raise _bad(f"{what} 必填且须为非空字符串（相对沙箱根）", {"got": repr(rel)})
    root_abs = os.path.realpath(root)
    cand = os.path.realpath(os.path.join(root_abs, rel))
    rn, cn = _norm(root_abs), _norm(cand)
    inside = (cn == rn)
    if not inside:
        try:
            inside = (os.path.commonpath([cn, rn]) == rn)
        except ValueError:          # 异盘 → commonpath 抛错 → 判越界
            inside = False
    if not inside:
        raise SkillError(
            E_PATH_OUT_OF_SCOPE,
            f"{what} 越出沙箱根（规范化后前缀不在根内）",
            {"rel": rel, "resolved": cand})
    return cand


def _check_root(root):
    """沙箱根必须由调用方显式给、且已存在（**不设隐式默认根**，定稿 §九-#8）。"""
    if root is None or (isinstance(root, str) and not root.strip()):
        raise _bad("sandbox_root 必填：不设隐式默认根（定稿 §九-#8 fail-closed）",
                   {"got": repr(root)})
    if not isinstance(root, str):
        raise _bad("sandbox_root 须为字符串路径", {"got": type(root).__name__})
    if not os.path.isdir(root):
        # 不隐式创建、不隐式回落到 %TEMP%——一律拒
        raise SkillError(E_PATH_OUT_OF_SCOPE,
                         "sandbox_root 不存在或不是目录（fail-closed，不隐式创建）",
                         {"root": root})
    return os.path.realpath(root)


def audit_path(root):
    return os.path.join(root, AUDIT_REL)


def read_audit(root):
    """读回台账（守卫/复跑用）。返回 dict 列表；文件不存在返回 []。"""
    p = audit_path(root)
    if not os.path.exists(p):
        return []
    out = []
    with open(p, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    out.append(json.loads(line))
                except ValueError:
                    out.append({"_unparsable": line})
    return out


# ---------------------------------------------------------------- 哈希 / 元数据

def _sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _pillow():
    """惰性取 Pillow（缺失 → E_TOOL_MISSING；不进模块 import 面，G5①）。"""
    if os.environ.get(_ENV_PILLOW_OFF) == "0":
        raise SkillError(E_TOOL_MISSING, "Pillow 后端被 IMGSKILL_PILLOW=0 显式禁用")
    try:
        import PIL
        from PIL import Image
    except Exception as e:                                    # pragma: no cover
        raise SkillError(E_TOOL_MISSING, "Pillow 不可用", {"err": repr(e)})
    return PIL, Image


def _pillow_bit_depth(img):
    b = _MODE_BITS.get(img.mode)
    if b is not None:
        return b
    try:
        from PIL import Image as _I
        base = _I.getmodebase(img.mode)
        return {"1": 1, "L": 8, "I": 32, "F": 32}.get(base, 8)
    except Exception:
        return 8


# ---------------------------------------------------------------- 后端探测

def resolve_magick():
    """解析 `magick` 可执行体（**不得假定它在 PATH**，定稿 §3.5）。

    次序：① env `IMGSKILL_MAGICK`（可执行体或安装目录）→ ② env `MAGICK_HOME` /
    `ImageMagick_HOME` 目录 → ③ `shutil.which("magick")`。皆无 → None。
    **绝不解析 `convert`**（Windows 上那是系统盘卷转换工具，定稿 §3.5）。
    """
    cand = os.environ.get(_ENV_MAGICK)
    if cand:
        p = cand
        if os.path.isdir(p):
            for name in ("magick.exe", "magick"):
                if os.path.isfile(os.path.join(p, name)):
                    return os.path.join(p, name)
        if os.path.isfile(p):
            return p
        return None                      # 显式给了但不在 → 视为不可用（不静默回落）
    for home in _ENV_HOMES:
        d = os.environ.get(home)
        if d and os.path.isdir(d):
            for name in ("magick.exe", "magick"):
                p = os.path.join(d, name)
                if os.path.isfile(p):
                    return p
    return shutil.which("magick")


def _magick_version(exe):
    rc, out, err = _spawn([exe, "-version"])
    txt = (out or "") + (err or "")
    for tok in txt.replace("\n", " ").split():
        # 首个形如 7.1.2-31 / 7.1.2 的串
        if tok[:1].isdigit() and tok.count(".") >= 1:
            return tok.strip(",")
    return "unknown"


def resolve_backend():
    """后端路由：`magick` 优先、Pillow 兜底；降级必须留痕（定稿 §九-#11）。

    返回 `(name, exe, version, note)`；`note` 为降级留痕（None 表示未降级）。
    两后端皆不可用 → `E_TOOL_MISSING`（fail-closed）。
    """
    pin = (os.environ.get(_ENV_BACKEND) or "auto").strip().lower()
    exe = resolve_magick()

    def pillow_ok():
        try:
            _pillow()
            import PIL
            return PIL.__version__
        except SkillError:
            return None
        except Exception:
            return None

    if pin == "magick":
        if exe is None:
            raise SkillError(E_TOOL_MISSING,
                             "后端被钉为 magick 但 magick 不可解析",
                             {"hint": _ENV_MAGICK})
        return "magick", exe, _magick_version(exe), None
    if pin == "pillow":
        v = pillow_ok()
        if v is None:
            raise SkillError(E_TOOL_MISSING, "后端被钉为 pillow 但 Pillow 不可用")
        return "pillow", None, v, None
    if pin != "auto":
        raise _bad(f"{_ENV_BACKEND} 取值非法（auto|magick|pillow）", {"got": pin})

    if exe is not None:
        return "magick", exe, _magick_version(exe), None
    v = pillow_ok()
    if v is None:
        raise SkillError(E_TOOL_MISSING,
                         "magick 与 Pillow 皆不可用（fail-closed）",
                         {"magick": None, "pillow": None})
    return "pillow", None, v, {"from": "magick", "to": "pillow",
                               "reason": E_TOOL_MISSING}


def _spawn(argv):
    """子进程统一走 argv 列表 + 显式 UTF-8（纪律 15；不拼 shell 串）。"""
    env = dict(os.environ)
    env["PYTHONUTF8"] = "1"
    try:
        cp = subprocess.run(argv, shell=False, capture_output=True,
                            encoding="utf-8", errors="replace",
                            timeout=_MAGICK_TIMEOUT, env=env)
    except FileNotFoundError as e:
        raise SkillError(E_TOOL_MISSING, "后端可执行体不在", {"argv0": argv[0], "err": str(e)})
    except PermissionError as e:
        raise SkillError(E_PERM, "后端可执行体无执行权限", {"argv0": argv[0], "err": str(e)})
    except subprocess.TimeoutExpired:
        raise SkillError(E_BACKEND_FAIL, "后端超时", {"argv": argv[:2]})
    return cp.returncode, cp.stdout, cp.stderr


def _classify_backend_err(err, default=E_BACKEND_FAIL):
    e = (err or "").lower()
    for key in ("no decode delegate", "improper image header",
                "unrecognized image format", "unable to read image",
                "not a valid", "crop/tile"):
        if key in e:
            return E_DECODE
    if "permission denied" in e:
        return E_PERM
    return default


# ---------------------------------------------------------------- magick 后端

_MAGICK_FMT = "%m|%w|%h|%z|%[channels]|%[bit-depth]"


def _magick_identify(exe, path):
    rc, out, err = _spawn([exe, "identify", "-format", _MAGICK_FMT, path])
    if rc != 0:
        raise SkillError(_classify_backend_err(err),
                         "magick identify 失败", {"rc": rc, "stderr": (err or "")[:400]})
    line = (out or "").strip().splitlines()
    if not line:
        raise SkillError(E_DECODE, "magick identify 无输出", {"path": path})
    parts = line[0].split("|")
    if len(parts) < 6:
        raise SkillError(E_DECODE, "magick identify 输出不可解析",
                         {"raw": line[0][:200]})
    fmt, w, h, depth, chans, _bd = parts[:6]
    try:
        width, height, bit_depth = int(w), int(h), int(depth)
    except ValueError:
        raise SkillError(E_DECODE, "magick identify 尺寸/位深不可解析",
                         {"raw": line[0][:200]})
    # `%[channels]` 实测形如 "srgb  4.0"（通道名 + 浮点），取首 token（本机实测）
    ch = chans.strip().split()[0].lower() if chans.strip() else ""
    return {
        "format": fmt.upper(),
        "width": width, "height": height,
        "mode": _CH2MODE.get(ch, ch or "unknown"),
        "bit_depth": bit_depth,
    }


def _magick_meta(exe, path):
    m = _magick_identify(exe, path)
    m["bytes"] = os.path.getsize(path)
    m["sha256"] = _sha256_file(path)
    return m


# ---------------------------------------------------------------- pillow 后端

def _open_pillow(path):
    _PIL, Image = _pillow()
    try:
        img = Image.open(path)
        img.load()
        return img
    except FileNotFoundError as e:
        raise SkillError(E_NOINPUT, "源文件不存在", {"err": str(e)})
    except PermissionError as e:
        raise SkillError(E_PERM, "读源文件无权限", {"err": str(e)})
    except Image.UnidentifiedImageError as e:
        raise SkillError(E_DECODE, "Pillow 解不出（损坏/非图像）", {"err": str(e)})
    except OSError as e:
        msg = str(e).lower()
        code = E_DECODE if ("truncated" in msg or "cannot identify" in msg
                            or "image file is truncated" in msg) else E_BACKEND_FAIL
        raise SkillError(code, "Pillow 打开失败", {"err": str(e)})


def _pillow_meta(path):
    img = _open_pillow(path)
    fmt = (img.format or "").upper()
    if not fmt:
        ext = os.path.splitext(path)[1].lstrip(".").lower()
        fmt = _EXT2FMT.get(ext, "UNKNOWN")
    return {
        "format": fmt, "width": img.size[0], "height": img.size[1],
        "mode": img.mode, "bit_depth": _pillow_bit_depth(img),
        "bytes": os.path.getsize(path), "sha256": _sha256_file(path),
    }


def _pillow_resize(src, dst, width, height, flt_name):
    _PIL, Image = _pillow()
    img = _open_pillow(src)
    if width is None and height is None:
        raise _bad("resize 需要 width 与/或 height")
    w0, h0 = img.size
    if width is not None and height is None:
        height = max(1, round(h0 * width / float(w0)))   # 保持纵横比
    if height is not None and width is None:
        width = max(1, round(w0 * height / float(h0)))
    resample = getattr(Image.Resampling, _FILTERS[flt_name][1])
    out = img.resize((int(width), int(height)), resample)
    _pillow_save(out, dst)


def _pillow_save(img, dst):
    ext = os.path.splitext(dst)[1].lstrip(".").lower()
    fmt = _EXT2FMT.get(ext)
    if fmt is None:
        raise SkillError(E_UNSUPPORTED_FORMAT, "目标扩展名不在写面", {"ext": ext})
    if fmt == "JPEG" and img.mode in ("RGBA", "LA", "P"):
        img = img.convert("RGB")
    try:
        img.save(dst, format=fmt)      # 不写 exif/时间戳（幂等口径：像素级门）
    except PermissionError as e:
        raise SkillError(E_PERM, "写目标无权限", {"err": str(e)})
    except OSError as e:
        raise SkillError(E_BACKEND_FAIL, "Pillow 保存失败", {"err": str(e)})


# ---------------------------------------------------------------- op 校验

def derive_level(op):
    return LEVEL_MAP.get(op)


def _norm_params(op, params):
    """按 op 规范化/校验参数；返回 (规范 params, 规范 dict 供 magick/写入面用)。"""
    if params is None:
        params = {}
    if not isinstance(params, dict):
        raise _bad("params 须为对象", {"got": type(params).__name__})
    if op == "inspect":
        extra = set(params) - {"note"}
        if extra:
            raise _bad("inspect 不接受参数", {"extra": sorted(extra)})
        return {}, {}
    if op == "resize":
        extra = set(params) - {"width", "height", "filter"}
        if extra:
            raise _bad("resize 参数仅 width/height/filter", {"extra": sorted(extra)})
        w, h = params.get("width"), params.get("height")
        for k, v in (("width", w), ("height", h)):
            if v is not None and (not isinstance(v, int) or isinstance(v, bool) or v <= 0):
                raise _bad(f"resize.{k} 须为正整数或 null", {"got": repr(v)})
        if w is None and h is None:
            raise _bad("resize 需要 width 与/或 height（不得皆缺）")
        flt = params.get("filter", DEFAULT_FILTER)
        if not isinstance(flt, str) or flt.lower() not in _FILTERS:
            raise _bad("resize.filter 不在支持面", {"supported": sorted(_FILTERS)})
        flt = flt.lower()
        return ({"width": w, "height": h, "filter": flt},
                {"width": w, "height": h, "filter": flt})
    # convert
    extra = set(params) - {"format"}
    if extra:
        raise _bad("convert 参数仅 format", {"extra": sorted(extra)})
    fmt = params.get("format")
    if fmt is not None:
        if not isinstance(fmt, str):
            raise _bad("convert.format 须为字符串", {"got": type(fmt).__name__})
        key = fmt.strip().lower()
        if key not in FMT_WRITE:
            raise SkillError(E_UNSUPPORTED_FORMAT, "目标格式不在后端写面",
                             {"format": fmt, "write_face": list(FMT_WRITE)})
        return {"format": _EXT2FMT[key]}, {"format": _EXT2FMT[key]}
    return {}, {}


def _derive_dst(src_rel, op, nparams, src_fmt_ext):
    """`dst` 缺省派生（定稿 §九-#7：显式优先；缺省 `src` 同目录 + `_out` + 后缀）。

    **本版解释**：定稿 §3.1/§3.6 均称「缺省由 `op`+`params` 派生」，而 §九-#7 的口诀
    写「原后缀」——对 `convert`（换容器）二者冲突：保留原后缀会得到
    「内容 webp / 名 .png」的自相矛盾产物。故：**换容器的 op（convert）派生时用目标
    格式后缀，其余保留原后缀**。此为 gap-fill，已列入交付「待核实」交编排侧裁定。
    """
    d = os.path.dirname(src_rel)
    stem = os.path.splitext(os.path.basename(src_rel))[0]
    ext = os.path.splitext(src_rel)[1] or src_fmt_ext or ".png"
    if op == "convert" and nparams.get("format"):
        ext = "." + _FMT2EXT.get(nparams["format"], ext.lstrip(".")).lower()
    rel = os.path.join(d, stem + "_out" + ext) if d else stem + "_out" + ext
    return rel


# ---------------------------------------------------------------- 审计

def _audit_write(root, rec):
    p = audit_path(root)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False, sort_keys=True) + "\n")


def _audit_seq(root):
    p = audit_path(root)
    if not os.path.exists(p):
        return 1
    n = 0
    with open(p, "r", encoding="utf-8", errors="replace") as f:
        for _ in f:
            n += 1
    return n + 1


def _make_audit(root, *, op, level, input_rel, input_sha, out_rel, out_sha,
                params, tool_version, caller, ok, error_code,
                backend, backend_note, sandbox_root, idempotency_key,
                extra=None, output_meta=None):
    seq = _audit_seq(root)
    rec = {
        "audit_id": f"audit_{int(time.time() * 1000)}_{seq}",
        "op": op,
        "level": level,
        "input_path": input_rel,
        "input_sha256": input_sha,
        "output_path": out_rel,
        "output_sha256": out_sha,
        "params": params,
        "tool_version": tool_version,
        "env": {"os": platform.platform(), "python": sys.version.split()[0],
                "pythonutf8": os.environ.get("PYTHONUTF8", "")},
        "ts": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime()),
        "caller": caller,
        "ok": bool(ok),
        "error_code": error_code,
        # —— 以下为定稿 §4.1 之外的本版增量（出参 `backend` + §九-#11 降级留痕）——
        "backend": backend,
        "backend_note": backend_note,
        "sandbox_root": sandbox_root,
        "idempotency_key": idempotency_key,
        "output_meta": output_meta,
    }
    if extra:
        rec.update(extra)
    return rec


# ---------------------------------------------------------------- 出参

def _result(ok, *, artifact_path=None, asset=None, meta=None, audit_id=None,
            backend=None, error=None):
    return {"ok": bool(ok), "artifact_path": artifact_path, "asset": asset,
            "meta": meta, "audit_id": audit_id, "backend": backend,
            "error": error}


def _err_result(code, message, detail=None, *, audit_id=None, backend=None):
    return _result(False, audit_id=audit_id, backend=backend,
                   error={"code": code, "message": message, "detail": detail})


# ---------------------------------------------------------------- op 实现

def _op_inspect(ctx):
    """读元数据（不改产物）。出参 artifact_path=None；meta=源元数据。"""
    b = ctx["backend"]
    if b["name"] == "magick":
        meta = _magick_meta(b["exe"], ctx["src_abs"])
    else:
        meta = _pillow_meta(ctx["src_abs"])
    ctx["out_rel"] = None
    ctx["out_sha"] = None
    ctx["output_meta"] = meta
    return _result(True, artifact_path=None, asset=meta["sha256"], meta=meta,
                   backend={"name": b["name"], "version": b["version"]})


def _op_resize(ctx):
    b, p = ctx["backend"], ctx["nparams"]
    if b["name"] == "magick":
        w, h = p["width"], p["height"]
        geom = f"{w}x{h}!" if (w and h) else (f"{w}x" if w else f"x{h}")
        rc, _out, err = _spawn([b["exe"], ctx["src_abs"], "-strip",
                                "-filter", _FILTERS[p["filter"]][0],
                                "-resize", geom, ctx["dst_abs"]])
        if rc != 0:
            raise SkillError(_classify_backend_err(err), "magick resize 失败",
                             {"rc": rc, "stderr": (err or "")[:400]})
        meta = _magick_meta(b["exe"], ctx["dst_abs"])
    else:
        _pillow_resize(ctx["src_abs"], ctx["dst_abs"],
                       p["width"], p["height"], p["filter"])
        meta = _pillow_meta(ctx["dst_abs"])
    _assert_target_size(meta, p["width"], p["height"])
    return _finish_artifact(ctx, meta)


def _op_convert(ctx):
    b, p = ctx["backend"], ctx["nparams"]
    want = p.get("format")
    if b["name"] == "magick":
        rc, _out, err = _spawn([b["exe"], ctx["src_abs"], "-strip", ctx["dst_abs"]])
        if rc != 0:
            raise SkillError(_classify_backend_err(err), "magick convert 失败",
                             {"rc": rc, "stderr": (err or "")[:400]})
        meta = _magick_meta(b["exe"], ctx["dst_abs"])
    else:
        img = _open_pillow(ctx["src_abs"])
        _pillow_save(img, ctx["dst_abs"])
        meta = _pillow_meta(ctx["dst_abs"])
    if want and meta["format"] != want:
        raise SkillError(E_BACKEND_FAIL,
                         "产物格式与目标不符（fail-closed）",
                         {"want": want, "got": meta["format"]})
    return _finish_artifact(ctx, meta)


def _assert_target_size(meta, w, h):
    if w is not None and meta["width"] != w:
        raise SkillError(E_BACKEND_FAIL, "resize 后宽度与目标不符",
                         {"want": w, "got": meta["width"]})
    if h is not None and meta["height"] != h:
        raise SkillError(E_BACKEND_FAIL, "resize 后高度与目标不符",
                         {"want": h, "got": meta["height"]})


def _finish_artifact(ctx, meta):
    ctx["out_rel"] = ctx["dst_rel"]
    ctx["out_sha"] = meta["sha256"]
    ctx["output_meta"] = meta
    return _result(True, artifact_path=ctx["dst_rel"], asset=meta["sha256"],
                   meta=meta,
                   backend={"name": ctx["backend"]["name"],
                            "version": ctx["backend"]["version"]})


_OPS = {"inspect": _op_inspect, "resize": _op_resize, "convert": _op_convert}


# ---------------------------------------------------------------- 入口

def run(req):
    """结构化入口（定稿 §3.1 入参 / §3.2 出参）。

    `req` = dict，键：`op`｜`src`｜`dst`｜`params`｜`declared_level`｜`caller`｜
    `idempotency_key` ＋ **`sandbox_root`**（**本版解释**：定稿 §3.1 入参清单未列
    该项，但 §九-#8 判「调用方必须显式给根」——故本版把它实现为入参 dict 的必需键，
    已列入交付「待核实」）。

    校验次序（**有意如此**，见其下注释）：
      根 → caller → op 已知 → declared_level 派生闸 → op 实现面 → params →
      src 解析/存在 → dst 派生/解析 → 后端探测 → 执行 → 回读元数据 → 落审计。
    """
    if not isinstance(req, dict):
        return _err_result(E_BAD_PARAM, "入参须为对象", {"got": type(req).__name__})

    op = req.get("op")
    root_in = req.get("sandbox_root")
    caller = req.get("caller")

    # ① 沙箱根：未给即拒（先于一切——否则连台账都无处落）
    try:
        root = _check_root(root_in)
    except SkillError as e:
        return _err_result(e.code, e.message, e.detail)

    level = derive_level(op)
    ctx = {
        "root": root, "op": op, "caller": caller, "backend": None,
        "dst_rel": None, "out_rel": None, "out_sha": None,
        "nparams": {}, "output_meta": None,
    }

    def _fail_and_audit(e, *, input_rel=None, input_sha=None, level_=level,
                        nparams=None, backend=None, backend_note=None):
        """失败也落审计（定稿 §四「每次操作」；ok=false + error_code）。"""
        ver = (backend or {}).get("version")
        rec = _make_audit(root, op=op if isinstance(op, str) else None,
                          level=level_, input_rel=input_rel,
                          input_sha=input_sha, out_rel=None, out_sha=None,
                          params=nparams or {}, tool_version=ver,
                          caller=caller if isinstance(caller, str) else None,
                          ok=False, error_code=e.code,
                          backend=backend, backend_note=backend_note,
                          sandbox_root=root,
                          idempotency_key=req.get("idempotency_key"))
        _audit_write(root, rec)
        return _err_result(e.code, e.message, e.detail, audit_id=rec["audit_id"],
                           backend=backend)

    try:
        # ② caller 必填（进审计，定稿 §3.1）
        if not isinstance(caller, str) or not caller.strip():
            raise _bad("caller 必填非空字符串（进审计）", {"got": repr(caller)})
        # ③ op 已知
        if not isinstance(op, str) or op not in LEVEL_MAP:
            raise SkillError(E_UNSUPPORTED_OP,
                             "op 未知（不在本版 op 表）",
                             {"op": op, "known": list(OPS_KNOWN)})
        # ④ declared_level 派生闸（定稿 §3.1「等级不可降级」）。**先于实现面判定**：
        #    「降级」是声明面的违规，与 op 是否已实现无关；先判才使该闸对本版
        #    留白的 L1/L2 op 同样可判（否则只能落到 E_UNSUPPORTED_OP，闸形同虚设）。
        dl = req.get("declared_level")
        if dl is not None:
            if dl not in _LEVEL_ORDER:
                raise _bad("declared_level 须为 L0/L1/L2", {"got": repr(dl)})
            if _LEVEL_ORDER[dl] < _LEVEL_ORDER[level]:
                raise SkillError(
                    E_LEVEL_DOWNGRADE,
                    "declared_level 低于 op 派生等级（等级不可降级）",
                    {"declared": dl, "derived": level, "op": op})
        # ⑤ op 实现面（本版范围外 → E_UNSUPPORTED_OP，非出错）
        if op not in OPS_IMPL:
            raise SkillError(E_UNSUPPORTED_OP,
                             "op 属本版范围外（本版仅 inspect/resize/convert）",
                             {"op": op, "derived_level": level,
                              "implemented": list(OPS_IMPL)})
        # ⑥ params
        nparams, mp = _norm_params(op, req.get("params"))
        ctx["nparams"] = mp
        # ⑦ src：解析（越界即拒）+ 存在性
        src_rel = req.get("src")
        src_abs = safe_join(root, src_rel, what="src")
        if not os.path.exists(src_abs):
            raise SkillError(E_NOINPUT, "src 不存在", {"src": src_rel})
        if not os.path.isfile(src_abs):
            raise SkillError(E_NOINPUT, "src 不是常规文件", {"src": src_rel})
        in_sha = _sha256_file(src_abs)
        src_rel = _rel(src_rel)
        ctx["src_abs"], ctx["src_rel"], ctx["input_sha"] = src_abs, src_rel, in_sha
        # ⑧ dst：显式优先；缺省派生；禁覆盖 src（fail-closed，§九-#7）
        dst_rel = req.get("dst")
        if dst_rel is None or (isinstance(dst_rel, str) and not dst_rel.strip()):
            dst_rel = _derive_dst(src_rel, op, nparams,
                                  os.path.splitext(src_abs)[1])
        dst_rel = _rel(dst_rel)
        dst_abs = safe_join(root, dst_rel, what="dst")
        if _norm(dst_abs) == _norm(src_abs):
            raise _bad("dst 不得覆盖 src（fail-closed，定稿 §九-#7）",
                       {"src": src_rel, "dst": dst_rel})
        # ⑨ 后端探测（两后端皆缺 → E_TOOL_MISSING，fail-closed）
        name, exe, ver, note = resolve_backend()
        backend = {"name": name, "version": ver}
        ctx["backend"] = {"name": name, "exe": exe, "version": ver}
        # ⑩ 幂等复用（同 key + 同参 + 同输入哈希 → 复用已存产物）
        if req.get("idempotency_key") is not None and op != "inspect":
            hit = _find_reuse(root, req.get("idempotency_key"), op, in_sha, nparams)
            if hit is not None:
                rec = _make_audit(
                    root, op=op, level=level, input_rel=src_rel, input_sha=in_sha,
                    out_rel=hit["output_path"], out_sha=hit["output_sha256"],
                    params=nparams, tool_version=ver, caller=caller, ok=True,
                    error_code=None, backend=backend, backend_note=note,
                    sandbox_root=root,
                    idempotency_key=req.get("idempotency_key"),
                    extra={"reused_from": hit["audit_id"]},
                    output_meta=hit.get("output_meta"))
                _audit_write(root, rec)
                return _result(True, artifact_path=hit["output_path"],
                               asset=hit["output_sha256"],
                               meta=hit.get("output_meta"), audit_id=rec["audit_id"],
                               backend=backend)
        # ⑪ dst 父目录（仅限根内，已在 safe_join 验过）按需创建
        par = os.path.dirname(dst_abs)
        if par and not os.path.isdir(par):
            os.makedirs(par, exist_ok=True)
        ctx["dst_rel"], ctx["dst_abs"] = dst_rel, dst_abs
        # ⑫ 执行
        res = _OPS[op](ctx)
        # ⑬ 审计
        rec = _make_audit(
            root, op=op, level=level, input_rel=src_rel, input_sha=in_sha,
            out_rel=ctx["out_rel"], out_sha=ctx["out_sha"], params=nparams,
            tool_version=ver, caller=caller, ok=True, error_code=None,
            backend=backend, backend_note=note, sandbox_root=root,
            idempotency_key=req.get("idempotency_key"),
            output_meta=ctx.get("output_meta"))
        _audit_write(root, rec)
        res["audit_id"] = rec["audit_id"]
        return res
    except SkillError as e:
        # 已探测到后端时把降级留痕带上
        bn = None
        try:
            if ctx["backend"] and ctx["backend"]["name"] == "pillow" \
                    and resolve_magick() is None:
                bn = {"from": "magick", "to": "pillow", "reason": E_TOOL_MISSING}
        except Exception:
            bn = None
        return _fail_and_audit(
            e, input_rel=ctx.get("src_rel"),
            input_sha=ctx.get("input_sha"),
            nparams=ctx.get("nparams"),
            backend=({"name": ctx["backend"]["name"],
                      "version": ctx["backend"]["version"]}
                     if ctx["backend"] else None),
            backend_note=bn)
    except PermissionError as e:
        return _fail_and_audit(SkillError(E_PERM, "OS 权限错误", {"err": str(e)}))
    except OSError as e:
        return _fail_and_audit(SkillError(E_BACKEND_FAIL, "OS 错误",
                                          {"err": str(e)}))
    except Exception as e:                                       # fail-closed 兜底
        return _fail_and_audit(SkillError(E_BACKEND_FAIL, "未预期错误",
                                          {"err": repr(e)}))


def _find_reuse(root, key, op, in_sha, nparams):
    """同 key + 同 op + 同输入哈希 + 同参 → 复用已成功产物（定稿 §3.1 幂等 key）。"""
    if key is None:
        return None
    for rec in reversed(read_audit(root)):
        if (rec.get("idempotency_key") == key and rec.get("ok") is True
                and rec.get("op") == op and rec.get("input_sha256") == in_sha
                and rec.get("params") == nparams and rec.get("output_path")):
            p = os.path.join(root, rec["output_path"])
            if os.path.isfile(p) and _sha256_file(p) == rec.get("output_sha256"):
                return rec
    return None
