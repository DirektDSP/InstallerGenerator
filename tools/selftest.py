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
        except Exception as e:  # noqa: BLE001
            check(False, f"{n} renders: {e}")

    print("\n[3] Polygraph NSIS parity vs upstream")
    upstream = REPO.parent / "Polygraph" / "packaging" / "installer.nsi"
    if upstream.exists():
        rendered = ri.render_nsi(manifests["polygraph"])
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
            prod = m["identity"]["product_name"]
            (art / f"{comp}-{prod}-9.9.9-Windows.exe").write_bytes(b"x")
            (art / f"{comp}-{prod}-9.9.9-macOS.pkg").write_bytes(b"y")
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
        check(len(catalog["plugins"]) == len(manifests), "all plugins present in catalog")

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
