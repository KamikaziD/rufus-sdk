#!/usr/bin/env python3
"""Generate icon-192.png and icon-512.png from icon.svg.

Requires: pip install cairosvg
Run from the icons/ directory or repo root.
"""
import pathlib, sys

ICONS_DIR = pathlib.Path(__file__).parent

def main():
    try:
        import cairosvg
    except ImportError:
        print("cairosvg not found — install with: pip install cairosvg", file=sys.stderr)
        sys.exit(1)

    svg_path = ICONS_DIR / "icon.svg"
    for size in (192, 512):
        out = ICONS_DIR / f"icon-{size}.png"
        cairosvg.svg2png(url=str(svg_path), write_to=str(out),
                         output_width=size, output_height=size)
        print(f"Generated {out}")

if __name__ == "__main__":
    main()
