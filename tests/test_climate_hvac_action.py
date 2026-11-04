"""hvac_action des zones : la décharge doit se voir en FAN (0.12.3+).

Une tuile `tile` native suit `hvac_action` : `heating` -> flamme, `idle` -> horloge.
Une zone dont le clapet est ouvert SANS demande affichait une horloge, indiscernable
de « rien ne se passe » ; elle est désormais exposée en `FAN`, avec un attribut
`decharge` pour les automatisations.

Home Assistant n'est pas installé dans l'environnement de test : les modules
utilisés par `climate.py` sont simulés au minimum ci-dessous.
"""

from __future__ import annotations

import importlib
import sys
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


class _Enum:
    """Suffisant pour les comparaisons d'identite faites par le code."""

    def __init__(self, name):
        self.name = name
        self.value = name.lower()

    def __repr__(self):
        return f"<{self.name}>"


HVACAction = types.SimpleNamespace(
    OFF=_Enum("OFF"), HEATING=_Enum("HEATING"), COOLING=_Enum("COOLING"),
    IDLE=_Enum("IDLE"), FAN=_Enum("FAN"), DRYING=_Enum("DRYING"),
)
HVACMode = types.SimpleNamespace(
    OFF=_Enum("OFF"), HEAT=_Enum("HEAT"), COOL=_Enum("COOL"), HEAT_COOL=_Enum("HEAT_COOL"),
    FAN_ONLY=_Enum("FAN_ONLY"), DRY=_Enum("DRY"), AUTO=_Enum("AUTO"),
)


class _StubBase:
    """Base neutre : accepte la subscripton generique et `__init_subclass__`."""

    def __init__(self, *a, **k):
        self.coordinator = a[0] if a else k.get("coordinator")

    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__()

    def __class_getitem__(cls, item):
        return cls


class _CoordinatorEntity(_StubBase):
    pass


class _ClimateEntity(_StubBase):
    pass


class _RestoreEntity(_StubBase):
    pass


class _DataUpdateCoordinator(_StubBase):
    pass


mk("homeassistant")
mk("homeassistant.components")
mk("homeassistant.components.climate", ClimateEntity=_ClimateEntity,
   ClimateEntityFeature=types.SimpleNamespace(TARGET_TEMPERATURE=1),
   HVACAction=HVACAction, HVACMode=HVACMode)


class _ConstModule(types.ModuleType):
    """Rend n'importe quelle constante HA connue sous forme de chaine."""

    def __getattr__(self, name):
        if name.startswith("UnitOf"):
            return types.SimpleNamespace(CELSIUS="°C", FAHRENHEIT="°F")
        return name.lower()


const_mod = _ConstModule("homeassistant.const")
sys.modules["homeassistant.const"] = const_mod
const_mod.ATTR_TEMPERATURE = "temperature"
const_mod.UnitOfTemperature = types.SimpleNamespace(CELSIUS="°C")
mk("homeassistant.exceptions", HomeAssistantError=Exception, ServiceValidationError=Exception)
mk("homeassistant.helpers")
mk("homeassistant.helpers.entity", DeviceInfo=dict)
mk("homeassistant.helpers.restore_state", RestoreEntity=_RestoreEntity)
mk("homeassistant.helpers.update_coordinator", CoordinatorEntity=_CoordinatorEntity,
   DataUpdateCoordinator=_DataUpdateCoordinator, UpdateFailed=Exception)
mk("homeassistant.core", HomeAssistant=object, callback=lambda f: f)
mk("homeassistant.helpers.event",
   async_track_state_change_event=lambda *a, **k: (lambda: None),
   async_track_time_interval=lambda *a, **k: (lambda: None),
   EVENT_HOMEASSISTANT_STARTED="started")


class _MockDT:
    @staticmethod
    def utcnow():
        import datetime as _d
        return _d.datetime.now(_d.timezone.utc)

    @staticmethod
    def now():
        import datetime as _d
        return _d.datetime.now()


_dt_mod = mk("homeassistant.util.dt", **{k: getattr(_MockDT, k) for k in ("utcnow", "now")})
_util_mod = mk("homeassistant.util", slugify=lambda s: str(s).lower().replace(" ", "_").replace("'", "_"))
_util_mod.dt = _dt_mod
 # `from homeassistant.util import dt as dt_util`

pkg = types.ModuleType("cz")
pkg.__path__ = [str(COMPONENT_DIR)]
sys.modules["cz"] = pkg


climate = importlib.import_module("cz.climate")
const = importlib.import_module("cz.const")
coordinator = importlib.import_module("cz.coordinator")
HVACAction = sys.modules["homeassistant.components.climate"].HVACAction


class Data:
    def __init__(self, zones):
        self.zones = zones
        self.fire_takeover = False


class Coord:
    def __init__(self, zdata):
        self.data = Data({"sam": zdata})
        self.zone_modes = {}
        self.zone_targets = {}


class Zone:
    uid = "sam"
    name = "Salle a manger"
    dampers = ["cover.sam_east", "cover.sam_west"]
    temp_sensor = "sensor.sam"
    offset = 0.0
    fire_room = True


def entite(**zdata):
    base = {"mode": const.HVAC_HEAT, "demand": False, "open": False, "system_off": False}
    base.update(zdata)
    zone_climate = object.__new__(climate.ZoneClimate)
    zone_climate.coordinator = Coord(base)
    zone_climate.zone = Zone()
    return zone_climate


def test_coordinator_expose_strategy_generator():
    """Régression 0.12.4 : `STRATEGY_GENERATOR` était utilisé dans le repli
    « température déportée indisponible » sans être importé -> NameError au
    premier passage dans cette branche (stratégie `remote`, sonde muette)."""
    assert coordinator.STRATEGY_GENERATOR == "generator"


def test_decharge_ouverte_sans_demande_affiche_fan():
    e = entite(demand=False, open=True)
    assert e.hvac_action is HVACAction.FAN
    assert e.extra_state_attributes["decharge"] is True


def test_zone_en_demande_affiche_heating():
    e = entite(demand=True, open=True)
    assert e.hvac_action is HVACAction.HEATING
    assert e.extra_state_attributes["decharge"] is False


def test_clapet_ferme_sans_demande_affiche_idle():
    e = entite(demand=False, open=False)
    assert e.hvac_action is HVACAction.IDLE
    assert e.extra_state_attributes["decharge"] is False


def test_froid_en_demande_affiche_cooling():
    e = entite(mode=const.HVAC_COOL, demand=True, open=True)
    assert e.hvac_action is HVACAction.COOLING


def test_mode_ventilation_affiche_fan():
    e = entite(mode=const.HVAC_FAN_ONLY, demand=False, open=False)
    assert e.hvac_action is HVACAction.FAN


def test_systeme_arrete_prime_sur_tout():
    e = entite(system_off=True, demand=True, open=True)
    assert e.hvac_action is HVACAction.OFF


def test_mode_off_prime_sur_tout():
    e = entite(mode=const.HVAC_OFF, demand=True, open=True)
    assert e.hvac_action is HVACAction.OFF


def test_donnees_vides_sans_crash():
    e = object.__new__(climate.ZoneClimate)
    e.coordinator = Coord({})
    e.coordinator.data.zones = {}
    e.zone = Zone()
    assert e.hvac_action is HVACAction.IDLE
