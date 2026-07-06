#!/usr/bin/env python3
"""Generate NEUTRAL, brand-free placeholder NSIS bitmaps (stdlib only).

Purpose: a plugin that ships no header.bmp/welcome.bmp (e.g. Chasm, which used
Inno Setup and only has icon.png) still needs *some* MUI bitmap so makensis
succeeds. We deliberately do NOT fall back to another plugin's branded art —
that is exactly the cross-plugin bleed this project exists to kill. Instead we
emit plain solid-colour BMPs at the exact dimensions MUI2 expects:

    header.bmp   150 x 57   (MUI_HEADERIMAGE_BITMAP)
    welcome.bmp  164 x 314  (MUI_WELCOMEFINISHPAGE_BITMAP)

24-bit uncompressed BGR, bottom-up — the format NSIS accepts. No dependencies.

Usage:
    python3 tools/gen_placeholder_assets.py <out-dir> [--only header|welcome]
"""
from __future__ import annotations

import argparse
import struct
import sys
from pathlib import Path

# A neutral dark slate; readable behind MUI's white text, tied to no brand.
FILL = (0x20, 0x24, 0x2B)  # R, G, B


def write_bmp(path: Path, width: int, height: int, rgb: tuple[int, int, int]) -> None:
    r, g, b = rgb
    row = bytes((b, g, r)) * width            # BGR per pixel
    pad = (-len(row)) % 4                       # rows padded to 4-byte boundary
    row = row + b"\x00" * pad
    pixels = row * height                       # bottom-up is fine for a solid fill
    filesize = 14 + 40 + len(pixels)
    fileheader = b"BM" + struct.pack("<IHHI", filesize, 0, 0, 14 + 40)
    infoheader = struct.pack(
        "<IiiHHIIiiII",
        40, width, height, 1, 24, 0, len(pixels), 2835, 2835, 0, 0,
    )
    path.write_bytes(fileheader + infoheader + pixels)


SPECS = {"header": (150, 57), "welcome": (164, 314)}


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("out", type=Path)
    ap.add_argument("--only", choices=SPECS.keys())
    args = ap.parse_args(argv)
    args.out.mkdir(parents=True, exist_ok=True)
    which = [args.only] if args.only else list(SPECS)
    for name in which:
        w, h = SPECS[name]
        dest = args.out / f"{name}.bmp"
        write_bmp(dest, w, h, FILL)
        print(f"wrote {dest} ({w}x{h})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
