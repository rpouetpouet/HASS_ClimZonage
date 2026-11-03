#!/usr/bin/env python3
"""Génère les visuels de marque de l'intégration clim_zonage.

Dessin maison : un toit avec une flamme (symbole de chauffage), pas d'image
tierce — donc aucune licence ni attribution à porter dans un dépôt public.

Sortie dans custom_components/clim_zonage/brand/ :
    icon.png            256×256
    icon@2x.png         512×512
    dark_icon.png       256×256   (variante thème sombre : maison claire)
    dark_icon@2x.png    512×512
    logo.png            512×256   (côté court 256, conforme à la spec)
    dark_logo.png       512×256

Spéc : PNG transparent RGBA, contenu centré. On dessine en 4× puis on réduit
en LANCZOS (anti-aliasing propre sans dépendance externe).
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw

S = 4  # facteur de suréchantillonnage
OUT = Path(__file__).resolve().parents[1] / "custom_components" / "clim_zonage" / "brand"

# Palette : la maison change de teinte selon le thème, la flamme reste identique.
LIGHT = {
    "house": (55, 71, 79, 255),      # bleu-gris foncé, lisible sur fond clair
    "flame_outer": (216, 74, 20, 255),
    "flame_mid": (243, 137, 43, 255),
    "flame_core": (255, 224, 102, 255),
}
DARK = {
    "house": (207, 216, 220, 255),   # gris très clair, lisible sur fond sombre
    "flame_outer": (216, 74, 20, 255),
    "flame_mid": (243, 137, 43, 255),
    "flame_core": (255, 224, 102, 255),
}


def draw_icon(colours: dict, size: int, supersample: int = S) -> Image.Image:
    """Dessine le pictogramme dans un carré de `size` px."""
    canvas = size * supersample
    img = Image.new("RGBA", (canvas, canvas), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)

    u = canvas / 100.0  # unité = 1 % du côté, pour des coordonnées lisibles

    # ─── maison : toit + corps ───
    roof = [(8 * u, 50 * u), (50 * u, 14 * u), (92 * u, 50 * u),
            (84 * u, 50 * u), (50 * u, 23 * u), (16 * u, 50 * u)]
    d.polygon(roof, fill=colours["house"])
    d.rectangle([24 * u, 50 * u, 76 * u, 88 * u], fill=colours["house"])

    # ─── flamme : trois tailles emboîtées ───
    def flame(cx: float, base_y: float, height: float, width: float, fill) -> None:
        h, w = height, width
        pts = [
            (cx, base_y - h),                       # pointe
            (cx + w * 0.42, base_y - h * 0.55),
            (cx + w * 0.50, base_y - h * 0.22),
            (cx + w * 0.30, base_y),                # bas droite
            (cx, base_y - h * 0.06),                # creux central
            (cx - w * 0.30, base_y),                # bas gauche
            (cx - w * 0.50, base_y - h * 0.22),
            (cx - w * 0.42, base_y - h * 0.55),
        ]
        d.polygon(pts, fill=fill)

    flame(50 * u, 84 * u, 52 * u, 34 * u, colours["flame_outer"])
    flame(50 * u, 84 * u, 34 * u, 21 * u, colours["flame_mid"])
    flame(50 * u, 84 * u, 17 * u, 11 * u, colours["flame_core"])

    return img.resize((size, size), Image.Resampling.LANCZOS)


def draw_logo(colours: dict, width: int = 512, height: int = 256) -> Image.Image:
    """Logo horizontal : le pictogramme centré, côté court = 256 px (spec)."""
    icon = draw_icon(colours, height)
    logo = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    logo.paste(icon, ((width - height) // 2, 0), icon)
    return logo


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    files = {
        "icon.png": draw_icon(LIGHT, 256),
        "icon@2x.png": draw_icon(LIGHT, 512),
        "dark_icon.png": draw_icon(DARK, 256),
        "dark_icon@2x.png": draw_icon(DARK, 512),
        "logo.png": draw_logo(LIGHT),
        "dark_logo.png": draw_logo(DARK),
    }
    for name, image in files.items():
        path = OUT / name
        image.save(path)
        print(f"{path.name:20} {image.size[0]}×{image.size[1]}  {path.stat().st_size} o")


if __name__ == "__main__":
    main()
