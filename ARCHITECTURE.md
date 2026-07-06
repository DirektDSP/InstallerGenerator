# Architecture

InstallerGenerator is a **manifest-driven, central orchestrator**. This document
is the contract: the manifest schema, the per-plugin build-recipe divergences it
has to absorb, the installer templating rules, and the catalog format.

## 1. The manifest (`plugins/<name>.toml`)

One file per plugin. This is the *only* per-plugin input; everything the
pipeline does is derived from it. Fields:

```toml
schema_version = "1"

[repo]
name          = "Polygraph"              # GitHub repo under DirektDSP/
ref           = ""                       # optional: pin a tag/branch/sha; "" = default branch

[identity]
product_name  = "Polygraph"              # display name (DAWs, installer UI)
company_name  = "DirektDSP"
bundle_id     = "com.direktdsp.polygraph"
# One-line, honest description shown on the installer welcome page + catalog.
# (Explicit per plugin so we never again ship Churn calling itself a
#  "polyphonic guitar-to-MIDI plugin" — that was a copy-paste bug.)
description   = "real-time polyphonic guitar to MIDI"
tagline       = "Polygraph — real-time polyphonic guitar to MIDI."
trial_days    = 7
website       = "https://direktdsp.com"

[formats]
# Which formats exist per OS. Drives installer sections and validation.
windows       = ["VST3", "CLAP", "Standalone"]
macos         = ["VST3", "AU", "CLAP", "Standalone"]
linux         = ["VST3", "CLAP", "Standalone"]

[build]
system            = "cmake"              # "cmake" | "projucer" (future: legacy trio)
build_dir         = "build"              # Polygraph/Churn: "build"; Chasm: "Builds"
artefacts_subdir  = "{name}_artefacts"   # under build_dir; {name} = repo.name
needs_plugin_template = true             # clone sibling DirektDSP/PluginTemplate?
disable_moonbase_flag = "POLYGRAPH_DISABLE_MOONBASE"   # CMake -D... for dev builds
config_secret     = "POLYGRAPH_CONFIG_B64"             # base64 moonbase config secret
# CMake target names per format (differ only by product name prefix, but explicit
# because Chasm has no Standalone target and legacy plugins won't be cmake at all).
targets           = { VST3 = "Polygraph_VST3", CLAP = "Polygraph_CLAP", AU = "Polygraph_AU", Standalone = "Polygraph_Standalone" }

[assets]
# Per-plugin brand binaries copied into packaging/ before rendering.
# Paths are relative to the cloned plugin repo. If the plugin already carries
# NSIS-ready assets (Polygraph/Churn do), point at them; otherwise the generator
# falls back to templates/assets/ placeholders.
icon_ico   = "packaging/icon.ico"
icon_png   = "packaging/icon.png"
header_bmp = "packaging/header.bmp"
welcome_bmp= "packaging/welcome.bmp"
```

`render_installer.py` reads this, substitutes every `@TOKEN@` in the templates,
and writes a ready-to-compile `packaging/installer.nsi` + macOS files into the
cloned plugin's working tree.

## 2. Build-recipe divergences (why the manifest looks the way it does)

The three launch plugins are *not* uniform under the hood. The manifest exists
to paper over exactly these differences so the pipeline stays single-path:

| Aspect | Polygraph | Churn | Chasm |
|--------|-----------|-------|-------|
| Identity source | `project.toml` | `project.toml` | hardcoded in `CMakeLists.txt`, exported via `GitHubENV.cmake` → `.env` |
| Sibling `../PluginTemplate` | **required** | **required** | not used (all submodules in-repo) |
| JUCE acquisition | submodule (via template) | submodule | submodule (`JUCE/`) |
| Build dir | `build/` | `build/` | `Builds/` |
| Formats | VST3/AU/CLAP/Standalone | VST3/AU/CLAP/Standalone | AU/VST3/AUv3/CLAP — **no Standalone** |
| Windows installer today | NSIS | NSIS | **Inno Setup** → migrating to NSIS |
| Manufacturer code | `Dkdp` (project.toml) | `Dkdp` | `Manu` (Pamplejuce default, uncustomized) |
| CI dispatch | `[win-build]`/`[mac-build]` flags | same | commit-flag driven too |

Chasm is the stress test: migrating it Inno→NSIS is what proves the template is
genuinely plugin-agnostic and not just a Polygraph/Churn clone.

Two data-quality issues this project also resolves:
- **Version drift**: Polygraph's `VERSION` file said `1.0.0` while its
  `project.toml` said `0.3.1`. The pipeline treats the `VERSION` file (or the
  git tag) as the single source of truth — same rule the old CI already used for
  installers — and the catalog records exactly what shipped.
- **Churn's welcome text** described Polygraph's function. Descriptions are now
  explicit per-manifest, so the rendered installer can never inherit a sibling's.

## 3. Installer templating rules

- **Windows (NSIS)** — `templates/installer.nsi.in`. Derived verbatim from
  Polygraph's `packaging/installer.nsi` (the two NSIS scripts were byte-identical
  after a name swap, so it templatizes cleanly). Plugin-specific literals become
  `@TOKEN@`:
  - `@PRODUCT_NAME@`, `@PRODUCT_NAME_LOWER@`, `@COMPANY_NAME@`, `@DESCRIPTION@`,
    `@WEBSITE@`, and the format sections are emitted conditionally from
    `[formats].windows`.
  - `VERSION`, `ARTIFACTS_DIR`, `OUTDIR` stay `/D` command-line defines (CI
    passes them), exactly as today.
  - Brand-asset defines (`MUI_ICON`, header/welcome bitmaps) and the EULA page
    are prefixed with `${__FILEDIR__}\` so they resolve against the `.nsi`'s own
    directory. `joncloud/makensis-action@v4` passes an absolute script path but
    runs makensis from the workspace root, not the script dir — bare-relative
    asset paths would resolve against the wrong cwd and fail the build.
- **macOS (`.pkg`)** — `templates/macos/build_pkg.sh` +
  `distribution.xml.template`. Already fully env/token driven upstream; the only
  hardcoded literal removed is the `OUT_PKG` product name, now `$PRODUCT_NAME`.
- **Shared resources** — one `EULA` + `README` in `templates/resources/`, bundled
  into every installer. These were byte-identical across Polygraph and Churn, so
  they live here once.

Render is pure text substitution with a hard **no-unsubstituted-token** check
(`grep '@[A-Z_]@'` after render fails the build) — the same guard the upstream
macOS script already used, now applied to every generated file.

## 4. Catalog contract (`catalog.json`)

The machine-readable index the download site renders from and the future desktop
bulk-installer consumes. Schema in `schema/catalog.schema.json`. Shape:

```json
{
  "generated_at": "2026-07-06T00:00:00Z",
  "publisher": "DirektDSP",
  "plugins": [
    {
      "name": "Polygraph",
      "version": "1.0.0",
      "description": "real-time polyphonic guitar to MIDI",
      "installers": {
        "windows": { "url": "...DirektDSP-Polygraph-1.0.0-Windows.exe", "sha256": "...", "size": 12345 },
        "macos":   { "url": "...DirektDSP-Polygraph-1.0.0-macOS.pkg",   "sha256": "...", "size": 12345 },
        "linux":   { "url": "...Polygraph-1.0.0-Linux.zip",             "sha256": "...", "size": 12345 }
      },
      "formats": ["VST3", "AU", "CLAP", "Standalone"],
      "install_paths": {
        "windows": { "VST3": "%COMMONPROGRAMFILES%\\VST3\\DirektDSP", "CLAP": "%COMMONPROGRAMFILES%\\CLAP\\DirektDSP" },
        "macos":   { "VST3": "/Library/Audio/Plug-Ins/VST3", "AU": "/Library/Audio/Plug-Ins/Components", "CLAP": "/Library/Audio/Plug-Ins/CLAP" }
      }
    }
  ]
}
```

`install_paths` is included so the desktop app can verify/repair installs and
offer uninstall without re-deriving each plugin's layout. It mirrors exactly what
the NSIS + pkg installers write.

## 5. Secrets

Set on the InstallerGenerator repo (org secrets preferred):

| Secret | Purpose |
|--------|---------|
| `PAT` | clone private plugin repos + sibling `PluginTemplate` |
| `<PLUGIN>_CONFIG_B64` | per-plugin base64 Moonbase config (e.g. `POLYGRAPH_CONFIG_B64`) |
| `MACOS_INSTALLER_SIGN_IDENTITY` | optional; enables `productbuild --sign` |
| `MOONBASE_ACCOUNT_ID` / `_API_KEY` / `_PRODUCT_ID` | optional Moonbase upload |

`GITHUB_TOKEN` (auto) covers Pages deploy + Release creation within this repo.
