"""Write the logo and browser-tab icon for each color theme (v0.35.2).

The coin in frontend/public/logo.svg, recolored per theme, as
frontend/public/logo-<theme>.svg, plus favicon-<theme>.ico (16, 32, 48, and
64 pixels). logo.svg and favicon.ico stay Bronze: they are what a browser
shows before the app has loaded, and what the README and a Homepage tile
link to. The theme keys must match frontend/src/themes.ts.

Needs rsvg-convert and ImageMagick; the one-liner in frontend/README.md runs
it in a throwaway Alpine container.
"""

import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

PUBLIC = Path(__file__).resolve().parents[1] / "frontend" / "public"
SIZES = (16, 32, 48, 64)

# rim, reeding, face, inner ring, the C
THEMES = {
    "bronze": ("#8a6a2f", "#5e4716", "#d2ae66", "#a5843f", "#3a2c10"),
    "silver": ("#6f7780", "#474e56", "#d5dade", "#98a0a9", "#2b3138"),
    "album": ("#7a6324", "#4f3f12", "#c9a755", "#9c8133", "#1d3a2e"),
    "ledger": ("#2b2b29", "#111111", "#ebe8df", "#8d8a82", "#7d2e2e"),
}

TEMPLATE = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64" role="img" aria-label="Cabinet">
  <circle cx="32" cy="32" r="30" fill="{0}"/>
  <circle cx="32" cy="32" r="28.2" fill="none" stroke="{1}" stroke-width="3.6" stroke-dasharray="1.7 1.7"/>
  <circle cx="32" cy="32" r="26" fill="{2}"/>
  <circle cx="32" cy="32" r="21.5" fill="none" stroke="{3}" stroke-width="1.4"/>
  <path d="M39.4 23.2A11.5 11.5 0 1 0 39.4 40.8" fill="none" stroke="{4}" stroke-width="6.5" stroke-linecap="round"/>
</svg>
"""


def main() -> None:
    for tool in ("rsvg-convert", "magick"):
        if not shutil.which(tool):
            sys.exit(f"{tool} is needed; see frontend/README.md for the container one-liner")
    for theme, colors in THEMES.items():
        svg = PUBLIC / f"logo-{theme}.svg"
        svg.write_text(TEMPLATE.format(*colors))
        with tempfile.TemporaryDirectory() as tmp:
            pngs = []
            for size in SIZES:
                png = Path(tmp) / f"{size}.png"
                subprocess.run(
                    ["rsvg-convert", "-w", str(size), "-h", str(size), str(svg), "-o", str(png)],
                    check=True,
                )
                pngs.append(str(png))
            subprocess.run(["magick", *pngs, str(PUBLIC / f"favicon-{theme}.ico")], check=True)
        print(f"logo-{theme}.svg, favicon-{theme}.ico")


if __name__ == "__main__":
    main()
