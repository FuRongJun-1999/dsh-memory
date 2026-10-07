# 图像 Skill 接口契约 · 设计 v0.1

> 时刻：2026-10-06 ｜ 性质：**设计稿（接口先行）**——本版只定接口，不落实现。
> 上游真源：`docs/eval/图像机制_设计与选型_v0.1.md`（八节方案，下称「方案稿」）｜
> `docs/eval/图像机制_步1前置摸底_v0.1.md`（步 1 结果与护栏，下称「摸底稿」）。
> 本文是**能力子系统**的接口层设计（属设计者自裁范围）；不触碰协议真源、不碰资格/信任/写入面。
> 口径原则：**与方案稿一致；凡不一致处显式标「承接口径/待裁」**，不静默偏移。

---

## 一、范围与定位

**一句话**：本 Skill 是本机图像能力的**能力子系统**（不是决策子系统）——把确定性图像变换收进一个**稳定接口**，后端（`magick`／Pillow／将来 libvips）可替换，Agent 只调 Skill、不直接操作任何具体软件。

**本版（v0.1）交付面**：

1. 定义 **Image Skill** 的接口契约（入参／出参／错误态／幂等／路径与编码约定）。
2. 定义 **inspect + edit 子集**（本机 CPU 可承载的确定性操作）。
3. 定义三可信等级的**审计字段**与**守卫草案**。

**本版不做**（沿方案稿 §六「边界」）：

| 不做 | 出处 | 原因 |
|---|---|---|
| 生成式重活（generate／inpaint／outpaint／style transfer／i2i） | 方案稿 §六、§三 generate 面 | 本机 4090 硬件层高负载不稳定；**生成一律走云（步 3）** |
| 操作 GUI 图像软件（不模拟人点 GUI） | 方案稿 §一、§六 | Agent 只调接口，不碰软件界面 |
| 碰资格/信任/写入面 | 方案稿 §六 | 它是能力子系统，不是决策子系统 |
| GIMP／Krita 作为程序化后端 | 方案稿 §六 | 人类编辑器，脚本面弱 |
| libvips 依赖 | 摸底稿 §三判定 | **先证瓶颈再引依赖**——本线当前体量未证收益，libvips 后置 |

**承接口径（与方案稿的显式对齐）**：方案稿 §三 的 `edit` 约定列了 14 个操作（inspect/resize/crop/rotate/flip/convert/composite/mask/adjust/blur/sharpen/thumbnail/extract/export）。本版**只取其中确定性、无模型、CPU 可承载的子集**（见 §五），其余列入「不做的操作」并给触发条件。

---

## 二、分层（每层职责与可/不可调用面）

沿方案稿 §三 的 Skill 分层展开为四层；**本文只设计 L1，L0/L2/L3 只定边界**。

```
L0 Agent（意图层）    把…缩小 / 转成 webp / 生成海边场景
      │  只调 L1 的 op；不接触任何后端参数
      ▼
L1 Image Skill API（★本设计对象）
      ├── inspect  元数据/尺寸/格式/哈希
      ├── edit     确定性变换（★本机 CPU 承载；本版实现子集）
      └── generate 生成式（★Job 化；本版只留接口占位，不实现）
      │  只调 L2 的「后端路由器」；不直接拼后端命令行
      ▼
L2 执行后端（可替换）  magick CLI ／ Pillow（本版）；libvips（后置）
      │  产物落 L3；写审计
      ▼
L3 Asset Store + 审计台账   可寻址 asset:// ／ 每次操作一条审计
```

| 层 | 职责 | 可调用面（允许） | 不可调用面（禁止） |
|---|---|---|---|
| **L0 Agent** | 表达意图、选 op、读产物元数据 | 调 `skill.inspect` / `skill.edit` /（将来 `skill.generate`） | 不接触 libvips API、IM 参数、CUDA、ComfyUI node id、模型路径（方案稿 §三原话：**全部藏在 Skill 后面**） |
| **L1 Skill API** | 校验入参 → 路由后端 → 收产物元数据 → 写审计 → 回结构化结果 | 调 L2 后端路由；读写沙箱内路径 | 不自行决策「该不该做」（决策属 L0/编排侧）；不写资格/信任面 |
| **L2 后端** | 执行单条确定性变换 | 被 L1 调用 | 不选路径（路径由 L1 定）；不碰审计台账以外状态 |
| **L3 Asset/审计** | 存产物、记账 | 被 L1 写 | 不反向修改 L0/L1 逻辑 |

**关键隔离**（可机械断言，见 §六-G5）：L1 模块的 import 面**不得**含 `md_cg` 的资格/信任/写入相关模块；L1 也不得将「是否放行」交给自身——**Skill 只报告结果，不裁决**。

---

## 三、接口契约（核心）

### 3.1 入参（结构化）

```jsonc
{
  "op":    "resize",                 // 必填；操作名（枚举，见 §五）
  "src":   "inbox/看板.png",          // 必填；源路径（相对沙箱根，UTF-8）
  "dst":   "out/看板_256.webp",       // 选填；缺省由 op+params 派生（见 3.6）
  "params": { "width": 256, "height": null, "filter": "lanczos" }, // 按 op 取用
  "declared_level": "L0",            // 选填；调用方声明可信等级（见下「等级不可降级」）
  "caller": "orchestrator:step2",    // 必填；调用者标识（进审计）
  "idempotency_key": null            // 选填；同 key 同参数可复用已存产物
}
```

**等级不可降级（设计判断点）**：`declared_level` 只是**声明**；Skill 以 `op → level` 的**派生映射**为准（§五表）。若 `declared_level` 低于派生等级 → 拒绝 `E_LEVEL_DOWNGRADE`，防止调用方把「确定+内容分析」当「纯确定」全自动跑（对齐方案稿 §四「不要让『看起来一样』成为成功标准」）。

### 3.2 出参（结构化）

```jsonc
{
  "ok": true,
  "artifact_path": "out/看板_256.webp",      // 产物路径（沙箱内相对路径）
  "asset": "asset://sha256:<hex>/看板_256.webp", // 可寻址 id（本版是否真落地=待裁）
  "meta": {
    "format": "WEBP", "width": 256, "height": 192,
    "bytes": 8123, "mode": "RGB", "bit_depth": 8,
    "sha256": "<hex64>"                          // 产物内容哈希（清洗元数据后，见 3.5）
  },
  "audit_id": "audit_<ts>_<seq>",               // 审计记录 id（见 §四）
  "backend": { "name": "magick", "version": "7.1.2-31" },
  "error": null
}
```

失败时：`ok=false`、`artifact_path=null`、`meta=null`、`error={code,message,detail}`。

### 3.3 错误态（可判别错误码 + 处置）

判据：**错误码必须能由调用方机械分支**，不靠错误消息文本。

| 错误码 | 触发条件 | 可判别依据 | 处置（调用方） |
|---|---|---|---|
| `E_NOINPUT` | `src` 不存在 | 路径 stat 失败 | 不重试；报上游补源 |
| `E_UNSUPPORTED_FORMAT` | 格式不在后端可读写面 | 后端 `identify -list format` 不含 | 换格式或换后端；记录缺口 |
| `E_TOOL_MISSING` | 后端可执行体不在（如 PATH 无 `magick`） | `shutil.which`／完整路径 stat 失败 | 走另一后端（Pillow）；两后端皆缺→fail-closed |
| `E_PERM` | 读写目标无权限 | OS 权限错误（errno EACCES） | 不重试；报权限问题 |
| `E_PATH_OUT_OF_SCOPE` | `src`/`dst` 越出沙箱根 | 规范化后前缀不在白名单内 | **拒绝**；防路径穿越（`..`、绝对路径、符号链接逃逸） |
| `E_BAD_PARAM` | 参数缺失/越界/类型错 | 参数校验 | 不重试；报参数错 |
| `E_BACKEND_FAIL` | 后端返回非 0 | 子进程 rc≠0 | 记 stderr（截断）；可换后端重试一次 |
| `E_DECODE` | 输入解不出（损坏/非图像） | 后端报解码失败 | 不重试；标记源损坏 |

**fail-closed 约定**（沿本仓 check_local_paths.py 做法）：环境错误（如无法执行工具探测）**不得静默放行**，一律落到明确错误码。

### 3.4 幂等性

| 等级 | 同输入同参数是否恒得同产物 | 说明 |
|---|---|---|
| **L0 纯确定性** | **是**（在清洗元数据前提下） | 位图变换本身确定；**但编码器可能写入时间戳**（PNG `tIME`、JPEG EXIF `DateTime`、WebP `VP8X` 时间字段）→ 字节级哈希可能抖动 |
| L1/L2 | 见 §四 | L1 依赖模型 → 须记 model_version；L2 须记 seed（不保证跨环境同） |

**幂等保证口径（设计判断点，待裁）**：L0 产物的 `sha256` 只对**剥离元数据后**的像素流计算（后端加 `-strip`／Pillow 不写 exif）——否则「同输入同产物」在字节级**不成立**。是否要求**位级**恒等（strict）还是**像素级**恒等（pixel-strict，允许容器元数据差异）= **待裁**（见 §七）。

### 3.5 路径与编码约定

- **全部路径与文本 UTF-8**（纪律 15）；中文路径**必须可用**（摸底稿 §六 A3 已实测通过：中文文件名 64×48 渐变图 → `magick` resize → WebP 全链 rc=0）。
- **沙箱根**：所有 `src`/`dst` 必须在配置的沙箱根之下（本版建议 `%TEMP%` 下的独立子目录；**在役库不得写入**）。越界 → `E_PATH_OUT_OF_SCOPE`。
- **禁止裸 `convert`**（摸底稿 §二 + §五护栏 1）：本机 PATH 上 `convert` 恒解析到系统盘 `%SystemRoot%\system32\convert.exe`（Windows 卷转换工具），**不是** ImageMagick。ImageMagick 侧一律走 `magick`；Python 侧优先 Pillow。此条进守卫（§六-G5）。
- **调用走 argv 列表 + 显式 UTF-8**（纪律 15）：`subprocess.run([...], shell=False, encoding='utf-8', errors='replace')`，环境带 `PYTHONUTF8=1`；**不拼 shell 串**。
- **刷新 PATH 前用完整路径**（摸底稿 §五护栏 3）：新 session 可能看不到 `magick`——Skill 解析后端时**不得假定** `magick` 在 PATH，需支持按「ImageMagick 安装目录」显式构造。

### 3.6 目标路径派生（`dst` 缺省规则，待裁）

当 `dst` 省略时的候选规则（**给选项，不拍板**）：

- **选项 A（推荐）**：`<out_dir>/<src_stem>__<op>_<param_slug>.<target_ext>`——可读、可追溯、天然防覆盖。
- **选项 B**：`<out_dir>/<src_stem>.<target_ext>`——简洁，但并发/重复会互相覆盖。
- **选项 C**：由调用方必须显式给 `dst`——最安全，但失便利。

---

## 四、审计字段（三可信等级）

沿方案稿 §四的三等级与「审计原则」逐条落成**字段清单**。等级以 `op` 派生（§五表），不由调用方降级。

### 4.1 公共字段（每次操作必落）

| 字段 | 类型 | 落点 | 复跑校验方式 |
|---|---|---|---|
| `audit_id` | str | 审计台账 | 唯一性断言 |
| `op` | str | 台账 | 枚举校验 |
| `level` | enum L0/L1/L2 | 台账 | == 派生映射（§五） |
| `input_path` | str（相对沙箱根） | 台账 | 存在性 |
| `input_sha256` | hex64 | 台账 | 重算比对 |
| `output_path` | str | 台账 | 存在性 |
| `output_sha256` | hex64 | 台账 | 重算比对 |
| `params` | json | 台账 | 规范化后哈希 |
| `tool_version` | str（如 magick 7.1.2-31／Pillow 12.3.0） | 台账 | 与后端探测一致 |
| `env` | json（OS/Python/关键 env） | 台账 | 只记录，不校验 |
| `ts` | ISO8601 | 台账 | — |
| `caller` | str | 台账 | — |
| `ok` / `error_code` | bool/str | 台账 | — |

### 4.2 分级增量字段

| 等级 | 增量字段 | 复跑校验 |
|---|---|---|
| **L0 纯确定性** | 无（公共字段即足） | 同输入同参两次 → `output_sha256` 相等（幂等断言） |
| **L1 确定性算法＋内容分析** | `model_version`、`confidence` | 记模型版本；置信度入台账（对齐方案稿 §四） |
| **L2 生成式** | `deterministic:false`、`model`、`seed`、`workflow_hash`、`provider`、`parameters` | 标 `deterministic:false`；seed/workflow 入台账 |

**本版 v0.1 只实际产生 L0 审计**（edit 子集全为纯确定性）；L1/L2 字段清单先定、待步 3 落地填值。

**审计原则落句**（方案稿 §四原话采纳）：每次操作记「输入 asset hash、输出 asset hash、操作、参数、工具版本、模型版本、workflow hash、seed、执行环境、时间」——**目的是「图像本身成为可寻址 Asset，编辑操作成为可追踪事件」**。

---

## 五、edit 子集清单（本版做哪些）

**一行一件**：操作 → 底层调用 → 参数 → 验收判据。等级均为 **L0**（纯确定性）。

| op | 底层调用（`magick` 优先，Pillow 兜底） | 参数 | 验收判据 | 派生的 level |
|---|---|---|---|---|
| `inspect` | `magick identify -format`／Pillow `Image.open` | 无 | 元数据（format/width/height/mode/hash）与源一致且可重算 | L0 |
| `resize` | `magick <src> -resize WxH! <dst>`／Pillow `resize(...,LANCZOS)` | `width`/`height`/`filter` | `meta.width/height == 目标`；纵横比按 `!` 语义 | L0 |
| `thumbnail` | `magick <src> -thumbnail <max> <dst>`／Pillow `thumbnail()` | `max_edge` | 最长边 == `max_edge`（保持纵横比） | L0 |
| `crop` | `magick <src> -crop WxH+X+Y <dst>`／Pillow `crop((x,y,x+w,y+h))` | `x`/`y`/`width`/`height` | `meta.width/height == 裁窗` | L0 |
| `rotate` | `magick <src> -rotate <deg> <dst>`／Pillow `rotate(deg,expand=True)` | `degrees` | 90 倍数时尺寸对调；非直角按外接矩形 | L0 |
| `flip` / `flop` | `magick <src> -flip`（上下）／`-flop`（左右） | `axis` | 与源同尺寸；镜像像素可断言 | L0 |
| `convert` | `magick <src> <dst>`（格式随扩展名）／Pillow `save(fmt=...)` | `format` | `meta.format == 目标`（摸底稿已实测 png→jpg/webp） | L0 |
| `adjust` | `magick <src> -brightness-contrast BxC -gamma G <dst>` | `brightness`/`contrast`/`gamma` | 参数入台账；同参幂等 | L0 |
| `blur` | `magick <src> -blur 0x<σ> <dst>` | `sigma` | 参数入台账；同参幂等 | L0 |
| `sharpen` | `magick <src> -sharpen 0x<σ> <dst>` | `sigma` | 参数入台账；同参幂等 | L0 |
| `composite` | `magick composite -gravity <g> -geometry +X+Y <over> <base> <dst>` | `over_path`/`gravity`/`opacity` | 尺寸同 base；合成位置入台账 | L0 |
| `mask` | `magick <src> -alpha set -write-mask <mask>`／Pillow `putalpha` | `mask_path`/`mode` | alpha 通道存在且可读回 | L0 |

**不做的操作（本版单列，含触发条件）**：

| 不做 | 等级 | 触发条件（何时进下一版） |
|---|---|---|
| `extract`（视频抽帧） | — | 本线涉视频 + `ffmpeg` 在场（摸底稿 §三-3，未装） |
| `export`（批量导出/多规格） | L0 | 出现「一源多规格」需求后，作为 `edit` 的组合器 |
| face/object detection、segmentation、OCR、background removal | **L1** | 引入模型 + 需 `model_version`（本版无模型） |
| generate/inpaint/outpaint/style transfer/i2i | **L2** | 云 GPU 就绪（方案稿步 3） |
| libvips 加速路径 | — | **先证性能/内存瓶颈**再引依赖（摸底稿 §三） |
| 任何 GUI 操作 | — | 永不做（方案稿 §六） |

---

## 六、守卫/验收草案

仿本仓守卫风格（如 `scripts/check_local_paths.py`：**规则 + 正/负样例 + `--selftest` + 退出码 0/1/2 + fail-closed**）。本版只出**判据草案**（尚未落码）。

| # | 守卫项 | 判据（能红） | 退出码/处置 |
|---|---|---|---|
| **G1** | **同输入幂等** | 同一 `src`+`params` 跑两次（清洗元数据口径），`output_sha256` 必须相等；不等 → 红 | 1；并指出两次差异字节区间 |
| **G2** | **中文路径可用** | 用中文文件名/中文目录跑 `resize`+`convert` 全链；任一步 rc≠0 或产物不可回读 → 红 | 1 |
| **G3** | **错误态可判别** | 构造 5 类错误（缺源/坏格式/缺工具/越界/坏参数），断言返回**指定错误码**；返回 `ok=false` 但码不对或无码 → 红 | 1 |
| **G4** | **审计字段齐** | 每次成功操作，台账记录必含 §4.1 全字段；缺任一 → 红（并点名缺失清单） | 1 |
| **G5** | **结构断言（不碰资格/信任/写入面）** | ① L1 模块 import 面**不含** `md_cg` 资格/信任/写入相关模块；② 源码/argv 中**不出现裸 `convert`**（须走 `magick`）；③ 所有产物路径落在沙箱根之内 | 1；越界即红 |
| **G6** | **禁裸 convert（硬门）** | 扫描 Skill 源码与 argv 构造点，出现 `"convert"` 作为可执行名 → 红（同摸底稿 §五护栏 1 升级为机械门） | 1 |
| **G7** | **fail-closed** | 后端探测/环境错误时**不得**返回 `ok=true`；应落明确错误码 | 1；静默放行即红 |

**自检要求**：守卫须带 `--selftest`，断言「正样例全命中 / 负样例零命中 / 守卫源码自身不被误判」（沿 check_local_paths.py 做法，规则字面量拼接构造防自命中）。

**G1 的可红前提**：必须先定「位级 / 像素级」幂等口径（§3.4 待裁）——口径不定，G1 无法机械判定。**这条是 G1 的前置依赖**。

---

## 七、待核实 / 待裁清单

### 7.1 自方案稿 §七 承接（未决）

| # | 项 | 归属 |
|---|---|---|
| 1 | `kuretoshi/photocraft` 与 ArtCraft 套件（storytold）PhotoCraft 的关系（同名两项目 or 同项目两口径） | **设计者裁定**（非本线阻塞） |
| 2 | libvips 本机安装可行性（归档＋PATH＋`pyvips`） | 待核实；**本版不引** |
| 3 | ImageMagick 版本与 policy（`magick` 命令名） | **已核实**：7.1.2-31 Q16-HDRI x64，入口 `magick`（摸底稿 §五 V1） |
| 4 | ComfyUI 云侧部署细节 | 步 3 时再核 |

### 7.2 本节新增（本设计暴露）

| # | 项 | 性质 | 归属 |
|---|---|---|---|
| 5 | Skill 模块落点与命名（`md_cg/image_skill.py`？`scripts/image_skill/`？） | 命名/分层 | **编排侧裁定** |
| 6 | 幂等口径：**位级** vs **像素级**（是否 `-strip`） | 取值 | **编排侧裁定**（G1 前置） |
| 7 | `dst` 缺省派生规则（A/B/C，见 §3.6） | 取值 | **编排侧裁定** |
| 8 | 沙箱根取值与生命周期（建议 `%TEMP%` 子目录；是否定期清理） | 取值 | **编排侧裁定** |
| 9 | 错误码编码风格（本文 `E_*` 前缀 vs 数字码 vs 复用本仓既有码表） | 命名 | **编排侧裁定** |
| 10 | `asset://` 可寻址 id **本版是否真落地**（方案稿 §四「可寻址 Asset」） | 范围 | **编排侧裁定** |
| 11 | 后端优先级（`magick` 优先还是 Pillow 优先；冲突时谁为准） | 取值 | **编排侧裁定** |
| 12 | 文档归域：本文按任务落在 `docs/eval/`，但方案稿 §五步 2 属「接口设计」——`eval/` 归域规则为「评测/第三方报告」，**是否应改归 `plans/`（设计/规格）** | 归域 | **编排侧裁定** |

---

## 八、下一步（接口已定，待实现）

1. **裁定 §七-6/7/8**（幂等口径/G1 前置、`dst` 派生、沙箱根）——这 3 项定了才能落码。
2. 落 `inspect + edit 子集`（§五）最小实现，跑通 §六 G1–G7。
3. 落**审计台账**（§4.1 公共字段 + L0 增量）。
4. L1/L2 字段与 `generate` Job 接口**留待步 3**（云侧）。

---

*本件为设计稿（接口先行）；实现与裁定后应升版并回写方案稿 §八 的队列状态。*

---

## 九、定稿（设计者位置 · 2026-10-07）

**定稿前独立复核（编排侧亲验，不采信出稿人转述）**：本文 272 行、**零本机绝对路径字面量**；`scripts/check_local_paths.py` **PASS**；**Pillow 12.3.0 在场且 `webp` 特性为真**；`magick` 7.1.2-31 Q16-HDRI 在场（当前 session PATH 未刷新）；`convert` 仍解析到系统盘卷转换工具（陷阱未消）。**「全绿地」这条复核结果为「实质成立、措辞略宽」**——全仓搜 `asset://`／`Image Skill`／`image_skill` 的命中**全部落在本线的两份设计文档与一份文档索引节点内，无任何实现代码**；但并非字面的「0 命中」，此处据实订正。

以下十项为裁定，逐条对应 §七 待裁表与本文三处「设计判断点」。

| # | 待裁项 | **裁定** | 理由 |
|---|---|---|---|
| 5 | Skill 模块落点与命名 | **`md_cg/imgskill.py`**（单模块，与 `goal_gen.py`／`autonomy.py` 同族）。**本版不新增 MCP op** | 能力子系统先落在库内；**协议面冻结在即，不因新能力扩大 op 面**——暴露面留到实现步单独评估 |
| 6 | 幂等口径（G1 前置） | **取「像素级必达、位级可选」**：剥离元数据后同输入同参 → **像素相等**即判幂等；位级恒等**不设为门** | 位级受第三方编码器时间戳（PNG `tIME`／JPEG EXIF／WebP 时间字段）牵制，把它设成门等于让别人的实现对我们的门负责；像素级可判别、可复跑、可归因 |
| 7 | `dst` 缺省派生规则 | **显式 `dst` 优先**；未给则由 `src` 派生（同名 + `_out` + 原后缀）；**禁止覆盖 `src`（fail-closed）** | 防误覆盖是硬要求；派生规则取最不易撞名的一种 |
| 8 | 沙箱根与生命周期 | **不设隐式默认根**——调用方必须显式给根，未给则**拒绝（fail-closed）**；生命周期＝调用方所有（本版**不自动清理**） | 「隐式根」等于把越界写藏进实现里；不自动清理 ＝ 不替调用方做删除决策 |
| 9 | 错误码风格 | **采纳本文 `E_*` 八码**（`E_NOINPUT`／`E_UNSUPPORTED_FORMAT`／`E_TOOL_MISSING`／`E_PERM`／`E_PATH_OUT_OF_SCOPE`／`E_BAD_PARAM`／`E_BACKEND_FAIL`／`E_DECODE`），全程 fail-closed | 自描述、可判别；不必强行套本仓既有码表（那是记忆面语义，不是图像面语义） |
| 10 | `asset://` 本版是否落地 | **不落地——本版只返回 `artifact_path` ＋ 纯 `sha256` 十六进制作占位**；不实现 `asset://` 解析器 | **不引入新协议面**（同 #5）；真落地待有第二个消费方时再议 |
| 11 | 后端优先级 | **`magick` 优先、Pillow 兜底**（`magick` 不可用时降级，且**降级必须落审计字段**） | 与步 1 实测一致（magick 覆盖面广、delegate 已验；Pillow 是最小通路）；降级要留痕，不许静默换后端 |
| 12 | 文档归域 `eval/` vs `plans/` | **不改，留在 `docs/eval/`** | `docs/eval/` 是本仓**探针／设计／读数**的既有归域（`W2_*`／`W5_*`／`W6_*` 等设计稿都在此），`plans/` 专给纲领与答卷；改归域会牵动链接与索引，收益为零 |

**对三处「设计判断点」的处置**：①**等级不可降级**（`declared_level` 低于 op 派生 → 拒绝）——**采纳**；②**幂等需 `-strip`**——**部分采纳**（`-strip` 作为实现手段可用，但**门设在像素级**，见 #6）；③**生成面只留接口占位**——**采纳**（同 #10）。

**§七-1 至 4 的处置**：①photocraft 同名关系＝**仍归设计者裁定**（本端不代裁）；②libvips **本版不引**（沿摸底判定「先证瓶颈再引依赖」）；③IM 版本已核实；④ComfyUI 属步 3。

**实现边界（本稿确立，实施步须遵守）**：不碰资格／信任／写入面（G5 结构断言）；产物**一律落调用方显式给的沙箱根**；**禁用裸 `convert`**（G6 硬门）；错误一律 fail-closed。**未定的只有 §七-1（归设计者）**——其余裁定齐备，**实现步可直接开工**。

---

## 十、实施裁定（设计者位置 · 2026-10-07 晚，随首版实现）

**范围**：本版只落 **3 个 op**（`inspect`／`resize`／`convert`），其余 9 op 与 L1/L2 类返回 `E_UNSUPPORTED_OP`（**「本版范围外」非出错**）。**已落盘两件**：`md_cg/imgskill.py`（877 行，库模块、零 CLI）与 `md_cg/test_imgskill.py`（557 行守卫）。

**编排侧亲跑复核（不采信转述）**：守卫在**两条后端路径**上各 **18 passed / 0 failed**——默认（PATH 无 `magick`）走 **pillow 兜底且降级留痕在**（`{from:magick,to:pillow,reason:E_TOOL_MISSING}`），`IMGSKILL_MAGICK` 注入则走 **magick 7.1.2-31、无降级**；**G1 像素级幂等**与位级（信息项，非门）均 True；`check_local_paths` **暂存后仍 PASS**（守卫内那处 `C:/Windows/win.ini` 是 G7 的越界**夹具**，正落在该门禁 docstring 自陈的「合成夹具／通用通例不在面」之内）。

**十项实施裁定**：

| # | 项 | **裁定** |
|---|---|---|
| 1 | `sandbox_root` 入参名 | **采纳**；本版**不进 MCP op 面**（沿 §九-#5「不新增 MCP op」） |
| 2 | `convert` 缺省 `dst` 后缀 | **采纳实现方解释**：取**目标格式后缀**（非「原后缀」）。理由：§九-#7 的「原后缀」是就**同格式** op 而言；`convert` 换格式时保留原后缀会产出「内容是 webp、名字是 .png」。**此为契约措辞瑕疵，本裁定即补正**：`dst` 派生 ＝ `<同名>_out` ＋ **目标格式后缀** |
| 3 | 审计台账落点 | **采纳** `<调用方沙箱根>/.imgskill/audit.jsonl`（落在沙箱根内，合 G5③ 精神） |
| 4 | `E_LEVEL_DOWNGRADE`／`E_UNSUPPORTED_OP` | **采纳为扩码**：§九 的「八码」是**契约面必判别集**，非全集；这两个属**范围／等级面**，一并导出并登记 |
| 5 | 校验次序（等级闸**先于**范围闸） | **采纳**——否则本版留白的 L1/L2 op 无从判降级，闸形同虚设 |
| 6 | 读写格式白名单显式化 | **采纳**（等价、可复跑、免每次探子进程） |
| 7 | `magick` 解析旋钮 | **采纳** `IMGSKILL_MAGICK` → `MAGICK_HOME` → `which`（PATH 未刷新期的必要通道） |
| 8 | G5① 运行期连带载入 `md_cg.trust` | **接受现状**：判据看 **imgskill 自身 import 面**（AST，零禁用模块）；包级连带来自 `md_cg/__init__.py`，本仓同族模块（`goal_gen`／`autonomy`）皆然，动 `__init__` 超本次范围。**登记为已知边界** |
| 9 | G6 判据边界（不判字面量拼接规避） | **接受**（与本仓「规则字面量拼接构造防自命中」的既有约定一致） |
| 10 | 符号链接逃逸／`E_PERM` 未实测 | **如实登记为未测项**（本机 `os.symlink` 报 WinError 1314 缺特权）；实现走 `realpath` 前缀比对，逻辑上覆盖但**未被真样例打过** |

**实现过程中查出并修掉一个真缺陷**：`magick %[channels]` 实返 `"srgb  4.0"`（带浮点尾巴），原样透出会污染 `meta.mode`——已取首 token 归一为 `RGB`。

**结论**：本版**可验收**；下一批 ＝ 其余 9 op 与 L1/L2 面（须先有模型／云侧，属步 3 邻域）。

---

## 十一、契约回写补正（v0.1-r1 · 2026-10-07 随补 op 批）

> **本节补正 §五 的若干点；冲突之处以本节为准。** 起因：实现 §五 余下 10 个 op 时发现该表有**三处内部冲突**（判据栏与实现栏互斥）与**两处未给取值**；实现方按「**判据优先、主后端语义优先**」做了 gap-fill，此处逐条确认并回写。

**（一）三处内部冲突 → 以「判据优先、主后端（`magick`）语义优先」为准**

| # | §五 原状 | 冲突 | **补正后（本节为准）** |
|---|---|---|---|
| A | `thumbnail` 判据「最长边 == `max_edge`（保持纵横比）」／实现栏写 `Pillow thumbnail()` | Pillow 的 `thumbnail()` **只缩不放**，与判据（缩与放两向都要求最长边 == `max_edge`）**互斥** | **判据不变**；Pillow 侧实现改为**等比 resize（LANCZOS）** |
| B | `rotate` 两栏方向 | `magick` 正角＝顺时针、Pillow `rotate` 正角＝逆时针，**互斥** | **取正角＝顺时针**（主后端语义）；Pillow 侧做方向反转补偿 |
| C | `flip`/`flop` 参数栏列了 `axis`；`composite` 命令栏含 `-geometry +X+Y` 而参数栏未列 | 参数栏与命令栏不一致 | `axis` 为**选填同轴确认项**；`composite` 位置**只由 `gravity` 定**，只收 `over_path`／`gravity`／`opacity`，**多余键 → `E_BAD_PARAM`** |

**（二）两处未给取值 → 确认实现方取值**：`thumbnail` 的 Pillow 侧滤波器**固定 LANCZOS**；`mask.mode` **本版只支持 `"set"`**（`mul` 等未落，走 `E_UNSUPPORTED_OP`——`magick` 单命令实测三种写法均无确定等价，为一个 mode 引多步中间产物不匹配收益）。

**（三）两处实现自加前提 → 接受**：`composite` 要求 **over ≤ base**、`mask` 要求 **mask 尺寸 == 源**——两后端在越界／异尺寸下行为不判齐，**fail-closed（`E_BAD_PARAM`）优于行为不可预期**（沿「不猜」原则）。

**（四）已接受、登记为已知差异（不设跨后端逐位门）**：`adjust`（magick 16-bit vs Pillow 8-bit LUT）与 `sharpen`（Pillow 侧固定 `percent=150, threshold=0`）**两后端数学不同源**——**判据不要求逐位**（§五 对这两行的判据是「参数入台账 ＋ 同参幂等」）；非直角 `rotate` 尺寸两后端本不同（45° 实测 magick 52×52／Pillow 50×50）——**只设 ±3px 内部门**。

**（五）`mask` 写面收窄 → 接受**：收窄为 `png`／`tif`／`tiff`——webp/bmp 编码器在 alpha 恒不透明时**会丢通道**，直接违反「alpha 通道存在且可读回」的判据。**判据优先**的正确取舍。

**（六）登记为后续小项（本批不改，超范围）**：`_classify_backend_err` 关键词表不含 magick 的 `invalid colormap index` ⇒「坏 palette PNG」这类损坏输入落 `E_BACKEND_FAIL` 而非 §3.3 的 `E_DECODE`（补关键词可同时改善多个 op，留下一批）；符号链接逃逸／`E_PERM` 仍**未用真样例打过**（沿 §十-#10）。

**补 op 批实测（编排侧亲跑）**：`md_cg/imgskill.py` 877→**1442 行**、`md_cg/test_imgskill.py` 557→**1229 行**；守卫 **两条后端各 39 passed / 0 failed**（默认 pillow 兜底带降级留痕；`IMGSKILL_MAGICK` 注入走 magick 7.1.2-31）；新增断言 21 条（既有 18 条未减弱，仅把 G3 的 `E_UNSUPPORTED_OP` 例由已实现的 `crop` 换为仍范围外的 `extract`）；7 件定点变异**各自恰好打中 1 项**；`check_local_paths` PASS。
