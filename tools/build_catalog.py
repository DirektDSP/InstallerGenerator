#!/usr/bin/env python3
"""Build catalog.json from a directory of published installers + manifests.

The catalog is the contract the download site renders from and the future
desktop bulk-installer reads. See schema/catalog.schema.json.

Installer filename conventions (produced by the templates):
    <Company>-<Product>-<Version>-Windows.exe
    <Company>-<Product>-<Version>-macOS.pkg
    <Product>-<Version>-Linux.zip            (or <Product>-v<Version>-Linux.zip)

Usage:
    python3 tools/build_catalog.py \
        --artifacts-dir dist \
        --url-base https://github.com/DirektDSP/{repo}/releases/download/v{version} \
        --out site/catalog.json

--url-base is a template with {repo}, {version}, {product}, {filename} fields.
If a plugin has no installer file present in --artifacts-dir, it is skipped
(with a logged note) rather than emitted with dangling URLs.

Stdlib only.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

import manifest as mf

# Where each format lands, per OS — mirrors the NSIS + pkg installers exactly.
INSTALL_PATHS = {
    "windows": {
        "VST3": r"%COMMONPROGRAMFILES%\VST3\{company}",
        "CLAP": r"%COMMONPROGRAMFILES%\CLAP\{company}",
        "Standalone": r"%PROGRAMFILES%\{company}\{product}",
    },
    "macos": {
        "VST3": "/Library/Audio/Plug-Ins/VST3",
        "AU": "/Library/Audio/Plug-Ins/Components",
        "CLAP": "/Library/Audio/Plug-Ins/CLAP",
        "Standalone": "/Applications",
    },
}


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def find_installer(artifacts_dir: Path, company: str, product: str, os_key: str):
    """Return the first matching installer Path for a plugin+OS, or None."""
    patterns = {
        "windows": [f"{company}-{product}-*-Windows.exe"],
        "macos": [f"{company}-{product}-*-macOS.pkg"],
        # Linux zips historically use either <Product>-<Version>- or -v<Version>-
        "linux": [f"{product}-*-Linux.zip"],
    }[os_key]
    for pat in patterns:
        hits = sorted(artifacts_dir.rglob(pat))
        if hits:
            return hits[0]
    return None


def version_from_filename(fn: str, product: str) -> str | None:
    """Extract X.Y.Z from a known installer filename."""
    # <Company>-<Product>-<Version>-Windows.exe / -macOS.pkg  -> token before -OS
    stem = fn.rsplit(".", 1)[0]
    for suffix in ("-Windows", "-macOS", "-Linux"):
        if stem.endswith(suffix):
            stem = stem[: -len(suffix)]
            break
    parts = stem.split("-")
    ver = parts[-1] if parts else ""
    return ver.lstrip("v") or None


def build_plugin_entry(m: dict, artifacts_dir: Path, url_base: str) -> dict | None:
    ident = m["identity"]
    company = ident["company_name"]
    product = ident["product_name"]
    # Distributable filenames use the space-free slug (see manifest.product_slug).
    slug = mf.product_slug(product)

    installers: dict[str, dict] = {}
    resolved_version: str | None = None
    for os_key in ("windows", "macos", "linux"):
        path = find_installer(artifacts_dir, company, slug, os_key)
        if not path:
            continue
        ver = version_from_filename(path.name, product)
        resolved_version = resolved_version or ver
        url = url_base.format(
            repo=m["repo"]["name"], version=ver or "", product=product, filename=path.name
        )
        installers[os_key] = {
            "filename": path.name,
            "url": url,
            "sha256": sha256(path),
            "size": path.stat().st_size,
        }

    if not installers:
        print(f"  skip {product}: no installers found in {artifacts_dir}", file=sys.stderr)
        return None

    # Union of formats across OSes for the summary badge list.
    all_formats: list[str] = []
    for os_key in ("windows", "macos", "linux"):
        for fmt in m["formats"][os_key]:
            if fmt not in all_formats:
                all_formats.append(fmt)

    install_paths: dict[str, dict] = {}
    for os_key in ("windows", "macos"):
        paths = {}
        for fmt in m["formats"][os_key]:
            tmpl = INSTALL_PATHS.get(os_key, {}).get(fmt)
            if tmpl:
                paths[fmt] = tmpl.format(company=company, product=product)
        if paths:
            install_paths[os_key] = paths

    return {
        "name": product,
        "slug": m["_slug"],
        "version": resolved_version or "0.0.0",
        "description": ident["description"],
        "tagline": ident.get("tagline", ""),
        "website": ident["website"],
        "repo": f"{company}/{m['repo']['name']}",
        "formats": all_formats,
        "installers": installers,
        "install_paths": install_paths,
    }


def build_catalog(names: list[str], artifacts_dir: Path, url_base: str,
                  generated_at: str) -> dict:
    plugins = []
    for name in names:
        m = mf.load(name)
        entry = build_plugin_entry(m, artifacts_dir, url_base)
        if entry:
            plugins.append(entry)
    plugins.sort(key=lambda p: p["name"].lower())
    return {
        "generated_at": generated_at,
        "publisher": "DirektDSP",
        "catalog_version": "1",
        "plugins": plugins,
    }


def all_manifest_names() -> list[str]:
    return sorted(p.stem for p in mf.PLUGINS_DIR.glob("*.toml"))


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description="Build catalog.json from installers")
    ap.add_argument("--artifacts-dir", required=True, type=Path)
    ap.add_argument("--url-base", required=True,
                    help="URL template with {repo} {version} {product} {filename}")
    ap.add_argument("--out", required=True, type=Path)
    ap.add_argument("--generated-at", required=True,
                    help="UTC ISO-8601 timestamp (pass from CI: date -u +%%Y-%%m-%%dT%%H:%%M:%%SZ)")
    ap.add_argument("--plugins", nargs="*", help="manifest names (default: all)")
    args = ap.parse_args(argv)

    names = args.plugins or all_manifest_names()
    catalog = build_catalog(names, args.artifacts_dir, args.url_base, args.generated_at)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(catalog, indent=2) + "\n")
    print(f"Wrote {args.out} with {len(catalog['plugins'])} plugin(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
