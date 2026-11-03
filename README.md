# HASS_ClimZonage

Intégration Home Assistant pour piloter un **gainable réversible zoné** (une unité
centrale + des clapets motorisés par pièce), née du besoin réel d'une maison où :

* la **sonde de reprise de l'unité** se trouve dans la plus grande pièce (90 m², 4,70 m
  de plafond) et non dans un couloir neutre ;
* cette même pièce abrite une **cheminée**, dont la sonde mesure le **panache**
  (elle monte de 20 °C quand la pièce ne gagne que 1,5 °C) ;
* les clapets sont **tout-ou-rien** (Shelly 2PM en `profile: cover`, actionneur
  Belimo, 67 s de course, aucune position en %) ;
* il ne faut **jamais** éteindre l'unité depuis le pilotage automatique, sous peine
  de ne plus savoir la rallumer (l'unité ne reçoit un ordre que sur *changement*).

Aucune automatisation, aucun template, aucun helper YAML : tout vit dans
l'intégration.

## Principes de conception

1. **Le moteur n'est jamais éteint par l'automatisme.** Quand aucune zone ne demande,
   l'intégration passe en **consigne de repli** (17 °C en chaud / 28 °C en froid) et en
   **ventilation `auto`**. Le thermostat interne de l'unité fait alors son travail, et
   l'unité reste joignable : dès qu'une zone redemande, la consigne remonte et les
   clapets s'ouvrent. Seul le **master switch** éteint réellement l'unité.
2. **La consigne du moteur ne dérive jamais d'un `min()`/`max()` des consignes de
   zone.** C'est l'erreur qui affame les autres pièces : dès que la pièce de reprise
   dépasse la consigne calculée (cheminée, soleil, grande hauteur), le compresseur
   s'arrête alors que des chambres demandent encore. Deux stratégies disponibles
   (§ Stratégies) règlent ce problème par construction.
3. **La cheminée est un détecteur, jamais une mesure.** L'écart panache − ambiance
   (≥ 5 °C pendant le cycle, redescente < 2 °C) détecte le feu ; la pièce ne peut
   déléguer son chauffage au feu que si elle est **déjà à ≥ 19 °C** (désarmement à
   18 °C). Un feu allumé dans une pièce froide reçoit donc le **renfort** du gainable.
4. **Le nombre de bouches ouvertes est une contrainte de pression statique** :
   en dessous du minimum configuré (défaut 2), la zone de décharge est ouverte pour
   ne pas étrangler le réseau ; la vitesse de ventilation suit le nombre de bouches.
5. **Aucune décision cachée** : les fonctions de décision sont pures et testées
   (`logic.py`, `tests/test_logic.py`), et le coordinateur ne fait que lire HA,
   appeler ces fonctions et écrire HA.

## Installation

HACS → *Intégrations* → ⋮ → *Dépôts personnalisés* → `https://github.com/rpouetpouet/HASS_ClimZonage`
(catégorie *Integration*), installer, puis **redémarrer Home Assistant**.

Un redémarrage est nécessaire à l'installation, et à chaque mise à jour du code Python.

## Configuration

Ajouter l'intégration **Clim Zonage**, puis :

1. **Moteur** : l'entité `climate` du gainable.
2. **Sonde de cheminée** (facultative) : la sonde du panache. Elle n'est jamais utilisée
   comme température d'ambiance.
3. **Zones** : pour chacune, un nom, une sonde d'ambiance, un ou plusieurs clapets
   (`cover`), et deux drapeaux — *pièce de la cheminée* et *zone de décharge*.

Les zones se modifient ensuite par **Configurer** (options flow) : réglages globaux,
ajout, édition, suppression. Une modification d'options recharge l'entrée, sans
redémarrage.

## Entités créées

| Entité | Rôle |
|---|---|
| `climate.clim_zonage_<zone>` | Thermostat de la pièce (Temp, Temp cible, modes `off/heat/cool`) |
| `switch.clim_zonage_systeme_actif` | **Master switch** — OFF = unité éteinte + clapets fermés. Point d'accroche unique pour une automatisation de présence |
| `select.clim_zonage_mode_global` | `heat` / `cool` / `fan_only` |
| `switch.clim_zonage_cheminee_chauffage_assure_par_le_feu` | Force / interdit manuellement la prise en charge par le feu |
| `binary_sensor.clim_zonage_chauffage_en_demande` | Au moins une zone demande |
| `binary_sensor.clim_zonage_cheminee_feu_detecte` | Feu détecté (panache) |
| `binary_sensor.clim_zonage_cheminee_chauffage_assure_par_le_feu` | Le feu est autorisé à chauffer seul (pièce ≥ 19 °C) |
| `sensor.clim_zonage_bouches_ouvertes` | Nombre de bouches réellement ouvertes |
| `sensor.clim_zonage_consigne_moteur` | Consigne réellement envoyée au gainable |
| `sensor.clim_zonage_temperature_deportee` | Température « maison » (zones en demande) |
| `sensor.clim_zonage_zones_en_demande` | Nombre + noms des zones en demande |
| `sensor.clim_zonage_strategie_moteur` | Stratégie réellement appliquée (+ `repli_actif`) |

## Stratégies moteur

* **`remote` (retenu le 03/11/2026)** — la consigne appliquée à l'unité est la **vraie consigne de
  maison** (la plus haute des consignes des zones en demande en chaud, la plus basse en froid) et
  l'unité régule sur la **température déportée** (§ capteur ci-dessous). Elle module d'elle-même,
  fait des cycles longs et s'arrête seule quand la maison est satisfaite. Nécessite un firmware
  ESPHome capable de recevoir une température externe : `echavet/MitsubishiCN105ESPHome` avec
  `remote_temperature_source` (le composant natif `mitsubishi_cn105` ne le permet pas).
  Vérifié sur ESP8266 `d1_mini` 4 Mo : flash 46,4 %, RAM 44,3 %.
  **Garde-fou** : si la température déportée disparaît (ESP hors ligne, entité `unavailable`),
  l'intégration repasse d'elle-même en `generator` et le signale (`sensor.clim_zonage_strategie_moteur`
  → `repli_actif: true`), au lieu de laisser l'unité retomber en silence sur sa sonde interne.
* **`generator`** — consigne = température de la pièce de reprise **+ marge** (2 °C) en chaud,
  **− marge** en froid, tant qu'une zone demande. Le thermostat interne ne peut plus arrêter la
  production, les clapets font la régulation. Fonctionne avec le firmware natif ; c'est aussi le
  mode de repli automatique.

La stratégie se change dans les options, sans redéploiement.

## Réglages globaux (options)

| Clé | Défaut | Sens |
|---|---|---|
| `strategy` | `generator` | voir ci-dessus |
| `deadband` | 0.7 °C | largeur de l'**hystérésis** : la zone démarre à `consigne − bande` et s'arrête à la consigne |
| `min_cycle` | 300 s | durée de cycle mini d'un clapet (course réelle 67 s) |
| `min_vents` | 2 | bouches ouvertes minimum (pression statique) |
| `margin` | 2.0 °C | marge de la consigne génératrice |
| `fallback_heat` / `fallback_cool` | 17 / 28 °C | repli quand aucune zone ne demande |
| `fire_delta_on` / `fire_delta_off` | 5 / 2 °C | hystérésis de détection du feu |
| `fire_temp_min` / `fire_temp_off` | 19 / 18 °C | plancher de pièce pour déléguer au feu |

## Dashboard

Un exemple de dashboard « Chauffage » (pilotage, zones, diagnostic) est fourni dans
[`docs/dashboard-example.yaml`](docs/dashboard-example.yaml).

## Relevé d'efficacité (hebdomadaire)

`tools/analyser_efficacite.py` lit `/api/history` (aucune entité créée, aucun impact sur HA) et
calcule, pièce par pièce : **gain utile** (°C/h clapet ouvert et compresseur en marche), **dérive
nocturne** (°C/h clapet fermé, machine à l'arrêt), **temps de satisfaction** (durée médiane d'un
épisode de demande) et **fréquence de demande**. Il en déduit des verdicts : pièce qui reçoit peu
d'air (bout de réseau, bouche étranglée → anticipation), pièce qui perd vite (déperdition → chauffer
plus tôt, pas plus de débit), pièce lente à servir, pièce qui redemande sans cesse, pièce qui dépasse
sa consigne (→ bande morte plus large).

    python3 tools/analyser_efficacite.py --days 7

Un cron Hermes (`Clim — efficacité par pièce (hebdo)`, job `ffaf93713c5a`) l'exécute chaque **lundi
9 h** via `~/.hermes/scripts/clim_efficacite.sh` et envoie le relevé sur Telegram.

## Licence

MIT.
