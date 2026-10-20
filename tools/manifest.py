"""Shared manifest loading + token derivation for InstallerGenerator.

Stdlib only (tomllib, pathlib). Python 3.11+.
"""
from __future__ import annotations

import re
import tomllib
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
PLUGINS_DIR = REPO_ROOT / "plugins"

# The formats the desktop installers know how to place. AUv3 is deliberately
# excluded (macOS App Store sandbox path only, not a flat-pkg payload).
KNOWN_FORMATS = ["VST3", "AU", "CLAP", "Standalone"]

# Publication state. Embargoed plugins still build in CI but stay off the public
# site and out of the aggregate release. Unflagged defaults to hidden, not leaked.
RELEASE_STATUSES = ["public", "embargoed"]
DEFAULT_RELEASE_STATUS = "embargoed"


# Per-OS runtime companions of the single-file formats (.clap / Standalone).
# macOS is excluded on purpose: its bundles carry their own Frameworks/Resources.
RUNTIME_FILE_OSES = ["windows", "linux"]
# Bare names only: they are spliced into shell loops (workflow) and NSIS paths, so
# no spaces, quotes, globs, separators or leading dots. A trailing "/" marks a
# directory explicitly and is stripped for the name check.
_RUNTIME_NAME_RE = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9._+-]*$")


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

    m["_runtime_files"] = _validate_runtime_files(m.get("runtime_files", {}), str(p))

    status = m.get("release", {}).get("status", DEFAULT_RELEASE_STATUS)
    if status not in RELEASE_STATUSES:
        raise ManifestError(
            f"{p} [release]: unknown status '{status}' "
            f"(known: {', '.join(RELEASE_STATUSES)})"
        )

    m["_path"] = str(p)
    m["_slug"] = p.stem
    m["_release_status"] = status
    return m


def _validate_runtime_files(table: dict, ctx: str) -> dict[str, list[str]]:
    """Validate the optional [runtime_files] table -> {os: [entry, ...]}.

    Each entry is a file or directory that sits beside the single-file formats
    (CLAP/ and Standalone/ in the build artefacts dir). A trailing "/" marks a
    directory explicitly; without it, an entry containing no "." is treated as a
    directory (e.g. "Licenses") and everything else as a file.
    """
    if not isinstance(table, dict):
        raise ManifestError(f"{ctx}: [runtime_files] must be a table")
    out: dict[str, list[str]] = {}
    for osname, entries in table.items():
        if osname not in RUNTIME_FILE_OSES:
            raise ManifestError(
                f"{ctx} [runtime_files]: unknown key '{osname}' "
                f"(known: {', '.join(RUNTIME_FILE_OSES)})"
            )
        if not isinstance(entries, list) or not all(isinstance(e, str) for e in entries):
            raise ManifestError(f"{ctx} [runtime_files].{osname}: must be a list of strings")
        seen: set[str] = set()
        for e in entries:
            name = e.rstrip("/")
            if not _RUNTIME_NAME_RE.match(name) or name.endswith("."):
                raise ManifestError(
                    f"{ctx} [runtime_files].{osname}: bad entry {e!r} (a bare file or "
                    f"directory name: letters, digits and . _ + - only, no paths or spaces)"
                )
            if name in seen:
                raise ManifestError(f"{ctx} [runtime_files].{osname}: duplicate entry {e!r}")
            seen.add(name)
        out[osname] = list(entries)
    return out


def runtime_files(m: dict, osname: str) -> list[str]:
    """Runtime companion entries for `osname`, as written in the manifest ([] if none)."""
    if "_runtime_files" in m:
        return list(m["_runtime_files"].get(osname, []))
    return list(m.get("runtime_files", {}).get(osname, []))


def runtime_entry(entry: str) -> tuple[str, bool]:
    """(bare name, is_directory) for a [runtime_files] entry."""
    name = entry.rstrip("/")
    return name, entry.endswith("/") or "." not in name


def release_status(m: dict) -> str:
    """"public" or "embargoed" — defaults to embargoed for an unflagged manifest."""
    return m.get("_release_status") or m.get("release", {}).get(
        "status", DEFAULT_RELEASE_STATUS
    )


def is_public(m: dict) -> bool:
    """True iff this plugin may appear in catalog.json / the site / the release."""
    return release_status(m) == "public"


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


def linux_tokens(m: dict) -> dict[str, str]:
    """The @TOKEN@ -> value map for templates/linux/LINUX-INSTALL.txt.in."""
    ident = m["identity"]
    return {
        "PRODUCT_NAME": ident["product_name"],
        "COMPANY_NAME": ident["company_name"],
        "WEBSITE": ident["website"],
        # Shared per-vendor directory convention: /usr/lib/<company>/<product>/
        "SHARED_DIR": f"{ident['company_name'].lower()}/{ident['product_name'].lower()}",
        "RUNTIME_FILES": ", ".join(runtime_entry(e)[0] for e in runtime_files(m, "linux")),
    }
