#!/usr/bin/env python3
"""Embargo gate for unreleased plugins.

A manifest declares [release] status = "public" | "embargoed"; unflagged is
embargoed (see manifest.DEFAULT_RELEASE_STATUS). Embargoed plugins still build in
CI, staying available as repo-private workflow artifacts.

Two enforcement points, since hiding a plugin from the site is not hiding its
binaries. build_catalog.py skips embargoed manifests, keeping them out of
catalog.json and so off the site. `--prune-dir` then deletes their installers
before upload, because the aggregate release is public with deterministic
filenames — an unpruned installer is fetchable by URL with nothing linking it.

Usage:
    python3 tools/embargo.py --list                  # status of every manifest
    python3 tools/embargo.py --list embargoed        # slugs, one per line
    python3 tools/embargo.py --prune-dir dist        # delete embargoed artifacts
    python3 tools/embargo.py --prune-dir dist --dry-run

Stdlib only.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import build_catalog as bc
import manifest as mf

OS_KEYS = ("windows", "macos", "linux")


def all_manifest_names() -> list[str]:
    return sorted(p.stem for p in mf.PLUGINS_DIR.glob("*.toml"))


def partition(names: list[str]) -> tuple[list[str], list[str]]:
    """(public, embargoed) manifest names."""
    public, embargoed = [], []
    for name in names:
        (public if mf.is_public(mf.load(name)) else embargoed).append(name)
    return public, embargoed


def artifact_globs(m: dict) -> list[str]:
    """Globs matching one plugin's distributable artifacts.

    Trailing '*' also catches the sidecars the staging step copies (.sha256).
    """
    ident = m["identity"]
    company = ident["company_name"]
    slug = mf.product_slug(ident["product_name"])
    globs = []
    for os_key in OS_KEYS:
        for pat in bc.installer_patterns(company, slug, os_key):
            globs.append(pat + "*")
    return globs


def prune(directory: Path, dry_run: bool = False) -> int:
    """Delete every embargoed plugin's artifacts from `directory`. Returns count."""
    if not directory.is_dir():
        print(f"embargo: {directory} is not a directory — nothing to prune",
              file=sys.stderr)
        return 0

    _, embargoed = partition(all_manifest_names())
    if not embargoed:
        print("embargo: no embargoed plugins; nothing to prune")
        return 0

    removed = 0
    for name in embargoed:
        m = mf.load(name)
        hits: list[Path] = []
        for pattern in artifact_globs(m):
            hits.extend(sorted(directory.rglob(pattern)))
        for path in hits:
            if not path.is_file():
                continue
            print(f"  {'would remove' if dry_run else 'removed'} "
                  f"{path.relative_to(directory)}  (embargo: {name})")
            if not dry_run:
                path.unlink()
            removed += 1

    verb = "would remove" if dry_run else "removed"
    print(f"embargo: {verb} {removed} artifact(s) for "
          f"{len(embargoed)} embargoed plugin(s): {', '.join(embargoed)}")
    return removed


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description="Embargo gate for unreleased plugins")
    ap.add_argument("--list", nargs="?", const="all",
                    choices=["all", "public", "embargoed"],
                    help="print manifest publication status")
    ap.add_argument("--prune-dir", type=Path,
                    help="delete embargoed plugins' artifacts from this directory")
    ap.add_argument("--dry-run", action="store_true",
                    help="with --prune-dir: report what would be deleted, delete nothing")
    args = ap.parse_args(argv)

    if not args.list and not args.prune_dir:
        ap.error("nothing to do: pass --list and/or --prune-dir")

    if args.list:
        public, embargoed = partition(all_manifest_names())
        if args.list == "public":
            print("\n".join(public))
        elif args.list == "embargoed":
            print("\n".join(embargoed))
        else:
            for name in sorted(public + embargoed):
                print(f"{'public   ' if name in public else 'embargoed'}  {name}")
            print(f"\n{len(public)} public, {len(embargoed)} embargoed", file=sys.stderr)

    if args.prune_dir:
        prune(args.prune_dir, dry_run=args.dry_run)

    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
