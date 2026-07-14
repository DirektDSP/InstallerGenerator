# Generic DirektDSP installer brand assets

The committed **DirektDSP house** installer assets, used as the fallback for any
plugin that ships no art of its own:

- `icon.png` (512×512) — plugin `ICON_BIG` + source for the Windows `icon.ico`
- `header.bmp` (150×57, 24-bit) — MUI installer header strip
- `welcome.bmp` (164×314, 24-bit) — MUI welcome / finish side panel

They use the DirektDSP palette (paper `#F4EFE2`, ink `#1B1813`, red `#C8392B`)
and the brand marks — deliberately tied to **no single plugin**:

- **wordmark** — "Direkt" in Magneto Bold, as traced vector paths (from
  `SpiceRack/assets/direktdsp-wordmark.svg`; no font needed to render)
- **lettermark** — the Magneto "D" glyph isolated from the same trace
- **captions** — Outfit (Google Fonts, OFL); install it locally before
  regenerating (`~/.local/share/fonts` + `fc-cache`) or the text falls back

## Regenerate

Source SVGs are in `src/`. Rendered with `rsvg-convert` + a stdlib PNG→BMP step:

```
python3 tools/gen_brand_assets.py    # needs rsvg-convert on PATH
```

## Rule

A plugin that wants its OWN installer art commits `header.bmp` / `welcome.bmp` /
`icon.png` to its repo's `packaging/`; CI uses those and only falls back to these
house assets for whatever is missing. Never copy one plugin's art into another —
cross-plugin bitmap bleed is the class of bug this project exists to eliminate.
