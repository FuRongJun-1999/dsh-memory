> **Languages:** [中文](../../ops/运维与排障.md) · English

# Operations and troubleshooting

> This page was split from the original `README.md` (source: the three sections "Write credentials", "Restart after an upgrade", and "FAQ" of the original README (L118–L195)).


## Restart the long-running MCP process after an upgrade (generation check)

### ♻️ Restart the long-running MCP process after an upgrade (generation check)

> **The one-line operational premise**: **when the code changes, restart the resident MCP process** — do not wait for an `ImportError` before you start troubleshooting.

**Root cause (confirmed)**: the LINGSHU brain (`md_cg`) is a **long-running stdio process** that only reads from disk at a module's **first import**; meanwhile `md_cg` contains **many deferred imports written inside functions** (a good share of them to avoid circular imports). The two combine: after an upgrade (switching packages / `git pull` / reinstall), **old-generation modules loaded before the upgrade** and **new-generation modules imported lazily after it** are mixed across generations in the same process. Measured symptom: a `cg` write returns `ImportError: cannot import name 'mint_auto_id' from 'md_cg.mdcg'` while **the on-disk state is perfectly fine** (a fresh interpreter imports the same module normally) — the error point is far from the root cause and is easily misjudged as "the code is broken".

**Self-check**: call `cg(op=info)` once against the **running** serve and read these five fields:

| Field | Meaning |
|---|---|
| `code_generation` | the first 12 characters of the code fingerprint **at the moment the process started** (= the generation the process actually holds) |
| `disk_generation` | the first 12 characters of the fingerprint of the code **on disk right now** |
| `stale_on_disk` | the two differ ⇒ the on-disk code has moved to a new generation (`true`) |
| `restart_required` | same truth value as `stale_on_disk` — time to restart |
| `hint` | a one-line handling hint in Chinese |

The fingerprint is a **content hash** (sha256 over the sorted (relative path, file bytes) of `md_cg/**/*.py`, skipping `__pycache__` and `test_*.py`), so a "rewrite with no change" (packing, unpacking, checksum write-back) does not falsely report a new generation. `stale_on_disk: true` means this process is stuck on the old generation.

**Handling**: **restart the resident MCP process** — on the DSH side, restart DSH (or refresh the Web UI so the plugin re-pulls the brain subprocess); other hosts reconnect to that MCP server. **Memory data is lossless**: not one byte of the on-disk source of truth moved; the restart only makes the process read one generation of code anew.

**There is also a startup gate**: before the service actually starts serving, every "deferred import inside a function" on disk is trial-resolved once (import the target module -> take the name); a missing name **refuses startup** and makes the process exit non-zero, with stderr naming the offending submodule and name. A "half-upgraded" package therefore exposes itself at startup rather than blowing up during some later write.

## Write credentials (make memory actually persist)

## 🔑 Write credentials (make memory actually persist)

```bash
# 签发（明文不进配置文件）
python -m md_cg.tokens issue --role designer --actor dsh-memory --clearance internal ^
  --ops-allow info,route,read,write,recent,goal,identity,whitebox,verify ^
  --layers-allow knowledge,contextual,structural,self,goals,unresolved,rejected
setx MDCG_TOKEN "mdcg1.xxxxx"     # 然后重启 DSH
```

```yaml
    env:
      MDCG_TOKEN: !!js process.env.MDCG_TOKEN
```

> `--role recorder` is the least-privilege version (automatic memory / transcription only; `whitebox`, `identity`, and `verify` are rejected).
> **The necessary and sufficient condition for persisting = the final verdict is ACCEPT**: `cg(op=write)` must pass through the three gates audit -> consistency -> gated (three questions, four states) in order; anything other than ACCEPT adds no persist point.
> **Do not treat `ok: true` as a successful write**: when nothing persists the response looks like `{"ok": true, "committed": false, "moved_to": "review_queue"}` — `ok` only means the request was accepted; **persisting is decided by `committed` alone**. `text` writes are reviewed under the **default policy** (the policy ships with the package: `<package>/data/policy.json`, overridable with `MDCG_POLICY_FILE`) — missing any of the six CCG elements or hitting the forbidden list yields `REJECT` (`moved_to: "rejected"`, recorded in negative memory); to persist immediately, use a verifiable type such as `content_kind: 'code'` (AST parse passes = `ACCEPT`). **When the policy itself is unavailable** (`MDCG_POLICY_FILE` points at a bad path, the packaged default cannot be read either, **or the policy content shape is invalid**), writes **fail-closed**: nothing persists and nothing enters the review queue (returns `moved_to: "policy_unavailable"` + an error code and hint), and the body is never stuffed into `hippocampus/inbox.jsonl`. **Invalid shape criterion**: if any value of the four list-typed keys `forbidden` / `required` / `required_kinds` / `required_labels` is not an array (written as a scalar such as `1` / `true`, or written as a string), it is invalid — values outside arrays have no single reading, so the gate does not guess and does not split a string into per-character rules (error code `policy_bad_shape`). The policy source is visible in the startup stderr, `python -m md_cg.mcp_server --show-config`, and the `write_policy` field of `cg(op=info)` (`env` / `package_default` / `unavailable`); the diagnostic surface **always exits 0**, and when the policy is unavailable `available: false` with `error` giving the error code and an actionable hint — if `--show-config` reports `policy_bad_shape`, the policy file has a wrong key type.
> **`text` writes must carry the six CCG elements** (function name / effective condition / sub-functions / execution / verification method / non-applicable conditions, one per line, each starting with `# 要素名：`): missing elements are rejected outright by the write gate (`moved_to: "rejected"`, `committed: false`, recorded in negative memory), and the response's `verdict.detail.missing` gives the **complete list of what is missing** — rewrite with the list filled in; you do not have to wait for a read-back to discover it. The requirement is defined by the rule base's `required` and `required_kinds` (default policy = `data/policy.json` in the package, shipped with the npm package; a policy pointed to by `MDCG_POLICY_FILE` overrides it), and **you can adjust it**: change the policy by editing that file (or keep your own copy and set `MDCG_POLICY_FILE`), not the code.

## FAQ

## ❓ FAQ

<details>
<summary><b>Why can't I install into the profile with a bare <code>npm install</code>?</b></summary>

Installation must use `dsh plugin --profile <name> add .`: the plugin declares 6 `peerDependencies` (cordis / dsh-llm / dsh-session / dsh-system-prompt / dsh-tools / schemastery), and `dsh plugin add` goes through pnpm, which resolves the peer versions the host provides correctly; a bare `npm install` installs the wrong dependency versions into the profile and breaks loading. `npm install` at the repository root is only for development builds (`npm run build`).
</details>

<details>
<summary><b>Installed the plugin / configured the credentials and nothing took effect?</b></summary>

DSH uses the Cordis bundle mechanism; after adding or updating a plugin you must **restart the DSH process** (or refresh the Web UI page) for it to reload; the same holds after configuring `MDCG_TOKEN` via `setx` — a restart is required for it to be visible (see [Write credentials](#-write-credentials-make-memory-actually-persist)).
</details>

<details>
<summary><b>How do I confirm the Agent really wrote the memory in?</b></summary>

Look at the <code>committed</code> field of the response, and <strong>do not treat <code>ok: true</code> as a successful write</strong> — <code>{"ok": true, "committed": false, "moved_to": "review_queue"}</code> means the request was accepted but <strong>not persisted</strong> (the content went into the review queue). The necessary and sufficient condition for persisting = all three gates finally return <code>ACCEPT</code>.
</details>

<details>
<summary><b>Why did my write not persist?</b></summary>

The three most common causes: ① no write credentials configured -> read-only <code>guest</code>, writes do not persist (for credentials see <a href="#-write-credentials-make-memory-actually-persist">Write credentials</a>); ② <code>content_kind</code> omitted or set to <code>text</code> -> reviewed under the **default policy** (<code>data/policy.json</code> in the package, overridable with <code>MDCG_POLICY_FILE</code>): missing any of the six CCG elements or hitting the forbidden list means <code>REJECT</code> (recorded in negative memory, not persisted) -> use a verifiable type such as <code>content_kind: 'code'</code> (AST parse passes = ACCEPT); ③ it did not pass any of the audit -> consistency -> gated gates (three questions, four states).
</details>

<details>
<summary><b>Do other hosts such as CodeBuddy / ZCode / Codex CLI / Claude Code work too?</b></summary>

Yes. The brain <code>md_cg/</code> is a standard stdio MCP server (<code>python -m md_cg.mcp_server</code>), so any host that supports MCP can mount it directly; the five integrations differ only in how discipline is injected, see <a href="../mdcg/multi-harness.md#multi-harness-integration-directories-per-endpoint">Multi-harness integration</a>.
</details>
