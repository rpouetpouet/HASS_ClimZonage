# Clim Zonage — manuel d'utilisation

Document de référence du pilotage du gainable réversible Mitsubishi de la maison.
Rédigé le 03/11/2026 par Marvin. Toutes les valeurs marquées « vérifié le » sont mesurées en live
sur l'instance Home Assistant `192.168.42.160`, pas recopiées d'une doc.

---

## 1. Vue d'ensemble

Il y a **un seul gainable réversible** (Clim Master) qui souffle dans **6 pièces** par un réseau de
gaines. Chaque pièce reçoit l'air par une **bouche** dont l'ouverture est commandée par un **clapet
motorisé** (vanne tout-ou-rien). L'unité chauffe ou refroidit une seule fois pour toute la maison ;
la répartition par pièce se fait **uniquement** par les clapets.

Le système fonctionne donc en trois couches :

1. **Le gainable** produit de l'air chaud ou froid, à une consigne et une vitesse de ventilation.
2. **Les 7 clapets** envoient cet air dans la pièce qui en a besoin, et seulement à elle.
3. **L'intégration `clim_zonage`** (maison, installée le 03/11/2026) décide, toutes les 30 secondes,
   qui a besoin de quoi et commande les deux couches précédentes.

Ce qui n'existe plus : ni automatisation YAML, ni helper, ni template dans la configuration de Home
Assistant. Toute la logique est dans le composant `custom_components/clim_zonage`, hébergé sur
`github.com/rpouetpouet/HASS_ClimZonage`.

---

## 2. L'inventaire (vérifié le 03/11/2026)

### Les zones

```text
Zone             Sonde d'ambiance                                  Clapet(s)
Batcave          sensor.batcave_temp_batcave_temperature           cover.batcave_valvebatcave
Salle de jeux    sensor.salle_de_jeux_tempsdj_temp                 cover.salle_de_jeux_valvesdj
Alice            sensor.alice_tempalice_temp                       cover.valvealice
Noémie           sensor.noemie_tempnoemie_temp                     cover.valvenoemie
Nous             sensor.nous_tempnous_temp                         cover.valvenous
Salle à manger    sensor.salle_a_manger_temp_sam_temperature        cover.sam_east + cover.sam_west
```

- Les **sondes du gateway Xiaomi** (`xiaomi_aqara`) font foi pour SdJ, Alice, Noémie et Nous. C'est
  une décision explicite : plusieurs pièces ont **deux** sondes vivantes et divergentes (Alice
  20.4 vs 19.6, Nous 23.0 vs 23.9). Les doublons BLE sont ignorés.
- Batcave et Salle à manger n'ont pas de sonde gateway : leurs sondes BLE sont les seules.
- La **Salle à manger** est une zone spéciale : c'est la plus grande pièce (90 m², plafond 4,70 m),
  elle contient **deux clapets** commandés ensemble, elle abrite **la sonde de reprise du gainable**,
  et elle contient la **cheminée**. Elle est aussi la **zone de décharge** (voir §5).

### Les moteurs

```text
Clim Master      climate.clim_master      ESPHome, pont CN105, IP 192.168.42.150 (gainable zoné)
Clim Extension   climate.clim_extension   ESPHome, pont CN105, IP 192.168.42.34 (non zoné, hors système)
```

### Ce qu'il ne faut pas confondre

- `sensor.salle_a_manger_tempfireplace_temp` = sonde du **panache de la cheminée**. Elle monte à
  40-45 °C quand la pièce ne gagne que 1,5 °C. **Jamais** utilisée comme température d'ambiance :
  elle sert uniquement de **détecteur de feu**.
- `sensor.salle_a_manger_towertree_temperature` = sonde d'un arbre en forme de tour, à 24-25 °C
  constants. Ne mesure pas la pièce, n'entre dans aucun calcul.
- `climate.clim_master.current_temperature` = la température **que voit l'unité**. Depuis le
  03/11/2026 ce n'est plus sa sonde interne, mais la **température déportée** envoyée par
  l'intégration (voir §6).

---

## 3. Les entités du système

| Entité | Ce que c'est |
|---|---|
| `climate.clim_zonage_<zone>` | Le thermostat d'une pièce : température mesurée, consigne, mode `off/heat/cool` |
| `switch.clim_zonage_systeme_actif` | **Master switch**. OFF = gainable éteint + tous les clapets fermés |
| `select.clim_zonage_mode_global` | Saison : `heat`, `cool` ou `fan_only` (ventilation seule) |
| `switch.clim_zonage_cheminee_chauffage_assure_par_le_feu` | Force ou interdit manuellement la prise en charge par le feu |
| `binary_sensor.clim_zonage_chauffage_en_demande` | Au moins une pièce réclame de la chaleur |
| `binary_sensor.clim_zonage_cheminee_feu_detecte` | Le panache est chaud : feu détecté |
| `binary_sensor.clim_zonage_cheminee_chauffage_assure_par_le_feu` | Le feu est autorisé à chauffer seul la pièce |
| `sensor.clim_zonage_zones_en_demande` | Nombre de pièces en demande (+ leur nom en attribut) |
| `sensor.clim_zonage_bouches_ouvertes` | Nombre de **zones** dont au moins un clapet est ouvert (la SaM, avec ses 2 clapets, compte pour 1) |
| `sensor.clim_zonage_consigne_moteur` | La consigne réellement envoyée au gainable |
| `sensor.clim_zonage_temperature_deportee` | La température « maison » calculée pour le gainable |
| `sensor.clim_zonage_strategie_moteur` | `remote` ou `generator`, et si un repli est actif |
| `button.clim_zonage_recalibrer_les_clapets` | Cycle forcé de tous les clapets (voir §4 bis) |

---

## 4. La loi de commande, pas à pas

Toutes les 30 secondes — et immédiatement à chaque changement de sonde, de consigne, de mode ou de
clapet — l'intégration exécute la même séquence.

### Étape 1 — le master switch

Si `switch.clim_zonage_systeme_actif` est **OFF** : gainable éteint, tous les clapets fermés, fin.
**C'est le seul chemin d'extinction du système.**

### Étape 2 — la cheminée

L'écart entre la sonde du panache et la sonde d'ambiance est calculé :

- écart ≥ **5 °C** → feu détecté (le bruit hors feu mesuré est de −1.0 à +0.4 °C, donc 5 est large)
- écart < **2 °C** pendant 15 min → feu éteint

Puis la **prise en charge** : le feu ne peut être le seul chauffage de la pièce que si la pièce est
**déjà à ≥ 19 °C**. En dessous, le gainable continue de chauffer — un feu allumé dans une pièce
froide reçoit donc le renfort du gainable. Désarmement si la pièce descend sous 18 °C (une bûche qui
couve garde un panache chaud alors que la pièce refroidit : c'est le plancher de température, pas
l'écart, qui protège).

### Étape 3 — la demande de chaque pièce

C'est une **hystérésis symétrique autour de la consigne** : `deadband` est la demi-largeur de la bande.

- en **chaud** : la pièce *entre* en demande sous `consigne − 0,7` et n'en *sort* qu'au-dessus de
  `consigne + 0,7` ;
- en **froid** : elle entre au-dessus de `consigne + 0,7` et sort sous `consigne − 0,7`.

Exemple, consigne 20,0 et bande 0,7 : démarrage à **19,3**, arrêt à **20,7**. Chaque thermostat expose
les deux seuils (`seuil_demarrage`, `seuil_arret`) — la loi de commande est lisible depuis le
dashboard, plus besoin de la deviner.

⚠️ **Pourquoi pas un simple seuil.** Un seuil unique démarre *et* arrête au même point : réévalué à
chaque cycle (30 s) et à chaque changement de sonde, il bascule sans arrêt quand la pièce flotte
autour du seuil (sondes à 0,1 °C de résolution). Et chaque bascule fait passer la consigne du moteur
de la consigne de maison au **repli** — donc commande le compresseur en marche/arrêt.

⚠️ **Pourquoi la bande est symétrique et pas arrêtée à la consigne.** L'unité a son **propre
différentiel de thermostat** (mesuré autour de 0,5 à 1 °C) : avec un arrêt pile à la consigne, la
demande tombait, le moteur repassait en repli, et il ne restait plus assez d'écart pour que l'unité
redémarre — la pièce plafonnait **0,5 °C sous sa cible** (mesuré : 18,9 à 19,4 pour une consigne de
20,0). En tenant la demande jusqu'à `consigne + 0,7`, le moteur reste armé sur la vraie consigne et
l'unité produit tant que son propre seuil est franchi : la pièce converge vers la cible.

**Conséquence à assumer** : une pièce légèrement **au-dessus** de sa consigne reste « en demande »
(donc clapet ouvert, action « chauffe ») jusqu'à +0,7. C'est le prix pour atteindre la cible en réel.
Pour resserrer, baisser `deadband` (0,35 donne une bande totale de 0,7 °C centrée sur la cible).

**Conséquence importante à retenir** : avec une consigne de 19,5, une pièce n'entre en demande
qu'en **dessous de 18,8 °C**. Si toutes les pièces sont à 20 °C, le système est à l'arrêt — ce n'est
pas une panne.

Si la pièce est en **prise en charge cheminée**, elle est retirée de la demande.
Chaque thermostat de pièce n'expose que **deux modes : `off` (la pièce ne reçoit rien) et le mode de
la maison** — `heat` en hiver, `cool` en été, `fan_only` en ventilation seule. Le mode de la maison
(`select.clim_zonage_mode_global`) est donc l'autorité de saison : inutile de régler chaque pièce, un
changement de saison réaligne automatiquement toutes les pièces. Une pièce restée dans un autre mode
est réalignée d'office au cycle suivant, pour qu'aucune carte n'affiche un mode qui ne serait ni
proposé ni honoré.

### 4 bis — Recalibrer les clapets (`button.clim_zonage_recalibrer_les_clapets`)

Un clapet est **tout-ou-rien et ne renvoie aucune position** : son état dans Home Assistant n'est
qu'une croyance. Après un déplacement manuel, une coupure de courant pendant une course ou un ordre
Stop, le réel peut avoir divergé.

Le bouton demande simplement à **renvoyer l'ordre à chaque clapet au cycle suivant**, dans la
position déjà voulue, **qu'il y ait changement d'état ou non**. Ce n'est pas un cycle de fermeture :
rien n'est inversé, aucun chauffage n'est interrompu, et un clapet réellement bien positionné ne
bouge pas (une commande vers la position où il se trouve déjà ne l'entraîne pas).

Vérifié en direct — appui du bouton, cycle suivant :

```
18:01:36  Recalibration demandée : les ordres seront renvoyés au prochain cycle
18:01:41  Zone Batcave : fermeture        Zone Noemie : ouverture (déjà ouverte, réaffirmée)
          Zone Salle de jeux : fermeture  Zone Nous : fermeture
          Zone Alice : fermeture          Zone Salle a manger : fermeture
```

Soit **6 zones / 7 clapets** réaffirmés en un cycle de 30 s, sans coupure. Le délai maximum
d'application est le `cycle_seconds` (30 s par défaut), exposé par l'attribut `delai_max_s`.

Utilisable depuis une automatisation (`button.press`) — par exemple une fois par semaine la nuit.

### Étape 3 bis — le chien de garde des sondes

Chaque tour de boucle vérifie que **toutes les sondes essentielles** répondent : la sonde de chaque
zone **et** la sonde de panache de la cheminée. Une sonde qui n'a plus donné de valeur numérique
depuis `sensor_timeout_min` (10 min par défaut) est déclarée **indisponible** — un `unavailable`
d'une seconde ne compte donc pas.

Trois états, exposés par `binary_sensor.clim_zonage_sondes_operationnelles` (attribut `mode`) :

| Mode | Déclenchement | Ce que fait l'intégration |
|---|---|---|
| `normal` | toutes les sondes répondent | fonctionnement nominal |
| `gele` | une sonde vient de tomber (pendant `sensor_grace_s`, 120 s) | **aucune écriture** : ni clapet, ni consigne, ni vitesse |
| `degrade` | la sonde est tombée depuis plus que la grâce | les zones valides continuent, les clapets des zones muettes sont laissés en l'état, une notification persistante est créée |

Le gel de 120 s est ce qui empêche un trou d'une seconde (rechargement de l'intégration, redémarrage,
entité momentanément `unavailable`) de déclencher un mouvement de clapets puis de se figer 20 minutes
sur le verrou `min_cycle` — incident réellement vécu le 03/11/2026.

Le détail est lisible dans `sensor.clim_zonage_sondes_indisponibles` (nombre + attributs `detail` :
nom de la sonde et minutes sans mesure).

### Étape 4 — les clapets

Les clapets des pièces en demande sont ouverts, les autres fermés. Deux garde-fous :

- **Durée de cycle minimum** (réglage `min_cycle`, 1200 s ici) : un clapet qui vient de bouger ne
  rebouge pas avant ce délai — sa course réelle est de 67 s, deux mouvements rapprochés l'useraient
  et fausseraient l'état.
- **Minimum de bouches (`min_vents`, réglé à 1)** : le seuil se compte en **clapets physiques** — la
  salle à manger en a deux, elle pèse donc deux bouches, et le total du réseau est de **7**. Si les
  pièces en demande n'ouvrent pas assez de volets, la **zone de décharge** (la salle à manger) est
  ouverte en plus pour ne pas étrangler le réseau de gaines. Elle est laissée fermée si elle est déjà
  au-dessus de sa consigne, ou si le feu est en prise en charge.

⚠️ **À quoi sert vraiment ce minimum.** Le gainable **n'adapte pas son débit au nombre de bouches
ouvertes** : il régule sur la température (reprise contre consigne) et son ventilateur n'a que
quelques vitesses fixes — en `auto` il suit la charge thermique, pas la perte de charge des gaines.
L'adaptation du débit vient donc de **nous**, par la vitesse de ventilation (1-2 bouches → `low`,
3-4 → `medium`, 5-7 → `high`). Le minimum de bouches n'est qu'un **filet de sécurité acoustique** :
il évite le cas extrême d'une seule bouche à vitesse minimale, où la vitesse d'air dans le gaine et
le souffle au diffuseur deviennent audibles. Son coût est réel (il peut chauffer une pièce qui n'a
rien demandé) : si aucune sifflement n'est constaté avec une seule bouche ouverte, le passer à **1**
rend le système purement piloté par la demande.

### Étape 5 — le gainable

**S'il y a au moins une pièce en demande** : mode `heat` (ou `cool`) et :

- en **stratégie déportée** (celle retenue) : la consigne envoyée est la **vraie consigne de
  maison** — la plus haute des consignes des pièces en demande en chaud, la plus basse en froid.
  L'unité compare ensuite cette consigne à la température déportée et module d'elle-même.
- en **stratégie génératrice** (repli) : consigne = température de la pièce de reprise + 2 °C, pour
  que le thermostat interne ne puisse jamais arrêter la production.

La **vitesse de ventilation** suit le nombre de zones ouvertes : 1-2 → `low`, 3-4 → `medium`,
5 et plus → `high`.

**S'il n'y a aucune pièce en demande : le gainable n'est pas éteint.** L'intégration passe en
**consigne de repli** (17 °C en chaud, 28 °C en froid) et en **ventilation `auto`**. L'unité
s'arrête d'elle-même par son propre thermostat, mais reste joignable : dès qu'une pièce redemande,
la consigne remonte et les clapets s'ouvrent. C'est ce qui supprime définitivement le blocage
« moteur coupé, plus rien ne le rallume » (déjà vécu 93 minutes).

---

## 5. Les deux stratégies moteur

**Le problème que les deux résolvent.** La sonde interne du gainable est dans la salle à manger.
Si on la laisse faire, l'unité croit la maison chaude dès que cette pièce est chaude (feu, soleil,
grande hauteur) et **arrête de chauffer alors que des chambres demandent encore**.

- **`generator`** — on neutralise le thermostat de l'unité : consigne = reprise + 2 °C, donc elle
  produit toujours. Toute la finesse vient des clapets, en tout-ou-rien. L'unité ne module plus sur
  la maison, la consigne affichée sur l'unité est fausse. Fonctionne avec le firmware d'origine.
- **`remote`** (retenue le 03/11/2026) — on garde le thermostat de l'unité mais on **remplace son
  thermomètre** : l'intégration lui envoie la température de la **plus froide des pièces en
  demande**. L'unité module, fait des cycles longs, s'arrête d'elle-même quand la maison est
  servie, et la consigne affichée est honnête.

**Garde-fou de la stratégie `remote`** : si la température déportée disparaît (ESP hors ligne,
entité indisponible), l'intégration repasse **d'elle-même** en `generator` et le signale
(`sensor.clim_zonage_strategie_moteur` → attribut `repli_actif: true`). Sans ça, l'unité retomberait
en silence sur sa sonde interne et on retrouverait le problème d'origine.

Bascule : options de l'intégration, sans redémarrage.

---

## 6. Pourquoi le firmware du pont a changé

Les deux ponts CN105 (Master et Extension) ont été reflashés le 03/11/2026 avec
`echavet/MitsubishiCN105ESPHome` (tag `2026.5.1`) au lieu du composant natif `mitsubishi_cn105`.

La raison unique et suffisante : **le composant natif ne permet pas d'envoyer une température
externe à l'unité**. Le fork l'expose (`remote_temperature_source`), avec un keep-alive de 20 s et un
retour automatique à la sonde interne après 15 minutes sans nouvelle valeur. C'est ce qui rend la
stratégie `remote` possible.

Ce qu'il apporte en plus, sans être nécessaire : température extérieure réelle, fréquence
compresseur, état de fonctionnement (`stage`) et sous-mode (`sub_mode`, par exemple `PREHEAT` au
démarrage ou un dégivrage). Utile au diagnostic, pas au pilotage.

Mesures de compilation (ESP8266 d1_mini, 4 Mo) : **flash 46,4 %**, **RAM 44,3 %**. Retour arrière
possible à tout moment avec les YAML sauvegardés (voir §10).

---

## 7. Le master switch et l'automatisation de présence

`switch.clim_zonage_systeme_actif` est le **point d'accroche unique** :

- **ON** : le système pilote librement, selon les consignes des pièces.
- **OFF** : tout s'arrête, et c'est le **seul** chemin d'extinction.

Ce qui se passe exactement en passant sur OFF (mesuré le 03/11/2026, effet en ~3 s) :

- le gainable reçoit `hvac_mode: off` ;
- **les 7 clapets sont fermés une seule fois**, à l'entrée en arrêt, sans attendre la durée de cycle
  minimum (course de 67 s). **Ensuite l'intégration ne les touche plus** : une ouverture manuelle d'un
  clapet — depuis le dashboard ou depuis la télécommande murale — tient, et l'état réel est reporté
  dans les entités (vérifié le 03/11/2026 : clapet ouvert à la main, toujours ouvert 2 minutes après) ;
- `sensor.clim_zonage_strategie_moteur` passe à `off`, la température déportée n'est plus envoyée
  (l'unité retomberait sur sa sonde interne après 15 min, sans conséquence puisqu'elle est éteinte) ;
- les thermostats de pièce **restent lisibles** : consigne et température affichées, action `off`.
  Leurs modes et consignes sont **mémorisés** — au rallumage, tout revient tel quel, immédiatement
  (le verrou de cycle minimum est levé exprès pour que les clapets puissent rouvrir tout de suite) ;
- l'état du switch **survit à un redémarrage** de Home Assistant.

Pendant l'arrêt, la télécommande murale reprend la main sans que rien ne vienne la contredire, et
aucun clapet ne bouge. C'est donc l'état à utiliser pour une absence, ou pour laisser un tiers
piloter à la main.

Une automatisation de présence peut passer le système en manuel en éteignant ce switch, sans
connaître l'intérieur du système. Aucune autre automatisation ne doit commander `climate.clim_master`
ni les clapets : elle serait écrasée au tick suivant, et c'est la porte ouverte aux incohérences.

---

## 8. Le dashboard « Chauffage »

Trois vues, accessibles depuis la barre latérale (`/chauffage-clim`) :

- **Pilotage** — le master switch, le mode global, la stratégie, une phrase de synthèse (pièces en
  demande, bouches ouvertes, consigne envoyée, température déportée), la tuile du gainable (consigne
  et vitesse réelles), et la carte cheminée (feu détecté, prise en charge, forçage manuel).
- **Zones** — les 6 thermostats de pièce (consigne et mode directement réglables) et l'état des 7
  clapets.
- **Diagnostic** — trois graphiques sur 24 h : consigne envoyée vs température déportée vs reprise du
  gainable ; les 6 pièces ; feu + bouches + demandes. Plus les capteurs du firmware (température
  extérieure, Hz compresseur, stage, sub-mode, source déportée).

---

## 9. Les réglages (options de l'intégration)

| Réglage | Valeur | Quand y toucher |
|---|---|---|
| `strategy` | `remote` | seulement pour revenir en `generator` (dépannage firmware) |
| `deadband` | 0.7 °C | **largeur de l'hystérésis** : écart entre le seuil de démarrage et l'arrêt (à la consigne). Augmenter si les clapets battent, diminuer pour une régulation plus serrée |
| `min_cycle` | 1200 s (20 min) | ne pas descendre sous la course d'un clapet (67 s) ; c'est un verrou par zone, pas un temps de réaction |
| `min_vents` | 1 | bouches ouvertes minimum (pression statique), comptées en **clapets physiques** (7 au total) : en dessous, la zone de décharge est ouverte pour ne pas étrangler le réseau |
| `margin` | 2.0 °C | **sans effet en `remote`** ; sert en `generator` |
| `cycle_seconds` | 30 s | période de la boucle de décision (10 à 900 s). Une action manuelle reste immédiate |
| `damper_course` | 80 s | durée de course d'un clapet, utilisée par la recalibration (course réelle 67 s) |
| `fallback_heat` / `fallback_cool` | 17 / 28 °C | consigne de repli quand aucune pièce ne demande |
| `fire_delta_on` / `fire_delta_off` | 5 / 2 °C | détection du feu (marge sur le bruit mesuré) |
| `fire_temp_min` / `fire_temp_off` | 19 / 18 °C | plancher de pièce pour laisser le feu chauffer seul |

Les consignes des pièces, elles, se règlent sur les thermostats de zone (dashboard, vue Zones), ou
dans l'interface de l'entité.

---

## 10. Diagnostic — symptôme, cause, action

| Symptôme | Cause probable | Action |
|---|---|---|
| Aucune pièce ne chauffe alors que le système est actif | aucune pièce sous `consigne − 0.7` | c'est normal ; monter la consigne d'une pièce |
| Une pièce demande mais son clapet ne bouge pas | durée de cycle minimum (300 s) en cours | attendre 5 min ; c'est volontaire |
| Le gainable ne suit pas la consigne attendue | température déportée indisponible → repli | regarder `sensor.clim_zonage_strategie_moteur` (attribut `repli_actif`) |
| Consigne envoyée = 17.0 et 0 bouche ouverte | repli : aucune pièce ne demande | vérifier les consignes des pièces |
| Une pièce chauffe alors que le feu tourne | prise en charge non armée (pièce < 19 °C) | c'est voulu ; voir §4 étape 2, ou forcer le switch cheminée |
| Le feu est ignoré et la pièce surchauffe | prise en charge désarmée ou cheminée forcée à OFF | vérifier `switch.clim_zonage_cheminee_...` |
| Plus rien ne réagit après un redémarrage de HA | l'intégration recharge ses états restaurés | attendre 30 s, vérifier `sensor.clim_zonage_strategie_moteur` |
| Le dashboard montre un clapet « ouvert » alors qu'il est fermé | position réelle non lue (clapet tout-ou-rien, sans retour de position) | l'état ne bascule qu'à la fin de la course |

---

## 11. Maintenance

- **Mise à jour de l'intégration** : HACS → `HASS_ClimZonage` → Mettre à jour, puis **redémarrage
  de Home Assistant** (obligatoire pour tout changement de code Python d'un composant custom).
- **Modification des zones ou des réglages** : options de l'intégration. Aucun redémarrage.
- **Mise à jour du firmware des ponts** : le composant est un composant externe épinglé au tag
  `2026.5.1`. Si ESPHome est mis à jour et que la compilation casse, c'est ici qu'il faut regarder ;
  les YAML d'origine et une procédure de retour arrière existent :
  - Master : `/config/_backup_esphome_master_20261103-160039/clim-master.yaml`
  - Extension : `/config/_backup_esphome_ext_20261103-153551/clim-extension.yaml`
- **Sauvegardes Home Assistant** : l'entrée, les options et les consignes des pièces sont restaurées
  automatiquement au redémarrage.
- **Ancienne intégration `ducted_hvac`** : supprimée (entrée + composant + dépôt HACS) le 03/11/2026.
  Sauvegarde du composant : `/config/_backup_ducted_hvac_20261103-154527.tgz`.

---

## 12. Paramètres constructeur de l'unité (function settings)

Le pont CN105 sait lire — et écrire — les réglages usine de l'unité (codes ISU Mitsubishi). Ils sont
exposés dans Home Assistant comme des `select` de diagnostic, sous l'appareil **Clim Master**.
**Les modifier écrit réellement dans l'unité** : ne pas y toucher par curiosité.

Valeurs lues le 03/11/2026 sur la Master :

```text
101  Redémarrage après coupure ............ OFF
102  Source de température ................ Externe (CN105 / WiFi)
103  Lien ventilation ..................... Aucun
105  Éco d'énergie auto ................... OFF
107  Signal filtre ........................ Aucune indication
108  Hauteur plafond / pression statique .. Plafond haut
109  Nombre de bouches .................... 4 directions (sans objet)
110  Logique mode auto .................... Confort
111  Géométrie d'aube ..................... non supporté
117  Logique de dégivrage ................. Standard
124  Offset chauffe +2 °C ................. ON
125  Ventilateur en thermo-off (chaud) .... Extra-bas
127  Ventilateur en thermo-off (froid) .... Vitesse imposée
128  Affichage erreur télécommande ........ ON
```

Ce qu'il faut en retenir :

- **102 = Externe (CN105/WiFi)** : c'est le réglage qui rend la température déportée autoritaire. Il
  est déjà sur la bonne valeur — la stratégie `remote` utilise le mécanisme prévu par l'unité, sans
  bidouille.
- **108 = Plafond haut** est déjà cohérent avec les 4,70 m.
- **124 = ON** (offset de +2 °C en chaud) : si la maison se stabilise à `consigne + 2`, c'est lui.
  À mesurer quand il fera franchement froid avant de décider d'une compensation.
- **125 = Extra-bas** : compresseur arrêté, le ventilateur continue de souffler de l'air non chauffé —
  ressenti comme un courant d'air froid dans les pièces à clapet ouvert. Candidat au passage sur
  « Arrêt », à tester d'abord pour le confort.
- **101 = OFF** : après une coupure de courant, l'unité **ne redémarre pas seule**. C'est à la reprise
  après coupure de la relancer.
- **111 non supporté** — le seul code que cette unité n'expose pas.
- Les capteurs d'énergie (`puissance_absorbee`, `energie_consommee`, `heures_de_fonctionnement`)
  renvoient 0 : cette unité ne les publie pas.

**Ce que le protocole ne fournit pas** : aucune horloge, aucune date, aucun programme horaire. Le
CN105 de ce composant n'expose ni réglage de l'heure ni plages de fonctionnement — les seules
horloges sont celles de Home Assistant, et c'est l'intégration qui décide *quand* chauffer.

## 13. Ce qui reste ouvert

- Les **helpers de l'ancien chantier ont été supprimés le 03/11/2026** : les 6 `switch.clapet_*` de
  `templates.yaml` (sauvegarde `/config/_backup_templates_clapets_20261103-161118/`) et le helper
  `input_select.clim_mode_zonage`. L'intégration commande directement les `cover` des clapets.
- Les **function settings** du fork (hauteur de plafond / pression statique, ventilation pendant le
  thermo-off) n'ont pas été testés sur la Master : certaines unités renvoient des zéros.
- Aucune automatisation de **présence** n'est encore branchée sur le master switch.
- La **vitesse `middle`** n'est pas utilisée par le mapping actuel ; à valider à l'oreille si besoin.
- Le pont de la **Clim SdB Nous** (`clim-sdbnous`) est resté sur le composant natif : cette unité
  n'appartient pas au zonage et n'a pas besoin de température déportée.
- **Mesure d'efficacité** : `tools/analyser_efficacite.py` calcule par pièce le gain utile, la dérive
  nocturne, le temps de satisfaction et la fréquence de demande ; un cron l'exécute chaque lundi 9 h
  et envoie le relevé. Premier verdict exploitable après quelques jours de chauffage réel, et les
  réglages par pièce (bande morte, anticipation, priorité de débit) ne seront ajoutés que si les
  données les réclament.
