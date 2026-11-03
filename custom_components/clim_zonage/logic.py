"""Logique pure du zonage — aucune dépendance Home Assistant, donc testable seule.

Toutes les décisions (demande d'une zone, état du feu, consigne du moteur, vitesse)
sont des fonctions pures : elles prennent des nombres et rendent des valeurs.
Le coordinateur ne fait que lire HA, appeler ces fonctions, puis écrire HA.
"""

from __future__ import annotations

from typing import Iterable, Sequence

HEAT = "heat"
COOL = "cool"


def clamp(value: float, low: float, high: float) -> float:
    """Borne une valeur."""
    return max(low, min(high, value))


def snap(value: float, step: float) -> float:
    """Aligne une consigne sur le pas réel de l'unité (0.5 °C sur un CN105)."""
    if step <= 0:
        return value
    return round(round(value / step) * step, 2)


def zone_demands(
    current: float | None,
    target: float | None,
    mode: str | None,
    deadband: float,
    was_demanding: bool = False,
) -> bool:
    """Une zone demande-t-elle ? **Hystérésis à deux seuils**, pas un simple seuil.

    En chaud : une zone *entre* en demande sous `consigne − bande` (19.3 pour une
    consigne de 20.0 avec 0.7 de bande) et n'en *sort* qu'à la consigne (20.0).
    En froid, c'est le miroir : démarrage au-dessus de `consigne + bande`, arrêt à
    la consigne.

    Pourquoi deux seuils : un comparateur à seuil unique démarre **et** arrête au
    même point. Réévalué à chaque cycle (30 s) et à chaque changement de sonde, il
    bascule sans cesse quand la pièce flotte autour du seuil — et chaque bascule
    fait passer la consigne du moteur de 20.0 à la consigne de repli, donc
    commande le compresseur en marche/arrêt. L'hystérésis supprime ce battement
    par construction, et fait en plus **atteindre réellement la consigne** au lieu
    de s'arrêter 0.7 °C en dessous.
    """
    if current is None or target is None or mode not in (HEAT, COOL):
        return False
    if mode == HEAT:
        if was_demanding:
            return current < target
        return current < target - deadband
    if was_demanding:
        return current > target
    return current > target + deadband


def choose_fan(open_vents: int, thresholds: dict) -> str:
    """Vitesse de ventilation selon le nombre de bouches ouvertes.

    0 bouche → auto (le moteur est en repli, on ne force pas de vitesse).
    """
    if open_vents <= 0:
        return "auto"
    if open_vents <= int(thresholds.get("low", 2)):
        return "low"
    if open_vents <= int(thresholds.get("medium", 4)):
        return "medium"
    return "high"


def generator_setpoint(
    reference_temp: float | None,
    mode: str,
    margin: float,
    low: float,
    high: float,
    step: float,
) -> float | None:
    """Consigne « génératrice » : la température de référence + marge.

    But : que le thermostat interne de l'unité ne puisse JAMAIS arrêter la
    production tant qu'une zone demande, même si la pièce qui abrite la sonde
    de reprise est plus chaude que les consignes de zone (cheminée, soleil…).
    """
    if reference_temp is None:
        return None
    if mode == HEAT:
        return snap(clamp(reference_temp + margin, low, high), step)
    if mode == COOL:
        return snap(clamp(reference_temp - margin, low, high), step)
    return None


def virtual_temperature(
    samples: Sequence[tuple[float | None, float | None, bool]],
    mode: str,
) -> float | None:
    """Température « maison » envoyée au gainable (stratégie déportée).

    On ne moyenne QUE les zones en demande : une pièce déjà satisfaite (ou
    chauffée par la cheminée) ne doit pas tirer la valeur vers le haut et
    faire croire à l'unité que la maison est chaude.
    En chaud on prend la plus froide des zones en demande (la plus exigeante),
    en froid la plus chaude — c'est le comportement d'un thermostat bien placé.
    """
    demanding = [t for (t, _target, dem) in samples if dem and t is not None]
    if demanding:
        return min(demanding) if mode == HEAT else max(demanding)
    known = [t for (t, _target, _dem) in samples if t is not None]
    if not known:
        return None
    return sum(known) / len(known)


def house_setpoint(
    samples: Sequence[tuple[float | None, float | None, bool]],
    mode: str,
    low: float,
    high: float,
    step: float,
) -> float | None:
    """Consigne à envoyer au gainable en stratégie déportée.

    C'est la **vraie consigne de maison**, pas un offset : la plus haute des
    consignes des zones en demande en chaud (la plus basse en froid). L'unité
    compare ensuite cette consigne à la température déportée et module d'elle-même.
    """
    targets = [
        target for (_temp, target, dem) in samples if dem and target is not None
    ]
    if not targets:
        return None
    value = max(targets) if mode == HEAT else min(targets)
    return snap(clamp(value, low, high), step)


def fire_detected(
    chimney_temp: float | None,
    room_temp: float | None,
    previous: bool,
    delta_on: float,
    delta_off: float,
) -> bool:
    """Détection du feu par écart panache/ambiance, avec hystérésis.

    La sonde de cheminée est dans le panache : elle monte de 20 °C quand la
    pièce ne gagne que 1,5 °C. On ne l'utilise donc JAMAIS comme mesure
    d'ambiance, seulement comme détecteur.
    """
    if chimney_temp is None or room_temp is None:
        return previous
    delta = chimney_temp - room_temp
    if previous:
        return delta >= delta_off
    return delta >= delta_on


def fire_takes_over(
    fire: bool,
    room_temp: float | None,
    previous: bool,
    temp_min: float,
    temp_off: float,
) -> bool:
    """Le feu peut-il être le SEUL chauffage de la pièce ?

    Règle de Rich : seulement si la pièce est déjà à temp_min (19 °C). En
    dessous, le gainable continue de chauffer la pièce — un feu allumé dans
    une pièce froide reçoit donc le renfort du gainable.
    Le plancher est sur la sonde d'AMBIANCE, pas sur l'écart : une bûche qui
    couve garde un écart élevé alors que la pièce refroidit.
    """
    if not fire or room_temp is None:
        return False
    if previous:
        return room_temp >= temp_off
    return room_temp >= temp_min


def apply_min_vents(
    zones_openable: Iterable[str],
    demanding_zones: Iterable[str],
    dump_zone: str | None,
    min_vents: int,
    dump_available: bool,
    open_vents_in: Iterable[str] = (),
) -> set[str]:
    """Zones dont les clapets doivent être ouverts, pression statique comprise.

    Le seuil se compte en **clapets physiques**, pas en zones : la salle à
    manger a deux volets et pèse donc deux fois plus sur le débit réel.

    Si le nombre de volets ouvert par les seules zones en demande est inférieur
    au minimum, on ouvre la zone de décharge (la plus grande pièce) pour ne pas
    étrangler le réseau. `dump_available` est faux quand la décharge est
    elle-même trop chaude (cheminée allumée) : dans ce cas on assume le débit
    réduit.
    """
    wanted = set(demanding_zones)
    open_vents = len(list(open_vents_in))
    if dump_zone and dump_available and open_vents < min_vents:
        wanted.add(dump_zone)
    return wanted
