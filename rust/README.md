# mdcg-eval · 灵枢 Rust 检索库

一个 crate，三种形态（零第三方依赖，`std` only）：

| 形态 | 入口 | 用途 |
|---|---|---|
| **库** `mdcg_eval` | `src/lib.rs` → `engine::SearchEngine` | 嵌入 Rust 宿主：大批量记忆检索、多线程并发 |
| **进程实例** `--serve` | `src/serve.rs` | 每智能体一进程，stdin/stdout 逐行 JSON——语言无关的多智能体并发 |
| **评测器** `mdcg-eval` | `src/main.rs` | 公开数据集评测（LoCoMo 等），与 Python 口径逐位对齐 |

读侧 only：写入（写入闸门/凭据/冲突检测）仍由 Python MCP 承担——职责分离，避免双写实现漂移。

## 1. 库形态（Rust 宿主内嵌）

```toml
[dependencies]
mdcg-eval = { path = "../dsh-memory/rust" }
```

```rust
use mdcg_eval::{EngineConfig, SearchEngine};

let engine = SearchEngine::open("path/to/memory-root", &EngineConfig::default())?;
println!("docs={} 候选={}", engine.doc_count(), engine.candidate_count());

let hits = engine.search("评测复现脚本", 5);
for h in hits {
    println!("{}  {:.6}  {}  {}", h.score, h.score, h.layer, h.path);
}
```

`EngineConfig` 字段（全部可选，缺省与 Python `search_rrf` 默认一致）：
`paths`（参与融合的路，缺省四路）、`weights`（路权重覆盖）、`fusion_max`（每路先取前 50 再 RRF）、
`jaccard`（相似度口径，缺省 true）、`graph_seeds_sorted`、`order`（候选序）、`threads`（载入并行度）。

**并发模型**：`SearchEngine` 持全 owned 数据，`search(&self)` 纯读 → 自动 `Send + Sync`。
大批量检索 = 宿主持一个引擎 + 线程池并发调 `search`（索引只载入一次，零拷贝共享）。

## 2. serve 形态（多智能体并发 · 语言无关）

```bash
cargo build --release
./target/release/mdcg-eval --serve --root /path/to/memory-root
```

进程存活 = 检索实例（模式参照 protocol-compiler 蜂群实例基座）。
多智能体并发 = 协调器 spawn N 个实例——索引只读共享，OS 页缓存复用，单实例崩溃不扩散。
Python 宿主示例：

```python
import json, subprocess
p = subprocess.Popen(["mdcg-eval", "--serve", "--root", root],
                     stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                     text=True, encoding="utf-8")
def search(query, k=5):
    p.stdin.write(json.dumps({"op": "search", "query": query, "k": k}) + "\n")
    p.stdin.flush()
    return json.loads(p.stdout.readline())
```

协议（一行一请求，一行一响应；`quit` 或 EOF 退出）：

| 请求 | 响应 |
|---|---|
| `{"op":"ping"}` | `{"ok":true,"pong":true}` |
| `{"op":"info"}` | `{"ok":true,"root":...,"docs":N,"candidates":N,"paths":[...]}` |
| `{"op":"search","query":"...","k":5}` | `{"ok":true,"count":N,"took_ms":T,"hits":[{"id","path","layer","score"}...]}` |
| 非法请求 | `{"ok":false,"error":"..."}` |

## 3. 评测器形态

```bash
cargo run --release -- --dataset lc          # LoCoMo T-REC 三组 + 负例组
cargo run --release -- --n 2                 # 2 题快速冒烟
cargo run --release -- --help                # 全参数
```

口径说明（paths/weights/fusion/jaccard/order/graph-seeds）见 `--help` 与 `docs/` 评测报告；
结果落 `data/external/eval_results/`。

## 4. 口径承诺

* 检索编排与评测 CLI `main.rs::search` 逐行一致；文本/存储层与 Python `md_cg`
  逐函数对齐（`text.rs` / `store.rs` 头注释标注了对应 Python 源位置）。
* 任何口径改动必须**评测 CLI 与库两边同步**，否则评测分数与线上检索漂移。
* 零第三方依赖（D-005）：评测机离线可构建。

## 5. 构建与测试

```bash
cargo test      # 8 项：文本层 4 + 引擎 2（含多线程并发安全）+ serve 协议 2
cargo build --release
```
