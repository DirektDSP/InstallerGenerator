"""Shared manifest loading + token derivation for InstallerGenerator.

Stdlib only (tomllib, pathlib). Python 3.11+.
"""
from __future__ import annotations

import tomllib
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
PLUGINS_DIR = REPO_ROOT / "plugins"

# The formats the desktop installers know how to place. AUv3 is deliberately
# excluded (macOS App Store sandbox path only, not a flat-pkg payload).
KNOWN_FORMATS = ["VST3", "AU", "CLAP", "Standalone"]


class ManifestError(ValueError):
    pass


def _require(d: dict, key: str, ctx: str):
    if key not in d:
        raise ManifestError(f"{ctx}: missing required key '{key}'")
    return d[key]


def load(name_or_path: str | Path) -> dict:
    """Load and validate a plugin manifest by bare name or explicit path."""
    p = Path(name_or_path)
    if not p.suffix:
        p = PLUGINS_DIR / f"{str(name_or_path).lower()}.toml"
    if not p.exists():
        raise ManifestError(f"manifest not found: {p}")
    with p.open("rb") as fh:
        m = tomllib.load(fh)

    # Structural validation — fail early with a clear message rather than
    # KeyError deep inside rendering.
    repo = _require(m, "repo", str(p))
    ident = _require(m, "identity", str(p))
    formats = _require(m, "formats", str(p))
    build = _require(m, "build", str(p))
    for k in ("name",):
        _require(repo, k, f"{p} [repo]")
    for k in ("product_name", "company_name", "bundle_id", "description", "website"):
        _require(ident, k, f"{p} [identity]")
    for k in ("windows", "macos", "linux"):
        _require(formats, k, f"{p} [formats]")
    for osname in ("windows", "macos", "linux"):
        for fmt in formats[osname]:
            if fmt not in KNOWN_FORMATS:
                raise ManifestError(
                    f"{p} [formats].{osname}: unknown format '{fmt}' "
                    f"(known: {', '.join(KNOWN_FORMATS)})"
                )
    if "VST3" not in formats["windows"] or "VST3" not in formats["macos"]:
        raise ManifestError(f"{p}: VST3 is required on windows and macos")
    _require(build, "system", f"{p} [build]")

    m["_path"] = str(p)
    m["_slug"] = p.stem
    return m


def website_label(website: str) -> str:
    """direktdsp.com from https://direktdsp.com (for the NSIS finish-page link)."""
    return website.split("://", 1)[-1].rstrip("/")


def product_slug(product_name: str) -> str:
    """Filename-safe product name (spaces removed). Used only for distributable
    artifact filenames — GitHub Releases rewrite spaces to dots, which would
    break catalog URL matching. Display/paths keep the real (spaced) name."""
    return product_name.replace(" ", "")


def nsis_tokens(m: dict) -> dict[str, str]:
    """The @TOKEN@ -> value map for installer.nsi.in."""
    ident = m["identity"]
    return {
        "PRODUCT_NAME": ident["product_name"],
        "PRODUCT_NAME_LOWER": ident["product_name"].lower(),
        "PRODUCT_SLUG": product_slug(ident["product_name"]),
        "COMPANY_NAME": ident["company_name"],
        "DESCRIPTION": ident["description"],
        "WEBSITE": ident["website"],
        "WEBSITE_LABEL": website_label(ident["website"]),
    }
