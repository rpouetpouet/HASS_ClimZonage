#!/usr/bin/env python3
"""Analyse l'efficacité du zonage pièce par pièce, à partir de l'historique Home Assistant.

Aucune entité créée, aucun impact sur HA : on lit `/api/history`, on calcule, on imprime.

Métriques par pièce
-------------------
1. **Gain utile** (°C/h) — montée de température quand le clapet est ouvert ET que le
   compresseur produit. Mesure la puissance réellement livrée à la pièce.
2. **Dérive passive** (°C/h) — descente quand le clapet est fermé, la nuit, machine à
   l'arrêt. Mesure la déperdition du volume.
3. **Temps de satisfaction** — durée d'un épisode de demande, du clapet ouvert au retour
   au-dessus de la consigne − bande morte.
4. **Fréquence de demande** — nombre d'épisodes par 24 h (indicateur de sous-dimensionnement).

Filtres (sinon les chiffres mentent)
------------------------------------
* fenêtres « compresseur en marche » uniquement (Hz > 5) pour le gain ;
* fenêtres nocturnes (22 h → 7 h) et machine à l'arrêt pour la dérive ;
* les épisodes « cheminée » (binary_sensor feu) sont exclus ;
* la zone de décharge est signalée à part : elle est parfois ouverte pour la pression
  statique, pas parce qu'elle réclame de la chaleur ;
* résolution : 0.1 °C sur les sondes, 0.5 °C sur la consigne → fenêtres de 5 min minimum,
  intégration sur 30-60 min pour les débits (°C/h).

Usage
-----
    python3 tools/analyser_efficacite.py [--days 5] [--out rapport.md]

Les identifiants HA sont lus dans l'environnement (`HASS_URL`, `HASS_TOKEN`) ou, à défaut,
dans `~/.hermes/.env`.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

# ─── seuils de verdict (à ajuster si le ressenti contredit) ──────────────────
GOOD_GAIN = 0.30        # °C/h : en dessous, la pièce reçoit peu
BAD_DRIFT = -0.25       # °C/h : en dessous (plus négatif), la pièce perd vite
SLOW_SATISFACTION = 90  # minutes : au-delà, la pièce met trop longtemps
MANY_DEMANDS = 6        # épisodes / 24 h : au-delà, elle redemande sans cesse
OVERSHOOT = 0.5         # °C : dépassement moyen à la fin d'un épisode
MIN_WINDOWS = 12        # fenêtres de 5 min nécessaires pour publier une métrique
BIN = 300               # s : pas d'échantillonnage


# ─── accès HA ───────────────────────────────────────────────────────────────
def credentials() -> tuple[str, str]:
    url = os.environ.get("HASS_URL")
    token = os.environ.get("HASS_TOKEN")
    if not (url and token):
        env = Path.home() / ".hermes" / ".env"
        if env.exists():
            for line in env.read_text(encoding="utf-8", errors="ignore").splitlines():
                if line.startswith("HASS_URL=") and not url:
                    url = line.split("=", 1)[1].strip().strip('"').strip("'")
                elif line.startswith("HASS_TOKEN=") and not token:
                    token = line.split("=", 1)[1].strip().strip('"').strip("'")
    if not (url and token):
        sys.exit("HASS_URL / HASS_TOKEN introuvables (environnement ou ~/.hermes/.env)")
    return url.rstrip("/"), token


def api(url: str, token: str, path: str):
    req = urllib.request.Request(
        f"{url}{path}",
        headers={"Authorization": f"Bearer {token}"},
    )
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as err:  # noqa: TRY003
        print(f"HTTP {err.code} sur {path}", file=sys.stderr)
        raise


def states_snapshot(url: str, token: str) -> dict:
    return {e["entity_id"]: e for e in api(url, token, "/api/states")}


def history(url: str, token: str, entities: list[str], start: datetime, end: datetime):
    """Historique par tranches de 24 h (payload et mémoire bornés)."""
    out: dict[str, list[tuple[datetime, str, dict]]] = defaultdict(list)
    cursor = start
    while cursor < end:
        chunk_end = min(cursor + timedelta(days=1), end)
        query = urllib.parse.urlencode(
            {
                "filter_entity_id": ",".join(entities),
                "end_time": chunk_end.strftime("%Y-%m-%dT%H:%M:%SZ"),
                "minimal_response": "",
            }
        )
        path = f"/api/history/period/{cursor.strftime('%Y-%m-%dT%H:%M:%SZ')}?{query}"
        for series in api(url, token, path):
            if not series:
                continue
            eid = series[0]["entity_id"]
            for row in series:
                ts = datetime.fromisoformat(row["last_changed"])
                out[eid].append((ts, row.get("state"), row.get("attributes") or {}))
        cursor = chunk_end
    for eid in out:
        out[eid].sort(key=lambda r: r[0])
    return out


# ─── outils ─────────────────────────────────────────────────────────────────
def as_float(value) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def value_at(series, when: datetime):
    """Dernière valeur connue d'une série à un instant donné."""
    last = None
    for ts, state, attrs in series:
        if ts > when:
            break
        last = (state, attrs)
    return last


def bins(start: datetime, end: datetime):
    t = start
    while t < end:
        yield t
        t += timedelta(seconds=BIN)


def fmt(value: float | None, unit: str) -> str:
    return "n/d" if value is None else f"{value:+.2f} {unit}"


# ─── analyse ────────────────────────────────────────────────────────────────
def analyse(url: str, token: str, days: int) -> str:
    now = datetime.now(timezone.utc)
    start = now - timedelta(days=days)
    snap = states_snapshot(url, token)

    zones: list[dict] = []
    for eid, state in sorted(snap.items()):
        if not eid.startswith("climate.clim_zonage_"):
            continue
        attrs = state["attributes"]
        zones.append(
            {
                "name": eid.replace("climate.clim_zonage_", ""),
                "entity": eid,
                "sensor": attrs.get("sonde"),
                "dampers": attrs.get("clapets") or [],
            }
        )
    if not zones:
        return "Aucune zone `climate.clim_zonage_*` : intégration absente ou renommée."

    engine = "climate.clim_master"
    hz = "sensor.home_clim_master_compressor_frequency"
    outside = "sensor.home_clim_master_outside_air_temp"
    fire = "binary_sensor.clim_zonage_cheminee_feu_detecte"

    wanted = [engine, hz, outside, fire]
    for z in zones:
        if z["sensor"]:
            wanted.append(z["sensor"])
        wanted.extend(z["dampers"])
        wanted.append(z["entity"])
    wanted = [e for e in dict.fromkeys(wanted) if e in snap]

    print(f"Lecture de {len(wanted)} entités sur {days} jours…", file=sys.stderr)
    hist = history(url, token, wanted, start, now)

    stats = {}
    for z in zones:
        gain_samples, drift_samples, episodes = [], [], []
        current = None
        sat_temps, over_temps = [], []

        t = start + timedelta(seconds=BIN)
        while t < now:
            prev = t - timedelta(seconds=BIN)
            temp = as_float((value_at(hist.get(z["sensor"], []), t) or (None,))[0])
            temp_prev = as_float((value_at(hist.get(z["sensor"], []), prev) or (None,))[0])
            comp = as_float((value_at(hist.get(hz, []), t) or (None,))[0]) or 0.0
            fire_on = (value_at(hist.get(fire, []), t) or ("off",))[0] == "on"
            eng = (value_at(hist.get(engine, []), t) or ("off", {}))[1]
            consigne = as_float((eng or {}).get("temperature"))

            # clapets : au moins un ouvert ?
            opened = 0
            for damp in z["dampers"]:
                state = (value_at(hist.get(damp, []), t) or ("closed",))[0]
                if state in ("open", "opening"):
                    opened += 1

            if temp is not None and temp_prev is not None and not fire_on:
                delta = (temp - temp_prev) * (3600 / BIN)  # °C/h
                if abs(delta) < 5:  # saute les sauts de mesure aberrants
                    if opened and comp > 5:
                        gain_samples.append(delta)
                    elif not opened and comp <= 1 and (t.hour >= 22 or t.hour < 7):
                        drift_samples.append(delta)

            # épisodes de demande : on suit la demande calculée par l'intégration
            zone_state = (value_at(hist.get(z["entity"], []), t) or (None, {}))[1] or {}
            demande = zone_state.get("demande")
            if demande is True and current is None:
                current = {"start": t, "temp": temp, "consigne": consigne}
            elif demande is False and current is not None:
                current["end"] = t
                current["temp_end"] = temp
                if current.get("consigne") is not None:
                    if current.get("temp") is not None:
                        sat_temps.append(current["temp"])
                    if temp is not None:
                        over_temps.append(temp - current["consigne"])
                episodes.append(current)
                current = None
            t += timedelta(seconds=BIN)

        if current is not None:
            current["end"] = now
            episodes.append(current)

        def mean(values):
            return sum(values) / len(values) if len(values) >= MIN_WINDOWS else None

        durations = [
            (e["end"] - e["start"]).total_seconds() / 60
            for e in episodes
            if e.get("end")
        ]
        stats[z["name"]] = {
            "gain": mean(gain_samples),
            "gain_n": len(gain_samples),
            "drift": mean(drift_samples),
            "drift_n": len(drift_samples),
            "episodes": len(episodes),
            "median_min": sorted(durations)[len(durations) // 2] if durations else None,
            "overshoot": mean(over_temps) if len(over_temps) >= 3 else None,
            "decharge": z["name"] in ("salle_a_manger",),
        }

    # ─── rapport ────────────────────────────────────────────────────────────
    lines: list[str] = []
    period = "dernier jour" if days == 1 else f"{days} derniers jours"
    lines.append(f"**Efficacité du zonage — {period}**")
    lines.append("")
    ext = (value_at(hist.get(outside, []), now) or (None,))[0]
    total_ep = sum(s["episodes"] for s in stats.values())
    coverage = sum(
        1 for z in zones if hist.get(z["sensor"])
    )
    lines.append(
        f"T° extérieure actuelle : {ext if ext else 'n/d'} °C · "
        f"{total_ep} épisodes de demande sur la période · "
        f"{coverage}/{len(zones)} zones avec historique de sonde"
    )
    lines.append("")

    verdicts: list[str] = []
    for name, s in sorted(stats.items()):
        label = name.replace("_", " ")
        bits = []
        if s["gain"] is not None:
            bits.append(f"monte {s['gain']:+.2f} °C/h ({s['gain_n']} fen.)")
        else:
            bits.append(f"gain n/d ({s['gain_n']} fen.)")
        if s["drift"] is not None:
            bits.append(f"dérive nuit {s['drift']:+.2f} °C/h ({s['drift_n']} fen.)")
        else:
            bits.append(f"dérive n/d ({s['drift_n']} fen.)")
        bits.append(f"{s['episodes']} demande(s)")
        if s["median_min"] is not None:
            bits.append(f"médiane {s['median_min']:.0f} min")
        if s["overshoot"] is not None:
            bits.append(f"dépassement {s['overshoot']:+.2f} °C")
        suffix = " *(zone de décharge — hors efficacité)*" if s["decharge"] else ""
        lines.append(f"• **{label}** — " + " · ".join(bits) + suffix)

        if s["decharge"]:
            continue
        if s["gain"] is not None and s["gain"] < GOOD_GAIN:
            verdicts.append(
                f"**{label}** reçoit peu d'air chaud ({s['gain']:+.2f} °C/h) : bout de réseau, "
                "gaine sous-dimensionnée ou bouche étranglée → vérifier le réglage de la "
                "bouche, sinon anticiper le départ de chauffe."
            )
        if s["drift"] is not None and s["drift"] < BAD_DRIFT:
            verdicts.append(
                f"**{label}** perd vite ({s['drift']:+.2f} °C/h la nuit) : c'est une déperdition, "
                "pas un problème de régulation → anticiper (chauffer plus tôt), pas pousser plus de débit."
            )
        if s["median_min"] is not None and s["median_min"] > SLOW_SATISFACTION:
            verdicts.append(
                f"**{label}** met {s['median_min']:.0f} min à être satisfaite : combinaison "
                "d'un gain faible et/ou d'une dérive forte → candidat à l'anticipation."
            )
        if s["episodes"] > MANY_DEMANDS * days:
            verdicts.append(
                f"**{label}** redemande {s['episodes'] / days:.1f} fois par jour : sous-dimensionnée "
                "ou consigne trop basse pour son usage."
            )
        if s["overshoot"] is not None and s["overshoot"] > OVERSHOOT:
            verdicts.append(
                f"**{label}** dépasse de {s['overshoot']:+.2f} °C en fin d'épisode : inertie faible "
                "face à la course de 67 s → augmenter sa bande morte."
            )

    lines.append("")
    if verdicts:
        lines.append("**Ce qu'il faudrait ajuster**")
        lines.extend(f"• {v}" for v in verdicts)
    else:
        lines.append(
            "**Ce qu'il faudrait ajuster** — rien de net sur cette période : soit le système est "
            "correctement réglé, soit il n'y a pas encore assez de matière (voir les compteurs "
            "de fenêtres ci-dessus, il en faut au moins 12 par métrique)."
        )

    lines.append("")
    lines.append(
        "_Rappel de lecture : le gain est mesuré compresseur en marche et clapet ouvert ; la "
        "dérive uniquement la nuit, clapet fermé, machine à l'arrêt ; les épisodes cheminée sont "
        "exclus. Les apports solaires (baies vitrées) gonflent artificiellement le gain l'après-midi._"
    )
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--days", type=int, default=5, help="profondeur d'analyse (défaut 5)")
    parser.add_argument("--out", help="écrit aussi le rapport dans ce fichier")
    args = parser.parse_args()

    url, token = credentials()
    report = analyse(url, token, args.days)
    print(report)
    if args.out:
        Path(args.out).write_text(report + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
