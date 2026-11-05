"""Constantes de l'intégration clim_zonage."""

DOMAIN = "clim_zonage"
NAME = "Clim Zonage"
VERSION = "0.13.3"      # doit suivre manifest.json (source de vérité pour HACS)

# ─── Mode du système : sélecteur à trois positions ──────────────────────────
# `AUTO`   : le zonage régule (comportement historique du master switch ON).
# `MANUEL` : toutes les vannes ouvertes une fois, puis plus aucune décision —
#            ni clapet, ni mode, ni consigne, ni vitesse. L'utilisateur reprend
#            la main sur le gainable (télécommande filaire ou entité climate).
# `ARRET`  : moteur éteint + clapets fermés une fois (ex-master switch OFF).
SYSTEM_AUTO = "auto"
SYSTEM_MANUEL = "manuel"
SYSTEM_ARRET = "arret"
SYSTEM_MODES = [SYSTEM_AUTO, SYSTEM_MANUEL, SYSTEM_ARRET]
SYSTEM_LABELS = {SYSTEM_AUTO: "Auto", SYSTEM_MANUEL: "Manuel", SYSTEM_ARRET: "Arrêt"}
SYSTEM_FROM_LABEL = {v: k for k, v in SYSTEM_LABELS.items()}

# Entité `select` du réglage 102 de l'unité (source de température : sonde
# interne / télécommande filaire / externe CN105). Optionnelles : sans elle,
# l'intégration ne touche pas au réglage et le mode MANUEL n'est pas complet.
CONF_TEMP_SOURCE_SELECT = "temp_source_select"

# Durée du « pic à 0 » envoyé au pont quand on passe en Manuel ou en Arrêt.
# Le firmware CN105, en recevant 0, arrête son keep-alive et envoie UN paquet
# « pas de température externe » : l'unité reprend alors le thermostat de la
# télécommande filaire. Au-delà de ce délai on republie « aucune valeur », pour
# ne pas laisser un 0 °C dans l'historique de la sonde.
ZERO_PULSE_S = 20

# Fenêtre pendant laquelle on réaffirme le mode du moteur après une écriture du
# réglage 102 : sur un gainable, écrire (ou même lire) un function setting peut
# ÉTEINDRE l'unité (issue #610 du fork, confirmée sur deux installations).
POWER_RESYNC_WINDOW_S = 120

# Intervalle minimal entre deux réaffirmations du réglage 102 HORS changement de
# mode. L'état de l'entité `select` retarde (il n'est rafraîchi qu'au poll ISU),
# donc on s'appuie sur l'ordre qu'on vient de donner, pas sur ce qu'elle affiche :
# une écriture par changement de mode, plus un filet de sécurité horaire au cas
# où l'unité aurait été modifiée au panneau entre-temps.
SOURCE_REASSERT_S = 3600

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
CONF_ZONE_OFFSET = "offset"            # °C — correction de calibration de la sonde (ajoutée à la lecture)

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
CONF_CYCLE_SECONDS = "cycle_seconds"
CONF_DAMPER_COURSE = "damper_course"
CONF_SENSOR_TIMEOUT_MIN = "sensor_timeout_min"
CONF_SENSOR_GRACE_S = "sensor_grace_s"
CONF_SENSOR_FROZEN_H = "sensor_frozen_h"

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
DEFAULT_CYCLE_SECONDS = 30     # période de la boucle de décision (30 s)
DEFAULT_DAMPER_COURSE = 80     # s — course d'un clapet (maxtime du Shelly : 80 s, course réelle 67 s)
DEFAULT_SENSOR_TIMEOUT_MIN = 10  # min — au-delà, une sonde est déclarée indisponible (chien de garde)
DEFAULT_SENSOR_GRACE_S = 120     # s — gel total des décisions après la perte d'une sonde
DEFAULT_SENSOR_FROZEN_H = 6.0    # h — au-delà, une sonde qui ne bouge plus est suspecte
# Fenêtre de démarrage pendant laquelle on n'ENVOIE PAS de notification de sonde
# manquante : au boot, les intégrations sources n'ont pas encore republié leurs
# valeurs (une Aqara ne parle qu'une fois par heure), donc tout paraît muet.
# Les décisions, elles, restent protégées par `sensor_timeout_min` + `sensor_grace_s`.
STARTUP_NOTIFY_GRACE_S = 1800   # s — 30 min
# Fenêtre pendant laquelle AUCUN clapet n'est commandé après l'initialisation :
# `RestoreEntity` n'a pas encore rendu les états des zones au premier cycle, donc
# le coordinateur lit « aucune demande » et ouvrirait la décharge en fermant les
# pièces. Mesuré le 04/11/2026 : 11 s d'écart entre le premier cycle et le retour
# de la vraie demande → mauvais état figé 5 min par `min_cycle`.
STARTUP_DAMPER_GRACE_S = 60     # s — 1 min

# ─── Plages de consigne acceptées par les unités CN105 ──────────────────────
MIN_TEMP = 16.0
MAX_TEMP = 31.0
TEMP_STEP = 0.5


HVAC_HEAT = "heat"
HVAC_COOL = "cool"
HVAC_OFF = "off"
HVAC_FAN_ONLY = "fan_only"
