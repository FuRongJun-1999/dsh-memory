> **Languages:** [中文](../../../ui/minimal/使用说明.md) · English

# LINGSHU minimal UI share package v1.0

This is the frontend add-on package for the original LINGSHU `@furongjun1999/dsh-memory`; it is not a standalone skill and does not include the LINGSHU brain itself. It targets the single-bridge entry point of LINGSHU 0.8.1 verified in this round; 0.9.x is installed only after the installer compatibility check passes (0.9.11 has not been tested across versions, so the installer checks before writing to disk).

## Community installation (Windows)

1. Install and enable the original LINGSHU plugin in your own DSH first. Without LINGSHU installed, the UI package alone cannot provide memory features.
2. Exit DSH completely, including the background tray process.
3. Extract this package and double-click `安装UI.cmd`. It searches automatically for the current user's LINGSHU plugin; when it finds multiple or none, enter the root directory of your LINGSHU plugin (the level containing package.json).
4. Restart DSH and click 'LINGSHU' on the left. If the sidebar does not appear, check that the plugin is enabled, that the install directory belongs to the profile in use, and that DSH has fully restarted.
5. If permissions are insufficient, check LINGSHU's own credential settings; the installer does not issue tokens or bypass permissions.

PowerShell method (you can specify a path; check first):

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\install.ps1 -PluginPath '你自己的灵枢插件目录' -CheckOnly
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\install.ps1 -PluginPath '你自己的灵枢插件目录'
```

Bypass applies only to this script process and does not change the system execution policy. Do not run install scripts from unknown sources.

## Why does it read each computer's own memory?

This package adds UI code only; the server side reuses **the same configured MdcgClient brain bridge** on the recipient's machine and contains no author memory or author paths. All page calls use the current DSH same-origin API; they do not connect to the author's computer and do not set up a remote memory server.

The original LINGSHU default memory root is `.dsh-memory/data/mdcg` under the current user's DSH_HOME; the common Windows default expands to `%USERPROFILE%\.dsh\.dsh-memory\data\mdcg`. If the recipient already has a custom MDCG_ROOT, paths.json, or mdcg.root configuration, it is kept as-is and not forced back to the default.

Therefore: person A sees A's memory and person B sees B's memory; a new user's empty store stays empty and never shows the sharer's memory. If a user deliberately configures the root on a shared or synced drive, that sharing behavior is determined by their own configuration; this package does not guarantee automatic per-user or per-profile separation on the same computer.

The installer does not modify the cognitive map root, identity subject, automatic memory switch, MDCG_TOKEN, DSH profile, or credentials. The original LINGSHU records and reads its own memory after startup; that is original plugin behavior, not something this share package imports.

## UI features

Overview, memory retrieval and writing, target tasks, self-model, spatiotemporal relations, review and maintenance, plus the real MCP tool catalog and JSON call entry point. Common features use forms; every capability not listed separately goes to the 'toolbench'. The number of tools depends on the LINGSHU version the recipient installed and is not hard-coded to 33.

Original plugin permissions and guardrails are preserved. The pages and API depend on DSH host authentication that supports connection.admit; incompatible older hosts report a clear error and do not fall back to open access. Modification operations require confirmation; a memory write may be accepted, merged, discarded, or sent to review, and the actual receipt is authoritative.

## What the package includes / excludes

Includes: frontend pages, sidebar client bundle, same-origin API code, build scripts, installer, integrity manifest, and MIT license.

Excludes: the author's memory graph, data directory, keys, token, .credentials.yaml, paths.json, personal profile, session, chat logs, or a copy of the entire original LINGSHU plugin.

**Share only this ZIP; do not compress your own .dsh, .mdcg, the entire LINGSHU runtime directory, or the backup the installer generates on your machine.** The local backup may contain personal changes in your original plugin source and is meant only for rollback.

## Uninstall and upgrade

Exit DSH completely, then double-click `卸载UI.cmd`, or run `install.ps1 -Uninstall` against the same plugin directory. Only code backed up by this installer is restored; memory is never deleted.

If the source or manifest changed after installation, uninstall stops to avoid overwriting your new changes or an upstream upgrade. Do not force a bypass. An original LINGSHU upgrade may replace UI files: uninstall the UI before upgrading, check whether this package is still compatible after upgrading, and then reinstall. If it is already installed, running it again does not overwrite.

## Verification scope

Original implementation: 8 API tests pass, page interaction against a real read-only cognitive map and the 390px responsive test pass, and the module map and protected routes of the existing DSH client are mounted. The final click flow in a logged-in desktop GUI is confirmed by the user.

The share installer is additionally verified on a temporary plugin copy: compatibility check, install, idempotence, rejection of incompatible versions, overwrite protection after post-install changes, per-file restore on uninstall, and unchanged memory/paths/profile sentinels. Installation on recipients' different DSH versions has not been tested across machines.

## Blurb you can post directly

> This is the minimal frontend enhancement package for LINGSHU and carries no one's memory. Install the original LINGSHU first, then exit DSH completely, extract the package and run `安装UI.cmd`; after restarting, click LINGSHU in the sidebar. The UI reads the LINGSHU memory store already on your own computer; existing custom paths and permissions are kept, and you do not need to import my configuration. For Windows; currently compatible with LINGSHU 0.8.1.
