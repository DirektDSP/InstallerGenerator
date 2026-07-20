# MyDirekt — Desktop App Roadmap

> This document is the north star for MyDirekt, the cross-platform desktop
> **download + install manager** (Ninite-style multi-select) that consumes
> DirektDSP's `catalog.json`, with room for Moonbase-backed bulk licensing later.
>
> The **contract** it depends on (`catalog.json` + schema) is owned by the public
> InstallerGenerator repo; a copy of this roadmap lives there too.

## Current status (as of last work session)

Phases 1–3 are **built**. The full pipeline — select → download (parallel) →
verify SHA256 → install (serial) — is implemented for all three OSes, with
per-plugin progress in the UI. 15 Rust unit tests pass; `cargo check` and the
frontend build are clean.

| Phase | State | Notes |
|---|---|---|
| 1 — Contract (`install_hints`) | ✅ done, in InstallerGenerator `main` | commit `822c269` |
| 2 — App skeleton + picker UI | ✅ done | Tauri v2 + Vue 3 + TS + bun |
| 3a — Parallel download + verify | ✅ done | reqwest/rustls + sha2, streaming verify |
| 3b — Elevated serial install | ✅ code done, **needs real-OS execution testing** | Linux/macOS/Windows |
| 4 — Moonbase bulk auth | ⬜ not started | needs Moonbase SDK/API details |
| 5 — Web "Get the app" hero | ⬜ not started | in InstallerGenerator `gen_site.py` |

**Blocked (not code):**
- **CI matrix** (`.github/workflows/build.yml`) — blocked on **DirektDSP org
  GitHub Actions billing** (jobs won't start). Clear billing, then
  `gh workflow run build.yml` to produce Win/mac/Linux bundles.
- **Real-OS execution tests** — Linux + macOS on owner's machines; Windows via
  friends (needs a CI build first). Only the pure builders/parsers are unit-tested
  so far; the actual elevated install exec on mac/Windows is unrun.

**Resume here (suggested next steps):**
1. Clear org Actions billing → run CI → hand a Windows build to testers.
2. Test 3b Linux/macOS locally; fix anything flagged.
3. Phase 5 web hero (fully doable without the app running).
4. Phase 4 Moonbase — gather SDK/API shape first (Vue SDK, server-authoritative).

**Toolchain (owner's WSL box):** rust 1.97.1, bun 1.3.14, webkit2gtk 2.52.5.
Run the app: `bun run tauri dev` (kill any stale vite on :1420 first).

## Why a desktop app (and not a web "install all" button)

The original idea was a Ninite-style unified installer downloadable from the
GitHub Pages site. That runs into a hard wall: **NSIS is Windows-only.** A single
checkbox-driven GUI installer that works on Windows, macOS, and Linux does not
exist in the current toolchain, and building three separate GUI stubs is
effectively building a desktop app anyway.

So the unified installer *is* the desktop app. One Tauri codebase gives the
cross-platform checkbox multi-select + download + install experience, and the
existing static site keeps offering per-plugin manual downloads for users who
want them.

## Repo layout

| Repo | Visibility | Owns |
|---|---|---|
| **InstallerGenerator** (this repo) | public | Build+installer factory, `plugins/*.toml`, templates, CI, and the **contract**: `catalog.json` + `schema/catalog.schema.json` + the static download site |
| **Desktop app** (separate) | private | The Tauri app. Reads the published `catalog.json` at runtime over its public URL |

Why separate + private:
- **Separation** — keeps the Python/CI build-factory decoupled from the Rust/Tauri
  app; independent release cycles, no mixed toolchains in one tree.
- **Private is early-dev comfort, not a security control.** A desktop app ships a
  binary users can decompile, so repo visibility protects nothing an attacker
  couldn't get from the shipped `.exe`. The real protection is the licensing
  architecture below. Private simply avoids exposing half-built work; it can flip
  public later with no design change.

## Licensing architecture (server-authoritative)

Moonbase licensing (Phase 4) is designed **server-authoritative** from day one:
- Moonbase validates entitlement **server-side**; the client holds only a user
  auth token, never a shared secret or signing key.
- **No secrets in the app repo or the shipped binary.** (Mirrors this repo's
  existing pattern — per-plugin `*_CONFIG_B64` are CI secrets, never committed.)
- Consequence: the app source leaks nothing useful even when public, and
  licensing is never gated at install time — plugins already self-license at
  runtime. Bulk auth is a convenience layer, not a gate.

## The contract: `catalog.json`

`catalog.json` (see `schema/catalog.schema.json`) is the machine-readable index
the app reads. Each `plugins[]` entry carries everything the orchestrate-native
engine needs:

- `installers.{windows,macos,linux}` → `{ filename, url, sha256, size }`
- `install_paths` (per-OS, per-format) for verify/uninstall
- `name`, `slug`, `version`, `formats`

Plus a top-level `install_hints` block (added in Phase 1) describing how to run
each OS's native installer unattended. **This contract is complete for
orchestrate-native install** — the app needs no further changes here to start.

## Decisions locked

| Decision | Choice | Rationale |
|---|---|---|
| Sequencing | Contract-first, then desktop app | `catalog.json` is the shared data model both the site and the app read; stabilize it before building consumers |
| Primary deliverable | Cross-platform desktop app | NSIS can't go cross-platform; one app replaces three GUI stubs |
| Repo | Separate, private | Decouple toolchains/release cycles; privacy is dev comfort, security comes from architecture |
| Stack | **Tauri** (Rust backend + webview frontend) | Tiny binary, cross-platform, reuse web frontend, Rust handles filesystem + elevation |
| Install engine | **Orchestrate native installers** | App downloads the existing per-plugin `.exe`/`.pkg`/`.zip` and runs them silently; reuses all existing installer logic, least new code |
| Licensing | **Server-authoritative**, not install-gated | No client secrets; plugins self-license at runtime; bulk auth is a convenience |
| Web page | Keep static site | Add an "Get the app" hero; keep per-plugin manual downloads |

## Silent-install support (verified feasible)

Emitted into `catalog.json` as `install_hints` (Phase 1):

| OS | Installer | Silent invocation | Elevation | Notes |
|---|---|---|---|---|
| Windows | NSIS `.exe` | `installer.exe /S` | admin | MUI default. Standalone section is `/o` (unchecked) so it's skipped silent; VST3/CLAP/presets/manual install. UAC once. |
| macOS | `.pkg` | `installer -pkg X.pkg -target /` | root | Inherently non-interactive; app requests admin. |
| Linux | `.zip` | app extracts + copies to plugin dirs | none | No command; handled natively by the app. |

## Phases

### Phase 1 — Contract (DONE, in this repo)
- `schema/catalog.schema.json`: added optional top-level `install_hints` block +
  `install_hint` definition. Optional, so existing catalogs still validate.
- `tools/build_catalog.py`: emits `install_hints` (per-OS, derived from installer
  type), only for OSes with a published installer; `catalog_version` 1 → 2.
- Verified: `tools/selftest.py` passes; hints emit + validate.

### Phase 2 — Desktop app skeleton (Tauri) ✅ DONE
- Tauri v2 + Vue 3 + TypeScript + Vite, package manager **bun**. Vue chosen for
  Moonbase SDK compatibility (Vue or raw Node only). Identifier
  `com.direktdsp.mydirekt`.
- `src/catalog.ts` — TS types mirroring `catalog.schema.json` (v2) + `fetchCatalog()`
  + `detectOs()`. Catalog URL defaults to the published Pages site, override with
  `VITE_CATALOG_URL`. `install_hints` optional so a v1 catalog still parses.
- `src/App.vue` — plugin picker: lists only plugins installable on the detected
  OS, checkbox multi-select + select-all, version/size/format badges, live
  per-plugin progress bar, selected-count + total-size bar.

### Phase 3 — Download + install engine (Rust) ✅ CODE DONE

**Phase 3a — parallel download + verify** — `src-tauri/src/install.rs`
- `download_and_verify` command: concurrent download via **reqwest** (rustls, no
  OpenSSL sys-dep), streaming **sha2** verify against the catalog SHA256, progress
  on the `install://progress` event channel. Mismatched download is deleted, never
  cached. Per-item failure isolated; batch returns `DownloadResult[]`. Files cached
  under the OS app-cache dir.
- Frontend bridge: `src/install.ts` (`downloadAndVerify`, `onProgress`).

**Phase 3b — elevated serial install** — one runner + two OS-gated batch modules
- `src-tauri/src/runner.rs` — `install_verified` command. Groups items by type:
  zip installs per-item; pkg and nsis each run as **one elevated batch** (single
  prompt for the whole selection). Shared `push_batch` helper emits `install://run`
  events + collects results; whole-batch failure (declined elevation) marks every
  item in the batch failed. Order preserved.
- **Linux** (in runner.rs, no elevation): extract the plugin zip, copy bundles to
  `~/.vst3` / `~/.clap`. Path-traversal-safe (`enclosed_name()`), preserves the
  exec bit on `.so`. Standalone + manual PDF skipped this phase.
- **macOS** — `src-tauri/src/macos.rs`: build one shell script running each
  `installer -pkg -target /` serially with `MYDIREKT <idx> OK|FAIL` markers, run
  once via `osascript "... with administrator privileges"` (one admin prompt).
- **Windows** — `src-tauri/src/windows.rs`: build one `.cmd` running each
  `installer.exe /S` with `start /wait` (serial), launch once elevated via
  PowerShell `Start-Process -Verb RunAs -Wait` (one UAC prompt). Markers written
  to a result file the non-elevated parent reads (can't read child stdout across
  UAC). Declined UAC / missing markers → failures.
- All script builders + result parsers are **pure and unit-tested on any OS**;
  only the actual elevation exec is `#[cfg(target_os = ...)]`-gated (hence
  execution still needs testing on real mac/Windows).

**Elevation model decision (recorded):** separate elevated helper subprocess, NOT
a whole-app elevated manifest — UI stays at normal privilege. Two modes:
  1. **Prompt each run** — ✅ implemented (the osascript / RunAs launches above).
  2. **Persistent helper** — ⬜ later (Windows service / macOS `SMAppService` /
     Linux polkit+systemd). Bigger security surface; the batch/parser split is
     designed so this slots in behind the same interface.

### Phase 4 — Moonbase bulk authentication ⬜ FUTURE
- Optional login → Moonbase entitlement query (server-side) → default-check owned
  plugins. Client holds only an auth token. Never install-gated.
- **Before starting:** gather the Moonbase SDK/API shape (it's Vue-or-Node only —
  the Vue choice in Phase 2 was to keep this path open). Confirm the entitlement
  endpoint + token flow.

### Phase 5 — Web page updates (`gen_site.py`, InstallerGenerator repo) ⬜ TODO
- Add a hero: "Get the MyDirekt app" (links to app releases).
- Keep every per-plugin card + per-OS manual download button (the "still give
  users the choice" requirement). Fully doable without the app running.

## Distribution / CI

`.github/workflows/build.yml` — matrix build (ubuntu/macos/windows) via
`tauri-action`, uploads per-OS bundles as artifacts, on `workflow_dispatch` + `v*`
tags. macOS builds **unsigned** on the GitHub-hosted runner for now; the
signing/notarization env is stubbed (commented) so switching to the planned
self-hosted notarization runner is a `runs-on` label change + adding Apple
secrets. **Currently blocked on org Actions billing.**

## Open questions (defer until the phase that needs them)
- App auto-update mechanism (Tauri updater vs. manual).
- App code-signing / notarization (macOS Gatekeeper, Windows SmartScreen).
- Where the app binaries are hosted (likely a GitHub Release on the app repo).
- Uninstall from within the app (needs `install_paths` — already in catalog).
