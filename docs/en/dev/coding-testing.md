> **Languages:** [中文](../../dev/编码与测试约定.md) · English

# Coding and testing conventions

> This page was split out of the original `README.md` (source: the four original README sections "Development", "Python test conventions", "Coding conventions", and "Linux verification" (L565-L637)).

## Development and build

## 🛠️ Development

```bash
npm install                          # NODE_ENV=production 时须加 --include=dev
npm run build    # TypeScript 编译
npm test         # 真实集成测试（spawn 本机灵枢，验证握手/往返/注册/卸载）
```

> `NODE_ENV=production` (or `--omit=dev`) omits devDependencies, so `tsc`/`tsx` are not present;
> in that case `prepare` **skips the build and says so on stdout** (no longer making `npm install` fail entirely because `tsc` is missing),
> so use `npm install --include=dev` when you need a build. Also: running under `engines.node >=22.19` prints
> an EBADENGINE warning (informational only, non-blocking).

Tests do not depend on all DSH components: they use a minimal Cordis host (SystemPrompt + ToolRegistry + plugin) to isolate unstable surfaces.

### Python test conventions (must use `python -m`)

Tests inside packages such as `md_cg/` generally use **package-relative imports**, so they must be run as modules from the **repository root**; calling `python md_cg/test_xxx.py` directly raises ImportError (measured: 59 of 61 direct runs hit it). The one-command entry point encodes that convention (on Linux and macOS, replace `python` below with `python3`, since distributions ship no `python` by default):

```bash
python -m md_cg.run_tests                    # 全量（md_cg + compiler + swarm，按存在性发现）
python -m md_cg.run_tests md_cg -k p44       # 按组 / 关键字过滤
python -m md_cg.run_tests --jobs 1           # 串行（默认并发 4）
python scripts/run_tests.py                  # 源码树入口（等价；需 scripts/ 在）
```

> **The entry point lives inside the package** (`md_cg/run_tests.py`): the npm shipped surface (`files`) does not include `scripts/`,
> so in an installed plugin the only full-suite entry point available is the one above; in the `src/` source tree,
> `scripts/run_tests.py` and `npm run gate` still work (release gates are source-tree tools).
> The package runner **redirects subprocess output to a file** (no pipes): restricted hosts (such as the DSH file
> sandbox) forbid CreatePipe, so versions using `capture_output` turn every test case into a
> PermissionError false failure.

Equivalent single-test form: `python -m md_cg.test_p44_md_whitebox` (cwd=repository root). Exit code 0/1 feeds directly into a pre-commit gate.

## Coding conventions (all UTF-8 · commands go through python)

### Coding conventions (all UTF-8 · commands go through python)

**All text in this repository is UTF-8 (no BOM)**: source code, configuration, documentation, data, test fixtures, and also **paths and file names** (including Hive task identifiers). Chinese may appear directly in paths: this is not a suggestion, it is a convention.

> **Explicit statement for AI agents and integrators**: this is UTF-8. Access everything in this repository through **python** (`python -X utf8 ...`, equivalent to `PYTHONUTF8=1`); **do not use the console/terminal as the access channel**. The Windows console interprets received bytes according to its **code page** and renders Chinese as mojibake (measured: `控制台试验` displays as `鎺у埗鍙拌瘯楠` in a code page 936 window). **That is a display-layer problem, not a data-layer problem**: not a single character is lost. We **do not do console compatibility**: all reads, writes, and decisions work on UTF-8 bytes, and correctness does not depend on anyone's code page setting.

- **Entry-point self-guarantee**: the Python entry point checks `sys.flags.utf8_mode` at the earliest point; if it is off, it sets `PYTHONUTF8=1` / `PYTHONIOENCODING=utf-8` and restarts itself; when a restart is impossible it fails fast (no silent degradation).
- **Explicit over default**: in new code, `open()` / `read_text()` always pass `encoding="utf-8"` explicitly and never rely on the locale default (the default on Chinese Windows is cp936, and a bare `open()` reads and writes with it).
- **NFC measurement basis = reject, do not normalize silently** (see [identifier contract v2](../../plans/全中文编码与蜂巢任务标识契约_v2.0.md) §4.4 / §4.8): paths and identifiers **must already be in NFC-stable form** to be accepted. The criterion is the **block whitelist** `hive/id_charset_blocks.txt` (single source of truth: Rust embeds it at compile time via `include_str!`, and MCP and `md_cg` read the same file, **so no runtime Unicode property table is consulted and a property-table version skew between the two sides is structurally impossible**). Forms outside the table are **explicitly rejected**: forms that normalization would rewrite (CJK compatibility ideographs / fullwidth / circled letters and digits / mathematical alphanumerics / combining marks, and so on), and **letters and digits from scripts outside the whitelisted blocks** (the block selection is ASCII / Latin / Greek / Cyrillic / kana / Hangul syllables / CJK and extensions / bopomofo; see contract §4.4 for the deliberately excluded ranges). No silent rewriting is done (a zero-dependency hand-written full NFC implementation on the `hive` side is not feasible; rejection is stricter than silent normalization).
- **Hive task identifiers (id contract v2)**: `h_<identity>_<task>_<unit>_<number>`, for example `h_zcode端_灵枢迭代_反思单元_0001`. Three of the four slots (identity / task / unit) are **required at submission** and must not be derived silently; the number is assigned exclusively by the Rust-side allocator (fixed width of 4 digits, explicit error on overflow, no widening and no wraparound); the unit slot takes the closed set of five Hive units (recording unit / reflection unit / verification unit / output unit / life-support system). The CLI uses `--identity/--task/--unit` (env fallbacks `HIVE_JOB_IDENTITY/HIVE_JOB_TASK/HIVE_JOB_UNIT`), or `hive alloc-id` to get an id only; MCP `hive_spawn` takes the same three parameters (required). The old form `h<13-digit milliseconds>_<4-digit hex>` **remains valid** (zero migration for existing data).
- **The platform surface** is covered by the encoding / locale guards of the container dual-stack gate (see the next section).

## Linux verification (Docker container dual stack)

### Linux verification (Docker container dual stack, a release gate since 0.5.0)

```bash
# 栈一：rust + python 全量（cargo test / python 18 套含全部守卫 / smoke 端到端）
docker run --rm -v "$(pwd):/work" -w /work -e CARGO_TARGET_DIR=/tmp/target \
  rust:bookworm bash scripts/linux_verify.sh full
# 栈二：node 生态（发布件 TS 编译 + node test）
docker run --rm -v "$(pwd):/work" -w /work node:22-bookworm bash -c \
  "npm install --include=dev && npm run build && node --import tsx --test test/*.test.ts"
```

> The executor interpreter is probed by a trial run in `hive/src/exec.rs` (`python3` first, `python` as fallback), so the two commands above can be **copied as-is** with no need to pass `HIVE_PYTHON`; set it explicitly only to choose a different interpreter (an explicit value overrides the probe). Under Git Bash/MSYS you must first `export MSYS_NO_PATHCONV=1`, otherwise `/work` is rewritten to `C:/Program Files/Git/work`.
> Platform-difference guards are covered by the script list (encoding / locale / session filtering / SIGTERM cleanup); suites that depend on gitignored local corpora (p44 and others) are not in the container list and are covered on machines that have the corpora through the SKIP surface of `run_tests.py`.
