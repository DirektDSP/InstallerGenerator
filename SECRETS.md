# Required secrets

All secrets are set on the **InstallerGenerator** repo (this repo) — that's where
the orchestrator runs. Set them under *Settings → Secrets and variables → Actions
→ New repository secret*, or with the `gh` commands below.

> Only 5 real secrets exist. `PLUGIN_CONFIG_B64` seen in `build-plugin.yml` is a
> reusable-workflow **input**, not a secret you set — `build-all.yml` maps each
> plugin's own config secret into it.

## The list

| Secret | Required? | Used by | Purpose |
|--------|-----------|---------|---------|
| `PAT` | **Yes** | every plugin | Clone private repos: `MakeItLoud`, and (once they go private) `Polygraph`/`Churn`, plus the private `PluginTemplate` that Polygraph/Churn build against. Public clones don't need it, but the workflow always passes it, so it must exist. |
| `POLYGRAPH_CONFIG_B64` | If Polygraph licensed | polygraph | base64 of Polygraph's `moonbase_api_config.json`. Omit only if you also disable Moonbase (see caveat). |
| `CHURN_CONFIG_B64` | If Churn licensed | churn | base64 of Churn's `moonbase_api_config.json`. |
| `CONFIG_JSON_B64` | If Chasm licensed | chasm | base64 of Chasm's `moonbase_api_config.json`. |
| `MACOS_INSTALLER_SIGN_IDENTITY` | Optional | all (macOS) | Developer ID for `productbuild --sign`. Blank → unsigned `.pkg` (still builds). |

The free trio — **Fuzzboy, Hot-Potato, MakeItLoud** — need **no config secret**
(no licensing). MakeItLoud still needs `PAT` because its repo is private.

## PAT scope

A classic PAT needs the **`repo`** scope (read access to the private repos +
`PluginTemplate`). A fine-grained PAT needs **Contents: Read** on: `MakeItLoud`,
`PluginTemplate`, and — once private — `Polygraph`, `Churn`. Chasm stays public.

`GITHUB_TOKEN` (automatic) already covers this repo's Release + Pages publish;
you do **not** create that one.

## Set them with gh

```sh
# Required
gh secret set PAT                          --repo DirektDSP/InstallerGenerator   # paste the PAT
gh secret set POLYGRAPH_CONFIG_B64         --repo DirektDSP/InstallerGenerator < polygraph_moonbase_api_config.json.b64
gh secret set CHURN_CONFIG_B64             --repo DirektDSP/InstallerGenerator < churn_moonbase_api_config.json.b64
gh secret set CONFIG_JSON_B64              --repo DirektDSP/InstallerGenerator < chasm_moonbase_api_config.json.b64

# Optional (macOS signing)
gh secret set MACOS_INSTALLER_SIGN_IDENTITY --repo DirektDSP/InstallerGenerator  # e.g. "Developer ID Installer: DirektDSP (TEAMID)"
```

Produce a config's base64 with:

```sh
base64 -w0 moonbase_api_config.json > config.b64   # Linux
base64      moonbase_api_config.json > config.b64   # macOS
```

## Minimal sets by goal

- **Free trio only** (Fuzzboy, Hot-Potato, MakeItLoud): `PAT` — that's it.
- **All 6, licensed**: `PAT` + `POLYGRAPH_CONFIG_B64` + `CHURN_CONFIG_B64` +
  `CONFIG_JSON_B64` (+ `MACOS_INSTALLER_SIGN_IDENTITY` for signed macOS).

## Caveat — Moonbase without a config secret

Polygraph/Churn/Chasm's CMake builds Moonbase by default and expects
`assets/moonbase_api_config.json`. The workflow skips writing it when the config
secret is blank, but the Configure step does **not** yet pass a
`-DDISABLE_MOONBASE` flag, so a config-less build of those three will likely
fail. Either set their config secret, or ask for the disable-flag wiring
(tracked separately). The free trio are unaffected.
