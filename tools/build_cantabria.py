#!/usr/bin/env python3
"""
Filtra el GTFS estático nacional de RENFE Cercanías al núcleo 62 (Cantabria) y
escribe un subconjunto compacto en `data/cantabria.json.gz`, que la app embebe
como asset y actualiza por raw.githubusercontent.

Diseño (ver memoria project_renfe_module): los 14 MB del zip y los 247 MB de
`stop_times.txt` descomprimido NUNCA tocan el móvil; se filtran aquí (PC o
GitHub Action) y se publican ~517 KB gzip.

Uso:
    python tools/build_cantabria.py                # descarga el zip y filtra
    python tools/build_cantabria.py fichero.zip    # usa un zip ya descargado

Estructura del JSON resultante (claves cortas para reducir tamaño):
    {
      "generated": "2026-06-19T04:00:00Z",
      "nucleo": "62",
      "stops":      { stop_id: [nombre, lat, lon] },
      "routes":     { route_id: [short_name, long_name] },
      "calendar":   { service_id: [L,M,X,J,V,S,D, start, end] },   # días 0/1
      "trips":      { trip_id: [route_id, service_id, headsign] },
      "stop_times": { trip_id: [[seq, arr, dep, stop_id], ...] }   # HH:MM:SS
    }
"""
import csv
import io
import json
import sys
import urllib.request
import zipfile
from datetime import datetime, timezone

GTFS_URL = "https://ssl.renfe.com/ftransit/Fichero_CER_FOMENTO/fomento_transit.zip"
NUCLEO = "62"  # Cantabria: route_id empieza por el núcleo
# JSON plano (no .gz): el empaquetado de Android descomprime los .gz de assets y
# les quita la extensión, así que un asset .gz se serviría como 404. git comprime
# el blob (~512 KB en el packfile) y raw.githubusercontent lo sirve con gzip en
# tránsito, de modo que el coste real de tamaño es el mismo que el .gz.
OUT_PATH = "data/cantabria.json"


def _reader(zf: zipfile.ZipFile, name: str):
    """csv.DictReader sobre un .txt del zip, con cabeceras saneadas.

    Las cabeceras GTFS de RENFE traen espacios de relleno y, a veces, BOM:
    hay que hacer strip de los fieldnames o los lookups por clave fallan.
    """
    raw = io.TextIOWrapper(zf.open(name), encoding="utf-8-sig", newline="")
    rdr = csv.DictReader(raw)
    rdr.fieldnames = [(f or "").strip() for f in rdr.fieldnames]
    for row in rdr:
        yield {(k or "").strip(): (v or "").strip() for k, v in row.items()}


def build(zip_bytes: bytes) -> dict:
    zf = zipfile.ZipFile(io.BytesIO(zip_bytes))

    # 1. routes del núcleo (route_id empieza por "62")
    routes = {}
    for r in _reader(zf, "routes.txt"):
        rid = r["route_id"]
        if rid.startswith(NUCLEO):
            routes[rid] = [r.get("route_short_name", ""), r.get("route_long_name", "")]

    # 2. trips de esas rutas
    trips = {}
    service_ids = set()
    for t in _reader(zf, "trips.txt"):
        if t["route_id"] in routes:
            tid = t["trip_id"]
            trips[tid] = [t["route_id"], t["service_id"], t.get("trip_headsign", "")]
            service_ids.add(t["service_id"])

    # 3. stop_times de esos trips (el fichero gigante: se recorre en streaming)
    stop_times: dict[str, list] = {}
    stop_ids = set()
    for st in _reader(zf, "stop_times.txt"):
        tid = st["trip_id"]
        if tid not in trips:
            continue
        stop_times.setdefault(tid, []).append([
            int(st["stop_sequence"]),
            st.get("arrival_time", ""),
            st.get("departure_time", ""),
            st["stop_id"],
        ])
        stop_ids.add(st["stop_id"])
    for seq in stop_times.values():
        seq.sort(key=lambda s: s[0])

    # 4. stops referenciados
    stops = {}
    for s in _reader(zf, "stops.txt"):
        sid = s["stop_id"]
        if sid in stop_ids:
            lat = float(s["stop_lat"]) if s.get("stop_lat") else None
            lon = float(s["stop_lon"]) if s.get("stop_lon") else None
            stops[sid] = [s.get("stop_name", ""), lat, lon]

    # 5. calendar de los services usados
    days = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
    calendar = {}
    for c in _reader(zf, "calendar.txt"):
        sid = c["service_id"]
        if sid in service_ids:
            calendar[sid] = [int(c.get(d, "0") or "0") for d in days] + [
                c.get("start_date", ""), c.get("end_date", "")
            ]

    return {
        "generated": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "nucleo": NUCLEO,
        "stops": stops,
        "routes": routes,
        "calendar": calendar,
        "trips": trips,
        "stop_times": stop_times,
    }


def main() -> int:
    if len(sys.argv) > 1:
        with open(sys.argv[1], "rb") as f:
            zip_bytes = f.read()
        print(f"Usando zip local: {sys.argv[1]} ({len(zip_bytes)/1e6:.1f} MB)")
    else:
        print(f"Descargando GTFS RENFE: {GTFS_URL}")
        req = urllib.request.Request(GTFS_URL, headers={"User-Agent": "tusTusPlus-build"})
        with urllib.request.urlopen(req, timeout=120) as resp:
            zip_bytes = resp.read()
        print(f"Descargado: {len(zip_bytes)/1e6:.1f} MB")

    data = build(zip_bytes)
    print(
        f"Núcleo {NUCLEO}: {len(data['stops'])} paradas, {len(data['routes'])} rutas, "
        f"{len(data['trips'])} trips, {len(data['stop_times'])} con horarios, "
        f"{len(data['calendar'])} services"
    )

    payload = json.dumps(data, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    import os
    os.makedirs(os.path.dirname(OUT_PATH), exist_ok=True)
    with open(OUT_PATH, "wb") as f:
        f.write(payload)
    print(f"Escrito {OUT_PATH}: {len(payload)/1e6:.1f} MB JSON")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
