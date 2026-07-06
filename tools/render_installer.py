#!/usr/bin/env python3
"""Render a plugin manifest into a ready-to-compile installer tree.

Writes, into the cloned plugin's working dir (default: DirektDSP/<Name> beside
this repo, or --plugin-dir):

    packaging/installer.nsi          (from templates/installer.nsi.in)
    packaging/resources/EULA         (shared)
    packaging/resources/README       (shared)
    packaging/macos/build_pkg.sh     (shared, format-adaptive)
    packaging/macos/resources/{EULA,README}

Brand bitmaps (icon.ico/png, header.bmp, welcome.bmp) are expected to already
exist in the plugin's packaging/ (Polygraph/Churn) — the renderer leaves them
in place and only warns if missing; CI derives icon.ico from icon.png for
plugins that lack it (Chasm).

Stdlib only. Usage:
    python3 tools/render_installer.py <name> [--plugin-dir DIR] [--check]

--check renders to a temp dir and asserts no @TOKEN@ survives (used by tests/CI
without touching a real plugin checkout).
"""
from __future__ import annotations

import argparse
import re
import shutil
import sys
import tempfile
from pathlib import Path

import manifest as mf

REPO_ROOT = mf.REPO_ROOT
TEMPLATES = REPO_ROOT / "templates"

TOKEN_RE = re.compile(r"@([A-Z_]+)@")
# ;@IF <FORMAT> ... ;@ENDIF  — the ;@ prefix keeps the template a valid NSIS
# comment so the raw .in file still lints as NSIS.
IF_RE = re.compile(r"^;@IF\s+(\w+)\s*$")
ENDIF_RE = re.compile(r"^;@ENDIF\s*$")


def _resolve_conditionals(text: str, enabled: set[str]) -> str:
    """Keep ;@IF FMT blocks only when FMT is in `enabled`; strip the markers."""
    out: list[str] = []
    stack: list[bool] = []  # each entry = "are we currently keeping lines?"
    for line in text.splitlines(keepends=True):
        stripped = line.strip()
        m_if = IF_RE.match(stripped)
        if m_if:
            fmt = m_if.group(1)
            keep = (fmt in enabled) and all(stack)
            stack.append(keep)
            continue
        if ENDIF_RE.match(stripped):
            if not stack:
                raise ValueError("unbalanced ;@ENDIF in template")
            stack.pop()
            continue
        if all(stack):  # empty stack -> all([]) is True -> unconditional lines kept
            out.append(line)
    if stack:
        raise ValueError("unclosed ;@IF in template")
    return "".join(out)


def _substitute(text: str, tokens: dict[str, str]) -> str:
    def repl(match: re.Match) -> str:
        key = match.group(1)
        if key not in tokens:
            # Leave unknown tokens intact so the guard below catches them.
            return match.group(0)
        return tokens[key]

    return TOKEN_RE.sub(repl, text)


def render_nsi(m: dict) -> str:
    src = (TEMPLATES / "installer.nsi.in").read_text()
    # Conditional-section keys = the Windows formats, plus PRESETS if the manifest
    # declares a [presets] table (its files are staged into packaging/presets/).
    enabled = set(m["formats"]["windows"])
    if m.get("presets", {}).get("source"):
        enabled.add("PRESETS")
    text = _resolve_conditionals(src, enabled)
    text = _substitute(text, mf.nsis_tokens(m))
    leftover = sorted(set(TOKEN_RE.findall(text)))
    if leftover:
        raise ValueError(
            f"unsubstituted tokens in rendered installer.nsi: "
            f"{', '.join('@%s@' % t for t in leftover)}"
        )
    return text


def write_tree(m: dict, plugin_dir: Path) -> list[Path]:
    """Render everything into plugin_dir/packaging. Returns files written."""
    pkg = plugin_dir / "packaging"
    (pkg / "resources").mkdir(parents=True, exist_ok=True)
    (pkg / "macos" / "resources").mkdir(parents=True, exist_ok=True)
    written: list[Path] = []

    nsi = pkg / "installer.nsi"
    nsi.write_text(render_nsi(m))
    written.append(nsi)

    for fn in ("EULA", "README"):
        for dest in (pkg / "resources" / fn, pkg / "macos" / "resources" / fn):
            shutil.copyfile(TEMPLATES / "resources" / fn, dest)
            written.append(dest)

    bpkg = pkg / "macos" / "build_pkg.sh"
    shutil.copyfile(TEMPLATES / "macos" / "build_pkg.sh", bpkg)
    bpkg.chmod(0o755)
    written.append(bpkg)

    # Stage factory presets (if declared) into packaging/presets/ so both the NSIS
    # SecPresets section and build_pkg.sh (which globs packaging/presets) find them.
    presets = m.get("presets", {})
    src_glob = presets.get("source")
    if src_glob:
        dest_dir = pkg / "presets"
        dest_dir.mkdir(parents=True, exist_ok=True)
        matches = sorted(plugin_dir.glob(src_glob))
        for src in matches:
            if src.is_file():
                shutil.copyfile(src, dest_dir / src.name)
                written.append(dest_dir / src.name)
        if not matches:
            print(f"  warn: preset glob matched nothing: {src_glob}", file=sys.stderr)

    # Warn (don't fail) on missing brand bitmaps — CI handles icon.ico synthesis
    # and placeholder fallback; a render should still succeed for --check runs.
    assets = m.get("assets", {})
    for key in ("icon_ico", "icon_png", "header_bmp", "welcome_bmp"):
        rel = assets.get(key)
        if rel and not (plugin_dir / rel).exists():
            print(f"  warn: brand asset missing: {rel} (CI will fall back)", file=sys.stderr)

    return written


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description="Render installer tree from a manifest")
    ap.add_argument("name", help="plugin manifest name (e.g. polygraph)")
    ap.add_argument("--plugin-dir", help="cloned plugin working dir")
    ap.add_argument("--check", action="store_true",
                    help="render to a temp dir and validate only")
    args = ap.parse_args(argv)

    m = mf.load(args.name)

    if args.check:
        with tempfile.TemporaryDirectory() as tmp:
            files = write_tree(m, Path(tmp))
            print(f"OK: {m['identity']['product_name']} rendered {len(files)} files, no unsubstituted tokens")
        return 0

    if args.plugin_dir:
        plugin_dir = Path(args.plugin_dir)
    else:
        plugin_dir = REPO_ROOT.parent / m["repo"]["name"]
    if not plugin_dir.exists():
        print(f"error: plugin dir not found: {plugin_dir}", file=sys.stderr)
        return 1

    files = write_tree(m, plugin_dir)
    print(f"Rendered {m['identity']['product_name']} -> {plugin_dir}/packaging")
    for f in files:
        print(f"  {f.relative_to(plugin_dir)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
