# InstallerGenerator

Central build + installer factory for DirektDSP audio plugins.

## Add a plugin

1. Copy an existing `plugins/*.toml`, fill in identity + build recipe.
2. Ensure the plugin repo has a `VERSION` file and (if it uses the shared
   `../PluginTemplate`) that `needs_plugin_template = true` is set.
3. Add the plugin's name to the matrix in `.github/workflows/build-all.yml`
   (or let it be auto-discovered from `plugins/`).
4. Set the required repo secrets
