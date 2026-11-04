"""Zone de décharge : disponibilité et application du minimum de bouches.

Couvre la décision de Rich du 04/11/2026 : quand plus aucune pièce ne demande, la
zone de décharge sert au **débit** (pression statique) et doit s'ouvrir même si sa
propre consigne est atteinte ou si la cheminée chauffe la pièce.

`logic.py` n'importe pas Home Assistant : il se charge par chemin, sans stub.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

_SPEC = importlib.util.spec_from_file_location(
    "dump_logic",
    Path(__file__).resolve().parents[1]
    / "custom_components"
    / "clim_zonage"
    / "logic.py",
)
_LOGIC = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_LOGIC)

dump_is_available = _LOGIC.dump_is_available
apply_min_vents = _LOGIC.apply_min_vents
HEAT = _LOGIC.HEAT
COOL = _LOGIC.COOL


# ─── dump_is_available ──────────────────────────────────────────────────────
def test_idle_autorise_la_decharge_meme_consigne_atteinte_et_feu_actif():
    """Le cas demandé : tout le monde à température, SaM au-dessus de sa consigne."""
    assert (
        dump_is_available(HEAT, 21.1, 21.0, fire_takeover=True, is_fire_room=True, idle=True)
        is True
    )


def test_feu_actif_sur_la_piece_de_la_cheminee_bloque_la_decharge():
    """Inhibition conservée dès qu'une zone demande par ailleurs."""
    assert (
        dump_is_available(HEAT, 21.1, 21.0, fire_takeover=True, is_fire_room=True)
        is False
    )


def test_piece_au_dessus_de_sa_consigne_bloque_la_decharge():
    assert dump_is_available(HEAT, 21.1, 21.0, fire_takeover=False, is_fire_room=False) is False


def test_piece_sous_sa_consigne_autorise_la_decharge():
    assert dump_is_available(HEAT, 19.0, 21.0, fire_takeover=False, is_fire_room=False) is True


def test_froid_miroir():
    assert dump_is_available(COOL, 24.0, 24.0, fire_takeover=False, is_fire_room=False) is False
    assert dump_is_available(COOL, 25.0, 24.0, fire_takeover=False, is_fire_room=False) is True


# ─── apply_min_vents ────────────────────────────────────────────────────────
def test_min_vents_1_sans_demande_ouvre_la_decharge():
    wanted = apply_min_vents(
        zones_openable=["alice", "noemie", "sam"],
        demanding_zones=[],
        dump_zone="sam",
        min_vents=1,
        dump_available=True,
        open_vents_in=[],
    )
    assert wanted == {"sam"}


def test_min_vents_1_avec_une_demande_pas_de_decharge():
    wanted = apply_min_vents(
        zones_openable=["alice", "sam"],
        demanding_zones=["alice"],
        dump_zone="sam",
        min_vents=1,
        dump_available=True,
        open_vents_in=["cover.valvealice"],
    )
    assert wanted == {"alice"}


def test_min_vents_2_avec_une_demande_ajoute_la_decharge():
    wanted = apply_min_vents(
        zones_openable=["alice", "sam"],
        demanding_zones=["alice"],
        dump_zone="sam",
        min_vents=2,
        dump_available=True,
        open_vents_in=["cover.valvealice"],
    )
    assert wanted == {"alice", "sam"}


def test_decharge_indisponible_assume_le_debit_reduit():
    wanted = apply_min_vents(
        zones_openable=["alice", "sam"],
        demanding_zones=[],
        dump_zone="sam",
        min_vents=1,
        dump_available=False,
        open_vents_in=[],
    )
    assert wanted == set()


def test_chainage_idle_vers_ouverture_de_la_decharge():
    dispo = dump_is_available(HEAT, 21.1, 21.0, True, True, idle=True)
    wanted = apply_min_vents(
        zones_openable=["alice", "sam"],
        demanding_zones=[],
        dump_zone="sam",
        min_vents=1,
        dump_available=dispo,
        open_vents_in=[],
    )
    assert wanted == {"sam"}
