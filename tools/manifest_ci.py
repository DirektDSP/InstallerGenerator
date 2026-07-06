#!/usr/bin/env python3
"""Surface manifest fields to GitHub Actions.

Two modes:

  github-output <name>
      Emit key=value lines suitable for appending to $GITHUB_OUTPUT: repo_name,
      product_name, company_name, bundle_id, needs_plugin_template, build_dir,
      artefacts_subdir, disable_moonbase_flag, config_secret, ref, and per-OS
      space-separated build target lists + cmake target-name lists.

  matrix
      Emit a JSON array of manifest slugs for a fan-out matrix.

Keeping this in tested Python means the workflow YAML stays a thin driver.
Stdlib only.
"""
from __future__ import annotations

import json
import sys

import manifest as mf


def _targets_for(m: dict, os_key: str) -> list[str]:
    """CMake target names to build for the formats this OS ships."""
    tmap = m["build"].get("targets", {})
    out = []
    for fmt in m["formats"][os_key]:
        t = tmap.get(fmt)
        if t:
            out.append(t)
    # A Tests target only exists for plugins that carry one (Polygraph/Churn/Chasm
    # via PluginTemplate). Migrated free plugins (Fuzzboy) have no Tests target, so
    # gate on [build].has_tests (default true to preserve existing behaviour).
    if m["build"].get("has_tests", True):
        out.append("Tests")
    return out


def github_output(name: str) -> str:
    m = mf.load(name)
    repo = m["repo"]
    ident = m["identity"]
    build = m["build"]
    lines = {
        "slug": m["_slug"],
        "repo_name": repo["name"],
        "ref": repo.get("ref", ""),
        "product_name": ident["product_name"],
        "product_slug": mf.product_slug(ident["product_name"]),
        "company_name": ident["company_name"],
        "bundle_id": ident["bundle_id"],
        "needs_plugin_template": str(build.get("needs_plugin_template", False)).lower(),
        "build_dir": build.get("build_dir", "build"),
        "artefacts_subdir": build.get("artefacts_subdir", f"{repo['name']}_artefacts"),
        "disable_moonbase_flag": build.get("disable_moonbase_flag", ""),
        "config_secret": build.get("config_secret", ""),
        "has_tests": str(build.get("has_tests", True)).lower(),
        "windows_formats": " ".join(m["formats"]["windows"]),
        "macos_formats": " ".join(m["formats"]["macos"]),
        "linux_formats": " ".join(m["formats"]["linux"]),
        "windows_targets": " ".join(_targets_for(m, "windows")),
        "macos_targets": " ".join(_targets_for(m, "macos")),
        "linux_targets": " ".join(_targets_for(m, "linux")),
    }
    return "".join(f"{k}={v}\n" for k, v in lines.items())


def matrix() -> str:
    return json.dumps(sorted(p.stem for p in mf.PLUGINS_DIR.glob("*.toml")))


def main(argv: list[str]) -> int:
    if not argv:
        print("usage: manifest_ci.py {github-output <name>|matrix}", file=sys.stderr)
        return 2
    if argv[0] == "github-output":
        sys.stdout.write(github_output(argv[1]))
        return 0
    if argv[0] == "matrix":
        sys.stdout.write(matrix())
        return 0
    print(f"unknown mode: {argv[0]}", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
