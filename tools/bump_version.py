#!/usr/bin/env python3
"""Bump de version : manifest.json + const.py + commit + tag.

La version doit rester synchronisée à trois endroits (`manifest.json` pour HACS,
`const.VERSION`, et le tag git). Ce script fait les trois d'un coup, avec un
contrôle avant/après pour éviter le décalage silencieux.

Usage :
    python tools/bump_version.py 0.12.5 --message "correction X"
    python tools/bump_version.py 0.12.5 --dry-run
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "custom_components" / "clim_zonage" / "manifest.json"
CONST = ROOT / "custom_components" / "clim_zonage" / "const.py"
VERSION_RE = re.compile(r'^VERSION = "([^"]+)"', re.MULTILINE)


def lire() -> tuple[str, str]:
    manifest_version = json.loads(MANIFEST.read_text(encoding="utf-8"))["version"]
    match = VERSION_RE.search(CONST.read_text(encoding="utf-8"))
    if match is None:
        sys.exit("VERSION introuvable dans const.py")
    return manifest_version, match.group(1)


def ecrire(version: str) -> None:
    texte = MANIFEST.read_text(encoding="utf-8")
    texte = re.sub(r'"version": "[^"]+"', f'"version": "{version}"', texte, count=1)
    MANIFEST.write_text(texte, encoding="utf-8")

    texte = CONST.read_text(encoding="utf-8")
    texte = VERSION_RE.sub(f'VERSION = "{version}"', texte, count=1)
    CONST.write_text(texte, encoding="utf-8")


def git(*args: str) -> None:
    subprocess.run(["git", *args], cwd=ROOT, check=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("version", help="nouvelle version, ex. 0.12.5")
    parser.add_argument("--message", "-m", default=None, help="message de commit")
    parser.add_argument("--dry-run", action="store_true", help="affiche sans écrire")
    parser.add_argument("--no-tag", action="store_true", help="ne crée pas le tag")
    args = parser.parse_args()

    avant = lire()
    if avant[0] != avant[1]:
        print(f"⚠️  désaccord AVANT : manifest={avant[0]} const={avant[1]}")
    print(f"version actuelle : manifest={avant[0]} const={avant[1]}")

    if args.dry_run:
        print(f"[dry-run] écrirait {args.version} dans manifest.json et const.py")
        return

    ecrire(args.version)
    apres = lire()
    print(f"version écrite   : manifest={apres[0]} const={apres[1]}")
    if apres != (args.version, args.version):
        sys.exit("❌ écriture incohérente, rien n'a été committé")

    git("add", str(MANIFEST.relative_to(ROOT)), str(CONST.relative_to(ROOT)))
    message = args.message or f"{args.version}"
    git("commit", "-m", message)
    if not args.no_tag:
        git("tag", "-a", f"v{args.version}", "-m", message)
        print(f"tag v{args.version} créé (penser à `git push origin main --tags`)")
    else:
        print("commit créé, tag non demandé")


if __name__ == "__main__":
    main()
