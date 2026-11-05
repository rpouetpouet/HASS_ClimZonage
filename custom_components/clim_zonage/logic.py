"""Logique pure du zonage — aucune dépendance Home Assistant, donc testable seule.

Toutes les décisions (demande d'une zone, état du feu, consigne du moteur, vitesse)
sont des fonctions pures : elles prennent des nombres et rendent des valeurs.
Le coordinateur ne fait que lire HA, appeler ces fonctions, puis écrire HA.
"""

from __future__ import annotations

from typing import Iterable, Sequence

HEAT = "heat"
COOL = "cool"


def apply_offset(value: float | None, offset: float) -> float | None:
    """Applique la correction de calibration d'une sonde.

    `offset` est **ajouté** à la mesure : une sonde qui lit 0.8 °C de trop reçoit
    −0.8. La mesure brute n'est jamais modifiée en amont — l'entité d'origine
    garde sa valeur, seule la valeur utilisée par le zonage est corrigée.
    """
    if value is None or not offset:
        return value
    return round(value + offset, 2)


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
    """Une zone demande-t-elle ? **Hystérésis symétrique autour de la consigne**.

    La bande est centrée sur la consigne : `deadband` est la demi-largeur.
    En chaud, une zone entre en demande sous `consigne − bande` et n'en sort
    qu'au-dessus de `consigne + bande`. En froid, c'est le miroir.

    Pourquoi symétrique : avec un arrêt *à* la consigne, la demande tombe dès
    que la pièce l'atteint, le moteur repasse en consigne de repli, la production
    s'arrête — et l'unité, qui a son **propre différentiel de thermostat**
    (~0.5-1 °C), ne redémarre pas pour un demi-degré manquant. Résultat mesuré le
    03/11 : la pièce oscillait entre 18.9 et 19.4 pour une consigne de 20.0.
    En gardant la demande jusqu'à `consigne + bande`, le moteur reste armé sur la
    vraie consigne et l'unité produit tant que son propre seuil est franchi : la
    pièce converge vers la consigne au lieu de plafonner en dessous.

    Conséquence à assumer : une pièce légèrement **au-dessus** de sa consigne
    reste « en demande » (donc clapet ouvert, action « chauffe ») jusqu'à
    `consigne + bande`. C'est le prix pour atteindre la cible en réel ; réduire
    `deadband` resserre la bande dans les deux sens.
    """
    if current is None or target is None or mode not in (HEAT, COOL):
        return False
    if mode == HEAT:
        if was_demanding:
            return current < target + deadband
        return current < target - deadband
    if was_demanding:
        return current > target - deadband
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


MODE_NORMAL = "normal"
MODE_GELE = "gele"
MODE_DEGRADE = "degrade"


def pick_source_option(options: Sequence[str], want_panel: bool) -> str | None:
    """Quelle option du réglage 102 (source de température de l'unité) choisir ?

    `want_panel=True`  -> le thermostat de la **télécommande filaire** (le panneau).
    `want_panel=False` -> la source **externe CN105** (la température déportée que
    l'intégration envoie au gainable).

    On reconnaît les options par mots-clés plutôt que par leur libellé exact :
    ils viennent du YAML ESPHome (`options: {1: "Sonde interne (défaut)", …}`) et
    peuvent être réécrits. Aucune correspondance ⇒ `None`, et l'appelant ne
    touche à rien : mieux vaut ne pas écrire que d'écrire faux.
    """
    if not options:
        return None
    keys = ("filaire",) if want_panel else ("cn105", "externe")
    for option in options:
        low = option.lower()
        if any(key in low for key in keys):
            return option
    return None


def watchdog_mode(
    ko_count: int, ko_since_ts: float | None, now_ts: float, grace_s: float
) -> str:
    """Que faire quand une sonde essentielle ne donne plus de mesure ?

    Trois états, dans cet ordre :

    * `normal` — toutes les sondes répondent.
    * `gele` — une sonde vient de tomber : on **ne touche à rien** (ni clapet, ni
      consigne, ni vitesse) pendant la période de grâce. C'est ce qui empêche un
      trou d'une seconde (rechargement, redémarrage, `unavailable` passager) de
      déclencher un mouvement de clapets puis de se figer 20 minutes sur le
      verrou `min_cycle`.
    * `degrade` — la sonde est tombée depuis plus que la grâce : on continue avec
      les zones valides, on ne touche plus aux clapets de la zone muette, et on
      alerte. Une sonde morte ne doit pas geler le chauffage de toute la maison.
    """
    if ko_count <= 0:
        return MODE_NORMAL
    if ko_since_ts is None or (now_ts - ko_since_ts) < grace_s:
        return MODE_GELE
    return MODE_DEGRADE


def remote_setpoint(
    samples: Sequence[tuple[float | None, float | None, bool]],
    mode: str,
    margin: float,
    low: float,
    high: float,
    step: float,
) -> float | None:
    """Consigne envoyée à l'unité en stratégie déportée : consigne de maison + marge.

    La marge n'est pas un caprice : l'unité a son **propre différentiel de
    thermostat** (mesuré ~0,5 à 1 °C). Avec une consigne égale à la consigne de
    maison, il ne reste, une fois la pièce proche de sa cible, qu'un écart trop
    faible pour que le compresseur redémarre — la pièce plafonne alors sous sa
    consigne. Envoyer `consigne + marge` (chaud) / `consigne − marge` (froid)
    garantit le franchissement de ce différentiel tout en gardant une régulation
    finie : c'est la température déportée qui décide, pas la marge.
    """
    house = house_setpoint(samples, mode, low, high, step)
    if house is None:
        return None
    offset = margin if mode == HEAT else -margin
    return snap(clamp(house + offset, low, high), step)


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


def dump_is_available(
    mode: str | None,
    room_temp: float | None,
    target: float | None,
    fire_takeover: bool,
    is_fire_room: bool,
    idle: bool = False,
) -> bool:
    """La zone de décharge peut-elle servir de filet de pression statique ?

    Trois cas :
    - `idle` (aucune zone en demande, tout le monde à température) : la décharge ne
      sert plus au confort mais au **débit** — on l'ouvre quels que soient sa propre
      consigne et l'état de la cheminée. L'unité étant à sa consigne de repli, aucun
      air chaud n'est envoyé dans une pièce qui n'en veut pas : c'est un clapet
      ouvert pour la pression statique, pas un appel de chauffage.
    - sinon, deux raisons de ne pas l'ouvrir : elle est déjà au-delà de sa consigne
      (on enverrait de l'air chaud dans une pièce qui n'en veut pas), ou c'est la
      pièce que la cheminée chauffe — ouvrir son clapet pour « faire du débit » n'a
      pas de sens quand une autre zone demande, le feu s'en occupe déjà.
    """
    if idle:
        return True
    if is_fire_room and fire_takeover:
        return False
    if room_temp is None or target is None:
        return True
    return room_temp < target if mode == HEAT else room_temp > target


def apply_min_vents(
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
