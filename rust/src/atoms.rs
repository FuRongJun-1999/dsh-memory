//! 批次 15：query 统一归一层——与 `md_cg/semantic/unify.py` 同口径。
//!
//! 使用者口径定案（2026-09-23）：**统一翻译为中文 → 归一化到标准中文集 →
//! 检索**。任何语言 query 先归一为标准原子序列（空格 join）再进检索各路。
//!
//! 词表真源单侧化：en→zh 映射与 segment 键集由 Python 侧导出
//! （`md_cg/semantic/export_en_zh_map.py` → `en_zh_map.json`，28478 词 +
//! 204 标准原子），本模块**只查表不维护词典**——杜绝双词表版本漂移。
//!
//! 对齐细节：
//!   - en 形态归一复用 `text::normalize_en`（小写+停用词+strip_tense_en，
//!     已有 golden 对齐测试）——查表键 = strip 后原形（tests→test）；
//!   - segment = 贪心最长匹配（键长降序，未命中单字符保留），对齐
//!     `zh_en_atoms.segment`；
//!   - 无字母 query 原样返回（纯中文经 bigrams 去空白后与原文等价）；
//!   - 未登录词原样保留（unknown_keep，词表边界非错误）。
//!
//! 载入：env `MDCG_EN_ZH_MAP` 指向 en_zh_map.json（缺省探测仓库相对路径
//! `md_cg/semantic/en_zh_map.json`）；两处都没有 → None（归一层静默不
//! 生效，与 Python 失败降级同风格）。开关 `MDCG_UNIFY_QUERY=0` 显式关。

use crate::json::Json;
use crate::text::normalize_en;
use std::collections::HashMap;
use std::path::Path;

/// 标准原子词表 + en→zh 映射（进程内共享，`Clone` 廉价——Arc 语义由
/// `Engine.atoms: Option<Atoms>` 单点持有即可，引擎本身不可变共享）。
#[derive(Debug, Clone)]
pub struct Atoms {
    /// segment 贪心匹配键（长度降序；多字键优先防前缀吞并）。
    zh_sorted: Vec<String>,
    /// en 小写词（strip 后原形）→ 中文原子串。
    en2zh: HashMap<String, String>,
}

impl Atoms {
    /// 从 en_zh_map.json 载入（Python 导出器产出）。
    pub fn load(path: &Path) -> Result<Self, String> {
        let raw = std::fs::read_to_string(path)
            .map_err(|e| format!("读 {} 失败: {}", path.display(), e))?;
        let j = crate::json::parse(&raw)?;
        let zh_sorted = {
            let mut keys: Vec<String> = j
                .get("zh_keys")
                .and_then(Json::as_arr)
                .map(|a| {
                    a.iter()
                        .filter_map(Json::as_str)
                        .map(str::to_string)
                        .collect()
                })
                .unwrap_or_default();
            keys.sort_by(|a, b| b.chars().count().cmp(&a.chars().count()));
            keys
        };
        let en2zh = j
            .get("map")
            .and_then(Json::as_obj)
            .map(|pairs| {
                pairs
                    .iter()
                    .filter_map(|(k, v)| v.as_str().map(|s| (k.clone(), s.to_string())))
                    .collect::<HashMap<_, _>>()
            })
            .unwrap_or_default();
        if zh_sorted.is_empty() || en2zh.is_empty() {
            return Err(format!("{} 缺 zh_keys/map 段", path.display()));
        }
        Ok(Self { zh_sorted, en2zh })
    }

    /// env/缺省路径探测（`None` = 归一层不生效）。
    pub fn from_env() -> Option<Self> {
        if std::env::var("MDCG_UNIFY_QUERY").map(|v| v == "0").unwrap_or(false) {
            return None; // 显式关
        }
        let p = std::env::var("MDCG_EN_ZH_MAP").ok().map(PathBuf::from).or_else(|| {
            // 缺省：CARGO_MANIFEST_DIR 的上级仓库相对路径（评测器与仓库同仓场景）
            #[cfg(not(feature = "no-probe"))]
            {
                let p = Path::new(env!("CARGO_MANIFEST_DIR"))
                    .join("../md_cg/semantic/en_zh_map.json");
                p.is_file().then_some(p)
            }
            #[cfg(feature = "no-probe")]
            None
        })?;
        match Self::load(&p) {
            Ok(a) => Some(a),
            Err(e) => {
                eprintln!("[mcdg-eval] 统一归一层载入失败，退化为无归一口径: {e}");
                None
            }
        }
    }

    /// 贪心最长匹配（对齐 `zh_en_atoms.segment`）：命中键消费，未命中单
    /// 字符保留；返回空格 join 的原子序列。
    pub fn segment(&self, text: &str) -> String {
        let chars: Vec<char> = text.chars().collect();
        let mut out: Vec<String> = Vec::new();
        let mut pos = 0usize;
        while pos < chars.len() {
            let mut matched = false;
            for key in &self.zh_sorted {
                let kc: Vec<char> = key.chars().collect();
                if kc.is_empty() || pos + kc.len() > chars.len() {
                    continue;
                }
                if chars[pos..pos + kc.len()] == kc[..] {
                    out.push(key.clone());
                    pos += kc.len();
                    matched = true;
                    break;
                }
            }
            if !matched {
                out.push(chars[pos].to_string());
                pos += 1;
            }
        }
        out.join(" ")
    }

    /// 统一归一（对齐 `unify_query`）：无字母原样；否则 en 归一→查表→
    /// 中文段 segment。输出空格 join 的标准原子/保留词序列。
    pub fn unify(&self, query: &str) -> String {
        if !query.chars().any(|c| c.is_ascii_alphabetic()) {
            return query.to_string();
        }
        let base = normalize_en(query); // 小写+停用词+strip_tense+中文保留
        let mut out: Vec<String> = Vec::new();
        for word in base.split_whitespace() {
            // 单字母词（I）经 normalize_en 原样保留大写——查表一律 lower
            // （en_zh_map 键全小写；对齐 Python 链 i→我）
            if let Some(zh) = self.en2zh.get(&word.to_lowercase()) {
                let seg = self.segment(zh);
                if !seg.is_empty() {
                    out.push(seg);
                    continue;
                }
            }
            // 未登录词原样（unknown_keep）；中文段（normalize_en 已保留）
            // 含非 ASCII → 走 segment 归一到标准原子
            if word.chars().any(|c| !c.is_ascii()) {
                let seg = self.segment(word);
                if !seg.is_empty() {
                    out.push(seg);
                    continue;
                }
            }
            out.push(word.to_string());
        }
        let joined = out.join(" ");
        if joined.trim().is_empty() {
            query.trim().to_string()
        } else {
            joined
        }
    }
}

use std::path::PathBuf;

#[cfg(test)]
mod tests {
    use super::*;

    fn atoms() -> Atoms {
        let p = Path::new(env!("CARGO_MANIFEST_DIR")).join("../md_cg/semantic/en_zh_map.json");
        Atoms::load(&p).expect("en_zh_map.json 可载入（仓库内相对路径）")
    }

    #[test]
    fn unify_en_to_zh_atoms() {
        let a = atoms();
        // 与 Python unify_query 冒烟同例：跨语归一生效（「牛肉」为
        // ZH_EN 整键，segment 整词消费——两侧逐位同形）
        assert_eq!(a.unify("I eat beef yesterday"), "我 吃 牛肉 昨天");
        assert_eq!(a.unify("wrote"), "写");
        assert_eq!(a.unify("compiler tests"), "编 辑 家 测 试");
    }

    #[test]
    fn unify_pure_zh_untouched() {
        let a = atoms();
        assert_eq!(a.unify("蜂群调度 依赖门禁"), "蜂群调度 依赖门禁");
    }

    #[test]
    fn segment_greedy_longest() {
        let a = atoms();
        // 「牛肉」若为单键则整词消费；否则拆「牛 肉」——与 Python segment 同序
        let seg = a.segment("牛肉面");
        assert!(seg == "牛肉 面" || seg == "牛 肉 面", "贪心口径: {seg}");
    }
}
