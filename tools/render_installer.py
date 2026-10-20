#!/usr/bin/env python3
"""Render a plugin manifest into a ready-to-compile installer tree.

Writes, into the cloned plugin's working dir (default: DirektDSP/<Name> beside
this repo, or --plugin-dir):

    packaging/installer.nsi          (from templates/installer.nsi.in)
    packaging/resources/EULA         (shared)
    packaging/resources/README       (shared)
    packaging/macos/build_pkg.sh     (shared, format-adaptive)
    packaging/macos/resources/{EULA,README}
    packaging/macos/standalone.entitlements  (shared, hardened runtime)

Brand bitmaps (icon.ico/png, header.bmp, welcome.bmp) are expected to already
exist in the plugin's packaging/ (Polygraph/Churn) — the renderer leaves them
in place and only warns if missing; CI derives icon.ico from icon.png for
plugins that lack it (Chasm).

Stdlib only. Usage:
    python3 tools/render_installer.py <name> [--plugin-dir DIR] [--check]
    python3 tools/render_installer.py <name> --linux-readme PATH

--check renders to a temp dir and asserts no @TOKEN@ survives (used by tests/CI
without touching a real plugin checkout).
"""
from __future__ import annotations

import argparse
import re
import shutil
import sys
import tempfile
from pathlib import Path, PurePosixPath

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


# ;@RUNTIME install <clap|standalone>
# ;@RUNTIME remove  <clap|standalone> "<install dir>"
# Expands to one NSIS line per [runtime_files].windows entry (or to nothing when the
# manifest has none, so such plugins render exactly as before). Files and
# directories are staged by CI under ARTIFACTS_DIR\clap and ARTIFACTS_DIR\standalone.
RUNTIME_RE = re.compile(r'^(\s*);@RUNTIME\s+(install|remove)\s+(clap|standalone)(?:\s+(".*"))?\s*$')


def _expand_runtime(text: str, m: dict) -> str:
    entries = [mf.runtime_entry(e) for e in mf.runtime_files(m, "windows")]
    out: list[str] = []
    for line in text.splitlines(keepends=True):
        match = RUNTIME_RE.match(line.rstrip("\r\n"))
        if not match:
            out.append(line)
            continue
        indent, action, kind, dest = match.groups()
        nl = "\n" if line.endswith("\n") else ""
        if action == "remove" and not dest:
            raise ValueError(";@RUNTIME remove needs a quoted install dir")
        for name, is_dir in entries:
            if action == "install":
                # /nonfatal for both: an older plugin tag that predates the runtime
                # copy must still build an installer (the CI collect step warns).
                # Directories take /r (no trailing \*, so they land as a subdirectory
                # of the same name); plain files stay non-recursive.
                recurse = " /r" if is_dir else ""
                out.append(f'{indent}File /nonfatal{recurse} "${{ARTIFACTS_DIR}}\\{kind}\\{name}"{nl}')
            elif is_dir:
                out.append(f'{indent}RMDir /r "{dest[1:-1]}\\{name}"{nl}')
            else:
                out.append(f'{indent}Delete "{dest[1:-1]}\\{name}"{nl}')
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
    text = _expand_runtime(text, m)
    leftover = sorted(set(TOKEN_RE.findall(text)))
    if leftover:
        raise ValueError(
            f"unsubstituted tokens in rendered installer.nsi: "
            f"{', '.join('@%s@' % t for t in leftover)}"
        )
    return text


def render_linux_readme(m: dict) -> str:
    """LINUX-INSTALL.txt for the Linux zip (only meaningful with [runtime_files].linux)."""
    text = (TEMPLATES / "linux" / "LINUX-INSTALL.txt.in").read_text()
    text = _substitute(text, mf.linux_tokens(m))
    leftover = sorted(set(TOKEN_RE.findall(text)))
    if leftover:
        raise ValueError(
            f"unsubstituted tokens in LINUX-INSTALL.txt: "
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

    # Hardened-runtime entitlements for the Standalone .app. build_pkg.sh only
    # applies them when MACOS_ENTITLEMENTS points here, so staging is harmless
    # for plugins with no Standalone target.
    ents = pkg / "macos" / "standalone.entitlements"
    shutil.copyfile(TEMPLATES / "macos" / "standalone.entitlements", ents)
    written.append(ents)

    # Stage factory presets (if declared) into packaging/presets/ so both the NSIS
    # SecPresets section and build_pkg.sh (which globs packaging/presets) find them.
    presets = m.get("presets", {})
    src_glob = presets.get("source")
    if src_glob:
        dest_dir = pkg / "presets"
        dest_dir.mkdir(parents=True, exist_ok=True)

        # Preserve any directory structure BELOW the fixed part of the glob, so a
        # categorised bank (Sibyl: assets/stock_presets/<Category>/<name>.ddsp)
        # survives staging instead of collapsing into one flat folder. The base
        # is the longest wildcard-free prefix of the glob; for a flat pattern
        # like "presets/*.pp" that leaves the relative path a bare filename, so
        # existing plugins stage exactly as before.
        base = plugin_dir
        for part in PurePosixPath(src_glob).parts:
            if any(ch in part for ch in "*?["):
                break
            base = base / part

        matches = sorted(plugin_dir.glob(src_glob))
        for src in matches:
            if not src.is_file():
                continue
            try:
                rel = src.relative_to(base)
            except ValueError:
                rel = Path(src.name)
            dest = dest_dir / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(src, dest)
            written.append(dest)
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
    ap.add_argument("--linux-readme", metavar="PATH",
                    help="write only LINUX-INSTALL.txt to PATH (for the Linux zip) and exit")
    ap.add_argument("--check", action="store_true",
                    help="render to a temp dir and validate only")
    args = ap.parse_args(argv)

    m = mf.load(args.name)

    if args.linux_readme:
        if not mf.runtime_files(m, "linux"):
            print("error: manifest has no [runtime_files].linux; no README needed", file=sys.stderr)
            return 1
        Path(args.linux_readme).write_text(render_linux_readme(m))
        print(f"Wrote {args.linux_readme}")
        return 0

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
