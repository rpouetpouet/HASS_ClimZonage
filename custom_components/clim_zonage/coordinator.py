"""Coordinateur : le cerveau du zonage.

Une seule boucle décide de tout, sur un tick de 30 s **et** à chaque changement
d'état pertinent. Elle lit Home Assistant, appelle `logic.py` (fonctions pures),
puis écrit Home Assistant.

Règles non négociables encodées ici :
  * le gainable n'est JAMAIS éteint par le pilotage automatique — quand plus
    aucune zone ne demande, on passe en consigne de repli + ventilation auto,
    ce qui laisse le thermostat interne faire son travail sans jamais créer
    l'état « off » dont on ne sait pas ressortir ;
  * seul le master switch (OFF) éteint l'unité ;
  * les consignes de zone ne pilotent JAMAIS directement la consigne du moteur
    par un min()/max() : la sonde de reprise est dans une pièce qui peut être
    chaude pour une autre raison (cheminée) et affamerait les autres pièces.
"""

from __future__ import annotations

import datetime
import logging
import time
from dataclasses import dataclass, field
from typing import Any

from homeassistant.const import (
    ATTR_ENTITY_ID,
    SERVICE_CLOSE_COVER,
    SERVICE_OPEN_COVER,
    STATE_CLOSED,
    STATE_OPEN,
    STATE_OPENING,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.event import async_track_state_change_event
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from .const import (
    CONF_CYCLE_SECONDS,
    CONF_DAMPER_COURSE,
    CONF_DEADBAND,
    CONF_ENGINE,
    CONF_FALLBACK_COOL,
    CONF_FALLBACK_HEAT,
    CONF_FAN_THRESHOLDS,
    CONF_FIRE_DELTA_OFF,
    CONF_FIRE_DELTA_ON,
    CONF_FIRE_TEMP_MIN,
    CONF_FIRE_TEMP_OFF,
    CONF_FIREPLACE,
    CONF_MARGIN,
    CONF_MIN_CYCLE,
    CONF_MIN_VENTS,
    CONF_STRATEGY,
    CONF_ZONE_DAMPERS,
    CONF_ZONE_DUMP,
    CONF_ZONE_FIRE_ROOM,
    CONF_ZONE_NAME,
    CONF_ZONE_SENSOR,
    CONF_ZONE_UID,
    DOMAIN,
    HVAC_COOL,
    HVAC_FAN_ONLY,
    HVAC_HEAT,
    HVAC_OFF,
    MAX_TEMP,
    MIN_TEMP,
    STRATEGY_REMOTE,
    TEMP_STEP,
    TICK_SECONDS,
)
from .logic import (
    apply_min_vents,
    choose_fan,
    clamp,
    fire_detected,
    fire_takes_over,
    generator_setpoint,
    house_setpoint,
    snap,
    virtual_temperature,
    zone_demands,
)

_LOGGER = logging.getLogger(__name__)


@dataclass
class Zone:
    """Une zone de zonage : un thermostat, une sonde, N clapets."""

    uid: str
    name: str
    temp_sensor: str
    dampers: list[str]
    fire_room: bool = False
    dump: bool = False


@dataclass
class ZonageState:
    """Tout ce que les entités lisent (jamais de calcul dans les entités)."""

    active: bool = True
    mode: str = HVAC_HEAT
    zones: dict[str, dict[str, Any]] = field(default_factory=dict)
    fire: bool = False
    fire_takeover: bool = False
    open_vents: int = 0
    engine_setpoint: float | None = None
    virtual_temp: float | None = None
    strategy: str = ""


def build_zones(raw_zones: list[dict]) -> list[Zone]:
    """Convertit la config de l'entrée en objets Zone."""
    zones: list[Zone] = []
    for raw in raw_zones:
        zones.append(
            Zone(
                uid=raw[CONF_ZONE_UID],
                name=raw.get(CONF_ZONE_NAME, raw[CONF_ZONE_UID]),
                temp_sensor=raw[CONF_ZONE_SENSOR],
                dampers=list(raw.get(CONF_ZONE_DAMPERS) or []),
                fire_room=bool(raw.get(CONF_ZONE_FIRE_ROOM, False)),
                dump=bool(raw.get(CONF_ZONE_DUMP, False)),
            )
        )
    return zones


class ZonageCoordinator(DataUpdateCoordinator[ZonageState]):
    """Boucle de décision du zonage."""

    def __init__(self, hass: HomeAssistant, entry, zones: list[Zone], options: dict):
        cycle = int(options.get(CONF_CYCLE_SECONDS, 30))
        super().__init__(
            hass,
            _LOGGER,
            name=f"{DOMAIN}",
            update_interval=datetime.timedelta(seconds=cycle),
        )
        self.entry = entry
        self.zones = zones
        self.options = options

        self.engine: str = entry.data[CONF_ENGINE]
        self.fireplace_sensor: str | None = entry.data.get(CONF_FIREPLACE)

        # État persisté par les entités (source de vérité unique)
        self.active: bool = True
        self.mode: str = HVAC_HEAT
        self.zone_targets: dict[str, float] = {}
        self.zone_modes: dict[str, str] = {}

        # État interne (non exposé)
        self._state = ZonageState()
        self._last_toggle: dict[str, float] = {}
        self._fire = False
        self._fire_takeover = False
        self.fire_force = False  # forcé par le switch « chauffage assuré par le feu »
        self._force_dampers_next = False
        # Récalibration demandée : les ordres seront renvoyés au prochain cycle,
        # que l'état corresponde déjà ou non (propriété lue par le bouton).
        # État d'hystérésis : une zone en demande le reste jusqu'à sa consigne.
        self._zone_demanding: dict[str, bool] = {}
        self._off_closed = False  # les clapets ont-ils déjà été fermés pour cet arrêt ?
        self._unsub: list = []

    # ─── cycle de vie ───────────────────────────────────────────────────────
    async def async_setup(self) -> None:
        """Abonne la boucle aux changements d'état pertinents."""
        watched = {self.engine}
        if self.fireplace_sensor:
            watched.add(self.fireplace_sensor)
        for zone in self.zones:
            watched.add(zone.temp_sensor)
            watched.update(zone.dampers)
        self._unsub.append(
            async_track_state_change_event(
                self.hass, list(watched), self._handle_state_change
            )
        )

    @callback
    def _handle_state_change(self, event) -> None:
        """Un changement pertinent : on recalcule au prochain tick rapide."""
        self.hass.async_create_task(self.async_request_refresh())

    async def async_shutdown(self) -> None:
        for unsub in self._unsub:
            unsub()
        self._unsub.clear()

    # ─── lecture des entités ────────────────────────────────────────────────
    def is_zone_active(self, uid: str) -> bool:
        return self.zone_modes.get(uid) != HVAC_OFF

    def zone_target(self, uid: str) -> float | None:
        return self.zone_targets.get(uid)

    def zone_mode(self, uid: str) -> str:
        return self.zone_modes.get(uid, HVAC_OFF)

    def _float_state(self, entity_id: str | None) -> float | None:
        if not entity_id:
            return None
        state = self.hass.states.get(entity_id)
        if state is None or state.state in ("unknown", "unavailable", ""):
            return None
        try:
            return float(state.state)
        except (TypeError, ValueError):
            return None

    def _attr(self, entity_id: str, key: str) -> Any:
        state = self.hass.states.get(entity_id)
        return state.attributes.get(key) if state else None

    # ─── la boucle ──────────────────────────────────────────────────────────
    async def _async_update_data(self) -> ZonageState:
        opts = self.options
        engine_state = self.hass.states.get(self.engine)
        engine_mode = engine_state.state if engine_state else None

        # 1. MASTER OFF → tout s'arrête, et c'est le seul `off` du système.
        if not self.active:
            await self._async_engine_off()
            # On ferme les clapets UNE SEULE FOIS à l'entrée en arrêt, puis on
            # laisse la main : en mode arrêté, une ouverture manuelle d'un clapet
            # doit tenir (test, dépannage, pilotage par la télécommande murale).
            # Les refermer à chaque tick reviendrait à combattre l'utilisateur.
            if not self._off_closed or self._force_dampers_next:
                await self._async_apply_dampers(
                    set(), force=True, force_all=self._force_dampers_next
                )
                self._force_dampers_next = False
                self._off_closed = True
            # On garde les zones lisibles (consigne, température, mode `off`) :
            # l'utilisateur doit voir ce qui redémarrera, et `zone_modes` /
            # `zone_targets` restent intacts pour la réactivation.
            zdata_off: dict[str, dict[str, Any]] = {}
            open_off = 0
            for zone in self.zones:
                states = [self.hass.states.get(d) for d in zone.dampers]
                n_open = sum(
                    1
                    for s in states
                    if s is not None and s.state in (STATE_OPEN, STATE_OPENING)
                )
                open_off += n_open
                zdata_off[zone.uid] = {
                    "name": zone.name,
                    # Le mode AFFICHÉ reste celui mémorisé : si on exposait `off`
                    # pendant l'arrêt, RestoreEntity enregistrerait `off` et un
                    # redémarrage de HA survenu master éteint ferait perdre les
                    # modes des zones. L'arrêt se lit sur `systeme_actif` et sur
                    # hvac_action, pas en maquillant chaque zone.
                    "mode": self.zone_mode(zone.uid),
                    "temp": self._float_state(zone.temp_sensor),
                    "target": self.zone_target(zone.uid),
                    "demand": False,
                    "seuil_demarrage": None,
                    "seuil_arret": None,
                    "fire_room": zone.fire_room,
                    "open": n_open > 0,
                    "clapets_ouverts": n_open,
                    "system_off": True,
                }
            self._state = ZonageState(
                active=False,
                mode=HVAC_OFF,
                zones=zdata_off,
                strategy="off",
                open_vents=open_off,
            )
            return self._state

        mode = self.mode if self.mode in (HVAC_HEAT, HVAC_COOL, HVAC_FAN_ONLY) else HVAC_HEAT

        # Une zone restée dans un autre mode que celui de la maison (changement de
        # saison, redémarrage entre deux restaurations d'état) est réalignée
        # d'office : sinon elle afficherait un mode qui n'est ni proposé ni honoré.
        for uid, zmode in list(self.zone_modes.items()):
            if zmode != HVAC_OFF and zmode != mode:
                _LOGGER.info(
                    "Zone %s : mode %s alors que la maison est en %s, réaligné",
                    uid,
                    zmode,
                    mode,
                )
                self.zone_modes[uid] = mode

        # 2. Cheminée : détection (panache) puis prise en charge (plancher de pièce)
        fire_zone = next((z for z in self.zones if z.fire_room), None)
        room_temp = self._float_state(fire_zone.temp_sensor) if fire_zone else None
        chimney_temp = self._float_state(self.fireplace_sensor)
        self._fire = fire_detected(
            chimney_temp,
            room_temp,
            self._fire,
            float(opts.get(CONF_FIRE_DELTA_ON)),
            float(opts.get(CONF_FIRE_DELTA_OFF)),
        )
        self._fire_takeover = fire_takes_over(
            self._fire,
            room_temp,
            self._fire_takeover,
            float(opts.get(CONF_FIRE_TEMP_MIN)),
            float(opts.get(CONF_FIRE_TEMP_OFF)),
        )
        if self.fire_force:
            self._fire = True
            self._fire_takeover = True

        # 3. Demande par zone
        deadband = float(opts.get(CONF_DEADBAND))
        samples: list[tuple[float | None, float | None, bool]] = []
        zdata: dict[str, dict[str, Any]] = {}
        demanding: set[str] = set()

        for zone in self.zones:
            temp = self._float_state(zone.temp_sensor)
            target = self.zone_target(zone.uid)
            zmode = self.zone_mode(zone.uid)
            # Hystérésis à deux seuils : l'état précédent de la zone compte.
            demand = zone_demands(
                temp, target, zmode, deadband, self._zone_demanding.get(zone.uid, False)
            )
            if zone.fire_room and self._fire_takeover:
                demand = False  # le feu chauffe la pièce : le gainable la lâche
            if mode == HVAC_FAN_ONLY:
                demand = zmode != HVAC_OFF
            if mode in (HVAC_HEAT, HVAC_COOL) and zmode not in (mode, HVAC_OFF):
                demand = False  # mode interdit : la zone n'est pas en phase
            self._zone_demanding[zone.uid] = demand
            if demand:
                demanding.add(zone.uid)
            samples.append((temp, target, demand))
            if target is not None and mode in (HVAC_HEAT, HVAC_COOL):
                seuil_demarrage = (
                    target - deadband if mode == HVAC_HEAT else target + deadband
                )
            else:
                seuil_demarrage = None
            zdata[zone.uid] = {
                "name": zone.name,
                "temp": temp,
                "target": target,
                "mode": zmode,
                "demand": demand,
                "seuil_demarrage": None
                if seuil_demarrage is None
                else round(seuil_demarrage, 2),
                "seuil_arret": target,
                "fire_room": zone.fire_room,
            }

        # 4. Clapets : demande + minimum de bouches (pression statique)
        dump_zone = next((z for z in self.zones if z.dump), None)
        dump_available = True
        if dump_zone is not None and mode in (HVAC_HEAT, HVAC_COOL):
            dtemp = self._float_state(dump_zone.temp_sensor)
            dtarget = self.zone_target(dump_zone.uid)
            if dtemp is not None and dtarget is not None:
                # ne pas ouvrir la décharge si elle est déjà au-delà de sa consigne
                dump_available = (
                    dtemp < dtarget if mode == HVAC_HEAT else dtemp > dtarget
                )
        wanted = apply_min_vents(
            {z.uid for z in self.zones},
            demanding,
            dump_zone.uid if dump_zone else None,
            int(opts.get(CONF_MIN_VENTS)),
            dump_available,
            open_vents_in=[
                damper
                for zone in self.zones
                if zone.uid in demanding
                for damper in zone.dampers
            ],
        )
        if mode == HVAC_FAN_ONLY:
            wanted = {z.uid for z in self.zones if self.is_zone_active(z.uid)}

        # Recalibration demandée : on force l'envoi à TOUS les clapets au cycle
        # suivant, que leur état corresponde déjà ou non. Comme la commande part
        # vers la position voulue (et non vers l'inverse), le clapet réellement
        # dans le bon état ne bouge pas d'un pouce : sa course est déjà finie et
        # `open_cover`/`close_cover` sur un volet déjà dans cet état ne
        # l'entraîne pas. C'est le moyen le moins intrusif de réaligner le réel
        # sur la croyance de l'intégration.
        force_all = self._force_dampers_next
        self._force_dampers_next = False
        await self._async_apply_dampers(wanted, force_all=force_all)

        # 5. Bouches réellement ouvertes (mesuré, pas commandé) — on compte les
        #    CLAPETS physiques : la salle à manger en a deux, donc deux bouches.
        open_vents = 0
        open_zone_names: list[str] = []
        for zone in self.zones:
            states = [self.hass.states.get(d) for d in zone.dampers]
            zone_open = [
                s
                for s in states
                if s is not None and s.state in (STATE_OPEN, STATE_OPENING)
            ]
            open_vents += len(zone_open)
            zdata[zone.uid]["open"] = bool(zone_open)
            zdata[zone.uid]["clapets_ouverts"] = len(zone_open)
            if zone_open:
                open_zone_names.append(zone.name)

        # 6. Moteur : mode, consigne, vitesse
        setpoint: float | None = None
        virtual: float | None = virtual_temperature(samples, mode)
        strategy = opts.get(CONF_STRATEGY)
        effective = strategy

        if mode == HVAC_FAN_ONLY:
            setpoint = None
            await self._async_engine_fan_only()
            await self._async_set_fan(choose_fan(open_vents, opts.get(CONF_FAN_THRESHOLDS)))
        elif demanding:
            # Stratégie déportée : le capteur peut disparaître (ESP hors ligne,
            # entité unavailable). Sans valeur déportée l'unité retomberait en
            # silence sur sa propre sonde — on repasse donc explicitement en
            # consigne génératrice jusqu'au retour de la mesure.
            if strategy == STRATEGY_REMOTE and virtual is None:
                effective = STRATEGY_GENERATOR
                _LOGGER.warning(
                    "Température déportée indisponible : repli sur la consigne génératrice"
                )
            if effective == STRATEGY_REMOTE:
                setpoint = house_setpoint(samples, mode, MIN_TEMP, MAX_TEMP, TEMP_STEP)
            else:
                reference = self._float_state(fire_zone.temp_sensor) if fire_zone else None
                if reference is None:
                    reference = self._attr(self.engine, "current_temperature")
                setpoint = generator_setpoint(
                    float(reference) if reference is not None else None,
                    mode,
                    float(opts.get(CONF_MARGIN)),
                    MIN_TEMP,
                    MAX_TEMP,
                    TEMP_STEP,
                )
            await self._async_set_engine(mode, setpoint)
            await self._async_set_fan(choose_fan(open_vents, opts.get(CONF_FAN_THRESHOLDS)))
        else:
            # Aucune demande : on ne coupe pas — repli + ventilation auto.
            fallback = float(
                opts.get(
                    CONF_FALLBACK_HEAT if mode == HVAC_HEAT else CONF_FALLBACK_COOL
                )
            )
            setpoint = snap(clamp(fallback, MIN_TEMP, MAX_TEMP), TEMP_STEP)
            await self._async_set_engine(mode, setpoint)
            await self._async_set_fan("auto")

        self._state = ZonageState(
            active=True,
            mode=mode,
            zones=zdata,
            fire=self._fire,
            fire_takeover=self._fire_takeover,
            open_vents=open_vents,
            engine_setpoint=setpoint,
            virtual_temp=virtual,
            strategy=effective,
        )
        return self._state

    # ─── écritures ──────────────────────────────────────────────────────────
    async def _async_apply_dampers(
        self, wanted: set[str], force: bool = False, force_all: bool = False
    ) -> None:
        """Ouvre/ferme les clapets voulus, en respectant la durée de cycle.

        `force` : ignore le verrou de cycle (utilisé à l'arrêt du système).
        `force_all` : renvoie l'ordre à **toutes** les zones, même celles dont
        l'état correspond déjà — c'est la recalibration, qui réaffirme la
        position voulue sans pour autant inverser quoi que ce soit.
        """
        now = time.monotonic()
        min_cycle = float(self.options.get(CONF_MIN_CYCLE))
        for zone in self.zones:
            states = [self.hass.states.get(d) for d in zone.dampers]
            known = [s for s in states if s is not None]
            if not known:
                continue
            should_open = zone.uid in wanted
            is_open = any(s.state in (STATE_OPEN, STATE_OPENING) for s in known)
            is_closed = all(s.state in (STATE_CLOSED, "closing") for s in known)
            if not force_all and should_open == is_open:
                continue
            if should_open and not is_closed and not (force or force_all):
                continue
            if not (force or force_all) and not should_open and not is_open:
                continue
            last = self._last_toggle.get(zone.uid, 0.0)
            if not (force or force_all) and now - last < min_cycle:
                _LOGGER.debug(
                    "Zone %s : cycle trop court (%.0fs < %.0fs), on attend",
                    zone.name,
                    now - last,
                    min_cycle,
                )
                continue
            service = SERVICE_OPEN_COVER if should_open else SERVICE_CLOSE_COVER
            await self.hass.services.async_call(
                "cover",
                service,
                {ATTR_ENTITY_ID: zone.dampers},
                blocking=False,
            )
            self._last_toggle[zone.uid] = now
            _LOGGER.debug("Zone %s : %s", zone.name, "ouverture" if should_open else "fermeture")

    async def _async_set_engine(self, mode: str, setpoint: float | None) -> None:
        """Consigne AVANT mode (piège : sinon décision prise sur l'ancienne consigne)."""
        state = self.hass.states.get(self.engine)
        if state is None:
            return
        if setpoint is not None and state.attributes.get("temperature") != setpoint:
            await self.hass.services.async_call(
                "climate",
                "set_temperature",
                {ATTR_ENTITY_ID: self.engine, "temperature": setpoint},
                blocking=False,
            )
        if state.state != mode:
            await self.hass.services.async_call(
                "climate",
                "set_hvac_mode",
                {ATTR_ENTITY_ID: self.engine, "hvac_mode": mode},
                blocking=False,
            )

    async def _async_set_fan(self, fan: str) -> None:
        state = self.hass.states.get(self.engine)
        if state is None or state.attributes.get("fan_mode") == fan:
            return
        supported = state.attributes.get("fan_modes") or []
        if supported and fan not in supported:
            _LOGGER.debug("Vitesse %s non supportée par %s", fan, self.engine)
            return
        await self.hass.services.async_call(
            "climate",
            "set_fan_mode",
            {ATTR_ENTITY_ID: self.engine, "fan_mode": fan},
            blocking=False,
        )

    async def _async_engine_fan_only(self) -> None:
        state = self.hass.states.get(self.engine)
        if state is not None and state.state != HVAC_FAN_ONLY:
            await self.hass.services.async_call(
                "climate",
                "set_hvac_mode",
                {ATTR_ENTITY_ID: self.engine, "hvac_mode": HVAC_FAN_ONLY},
                blocking=False,
            )

    async def _async_engine_off(self) -> None:
        state = self.hass.states.get(self.engine)
        if state is not None and state.state not in (HVAC_OFF, "unavailable"):
            await self.hass.services.async_call(
                "climate",
                "set_hvac_mode",
                {ATTR_ENTITY_ID: self.engine, "hvac_mode": HVAC_OFF},
                blocking=False,
            )

    # ─── actions appelées par les entités ───────────────────────────────────
    async def async_set_active(self, active: bool) -> None:
        """Master switch. La réactivation lève le verrou de cycle mini.

        Passer OFF ferme tous les clapets d'autorité (force) et horodate ce
        mouvement ; sans ce nettoyage, un retour sur ON dans les 5 minutes
        laisserait les clapets fermés alors que des pièces demandent, et
        l'utilisateur conclurait que le système ne redémarre pas.

        On rafraîchit **immédiatement** (`async_refresh`) et non via le
        debouncer : une action humaine sur le master switch doit être visible
        tout de suite, alors que `async_request_refresh` peut attendre la fin
        du cooldown (jusqu'à 10 s) — mesuré le 03/11/2026.
        """
        if active and not self.active:
            self._last_toggle.clear()
        self.active = active
        # Un nouvel ordre explicite (ON ou OFF) réarme la fermeture d'office des
        # clapets : en OFF on ne ferme qu'une fois, ensuite la main est à
        # l'utilisateur (ouverture manuelle, télécommande murale).
        self._off_closed = False
        await self.async_refresh()

    async def async_set_global_mode(self, mode: str) -> None:
        """Changer le mode global aligne les zones (garde-fou « mode interdit »)."""
        self.mode = mode
        if mode in (HVAC_HEAT, HVAC_COOL):
            for uid, zmode in list(self.zone_modes.items()):
                if zmode != HVAC_OFF:
                    self.zone_modes[uid] = mode
        await self.async_refresh()

    async def async_set_zone_target(self, uid: str, target: float) -> None:
        self.zone_targets[uid] = snap(clamp(target, MIN_TEMP, MAX_TEMP), TEMP_STEP)
        await self.async_request_refresh()

    async def async_set_zone_mode(self, uid: str, mode: str) -> None:
        if mode in (HVAC_OFF,):
            self.zone_modes[uid] = HVAC_OFF
        else:
            self.zone_modes[uid] = mode
        await self.async_request_refresh()

    def allowed_zone_modes(self) -> list[str]:
        """Modes qu'une zone peut prendre : `off`, ou le mode de la maison.

        Le mode global est l'autorité de saison. Une zone n'a donc pas de raison
        d'exposer un mode différent : en chaud elle propose `off`/`heat`, en
        froid `off`/`cool`, en ventilation seule `off`/`fan_only`. Cela évite
        deux impasses : une zone réglée dans le mode opposé (silencieusement
        ignorée) et, en ventilation seule, des zones qu'on ne pouvait plus
        réactiver puisqu'elles n'exposaient que `off`.
        """
        mode = self.mode if self.mode in (HVAC_HEAT, HVAC_COOL, HVAC_FAN_ONLY) else HVAC_HEAT
        return [HVAC_OFF, mode]

    @property
    def recalibration_demandee(self) -> bool:
        """Vrai tant que la réaffirmation des ordres n'a pas eu lieu."""
        return self._force_dampers_next

    def seed_zone_demand(self, uid: str, demanding: bool) -> None:
        """Réamorce l'hystérésis d'une zone au démarrage de HA.

        Sans ça, une pièce qui demandait au moment du redémarrage repart en
        « pas en demande » et attend de repasser sous le seuil de démarrage —
        elle resterait froide jusqu'à 0.7 °C de moins. `RestoreEntity` fournit
        la dernière valeur connue de l'attribut `demande`.
        """
        self._zone_demanding[uid] = bool(demanding)

    async def async_recalibrate_dampers(self) -> None:
        """Recalibration : réaffirmer la position voulue sur tous les clapets.

        Les clapets sont tout-ou-rien et ne renvoient **aucune** position :
        l'état dans HA n'est qu'une croyance. Après un déplacement manuel, une
        coupure pendant une course ou un ordre Stop, le réel peut diverger.

        On ne ferme donc **plus** tout pour rouvrir ensuite : on demande
        simplement à renvoyer l'ordre à chaque clapet au cycle suivant, dans la
        position déjà voulue, qu'il y ait changement d'état ou non. Aucun
        chauffage n'est interrompu, et un clapet réellement bien positionné ne
        bouge pas.
        """
        if self._force_dampers_next:
            _LOGGER.info("Recalibration déjà demandée, en attente du prochain cycle")
            return
        self._force_dampers_next = True
        _LOGGER.info(
            "Recalibration demandée : les ordres de clapet seront renvoyés au prochain cycle"
        )
        # Le cycle suivant part dans `cycle_seconds` au plus tard ; on ne force
        # pas un refresh immédiat, la demande n'est pas urgente et un cycle
        # propre évite de doubler une écriture déjà en cours.
        await self.async_request_refresh()
