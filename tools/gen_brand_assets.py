#!/usr/bin/env python3
"""Render the generic DirektDSP installer brand assets from SVG source.

Source SVGs live in templates/assets/src/ (brand palette: paper #F4EFE2,
ink #1B1813, red #C8392B). This produces the committed, brand-neutral-to-any-
single-plugin house assets used as the fallback for every plugin that ships no
art of its own:

    templates/assets/icon.png     512x512  (also -> icon.ico in CI)
    templates/assets/header.bmp   150x57   24-bit  (MUI header)
    templates/assets/welcome.bmp  164x314  24-bit  (MUI welcome/finish panel)

Pipeline: rsvg-convert (SVG -> PNG) + a stdlib PNG->BMP converter (NSIS needs
24-bit uncompressed BMP; rsvg cannot emit BMP). No third-party Python deps.

Usage: python3 tools/gen_brand_assets.py
Requires rsvg-convert on PATH.
"""
from __future__ import annotations

import struct
import subprocess
import sys
import zlib
from pathlib import Path

ASSETS = Path(__file__).resolve().parent.parent / "templates" / "assets"
SRC = ASSETS / "src"


def rsvg_to_png(svg: Path, png: Path, w: int, h: int) -> None:
    subprocess.run(
        ["rsvg-convert", "-w", str(w), "-h", str(h), str(svg), "-o", str(png)],
        check=True,
    )


# --- minimal PNG reader (RGBA/RGB, 8-bit, no interlace) -----------------------
def _paeth(a: int, b: int, c: int) -> int:
    p = a + b - c
    pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
    return a if pa <= pb and pa <= pc else (b if pb <= pc else c)


def read_png_rgb(path: Path):
    d = path.read_bytes()
    assert d[:8] == b"\x89PNG\r\n\x1a\n", "not a PNG"
    w, h = struct.unpack(">II", d[16:24])
    bit_depth, color_type = d[24], d[25]
    assert bit_depth == 8 and color_type in (2, 6), "expect 8-bit RGB/RGBA"
    channels = 4 if color_type == 6 else 3
    i, idat = 8, b""
    while i < len(d):
        ln = struct.unpack(">I", d[i:i + 4])[0]
        typ = d[i + 4:i + 8]
        if typ == b"IDAT":
            idat += d[i + 8:i + 8 + ln]
        i += 12 + ln
    raw = zlib.decompress(idat)
    stride = w * channels
    out = bytearray(w * h * 3)  # RGB
    prev = bytearray(stride)
    pos = 0
    for y in range(h):
        f = raw[pos]; pos += 1
        line = bytearray(raw[pos:pos + stride]); pos += stride
        for x in range(stride):
            a = line[x - channels] if x >= channels else 0
            b = prev[x]
            c = prev[x - channels] if x >= channels else 0
            if f == 1: line[x] = (line[x] + a) & 255
            elif f == 2: line[x] = (line[x] + b) & 255
            elif f == 3: line[x] = (line[x] + ((a + b) >> 1)) & 255
            elif f == 4: line[x] = (line[x] + _paeth(a, b, c)) & 255
        for x in range(w):
            s = x * channels
            r, g, bb = line[s], line[s + 1], line[s + 2]
            if channels == 4:
                # composite over paper (#F4EFE2) using alpha
                al = line[s + 3]
                r = (r * al + 0xF4 * (255 - al)) // 255
                g = (g * al + 0xEF * (255 - al)) // 255
                bb = (bb * al + 0xE2 * (255 - al)) // 255
            o = (y * w + x) * 3
            out[o], out[o + 1], out[o + 2] = r, g, bb
        prev = line
    return w, h, out


def rgb_to_bmp(w: int, h: int, rgb: bytes, dest: Path) -> None:
    """Write a 24-bit uncompressed bottom-up BMP (BGR)."""
    row_pad = (-(w * 3)) % 4
    pixels = bytearray()
    for y in range(h - 1, -1, -1):  # bottom-up
        for x in range(w):
            o = (y * w + x) * 3
            pixels += bytes((rgb[o + 2], rgb[o + 1], rgb[o]))  # BGR
        pixels += b"\x00" * row_pad
    filesize = 14 + 40 + len(pixels)
    hdr = b"BM" + struct.pack("<IHHI", filesize, 0, 0, 14 + 40)
    info = struct.pack("<IiiHHIIiiII", 40, w, h, 1, 24, 0, len(pixels), 2835, 2835, 0, 0)
    dest.write_bytes(hdr + info + pixels)


def png_to_bmp(png: Path, bmp: Path) -> None:
    w, h, rgb = read_png_rgb(png)
    rgb_to_bmp(w, h, rgb, bmp)


def main() -> int:
    tmp = ASSETS / "_tmp"
    tmp.mkdir(exist_ok=True)
    try:
        # Icon: PNG straight out.
        rsvg_to_png(SRC / "icon.svg", ASSETS / "icon.png", 512, 512)
        # Header + welcome: PNG -> BMP.
        for name, w, h in (("header", 150, 57), ("welcome", 164, 314)):
            p = tmp / f"{name}.png"
            rsvg_to_png(SRC / f"{name}.svg", p, w, h)
            png_to_bmp(p, ASSETS / f"{name}.bmp")
        print("Generated:")
        for f in ("icon.png", "header.bmp", "welcome.bmp"):
            fp = ASSETS / f
            print(f"  {fp}  ({fp.stat().st_size} bytes)")
    finally:
        for f in tmp.glob("*"):
            f.unlink()
        tmp.rmdir()
    return 0


if __name__ == "__main__":
    if not __import__("shutil").which("rsvg-convert"):
        print("error: rsvg-convert not found on PATH", file=sys.stderr)
        raise SystemExit(1)
    raise SystemExit(main())
