#!/usr/bin/env python3
"""
Extrae las estaciones (aparcabicis recomendados) de TorreBici (Torrelavega) del
mapa público y escribe `data/torrebici.json`, que la app baja por
raw.githubusercontent para actualizar las ubicaciones sin recompilar.

Contexto (ver memoria project_torrebici): TorreBici es dockless sobre plataforma
RideMovi; NO hay API/JSON público ni tiempo real. La única fuente son las
estaciones incrustadas en un array JavaScript `misPuntos` dentro del HTML de
`torrebici.es/mapa.php`, con la forma:
    ["CE-01","43.35...","-4.05...","icon0","<popup HTML>"]
Aquí solo interesan los tres primeros campos: id, lat, lon.

Uso:
    python tools/build_torrebici.py                 # descarga y parsea la web
    python tools/build_torrebici.py mapa.html       # usa un HTML ya descargado

Salida `data/torrebici.json`:
    {
      "generated": "2026-07-01T04:00:00Z",
      "source": "https://www.torrebici.es/mapa.php",
      "count": 86,
      "stations": { "CE-01": [lat, lon], ... }   # ordenado por id
    }

Además regenera el fallback embebido `src/app/services/torrebici-stations.ts`
para mantener ambos en sync al ejecutarlo en local. La GitHub Action solo
commitea `data/torrebici.json` (actualización en caliente); el snapshot embebido
se refresca a mano cuando se quiera y se recompila la app.
"""
import json
import os
import re
import sys
import urllib.request
from datetime import datetime, timezone

URL = "https://www.torrebici.es/mapa.php"
OUT_JSON = "data/torrebici.json"
OUT_TS = "src/app/services/torrebici-stations.ts"

# Cada sub-array de misPuntos: sus tres primeros strings entrecomillados son
# id, lat, lon. Tolerante a espacios y a comillas simples o dobles.
TUPLE_RE = re.compile(
    r"""\[\s*['"]([^'"]+)['"]\s*,\s*['"]([^'"]+)['"]\s*,\s*['"]([^'"]+)['"]"""
)


def parse(html: str) -> dict[str, list[float]]:
    # Acotar al bloque misPuntos si existe, para no capturar otros arrays.
    m = re.search(r"misPuntos\s*=\s*\[(.*?)\]\s*;", html, re.S)
    block = m.group(1) if m else html

    stations: dict[str, list[float]] = {}
    for sid, lat_s, lon_s in TUPLE_RE.findall(block):
        sid = sid.strip()
        try:
            # La web mezcla decimales con punto y con coma (datos a mano).
            lat = float(lat_s.replace(",", "."))
            lon = float(lon_s.replace(",", "."))
        except ValueError:
            continue
        # Erratas de origen: alguna longitud viene sin el signo negativo.
        # Torrelavega está en el oeste (lon negativa) y en lat ~43.3-43.4.
        if lon > 0:
            lon = -lon
        if not (43.2 < lat < 43.45 and -4.15 < lon < -3.95):
            print(f"  aviso: {sid} fuera de rango ({lat},{lon}), se omite")
            continue
        stations.setdefault(sid, [round(lat, 6), round(lon, 6)])
    return dict(sorted(stations.items()))


def write_json(stations: dict, generated: str) -> None:
    os.makedirs(os.path.dirname(OUT_JSON), exist_ok=True)
    payload = {
        "generated": generated,
        "source": URL,
        "count": len(stations),
        "stations": stations,
    }
    with open(OUT_JSON, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, separators=(",", ":"))
        f.write("\n")
    print(f"Escrito {OUT_JSON}: {len(stations)} estaciones")


def write_ts(stations: dict, generated: str) -> None:
    rows = [f'  ["{sid}", {lat}, {lon}],' for sid, (lat, lon) in stations.items()]
    ts = (
        "// Estaciones (aparcabicis recomendados) de TorreBici — Torrelavega.\n"
        "// Servicio dockless sobre plataforma RideMovi; datos SOLO estáticos (id + coords),\n"
        "// extraídos del mapa público torrebici.es/mapa.php. Sin tiempo real.\n"
        "// FALLBACK EMBEBIDO: la app baja data/torrebici.json (más reciente) y usa esto\n"
        "// si no hay red. Regenerar con: python tools/build_torrebici.py\n"
        "// Errata de origen corregida: alguna longitud venía sin signo negativo.\n"
        f'export const TORREBICI_GENERATED = "{generated}";\n\n'
        "/** [id, lat, lon] */\n"
        "export const TORREBICI_STATIONS: ReadonlyArray<readonly [string, number, number]> = [\n"
        + "\n".join(rows)
        + "\n];\n"
    )
    with open(OUT_TS, "w", encoding="utf-8") as f:
        f.write(ts)
    print(f"Escrito {OUT_TS} (fallback embebido)")


def main() -> int:
    if len(sys.argv) > 1:
        with open(sys.argv[1], encoding="utf-8") as f:
            html = f.read()
        print(f"Usando HTML local: {sys.argv[1]}")
    else:
        print(f"Descargando {URL}")
        req = urllib.request.Request(URL, headers={"User-Agent": "tusTusPlus-build"})
        with urllib.request.urlopen(req, timeout=60) as resp:
            html = resp.read().decode("utf-8", "replace")

    stations = parse(html)
    if len(stations) < 50:
        print(f"ERROR: solo {len(stations)} estaciones; ¿cambió el HTML? Abortando.")
        return 1

    generated = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    write_json(stations, generated)
    write_ts(stations, generated)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
