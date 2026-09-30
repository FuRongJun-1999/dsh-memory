//! job 目录文件协议（跨语言接口的真源）。
//!
//! ```text
//! jobs/
//!   _serve.json               # serve 心跳 {pid, ts, workers}（主循环每拍写）
//!   _quarantine/              # 坏 status 隔离保留区（H-3；doctor --quarantine 移入）
//!     <job_id>/               #   整体 rename 移入（任务目录原样，逐字节不动）
//!   <job_id>/
//!     spec.json               # 任务规格（submit 写；先写）
//!     status.json             # 状态（submit 写初始 pending；status.json 出现 = 任务就绪可领取）
//!     status.corrupt.json     # 坏 status 标记（H-3；serve 持续 N 拍解析失败后落。
//!                             #   **旁证，不是任务本体**——status.json 坏也照原样留着）
//!     result.json             # 执行器产物（成功/API 错误均写，error 字段区分；
//!                             #   锚预期任务须带 result_anchor 回写锚，见 scheduler）
//!     kill                    # kill 标志（任意宿主创建；worker 检测到即强杀）
//!     claimed.lock            # 领取原子锁（create_new 成功者独占该任务）
//! ```
//!
//! H-3（坏 status 不再静默）：`status.json` 不可解析时**既不改写它、也不当成
//! 半成品无限等待**——serve 周期扫描计数、达阈值落 `status.corrupt.json` 标记、
//! doctor 归 `corrupt` 独立类别、`doctor --quarantine` 可整体移入 `_quarantine/`
//! 退出领取面（可 --unquarantine 原路退回）。**自动终态化不做**：那会让坏文件被
//! 静默吞掉，正是本缺陷的反面；坏 status 的处置权留给显式隔离与人工。
//!
//! P11 结果完整性锚（批次53）：提交面解析到锚密钥（keyres.rs）时，status.json
//! 追加 `result_nonce`（init_job_with_slots）= 该任务声明锚预期——serve 拉起执行器
//! 时注入 HIVE_RESULT_ANCHOR（hmac.rs 公式），执行器回写 result.json
//! `result_anchor`，classify_result 采信 done 前校验；无 nonce 的旧格式任务保持
//! 旧判据（向后兼容）。
//!
//! 状态机：pending → claimed → running → done | error | timeout | killed
//!
//! 并发安全要点：
//!   * `claimed.lock` 用 `create_new(true)` 原子创建——多 serve 竞争时只有
//!     一个领取成功，其余跳过（不损坏数据）；
//!   * 领取后 status.json 只由持有者单写（worker 写心跳/终态），无双写者。

use crate::json::Json;
use std::fs;
use std::io::Write;
use std::path::{Path, PathBuf};
use std::sync::OnceLock;
use std::time::{SystemTime, UNIX_EPOCH};

/// 生效条件：恒成立（时钟倒退时 unwrap_or(0) 诚实回落）——返回当前 Unix 毫秒。
/// 全仓时间戳（status.created_ts/心跳/日志 _t）的单点时钟源。
/// **已退出 id 生成**（B7：id 归语义四槽，时间只在 created_ts 里）——排序口径走
/// [`list_jobs_by_created`]，勿退回「名序 = 时间序」的代理。
pub fn now_ms() -> u128 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|d| d.as_millis())
        .unwrap_or(0)
}

/// 生效条件：恒成立——jobs 根目录 + job_id 拼任务目录路径（目录协议的唯一拼装点）。
pub fn job_dir(jobs: &Path, id: &str) -> PathBuf {
    jobs.join(id)
}

// ============================================================ id 契约 v2（B1..B7）
//
// 契约真源：docs/plans/全中文编码与蜂巢任务标识契约_v2.0.md §四.4/§四.5/§四.7。
// **本文件是判据单点**（§五 裁决 3：分配器唯一实现 = Rust 侧；MCP/编排面调用它，
// 不自持第二份）。跨语言一致性（python 孪生闸 `mcp_server._valid_job_id` 与
// `_dep_gate`）靠 `hive/id_contract_corpus_v2.txt` 的对照语料逐例钉死——两侧对任何
// 一例判不同即红。
//
// id 形态：`h_<身份>_<任务>_<单元>_<编号>`，例 `h_zcode端_灵枢迭代_反思单元_0001`。
// 四槽全必填（不许静默推导）；编号 4 位定宽十进制、溢出显式报错；`h` 前缀保留、
// 存量零迁移（旧形态 `h<13位毫秒>_<4位hex>` 必须仍通过、仍被 list_jobs 收）。
//
// 无环性（I-1）**不由 id 保证**（C1 订正）：本文件此处原有一句失实论证——`new_job_id`
// 的 doc 曾写「h 前缀使 list_jobs 的名升序 = 提交时间升序（I-1 拓扑序无环性的**结构性
// 根基**，spec.rs depends_on 校验依赖此前缀）」。该函数已按 B7 退场，该论证亦随契约 v2
// 失实：新形态 id 不含时间 ⇒ 名序不再携带时序（名序 = 时序只是旧形态 `h<毫秒>_<hex>`
// 的巧合代理），论证不得依赖它。真实机制 = **存在性闸**——提交时只能引用**已存在**的
// 任务目录（`main.rs` 提交侧的 `depends_on` 存在性检查 + MCP 侧 `_dep_gate`），运行期
// 再由 `scheduler.rs::deps_gate` 复核目录存在，故引用不到提交时尚不存在的任务、
// 自引用亦不可能，无需运行时环检测。

// ------------------------------------------------ B5′：字符白名单（区块表 · 唯一真源）

/// 区块表数据文件（c1）：`hive/id_charset_blocks.txt`——三处读者（本文件、
/// `hive_mcp/mcp_server.py`、`md_cg/units.py`）**共读的唯一真源**，任何一处都不得
/// 再手写/内嵌区间常量（2026-09-30 使用者裁定 ①-(c)：判据从「Unicode 属性判定」
/// 换成「区块白名单」）。
///
/// 嵌入方式（c2）：`include_str!` **编译期嵌入**——文件缺失 = **编译失败**（比任何运行期
/// 检查都早）；首次使用时惰性解析成静态区间表（[`id_charset_blocks`]，纯 std、无第三方
/// crate，零依赖 D-005 不破）。
///
/// 为什么换面：旧判据（`is_alphanumeric() && !会改写区块命中`，本批退休）依赖**运行时的
/// Unicode 属性表**——Python `unicodedata` 与 Rust 工具链各随自己的版本演化，全码点意义
/// 上不可能同判（实测 Python 侧余 9713 个 Cn 残余码点只能声明方向安全）。新区块表下判据
/// **不查任何 Unicode 属性库**，两侧只读同一份数据 ⇒ 版本差**结构性不可能**。
pub const ID_CHARSET_BLOCKS_TEXT: &str = include_str!("../id_charset_blocks.txt");

/// 惰性解析结果：首次使用解析一次（`Err` 同样缓存——fail-closed 后不反复重试）。
static ID_CHARSET_BLOCKS: OnceLock<Result<Vec<(u32, u32)>, String>> = OnceLock::new();

/// 区块表解析（**唯一配方**，与 py / md_cg 两处读者同此一条）：每行取 `#` 之前部分后
/// `trim`；空行跳过；余下 `split('-')` 两段 `u32::from_str_radix(x, 16)`。
///
/// 生效条件：全表形态正确、区间升序且**已归并到最小**、总区间数非空 → `Ok(区间表)`。
/// 不适用条件：不做任何 Unicode 属性/版本判断——本函数只认识「十六进制区间」字面量。
/// 任一行不合形态 / 越界 / 相邻相交乱序 / 空表 → `Err(原因)`——**fail-closed**：
/// 绝不静默跳过坏行（跳过的表会变成一张更宽或更窄的表，两侧随即不同判）。
/// 行尾 `\r` 由 `trim` 吸收（本机 `core.autocrlf=true`，checkout 可能给整表 CRLF）。
fn parse_id_charset_blocks(text: &str) -> Result<Vec<(u32, u32)>, String> {
    let mut out: Vec<(u32, u32)> = Vec::new();
    for (i, line) in text.lines().enumerate() {
        let body = line.split('#').next().unwrap_or("").trim();
        if body.is_empty() {
            continue;
        }
        let mut parts = body.split('-');
        let (lo, hi) = match (parts.next(), parts.next(), parts.next()) {
            (Some(a), Some(b), None) => (a.trim(), b.trim()),
            _ => return Err(format!("区块表第 {} 行不是 LO-HI 形态: {line:?}", i + 1)),
        };
        let lo = u32::from_str_radix(lo, 16)
            .map_err(|e| format!("区块表第 {} 行起段非十六进制: {e}", i + 1))?;
        let hi = u32::from_str_radix(hi, 16)
            .map_err(|e| format!("区块表第 {} 行止段非十六进制: {e}", i + 1))?;
        if lo > hi || hi > char::MAX as u32 {
            return Err(format!("区块表第 {} 行区间非法: {lo:#X}-{hi:#X}", i + 1));
        }
        // 已归并到最小：升序 ∧ 不相邻 ∧ 不相交（手改成重叠/乱序即在此停手）。
        if let Some(&(_, prev_hi)) = out.last() {
            if lo <= prev_hi + 1 {
                return Err(format!(
                    "区块表第 {} 行未归并到最小（与前区间相邻/相交/乱序）: {lo:#X}-{hi:#X}",
                    i + 1
                ));
            }
        }
        out.push((lo, hi));
    }
    if out.is_empty() {
        return Err("区块表解析出空区间集（fail-closed：空表绝不放行）".to_string());
    }
    Ok(out)
}

/// 生效条件：表可解析且非空 → `Ok(区间表)`（升序、已归并到最小）；否则 `Err(原因)`。
/// 判据读者**必须**在 `Err` 时 fail-closed（见 [`id_charset_member`]），不得退回任何
/// Unicode 属性判定兜底。
pub fn id_charset_blocks() -> Result<&'static [(u32, u32)], &'static str> {
    match ID_CHARSET_BLOCKS.get_or_init(|| parse_id_charset_blocks(ID_CHARSET_BLOCKS_TEXT)) {
        Ok(v) => Ok(v.as_slice()),
        Err(e) => Err(e.as_str()),
    }
}

/// 生效条件：表为 `Ok` 且 c 的码点 ∈ 其区间并集 → true；表为 `Err` → **一律 false**
/// （fail-closed：表缺失/坏行/空表 ⇒ 绝不放行任何字符）。
/// 单列成函数是为了让「Err ⇒ false」这条 fail-closed 判据可被守卫直接断言
/// （[`tests::charset_gate_fails_closed_on_bad_table`]）。
fn charset_member_in(blocks: &Result<Vec<(u32, u32)>, String>, c: char) -> bool {
    match blocks {
        Ok(v) => {
            let u = c as u32;
            v.iter().any(|(lo, hi)| u >= *lo && u <= *hi)
        }
        Err(_) => false,
    }
}

/// 字符类判据（B5′ · **全仓唯一字符集判据**）：c 是否落在区块表的区间并集内。
///
/// **不查任何 Unicode 属性库**（不用 `char::is_alphanumeric`，也不做 NFC 计算）⇒
/// 两侧读者（Rust 工具链 vs Python `unicodedata`）的属性表版本差**结构性不可能**：
/// 接受集只由这一份数据文件决定，逐码点相同（守卫全码点遍历断言，见
/// [`tests::charset_predicate_equals_blocks_table`]）。
/// **NFC 保证方式**（c5）：表本身由脚本按「类目 ∈ {Lu,Ll,Lt,Lm,Lo,Nd} ∧ 单字符 NFC 稳定」
/// 生成（生成器与守卫各全表重算一遍）⇒ 本判据不必做真 NFC 计算，收下的 id 也保证已是
/// NFC 形态（**拒收而非静默归一化**，零依赖 D-005 下不必手写完整 NFC）。
///
/// 不适用条件：`_`(U+005F) 与 `.`(U+002E) **不在本表内**，由 [`valid_job_id`] 的
/// **结构分支**处理（槽分隔符 / 非尾点非单独的点）⇒ 本判据是「字符类」判据，不含这两个
/// 结构字符；`err` 侧不做任何兜底放行。
pub fn id_charset_member(c: char) -> bool {
    charset_member_in(
        ID_CHARSET_BLOCKS.get_or_init(|| parse_id_charset_blocks(ID_CHARSET_BLOCKS_TEXT)),
        c,
    )
}

/// 零宽与不可见注入载体（B4 拒收项）：U+200B..U+200F、U+2060、U+FEFF。
pub fn is_zero_width(c: char) -> bool {
    matches!(c, '\u{200B}'..='\u{200F}' | '\u{2060}' | '\u{FEFF}')
}

/// 双向控制字符（B4 拒收项）：U+202A..U+202E、U+2066..U+2069。
pub fn is_bidi_control(c: char) -> bool {
    matches!(c, '\u{202A}'..='\u{202E}' | '\u{2066}'..='\u{2069}')
}

/// Windows 保留设备名（B4 拒收项；本仓 v0.5.1 刚修过这一类，勿回退）：
/// CON/PRN/AUX/NUL + COM1..9 + LPT1..9。Win32 对**单个路径分量**做设备名解析且
/// **忽略扩展名**（`CON.txt` 与 `CON` 同指设备），故比对的是「首个 `.` 之前」部分。
pub const RESERVED_DEVICE_NAMES: &[&str] = &[
    "CON", "PRN", "AUX", "NUL", "COM1", "COM2", "COM3", "COM4", "COM5", "COM6", "COM7",
    "COM8", "COM9", "LPT1", "LPT2", "LPT3", "LPT4", "LPT5", "LPT6", "LPT7", "LPT8", "LPT9",
];

/// 生效条件：s 的「首个 `.` 之前」部分（Win32 解析设备名时用的 basename）与任一
/// 保留设备名**ASCII 大小写不敏感**相等 → true（含 `CON.txt` 这类带扩展名形态）。
pub fn is_reserved_device_name(s: &str) -> bool {
    let base = s.split('.').next().unwrap_or(s);
    RESERVED_DEVICE_NAMES.iter().any(|d| base.eq_ignore_ascii_case(d))
}

/// job_id 结构合法性（B4 字符集闸 + 防路径穿越；**全仓唯一判据**）。
///
/// 字符集判据（B4；2026-09-30 换面）：白名单 = **区块表区间并集**（[`id_charset_member`]，
/// 唯一真源 `hive/id_charset_blocks.txt`）**加两个结构字符** `_`（槽分隔符）与 `.`（非尾点、
/// 非单独才收）——由「ASCII 字母数字 + `_`」放宽后，新形态中文 id 与旧形态 id **同时**满足；
/// 旧形态 `h<13位毫秒>_<4位hex>` 仍通过（存量零迁移）。`h` 前缀与非空要求保留（§四.7：
/// 去掉它要牵动一大片，收益为零）。
/// **判据不查任何 Unicode 属性库**（不再用 `char::is_alphanumeric`）⇒ 与 Python 侧的
/// 属性表版本差**结构性不可能**；NFC 保证由表本身承载（表内每码点已由生成器筛过 NFC 稳定，
/// c3/c5）——`-` 与其他形态一律拒（不在表内、且不是结构字符）。
/// 拒收逐条在本函数内显式判，不靠上游、也不靠「表里没有所以顺带拒」：
///   * `/` `\` `:`（路径分隔/盘符/ADS；2026-09-25 缺陷载体：`kill ..` 池外写、
///     `poll ../victim` 池外读任意目录 result 全文）；
///   * 单独的 `.` 与 `..`（**整串**等于）、**按 `_` 分段的任一段**等于 `.`/`..`
///     （c7 段级：目录可作父段，成 5 段形态 ⇒ 段级 `..` 是真实载体）、尾点
///     （Win32 静默剥尾点 ⇒ 两个不同 id 落同一目录）；
///   * 控制字符（含 NUL）、零宽、双向控制；
///   * 首尾空白；
///   * Windows 保留设备名（含带扩展名形态）——整 id 与按 `_` 分段的**任一段**；
///   * 区块白名单（[`id_charset_member`]）之外的一切字符——含旧机制点名的「会归一化改写」
///     形态（兼容/带圈/上下标/数学字母数字/全角半角/兼容表意/组合标记…），它们都在候选
///     区块之外，见 `hive/id_charset_blocks.txt` 的「有意不收」段。
/// 生效条件：id 满足上述全部 → true；否则 false——kill/poll/depends_on 等一切把
/// **外部输入**的 job_id 拼进路径的入口，必须先过此闸。
pub fn valid_job_id(id: &str) -> bool {
    if id.is_empty() || !id.starts_with('h') {
        return false;
    }
    if id.trim() != id {
        return false; // 首尾空白
    }
    if id.ends_with('.') {
        return false; // 尾点
    }
    if id == "." || id == ".." {
        return false; // 相对段（h 前缀下已不可达；显式保留判据，防前缀规则漂移）
    }
    // 「. / ..」的**段级**判据（c7，2026-09-30 加固）：按 `_` 分段，**任一段**等于
    // `.` 或 `..` 即拒。为什么是段级：id 的每一段都可能被宿主当作**目录名**或**父目录段**
    // 用（契约 §四.4「任务槽：目录可作它的父段」，即 5 段形态），段级 `..` 因此是真实载体。
    // 现场定性（如实）：现状整串口径收下 `h_.._x` / `h_a_.._b` 这类「含 `..` 段但不以点
    // 结尾」的 id，其拼出的路径**停在池内**、不构成穿越 ⇒ 本次是**面向重构的纵深加固**，
    // 不是现实缺陷的修补。范围**只加这一条**：不拒空段（`h__x`）等其它形态——那是未被
    // 裁定的行为收紧，不许顺手做。
    if id.split('_').any(|seg| seg == "." || seg == "..") {
        return false;
    }
    for c in id.chars() {
        if c.is_control() || c == '/' || c == '\\' || c == ':' {
            return false;
        }
        if is_zero_width(c) || is_bidi_control(c) {
            return false;
        }
        if c == '_' || c == '.' {
            continue;
        }
        if !id_charset_member(c) {
            return false;
        }
    }
    if is_reserved_device_name(id) {
        return false;
    }
    // 段级设备名：id 的任一段都可能被宿主用作目录名（契约 §四.4「目录可作它的
    // 父段」），而 Win32 的设备名解析是**按分量**做的——故任一段命中即拒。
    if id.split('_').any(is_reserved_device_name) {
        return false;
    }
    true
}

/// 四槽之一的结构校验（B8 提交面；id 拼装前的唯一槽闸）。
///
/// 槽取值 = 语义标签（身份/任务/单元），落进 id 就是路径分量的一段，故判据与
/// [`valid_job_id`] 同族：**每字符必须落在区块白名单内**（[`id_charset_member`]，唯一真源
/// `hive/id_charset_blocks.txt`；不查任何 Unicode 属性库）——这意味着槽内不含 `_`
/// （它是槽分隔符，含它就无法切回四槽）、不含 `.`/路径分隔符/控制与零宽字符；
/// 另外不得是 Windows 保留设备名（`CON`/`NUL`/`COM1`…，含大小写变体）。
/// **显式拒收集合**（c7/c9：白名单外是「默认被拒」，但结构面必须逐条显式断言——
/// 防将来有人放宽某个区块时把它们带进来）：`_` / 路径成分 `/` `\` `:` / `.` /
/// 控制字符 / 零宽（U+200B..200F、U+2060、U+FEFF）/ 双向控制（U+202A..202E、U+2066..2069）。
/// 这些断言与白名单**同向**（它们本就不在表内）⇒ 判据面不变、拒绝面更显式。
/// 生效条件：slot=槽名（身份/任务/单元）、value 合法 → Ok(())；否则 Err，错误文本
/// 含槽名与取值（可直读、可照抄）。
pub fn valid_slot(slot: &str, value: &str) -> Result<(), String> {
    if value.is_empty() || value.trim() != value {
        return Err(format!(
            "{slot}槽为空（或含首尾空白）——四槽全必填，不许静默推导"
        ));
    }
    for c in value.chars() {
        if c == '_' {
            return Err(format!(
                "{slot}槽非法: {value:?}——槽取值不得含 `_`（它是 id 的槽分隔符，含它就切不回四槽）"
            ));
        }
        // c7/c9 显式拒收（白名单外是默认被拒，但结构面必须逐条显式断言，不靠「表里没有」）：
        if c.is_control() {
            return Err(format!(
                "{slot}槽非法: {value:?}——含控制字符 U+{:04X}",
                c as u32
            ));
        }
        if is_zero_width(c) || is_bidi_control(c) {
            return Err(format!(
                "{slot}槽非法: {value:?}——含零宽/双向控制字符 U+{:04X}",
                c as u32
            ));
        }
        if c == '/' || c == '\\' || c == ':' || c == '.' {
            return Err(format!(
                "{slot}槽非法: {value:?}——含路径成分或点（`/` `\\` `:` `.`；槽取值是 id 的路径分量段）"
            ));
        }
        if !id_charset_member(c) {
            return Err(format!(
                "{slot}槽非法: {value:?}——槽取值须为区块白名单内的字母/数字（判据 = \
                 `hive/id_charset_blocks.txt` 的区间并集，不查 Unicode 属性库；表外形态一律拒，\
                 含会归一化改写的形态）"
            ));
        }
    }
    if is_reserved_device_name(value) {
        return Err(format!(
            "{slot}槽非法: {value:?}——Windows 保留设备名（CON/PRN/AUX/NUL/COM1..9/LPT1..9，\
             含 CON.txt 这类带扩展名形态）"
        ));
    }
    Ok(())
}

// ------------------------------------------------------ B2：五单元闭集（真源同源）

/// 蜂巢五单元闭集（B2）：(英文键, 落 id 的中文名)，顺序 = 真源 `md_cg/identity.py`
/// 的 `POSITIONS` 声明顺序（= `POSITION_ORDER`）。
///
/// 真源唯一：本表与 `identity.POSITIONS` 的同源由单测
/// [`tests::units_match_identity_positions`] 机械钉死（任一侧增删即红）。
/// **副代理不是第六单元**（副代理是融合位 𝓕 本身，五单元是它的功能分解）⇒ 恰 5 项。
pub const UNITS: &[(&str, &str)] = &[
    ("record", "记录单元"),
    ("reflect", "反思单元"),
    ("verify", "验证单元"),
    ("output", "输出单元"),
    ("sustain", "维生系统"),
];

/// 单元槽受理面（B2）：**英文键或中文名两种写法都收**，落 id 一律中文名。
/// 生效条件：unit 命中闭集任一写法 → Some(中文名)；否则 None（调用方 fail-closed）。
pub fn unit_canonical(unit: &str) -> Option<&'static str> {
    UNITS.iter()
        .find(|(en, zh)| *en == unit || *zh == unit)
        .map(|(_, zh)| *zh)
}

/// 五单元词表串（错误文本与守卫用）：形状 `record=记录单元 / reflect=反思单元 / …`。
pub fn unit_inventory() -> String {
    UNITS.iter()
        .map(|(en, zh)| format!("{en}={zh}"))
        .collect::<Vec<_>>()
        .join(" / ")
}

// -------------------------------------------- B1/B3：独占创建即分配的 id 分配器

/// 编号上限：每单元 9999（B3 裁定：4 位定宽，溢出**显式报错**，不静默加宽）。
pub const MAX_UNIT_SEQ: u32 = 9999;
/// 编号定宽（十进制 4 位，B1）。
pub const SEQ_WIDTH: usize = 4;

/// 同前缀已有编号最大值 + 1（**仅起点提示**）。分配成败一律以 `fs::create_dir`
/// 为准（B3）——本函数只影响「从几号开始试」，不影响正确性。
/// 返回值 ∈ `1..=MAX_UNIT_SEQ + 1`；取到 `MAX_UNIT_SEQ + 1`（= 10000）只说明「最高号位
/// `…_9999` 已被占用」，**不是用尽结论**——起点越过上限时由 [`seq_candidates`] 回绕到
/// 低位段继续（同样 4 位定宽），用尽与否一律由 create_dir 的碰撞面说话。
/// 生效条件：jobs 可读 → 同前缀目录中 4 位十进制尾段的最大值 +1；无同前缀件/目录
/// 不可读/尾段形态不符 → 1（不 panic、不伪造默认值）。
fn next_seq_hint(jobs: &Path, prefix: &str) -> u32 {
    let mut max = 0u32;
    if let Ok(rd) = fs::read_dir(jobs) {
        for e in rd.flatten() {
            if !e.path().is_dir() {
                continue;
            }
            let name = e.file_name().to_string_lossy().to_string();
            if let Some(tail) = name.strip_prefix(prefix) {
                if tail.len() == SEQ_WIDTH && tail.chars().all(|c| c.is_ascii_digit()) {
                    if let Ok(n) = tail.parse::<u32>() {
                        if n > max {
                            max = n;
                        }
                    }
                }
            }
        }
    }
    max.saturating_add(1)
}

/// 号位搜索序（B3/c1）：**先在号位间回绕地搜**——先 `hint..=MAX_UNIT_SEQ`，
/// 再回绕到 `1..hint`。
///
/// 两个区间**互不重叠**，并集恰是 `1..=MAX_UNIT_SEQ` 的全部 9999 个号位 ⇒
/// **每个号位至多被尝试一次**（不重复试号、不 panic、不死循环）。`hint` 越过上限时
/// 第一段为空（`10000..=9999`）；`hint == 1` 时第二段为空（`1..1`）——**空区间就是空
/// 迭代**，行为确定。回绕段上界夹到 `MAX_UNIT_SEQ + 1`，故 `hint` 再大也不会让搜索序
/// 产出 5 位号位（4 位定宽的前提只由搜索序的**值域**保证，与起点取值无关）。
///
/// **两个「回绕」必须分清**（c1/c2，两个读法不能混）：
///   · **编号值不回绕**——分配出的编号**绝不**溢出成 `0001` 去复用已发布的 id；
///     9999 个号位全被占用时一律**显式报错**、不自动加宽（B3 裁定）。
///   · **搜索在号位间回绕**——只是「试号的**顺序**」绕一圈，好把 9999 个号位**用尽**；
///     `hint` 仅作起点提示，分配成败**一律以 `fs::create_dir` 的碰撞面为准**。
fn seq_candidates(hint: u32) -> impl Iterator<Item = u32> {
    // 回绕段 = 1..=(hint-1)，上界夹到 10000 使号位恒 ≤ 9999（定宽 4 位）。
    let wrap_hi = hint.min(MAX_UNIT_SEQ + 1);
    (hint..=MAX_UNIT_SEQ).chain(1..wrap_hi)
}

/// 分配 job_id（B1/B3/B7）：`h_<身份>_<任务>_<单元>_<编号>`。
///
/// 算法 = **独占创建即分配**：对 `jobs/<id>` 执行 `fs::create_dir`，成功即分配；
/// `AlreadyExists` **才算碰撞** ⇒ 取搜索序里的下一个号位重试。搜索序见
/// [`seq_candidates`]：先 `hint..=MAX_UNIT_SEQ`、再**回绕** `1..hint`（起点
/// `hint` = [`next_seq_hint`] 的「同前缀已有编号最大值 +1」，**只是起点提示**，
/// 不参与成败判定）。非 `AlreadyExists` 的建目录错误**当场返回 Err**，绝不吞。
/// 性质：碰撞**结构上不可能**（不再依赖「毫秒恰好不同 ∧ pid 恰好不同」——
/// H-1 的碰撞那半因此被消解而非修补）。
///
/// **两个「回绕」必须分清**（c1/c2 点名的读法陷阱）：
///   · **编号值不回绕**：分配出的编号恒为 4 位定宽 `0001..=9999`——用尽即**显式报错**，
///     既不加宽成 5 位，也**不溢出回绕成 `0001`** 去复用已发布的 id；
///   · **搜索在号位间回绕**：只绕「试号顺序」（起点之后的低位段），目的是把 9999 个号位
///     **全部用尽**——故池内只存 `…_9999` 时（起点 = 10000 > 上限）仍能分配到空闲的
///     `…_0001`，而不是白扔 9998 个号位。
/// 上述「用尽」是**可证事实**而非猜测：循环跑完 = 搜索序（并集 `1..=9999`）中每个号位
/// 的 create_dir 都返回了 `AlreadyExists`，其余错误已在上文当场 Err ⇒ 报错文案与池内事实
/// 必然相符。
/// 生效条件：jobs 可建、三槽合法、单元 ∈ 五单元闭集、**号位未满** → Ok(id)
/// （**目录已创建** = 分配已完成；调用方随后写 spec/status）；任一不满足 → Err
/// （含前缀/槽名/上限等可直读原因，绝不静默降级）。
/// 不适用条件：不写 spec.json/status.json（写序归 [`init_job_with_slots`]）；
/// 不改动任何既有任务目录。
pub fn alloc_job_id(
    jobs: &Path,
    identity: &str,
    task: &str,
    unit: &str,
) -> Result<String, String> {
    valid_slot("身份", identity)?;
    valid_slot("任务", task)?;
    let unit_zh = unit_canonical(unit).ok_or_else(|| {
        format!(
            "单元槽非法: {unit:?}——单元槽取蜂巢五单元**闭集**（英文键或中文名二选一）：{}",
            unit_inventory()
        )
    })?;
    fs::create_dir_all(jobs)
        .map_err(|e| format!("建 jobs 目录失败 {}: {e}", jobs.display()))?;
    let prefix = format!("h_{identity}_{task}_{unit_zh}_");
    let width = SEQ_WIDTH;
    let mut last_collision = String::new();
    // 搜索在号位间回绕：起点只是提示，循环覆盖全部 9999 个号位（每个至多试一次）。
    for n in seq_candidates(next_seq_hint(jobs, &prefix)) {
        let id = format!("{prefix}{n:0width$}");
        match fs::create_dir(job_dir(jobs, &id)) {
            Ok(()) => return Ok(id),
            Err(e) if e.kind() == std::io::ErrorKind::AlreadyExists => {
                last_collision = id;
            }
            Err(e) => {
                return Err(format!(
                    "建任务目录失败 {}: {e}",
                    job_dir(jobs, &id).display()
                ));
            }
        }
    }
    // 走到这里 = 1..=9999 的每个号位都返回了 AlreadyExists（非碰撞错误已当场 Err）
    // ⇒ 「全部被占用」是按事实说话，不是猜测（旧的「已无可用编号」会被读成
    // 「前面也满了」，而当时 0001..9998 实际可能全空闲）。
    Err(format!(
        "编号用尽: 前缀 {prefix} 的 {MAX_UNIT_SEQ} 个号位已全部被占用（4 位定宽、不自动加宽）\
         ——请换任务槽或另起单元{tail}",
        tail = if last_collision.is_empty() {
            String::new()
        } else {
            format!("；末次碰撞 {last_collision}")
        }
    ))
}

/// 覆盖写 JSON 文本（UTF-8）——tmp + fsync + rename 原子替换。
///
/// 禁止直接 `File::create` 目标文件：它先把旧文件截断为 0 字节，并发读者
/// （patch_status 读-改-写、poll/doctor 轮询）会在「截断后、写完前」的窗口
/// 读到空文件导致 parse 失败。同目录 rename 在 POSIX 与 Windows
///（MoveFileEx + REPLACE_EXISTING）上均为原子替换，读者只见旧内容或新内容。
/// tmp 名带 pid：多 serve 竞争写 `_serve.json` 时互不踩踏，rename 最后写者赢。
/// 生效条件：写 JSON 文本（UTF-8）——tmp + fsync + rename 原子替换；并发读者
/// 只见旧内容或新内容，绝不读空；多写者竞争时 rename 最后写者赢。
/// 不适用条件：不保证跨进程写序（那由上层协议——status 单写者/日志锁——承载）。
pub fn write_json(path: &Path, v: &Json) -> std::io::Result<()> {
    let data = v.to_json_string();
    let tmp = path.with_extension(format!("tmp{}", std::process::id()));
    {
        let mut f = fs::File::create(&tmp)?;
        f.write_all(data.as_bytes())?;
        f.sync_all()?;
    }
    fs::rename(&tmp, path)
}

/// 读 JSON 文本并解析（坏文件按错误返回，不静默吞）。
/// 生效条件：文件存在且为合法 JSON → Ok(Json)；不存在/坏文件 → Err（含路径，
/// 不静默吞——坏文件是事故信号不是默认值来源）。
pub fn read_json(path: &Path) -> Result<Json, String> {
    let text = fs::read_to_string(path).map_err(|e| format!("{}: {e}", path.display()))?;
    crate::json::parse(&text).map_err(|e| format!("{}: {e}", path.display()))
}

/// 结果锚 nonce（P11，批次53）：提交时生成、落 status.json `result_nonce`，
/// 与锚密钥（keyres.rs）共同参与结果完整性锚公式（hmac.rs::result_anchor_hex）。
/// nonce 只求**任务内唯一**（防锚跨任务复用），秘密性归锚密钥——故非密码学熵：
/// FNV-1a 混合 毫秒时钟 + pid + 进程内计数器 + 栈地址（ASLR）。
/// 生效条件：恒成立——每次调用返回 16 hex 字符；同进程单调计数保证批量提交
/// 互异，跨进程由 (时钟, pid, ASLR) 区分。
pub fn new_result_nonce() -> String {
    use std::sync::atomic::{AtomicU64, Ordering};
    static COUNTER: AtomicU64 = AtomicU64::new(0);
    let c = COUNTER.fetch_add(1, Ordering::Relaxed);
    let addr = &c as *const u64 as u64;
    let mut h: u64 = 0xcbf2_9ce4_8422_2325; // FNV-1a offset basis
    for x in [now_ms() as u64, std::process::id() as u64, c, addr] {
        for b in x.to_le_bytes() {
            h ^= b as u64;
            h = h.wrapping_mul(0x0000_0100_0000_01b3);
        }
    }
    format!("{h:016x}")
}

/// 四槽建任务（B7/B8 的**写序单点**）：先 [`alloc_job_id`] 独占分配 id（任务目录
/// 即由它创建）→ 落 spec.json → 再落初始 status(pending)。
/// 写序：spec.json 先行，status.json 后写 = 「任务就绪」信号，
/// serve 只领取见到 status.json 且 state=pending 的任务。
/// 锚感知（P11，批次53）：nonce 给定（= 提交面解析到了锚密钥）时在 status.json 追加
/// `result_nonce` 字段——该任务自此**声明锚预期**：终态判据面在采信 done 前校验
/// result.json 的 result_anchor（scheduler::classify_result）；nonce 为 None =
/// 旧格式任务（无锚预期），终态判据保持旧口径（向后兼容：存量消费者零变更）。
/// 生效条件：三槽合法（[`valid_slot`]）、单元 ∈ 五单元闭集、号位未满、jobs 可写 →
/// 返回 job_id；分配失败/任一写失败 → Err 且目录残留半成品（无害：serve 只领取
/// 见到 status.json 且 state=pending 的任务）。
/// 不适用条件：不再自造 id（B7：`new_job_id` 退场，id 一律由分配器独占创建得出）。
#[allow(clippy::too_many_arguments)]
pub fn init_job_with_slots(
    jobs: &Path,
    identity: &str,
    task: &str,
    unit: &str,
    spec_json: &Json,
    timeout_s: u64,
    nonce: Option<&str>,
) -> Result<String, String> {
    let id = alloc_job_id(jobs, identity, task, unit)?;
    let dir = job_dir(jobs, &id);
    write_json(&dir.join("spec.json"), spec_json)
        .map_err(|e| format!("写 spec.json 失败: {e}"))?;
    let mut status = vec![
        ("job_id".to_string(), Json::Str(id.clone())),
        ("state".to_string(), Json::Str("pending".to_string())),
        ("created_ts".to_string(), Json::Num(now_ms() as f64)),
        ("started_ts".to_string(), Json::Null),
        ("heartbeat_ts".to_string(), Json::Null),
        ("elapsed_s".to_string(), Json::Num(0.0)),
        ("timeout_s".to_string(), Json::Num(timeout_s as f64)),
        ("model".to_string(), Json::Null),
        ("pid".to_string(), Json::Null),
        ("error".to_string(), Json::Null),
    ];
    if let Some(n) = nonce {
        status.push(("result_nonce".to_string(), Json::Str(n.to_string())));
    }
    write_json(&dir.join("status.json"), &Json::Obj(status))
        .map_err(|e| format!("写 status.json 失败: {e}"))?;
    Ok(id)
}

/// 原子领取：`claimed.lock` create_new 成功者独占。返回 false = 已被领取。
/// 生效条件：claimed.lock 以 create_new 原子创建——成功 true = 本实例独占领取，
/// false = 已被领取（多 serve 竞争只有一胜者，不损坏数据）。
pub fn claim(dir: &Path) -> bool {
    fs::OpenOptions::new()
        .write(true)
        .create_new(true)
        .open(dir.join("claimed.lock"))
        .is_ok()
}

/// 读 status.json；不存在按 pending 前态处理（理论上仅在竞态窗口）。
/// 生效条件：status.json 存在且合法 → Ok(Json)；不存在 → Err（竞态窗口内
/// 调用方按 pending 前态处理）；坏文件 → Err（事故信号不吞）。
pub fn read_status(dir: &Path) -> Result<Json, String> {
    read_json(&dir.join("status.json"))
}

// ---------------------------------------------------- H-3 坏 status（可观测且可处置）

/// status.json 读取**三态**（H-3）。
///
/// 旧 `read_status` 把「文件不在」与「文件在但坏」都归 Err，调用方无从分辨
/// 「提交竞态窗口（正常时序，下拍就好）」与「status 损坏（事故，永不自愈）」，
/// 于是只能一律当半成品无限等待——这正是 H-3 的病灶（任务既不被领取也不被
/// 清理，只在 doctor 里变成一个 unknown）。
/// 生效条件：dir/status.json 存在且可解析 → `Ok(Json)`；**不存在** → `Absent`
/// （提交竞态窗口/手工删，调用方按「未就绪」下拍再看）；存在但读/解析失败 →
/// `Corrupt(原因)`——**必须与 Absent 区别对待**：Corrupt 是可观测、可标记、
/// 可隔离的事故信号，Absent 是正常时序。判据唯一实现（serve 主循环 /
/// recover_orphans / doctor 三处共用，勿各自 try/catch 出第二套口径）。
/// 不适用条件：不判断 state 取值合法性（那是 state 语义面的事，与本判据无关）。
pub enum StatusRead {
    Ok(Json),
    Absent,
    Corrupt(String),
}

/// 生效条件：dir 给定 → 按 StatusRead 三态分类（存在性先判，再解析）；
/// 文件不存在一律 Absent（与解析失败的 Corrupt 不混淆）。
pub fn read_status_classified(dir: &Path) -> StatusRead {
    let p = dir.join("status.json");
    if !p.is_file() {
        return StatusRead::Absent;
    }
    match read_json(&p) {
        Ok(v) => StatusRead::Ok(v),
        Err(e) => StatusRead::Corrupt(e),
    }
}

/// 坏 status 标记文件名（H-3）。
///
/// **旁证，不是任务本体**：status.json 即便不可解析也照原样留着（既是诊断证据，
/// 也是人工修复的输入）——标记只是「这台任务当前坏着」的独立落点，任何路径都
/// **不得**改写成 status.json 自己（覆盖任务本体 = 把事故静默吞掉）。
pub const CORRUPT_MARK: &str = "status.corrupt.json";

/// 坏 status 隔离保留区目录名（H-3）：池内子目录，`list_jobs` 只收 `h` 前缀
/// 目录，故移入者自动退出领取面/统计面（=「移出池」），但同卷同根——rename
/// 原子、任务目录逐字节不动、可原路退回（`doctor --unquarantine`）。
pub const QUARANTINE_DIR: &str = "_quarantine";

/// 生效条件：恒成立——坏 status 标记文件的路径（dir/status.corrupt.json）。
pub fn corrupt_mark_path(dir: &Path) -> PathBuf {
    dir.join(CORRUPT_MARK)
}

/// 生效条件：标记文件存在且合法 → Some(Json)；不存在/坏文件 → None
/// （消费者按「无标记」处理，不伪造默认值）。
pub fn read_corrupt_mark(dir: &Path) -> Option<Json> {
    read_json(&corrupt_mark_path(dir)).ok()
}

/// 生效条件：标记文件存在则删除，返回是否真的删了（幂等：无标记 → false
/// 不报错）——status 恢复可解析时撤销标记，信号跟随现实而非陈化。
pub fn clear_corrupt_mark(dir: &Path) -> bool {
    fs::remove_file(corrupt_mark_path(dir)).is_ok()
}

/// 落坏 status 标记（H-3）：**只写 status.corrupt.json，绝不碰 status.json**。
/// 生效条件：dir 可写且 job_id/ticks/threshold/first_ts/err 给定 → 写标记文件
/// （tmp+rename 原子，write_json 同款）；写失败 → Err 透传（serve 侧 `let _`，
/// 标记尽力而为：盘满/只读时 serve 的 stderr 告警与 doctor 归类仍在，不静默）。
/// 不适用条件：不改写/不改名 status.json（任务本体不受任何影响）。
pub fn write_corrupt_mark(
    dir: &Path,
    job_id: &str,
    ticks: u64,
    threshold: u64,
    first_ts: u128,
    err: &str,
) -> Result<(), String> {
    let v = Json::Obj(vec![
        ("job_id".to_string(), Json::Str(job_id.to_string())),
        ("kind".to_string(), Json::Str("status_unparseable".to_string())),
        ("detected_ts".to_string(), Json::Num(now_ms() as f64)),
        ("first_ts".to_string(), Json::Num(first_ts as f64)),
        ("ticks".to_string(), Json::Num(ticks as f64)),
        ("threshold".to_string(), Json::Num(threshold as f64)),
        ("last_error".to_string(), Json::Str(err.to_string())),
        (
            "note".to_string(),
            Json::Str(
                "status.json 不可解析（≥threshold 拍）：任务不被领取、不被改写；\
                 处置=doctor 归类 corrupt 后 doctor --quarantine 移出池（可 --unquarantine 退回）。\
                 本标记为独立旁证文件，status.json 本体逐字节未动。"
                    .to_string(),
            ),
        ),
    ]);
    write_json(&corrupt_mark_path(dir), &v).map_err(|e| e.to_string())
}

/// 隔离保留区中的任务名（H-3）：jobs/_quarantine 下 h 前缀目录，名升序。
/// 生效条件：jobs 给定 → 返回保留区内的任务目录名（目录不存在 → 空列表）；
/// 这些任务已退出领取面（list_jobs 不收），doctor 据此如实报「已隔离」。
pub fn quarantined_jobs(jobs: &Path) -> Vec<String> {
    let mut out = Vec::new();
    if let Ok(rd) = fs::read_dir(jobs.join(QUARANTINE_DIR)) {
        for e in rd.flatten() {
            let name = e.file_name().to_string_lossy().to_string();
            if name.starts_with('h') && e.path().is_dir() {
                out.push(name);
            }
        }
    }
    out.sort();
    out
}

/// 更新 status.json 的若干字段（读-改-写，全量覆盖）。
/// 生效条件：status.json 合法可读 → 读-改-写全量覆盖（write_json 原子替换），
/// 字段存在则覆写、不存在则追加；不可读 → Err。单写者纪律：仅领取者/serve
/// 写 status（并发安全要点，见模块头）。
pub fn patch_status(dir: &Path, fields: Vec<(String, Json)>) -> Result<(), String> {
    let mut st = read_status(dir)?;
    if let Json::Obj(kv) = &mut st {
        for (k, v) in fields {
            match kv.iter_mut().find(|(ek, _)| *ek == k) {
                Some(slot) => slot.1 = v,
                None => kv.push((k, v)),
            }
        }
    }
    write_json(&dir.join("status.json"), &st).map_err(|e| e.to_string())
}

/// worker 心跳：刷新 heartbeat_ts / elapsed_s / state。
/// 生效条件：worker 运行中周期调用——刷新 state/heartbeat_ts/elapsed_s
/// （started_ms>0 时按 now-started 计，否则 0）；超时强杀的「失联判据」即
/// heartbeat_ts 停更。写入失败 → Err 透传（worker 自行决定重试/退出）。
pub fn heartbeat(dir: &Path, state: &str, started_ms: u128) -> Result<(), String> {
    let now = now_ms();
    let elapsed = if started_ms > 0 { (now - started_ms) as f64 / 1000.0 } else { 0.0 };
    patch_status(
        dir,
        vec![
            ("state".to_string(), Json::Str(state.to_string())),
            ("heartbeat_ts".to_string(), Json::Num(now as f64)),
            ("elapsed_s".to_string(), Json::Num((elapsed * 100.0).round() / 100.0)),
        ],
    )
}

/// kill 标志是否存在。
/// 生效条件：恒成立——kill 标志文件存在即 true（任意宿主创建，跨语言 kill 通道）。
pub fn kill_requested(dir: &Path) -> bool {
    dir.join("kill").exists()
}

/// 写 kill 标志（幂等）。
/// 生效条件：幂等写 kill 标志文件（已存在不重复创建）；写失败 → Err。
/// 不适用条件：不直接杀进程——真正回收由 worker 检测标志后的 kill 树路径执行。
pub fn request_kill(dir: &Path) -> Result<(), String> {
    let p = dir.join("kill");
    if !p.exists() {
        fs::File::create(&p).map_err(|e| format!("写 kill 标志失败: {e}"))?;
    }
    Ok(())
}

/// 列出全部任务目录名（按名升序；**不再是**时间升序——C2 订正）。
/// 生效条件：恒成立——jobs 目录下 h 前缀子目录按名升序返回；目录不可读 → 空列表。
/// 该顺序**不是**时序保证：名序 = 提交时序只对旧形态 id（`h<毫秒>_<hex>`）成立，
/// id 契约 v2 起 id 不含时间（B7），故不得再以「job_id 含毫秒时间戳」为由把名序读作时序。
///
/// 边界：本函数是**名升序**，也是存量调用点依赖的现状口径（A4：不得改成按
/// created_ts 排）。「名升序 = 时间升序」只对旧形态 id（`h<毫秒>_<hex>`）成立；
/// 需要**真值时间序**（新形态 id 下名序不再带时间序）的唯一单点 =
/// [`list_jobs_by_created`]，逐位相等的旧形态保序见其单测
/// `list_jobs_by_created_preserves_legacy_order`。
pub fn list_jobs(jobs: &Path) -> Vec<String> {
    let mut out = Vec::new();
    if let Ok(rd) = fs::read_dir(jobs) {
        for e in rd.flatten() {
            let name = e.file_name().to_string_lossy().to_string();
            if name.starts_with("h") && e.path().is_dir() {
                out.push(name);
            }
        }
    }
    out.sort();
    out
}

/// 读 `dir/status.json` 的 `created_ts` 真值（Unix 毫秒）。
///
/// 缺失 / 非数 / 负值 / status.json 不存在或不可解析 → `i64::MIN`（=「无时间」哨兵，
/// 排最前）。**读失败不 panic、不伪造默认值、结果确定**：任何异常输入都归到同一个
/// 可预期的哨兵值，绝不因单个坏任务让整体排序不确定。**只读**——本函数（及其调用方
/// `list_jobs_by_created`）不新建/不修改任何文件。
/// 生效条件：dir 给定 → 返回 i64（`i64::MIN` 表示无有效 created_ts）；
/// 不适用条件：不做状态判读、不做存在性检查（那是 read_status_classified 的事）。
fn created_ts_of(dir: &Path) -> i64 {
    let st = match read_status(dir) {
        Ok(v) => v,
        Err(_) => return i64::MIN,
    };
    match st.get("created_ts").and_then(|x| x.as_f64()) {
        Some(n) if n.is_finite() && n >= 0.0 => n as i64,
        _ => i64::MIN,
    }
}

/// 列出全部任务目录名，按 **created_ts 真值升序**（次键 id 字典序）。
///
/// 与 `list_jobs` 的关系：**成员集合同一口径**（都走 list_jobs 的 h 前缀目录过滤 +
/// 同一 `job_dir` 拼装），只有排序键不同——故存量池零迁移（旧形态 id 照样被收）。
/// 排序读的是每个任务 `status.json` 的 `created_ts`，不是目录名：旧形态
/// `h<毫秒>_<hex>` 下两者一致（保序，见单测），新契约 id 下名序不再带时间序，故
/// 一切「按时间序」的语义（FIFO 领取 / 最老者去重 / 汇总遍历）必须走本单点。
/// 缺 created_ts（缺失/非数/负值/读失败）→ `i64::MIN` 排最前，同哨兵值内按 id
/// 字典序（与 `list_jobs` 的名序同口径）——总序确定，且与目录枚举次序无关。
/// 生效条件：jobs 给定 → 返回 created_ts 升序、次键 id 字典序的任务目录名；
/// 池空/目录不可读 → 空列表。**只读**：绝不新建/修改任何文件。
/// 不适用条件：不改写 `list_jobs` 本身（A4：存量调用点依赖它的名序现状）。
pub fn list_jobs_by_created(jobs: &Path) -> Vec<String> {
    let mut keyed: Vec<(i64, String)> = list_jobs(jobs)
        .into_iter()
        .map(|id| (created_ts_of(&job_dir(jobs, &id)), id))
        .collect();
    keyed.sort_by(|a, b| a.0.cmp(&b.0).then_with(|| a.1.cmp(&b.1)));
    keyed.into_iter().map(|(_, id)| id).collect()
}

/// 写 serve 心跳。
///
/// `exec_py` / `exec_mode` 是**执行器资格的权威来源**（serve 启动时固化）：serve 的 env
/// 对另一个进程不可反查，doctor 若拿自身 env 判资格必得错位结论。故由 serve 把自己
/// 真实生效的执行器写进心跳——任何入口（CLI doctor / MCP doctor）读同一块即同口径。
/// 生效条件：serve 主循环每拍调用——写 _serve.json（pid/ts/workers/exec_py/
/// exec_mode，tmp+rename 原子）。互验身份字段需走 write_serve_heartbeat_ext。
pub fn write_serve_heartbeat(
    jobs: &Path,
    workers: usize,
    exec_py: &Path,
    exec_mode: &str,
) -> Result<(), String> {
    write_serve_heartbeat_ext(
        jobs,
        workers,
        exec_py,
        exec_mode,
        None,
        None,
        None,
        None,
        None,
    )
}

/// 写 serve 心跳（互验扩展，批次10 §7.2）：instance/role/fingerprint/iter_id/
/// progress 五字段由 serve 自报（env 固化 + 判据面 digest），**显式设置才落**——
/// 消费者对缺失字段按「未知」处理，不伪造默认值（跨进程 env 不可反查，
/// 心跳是唯一权威来源）。
/// 生效条件：同 write_serve_heartbeat，另附互验五字段（instance/role/
/// fingerprint/iter_id/progress）——**显式 Some 才落**，None 时字段缺失，
/// 消费者按「未知」处理不伪造默认值（§7.2 兼容原则）。
#[allow(clippy::too_many_arguments)]
pub fn write_serve_heartbeat_ext(
    jobs: &Path,
    workers: usize,
    exec_py: &Path,
    exec_mode: &str,
    instance: Option<&str>,
    role: Option<&str>,
    fingerprint: Option<&str>,
    iter_id: Option<&str>,
    progress: Option<&str>,
) -> Result<(), String> {
    let mut v = vec![
        ("pid".to_string(), Json::Num(std::process::id() as f64)),
        ("ts".to_string(), Json::Num(now_ms() as f64)),
        ("workers".to_string(), Json::Num(workers as f64)),
        (
            "exec_py".to_string(),
            Json::Str(exec_py.to_string_lossy().to_string()),
        ),
        ("exec_mode".to_string(), Json::Str(exec_mode.to_string())),
    ];
    let opt = |k: &str, x: Option<&str>| {
        x.map(|s| (k.to_string(), Json::Str(s.to_string())))
    };
    v.extend(opt("instance", instance));
    v.extend(opt("role", role));
    v.extend(opt("fingerprint", fingerprint));
    v.extend(opt("iter_id", iter_id));
    v.extend(opt("progress", progress));
    write_json(&jobs.join("_serve.json"), &Json::Obj(v)).map_err(|e| e.to_string())
}

/// 读 serve 心跳（不存在 → None）。
/// 生效条件：_serve.json 存在且合法 → Some(Json)；不存在/坏文件 → None
/// （消费者按 no_heartbeat_or_legacy 口径如实标注，不伪造默认值）。
pub fn read_serve_heartbeat(jobs: &Path) -> Option<Json> {
    read_json(&jobs.join("_serve.json")).ok()
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::json::parse;

    fn tmpdir(tag: &str) -> PathBuf {
        let d = std::env::temp_dir().join(format!(
            "hive_job_{tag}_{}",
            now_ms()
        ));
        let _ = fs::remove_dir_all(&d);
        fs::create_dir_all(&d).unwrap();
        d
    }

    /// 单测夹具：四槽建任务（与 CLI/MCP 走**同一条**写序单点；槽值固定，编号自增）。
    fn mkjob(jobs: &Path, spec: &Json, timeout_s: u64) -> String {
        init_job_with_slots(jobs, "单测端", "id契约", "记录单元", spec, timeout_s, None).unwrap()
    }

    #[test]
    fn init_and_claim_once() {
        let jobs = tmpdir("claim");
        let spec = parse(r#"{"model":"m","user_prompt":"x"}"#).unwrap();
        let id = mkjob(&jobs, &spec, 300);
        assert!(id.starts_with("h_单测端_id契约_记录单元_"), "四槽形态: {id}");
        let dir = job_dir(&jobs, &id);
        assert!(dir.join("spec.json").is_file());
        let st = read_status(&dir).unwrap();
        assert_eq!(st.get("state").unwrap().as_str().unwrap(), "pending");
        // 领取一次成功，第二次必须失败（原子性）
        assert!(claim(&dir));
        assert!(!claim(&dir));
        let _ = fs::remove_dir_all(&jobs);
    }

    #[test]
    fn status_patch_and_heartbeat() {
        let jobs = tmpdir("patch");
        let spec = parse(r#"{"model":"m","user_prompt":"x"}"#).unwrap();
        let id = mkjob(&jobs, &spec, 60);
        let dir = job_dir(&jobs, &id);
        patch_status(
            &dir,
            vec![
                ("state".to_string(), Json::Str("running".to_string())),
                ("model".to_string(), Json::Str("m".to_string())),
            ],
        )
        .unwrap();
        let st = read_status(&dir).unwrap();
        assert_eq!(st.get("state").unwrap().as_str().unwrap(), "running");
        assert_eq!(st.get("timeout_s").unwrap().as_f64().unwrap(), 60.0);
        heartbeat(&dir, "running", now_ms() - 1500).unwrap();
        let st = read_status(&dir).unwrap();
        let el = st.get("elapsed_s").unwrap().as_f64().unwrap();
        assert!(el >= 1.0 && el < 5.0, "elapsed={el}");
        let _ = fs::remove_dir_all(&jobs);
    }

    #[test]
    fn kill_flag_idempotent() {
        let jobs = tmpdir("kill");
        let spec = parse(r#"{"model":"m","user_prompt":"x"}"#).unwrap();
        let id = mkjob(&jobs, &spec, 60);
        let dir = job_dir(&jobs, &id);
        assert!(!kill_requested(&dir));
        request_kill(&dir).unwrap();
        request_kill(&dir).unwrap(); // 幂等
        assert!(kill_requested(&dir));
        let _ = fs::remove_dir_all(&jobs);
    }

    /// B4/B9 字符集闸（合法/非法两侧；含 2026-09-25 缺陷的穿越载体）。
    ///
    /// 合法侧：新契约四槽中文 id（契约示例与边界形态）+ 旧形态 `h<毫秒>_<hex>`
    /// （存量零迁移：旧 id 必须仍然合法）→ 必须**通过**。
    /// 非法侧：路径成分、首尾空白与尾点、控制字符（含 NUL）、零宽/双向控制、
    /// Windows 保留设备名（含带扩展名形态）、**区块白名单外**字符（含一切会归一化
    /// 改写的形态）→ 必须**拒绝**（它们曾可经 job_dir 逃出 jobs 池写 kill 文件、
    /// 读任意目录 result 全文）。
    #[test]
    fn valid_job_id_charset_gate() {
        for ok in [
            "h_zcode端_灵枢迭代_反思单元_0001", // 契约示例
            "h_端_任务_记录单元_9999",           // 编号上界形态
            "h_端_任务_维生系统_0001",           // 五单元第五项落 id
            // 编号形态 0：本实现**收**（字符集闸不判编号数值——旧形态 id 无该槽，
            // 按形态判编号会把存量 id 一并误杀；分配器自 0001 起，永不产出 0000）
            "h_端_任务_反思单元_0000",
            "h_123_456_输出单元_0007",
            "h1758000000000_1a2b", // 旧形态（13 位毫秒 + 4 位 hex）
            "h1_a",                // 旧判例短形
            "h",                   // 仅 h 前缀（旧判例保留）
            "h_a.b",               // `.` 非尾点、非单独 → 收（B4 拒收项反推）
        ] {
            assert!(valid_job_id(ok), "合法 id 被拒: {ok:?}");
        }
        for bad in [
            "", "..", "../victim", "h/../../x", "h/.", "h\\..", "h:x", "/etc", "x123",
            "h.%.txt", // 白名单外字符 `%`
            "h..", "h.", "h ", "h\t",
            "h\x01", "h\x7f", "h\x00NUL",           // 控制字符（含 NUL）
            "h\u{200B}", "h\u{202E}", "h\u{FEFF}",  // 零宽 / 双向控制
            "h\u{0301}", "h\u{41}\u{301}",          // 组合标记（NFD 形复合）
            // 区块白名单外（候选区块未收）：兼容分解/上下标/数字形式/全角/谚文 Jamo/
            // 兼容表意/连字——旧机制下靠 NFC_REWRITE_BLOCKS 拒，本批靠「不在表内」拒。
            "h\u{00AA}", "h\u{2070}", "h\u{2160}", "h\u{FF11}", "h\u{1100}",
            "h\u{FA10}", "h\u{FB01}",
            "h_CON_任务_记录单元_0001",              // 段落设备名
            "h_CON.txt_任务_记录单元_0001",          // 带扩展名形态
            "h_端_aux_记录单元_0001",                // 小写 aux（大小写不敏感）
            "h_端_任务_COM1_0001",                   // COM1 段
            "h_端-1_任务_记录单元_0001",             // `-` 不在白名单
        ] {
            assert!(!valid_job_id(bad), "非法 id 被收: {bad:?}");
        }
    }

    /// B5′（改造自旧的 NFC 闭集守卫）：契约点名的 11 个「有意不收」区块**不得**被白名单
    /// 收进来——旧机制下它们是 `nfc_rewritable` 闭集，本批该闭集退休，同一条拒绝面改由
    /// 「候选区块之外」承载（见 `hive/id_charset_blocks.txt` 的「有意不收」段）。
    /// 区块表被放宽 / 候选清单被增补即红。
    #[test]
    fn charset_blocks_exclude_contract_forms() {
        for (cp, tag) in [
            (0x1100u32, "Hangul Jamo"),
            (0x3130, "Hangul 兼容 Jamo"),
            (0xF900, "CJK 兼容表意"),
            (0xFE30, "CJK 兼容形式"),
            (0xFE50, "小写变体形式"),
            (0xFF00, "半角全角"),
            (0x2460, "带圈字母数字"),
            (0x3200, "带圈/括号 CJK 与单位"),
            (0x2100, "Letterlike"),
            (0x1D400, "数学字母数字"),
            (0x2F800, "CJK 兼容表意补充"),
        ] {
            let c = char::from_u32(cp).unwrap();
            assert!(!id_charset_member(c), "有意不收的区块代表点被判收 {cp:#06x}（{tag}）");
            assert!(
                !valid_job_id(&format!("h{c}")),
                "有意不收的区块代表点经 id 闸被收 {cp:#06x}（{tag}）"
            );
        }
        // 区间两端（防「只写了一半」的漂移）
        for (lo, hi) in [(0x1100u32, 0x11FFu32), (0x1D400, 0x1D7FF), (0x2F800, 0x2FA1F)] {
            for cp in [lo, hi] {
                assert!(!id_charset_member(char::from_u32(cp).unwrap()), "{cp:#06x}");
            }
        }
        // 不误伤：常规中文与 ASCII 字母数字必须判收
        for c in ['灵', '枢', '迭', '代', 'A', 'z', '0', '9'] {
            assert!(id_charset_member(c), "常规字符被误判为白名单外: {c:?}");
        }
    }

    /// c7：拒收项**逐条显式断言**——「白名单外所以默认被拒」不算数（防将来放宽某个区块时
    /// 把零宽/双向控制/控制字符/路径成分带进来）。每条都同时过 **id 闸**与**槽闸**：两处
    /// 判据同源（[`id_charset_member`]），拒绝面必须一致。
    #[test]
    fn charset_gate_rejects_contract_list_explicitly() {
        let mut suspects: Vec<char> = Vec::new();
        suspects.extend('\u{200B}'..='\u{200F}'); // 零宽（c7 逐码点）
        suspects.push('\u{2060}');
        suspects.push('\u{FEFF}');
        suspects.extend('\u{202A}'..='\u{202E}'); // 双向控制（c7 逐码点）
        suspects.extend('\u{2066}'..='\u{2069}');
        suspects.extend('\u{0000}'..='\u{001F}'); // C0 控制
        suspects.push('\u{007F}'); // DEL
        suspects.push('\u{0085}'); // C1 控制
        suspects.extend(['/', '\\', ':', '.']); // 路径成分与点
        suspects.extend(['\u{00A0}', '\u{3000}']); // 空白（首尾空白面）
        for c in suspects {
            let s = c.to_string();
            assert!(!id_charset_member(c), "拒收项落在白名单内: U+{:04X}", c as u32);
            assert!(!valid_job_id(&format!("h{c}")), "id 闸放过拒收项: U+{:04X}", c as u32);
            assert!(valid_slot("任务", &s).is_err(), "槽闸放过拒收项: U+{:04X}", c as u32);
        }
        // `_` 是**结构字符**（槽分隔符）：槽闸拒、id 闸收——两侧有意不同，显式钉住。
        assert!(!id_charset_member('_'));
        assert!(valid_job_id("h_"), "`_` 是 id 的结构字符，须收");
        assert!(valid_slot("任务", "_").is_err());
        // 单独的 `.` 与 `..`、尾点：字符串级形态（不在单字符面内）
        for bad in [".", "..", "h.", "h..", "h/.", "../victim", "h/../../x", "h\\..", "h:x"] {
            assert!(!valid_job_id(bad), "拒收形态被收: {bad:?}");
        }
        // 首尾空白（整串面）
        for bad in ["h ", "h\t", " h", "h\u{00A0}", "h\u{3000}"] {
            assert!(!valid_job_id(bad), "首尾空白被收: {bad:?}");
        }
        // Windows 保留设备名：**逐名**（大小写不敏感 / 带扩展名 / 按 `_` 分段任一段）
        for name in RESERVED_DEVICE_NAMES {
            let lower = name.to_ascii_lowercase();
            for form in [
                format!("h_{name}_任务_记录单元_0001"),
                format!("h_{name}.txt_任务_记录单元_0001"),
                format!("h_任务_{name}_记录单元_0001"),
                format!("h_任务_记录单元_{lower}"),
                format!("h_{lower}.txt_任务_记录单元_0001"),
            ] {
                assert!(!valid_job_id(&form), "保留设备名形态被收: {form:?}");
            }
            assert!(valid_slot("任务", name).is_err(), "槽闸放过保留设备名: {name}");
        }
    }

    /// c13：**字符类判据 ≡ 表**（全码点遍历 `0..=0x10FFFF`；纯内存区间查表，秒级）。
    /// 不再靠「喂真 hive.exe 逐码点」（那是 44 分钟路径）——接受集与表的区间并集逐码点
    /// 相同正是本批的结构性判据（两侧各自「≡ 表」合起来即两侧零分歧）。
    /// 范围说明：代理区 U+D800..DFFF 不是 `char`（`char::from_u32` 返回 None），
    /// 结构上不可达，故跳过而非断言。
    #[test]
    fn charset_predicate_equals_blocks_table() {
        let blocks = id_charset_blocks().expect("嵌入的区块表必须可解析且非空（fail-closed）");
        assert!(blocks.len() >= 30, "区块表区间数非退化，实得 {}", blocks.len());
        // 表已归并到最小（与生成器 `_is_minimal` 同判据：升序 ∧ 不相邻 ∧ 不相交）
        for w in blocks.windows(2) {
            let (a1, b1) = w[0];
            let (a2, b2) = w[1];
            assert!(a1 <= b1 && b1 + 1 < a2 && a2 <= b2, "未归并到最小: {a1:#X}-{b1:#X} / {a2:#X}-{b2:#X}");
        }
        let mut hit: u64 = 0;
        for cp in 0..=0x10FFFFu32 {
            let Some(c) = char::from_u32(cp) else { continue };
            let want = blocks.iter().any(|(lo, hi)| cp >= *lo && cp <= *hi);
            assert_eq!(id_charset_member(c), want, "接受集与表不符: U+{cp:04X}");
            if want {
                hit += 1;
            }
        }
        assert!(hit > 100_000, "接受集非退化（表覆盖 {hit} 个码点）");
    }

    /// c13：`valid_job_id` 与 `valid_slot` **用的字符判据** ≡ 表（全码点遍历）。
    /// `_` 与 `.` 是两个**结构字符**（不在表内、由结构分支处理，见 [`id_charset_member`]
    /// 的不适用条件）：`h_` 收、`h.` 拒（尾点）——故 id 侧的等价式把 `_` 单列，
    /// 槽侧则连 `_` 一起必须在表外即拒（两处口径一致且都有意为之）。
    #[test]
    fn job_id_and_slot_gates_use_table_membership() {
        assert!(id_charset_blocks().is_ok(), "区块表必须可解析");
        for cp in 0..=0x10FFFFu32 {
            let Some(c) = char::from_u32(cp) else { continue };
            let member = id_charset_member(c);
            assert_eq!(
                valid_job_id(&format!("h{c}")),
                member || c == '_',
                "id 闸字符判据 ≠ 表: U+{cp:04X}"
            );
            assert_eq!(
                valid_slot("任务", &c.to_string()).is_ok(),
                member,
                "槽闸字符判据 ≠ 表: U+{cp:04X}"
            );
        }
    }

    /// c2 fail-closed：表坏（缺/坏行/空）⇒ 判据**一律 false**，绝不退回属性判定兜底。
    #[test]
    fn charset_gate_fails_closed_on_bad_table() {
        // 解析器侧：空文本、坏行、越界、未归并到最小 → Err（绝不静默跳过）
        for bad in ["", "# 只有注释\n", "00\n", "ZZ-40\n", "0050-0040\n", "0030-0039\r\n-1\n"] {
            assert!(parse_id_charset_blocks(bad).is_err(), "坏表须 Err: {bad:?}");
        }
        assert!(parse_id_charset_blocks("0050-0040").is_err(), "逆序须 Err");
        assert!(parse_id_charset_blocks("0030-0039\n003A-0045").is_err(), "相邻须 Err（未归并）");
        assert!(parse_id_charset_blocks("0050-0060\n0030-0039").is_err(), "乱序须 Err");
        assert!(parse_id_charset_blocks("0030-0039\n0040-0045").is_ok(), "留空隙的表须 Ok");
        // 判据侧：Err / 空集 ⇒ false（fail-closed 的两个面都钉住）
        let err: Result<Vec<(u32, u32)>, String> = Err("表缺失".to_string());
        let empty: Result<Vec<(u32, u32)>, String> = Ok(Vec::new());
        for blocks in [&err, &empty] {
            for c in ['A', 'z', '0', '灵'] {
                assert!(!charset_member_in(blocks, c), "fail-closed 失守: {c:?}");
            }
        }
        // 表在位时同一入口仍放行（防「一律 false」被写成无条件拒绝）
        let ok = id_charset_blocks().expect("表可解析");
        let ok_owned: Result<Vec<(u32, u32)>, String> = Ok(ok.to_vec());
        assert!(charset_member_in(&ok_owned, '灵'));
    }

    /// c14：守卫自身的 UTF-8 自保证（照 `scripts/run_tests.py` 的最小形态）。
    /// Rust 侧没有 Python 那种 stdout 编解码失败模式（`println!` 直写字节），故最小形态 =
    /// 对**嵌入的表文本**做往返断言：无 BOM、中文表头逐字往返、CRLF 形态解析出同一张表。
    /// （编码非法 = `include_str!` 编译失败——比运行期断言更早，见 [`ID_CHARSET_BLOCKS_TEXT`]。）
    #[test]
    fn charset_blocks_text_is_utf8_without_bom() {
        let t = ID_CHARSET_BLOCKS_TEXT;
        assert!(!t.starts_with('\u{FEFF}'), "表文件带了 BOM");
        assert!(t.starts_with("# 蜂巢 job_id 字符白名单"), "表头中文未逐字往返");
        assert!(t.contains("唯一真源"), "表头缺「唯一真源」标记");
        let lf = parse_id_charset_blocks(t).expect("LF 表须可解析");
        let crlf = parse_id_charset_blocks(&t.replace('\n', "\r\n")).expect("CRLF 表须可解析");
        assert_eq!(lf, crlf, "CRLF 形态须解析出同一张表（autocrlf checkout 不改变接受集）");
    }

    /// B2 同源断言：五单元词表与真源 `md_cg/identity.py` 的 `POSITIONS` 逐项一致
    /// （英文键、落 id 的中文名、声明顺序三者都钉）——任一侧增删/改名/换序即红。
    /// 形态照 `md_cg/test_p21_tokens.py:218` 的「与 identity.POSITIONS 同源校验」。
    #[test]
    fn units_match_identity_positions() {
        let p = Path::new(env!("CARGO_MANIFEST_DIR"))
            .join("..")
            .join("md_cg")
            .join("identity.py");
        let text = fs::read_to_string(&p)
            .unwrap_or_else(|e| panic!("读真源 md_cg/identity.py 失败 {}: {e}", p.display()));
        let start = text.find("POSITIONS = {").expect("真源缺 `POSITIONS = {`");
        let block = &text[start..];
        let end = block.find("\n}").expect("真源 POSITIONS 块未闭合");
        let mut keys: Vec<String> = Vec::new();
        let mut units: Vec<String> = Vec::new();
        for line in block[..end].lines() {
            let t = line.trim();
            if t.starts_with('"') && t.contains("\": {") {
                keys.push(t.trim_start_matches('"').split('"').next().unwrap_or("").to_string());
            }
            if let Some(i) = t.find("\"unit\":") {
                let rest = t[i + "\"unit\":".len()..].trim_start().trim_start_matches('"');
                units.push(rest.split('"').next().unwrap_or("").to_string());
            }
        }
        let want_keys: Vec<String> = UNITS.iter().map(|(en, _)| en.to_string()).collect();
        let want_units: Vec<String> = UNITS.iter().map(|(_, zh)| zh.to_string()).collect();
        assert_eq!(keys, want_keys, "五单元英文键与顺序必须与 identity.POSITIONS 逐项一致");
        assert_eq!(units, want_units, "落 id 的中文名必须与 identity.POSITIONS 逐项一致");
    }

    /// B6 跨语言对照语料解码：`<verdict>\t<utf8-hex>\t<说明>`（两列以上备注可为空）。
    fn corpus_cases() -> Vec<(String, String, String)> {
        let raw = include_str!("../id_contract_corpus_v2.txt");
        let mut out = Vec::new();
        for (i, line) in raw.lines().enumerate() {
            let line = line.trim_end_matches('\r');
            if line.trim().is_empty() || line.starts_with('#') {
                continue;
            }
            let cols: Vec<&str> = line.splitn(3, '\t').collect();
            assert_eq!(cols.len(), 3, "语料第 {} 行须三列（verdict/hex/说明）: {line:?}", i + 1);
            let bytes = hex_decode(cols[1])
                .unwrap_or_else(|e| panic!("语料第 {} 行 hex 解码失败: {e}", i + 1));
            let s = String::from_utf8(bytes)
                .unwrap_or_else(|e| panic!("语料第 {} 行不是合法 UTF-8: {e}", i + 1));
            out.push((cols[0].to_string(), s, cols[2].to_string()));
        }
        out
    }

    fn hex_decode(s: &str) -> Result<Vec<u8>, String> {
        if s.len() % 2 != 0 {
            return Err("hex 长度为奇数".to_string());
        }
        let b = s.as_bytes();
        let mut out = Vec::with_capacity(b.len() / 2);
        for pair in b.chunks(2) {
            let hi = (pair[0] as char).to_digit(16).ok_or("非 hex 字符")?;
            let lo = (pair[1] as char).to_digit(16).ok_or("非 hex 字符")?;
            out.push((hi * 16 + lo) as u8);
        }
        Ok(out)
    }

    /// B6：跨语言对照语料**逐例同判**（Rust 侧判据 = [`valid_job_id`]）。
    /// 语料是两侧（rust 闸 / python 孪生闸）共用的唯一副本——任何一例判反即红。
    /// 纪律：**不许改语料迁就实现**（改语料 = 改判据面，须先改判据再同步语料并留痕）。
    #[test]
    fn id_contract_corpus_verdicts() {
        let cases = corpus_cases();
        assert!(cases.len() >= 18, "语料至少 18 例（B6），实得 {}", cases.len());
        let (mut accepts, mut rejects) = (0, 0);
        for (want, id, note) in &cases {
            let expect = match want.as_str() {
                "accept" => {
                    accepts += 1;
                    true
                }
                "reject" => {
                    rejects += 1;
                    false
                }
                other => panic!("语料 verdict 只能是 accept/reject，实得 {other:?}（{note}）"),
            };
            assert_eq!(valid_job_id(id), expect, "语料例不符: want={want} id={id:?}（{note}）");
        }
        assert!(accepts >= 5 && rejects >= 5, "语料两侧都须非退化: accept={accepts} reject={rejects}");
    }

    /// B6/B9：语料必须含契约点名的关键样本（合法四槽中文 id、存量旧形态、
    /// 争议字符、路径与不可见注入载体）——防语料被悄悄裁成「无争议的少数例」。
    #[test]
    fn id_contract_corpus_covers_contract_samples() {
        let cases = corpus_cases();
        let has = |id: &str, want: &str| {
            cases.iter().any(|(v, s, _)| v == want && s == id)
        };
        for id in [
            "h_zcode端_灵枢迭代_反思单元_0001",
            "h_端_任务_记录单元_9999",
            "h1758000000000_1a2b",
            "h1_a",
            "h",
        ] {
            assert!(has(id, "accept"), "合法样本缺失/判反: {id:?}");
        }
        for id in [
            "", "..", "../victim", "h/../../x", "h/.", "h\\..", "h:x", "/etc", "h..", "h ",
            "h\t", "h\u{200B}", "h\u{202E}", "h\u{0301}", "h\u{41}\u{301}", "h\u{FA10}",
            "h\u{FF11}", "h\u{2160}", "h\u{00AA}", "h\u{2070}", "h\u{1100}", "h\u{FB01}",
            "h_CON_任务_记录单元_0001", "h_CON.txt_任务_记录单元_0001",
        ] {
            assert!(has(id, "reject"), "拒收样本缺失/判反: {id:?}");
        }
    }

    #[test]
    fn list_jobs_sorted() {
        let jobs = tmpdir("list");
        let spec = parse(r#"{"model":"m","user_prompt":"x"}"#).unwrap();
        let a = mkjob(&jobs, &spec, 60);
        let b = mkjob(&jobs, &spec, 60);
        let all = list_jobs(&jobs);
        assert_eq!(all, vec![a, b]);
        let _ = fs::remove_dir_all(&jobs);
    }

    // ------------------------------------------------------ B1/B3 分配器（独占创建即分配）

    /// B3：连续分配不碰撞、编号 4 位定宽、**分配即创建目录**（独占创建即分配）。
    #[test]
    fn alloc_job_id_increments_without_collision() {
        let jobs = tmpdir("alloc_seq");
        let a = alloc_job_id(&jobs, "测试端", "编号", "反思单元").unwrap();
        let b = alloc_job_id(&jobs, "测试端", "编号", "反思单元").unwrap();
        let c = alloc_job_id(&jobs, "测试端", "编号", "反思单元").unwrap();
        assert_eq!(a, "h_测试端_编号_反思单元_0001");
        assert_eq!(b, "h_测试端_编号_反思单元_0002");
        assert_eq!(c, "h_测试端_编号_反思单元_0003");
        for id in [&a, &b, &c] {
            assert!(job_dir(&jobs, id).is_dir(), "分配必须已创建目录: {id}");
            let tail: String = id.chars().rev().take(SEQ_WIDTH).collect::<Vec<_>>()
                .into_iter().rev().collect();
            assert_eq!(tail.len(), SEQ_WIDTH);
            assert!(tail.chars().all(|c| c.is_ascii_digit()), "编号须 4 位十进制: {id}");
        }
        let _ = fs::remove_dir_all(&jobs);
    }

    /// B3：起点 = 同前缀已有编号最大值 + 1（提示；成败仍以 create_dir 为准），
    /// 不同前缀各自计数互不影响。
    #[test]
    fn alloc_job_id_starts_after_existing_max() {
        let jobs = tmpdir("alloc_max");
        for n in ["0001", "0002", "0007"] {
            fs::create_dir_all(job_dir(&jobs, &format!("h_端_任务_记录单元_{n}"))).unwrap();
        }
        fs::create_dir_all(job_dir(&jobs, "h_端_任务_输出单元_0003")).unwrap();
        assert_eq!(
            alloc_job_id(&jobs, "端", "任务", "记录单元").unwrap(),
            "h_端_任务_记录单元_0008"
        );
        assert_eq!(
            alloc_job_id(&jobs, "端", "任务", "输出单元").unwrap(),
            "h_端_任务_输出单元_0004"
        );
        let _ = fs::remove_dir_all(&jobs);
    }

    /// c1/c3：**搜索在号位间回绕**——池内只存 `…_9999` 时起点 = 10000（越过上限），
    /// 第一段 `10000..=9999` 为空、接回绕段 ⇒ 分到空闲的 `…_0001`（白扔 9998 个号位
    /// 的旧行为就此消解）。**编号值不回绕**：分出的 `0001` 是本前缀当时空闲的号位，
    /// 不是复用已发布 id——目录即分配凭证，与「用尽即报错」不冲突。
    #[test]
    fn alloc_job_id_wraps_over_slots_past_the_hint() {
        let jobs = tmpdir("alloc_wrap");
        fs::create_dir_all(job_dir(&jobs, "h_端_任务_记录单元_9999")).unwrap();
        assert_eq!(
            alloc_job_id(&jobs, "端", "任务", "记录单元").unwrap(),
            "h_端_任务_记录单元_0001"
        );
        // 回绕段的起点随分配前移：下一次起点 = 0002（**不重复试** 已占的 0001）
        assert_eq!(
            alloc_job_id(&jobs, "端", "任务", "记录单元").unwrap(),
            "h_端_任务_记录单元_0002"
        );
        // hint 落在回绕区间内（9999 + 0001 在场 → 起点 10000）也不重复试号：落到 0002
        let jobs2 = tmpdir("alloc_wrap_hole");
        for n in ["0001", "9999"] {
            fs::create_dir_all(job_dir(&jobs2, &format!("h_端_任务_记录单元_{n}"))).unwrap();
        }
        assert_eq!(
            alloc_job_id(&jobs2, "端", "任务", "记录单元").unwrap(),
            "h_端_任务_记录单元_0002"
        );
        let _ = fs::remove_dir_all(&jobs);
        let _ = fs::remove_dir_all(&jobs2);
    }

    /// c3：搜索序 = 「先 `hint..=MAX`，再回绕 `1..hint`」，两区间**互不重叠**、
    /// 并集恰为 `1..=MAX_UNIT_SEQ`（每个号位至多试一次）；`hint` 取端点/越界值都不
    /// panic、不死循环；越界起点也不产出 5 位号位（4 位定宽前提不被搜索序破坏）。
    #[test]
    fn seq_candidates_wraps_without_overlap() {
        use std::collections::BTreeSet;
        let all: BTreeSet<u32> = (1..=MAX_UNIT_SEQ).collect();
        for hint in [1u32, 2, 3, 5000, MAX_UNIT_SEQ - 1, MAX_UNIT_SEQ, MAX_UNIT_SEQ + 1] {
            let seq: Vec<u32> = seq_candidates(hint).collect();
            assert_eq!(seq.len() as u32, MAX_UNIT_SEQ, "hint={hint} 须恰覆盖全部号位");
            let set: BTreeSet<u32> = seq.iter().copied().collect();
            assert_eq!(set.len(), seq.len(), "hint={hint} 区间重叠 ⇒ 重复试号");
            assert_eq!(set, all, "hint={hint} 并集须是 1..=9999");
            if hint <= MAX_UNIT_SEQ {
                assert_eq!(seq[0], hint, "hint={hint} 须自起点提示起搜");
            } else {
                assert_eq!(seq[0], 1, "hint={hint} 越界时须直接从回绕段起搜");
            }
            // 末位 = 回绕段上界；`hint == 1` 时回绕段为空（`1..1`）⇒ 末位 = 首段上界。
            let want_last = if hint <= 1 { MAX_UNIT_SEQ } else { hint - 1 };
            assert_eq!(seq[seq.len() - 1], want_last, "hint={hint} 末位不符");
        }
        // 防御面：起点远越界（生产上 next_seq_hint ≤ 10000，见其文档）也只出 4 位号位
        let seq: Vec<u32> = seq_candidates(MAX_UNIT_SEQ + 7).collect();
        assert!(seq.iter().all(|n| all.contains(n)), "搜索序不得产出 5 位号位");
    }

    /// c2：**只有 9999 个号位全部被占用才报错，且文案如实**（真建满 9999 个号位——
    /// 本机实测建目录 0.84s、扫描 0.19s，代价可接受）。文案须含「全部被占用」，
    /// **不得**含会被读成「前面也满了」的旧措辞「已无可用编号」；不加宽为 5 位、
    /// 不把已占号位就地复用、保留可直读的「末次碰撞」。
    #[test]
    fn alloc_job_id_reports_exhaustion_only_when_all_slots_taken() {
        let jobs = tmpdir("alloc_full");
        for n in 1..=MAX_UNIT_SEQ {
            fs::create_dir_all(job_dir(&jobs, &format!("h_端_任务_记录单元_{n:04}")))
                .unwrap();
        }
        assert_eq!(MAX_UNIT_SEQ, 9999, "生产默认上限恒为 9999（B3 裁定，钉死）");
        let e = alloc_job_id(&jobs, "端", "任务", "记录单元").unwrap_err();
        assert!(e.contains("全部被占用"), "文案须如实说「全部被占用」: {e}");
        assert!(!e.contains("已无可用编号"), "旧措辞会被读成「前面也满了」: {e}");
        assert!(e.contains(&format!("{MAX_UNIT_SEQ} 个号位")), "文案须含号位数: {e}");
        assert!(e.contains("h_端_任务_记录单元_"), "错误须含前缀: {e}");
        assert!(e.contains("末次碰撞"), "须保留可直读的末次碰撞: {e}");
        assert!(!job_dir(&jobs, "h_端_任务_记录单元_10000").exists(), "不得加宽为 5 位");
        // 上界形态：9998 在场 → 9999 仍可分配；9999 也在场 → 起点越界 ⇒ 回绕找空号位
        let jobs2 = tmpdir("alloc_last");
        fs::create_dir_all(job_dir(&jobs2, "h_端_任务_记录单元_9998")).unwrap();
        assert_eq!(
            alloc_job_id(&jobs2, "端", "任务", "记录单元").unwrap(),
            "h_端_任务_记录单元_9999"
        );
        assert_eq!(
            alloc_job_id(&jobs2, "端", "任务", "记录单元").unwrap(),
            "h_端_任务_记录单元_0001"
        );
        let _ = fs::remove_dir_all(&jobs);
        let _ = fs::remove_dir_all(&jobs2);
    }

    /// B3：**AlreadyExists 才算碰撞**——同前缀下非 4 位十进制尾段的外来目录既不
    /// 参与起点计算、也不占号位（分配照常从空号位取）。
    #[test]
    fn alloc_job_id_ignores_foreign_dirs() {
        let jobs = tmpdir("alloc_foreign");
        fs::create_dir_all(job_dir(&jobs, "h_端_任务_记录单元_x")).unwrap();
        fs::create_dir_all(job_dir(&jobs, "h_端_任务_记录单元_00010")).unwrap(); // 5 位：不参与
        assert_eq!(
            alloc_job_id(&jobs, "端", "任务", "记录单元").unwrap(),
            "h_端_任务_记录单元_0001"
        );
        let _ = fs::remove_dir_all(&jobs);
    }

    /// B2：单元槽收英文键与中文名两种写法，**落 id 一律中文名**；非闭集值显式报错
    /// 且错误文本列全五单元（词表恰 5 项：副代理不是第六单元）。
    #[test]
    fn alloc_job_id_accepts_both_unit_spellings() {
        let jobs = tmpdir("alloc_unit");
        assert_eq!(
            alloc_job_id(&jobs, "测试端", "单元槽", "reflect").unwrap(),
            "h_测试端_单元槽_反思单元_0001"
        );
        assert_eq!(
            alloc_job_id(&jobs, "测试端", "单元槽", "反思单元").unwrap(),
            "h_测试端_单元槽_反思单元_0002"
        );
        let e = alloc_job_id(&jobs, "测试端", "单元槽", "第六单元").unwrap_err();
        assert!(e.contains("单元槽非法"), "{e}");
        for (en, zh) in UNITS {
            assert!(e.contains(*en) && e.contains(*zh), "错误须列全五单元: {e}");
        }
        assert_eq!(UNITS.len(), 5, "副代理不是第六单元——词表恰 5");
        assert_eq!(unit_canonical("sustain"), Some("维生系统"));
        assert_eq!(unit_canonical("维生系统"), Some("维生系统"));
        assert_eq!(unit_canonical("第六单元"), None);
        let _ = fs::remove_dir_all(&jobs);
    }

    /// B8 槽闸：空/首尾空白/含 `_`（槽分隔符）/含 `.`/路径成分/保留设备名/
    /// **区块白名单外**（含旧机制点名的会改写形态与零宽）→ 拒；中文与 ASCII 字母数字 → 收。
    #[test]
    fn valid_slot_rejects_unusable_values() {
        for ok in ["zcode端", "灵枢迭代", "记录单元", "a1", "端123"] {
            assert!(valid_slot("身份", ok).is_ok(), "合法槽值被拒: {ok:?}");
        }
        for bad in [
            "", " ", " 端", "端 ", "a_b", "a.b", "端/1", "端\\1", "h:x", "端:1", "CON",
            "con", "NUL.txt", "COM1", "lpt9", "aux", "单元\u{200B}", "\u{00AA}", "\u{FF11}",
            "端\u{0301}", "端\u{202E}", "端\u{3000}",
        ] {
            assert!(valid_slot("任务", bad).is_err(), "非法槽值被收: {bad:?}");
        }
    }

    /// B1/B7：inset 写序单点 —— `init_job_with_slots` 落 spec.json 先、status.json
    /// 后（status 出现 = 就绪信号），且 id 由分配器给出（四槽形态、编号 4 位）。
    #[test]
    fn init_job_with_slots_writes_spec_then_status() {
        let jobs = tmpdir("slots_init");
        let spec = parse(r#"{"model":"m","user_prompt":"x"}"#).unwrap();
        let id = init_job_with_slots(&jobs, "测试端", "写序", "验证单元", &spec, 30, None).unwrap();
        assert_eq!(id, "h_测试端_写序_验证单元_0001");
        let dir = job_dir(&jobs, &id);
        assert!(dir.join("spec.json").is_file() && dir.join("status.json").is_file());
        let st = read_status(&dir).unwrap();
        assert_eq!(st.get("state").unwrap().as_str().unwrap(), "pending");
        assert_eq!(st.get("job_id").unwrap().as_str().unwrap(), id);
        assert_eq!(st.get("timeout_s").unwrap().as_f64().unwrap(), 30.0);
        assert!(st.get("result_nonce").is_none(), "无锚密钥 = 旧格式（不带 nonce）");
        let _ = fs::remove_dir_all(&jobs);
    }


    /// 手搭一台任务目录（A3 专用）：直接落 status.json，绕开 `init_job_with_slots`
    /// 的分配器（id 手工指定），以便显式指定 created_ts（`None` = 不写该字段）。
    fn make_job(jobs: &Path, id: &str, created: Option<i64>) {
        let dir = job_dir(jobs, id);
        fs::create_dir_all(&dir).unwrap();
        let mut kv = vec![("job_id".to_string(), Json::Str(id.to_string()))];
        if let Some(ts) = created {
            kv.push(("created_ts".to_string(), Json::Num(ts as f64)));
        }
        write_json(&dir.join("status.json"), &Json::Obj(kv)).unwrap();
    }

    /// A3 保序证明（旧形态）：N 个旧形态 id（名序 == created_ts 序）→
    /// `list_jobs_by_created` 的顺序与 `list_jobs` **逐位相同**（存量零迁移的可证面）。
    /// 旧形态 = `h<13 位毫秒>_<4 位 hex>`（B4 存量样本），created_ts 与 id 内毫秒同值。
    #[test]
    fn list_jobs_by_created_preserves_legacy_order() {
        let jobs = tmpdir("order_legacy");
        let ids = [
            "h1700000000000_1a2b",
            "h1700000000001_1a2b",
            "h1700000000002_00ff",
            "h1700000000003_a000",
            "h1700000000004_ffff",
        ];
        for (i, id) in ids.iter().enumerate() {
            make_job(&jobs, id, Some(1_700_000_000_000 + i as i64));
        }
        let by_name = list_jobs(&jobs);
        let by_created = list_jobs_by_created(&jobs);
        assert_eq!(by_name.len(), ids.len());
        // 逐位相同（保序）：旧形态下两者不可区分
        assert_eq!(by_created, by_name, "旧形态必须保序（名序 == created_ts 序）");
        assert_eq!(by_created, ids.iter().map(|s| s.to_string()).collect::<Vec<_>>());
        let _ = fs::remove_dir_all(&jobs);
    }

    /// A3 按真值证明（与上例相反）：created_ts 与名序**相反** → 新单点按 created_ts 排，
    /// 与 `list_jobs` 的名序不同（证明它读的是真值而非名序）。
    #[test]
    fn list_jobs_by_created_sorts_by_truth_not_name() {
        let jobs = tmpdir("order_truth");
        // 名序：...0000 < ...0001 < ...0002；created_ts：300 / 200 / 100（完全相反）
        make_job(&jobs, "h1700000000000_1a2b", Some(300));
        make_job(&jobs, "h1700000000001_1a2b", Some(200));
        make_job(&jobs, "h1700000000002_1a2b", Some(100));
        let by_name = list_jobs(&jobs);
        let by_created = list_jobs_by_created(&jobs);
        assert_eq!(
            by_name,
            vec![
                "h1700000000000_1a2b".to_string(),
                "h1700000000001_1a2b".to_string(),
                "h1700000000002_1a2b".to_string(),
            ],
            "list_jobs 必须仍是名升序（A4：不得改成按 created_ts）"
        );
        assert_eq!(
            by_created,
            vec![
                "h1700000000002_1a2b".to_string(), // created_ts=100 最老
                "h1700000000001_1a2b".to_string(), // 200
                "h1700000000000_1a2b".to_string(), // 300
            ],
            "新单点必须按 created_ts 升序（与名序相反）"
        );
        assert_ne!(by_created, by_name, "两组样本必须能区分两种口径");
        let _ = fs::remove_dir_all(&jobs);
    }

    /// A3 退化输入：created_ts 缺失 / 非数 / 负值 / status.json 不存在 → 一律 `i64::MIN`
    /// （排最前），同哨兵值内按 id 字典序；读失败不 panic，重复调用结果确定。
    #[test]
    fn list_jobs_by_created_handles_missing_and_bad_ts() {
        let jobs = tmpdir("order_bad");
        make_job(&jobs, "h9000000000000_a", None); // 缺字段
        make_job(&jobs, "h9000000000000_b", Some(-5)); // 负值
        {
            // 非数（字符串形态 created_ts）
            let d = job_dir(&jobs, "h9000000000000_c");
            fs::create_dir_all(&d).unwrap();
            write_json(
                &d.join("status.json"),
                &Json::Obj(vec![("created_ts".to_string(), Json::Str("x".into()))]),
            )
            .unwrap();
        }
        // status.json 根本不存在（读失败，不得 panic）
        fs::create_dir_all(job_dir(&jobs, "h9000000000000_d")).unwrap();
        // 正常值：必须排在这些「无时间」任务之后
        make_job(&jobs, "h0000000000001_0", Some(10));
        // 坏 JSON（读失败，按缺失处理）
        {
            let d = job_dir(&jobs, "h9000000000000_e");
            fs::create_dir_all(&d).unwrap();
            fs::write(d.join("status.json"), b"{ not json").unwrap();
        }
        let got = list_jobs_by_created(&jobs);
        assert_eq!(
            got,
            vec![
                // 五个 i64::MIN（id 字典序次键），最后是唯一有真值的一台
                "h9000000000000_a".to_string(),
                "h9000000000000_b".to_string(),
                "h9000000000000_c".to_string(),
                "h9000000000000_d".to_string(),
                "h9000000000000_e".to_string(),
                "h0000000000001_0".to_string(),
            ],
        );
        // 确定性：与目录枚举次序无关，重复调用逐位相同
        for _ in 0..3 {
            assert_eq!(list_jobs_by_created(&jobs), got);
        }
        let _ = fs::remove_dir_all(&jobs);
    }

    /// P11 结果锚（批次53）：nonce=Some 时 status 落 `result_nonce`；None 时
    /// 与旧格式逐字段一致（向后兼容）；nonce 生成器批量唯一。
    #[test]
    fn init_job_with_slots_anchor_metadata() {
        let jobs = tmpdir("anchor");
        let spec = parse(r#"{"model":"m","user_prompt":"x"}"#).unwrap();
        // 旧格式：无 result_nonce 字段
        let legacy = mkjob(&jobs, &spec, 60);
        let st = read_status(&job_dir(&jobs, &legacy)).unwrap();
        assert!(st.get("result_nonce").is_none(), "旧格式任务不得带锚字段");
        // 锚格式：result_nonce 落盘且与提交值一致
        let n1 = new_result_nonce();
        let anchored =
            init_job_with_slots(&jobs, "单测端", "id契约", "记录单元", &spec, 60, Some(&n1))
                .unwrap();
        let st = read_status(&job_dir(&jobs, &anchored)).unwrap();
        assert_eq!(st.get("result_nonce").unwrap().as_str().unwrap(), n1);
        // nonce 唯一性：批量 1000 个互异、16 hex
        let mut seen = std::collections::HashSet::new();
        for _ in 0..1000 {
            let n = new_result_nonce();
            assert_eq!(n.len(), 16);
            assert!(seen.insert(n), "nonce 批量内必须互异");
        }
        let _ = fs::remove_dir_all(&jobs);
    }
}
