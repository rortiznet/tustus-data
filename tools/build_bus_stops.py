#!/usr/bin/env python3
"""
Genera las paradas y líneas del autobús urbano de Santander (TUS) a partir del
GTFS oficial, para que la app no dependa de datos.santander.es.

## Por qué

La app sacaba las paradas (`paradas_bus.json`) y la tabla de líneas
(`lineas_bus.json`) del open data del Ayuntamiento. En noviembre de 2026
datos.santander.es pasó más de una semana cortando todas las conexiones: quien
instalaba la app se quedaba en "Actualizando paradas…" para siempre, y los
tiempos salían con el código interno de línea en vez de su número.

## Fuente

El GTFS que TUS publica en el Punto de Acceso Nacional (NAP) del Ministerio de
Transportes. Mobility Database guarda la última copia y la sirve sin clave:
    https://files.mobilitydatabase.org/mdb-2762/latest.zip

## Qué número es la parada (comprobado el 7/11/2026)

El GTFS trae dos: `stop_id` (99) y `stop_code` (PA100). El que usa TUS, y por
tanto la app y los favoritos guardados, es **el del poste**, `stop_code` sin
el prefijo PA. Se comprobó pidiendo tiempos a TUS de seis números cuyas dos
candidatas no comparten ninguna línea: en todos, las líneas eran las de la
parada del `stop_code`. De paso: la `line` que devuelve TUS es el `route_id`
del GTFS (71 = 7C1), y de ahí sale la tabla de líneas.

## Salida

Escribe DOS ficheros con el mismo contenido:
    data/bus-stops.json          -> copia remota (tustus-data, actualización en caliente)
    src/assets/bus/stops.json    -> fallback embebido (sin red)

    {
      "generated": "2026-11-07T21:30:00Z",
      "stops": [ {"ayto:numero","ayto:parada","ayto:sentido",
                  "wgs84_pos:lat","wgs84_pos:long"}, … ],
      "lines": { "<route_id>": "<número visible>", … }
    }

Las paradas usan los mismos nombres de campo que el open data, así que el resto
de la app no cambia. Los nombres vienen en MAYÚSCULAS y se pasan a mayúsculas
y minúsculas aquí; la app aplica después su limpieza de siempre.

Uso: python3 tools/build_bus_stops.py
"""
import collections
import csv
import io
import json
import pathlib
import re
import sys
import urllib.request
import zipfile
from datetime import datetime, timezone

GTFS_URL = "https://files.mobilitydatabase.org/mdb-2762/latest.zip"

RAIZ = pathlib.Path(__file__).resolve().parent.parent
SALIDA_REMOTA = RAIZ / "data" / "bus-stops.json"
SALIDA_ASSET = RAIZ / "src" / "assets" / "bus" / "stops.json"

# TUS tiene unas 460 paradas. Si salen muchas menos, el GTFS ha cambiado de
# forma o viene roto: mejor no escribir nada que publicar un listado cojo.
MINIMO_PARADAS = 300
MINIMO_LINEAS = 15

MINUSCULAS = {"de", "del", "la", "las", "el", "los", "y", "a", "en", "con", "por"}
SIGLAS = {"PCTCAN", "UIMP", "S/N", "IES", "CEIP", "ONCE"}


def titulo(texto: str) -> str:
    """'PASEO DE PEREDA 35' -> 'Paseo de Pereda 35'."""
    texto = re.sub(r"\s+", " ", texto or "").strip()

    def palabra(p: str, primera: bool) -> str:
        if p.upper() in SIGLAS or any(c.isdigit() for c in p):
            return p.upper()
        if not primera and p.lower() in MINUSCULAS:
            return p.lower()
        # Respeta guiones y abreviaturas: "PIQUIO-PZA.ITALIA" -> "Piquio-Pza.Italia",
        # "L.QUINTANILLA" -> "L.Quintanilla".
        trozos = re.split(r"([-.])", p)
        return "".join(
            t if t in "-." or t.upper() in SIGLAS else t[:1].upper() + t[1:].lower()
            for t in trozos
        )

    partes = texto.split(" ")
    return " ".join(palabra(p, i == 0) for i, p in enumerate(partes))


def leer(z: zipfile.ZipFile, nombre: str):
    with z.open(nombre) as f:
        yield from csv.DictReader(io.TextIOWrapper(f, encoding="utf-8-sig"))


def main() -> int:
    print(f"Descargando GTFS de TUS… ({GTFS_URL})")
    req = urllib.request.Request(GTFS_URL, headers={"User-Agent": "moviuca-data"})
    with urllib.request.urlopen(req, timeout=120) as r:
        z = zipfile.ZipFile(io.BytesIO(r.read()))

    lineas = {
        row["route_id"]: row["route_short_name"].strip()
        for row in leer(z, "routes.txt")
        if row["route_short_name"].strip()
    }
    viajes = {row["trip_id"]: row for row in leer(z, "trips.txt")}

    # Sentido = destino más habitual de los viajes que SALEN de la parada (en
    # la última parada del viaje el destino es ella misma y no dice nada).
    # Es lo que traía el open data: la app solo lo enseña cuando dos postes
    # enfrentados se llaman igual.
    ultimos: dict[str, tuple[int, str]] = {}
    pasos: list[tuple[str, str, int]] = []
    for row in leer(z, "stop_times.txt"):
        seq = int(row["stop_sequence"])
        pasos.append((row["trip_id"], row["stop_id"], seq))
        actual = ultimos.get(row["trip_id"])
        if actual is None or seq > actual[0]:
            ultimos[row["trip_id"]] = (seq, row["stop_id"])
    destinos: dict[str, collections.Counter] = collections.defaultdict(collections.Counter)
    for trip_id, stop_id, seq in pasos:
        if ultimos[trip_id][0] == seq:
            continue
        cabecera = (viajes.get(trip_id) or {}).get("trip_headsign", "").strip()
        if cabecera:
            destinos[stop_id][cabecera] += 1

    paradas = []
    vistos = set()
    for row in leer(z, "stops.txt"):
        if row.get("location_type") not in ("", "0", None):
            continue
        codigo = row["stop_code"].strip()
        m = re.fullmatch(r"PA(\d+)", codigo)
        if not m:
            print(f"  aviso: stop_code inesperado {codigo!r} ({row['stop_name']}), se omite")
            continue
        numero = str(int(m.group(1)))
        if numero in vistos:
            print(f"  aviso: número repetido {numero}, se omite el segundo")
            continue
        vistos.add(numero)
        sentido = destinos[row["stop_id"]].most_common(1)
        paradas.append({
            "ayto:numero": numero,
            "ayto:parada": titulo(row["stop_name"]),
            "ayto:sentido": titulo(sentido[0][0]) if sentido else "",
            "wgs84_pos:lat": row["stop_lat"].strip(),
            "wgs84_pos:long": row["stop_lon"].strip(),
        })
    paradas.sort(key=lambda p: int(p["ayto:numero"]))

    if len(paradas) < MINIMO_PARADAS or len(lineas) < MINIMO_LINEAS:
        print(f"\nERROR: {len(paradas)} paradas y {len(lineas)} líneas "
              f"(mínimos {MINIMO_PARADAS} y {MINIMO_LINEAS}). No se escribe nada.")
        return 1

    salida = {
        "generated": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "stops": paradas,
        "lines": lineas,
    }
    crudo = json.dumps(salida, ensure_ascii=False, separators=(",", ":"))
    for destino in (SALIDA_REMOTA, SALIDA_ASSET):
        destino.parent.mkdir(parents=True, exist_ok=True)
        destino.write_text(crudo + "\n", encoding="utf-8")

    print(f"\n{len(paradas)} paradas, {len(lineas)} líneas, {len(crudo)/1024:.1f} KB")
    for destino in (SALIDA_REMOTA, SALIDA_ASSET):
        print(f"  → {destino.relative_to(RAIZ)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
