"""Tests de la logique pure du zonage (aucune dépendance Home Assistant)."""

from __future__ import annotations

import importlib.util
from pathlib import Path

# On charge logic.py par chemin : le paquet custom_components.clim_zonage
# importe Home Assistant, absent de l'environnement de test.
_SPEC = importlib.util.spec_from_file_location(
    "zlogic",
    Path(__file__).resolve().parents[1]
    / "custom_components"
    / "clim_zonage"
    / "logic.py",
)
_LOGIC = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_LOGIC)

apply_min_vents = _LOGIC.apply_min_vents
apply_offset = _LOGIC.apply_offset
dump_is_available = _LOGIC.dump_is_available
choose_fan = _LOGIC.choose_fan
fire_detected = _LOGIC.fire_detected
fire_takes_over = _LOGIC.fire_takes_over
generator_setpoint = _LOGIC.generator_setpoint
house_setpoint = _LOGIC.house_setpoint
remote_setpoint = _LOGIC.remote_setpoint
watchdog_mode = _LOGIC.watchdog_mode
snap = _LOGIC.snap
virtual_temperature = _LOGIC.virtual_temperature
zone_demands = _LOGIC.zone_demands


def test_snap_sur_le_pas_reel():
    assert snap(22.34, 0.5) == 22.5
    assert snap(22.24, 0.5) == 22.0
    assert snap(22.5, 0.0) == 22.5


def test_demande_avec_bande_morte():
    # consigne 19.5, bande 0.7 → demande sous 18.8 seulement
    assert zone_demands(18.7, 19.5, "heat", 0.7) is True
    assert zone_demands(18.8, 19.5, "heat", 0.7) is False
    assert zone_demands(20.0, 19.5, "heat", 0.7) is False
    # en froid, l'inverse
    assert zone_demands(27.0, 26.0, "cool", 0.7) is True
    assert zone_demands(26.5, 26.0, "cool", 0.7) is False
    # une zone éteinte ne demande jamais
    assert zone_demands(10.0, 19.5, "off", 0.7) is False
    # sonde absente → pas de décision
    assert zone_demands(None, 19.5, "heat", 0.7) is False


def test_vitesse_selon_bouches():
    th = {"low": 2, "medium": 4, "high": 7}
    assert choose_fan(0, th) == "auto"
    assert choose_fan(1, th) == "low"
    assert choose_fan(2, th) == "low"
    assert choose_fan(3, th) == "medium"
    assert choose_fan(5, th) == "high"


def test_consigne_generatrice_decouplee_de_la_piece_chaude():
    # La pièce de reprise est à 23 °C, une zone demande encore : en chaud la
    # consigne doit rester AU-DESSUS de 23 pour que l'unité produise.
    sp = generator_setpoint(23.0, "heat", 2.0, 16, 31, 0.5)
    assert sp == 25.0
    assert sp > 23.0
    # bornage haut
    assert generator_setpoint(30.5, "heat", 2.0, 16, 31, 0.5) == 31.0
    # en froid, la marge va vers le bas
    assert generator_setpoint(24.0, "cool", 2.0, 16, 31, 0.5) == 22.0
    # sans référence, pas de consigne inventée
    assert generator_setpoint(None, "heat", 2.0, 16, 31, 0.5) is None


def test_temperature_deportee_ne_moyenne_que_les_zones_en_demande():
    # SaM chaude (cheminée) non demandeuse : elle ne doit PAS tirer la valeur
    samples = [
        (23.6, 19.5, False),   # salle à manger chauffée par le feu
        (20.4, 19.5, True),    # Alice en demande
        (19.7, 19.5, True),    # Noémie en demande
        (24.0, 19.5, False),
    ]
    assert virtual_temperature(samples, "heat") == 19.7
    # si aucune zone ne demande : moyenne de ce qui est connu (information)
    idle = [(20.0, 19.5, False), (22.0, 19.5, False)]
    assert virtual_temperature(idle, "heat") == 21.0


def test_detection_feu_hysteresis():
    # sous le seuil : pas de feu
    assert fire_detected(22.0, 21.0, False, 5.0, 2.0) is False
    # au-dessus : feu
    assert fire_detected(44.0, 23.0, False, 5.0, 2.0) is True
    # feu en cours : on garde tant que l'écart reste >= 2
    assert fire_detected(26.0, 23.0, True, 5.0, 2.0) is True
    assert fire_detected(24.0, 23.0, True, 5.0, 2.0) is False
    # sonde absente : on ne change pas d'avis
    assert fire_detected(None, 23.0, True, 5.0, 2.0) is True


def test_prise_en_charge_chemin_e_piece_froide():
    # Feu allumé MAIS pièce à 18.5 < 19 → le gainable doit continuer de chauffer
    assert fire_takes_over(True, 18.5, False, 19.0, 18.0) is False
    # pièce à 19.0 → le feu peut chauffer seul
    assert fire_takes_over(True, 19.0, False, 19.0, 18.0) is True
    # déjà pris en charge : on garde jusqu'à 18.0 (bûche qui couve)
    assert fire_takes_over(True, 18.2, True, 19.0, 18.0) is True
    assert fire_takes_over(True, 17.9, True, 19.0, 18.0) is False
    # pas de feu → pas de prise en charge
    assert fire_takes_over(False, 23.0, True, 19.0, 18.0) is False


def test_consigne_de_maison_et_marge_en_deporte():
    samples = [(19.2, 20.0, True), (21.0, 19.5, False), (20.1, 20.0, True)]
    # sans marge : la plus haute consigne des pièces en demande
    assert house_setpoint(samples, "heat", 16, 31, 0.5) == 20.0
    # avec marge 0.5 : consigne + marge, pour franchir le différentiel de l'unité
    assert remote_setpoint(samples, "heat", 0.5, 16, 31, 0.5) == 20.5
    assert remote_setpoint(samples, "heat", 1.0, 16, 31, 0.5) == 21.0
    # en froid, la marge se retire
    cool = [(23.0, 22.0, True), (19.0, 20.0, False)]
    assert house_setpoint(cool, "cool", 16, 31, 0.5) == 22.0
    assert remote_setpoint(cool, "cool", 0.5, 16, 31, 0.5) == 21.5
    # bornage et arrondi sur le pas réel de l'unité
    assert remote_setpoint([(19.0, 30.5, True)], "heat", 1.0, 16, 31, 0.5) == 31
    # aucune pièce en demande → pas de consigne
    assert remote_setpoint([(20.0, 19.5, False)], "heat", 0.5, 16, 31, 0.5) is None


def test_correction_de_calibration_dune_sonde():
    # une sonde qui lit 0.8 °C de trop reçoit un offset de -0.8
    assert apply_offset(21.3, -0.8) == 20.5
    assert apply_offset(19.9, 0.0) == 19.9
    assert apply_offset(19.9, 0.4) == 20.3
    # pas de mesure → pas de correction
    assert apply_offset(None, -0.8) is None
    # arrondi propre (les sondes sont à 0.1 °C)
    assert apply_offset(20.15, 0.1) == 20.25


def test_chien_de_garde_trois_etats():
    """normal → gele (grâce) → degrade : une sonde morte ne doit pas figer la maison."""
    now = 1_000_000.0
    assert watchdog_mode(0, None, now, 120) == "normal"
    # une sonde vient de tomber : on ne touche à rien
    assert watchdog_mode(1, now - 5, now, 120) == "gele"
    assert watchdog_mode(3, now - 119, now, 120) == "gele"
    # au-delà de la grâce : on continue avec les zones valides et on alerte
    assert watchdog_mode(1, now - 121, now, 120) == "degrade"
    assert watchdog_mode(2, now - 3600, now, 120) == "degrade"
    # jamais de mesure connue (démarrage avec une sonde déjà morte) : gel d'abord
    assert watchdog_mode(1, None, now, 120) == "gele"


def test_demande_avec_hysteresis():
    # Chaud, consigne 20.0, demi-bande 0.7 → démarrage sous 19.3, arrêt à 20.7
    assert zone_demands(19.2, 20.0, "heat", 0.7, False) is True
    assert zone_demands(19.4, 20.0, "heat", 0.7, False) is False   # pas encore entrée
    # une fois entrée, elle tient jusqu'à consigne + bande (bande symétrique)
    assert zone_demands(19.4, 20.0, "heat", 0.7, True) is True
    assert zone_demands(19.9, 20.0, "heat", 0.7, True) is True
    assert zone_demands(20.0, 20.0, "heat", 0.7, True) is True     # la cible ne l'arrête plus
    assert zone_demands(20.5, 20.0, "heat", 0.7, True) is True
    assert zone_demands(20.7, 20.0, "heat", 0.7, True) is False    # arrêt au-dessus de la cible
    # et ne redémarre qu'en repassant sous 19.3 (bande totale 1.4 °C)
    assert zone_demands(19.5, 20.0, "heat", 0.7, False) is False
    assert zone_demands(19.2, 20.0, "heat", 0.7, False) is True

    # Froid, miroir : démarrage au-dessus de 20.7, arrêt sous 19.3
    assert zone_demands(20.8, 20.0, "cool", 0.7, False) is True
    assert zone_demands(20.5, 20.0, "cool", 0.7, False) is False
    assert zone_demands(20.5, 20.0, "cool", 0.7, True) is True
    assert zone_demands(20.0, 20.0, "cool", 0.7, True) is True
    assert zone_demands(19.2, 20.0, "cool", 0.7, True) is False

    # Pas de demande hors chaud/froid, ou sans mesure
    assert zone_demands(19.0, 20.0, "off", 0.7, True) is False
    assert zone_demands(None, 20.0, "heat", 0.7, True) is False
    assert zone_demands(19.0, None, "heat", 0.7, True) is False


def test_pas_de_battement_autour_du_seuil():
    """Sans hystérésis, 19.2/19.3/19.2/19.3 faisait battre la demande à chaque tour."""
    consigne, bande = 20.0, 0.7
    etat = False
    bascules = 0
    for temp in [19.2, 19.3, 19.2, 19.3, 19.2, 19.3]:
        nouveau = zone_demands(temp, consigne, "heat", bande, etat)
        if nouveau != etat:
            bascules += 1
        etat = nouveau
    assert etat is True
    assert bascules == 1  # une seule bascule : on entre, on n'en sort plus


def test_decharge_jamais_ouverte_si_le_feu_chauffe_la_piece():
    # pièce froide et feu en prise en charge : on n'ouvre pas la décharge
    assert dump_is_available("heat", 18.0, 19.5, True, True) is False
    # même pièce, feu terminé : elle redevient une décharge normale
    assert dump_is_available("heat", 18.0, 19.5, False, True) is True
    # déjà au-dessus de sa consigne : on n'envoie pas d'air chaud
    assert dump_is_available("heat", 20.0, 19.5, False, True) is False
    # en froid, miroir
    assert dump_is_available("cool", 23.0, 25.0, False, True) is False
    assert dump_is_available("cool", 26.0, 25.0, False, True) is True
    # sonde ou consigne indisponible : on laisse la décharge disponible
    assert dump_is_available("heat", None, 19.5, False, True) is True
    assert dump_is_available("heat", 18.0, None, False, True) is True


def test_minimum_de_bouches_et_decharge():
    # une seule zone en demande, un seul clapet → on ajoute la décharge
    assert apply_min_vents({"alice"}, "sam", 2, True, ["cover.valvealice"]) == {
        "alice",
        "sam",
    }
    # la décharge est trop chaude (cheminée) → on ne l'ouvre pas
    assert apply_min_vents({"alice"}, "sam", 2, False, ["cover.valvealice"]) == {"alice"}
    # assez de clapets ouverts par la demande → décharge inutile
    assert apply_min_vents(
        {"alice", "noemie"},
        "sam",
        2,
        True,
        ["cover.valvealice", "cover.valvenoemie"],
    ) == {"alice", "noemie"}
    # la salle à manger compte pour DEUX clapets : ouverte seule, elle suffit
    assert apply_min_vents({"sam"}, "sam", 2, True, ["cover.sam_east", "cover.sam_west"]) == {
        "sam"
    }
    # pas de zone de décharge configurée : on ne plante pas
    assert apply_min_vents({"alice"}, None, 2, True, ["cover.valvealice"]) == {"alice"}


def test_consigne_de_maison_strategie_deportee():
    from importlib import util as _u

    house_setpoint = _LOGIC.house_setpoint
    # la plus haute consigne des zones en demande, en chaud
    samples = [
        (18.5, 19.5, True),
        (18.0, 19.0, True),
        (23.6, 19.5, False),   # SaM chauffée par la cheminée : ignorée
    ]
    assert house_setpoint(samples, "heat", 16, 31, 0.5) == 19.5
    # en froid, la plus basse des consignes en demande
    cool = [(27.0, 26.0, True), (26.5, 25.0, True), (21.0, 26.0, False)]
    assert house_setpoint(cool, "cool", 16, 31, 0.5) == 25.0
    # aucune zone en demande : pas de consigne inventée
    assert house_setpoint([(20.0, 19.5, False)], "heat", 16, 31, 0.5) is None
    # bornage au pas et aux limites de l'unité
    assert house_setpoint([(10.0, 40.0, True)], "heat", 16, 31, 0.5) == 31.0
