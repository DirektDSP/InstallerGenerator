# InstallerGenerator

Central build + installer factory for DirektDSP audio plugins.

One repo that clones each plugin, builds every format, wraps them in a
**single unified installer format** (NSIS on Windows, `productbuild` `.pkg` on
macOS, zip on Linux), and publishes every plugin's installers to one place with
a machine-readable `catalog.json` — the seed for a future desktop app that can
bulk-install everything a user owns.

## Why this exists

Before this, every plugin carried its own copy-pasted installer scripts and CI:

| Plugin | Windows installer | macOS installer | CI |
|--------|-------------------|-----------------|-----|
| Polygraph | NSIS | `productbuild` `.pkg` | per-repo GHA |
| Churn | NSIS (byte-identical to Polygraph's, name-swapped) | `.pkg` | per-repo GHA |
| Chasm | **Inno Setup** (different tech) | `.pkg` | per-repo GHA |

Same job, three drifting implementations. The NSIS scripts were identical after
a find-and-replace; Chasm used a different installer technology entirely; and a
copy-paste bug had shipped Churn's installer describing it as a "polyphonic
guitar-to-MIDI plugin" (that's Polygraph). Duplicated work, inconsistent output.

**InstallerGenerator collapses all of that into one templated pipeline.** Add a
plugin by dropping a ~30-line manifest in `plugins/`. Everything else — build
recipe, installer, checksums, catalog, download page — is generated.

## How it works (central orchestrator)

```
                    plugins/<name>.toml   (identity + build recipe)
                            │
   ┌────────────────────────┼────────────────────────┐
   │  InstallerGenerator (this repo) — GitHub Actions │
   │                                                  │
   │  1. clone DirektDSP/<Name> @ tag/ref             │
   │  2. build every format per-OS (from manifest)    │
   │  3. render templates/installer.nsi.in → .nsi     │
   │  4. makensis / build_pkg.sh → installers         │
   │  5. sha256 + smoke-test each installer           │
   │  6. build_catalog.py  → catalog.json             │
   │  7. gen_site.py       → static download site     │
   └────────────────────────┬─────────────────────────┘
                            │
              ┌─────────────┴──────────────┐
              ▼                            ▼
     GitHub Pages download          GitHub Release
     site + catalog.json            (durable installer host)
```

The plugin repos do **not** need their own installer scripts or a copied CI job.
InstallerGenerator owns the whole pipeline centrally and pulls each plugin in.

## Layout

```
plugins/            one <name>.toml manifest per plugin (the only per-plugin input)
templates/          the single source-of-truth installer templates
  installer.nsi.in    tokenized NSIS script (Windows)
  macos/              build_pkg.sh + distribution.xml.template (macOS .pkg)
  resources/          shared EULA + README bundled into every installer
tools/              stdlib-only Python (no third-party deps)
  render_installer.py   manifest -> packaging/installer.nsi (+ macOS files)
  build_catalog.py      installers + manifests -> catalog.json
  gen_site.py           catalog.json -> static GitHub Pages site
schema/             catalog.schema.json (the contract the desktop app reads)
.github/workflows/  build-plugin.yml (one plugin) + build-all.yml (fan-out + publish)
site/               static assets for the download page
```

## Add a plugin

1. Copy an existing `plugins/*.toml`, fill in identity + build recipe.
2. Ensure the plugin repo has a `VERSION` file and (if it uses the shared
   `../PluginTemplate`) that `needs_plugin_template = true` is set.
3. Add the plugin's name to the matrix in `.github/workflows/build-all.yml`
   (or let it be auto-discovered from `plugins/`).
4. Set the required repo secrets (PAT, per-plugin Moonbase config) — see
   [ARCHITECTURE.md](ARCHITECTURE.md#secrets).

Run `python3 tools/render_installer.py <name>` locally to preview the exact
installer script that CI will compile.

See [ARCHITECTURE.md](ARCHITECTURE.md) for the manifest schema, the build-recipe
divergences between plugins, and the catalog contract.
