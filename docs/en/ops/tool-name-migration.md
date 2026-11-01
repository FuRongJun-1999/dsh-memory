> **Languages:** [中文](../../ops/工具名迁移_0.9.9.md) · English

# Tool name migration (as of 0.9.9)

## What changed

| Version | Tool names |
|---|---|
| ≤ 0.9.8 | lingshu_cg / lingshu_stg / lingshu_mdcg_reflect |
| ≥ 0.9.9 | cg / stg / mdcg_reflect |

Reason: previously the prefix was composed from serverName, which produced identification errors where "the same MCP service showed different tool names on different hosts".
serverName is still used for internal provider/log identification.

## Impact (issue #634)

Long-running sessions, agent orchestration, or scripts that are **running** during the upgrade hit `unknown tool` immediately after the upgrade if they hard-code the old names;
newly opened sessions are unaffected. The host logs and the plugin logs both show successful registration, and the error appears only in the caller — that is the hardest part to troubleshoot.

## Migration

1. Caller side: drop the `lingshu_` prefix (lingshu_cg -> cg);
2. Configuration side: the tools selection table in the profile matches the raw MCP-side names, so writing either lingshu_cg or cg does not change the selection result;
3. Compatibility: from 0.9.12 the lingshu_* aliases are also registered by default (their description carries the `已弃用别名` deprecated-alias label and points to the same implementation);
   set toolAliases: false to keep only the bare names.

## Why aliases are not kept long term

Two sets of names would put "one tool with two identities" into the model context, and would make audit logs contain two spellings.
Aliases are only an upgrade buffer and are planned for removal after one minor cycle; the README and this page will note it then.
