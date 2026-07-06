# Required secrets

| Secret | Required? | Used by | Purpose |
|--------|-----------|---------|---------|
| `PAT` | **Yes** | every plugin | Clone private repos: `MakeItLoud`, and (once they go private) `Polygraph`/`Churn`, plus the private `PluginTemplate` that Polygraph/Churn build against. Public clones don't need it, but the workflow always passes it, so it must exist. |
| `POLYGRAPH_CONFIG_B64` | If Polygraph licensed | polygraph | base64 of Polygraph's `moonbase_api_config.json`. Omit only if you also disable Moonbase (see caveat). |
| `CHURN_CONFIG_B64` | If Churn licensed | churn | base64 of Churn's `moonbase_api_config.json`. |
| `CONFIG_JSON_B64` | If Chasm licensed | chasm | base64 of Chasm's `moonbase_api_config.json`. |
| `MACOS_INSTALLER_SIGN_IDENTITY` | Optional | all (macOS) | Developer ID for `productbuild --sign`. Blank → unsigned `.pkg` (still builds). |

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
