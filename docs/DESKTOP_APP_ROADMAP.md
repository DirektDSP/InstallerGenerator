# DirektDSP Installer — Desktop App Roadmap

> Status: planning. This document is the north star for the cross-platform desktop
> **download + install manager** (Ninite-style multi-select) that consumes this
> repo's `catalog.json`, with room for Moonbase-backed bulk licensing later.
>
> **The app lives in a separate private repo** — this file stays here because the
> *contract* (`catalog.json` + schema) it depends on is owned here. See
> "Repo layout" below.

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

### Phase 2 — Desktop app skeleton (Tauri, private repo)
- New private repo (Tauri project). Rust backend + minimal webview frontend.
- Frontend fetches the published `catalog.json` (same URL the site uses).
- Render the plugin list with checkboxes, versions, sizes, format badges —
  the same data the site cards show.
- No install yet: just "select and see what would download".
- **Prereq:** Rust toolchain (`rustup default stable`) + Node; Tauri CLI.

### Phase 3 — Download + install engine (Rust)
- Rust: download selected installers, verify SHA256 against catalog, run the
  per-OS silent invocation from `install_hints`, report progress to the webview.
- Elevation: request admin/root once per session, not per plugin.
- Handle partial failure (one plugin fails → others still install).

### Phase 4 — Moonbase bulk authentication (future)
- Optional login → Moonbase entitlement query (server-side) → default-check owned
  plugins. Client holds only an auth token. Never install-gated.

### Phase 5 — Web page updates (`gen_site.py`, this repo)
- Add a hero: "Get the DirektDSP Installer app" (links to app releases).
- Keep every per-plugin card + per-OS manual download button (the "still give
  users the choice" requirement).

## Open questions (defer until the phase that needs them)
- App auto-update mechanism (Tauri updater vs. manual).
- App code-signing / notarization (macOS Gatekeeper, Windows SmartScreen).
- Where the app binaries are hosted (likely a GitHub Release on the app repo).
- Uninstall from within the app (needs `install_paths` — already in catalog).
