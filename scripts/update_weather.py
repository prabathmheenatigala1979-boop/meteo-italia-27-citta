#!/usr/bin/env python3
"""Generate a three-day, 27-city Italian forecast from ECMWF IFS Open Data.

The script downloads selected GRIB2 fields directly from ECMWF's public
open-data mirrors, extracts the nearest model grid point for each city,
aggregates the values by calendar day in Europe/Rome, validates the result,
and atomically replaces data/weather.json only when the output is complete.
"""

from __future__ import annotations

import json
import math
import os
import tempfile
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from eccodes import (
    codes_get,
    codes_grib_find_nearest,
    codes_grib_new_from_file,
    codes_release,
)
from ecmwf.opendata import Client


ROOT = Path(__file__).resolve().parents[1]
OUTPUT_PATH = ROOT / "data" / "weather.json"
ROME = ZoneInfo("Europe/Rome")

CITIES = [{'name': 'Ancona', 'region': 'Marche', 'lat': 43.6158, 'lon': 13.5189}, {'name': 'Bari', 'region': 'Puglia', 'lat': 41.1171, 'lon': 16.8719}, {'name': 'Bologna', 'region': 'Emilia-Romagna', 'lat': 44.4949, 'lon': 11.3426}, {'name': 'Bolzano', 'region': 'Trentino-Alto Adige', 'lat': 46.4983, 'lon': 11.3548}, {'name': 'Brescia', 'region': 'Lombardia', 'lat': 45.5416, 'lon': 10.2118}, {'name': 'Cagliari', 'region': 'Sardegna', 'lat': 39.2238, 'lon': 9.1217}, {'name': 'Campobasso', 'region': 'Molise', 'lat': 41.5603, 'lon': 14.6627}, {'name': 'Catania', 'region': 'Sicilia', 'lat': 37.5079, 'lon': 15.083}, {'name': 'Civitavecchia', 'region': 'Lazio', 'lat': 42.0924, 'lon': 11.7954}, {'name': 'Firenze', 'region': 'Toscana', 'lat': 43.7696, 'lon': 11.2558}, {'name': 'Frosinone', 'region': 'Lazio', 'lat': 41.6396, 'lon': 13.3412}, {'name': 'Genova', 'region': 'Liguria', 'lat': 44.4056, 'lon': 8.9463}, {'name': 'Latina', 'region': 'Lazio', 'lat': 41.4676, 'lon': 12.9037}, {'name': 'Messina', 'region': 'Sicilia', 'lat': 38.1938, 'lon': 15.554}, {'name': 'Milano', 'region': 'Lombardia', 'lat': 45.4642, 'lon': 9.19}, {'name': 'Napoli', 'region': 'Campania', 'lat': 40.8518, 'lon': 14.2681}, {'name': 'Palermo', 'region': 'Sicilia', 'lat': 38.1157, 'lon': 13.3615}, {'name': 'Perugia', 'region': 'Umbria', 'lat': 43.1107, 'lon': 12.3908}, {'name': 'Pescara', 'region': 'Abruzzo', 'lat': 42.4618, 'lon': 14.2161}, {'name': 'Reggio Calabria', 'region': 'Calabria', 'lat': 38.1113, 'lon': 15.6473}, {'name': 'Rieti', 'region': 'Lazio', 'lat': 42.4045, 'lon': 12.8567}, {'name': 'Roma', 'region': 'Lazio', 'lat': 41.9028, 'lon': 12.4964}, {'name': 'Torino', 'region': 'Piemonte', 'lat': 45.0703, 'lon': 7.6869}, {'name': 'Trieste', 'region': 'Friuli-Venezia Giulia', 'lat': 45.6495, 'lon': 13.7768}, {'name': 'Venezia', 'region': 'Veneto', 'lat': 45.4408, 'lon': 12.3155}, {'name': 'Verona', 'region': 'Veneto', 'lat': 45.4384, 'lon': 10.9916}, {'name': 'Viterbo', 'region': 'Lazio', 'lat': 42.4207, 'lon': 12.1077}]

PARAMETERS = ["2t", "10u", "10v", "tp", "tcc"]
FORECAST_STEPS = list(range(0, 73, 3))


def round_or_none(value: float | None, digits: int = 1) -> float | None:
    if value is None or not math.isfinite(value):
        return None
    return round(value, digits)


def weather_summary(precip_mm: float, cloud_fraction: float) -> tuple[str, str]:
    """Return a cautious Italian label and an accessible icon.

    Thunderstorms are deliberately not inferred from these fields alone.
    """
    if precip_mm >= 20:
        return "Pioggia a tratti intensa", "🌧️"
    if precip_mm >= 5:
        return "Pioggia probabile", "🌧️"
    if precip_mm >= 0.5:
        return "Possibili piogge o rovesci", "🌦️"
    if cloud_fraction >= 0.78:
        return "Molto nuvoloso", "☁️"
    if cloud_fraction >= 0.48:
        return "Parzialmente nuvoloso", "⛅"
    return "Prevalentemente sereno", "☀️"


def download_grib(target: Path) -> str:
    """Download from a public ECMWF cloud mirror without an API key."""
    errors: list[str] = []
    for source in ("aws", "google", "azure"):
        try:
            client = Client(
                source=source,
                model="ifs",
                resol="0p25",
                preserve_request_order=False,
            )
            client.retrieve(
                type="fc",
                stream="oper",
                time=0,
                step=FORECAST_STEPS,
                param=PARAMETERS,
                target=str(target),
            )
            if target.exists() and target.stat().st_size > 0:
                return source
            raise RuntimeError("Il file GRIB scaricato è vuoto.")
        except Exception as exc:  # noqa: BLE001
            errors.append(f"{source}: {type(exc).__name__}: {exc}")
            if target.exists():
                target.unlink()
    raise RuntimeError(
        "Impossibile scaricare i dati ECMWF dai mirror pubblici. "
        + " | ".join(errors)
    )


def parse_grib(path: Path) -> tuple[dict[str, dict[datetime, dict[str, float]]], datetime]:
    """Extract nearest-grid values for every city and forecast time."""
    samples: dict[str, dict[datetime, dict[str, float]]] = {
        city["name"]: defaultdict(dict) for city in CITIES
    }
    model_run: datetime | None = None

    with path.open("rb") as handle:
        while True:
            gid = codes_grib_new_from_file(handle)
            if gid is None:
                break
            try:
                short_name = str(codes_get(gid, "shortName"))
                if short_name not in PARAMETERS:
                    continue

                data_date = str(codes_get(gid, "dataDate"))
                data_time = int(codes_get(gid, "dataTime"))
                end_step = int(codes_get(gid, "endStep"))

                hour = data_time // 100
                minute = data_time % 100
                run_utc = datetime.strptime(data_date, "%Y%m%d").replace(
                    hour=hour,
                    minute=minute,
                    tzinfo=timezone.utc,
                )
                valid_utc = run_utc + timedelta(hours=end_step)
                if model_run is None or run_utc > model_run:
                    model_run = run_utc

                for city in CITIES:
                    nearest = codes_grib_find_nearest(
                        gid,
                        float(city["lat"]),
                        float(city["lon"]),
                        npoints=1,
                    )[0]
                    value = float(nearest.value)
                    samples[city["name"]][valid_utc][short_name] = value
            finally:
                codes_release(gid)

    if model_run is None:
        raise RuntimeError("Nessun messaggio GRIB valido trovato.")
    return samples, model_run


def aggregate_city(
    city: dict[str, Any],
    city_samples: dict[datetime, dict[str, float]],
    target_dates: list,
) -> dict[str, Any]:
    daily: dict[Any, dict[str, list[float] | float]] = {
        date: {
            "temperatures": [],
            "winds": [],
            "clouds": [],
            "precipitation": 0.0,
        }
        for date in target_dates
    }

    ordered_times = sorted(city_samples)
    previous_tp_m: float | None = None

    for valid_utc in ordered_times:
        values = city_samples[valid_utc]
        local_date = valid_utc.astimezone(ROME).date()

        current_tp_m = values.get("tp")
        precip_increment_mm = 0.0
        if current_tp_m is not None:
            if previous_tp_m is not None:
                precip_increment_mm = max(0.0, (current_tp_m - previous_tp_m) * 1000.0)
            previous_tp_m = current_tp_m

        if local_date not in daily:
            continue

        if "2t" in values:
            daily[local_date]["temperatures"].append(values["2t"] - 273.15)

        if "10u" in values and "10v" in values:
            wind_kmh = math.hypot(values["10u"], values["10v"]) * 3.6
            daily[local_date]["winds"].append(wind_kmh)

        if "tcc" in values:
            daily[local_date]["clouds"].append(
                min(1.0, max(0.0, values["tcc"]))
            )

        daily[local_date]["precipitation"] += precip_increment_mm

    forecasts = []
    italian_days = ["Oggi", "Domani", "Dopodomani"]

    for index, date in enumerate(target_dates):
        item = daily[date]
        temperatures = item["temperatures"]
        winds = item["winds"]
        clouds = item["clouds"]
        precip = float(item["precipitation"])

        if not temperatures:
            raise RuntimeError(f"Dati temperatura mancanti per {city['name']} il {date}.")

        cloud_mean = sum(clouds) / len(clouds) if clouds else 0.0
        description, icon = weather_summary(precip, cloud_mean)

        forecasts.append(
            {
                "day_label": italian_days[index],
                "date": date.isoformat(),
                "description": description,
                "icon": icon,
                "temperature_min_c": round_or_none(min(temperatures)),
                "temperature_max_c": round_or_none(max(temperatures)),
                "precipitation_mm": round_or_none(precip),
                "wind_max_kmh": round_or_none(max(winds) if winds else None, 0),
                "cloud_cover_percent": round_or_none(cloud_mean * 100.0, 0),
            }
        )

    return {
        "name": city["name"],
        "region": city["region"],
        "latitude": city["lat"],
        "longitude": city["lon"],
        "forecast": forecasts,
    }


def build_payload(
    samples: dict[str, dict[datetime, dict[str, float]]],
    model_run: datetime,
    source_mirror: str,
) -> dict[str, Any]:
    now_italy = datetime.now(ROME)
    today = now_italy.date()
    target_dates = [today + timedelta(days=offset) for offset in range(3)]

    city_results = [
        aggregate_city(city, samples[city["name"]], target_dates)
        for city in CITIES
    ]

    if len(city_results) != 27:
        raise RuntimeError(f"Numero città non valido: {len(city_results)}.")

    for city in city_results:
        if len(city["forecast"]) != 3:
            raise RuntimeError(f"Previsione incompleta per {city['name']}.")

    return {
        "status": "ok",
        "title": "Previsioni Meteo Italia — 27 città",
        "generated_at_italy": now_italy.isoformat(timespec="minutes"),
        "generated_at_label": now_italy.strftime("%d/%m/%Y alle ore %H:%M"),
        "timezone": "Europe/Rome",
        "model": "ECMWF IFS Open Data 0,25°",
        "model_run_utc": model_run.astimezone(timezone.utc).isoformat(timespec="minutes"),
        "model_run_label": model_run.astimezone(timezone.utc).strftime(
            "%d/%m/%Y — %H:%M UTC"
        ),
        "source_mirror": source_mirror,
        "forecast_type": "indicative_model_output",
        "notice_it": (
            "Previsioni indicative elaborate automaticamente dal modello ECMWF IFS. "
            "Non costituiscono un'allerta ufficiale. Per allerte e indicazioni di "
            "sicurezza consultare sempre la Protezione Civile e le autorità locali."
        ),
        "attribution": (
            "Dati: ECMWF Open Data, licenza CC BY 4.0. "
            "Elaborazione automatica: Meteo Italia 24."
        ),
        "cities": city_results,
    }


def atomic_write_json(payload: dict[str, Any]) -> None:
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(
        prefix="weather-",
        suffix=".json",
        dir=OUTPUT_PATH.parent,
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
        os.replace(temp_name, OUTPUT_PATH)
    finally:
        if os.path.exists(temp_name):
            os.unlink(temp_name)


def main() -> None:
    raw_path = ROOT / "ecmwf-forecast.grib2"
    try:
        source_mirror = download_grib(raw_path)
        samples, model_run = parse_grib(raw_path)
        payload = build_payload(samples, model_run, source_mirror)
        atomic_write_json(payload)
        print(
            f"OK: {len(payload['cities'])} città aggiornate — "
            f"run {payload['model_run_label']}."
        )
    finally:
        if raw_path.exists():
            raw_path.unlink()


if __name__ == "__main__":
    main()
