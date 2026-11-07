"""Priorité des clapets : amorçage au démarrage, et la décharge qui cède tout de suite.

Deux régressions constatées le 04/11/2026 :

1. **Course au démarrage.** Redémarrage de HA à 10:25:38 : les entités de zone sont
   recréées (`consigne=None temp=None demande=False`), le coordinateur lit « aucune
   demande » au premier cycle, ouvre la décharge et ferme les deux chambres. La
   vraie demande revient 11 s plus tard… et `min_cycle` fige ce mauvais état
   5 minutes. Correctif : pendant `STARTUP_DAMPER_GRACE_S` après l'initialisation,
   aucun clapet n'est commandé.

2. **La décharge ne doit pas attendre le verrou.** `min_cycle` protège les clapets
   contre le battement, mais l'appliquer à la fermeture d'un bypass de débit fait
   chauffer jusqu'à 5 min une pièce qui n'a rien demandé. Correctif : la fermeture
   de la zone de décharge ignore le verrou dès qu'une zone demande.

Home Assistant est simulé au minimum.
"""

from __future__ import annotations

import asyncio
import importlib
import sys
import time
import types
from pathlib import Path

COMPONENT_DIR = (
    Path(__file__).resolve().parents[1] / "custom_components" / "clim_zonage"
)


def mk(name, **attrs):
    m = types.ModuleType(name)
    for k, v in attrs.items():
        setattr(m, k, v)
    sys.modules[name] = m
    return m


class _StubBase:
    def __init__(self, *a, **k):
        self.coordinator = a[0] if a else k.get("coordinator")

    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__()

    def __class_getitem__(cls, item):
        return cls


class _ConstModule(types.ModuleType):
    def __getattr__(self, name):
        if name.startswith("UnitOf"):
            return types.SimpleNamespace(CELSIUS="°C", FAHRENHEIT="°F")
        if name.startswith("STATE_"):
            # STATE_OPEN -> "open", STATE_OPENING -> "opening", etc.
            return name[len("STATE_"):].lower()
        if name.startswith("SERVICE_"):
            # SERVICE_CLOSE_COVER -> "close_cover"
            return name[len("SERVICE_"):].lower()
        return name.lower()


mk("homeassistant")
mk("homeassistant.components")
mk(
    "homeassistant.components.climate",
    ClimateEntity=_StubBase,
    ClimateEntityFeature=types.SimpleNamespace(TARGET_TEMPERATURE=1),
    HVACAction=types.SimpleNamespace(OFF="off", HEATING="heating", COOLING="cooling", IDLE="idle", FAN="fan"),
    HVACMode=types.SimpleNamespace(
        OFF="off", HEAT="heat", COOL="cool", HEAT_COOL="heat_cool",
        FAN_ONLY="fan_only", DRY="dry", AUTO="auto",
    ),
)
const_mod = _ConstModule("homeassistant.const")
const_mod.ATTR_TEMPERATURE = "temperature"
const_mod.UnitOfTemperature = types.SimpleNamespace(CELSIUS="°C")
sys.modules["homeassistant.const"] = const_mod
mk("homeassistant.exceptions", HomeAssistantError=Exception, ServiceValidationError=Exception)
mk("homeassistant.helpers")
mk("homeassistant.helpers.entity", DeviceInfo=dict)
mk("homeassistant.helpers.restore_state", RestoreEntity=_StubBase)
mk(
    "homeassistant.helpers.update_coordinator",
    CoordinatorEntity=_StubBase,
    DataUpdateCoordinator=_StubBase,
    UpdateFailed=Exception,
)
mk("homeassistant.core", HomeAssistant=object, callback=lambda f: f)
mk(
    "homeassistant.helpers.event",
    async_track_state_change_event=lambda *a, **k: (lambda: None),
    async_track_time_interval=lambda *a, **k: (lambda: None),
    async_call_later=lambda *a, **k: (lambda: None),
    EVENT_HOMEASSISTANT_STARTED="started",
)
_dt = mk(
    "homeassistant.util.dt",
    utcnow=lambda: __import__("datetime").datetime.now(__import__("datetime").timezone.utc),
    now=lambda: __import__("datetime").datetime.now(),
)
_util = mk("homeassistant.util", slugify=lambda s: str(s).lower().replace(" ", "_"))
_util.dt = _dt

pkg = types.ModuleType("cz")
pkg.__path__ = [str(COMPONENT_DIR)]
sys.modules["cz"] = pkg

coordinator_mod = importlib.import_module("cz.coordinator")
const = importlib.import_module("cz.const")


# ─── stubs Home Assistant ───────────────────────────────────────────────────
class _State:
    """État minimal : `last_updated`/`last_changed` sont lus par le chien de garde."""

    def __init__(self, state, attributes=None, age_s: float = 5.0):
        import datetime as _d

        self.state = state
        self.attributes = attributes or {}
        horodatage = _d.datetime.now(_d.timezone.utc) - _d.timedelta(seconds=age_s)
        self.last_updated = horodatage
        self.last_changed = horodatage


class _States:
    def __init__(self, mapping):
        self.mapping = mapping

    def get(self, entity_id):
        return self.mapping.get(entity_id)


class _Services:
    def __init__(self):
        self.calls = []

    async def async_call(self, domain, service, data, blocking=False):
        self.calls.append((domain, service, dict(data)))


class _FakeHass:
    def __init__(self, mapping=None):
        self.states = _States(mapping or {})
        self.services = _Services()
        self.data = {}

    def async_create_task(self, coro):
        coro.close()
        return None


class _Entry:
    entry_id = "test"
    data = {"engine_entity": "climate.moteur", "fireplace_sensor": None}
    options = {}


def _coordinator(etats_clapets, options=None):
    zones = [
        coordinator_mod.Zone(uid="alice", name="Alice", temp_sensor="sensor.alice", dampers=["cover.valvealice"]),
        coordinator_mod.Zone(
            uid="sam", name="SdM", temp_sensor="sensor.sam",
            dampers=["cover.sam_east", "cover.sam_west"], fire_room=True, dump=True,
        ),
    ]
    hass = _FakeHass(etats_clapets)
    c = coordinator_mod.ZonageCoordinator(hass, _Entry(), zones, options or {})
    c.hass = hass
    # `active` est devenu une propriété en lecture (dérivée de system_mode).
    c.system_mode = coordinator_mod.SYSTEM_AUTO
    c.mode = "heat"
    c.zone_targets = {"alice": 21.0, "sam": 21.0}
    c.zone_modes = {"alice": "heat", "sam": "heat"}
    return c


def _ouvert(eid):
    return {eid: _State("open")}


def _ferme(eid):
    return {eid: _State("closed")}


# ─── 1. la décharge cède immédiatement ─────────────────────────────────────
def test_fermeture_de_la_decharge_ignore_le_verrou_quand_une_piece_demande():
    etats = {**_ouvert("cover.sam_east"), **_ouvert("cover.sam_west"), **_ferme("cover.valvealice")}
    c = _coordinator(etats, {const.CONF_MIN_CYCLE: 300})
    # la décharge vient de bouger : verrou armé
    c._last_toggle["sam"] = time.monotonic()
    c._last_toggle["alice"] = time.monotonic()
    asyncio.run(
        c._async_apply_dampers({"alice"}, demanding={"alice"})
    )
    services = [call[1] for call in c.hass.services.calls]
    fermetures = [call for call in c.hass.services.calls if call[1] == "close_cover"]
    assert any("cover.sam_east" in str(call[2]) for call in fermetures), (
        f"la décharge aurait dû être fermée malgré le verrou, appels : {services}"
    )


def test_ouverture_de_la_decharge_respecte_toujours_le_verrou():
    etats = {**_ferme("cover.sam_east"), **_ferme("cover.sam_west"), **_ferme("cover.valvealice")}
    c = _coordinator(etats, {const.CONF_MIN_CYCLE: 300})
    c._last_toggle["sam"] = time.monotonic()
    asyncio.run(c._async_apply_dampers({"sam"}, demanding=set()))
    assert c.hass.services.calls == [], (
        f"ouvrir la décharge doit attendre le verrou, appels : {c.hass.services.calls}"
    )


def test_zone_normale_respecte_le_verrou():
    etats = {**_ferme("cover.valvealice")}
    c = _coordinator(etats, {const.CONF_MIN_CYCLE: 300})
    c._last_toggle["alice"] = time.monotonic()
    asyncio.run(c._async_apply_dampers({"alice"}, demanding={"alice"}))
    assert c.hass.services.calls == [], "une zone de confort doit attendre le verrou"


def test_fermeture_de_la_decharge_sans_demande_attend_le_verrou():
    etats = {**_ouvert("cover.sam_east"), **_ouvert("cover.sam_west")}
    c = _coordinator(etats, {const.CONF_MIN_CYCLE: 300})
    c._last_toggle["sam"] = time.monotonic()
    asyncio.run(c._async_apply_dampers(set(), demanding=set()))
    assert c.hass.services.calls == [], "sans demande réelle, le verrou s'applique"


# ─── 2. amorçage : aucun clapet commandé juste après le démarrage ──────────
def test_amorcage_aucune_commande_de_clapet():
    etats = {
        "climate.moteur": _State("heat", {"temperature": 19.0, "fan_mode": "auto"}),
        "sensor.alice": _State("20.0"),
        "sensor.sam": _State("22.0"),
        **_ferme("cover.valvealice"),
        **_ouvert("cover.sam_east"),
        **_ouvert("cover.sam_west"),
    }
    c = _coordinator(etats, {const.CONF_MIN_CYCLE: 300})
    asyncio.run(c.async_setup())
    assert c._startup_damper_until > time.time(), "la fenêtre d'amorçage doit être armée"

    asyncio.run(c._async_update_data())
    clapets = [call for call in c.hass.services.calls if call[0] == "cover"]
    assert clapets == [], f"aucun clapet ne doit bouger pendant l'amorçage : {clapets}"


def test_apres_amorcage_les_clapets_bougent():
    etats = {
        "climate.moteur": _State("heat", {"temperature": 19.0, "fan_mode": "auto"}),
        "sensor.alice": _State("20.0"),
        "sensor.sam": _State("22.0"),
        **_ferme("cover.valvealice"),
        **_ouvert("cover.sam_east"),
        **_ouvert("cover.sam_west"),
    }
    c = _coordinator(etats, {const.CONF_MIN_CYCLE: 0})
    asyncio.run(c.async_setup())
    c._startup_damper_until = 0.0     # fenêtre écoulée
    asyncio.run(c._async_update_data())
    clapets = [call for call in c.hass.services.calls if call[0] == "cover"]
    assert any("cover.valvealice" in str(call[2]) for call in clapets), (
        f"Alice demande, son clapet doit s'ouvrir : {clapets}"
    )


# ─── 4. zone à deux clapets en état MIXTE (régression du 07/11/2026) ───────
def test_zone_mixte_recommande_le_clapet_reste_ferme():
    """sam_east ouvert mais sam_west fermé : la zone doit être rattrapée.

    L'ancienne décision `is_open = any(...)` considérait la zone comme « déjà
    ouverte » dès qu'un clapet l'était : le clapet resté fermé n'était plus
    jamais commandé et la salle à manger chauffait sur une seule bouche
    (constaté le 07/11/2026, après un échec de communication Shelly sur
    `cover.sam_west`). On attend désormais l'ordre vers `sam_west` seul.
    """
    etats = {**_ouvert("cover.sam_east"), **_ferme("cover.sam_west"), **_ferme("cover.valvealice")}
    c = _coordinator(etats, {const.CONF_MIN_CYCLE: 0})
    asyncio.run(c._async_apply_dampers({"sam"}, demanding={"sam"}))
    ouvertures = [call for call in c.hass.services.calls if call[1] == "open_cover"]
    assert ouvertures, f"la zone mixte doit être recomandée : {c.hass.services.calls}"
    cibles = str(ouvertures[0][2])
    assert "cover.sam_west" in cibles, f"sam_west devait être commandé : {cibles}"
    assert "cover.sam_east" not in cibles, (
        f"sam_east est déjà ouvert, inutile de le rejouer : {cibles}"
    )


# ─── 5. une zone déjà entièrement ouverte ne reçoit rien ───────────────────
def test_zone_deja_ouverte_n_est_pas_recommandee():
    """Pas de régression inverse : une zone complète ne doit rien recevoir."""
    etats = {**_ouvert("cover.sam_east"), **_ouvert("cover.sam_west"), **_ferme("cover.valvealice")}
    c = _coordinator(etats, {const.CONF_MIN_CYCLE: 0})
    asyncio.run(c._async_apply_dampers({"sam"}, demanding={"sam"}))
    assert c.hass.services.calls == [], (
        f"une zone déjà ouverte ne doit produire aucun appel : {c.hass.services.calls}"
    )
