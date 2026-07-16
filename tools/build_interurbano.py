#!/usr/bin/env python3
"""
Compacta el GTFS estático del **autobús interurbano de Cantabria** (NAP, feed BUS
Cantabria) a un JSON pequeño que la app embebe como asset y actualiza por
raw.githubusercontent.

El GTFS del NAP requiere login gratuito para descargarse
(https://nap.transportes.gob.es/Files/Detail/1363), así que este script NO lo
descarga: recibe el ZIP ya bajado.

Uso:
    python tools/build_interurbano.py 20260702_000020_BUS_Cantabria.zip

Escribe DOS ficheros con el mismo contenido:
    data/interurbano.json                     -> copia remota (actualización en caliente)
    src/assets/interurbano/interurbano.json   -> fallback embebido (offline)

Estructura del JSON (claves cortas; ver build_cantabria.py para el patrón hermano):
    {
      "generated": "2026-07-03T...Z",
      "agencies":  { agency_id: nombre },
      "stops":     { stop_id: [nombre, lat, lon] },
      "routes":    { route_id: [long_name, color, agency_id] },   # sin short_name en este feed
      "calendar":  { service_id: [L,M,X,J,V,S,D, start, end] },   # días 0/1, fechas YYYYMMDD
      "removed":   { service_id: [YYYYMMDD, ...] },               # calendar_dates (todos tipo 2 = quita)
      "trips":     { trip_id: [route_id, service_id, headsign] },
      "stop_times":{ trip_id: [[seq, "HH:MM:SS", stop_id], ...] } # hora = salida (== llegada en este feed)
    }
"""
import csv
import io
import json
import os
import sys
import zipfile
from datetime import datetime, timezone

DATA_PATH = "data/interurbano.json"
ASSET_PATH = "src/assets/interurbano/interurbano.json"


def _reader(zf: zipfile.ZipFile, name: str):
    """csv.DictReader sobre un .txt del zip, con cabeceras saneadas (BOM/espacios)."""
    raw = io.TextIOWrapper(zf.open(name), encoding="utf-8-sig", newline="")
    rdr = csv.DictReader(raw)
    rdr.fieldnames = [(f or "").strip() for f in rdr.fieldnames]
    for row in rdr:
        yield {(k or "").strip(): (v or "").strip() for k, v in row.items()}


def build(zip_bytes: bytes) -> dict:
    zf = zipfile.ZipFile(io.BytesIO(zip_bytes))

    agencies = {a["agency_id"]: a.get("agency_name", "") for a in _reader(zf, "agency.txt")}

    routes = {}
    for r in _reader(zf, "routes.txt"):
        routes[r["route_id"]] = [
            r.get("route_long_name", "") or r.get("route_short_name", ""),
            r.get("route_color", ""),
            r.get("agency_id", ""),
        ]

    stops = {}
    for s in _reader(zf, "stops.txt"):
        lat = float(s["stop_lat"]) if s.get("stop_lat") else None
        lon = float(s["stop_lon"]) if s.get("stop_lon") else None
        stops[s["stop_id"]] = [
            s.get("stop_name", ""),
            round(lat, 5) if lat is not None else None,
            round(lon, 5) if lon is not None else None,
        ]

    days = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
    calendar = {}
    for c in _reader(zf, "calendar.txt"):
        calendar[c["service_id"]] = [int(c.get(d, "0") or "0") for d in days] + [
            c.get("start_date", ""), c.get("end_date", "")
        ]

    # calendar_dates: en este feed TODOS son exception_type=2 (quitar servicio ese día).
    removed: dict[str, list] = {}
    for cd in _reader(zf, "calendar_dates.txt"):
        if cd.get("exception_type") == "2":
            removed.setdefault(cd["service_id"], []).append(cd["date"])
        else:
            # exception_type=1 (añadir) — no aparece hoy, pero lo dejamos anotado por si cambia.
            print(f"  aviso: calendar_dates tipo {cd.get('exception_type')} para {cd['service_id']} (no soportado como 'removed')")

    trips = {}
    for t in _reader(zf, "trips.txt"):
        trips[t["trip_id"]] = [
            t["route_id"], t["service_id"], t.get("trip_short_name", "")
        ]

    stop_times: dict[str, list] = {}
    for st in _reader(zf, "stop_times.txt"):
        tid = st["trip_id"]
        # arrival==departure en la práctica; guardamos una sola hora (la de salida).
        time = st.get("departure_time", "") or st.get("arrival_time", "")
        stop_times.setdefault(tid, []).append(
            [int(st["stop_sequence"]), time, st["stop_id"]]
        )
    for seq in stop_times.values():
        seq.sort(key=lambda s: s[0])

    return {
        "generated": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "agencies": agencies,
        "stops": stops,
        "routes": routes,
        "calendar": calendar,
        "removed": removed,
        "trips": trips,
        "stop_times": stop_times,
    }


def main() -> int:
    if len(sys.argv) < 2:
        print("Uso: python tools/build_interurbano.py <fichero_GTFS.zip>")
        return 2
    with open(sys.argv[1], "rb") as f:
        zip_bytes = f.read()
    print(f"GTFS: {sys.argv[1]} ({len(zip_bytes)/1e6:.2f} MB)")

    data = build(zip_bytes)
    print(
        f"{len(data['agencies'])} operadores, {len(data['routes'])} rutas, "
        f"{len(data['stops'])} paradas, {len(data['trips'])} viajes, "
        f"{len(data['stop_times'])} con horarios, {len(data['calendar'])} services, "
        f"{len(data['removed'])} con excepciones"
    )

    payload = json.dumps(data, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    for path in (DATA_PATH, ASSET_PATH):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as f:
            f.write(payload)
        print(f"Escrito {path}: {len(payload)/1e6:.2f} MB")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
