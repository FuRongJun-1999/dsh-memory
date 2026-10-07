# -*- coding: utf-8 -*-
r"""图像 Skill（Image Skill）· L1 能力子系统 · **本版实现 13 op**。

契约真源：`docs/eval/图像Skill_接口契约_设计_v0.1.md` §九 定稿（2026-10-07，十项裁定）。
本模块按该定稿实现；凡定稿未逐字给出、需本实现自补之处，一律在 docstring 内标
「**本版解释**」，并列入交付说明的「待核实」清单——不自作主张改判契约。

本版范围（**13 个 op**，契约 §五 表内全部落成）：

  **已实现集**（`OPS_IMPL`，13 件）：
    * `inspect`   读元数据（format/width/height/bytes/mode/bit_depth/sha256）
    * `resize`    改尺寸（`width`/`height`/`filter`）
    * `convert`   转格式（`format`）
    * `thumbnail` 长边缩到 `max_edge`（保持纵横比；**可放大**，与 magick `-thumbnail` 同语义）
    * `crop`      裁窗（`x`/`y`/`width`/`height`；窗口须整幅落在源内）
    * `rotate`    旋转（`degrees`；**本版约定正角 = 顺时针**）
    * `flip`      上下镜像（`axis` 选填，须与 op 同轴）
    * `flop`      左右镜像（`axis` 选填，须与 op 同轴）
    * `adjust`    亮度/对比度/伽马（`brightness`/`contrast`/`gamma`）
    * `blur`      高斯模糊（`sigma`）
    * `sharpen`   反锐化（`sigma`）
    * `composite` 叠图（`over_path`/`gravity`/`opacity`）
    * `mask`      用 mask 设 alpha（`mask_path`/`mode`；本版只落 `mode="set"`）

  **仍范围外集**（命中即 `E_UNSUPPORTED_OP`——**「范围外」不是出错**）：
    * `export`（批量/多规格导出）与 `extract`（视频抽帧）：契约 §五「不做的操作」表
      （触发条件：出现「一源多规格」需求 / 本线涉视频且 `ffmpeg` 在场）；
    * L1 检测类 `detect`/`segment`/`ocr`/`bg_remove`：需模型 + `model_version`（本版无模型）；
    * L2 生成类 `generate`/`inpaint`/`outpaint`/`style_transfer`/`i2i`：走云（步 3）；
    * 任何不在 `LEVEL_MAP` 的 op 名（未知 op）。
    * 另：`mask.mode` 的非 `set` 取值（见 `MASK_MODE_UNIMPL`）也走此码——见下「本版解释」。

**本版解释（定稿未逐字给出的取值，一律在此显式声明，交编排侧裁定，不静默偏移）**：

  1. `thumbnail` 的放大语义：契约 §五 的判据是「最长边 == `max_edge`」，而其「Pillow
     兜底」栏写 `thumbnail()`——**实测 Pillow `thumbnail()` 只缩不放**（40×30 要 60 →
     仍是 40×30），与判据冲突；magick `-thumbnail 60x60` 则放大到 60×45。故 Pillow 侧
     本版**改用等比 `resize`**（缩放系数 `max_edge / 长边`），使两后端同语义、判据可判。
  2. `rotate` 的方向与背景：**实测 magick `-rotate` 正角 = 顺时针，Pillow `rotate()` 正角 =
     逆时针**（4×3 角标记像素落点：(0,0)→(2,0) vs (0,3)），契约 §五 两栏因而互斥。本版
     取 **正角 = 顺时针**（magick 原生方向，magick 为主后端；Pillow 侧传 `-degrees`）。
     背景：magick 默认背景为**不透明白**（实测 RGBA 源亦为 `(255,255,255,255)`），
     Pillow 默认不透明黑/透明 → 本版显式给白（`_ROT_BG`）对齐 magick。
  3. `crop` 越界：magick 对越窗**静默裁剪**（`100x100+30+20` on 40×30 → 10×10），Pillow 则
     补黑——两者不判齐。故本版**先验窗口整幅落在源内**，越窗即 `E_BAD_PARAM`。
  4. `composite`：契约 §五 的 `-geometry +X+Y` 与 `axis` 同类（表里留了但参数栏未列），
     故本版只取 `over_path`/`gravity`/`opacity` 三参；位置由 `gravity` 定，偏移恒 `+0+0`。
     `opacity` 取 **0..1 浮点**（magick 侧转 `-evaluate multiply` 的 alpha 缩放）；
     并**要求 over 不大于 base**（越界时两后端行为不一致，fail-closed 拒绝）。
     输出 mode 随 base（base 无 alpha → 输出涂成 RGB），与 magick 实测一致。
  5. `mask`：写面**收窄为 `png`/`tif`/`tiff`**（`_ALPHA_FMT`）——因为 `webp`/`bmp` 编码器在
     alpha 恒不透明时会**丢弃该通道**，那会直接违反判据「alpha 通道存在且可读回」。
     `mode` 本版只落 `"set"`（= `CopyOpacity` / `putalpha`，实测两后端**逐像素相等**）；
     `"mul"`（alpha := 原 alpha × mask）**未落**：magick 单命令无确定等价（实测
     `-compose Multiply -channel A` 乘的是**两图各自的 alpha**（mask 恒不透明 → 恒 255），
     `-fx "u.a*v.a"` 只取 `u.a`，`-alpha copy` 亦不改 alpha）——须多步中间件或 `-fx` 语义
     裁定，故列入 `MASK_MODE_UNIMPL` 走 `E_UNSUPPORTED_OP`。mask 尺寸须与源一致。
  6. `adjust`：Pillow 侧用**逐通道 8-bit LUT** 按「亮度（加性百分比）→ 对比度（绕 128 缩放）
     → 伽马（`v^(1/g)`）」实现（不经 `ImageEnhance`，避免其 alpha 语义不透明）；
     magick 侧用 `-brightness-contrast BxC -gamma G`。两后端数学不同源（magick 走 16-bit），
     判据仅取契约 §五 的「参数入台账 + 同参幂等」，**不设跨后端逐位相等**。
  7. `sharpen`：magick `-sharpen 0xσ` ↔ Pillow `UnsharpMask(radius=σ, percent=150,
     threshold=0)`（固定 percent/threshold，**近似等价**，非逐位相等）。
  8. 非直角 `rotate` 的尺寸：**两后端取值本就不同**（40×30 转 45°：magick 52×52、
     Pillow 50×50，解析外接矩形 49.50）——故本版只做**容差 3px 的内部门**，
     不设跨后端逐位门。

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
import math
import os
import platform
import shutil
import subprocess
import sys
import time

__all__ = [
    "run", "OPS_IMPL", "OPS_KNOWN", "OPS_OUT_OF_SCOPE", "MASK_MODE_UNIMPL",
    "LEVEL_MAP", "ERROR_CODES", "GRAVITIES",
    "derive_level", "resolve_magick", "resolve_backend", "read_audit",
    "AUDIT_REL", "audit_path",
]

# ---------------------------------------------------------------- 常量

L0, L1, L2 = "L0", "L1", "L2"
_LEVEL_ORDER = {L0: 0, L1: 1, L2: 2}

#: 本版**实际实现**的 op（契约 §五 表内的确定性、无模型子集，13 件全落）
OPS_IMPL = ("inspect", "resize", "convert", "thumbnail", "crop", "rotate",
            "flip", "flop", "adjust", "blur", "sharpen", "composite", "mask")

#: 本版**仍范围外**的 op 名（命中 → `E_UNSUPPORTED_OP`；「范围外」非出错）。
#: 与 `LEVEL_MAP` 的差集（除已实现者）等价；此处显式列出以便核对。
OPS_OUT_OF_SCOPE = ("extract", "export",
                    "detect", "segment", "ocr", "bg_remove",
                    "generate", "inpaint", "outpaint", "style_transfer", "i2i")

#: `mask.mode` 里**已知但未落**的取值 → `E_UNSUPPORTED_OP`（理由见模块 docstring 本版解释 5）
MASK_MODE_UNIMPL = ("mul", "multiply", "combine")

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

#: 镜像 op 的轴：`axis` 参数是同义确认项（**本版解释**：契约 §五 两件 op 合成一行、
#: 参数栏写 `axis`，但 op 名本身已编码了轴——故本版把 `axis` 设为选填且须与 op 同轴）
_AXIS = {
    "flip": ("vertical", "v", "updown", "ud", "上下"),
    "flop": ("horizontal", "h", "leftright", "lr", "左右"),
}
#: 镜像 op → (magick 旗标, Pillow Transpose 常量名, 中文标签)
_MIRROR = {
    "flip": ("-flip", "FLIP_TOP_BOTTOM", "上下"),
    "flop": ("-flop", "FLIP_LEFT_RIGHT", "左右"),
}

#: composite `gravity`：别名 → 规范名（IM `-gravity` 取值）
_GRAVITY_ALIAS = {
    "center": "center", "centre": "center", "c": "center",
    "north": "north", "n": "north",
    "south": "south", "s": "south",
    "east": "east", "e": "east",
    "west": "west", "w": "west",
    "northwest": "northwest", "nw": "northwest",
    "northeast": "northeast", "ne": "northeast",
    "southwest": "southwest", "sw": "southwest",
    "southeast": "southeast", "se": "southeast",
}
#: 规范 gravity → (横向系数, 纵向系数)：0=左/上，0.5=中，1=右/下
_GRAVITY_F = {
    "center": (0.5, 0.5), "north": (0.5, 0.0), "south": (0.5, 1.0),
    "east": (1.0, 0.5), "west": (0.0, 0.5),
    "northwest": (0.0, 0.0), "northeast": (1.0, 0.0),
    "southwest": (0.0, 1.0), "southeast": (1.0, 1.0),
}
GRAVITIES = tuple(sorted(_GRAVITY_F))

#: mask 的目标写面（**本版解释 5**：须支持 alpha 通道；webp/bmp 会在 alpha 恒不透明时丢通道）
_ALPHA_FMT = ("png", "tif", "tiff")

#: rotate 非直角时空白处填色（**本版解释 2**：对齐 magick 的不透明白默认背景）
_ROT_BG = {"1": 1, "L": 255, "LA": (255, 255), "P": 255, "I": 255, "F": 255.0,
           "RGB": (255, 255, 255), "RGBA": (255, 255, 255, 255)}

#: 参数域（越界即 `E_BAD_PARAM`）；`sigma` 上限对齐 Pillow `GaussianBlur`/`UnsharpMask` 可接受面
_ADJ_RANGE = 100.0          # brightness/contrast 百分比绝对值上限
_GAMMA_RANGE = (0.0, 10.0)  # gamma 开区间下界 / 闭区间上界
_SIGMA_MAX = 100.0          # blur/sharpen 的 sigma 上限

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


# ---------------------------------------------------------------- 参数/几何小工具

def _is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def _is_num(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool) \
        and math.isfinite(float(v))


def _fmt_num(x):
    """数值 → CLI 参数串（整值不带小数点；不依赖 locale）。"""
    f = float(x)
    return str(int(f)) if f == int(f) else repr(f)


def _resample(Image, flt_name):
    return getattr(Image.Resampling, _FILTERS[flt_name][1])


def _size_of(ctx, path):
    """取任意沙箱内文件的像素尺寸（crop/rotate/mirror/composite/mask 的验收判据要用）。"""
    b = ctx["backend"]
    if b["name"] == "magick":
        m = _magick_identify(b["exe"], path)
        return m["width"], m["height"]
    return _open_pillow(path).size


def _src_size(ctx):
    return _size_of(ctx, ctx["src_abs"])


def _rot_bg(mode):
    """rotate 空白填色（本版解释 2：对齐 magick 的不透明白默认背景）。"""
    return _ROT_BG.get(mode, (255, 255, 255))


def _adj_lut(brightness, contrast, gamma):
    """单通道 8-bit LUT：亮度（加性百分比）→ 对比度（绕 128 缩放）→ 伽马（v^(1/g)）。"""
    out = []
    for v in range(256):
        f = v + brightness * 255.0 / 100.0
        f = 128.0 + (f - 128.0) * (100.0 + contrast) / 100.0
        f = max(0.0, min(255.0, f))
        if gamma != 1.0:
            f = 255.0 * ((f / 255.0) ** (1.0 / gamma))
        out.append(max(0, min(255, int(round(f)))))
    return out


def _adj_lut_for(img, lut):
    """按 band 数铺开 LUT（带 alpha 的 mode：alpha band 用恒等 LUT，不动 alpha）。"""
    n = len(img.getbands())
    if img.mode in ("LA", "RGBA"):
        return list(lut) * (n - 1) + list(range(256))
    return list(lut) * n


def _pillow_filter_mod():
    """惰性取 `PIL.ImageFilter`（不进模块 import 面；缺失 → E_TOOL_MISSING）。"""
    _pillow()                                  # 先确认 Pillow 在场（含 IMGSKILL_PILLOW=0 否决）
    try:
        from PIL import ImageFilter
    except Exception as e:                                        # pragma: no cover
        raise SkillError(E_TOOL_MISSING, "Pillow ImageFilter 不可用", {"err": repr(e)})
    return ImageFilter


# ---------------------------------------------------------------- op 校验

def derive_level(op):
    return LEVEL_MAP.get(op)


def _norm_params(op, params):
    """按 op 规范化/校验参数；返回 (台账参数, 执行参数) 两字典。

    台账参数只放**已归一的值**（默认值补齐、别名解析、路径统一 `/`）——它同时是
    幂等复用的比对键（`_find_reuse` 拿它逐字比对），故取值必须稳定、可复跑。
    """
    if params is None:
        params = {}
    if not isinstance(params, dict):
        raise _bad("params 须为对象", {"got": type(params).__name__})

    def extra_keys(allowed, label):
        ex = set(params) - set(allowed)
        if ex:
            raise _bad(f"{label} 参数仅 {'/'.join(sorted(allowed))}", {"extra": sorted(ex)})

    if op == "inspect":
        extra_keys({"note"}, "inspect")
        return {}, {}
    if op == "resize":
        extra_keys({"width", "height", "filter"}, "resize")
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
    if op == "convert":
        extra_keys({"format"}, "convert")
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
    if op == "thumbnail":
        extra_keys({"max_edge"}, "thumbnail")
        m = params.get("max_edge")
        if not _is_int(m) or m <= 0:
            raise _bad("thumbnail.max_edge 须为正整数", {"got": repr(m)})
        n = {"max_edge": int(m)}
        return dict(n), dict(n)
    if op == "crop":
        extra_keys({"x", "y", "width", "height"}, "crop")
        x, y = params.get("x", 0), params.get("y", 0)
        w, h = params.get("width"), params.get("height")
        for k, v in (("x", x), ("y", y)):
            if not _is_int(v) or v < 0:
                raise _bad(f"crop.{k} 须为非负整数（负数在 magick 里是「从右/下起算」的另一语义）",
                           {"got": repr(v)})
        for k, v in (("width", w), ("height", h)):
            if not _is_int(v) or v <= 0:
                raise _bad(f"crop.{k} 必填且须为正整数", {"got": repr(v)})
        n = {"x": int(x), "y": int(y), "width": int(w), "height": int(h)}
        return dict(n), dict(n)
    if op == "rotate":
        extra_keys({"degrees"}, "rotate")
        deg = params.get("degrees")
        if not _is_num(deg):
            raise _bad("rotate.degrees 必填且须为有限数值", {"got": repr(deg)})
        if abs(float(deg)) > 3600.0:
            raise _bad("rotate.degrees 超出 ±3600（防误传弧度/毫弧度）", {"got": repr(deg)})
        n = {"degrees": float(deg)}
        return dict(n), dict(n)
    if op in ("flip", "flop"):
        extra_keys({"axis"}, op)
        ax = params.get("axis")
        if ax is None:
            return {}, {}
        if not isinstance(ax, str) or ax.strip().lower() not in _AXIS[op]:
            raise _bad(f"{op}.axis 须与 op 同轴（或整参省略）",
                       {"got": repr(ax), "op_axis": _AXIS[op][0],
                        "accepted": list(_AXIS[op])})
        n = {"axis": _AXIS[op][0]}
        return dict(n), dict(n)
    if op == "adjust":
        extra_keys({"brightness", "contrast", "gamma"}, "adjust")
        if not params:                                   # 全缺 → 无操作，拒
            raise _bad("adjust 需要 brightness/contrast/gamma 至少其一")
        br, ct = params.get("brightness", 0), params.get("contrast", 0)
        for k, v in (("brightness", br), ("contrast", ct)):
            if not _is_int(v) or abs(v) > _ADJ_RANGE:
                raise _bad(f"adjust.{k} 须为 ±{int(_ADJ_RANGE)} 内整数", {"got": repr(v)})
        gm = params.get("gamma", 1.0)
        if not _is_num(gm) or not (_GAMMA_RANGE[0] < float(gm) <= _GAMMA_RANGE[1]):
            raise _bad("adjust.gamma 须在 (0, 10] 内",
                       {"got": repr(gm), "range": list(_GAMMA_RANGE)})
        n = {"brightness": int(br), "contrast": int(ct), "gamma": float(gm)}
        return dict(n), dict(n)
    if op in ("blur", "sharpen"):
        extra_keys({"sigma"}, op)
        s = params.get("sigma")
        if not _is_num(s) or not (0.0 < float(s) <= _SIGMA_MAX):
            raise _bad(f"{op}.sigma 须在 (0, {int(_SIGMA_MAX)}] 内",
                       {"got": repr(s)})
        n = {"sigma": float(s)}
        return dict(n), dict(n)
    if op == "composite":
        extra_keys({"over_path", "gravity", "opacity"}, "composite")
        over = params.get("over_path")
        if not isinstance(over, str) or not over.strip():
            raise _bad("composite.over_path 必填且须为非空字符串（相对沙箱根）",
                       {"got": repr(over)})
        g = params.get("gravity", "center")
        if not isinstance(g, str) or g.strip().lower() not in _GRAVITY_ALIAS:
            raise _bad("composite.gravity 不在支持面",
                       {"got": repr(g), "supported": list(GRAVITIES)})
        op_v = params.get("opacity", 1.0)
        if not _is_num(op_v) or not (0.0 <= float(op_v) <= 1.0):
            raise _bad("composite.opacity 须在 [0, 1] 内", {"got": repr(op_v)})
        n = {"over_path": _rel(over), "gravity": _GRAVITY_ALIAS[g.strip().lower()],
             "opacity": float(op_v)}
        return dict(n), dict(n)
    if op == "mask":
        extra_keys({"mask_path", "mode"}, "mask")
        mp = params.get("mask_path")
        if not isinstance(mp, str) or not mp.strip():
            raise _bad("mask.mask_path 必填且须为非空字符串（相对沙箱根）",
                       {"got": repr(mp)})
        mode = params.get("mode", "set")
        if not isinstance(mode, str):
            raise _bad("mask.mode 须为字符串", {"got": type(mode).__name__})
        key = mode.strip().lower()
        if key in MASK_MODE_UNIMPL:
            # 「已知但未落」→ 范围外（非出错）：magick 无单命令确定等价，见模块 docstring
            raise SkillError(E_UNSUPPORTED_OP,
                             "mask.mode 该取值属本版范围外",
                             {"mode": mode, "implemented": ["set"],
                              "unimplemented_reason": "magick 单命令无确定等价（须多步中间件）"})
        if key != "set":
            raise _bad("mask.mode 不在支持面", {"got": repr(mode), "supported": ["set"]})
        n = {"mask_path": _rel(mp), "mode": "set"}
        return dict(n), dict(n)
    # 不可达（run() 已在实现面处挡下范围外 op）；防御性兜底：fail-closed
    raise SkillError(E_UNSUPPORTED_OP, "op 无参数校验分支（实现表与校验表不一致）",
                     {"op": op, "implemented": list(OPS_IMPL)})



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


def _assert_same_size(meta, want, label):
    if (meta["width"], meta["height"]) != tuple(want):
        raise SkillError(E_BACKEND_FAIL, f"{label} 后尺寸与目标不符（fail-closed）",
                         {"want": list(want), "got": [meta["width"], meta["height"]]})


def _op_thumbnail(ctx):
    """长边缩到 `max_edge`（保持纵横比，可放可缩；判据：最长边 == max_edge）。"""
    b, p = ctx["backend"], ctx["nparams"]
    m = p["max_edge"]
    if b["name"] == "magick":
        rc, _o, err = _spawn([b["exe"], ctx["src_abs"], "-strip",
                              "-thumbnail", f"{m}x{m}", ctx["dst_abs"]])
        if rc != 0:
            raise SkillError(_classify_backend_err(err), "magick thumbnail 失败",
                             {"rc": rc, "stderr": (err or "")[:400]})
        meta = _magick_meta(b["exe"], ctx["dst_abs"])
    else:
        _PIL, Image = _pillow()
        img = _open_pillow(ctx["src_abs"])
        w0, h0 = img.size
        if max(w0, h0) != m:
            # 本版解释 1：Pillow `thumbnail()` 只缩不放，与判据冲突 → 改用等比 resize
            s = float(m) / float(max(w0, h0))
            img = img.resize((max(1, int(round(w0 * s))), max(1, int(round(h0 * s)))),
                             _resample(Image, DEFAULT_FILTER))
        _pillow_save(img, ctx["dst_abs"])
        meta = _pillow_meta(ctx["dst_abs"])
    if max(meta["width"], meta["height"]) != m:
        raise SkillError(E_BACKEND_FAIL, "thumbnail 后最长边 != max_edge（fail-closed）",
                         {"max_edge": m, "got": [meta["width"], meta["height"]]})
    return _finish_artifact(ctx, meta)


def _op_crop(ctx):
    """裁窗 `x/y/width/height`（判据：产物尺寸 == 裁窗；窗口须整幅落在源内）。"""
    b, p = ctx["backend"], ctx["nparams"]
    x, y, w, h = p["x"], p["y"], p["width"], p["height"]
    sw, sh = _src_size(ctx)
    if x + w > sw or y + h > sh:
        # 本版解释 3：magick 越窗静默裁剪、Pillow 补黑 —— 不判齐 → 先验即拒
        raise _bad("crop 窗口越出源图（两后端越窗行为不判齐，fail-closed）",
                   {"window": [x, y, w, h], "src": [sw, sh]})
    if b["name"] == "magick":
        rc, _o, err = _spawn([b["exe"], ctx["src_abs"], "-strip",
                              "-crop", f"{w}x{h}+{x}+{y}", "+repage", ctx["dst_abs"]])
        if rc != 0:
            raise SkillError(_classify_backend_err(err), "magick crop 失败",
                             {"rc": rc, "stderr": (err or "")[:400]})
        meta = _magick_meta(b["exe"], ctx["dst_abs"])
    else:
        img = _open_pillow(ctx["src_abs"])
        _pillow_save(img.crop((x, y, x + w, y + h)), ctx["dst_abs"])
        meta = _pillow_meta(ctx["dst_abs"])
    _assert_same_size(meta, (w, h), "crop")
    return _finish_artifact(ctx, meta)


def _op_rotate(ctx):
    """旋转 `degrees`（**本版约定正角 = 顺时针**，见模块 docstring 本版解释 2）。

    判据（契约 §五）：90 倍数时尺寸对调；非直角按外接矩形（两后端取值本有差异，
    故为**容差 3px 的内部门**，非跨后端逐位门）。
    """
    b, p = ctx["backend"], ctx["nparams"]
    deg = p["degrees"]
    sw, sh = _src_size(ctx)
    if b["name"] == "magick":
        # 实测：magick `-rotate` 正角即顺时针（与 Pillow 相反），故原样传
        rc, _o, err = _spawn([b["exe"], ctx["src_abs"], "-strip",
                              "-rotate", _fmt_num(deg), ctx["dst_abs"]])
        if rc != 0:
            raise SkillError(_classify_backend_err(err), "magick rotate 失败",
                             {"rc": rc, "stderr": (err or "")[:400]})
        meta = _magick_meta(b["exe"], ctx["dst_abs"])
    else:
        img = _open_pillow(ctx["src_abs"])
        img = img.rotate(-float(deg), expand=True, fillcolor=_rot_bg(img.mode))
        _pillow_save(img, ctx["dst_abs"])
        meta = _pillow_meta(ctx["dst_abs"])
    _assert_rotate_size(meta, sw, sh, deg)
    return _finish_artifact(ctx, meta)


def _assert_rotate_size(meta, sw, sh, deg):
    k = int(round(float(deg) / 90.0))
    if abs(float(deg) - k * 90.0) < 1e-9:            # 直角：0/180 同尺寸，90/270 对调
        want = (sh, sw) if (k % 2) else (sw, sh)
        _assert_same_size(meta, want, f"rotate({deg:g})")
        return
    c = abs(math.cos(math.radians(float(deg))))
    s = abs(math.sin(math.radians(float(deg))))
    aw, ah = sw * c + sh * s, sw * s + sh * c
    if abs(meta["width"] - aw) > 3 or abs(meta["height"] - ah) > 3:
        raise SkillError(E_BACKEND_FAIL,
                         "rotate 非直角后尺寸偏离外接矩形（容差 3px，fail-closed）",
                         {"analytic": [round(aw, 2), round(ah, 2)],
                          "got": [meta["width"], meta["height"]], "degrees": deg})


def _op_mirror(ctx):
    """`flip`（上下）/`flop`（左右）镜像（判据：与源同尺寸 + 镜像像素可断言）。"""
    b = ctx["backend"]
    flag, pconst, zh = _MIRROR[ctx["op"]]
    sw, sh = _src_size(ctx)
    if b["name"] == "magick":
        rc, _o, err = _spawn([b["exe"], ctx["src_abs"], "-strip", flag, ctx["dst_abs"]])
        if rc != 0:
            raise SkillError(_classify_backend_err(err), f"magick {ctx['op']} 失败",
                             {"rc": rc, "stderr": (err or "")[:400]})
        meta = _magick_meta(b["exe"], ctx["dst_abs"])
    else:
        _PIL, Image = _pillow()
        img = _open_pillow(ctx["src_abs"])
        _pillow_save(img.transpose(getattr(Image.Transpose, pconst)), ctx["dst_abs"])
        meta = _pillow_meta(ctx["dst_abs"])
    _assert_same_size(meta, (sw, sh), f"{zh}镜像")
    return _finish_artifact(ctx, meta)


def _finish_artifact(ctx, meta):
    ctx["out_rel"] = ctx["dst_rel"]
    ctx["out_sha"] = meta["sha256"]
    ctx["output_meta"] = meta
    return _result(True, artifact_path=ctx["dst_rel"], asset=meta["sha256"],
                   meta=meta,
                   backend={"name": ctx["backend"]["name"],
                            "version": ctx["backend"]["version"]})


def _op_adjust(ctx):
    """亮度/对比度/伽马（判据：参数入台账 + 同参幂等；两后端数学不同源，见本版解释 6）。"""
    b, p = ctx["backend"], ctx["nparams"]
    br, ct, gm = p["brightness"], p["contrast"], p["gamma"]
    if b["name"] == "magick":
        args = []
        if br or ct:
            args += ["-brightness-contrast", f"{br}x{ct}"]
        if gm != 1.0:
            args += ["-gamma", _fmt_num(gm)]
        rc, _o, err = _spawn([b["exe"], ctx["src_abs"], "-strip"] + args + [ctx["dst_abs"]])
        if rc != 0:
            raise SkillError(_classify_backend_err(err), "magick adjust 失败",
                             {"rc": rc, "stderr": (err or "")[:400]})
        meta = _magick_meta(b["exe"], ctx["dst_abs"])
    else:
        _PIL, Image = _pillow()
        img = _open_pillow(ctx["src_abs"])
        if img.mode not in ("L", "LA", "RGB", "RGBA"):
            img = img.convert("RGB")          # 非常规 mode（P/1/CMYK/I/F）先归一
        img = img.point(_adj_lut_for(img, _adj_lut(br, ct, gm)))
        _pillow_save(img, ctx["dst_abs"])
        meta = _pillow_meta(ctx["dst_abs"])
    return _finish_artifact(ctx, meta)


def _op_blur(ctx):
    """高斯模糊（判据：参数入台账 + 同参幂等）。"""
    return _sigma_filter(ctx, "magick -blur", "GaussianBlur")


def _op_sharpen(ctx):
    """反锐化（判据：参数入台账 + 同参幂等；两后端非逐位等价，见本版解释 7）。"""
    return _sigma_filter(ctx, "magick -sharpen", "UnsharpMask")


def _sigma_filter(ctx, magick_label, pil_const):
    b, p = ctx["backend"], ctx["nparams"]
    s = p["sigma"]
    if b["name"] == "magick":
        flag = "-blur" if ctx["op"] == "blur" else "-sharpen"
        rc, _o, err = _spawn([b["exe"], ctx["src_abs"], "-strip",
                              flag, "0x" + _fmt_num(s), ctx["dst_abs"]])
        if rc != 0:
            raise SkillError(_classify_backend_err(err), f"{magick_label} 失败",
                             {"rc": rc, "stderr": (err or "")[:400]})
        meta = _magick_meta(b["exe"], ctx["dst_abs"])
    else:
        _PIL, Image = _pillow()
        ImageFilter = _pillow_filter_mod()
        img = _open_pillow(ctx["src_abs"])
        if img.mode not in ("L", "LA", "RGB", "RGBA"):
            img = img.convert("RGB")
        if pil_const == "UnsharpMask":
            flt = ImageFilter.UnsharpMask(radius=float(s), percent=150, threshold=0)
        else:
            flt = ImageFilter.GaussianBlur(float(s))
        img = img.filter(flt)
        _pillow_save(img, ctx["dst_abs"])
        meta = _pillow_meta(ctx["dst_abs"])
    return _finish_artifact(ctx, meta)


def _op_composite(ctx):
    """把 `over_path` 按 `gravity` 叠到 `src` 上（判据：尺寸同 base；合成位置入台账）。

    `opacity`（0..1）在 magick 侧实现为 over 的 alpha 缩放（`-evaluate multiply`），
    在 Pillow 侧实现为 `putalpha` 缩放 —— 实测 opacity=1 两后端**逐像素相等**，
    opacity<1 有 ±1 的量化差（不设逐位门）。
    """
    b, p = ctx["backend"], ctx["nparams"]
    root = ctx["root"]
    over_rel, g, op_v = p["over_path"], p["gravity"], p["opacity"]
    over_abs = safe_join(root, over_rel, what="params.over_path")
    if not os.path.isfile(over_abs):
        raise SkillError(E_NOINPUT, "composite.over_path 不存在", {"over_path": over_rel})
    bw, bh = _src_size(ctx)
    ow, oh = _size_of(ctx, over_abs)
    if ow > bw or oh > bh:
        # 本版解释 4：over 大于 base 时两后端行为不一致（magick 静默裁到 base、Pillow 会平移）
        raise _bad("composite 的 over 不得大于 base（fail-closed）",
                   {"over": [ow, oh], "base": [bw, bh]})
    fx, fy = _GRAVITY_F[g]
    gx, gy = int(round((bw - ow) * fx)), int(round((bh - oh) * fy))
    if b["name"] == "magick":
        rc, _o, err = _spawn([b["exe"], ctx["src_abs"],
                              "(", over_abs, "-alpha", "set", "-channel", "A",
                              "-evaluate", "multiply", _fmt_num(op_v), "+channel", ")",
                              "-gravity", g, "-geometry", "+0+0",
                              "-composite", "-strip", ctx["dst_abs"]])
        if rc != 0:
            raise SkillError(_classify_backend_err(err), "magick composite 失败",
                             {"rc": rc, "stderr": (err or "")[:400]})
        meta = _magick_meta(b["exe"], ctx["dst_abs"])
    else:
        _PIL, Image = _pillow()
        base = _open_pillow(ctx["src_abs"])
        over = _open_pillow(over_abs)
        had_a = "A" in base.getbands()          # 输出 mode 随 base（与 magick 实测一致）
        base = base.convert("RGBA")
        over = over.convert("RGBA")
        if op_v < 1.0:
            over.putalpha(over.getchannel("A").point(lambda v: int(round(v * op_v))))
        canvas = base.copy()
        canvas.alpha_composite(over, dest=(gx, gy))
        _pillow_save(canvas if had_a else canvas.convert("RGB"), ctx["dst_abs"])
        meta = _pillow_meta(ctx["dst_abs"])
    _assert_same_size(meta, (bw, bh), "composite")
    return _finish_artifact(ctx, meta)


def _op_mask(ctx):
    """用 `mask_path` 设 alpha（判据：alpha 通道存在且可读回）。

    本版只落 `mode="set"`（= alpha 取 mask 灰度）；写面收窄见模块 docstring 本版解释 5。
    """
    b, p = ctx["backend"], ctx["nparams"]
    root = ctx["root"]
    fmt_ext = os.path.splitext(ctx["dst_rel"])[1].lstrip(".").lower()
    if fmt_ext not in _ALPHA_FMT:
        raise SkillError(E_UNSUPPORTED_FORMAT,
                         "mask 目标格式须在支持 alpha 的写面内",
                         {"dst_ext": fmt_ext, "alpha_write_face": list(_ALPHA_FMT)})
    mask_rel = p["mask_path"]
    mask_abs = safe_join(root, mask_rel, what="params.mask_path")
    if not os.path.isfile(mask_abs):
        raise SkillError(E_NOINPUT, "mask.mask_path 不存在", {"mask_path": mask_rel})
    sw, sh = _src_size(ctx)
    mw, mh = _size_of(ctx, mask_abs)
    if (mw, mh) != (sw, sh):
        raise _bad("mask 与源尺寸不一致（fail-closed：magick 会缩放 mask，Pillow 直接报错）",
                   {"mask": [mw, mh], "src": [sw, sh]})
    if b["name"] == "magick":
        rc, _o, err = _spawn([b["exe"], ctx["src_abs"], mask_abs, "-alpha", "off",
                              "-compose", "CopyOpacity", "-composite", "-strip",
                              ctx["dst_abs"]])
        if rc != 0:
            raise SkillError(_classify_backend_err(err), "magick mask 失败",
                             {"rc": rc, "stderr": (err or "")[:400]})
        meta = _magick_meta(b["exe"], ctx["dst_abs"])
    else:
        _PIL, Image = _pillow()
        img = _open_pillow(ctx["src_abs"])
        if "A" not in img.getbands():
            img = img.convert("RGBA")
        img.putalpha(_open_pillow(mask_abs).convert("L"))
        _pillow_save(img, ctx["dst_abs"])
        meta = _pillow_meta(ctx["dst_abs"])
    if "A" not in str(meta.get("mode") or "").upper():
        # 判据本身（alpha 通道存在）fail-closed 化：产不出 alpha 即失败，不静默放行
        raise SkillError(E_BACKEND_FAIL, "mask 产物无 alpha 通道（fail-closed）",
                         {"mode": meta.get("mode")})
    return _finish_artifact(ctx, meta)


_OPS = {
    "inspect": _op_inspect, "resize": _op_resize, "convert": _op_convert,
    "thumbnail": _op_thumbnail, "crop": _op_crop, "rotate": _op_rotate,
    "flip": _op_mirror, "flop": _op_mirror,
    "adjust": _op_adjust, "blur": _op_blur, "sharpen": _op_sharpen,
    "composite": _op_composite, "mask": _op_mask,
}


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
                             "op 属本版范围外（范围外集见 OPS_OUT_OF_SCOPE）",
                             {"op": op, "derived_level": level,
                              "implemented": list(OPS_IMPL),
                              "out_of_scope": list(OPS_OUT_OF_SCOPE)})
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
