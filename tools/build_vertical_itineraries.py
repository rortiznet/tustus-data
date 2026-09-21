#!/usr/bin/env python3
"""
Construye el mapa **itinerario → tramos en orden** de los itinerarios verticales
de Santander (SantanView), para que la app pueda agrupar los tramos de una misma
subida bajo un solo panel.

## Por qué hace falta precalcularlo

La pertenencia de una instalación a un itinerario **solo viene en el detalle**
(`/api/facilities/:id`), no en el listado (`?bbox=`). Pedir las 87 fichas de
detalle son ~450 KB y casi dos minutos respetando la cuota del proxy: imposible
al arrancar la app. El mapa, en cambio, pesa unos 6 KB y cambia muy de tanto en
tanto, así que se genera aquí y la app se lo descarga hecho.

## Por qué no se deduce del nombre

Los nombres llevan "Tramo N" y a veces el itinerario entre paréntesis, así que
parece que bastaría. Medido contra la verdad el 17/9/2026: acierta 19 de 27
grupos, **mezcla 3 y parte 2**. Tres ejemplos de por qué:

  - `Calle de Valencia` tiene los tramos 1-2 como "Jose Hierro - Calle de
    Valencia" y el 3 como "Calle Islas Canarias - Calle de Valencia".
  - `Magallanes - Cisneros - Tramo 1` no está en NINGÚN itinerario, aunque los
    tramos 2 y 3 con ese mismo prefijo sí estén en `Calle Florida`.
  - `Cardenal Herrera Oria - Calle del Alheli - Tramo 1 (Calle de la Mimosa)`
    lleva esa etiqueta entre paréntesis y tampoco pertenece al itinerario.

O sea: hasta el paréntesis miente. El único dato fiable es `itineraries[]` del
detalle, y por eso este script lo recorre entero.

## Uso

    python3 tools/build_vertical_itineraries.py

Escribe DOS ficheros con el mismo contenido:
    data/vertical-itineraries.json              -> copia remota (actualización en caliente)
    src/assets/vertical/itineraries.json        -> fallback embebido (offline)

Estructura:
    {
      "generated": "2026-09-17T18:40:00Z",
      "itineraries": {
        "<itineraryId>": { "name": "Rio de la Pila", "steps": ["<facilityId>", ...] }
      }
    }

`steps` va ordenado por `stepOrder`. Las instalaciones que no aparecen en ningún
itinerario simplemente no salen aquí, y la app las pinta sueltas.
"""
import json
import pathlib
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone

# El proxy público de la app: guarda el token de SantanView en el servidor, así
# que este script no necesita credencial ninguna (ni el repo tustus-data, cuando
# lo ejecute su Action).
BASE = "https://moviuca-edge.rortiznet.deno.net/santanview"
BBOX = "-3.88,43.42,-3.74,43.51"

RAIZ = pathlib.Path(__file__).resolve().parent.parent
SALIDA_REMOTA = RAIZ / "data" / "vertical-itineraries.json"
SALIDA_ASSET = RAIZ / "src" / "assets" / "vertical" / "itineraries.json"

# El cuello de botella NO es nuestro proxy (120 lecturas/min por IP), sino
# SantanView: su enfriamiento se aplica a **nuestro token entero**, no por
# usuario. Medido el 21/9/2026 con una pausa de 0,4 s: las 76 primeras fichas
# entraron y de la 77 en adelante todas devolvieron 502, porque el proxy
# reenvía como 502 cualquier respuesta no-OK de arriba. La ejecución se cayó
# entera, que es lo correcto —mejor eso que publicar un mapa al que le faltan
# tramos— pero no hay que llegar ahí.
#
# Con 1,2 s son unos 105 s para las 87. Para un trabajo semanal da igual, y es
# mucho más considerado con un servicio que es de otra persona.
PAUSA_SEG = 1.2
TIEMPO_ESPERA = 30

# Reintentos por ficha, con espera creciente. Si aun así saltara el
# enfriamiento, esperar medio minuto suele bastar para que nos vuelva a
# atender; y si no, la ejecución falla sin escribir nada, como antes.
ESPERAS_REINTENTO = (5, 15, 40)

# Si un día la API deja de devolver itinerarios, es mejor no escribir nada que
# publicar un mapa vacío que desagruparía la lista entera en la app.
MINIMO_ITINERARIOS = 15


def pide(url: str) -> dict:
    """Una petición, reintentando si arriba nos han puesto en enfriamiento."""
    ultimo: Exception | None = None
    for espera in (0, *ESPERAS_REINTENTO):
        if espera:
            time.sleep(espera)
        try:
            req = urllib.request.Request(url, headers={"Accept": "application/json"})
            with urllib.request.urlopen(req, timeout=TIEMPO_ESPERA) as r:
                return json.load(r)
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as e:
            ultimo = e
    raise ultimo  # type: ignore[misc]


def main() -> int:
    print(f"Listando instalaciones… ({BASE})")
    lista = pide(f"{BASE}/api/facilities?bbox={BBOX}")["facilities"]
    print(f"  {len(lista)} instalaciones")

    itinerarios: dict[str, dict] = {}
    fallos = 0
    for i, f in enumerate(lista, 1):
        try:
            det = pide(f"{BASE}/api/facilities/{f['id']}?rangeDays=7")
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as e:
            print(f"  [{i}/{len(lista)}] fallo en {f['name']}: {e}")
            fallos += 1
            time.sleep(PAUSA_SEG)
            continue
        for it in det.get("itineraries") or []:
            entrada = itinerarios.setdefault(
                it["id"], {"name": it["name"], "steps": []}
            )
            entrada["steps"].append((it["stepOrder"], f["id"]))
        time.sleep(PAUSA_SEG)
        if i % 20 == 0:
            print(f"  [{i}/{len(lista)}]…")

    # Un fallo suelto de red no debe publicar un itinerario al que le falte un
    # tramo: eso se vería en la app como una subida más corta de lo que es.
    if fallos:
        print(f"\nERROR: {fallos} fichas no se pudieron leer; no se escribe nada.")
        return 1

    for entrada in itinerarios.values():
        entrada["steps"].sort()
        entrada["steps"] = [fid for _, fid in entrada["steps"]]

    if len(itinerarios) < MINIMO_ITINERARIOS:
        print(
            f"\nERROR: solo {len(itinerarios)} itinerarios (mínimo {MINIMO_ITINERARIOS}). "
            "¿Ha cambiado la API? No se escribe nada."
        )
        return 1

    agrupadas = sum(len(v["steps"]) for v in itinerarios.values())
    salida = {
        "generated": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "itineraries": itinerarios,
    }
    crudo = json.dumps(salida, ensure_ascii=False, separators=(",", ":"))
    for destino in (SALIDA_REMOTA, SALIDA_ASSET):
        destino.parent.mkdir(parents=True, exist_ok=True)
        destino.write_text(crudo + "\n", encoding="utf-8")

    print(f"\n{len(itinerarios)} itinerarios, {agrupadas} de {len(lista)} instalaciones agrupadas")
    print(f"  {len(lista) - agrupadas} quedan sueltas (sin itinerario)")
    print(f"  {len(crudo)/1024:.1f} KB")
    for destino in (SALIDA_REMOTA, SALIDA_ASSET):
        print(f"  → {destino.relative_to(RAIZ)}")
    print("\nReparto por número de tramos:")
    from collections import Counter
    for n, c in sorted(Counter(len(v["steps"]) for v in itinerarios.values()).items()):
        print(f"  {n} tramo(s): {c} itinerario(s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
