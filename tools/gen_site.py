#!/usr/bin/env python3
"""Generate the static GitHub Pages download site from catalog.json.

Emits <out>/index.html — one card per plugin with per-OS download buttons,
version, description, format badges, and copyable SHA256s. The page fetches
nothing at runtime except the catalog it is generated from (also copied beside
it as catalog.json so the desktop app and the page share one source).

Design: brand-neutral, works light/dark, no external assets or JS frameworks.
Stdlib only (html.escape, json).

Usage:
    python3 tools/gen_site.py --catalog site/catalog.json --out site
"""
from __future__ import annotations

import argparse
import html
import json
import shutil
import sys
from pathlib import Path

OS_LABEL = {"windows": "Windows", "macos": "macOS", "linux": "Linux"}
OS_HINT = {"windows": ".exe installer", "macos": ".pkg installer", "linux": ".zip"}

PAGE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{publisher} — Plugin Downloads</title>
<style>
  :root {{
    --bg: #0f1115; --card: #171a21; --fg: #e6e9ef; --muted: #9aa3b2;
    --accent: #5b9dff; --border: #262b36; --badge: #222834;
  }}
  @media (prefers-color-scheme: light) {{
    :root {{ --bg:#f6f7f9; --card:#fff; --fg:#12151b; --muted:#5a6472;
             --accent:#1e66f5; --border:#e2e6ec; --badge:#eef1f5; }}
  }}
  * {{ box-sizing: border-box; }}
  body {{ margin:0; background:var(--bg); color:var(--fg);
    font:16px/1.5 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Helvetica,Arial,sans-serif; }}
  header {{ max-width:960px; margin:0 auto; padding:48px 24px 8px; }}
  h1 {{ font-size:28px; margin:0 0 4px; }}
  header p {{ color:var(--muted); margin:0; }}
  main {{ max-width:960px; margin:0 auto; padding:24px; display:grid; gap:20px; }}
  .card {{ background:var(--card); border:1px solid var(--border); border-radius:14px; padding:22px 24px; }}
  .card h2 {{ margin:0 0 2px; font-size:20px; }}
  .ver {{ color:var(--muted); font-weight:400; font-size:14px; }}
  .desc {{ color:var(--muted); margin:6px 0 14px; }}
  .badges {{ display:flex; flex-wrap:wrap; gap:6px; margin-bottom:16px; }}
  .badge {{ background:var(--badge); border:1px solid var(--border); border-radius:999px;
    padding:2px 10px; font-size:12px; color:var(--fg); }}
  .dl {{ display:flex; flex-wrap:wrap; gap:10px; }}
  a.btn {{ text-decoration:none; background:var(--accent); color:#fff; padding:9px 16px;
    border-radius:9px; font-weight:600; font-size:14px; display:inline-flex; flex-direction:column; }}
  a.btn small {{ font-weight:400; opacity:.85; font-size:11px; }}
  .sums {{ margin-top:14px; font-size:12px; color:var(--muted); }}
  .sums code {{ font-size:11px; word-break:break-all; }}
  details summary {{ cursor:pointer; }}
  footer {{ max-width:960px; margin:0 auto; padding:16px 24px 60px; color:var(--muted); font-size:13px; }}
  footer code {{ font-size:12px; }}
</style>
</head>
<body>
<header>
  <h1>{publisher} — Plugin Downloads</h1>
  <p>{count} plugin(s) · generated {generated_at} · <a href="catalog.json">catalog.json</a></p>
</header>
<main>
{cards}
</main>
<footer>
  <p>All installers are code-verifiable: each download has a SHA256 checksum in
  <a href="catalog.json"><code>catalog.json</code></a>, the machine-readable index
  a desktop bulk-installer can read to install every plugin you own at once.</p>
</footer>
</body>
</html>
"""

CARD = """  <section class="card">
    <h2>{name} <span class="ver">v{version}</span></h2>
    <div class="desc">{description}</div>
    <div class="badges">{badges}</div>
    <div class="dl">{buttons}</div>
    <div class="sums"><details><summary>Checksums (SHA256)</summary>{sums}</details></div>
  </section>"""


def render_card(p: dict) -> str:
    badges = "".join(
        f'<span class="badge">{html.escape(f)}</span>' for f in p.get("formats", [])
    )
    buttons = []
    sums = []
    for os_key in ("windows", "macos", "linux"):
        art = p.get("installers", {}).get(os_key)
        if not art:
            continue
        buttons.append(
            f'<a class="btn" href="{html.escape(art["url"])}">'
            f'{OS_LABEL[os_key]}<small>{OS_HINT[os_key]}</small></a>'
        )
        sums.append(
            f'<div>{OS_LABEL[os_key]}: <code>{html.escape(art["sha256"])}</code></div>'
        )
    return CARD.format(
        name=html.escape(p["name"]),
        version=html.escape(p["version"]),
        description=html.escape(p.get("description", "")),
        badges=badges,
        buttons="".join(buttons) or "<em>No installers published yet.</em>",
        sums="".join(sums),
    )


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description="Generate download site from catalog.json")
    ap.add_argument("--catalog", required=True, type=Path)
    ap.add_argument("--out", required=True, type=Path)
    args = ap.parse_args(argv)

    catalog = json.loads(args.catalog.read_text())
    args.out.mkdir(parents=True, exist_ok=True)
    cards = "\n".join(render_card(p) for p in catalog["plugins"])
    page = PAGE.format(
        publisher=html.escape(catalog.get("publisher", "DirektDSP")),
        count=len(catalog["plugins"]),
        generated_at=html.escape(catalog.get("generated_at", "")),
        cards=cards,
    )
    (args.out / "index.html").write_text(page)
    # Keep catalog.json beside the page so the site and the desktop app share one.
    if args.catalog.resolve() != (args.out / "catalog.json").resolve():
        shutil.copyfile(args.catalog, args.out / "catalog.json")
    print(f"Wrote {args.out}/index.html ({len(catalog['plugins'])} plugin cards)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
