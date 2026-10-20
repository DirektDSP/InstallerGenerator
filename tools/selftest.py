#!/usr/bin/env python3
"""End-to-end self-test for the InstallerGenerator tooling (stdlib only).

Runs without a real plugin checkout or makensis:
  1. every manifest loads + validates
  2. every manifest renders with no unsubstituted @TOKEN@
  3. rendered Polygraph NSIS matches the upstream hand-written script on every
     functional (non-comment) line — proves the template is faithful
  4. a synthetic catalog builds and validates against the schema
  5. the site generates

Exit 0 = all pass.
"""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import build_catalog as bc  # noqa: E402
import manifest as mf  # noqa: E402
import render_installer as ri  # noqa: E402
import validate_catalog as vc  # noqa: E402

REPO = mf.REPO_ROOT
FAILS: list[str] = []


def check(cond: bool, msg: str):
    print(("  ok  " if cond else " FAIL ") + msg)
    if not cond:
        FAILS.append(msg)


def functional_lines(text: str) -> list[str]:
    """Non-blank, non-comment NSIS lines (drop ; comments) for parity compare."""
    out = []
    for ln in text.splitlines():
        s = ln.strip()
        if not s or s.startswith(";"):
            continue
        out.append(s)
    return out


def main() -> int:
    names = sorted(p.stem for p in mf.PLUGINS_DIR.glob("*.toml"))
    print(f"manifests: {names}")

    print("\n[1] load + validate manifests")
    manifests = {}
    for n in names:
        try:
            manifests[n] = mf.load(n)
            check(True, f"{n} loads")
        except Exception as e:  # noqa: BLE001
            check(False, f"{n} loads: {e}")

    print("\n[2] render with no unsubstituted tokens")
    for n, m in manifests.items():
        try:
            nsi = ri.render_nsi(m)  # raises if any @TOKEN@ survives
            check(_tokens(nsi) == "", f"{n} renders clean (no @TOKEN@)")
            # Presets section present iff the manifest declares [presets].source.
            has_presets = bool(m.get("presets", {}).get("source"))
            has_section = "SecPresets" in nsi
            check(has_presets == has_section,
                  f"{n} preset section {'present' if has_presets else 'absent'} as expected")
        except Exception as e:  # noqa: BLE001
            check(False, f"{n} renders: {e}")

    print("\n[2b] synthetic PRESETS conditional")
    try:
        pm = dict(manifests[names[0]])
        pm["presets"] = {"source": "assets/presets/*.pp"}
        nsi = ri.render_nsi(pm)
        check("SecPresets" in nsi and "$COMMONDOCUMENTS" in nsi,
              "PRESETS conditional emits SecPresets + COMMONDOCUMENTS path")
    except Exception as e:  # noqa: BLE001
        check(False, f"synthetic presets render: {e}")

    print("\n[2d] [runtime_files] -> NSIS sections / Linux notes / CI outputs")
    try:
        rt = {"windows": ["onnxruntime.dll", "Licenses"], "linux": ["libonnxruntime.so.1.23.2", "Licenses"]}
        base = dict(manifests["polygraph"])
        base.pop("runtime_files", None)
        base["_runtime_files"] = {}
        withrt = dict(base)
        withrt["runtime_files"] = rt
        withrt["_runtime_files"] = rt

        # Without the table: every directive vanishes and the output is exactly
        # the template with the ;@RUNTIME lines deleted (i.e. what rendered before).
        src = (ri.TEMPLATES / "installer.nsi.in").read_text()
        legacy = "".join(l for l in src.splitlines(keepends=True) if ";@RUNTIME" not in l)
        for n, m in manifests.items():
            if mf.runtime_files(m, "windows"):
                continue
            old_style = ri._substitute(
                ri._resolve_conditionals(
                    legacy,
                    set(m["formats"]["windows"]) | ({"PRESETS"} if m.get("presets", {}).get("source") else set()),
                ),
                mf.nsis_tokens(m),
            )
            check(ri.render_nsi(m).encode() == old_style.encode(),
                  f"{n} (no [runtime_files]) renders byte-identical to the pre-feature template")
        check(ri.render_nsi(base) != ri.render_nsi(withrt), "runtime_files changes the render")
        check(not mf.runtime_files(manifests["sift"], "windows"), "sift declares no runtime files")

        nsi = ri.render_nsi(withrt)
        for want in (
            'File /nonfatal "${ARTIFACTS_DIR}\\clap\\onnxruntime.dll"',
            'File /nonfatal /r "${ARTIFACTS_DIR}\\clap\\Licenses"',
            'File /nonfatal "${ARTIFACTS_DIR}\\standalone\\onnxruntime.dll"',
            'File /nonfatal /r "${ARTIFACTS_DIR}\\standalone\\Licenses"',
            'Delete "$COMMONFILES64\\CLAP\\DirektDSP\\onnxruntime.dll"',
            'RMDir /r "$COMMONFILES64\\CLAP\\DirektDSP\\Licenses"',
            'Delete "$INSTDIR\\onnxruntime.dll"',
            'RMDir /r "$INSTDIR\\Licenses"',
        ):
            check(want in nsi, f"NSIS has: {want}")
        # Install lines must sit inside their section, uninstall lines before the RMDir.
        lines = [l.strip() for l in nsi.splitlines()]
        def idx(prefix, start=0):
            return next(i for i in range(start, len(lines)) if lines[i].startswith(prefix))
        clap0 = idx('Section "Polygraph CLAP"'); clap1 = idx("SectionEnd", clap0)
        sa0 = idx('Section /o "Polygraph Standalone"'); sa1 = idx("SectionEnd", sa0)
        check(clap0 < idx("File /nonfatal \"${ARTIFACTS_DIR}\\clap\\onnx", clap0) < clap1,
              "CLAP runtime files installed inside the CLAP section")
        check(sa0 < idx("File /nonfatal \"${ARTIFACTS_DIR}\\standalone\\onnx", sa0) < sa1,
              "Standalone runtime files installed inside the Standalone section")
        check(idx('RMDir /r "$COMMONFILES64\\CLAP') < idx('RMDir "$COMMONFILES64\\CLAP'),
              "CLAP runtime dir removed before the CLAP folder RMDir")
        check(idx('RMDir /r "$INSTDIR\\Licenses"') < idx('RMDir "$INSTDIR"'),
              "Standalone runtime dir removed before the INSTDIR RMDir")
        check("@RUNTIME" not in nsi, "no ;@RUNTIME marker survives in the rendered NSIS")

        # No CLAP / Standalone format -> no runtime lines.
        nof = dict(withrt)
        nof["formats"] = {**withrt["formats"], "windows": ["VST3"]}
        check("onnxruntime" not in ri.render_nsi(nof), "runtime lines follow the CLAP/Standalone gates")

        # Linux notes + CI outputs.
        txt = ri.render_linux_readme(withrt)
        check("libonnxruntime.so.1.23.2, Licenses" in txt and "/usr/lib/direktdsp/polygraph/" in txt
              and "@" not in txt, "LINUX-INSTALL.txt renders (runtime list + shared dir, no tokens)")
        import manifest_ci as mci  # noqa: PLC0415
        out = dict(l.split("=", 1) for l in mci.github_output("polygraph").splitlines())
        check(out["windows_runtime_files"] == "onnxruntime.dll Licenses"
              and out["linux_runtime_files"] == "libonnxruntime.so.1.23.2 Licenses",
              "manifest_ci exposes windows_/linux_runtime_files for polygraph")
        out = dict(l.split("=", 1) for l in mci.github_output("sift").splitlines())
        check(out["windows_runtime_files"] == "" and out["linux_runtime_files"] == "",
              "manifest_ci runtime outputs are empty for a plugin without the table")

        # Validation.
        for bad, label in (
            ({"windows": ["../x.dll"]}, "path traversal"),
            ({"windows": ["a b.dll"]}, "whitespace"),
            ({"windows": ["*.dll"]}, "glob"),
            ({"windows": ["x.dll", "x.dll"]}, "duplicate"),
            ({"macos": ["x"]}, "unsupported OS key"),
            ({"linux": "x"}, "non-list"),
        ):
            try:
                mf._validate_runtime_files(bad, "t")
                check(False, f"manifest rejects {label}")
            except mf.ManifestError:
                check(True, f"manifest rejects {label}")
        check(mf.runtime_entry("Licenses") == ("Licenses", True)
              and mf.runtime_entry("onnxruntime.dll") == ("onnxruntime.dll", False)
              and mf.runtime_entry("data.d/") == ("data.d", True),
              "runtime_entry classifies dirs vs files")
    except Exception as e:  # noqa: BLE001
        check(False, f"runtime_files checks: {e!r}")

    print("\n[2c] write_tree stages the shared macOS packaging files")
    with tempfile.TemporaryDirectory() as tmp:
        try:
            written = ri.write_tree(manifests[names[0]], Path(tmp))
            rel = {p.relative_to(Path(tmp) / "packaging").as_posix() for p in written}
            for want in ("macos/build_pkg.sh", "macos/standalone.entitlements",
                         "macos/resources/EULA", "macos/resources/README"):
                check(want in rel and (Path(tmp) / "packaging" / want).is_file(),
                      f"write_tree stages {want}")
            ents = (Path(tmp) / "packaging" / "macos" / "standalone.entitlements").read_text()
            check("com.apple.security.device.audio-input" in ents,
                  "standalone.entitlements carries the audio-input entitlement")
        except Exception as e:  # noqa: BLE001
            check(False, f"write_tree: {e}")

    print("\n[3] Polygraph NSIS parity vs upstream")
    upstream = REPO.parent / "Polygraph" / "packaging" / "installer.nsi"
    if upstream.exists():
        # The upstream script predates [runtime_files]; compare the base layout
        # (the runtime lines are covered by [2d]).
        pg = dict(manifests["polygraph"])
        pg["_runtime_files"] = {}
        pg["runtime_files"] = {}
        rendered = ri.render_nsi(pg)
        up = functional_lines(upstream.read_text())
        rn = functional_lines(rendered)
        # Two intentional improvements over the hand-written upstream:
        #  1. welcome-page text is manifest-driven (reworded) — drop that line.
        #  2. brand-asset paths are prefixed with ${__FILEDIR__}\ for cwd-safety —
        #     strip that prefix before comparing so any OTHER drift still fails.
        def norm(lines):
            out = []
            for l in lines:
                if "MUI_WELCOMEPAGE_TEXT" in l:
                    continue
                out.append(l.replace('"${__FILEDIR__}\\', '"'))
            return out
        up_f, rn_f = norm(up), norm(rn)
        check(up_f == rn_f, "every functional line matches upstream (modulo intended fixes)")
        if up_f != rn_f:
            _print_line_diff(up_f, rn_f)
    else:
        check(True, f"upstream not present locally ({upstream}) — skipped")

    print("\n[4] catalog build + schema validation")
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        art = tmp / "art"
        art.mkdir()
        for m in manifests.values():
            comp = m["identity"]["company_name"]
            # Distributable filenames use the space-free slug (matches the
            # installers the workflow actually produces).
            slug = mf.product_slug(m["identity"]["product_name"])
            (art / f"{comp}-{slug}-9.9.9-Windows.exe").write_bytes(b"x")
            (art / f"{comp}-{slug}-9.9.9-macOS.pkg").write_bytes(b"y")
        catalog = bc.build_catalog(
            list(manifests.keys()), art,
            "https://example.com/{repo}/{version}/{filename}",
            "2026-07-06T00:00:00Z",
        )
        catf = tmp / "catalog.json"
        catf.write_text(json.dumps(catalog, indent=2))
        schema = json.loads((REPO / "schema" / "catalog.schema.json").read_text())
        v = vc.V(schema)
        v.check(catalog, schema)
        check(not v.errors, "catalog validates against schema")
        for e in v.errors:
            print("      " + e)

        public = {n for n, m in manifests.items() if mf.is_public(m)}
        embargoed = set(manifests) - public
        check(len(catalog["plugins"]) == len(public),
              f"every public plugin in catalog ({len(public)} public, "
              f"{len(embargoed)} embargoed)")

        print("\n[4b] embargo gate")
        # The site renders only from the catalog, so absent here == absent there.
        cat_slugs = {p["slug"] for p in catalog["plugins"]}
        leaked = sorted(cat_slugs & embargoed)
        check(not leaked, f"no embargoed plugin in catalog{': ' + ', '.join(leaked) if leaked else ''}")
        check(cat_slugs == public, "catalog slugs == public manifests")

        # An unflagged manifest must default to hidden, not exposed.
        unflagged = {k: v for k, v in manifests[names[0]].items() if k != "release"}
        unflagged.pop("_release_status", None)
        check(not mf.is_public(unflagged), "manifest with no [release] flag defaults to embargoed")

        # ...and the binaries must be pruned, not merely unlisted.
        import embargo as emb  # noqa: PLC0415

        def owner(filename: str) -> str | None:
            """Which manifest does this synthetic artifact belong to?"""
            for n, m in manifests.items():
                s = mf.product_slug(m["identity"]["product_name"])
                if f"-{s}-" in filename or filename.startswith(f"{s}-"):
                    return n
            return None

        before = {p.name for p in art.iterdir()}
        check(all(owner(n) for n in before), "every seeded artifact maps to a manifest")
        emb.prune(art)
        after = {p.name for p in art.iterdir()}

        # One Windows + one macOS seeded per manifest, so the split is exact —
        # catches over- and under-pruning alike.
        check({owner(n) for n in after} == public,
              "exactly the public plugins' installers survive the prune")
        check({owner(n) for n in before - after} == embargoed,
              "exactly the embargoed plugins' installers were pruned")
        check(len(after) == 2 * len(public), f"{2 * len(public)} artifacts left")

        print("\n[5] site generation")
        r = subprocess.run(
            [sys.executable, str(REPO / "tools" / "gen_site.py"),
             "--catalog", str(catf), "--out", str(tmp / "site")],
            capture_output=True, text=True,
        )
        check(r.returncode == 0 and (tmp / "site" / "index.html").exists(),
              "site index.html generated")
        if r.returncode != 0:
            print(r.stderr)

    print()
    if FAILS:
        print(f"SELFTEST FAILED: {len(FAILS)} check(s)")
        return 1
    print("SELFTEST PASSED")
    return 0


def _tokens(text: str) -> str:
    import re
    return "".join(re.findall(r"@[A-Z_]+@", text))


def _print_line_diff(a: list[str], b: list[str]):
    import difflib
    for line in difflib.unified_diff(a, b, "upstream", "rendered", lineterm=""):
        print("      " + line)


if __name__ == "__main__":
    raise SystemExit(main())
