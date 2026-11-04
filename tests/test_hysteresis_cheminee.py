"""Hystérésis des zones et logique cheminée — les deux parties les plus subtiles.

Aucune dépendance Home Assistant : `logic.py` se charge par chemin.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

_SPEC = importlib.util.spec_from_file_location(
    "hyst_logic",
    Path(__file__).resolve().parents[1]
    / "custom_components"
    / "clim_zonage"
    / "logic.py",
)
_L = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_L)


# ─── zone_demands : hystérésis symétrique autour de la consigne ─────────────
def test_chaud_demarrage_sous_consigne_moins_hysteresis():
    # consigne 20, hystérésis (demi-bande) 0.7 → démarre à 19.3
    assert _L.zone_demands(19.2, 20.0, _L.HEAT, 0.7, False) is True
    assert _L.zone_demands(19.3, 20.0, _L.HEAT, 0.7, False) is False


def test_chaud_maintien_jusqua_consigne_plus_hysteresis():
    # une zone déjà en demande reste en demande jusqu'à 20.7
    assert _L.zone_demands(20.6, 20.0, _L.HEAT, 0.7, True) is True
    assert _L.zone_demands(20.7, 20.0, _L.HEAT, 0.7, True) is False


def test_froid_est_le_miroir():
    assert _L.zone_demands(24.8, 24.0, _L.COOL, 0.7, False) is True
    assert _L.zone_demands(24.7, 24.0, _L.COOL, 0.7, False) is False
    assert _L.zone_demands(23.4, 24.0, _L.COOL, 0.7, True) is True
    assert _L.zone_demands(23.3, 24.0, _L.COOL, 0.7, True) is False


def test_valeurs_manquantes_ou_mode_invalide_ne_demandent_pas():
    assert _L.zone_demands(None, 20.0, _L.HEAT, 0.7, True) is False
    assert _L.zone_demands(19.0, None, _L.HEAT, 0.7, True) is False
    assert _L.zone_demands(19.0, 20.0, "fan_only", 0.7, True) is False
    assert _L.zone_demands(30.0, 20.0, _L.HEAT, 0.7, False) is False


# ─── fire_detected : écart panache / ambiance, avec hystérésis ──────────────
def test_feu_detecte_par_ecart():
    assert _L.fire_detected(45.0, 20.0, False, 5.0, 2.0) is True   # écart 25
    assert _L.fire_detected(24.0, 20.0, False, 5.0, 2.0) is False  # écart 4 < 5


def test_feu_maintien_a_un_ecart_plus_faible():
    assert _L.fire_detected(23.0, 20.0, True, 5.0, 2.0) is True    # écart 3 >= 2
    assert _L.fire_detected(21.0, 20.0, True, 5.0, 2.0) is False   # écart 1 < 2


def test_feu_sans_mesure_garde_l_etat_precedent():
    assert _L.fire_detected(None, 20.0, True, 5.0, 2.0) is True
    assert _L.fire_detected(40.0, None, False, 5.0, 2.0) is False


# ─── fire_takes_over : le feu peut-il être le seul chauffage ? ──────────────
def test_pas_de_feu_pas_de_prise_en_charge():
    assert _L.fire_takes_over(False, 22.0, False, 19.0, 18.0) is False


def test_prise_en_charge_seulement_si_la_piece_est_assez_chaude():
    assert _L.fire_takes_over(True, 19.0, False, 19.0, 18.0) is True
    assert _L.fire_takes_over(True, 18.9, False, 19.0, 18.0) is False


def test_prise_en_charge_maintien_avec_hysteresis_basse():
    assert _L.fire_takes_over(True, 18.0, True, 19.0, 18.0) is True
    assert _L.fire_takes_over(True, 17.9, True, 19.0, 18.0) is False


def test_prise_en_charge_sans_mesure_d_ambiance_est_refusee():
    assert _L.fire_takes_over(True, None, True, 19.0, 18.0) is False
