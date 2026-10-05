"""Recorta um template a partir de um screenshot de referência.

Uso:
    python scripts/crop_template.py data/screenshots/capture_123.png btn_ok 200 800 140 50
            (arquivo, nome do template, x, y, largura, altura)
"""
import sys
from pathlib import Path

from PIL import Image

TEMPLATES = Path(__file__).resolve().parent.parent / "ptcgp_bot" / "vision" / "templates"

if __name__ == "__main__":
    if len(sys.argv) != 7:
        print(__doc__)
        sys.exit(1)
    src, name, x, y, w, h = sys.argv[1], sys.argv[2], *map(int, sys.argv[3:])
    img = Image.open(src).crop((x, y, x + w, y + h))
    out = TEMPLATES / f"{name}.png"
    img.save(out)
    print(f"template salvo em {out} ({w}x{h})")
