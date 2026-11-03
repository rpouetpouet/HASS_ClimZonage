"""Constantes de l'intégration clim_zonage."""

DOMAIN = "clim_zonage"
NAME = "Clim Zonage"
VERSION = "0.1.0"

# ─── Clés de configuration (data de l'entrée) ────────────────────────────────
CONF_ENGINE = "engine_entity"          # climate.* du gainable (moteur)
CONF_FIREPLACE = "fireplace_sensor"    # sonde du panache de la cheminée
CONF_ZONES = "zones"                   # liste de dicts (voir plus bas)

# Clés d'une zone
CONF_ZONE_UID = "uid"
CONF_ZONE_NAME = "name"
CONF_ZONE_SENSOR = "temp_sensor"
CONF_ZONE_DAMPERS = "dampers"          # liste de cover.*
CONF_ZONE_FIRE_ROOM = "fire_room"      # la pièce où se trouve la cheminée (référence)
CONF_ZONE_DUMP = "dump_zone"           # zone de décharge / bypass pression statique

# ─── Options globales ───────────────────────────────────────────────────────
CONF_STRATEGY = "strategy"             # "generator" | "remote"
CONF_DEADBAND = "deadband"
CONF_MIN_CYCLE = "min_cycle"
CONF_MIN_VENTS = "min_vents"
CONF_MARGIN = "margin"
CONF_FALLBACK_HEAT = "fallback_heat"
CONF_FALLBACK_COOL = "fallback_cool"
CONF_FIRE_DELTA_ON = "fire_delta_on"
CONF_FIRE_DELTA_OFF = "fire_delta_off"
CONF_FIRE_TEMP_MIN = "fire_temp_min"
CONF_FIRE_TEMP_OFF = "fire_temp_off"
CONF_FAN_THRESHOLDS = "fan_thresholds"

STRATEGY_GENERATOR = "generator"
STRATEGY_REMOTE = "remote"
STRATEGIES = [STRATEGY_GENERATOR, STRATEGY_REMOTE]

# ─── Valeurs par défaut (UNE seule source : jamais de littéral dupliqué) ─────
DEFAULT_STRATEGY = STRATEGY_GENERATOR
DEFAULT_DEADBAND = 0.7         # °C — aligné sur l'ancienne tolérance ducted_hvac
DEFAULT_MIN_CYCLE = 300        # s — doit dépasser la course d'un clapet (67 s)
DEFAULT_MIN_VENTS = 2          # bouches ouvertes minimum (pression statique)
DEFAULT_MARGIN = 2.0           # °C — marge de la consigne génératrice
DEFAULT_FALLBACK_HEAT = 17.0   # °C — consigne de repli quand aucune zone ne demande
DEFAULT_FALLBACK_COOL = 28.0   # °C — idem en froid
DEFAULT_FIRE_DELTA_ON = 5.0    # °C — panache − ambiance : 5× le bruit mesuré hors feu
DEFAULT_FIRE_DELTA_OFF = 2.0   # °C — hystérésis de descente
DEFAULT_FIRE_TEMP_MIN = 19.0   # °C — la pièce doit être à ≥ 19 avant que le feu chauffe seul
DEFAULT_FIRE_TEMP_OFF = 18.0   # °C — hystérésis basse (bûche qui couve / pièce qui refroidit)
DEFAULT_FAN_THRESHOLDS = {"low": 2, "medium": 4, "high": 7}

# ─── Plages de consigne acceptées par les unités CN105 ──────────────────────
MIN_TEMP = 16.0
MAX_TEMP = 31.0
TEMP_STEP = 0.5

TICK_SECONDS = 30              # période du coordinateur

HVAC_HEAT = "heat"
HVAC_COOL = "cool"
HVAC_OFF = "off"
HVAC_FAN_ONLY = "fan_only"
