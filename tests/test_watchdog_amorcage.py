"""Chien de garde des sondes : amorçage au démarrage et temporisation de l'alerte.

Régression du 04/11/2026 : après un redémarrage de HA, l'alerte « sonde(s)
indisponible(s) » partait **8 secondes après le boot** avec les 7 sondes listées,
parce que `_sensor_last_ok` était vide (`age is None` ⇒ tout en défaut).

Corrigé en 0.12.6 :
  * `async_setup` amorce `_sensor_last_ok` à « maintenant » pour chaque sonde
    essentielle ⇒ il faut réellement `sensor_timeout_min` sans mesure pour être
    en défaut ;
  * la notification n'est créée qu'en mode `degrade`, donc après le délai de
    grâce (`sensor_grace_s`), comme le gel des décisions.

Home Assistant est simulé au minimum (mêmes stubs que test_climate_hvac_action).
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
        return name.lower()


mk("homeassistant")
mk("homeassistant.components")
mk(
    "homeassistant.components.climate",
    ClimateEntity=_StubBase,
    ClimateEntityFeature=types.SimpleNamespace(TARGET_TEMPERATURE=1),
    HVACAction=types.SimpleNamespace(
        OFF="off", HEATING="heating", COOLING="cooling", IDLE="idle", FAN="fan"
    ),
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
logic = importlib.import_module("cz.logic")
const = importlib.import_module("cz.const")


class _States:
    """Aucun état connu : c'est exactement la situation au démarrage."""

    def get(self, entity_id):
        return None


class _FakeHass:
    def __init__(self):
        self.states = _States()
        self.data = {}

    def async_create_task(self, coro):
        # coroutine volontairement non exécutée : on la ferme pour éviter le
        # RuntimeWarning « never awaited ».
        coro.close()
        return None


class _Entry:
    entry_id = "test"
    data = {"engine_entity": "climate.clim_master", "fireplace_sensor": "sensor.cheminee"}
    options = {}


def _coordinator():
    zones = [
        coordinator_mod.Zone(uid="alice", name="Alice", temp_sensor="sensor.alice", dampers=["cover.a"]),
        coordinator_mod.Zone(uid="sam", name="SdM", temp_sensor="sensor.sam", dampers=["cover.s"]),
    ]
    c = coordinator_mod.ZonageCoordinator(_FakeHass(), _Entry(), zones, {})
    c.hass = _FakeHass()
    return c


# ─── amorçage ───────────────────────────────────────────────────────────────
def test_amorcage_remplit_sensor_last_ok_au_demarrage():
    c = _coordinator()
    avant = time.time()
    asyncio.run(c.async_setup())
    apres = time.time()

    attendus = {"climate.clim_master", "sensor.cheminee", "sensor.alice", "sensor.sam"}
    assert attendus <= set(c._sensor_last_ok), (
        f"non amorcées : {attendus - set(c._sensor_last_ok)}"
    )
    for eid, ts in c._sensor_last_ok.items():
        assert avant <= ts <= apres, f"{eid} amorcé avec un horodatage incohérent"


def test_pas_de_defaut_juste_apres_le_demarrage():
    """Le cas du 04/11 : aucune mesure encore disponible, aucune sonde en défaut."""
    c = _coordinator()
    asyncio.run(c.async_setup())
    watchdog, ko_zones = asyncio.run(c._async_watchdog({}))
    assert c.sensor_ko == {}, f"sondes déclarées muettes à t+0 : {sorted(c.sensor_ko)}"
    assert watchdog == logic.MODE_NORMAL
    assert ko_zones == set()


def test_defaut_apres_le_timeout():
    """Une sonde réellement muette au-delà du timeout doit être signalée."""
    c = _coordinator()
    asyncio.run(c.async_setup())
    vieux = time.time() - 3600  # 1 h sans mesure, timeout par défaut = 10 min
    for eid in list(c._sensor_last_ok):
        c._sensor_last_ok[eid] = vieux
    c._ko_since = vieux
    watchdog, ko_zones = asyncio.run(c._async_watchdog({}))
    # Le gainable n'est pas une « sonde essentielle » : le chien de garde ne
    # surveille que les sondes de zone et celle de la cheminée.
    assert set(c.sensor_ko) == {"sensor.cheminee", "sensor.alice", "sensor.sam"}
    assert watchdog == logic.MODE_DEGRADE  # grâce de 120 s largement dépassée
    assert ko_zones == {"alice", "sam"}


# ─── temporisation de l'alerte ──────────────────────────────────────────────
def test_watchdog_mode_gele_puis_degrade():
    now = 1000.0
    assert logic.watchdog_mode(0, None, now, 120) == logic.MODE_NORMAL
    assert logic.watchdog_mode(1, now - 30, now, 120) == logic.MODE_GELE
    assert logic.watchdog_mode(1, now - 300, now, 120) == logic.MODE_DEGRADE
    assert logic.watchdog_mode(1, None, now, 120) == logic.MODE_GELE


def _sonde_muette_depuis_une_heure(c):
    vieux = time.time() - 3600
    for eid in list(c._sensor_last_ok):
        c._sensor_last_ok[eid] = vieux
    c._ko_since = vieux


def test_pas_de_notification_pendant_la_fenetre_de_demarrage():
    """Cas réel du 04/11 : deux Aqara en `unknown` 10 min après le boot.

    Les décisions passent bien en `degrade` (protection rapide), mais aucune
    notification ne doit partir avant `STARTUP_NOTIFY_GRACE_S`.
    """
    c = _coordinator()
    asyncio.run(c.async_setup())
    _sonde_muette_depuis_une_heure(c)
    c._started_at = time.time()          # on vient de démarrer
    asyncio.run(c._async_watchdog({}))
    assert c.watchdog == logic.MODE_DEGRADE, "la protection des décisions doit rester rapide"
    assert c._ko_notified is False, "aucune notification ne doit partir pendant la fenêtre de démarrage"


def test_notification_apres_la_fenetre_de_demarrage():
    c = _coordinator()
    asyncio.run(c.async_setup())
    _sonde_muette_depuis_une_heure(c)
    c._started_at = time.time() - const.STARTUP_NOTIFY_GRACE_S - 60
    asyncio.run(c._async_watchdog({}))
    assert c._ko_notified is True, "après la fenêtre, une sonde réellement muette doit alerter"


def test_alerte_seulement_en_mode_degrade():
    """La notification n'est créée qu'après la grâce : on vérifie la condition."""
    c = _coordinator()
    asyncio.run(c.async_setup())
    c._ko_since = time.time() - 30      # encore dans la grâce
    asyncio.run(c._async_watchdog({}))
    gelé = c.watchdog
    c._ko_notified = False
    if gelé == logic.MODE_DEGRADE:
        raise AssertionError("le watchdog ne devrait pas être en degrade après 30 s")
    # et après la grâce
    c._ko_since = time.time() - 600
    for eid in list(c._sensor_last_ok):
        c._sensor_last_ok[eid] = time.time() - 3600
    asyncio.run(c._async_watchdog({}))
    assert c.watchdog == logic.MODE_DEGRADE
