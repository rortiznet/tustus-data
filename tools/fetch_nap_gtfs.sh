#!/usr/bin/env bash
# Descarga el GTFS estático del interurbano de Cantabria desde el NAP
# (nap.transportes.gob.es) usando su API oficial con ApiKey.
#
# Cómo obtener la ApiKey (gratis, instantánea):
#   1. Regístrate/inicia sesión en https://nap.transportes.gob.es
#   2. "Editar Perfil" → indica un nombre de aplicación → se te asigna la key.
#
# Variables de entorno:
#   NAP_API_KEY   (obligatoria) ApiKey UUID del NAP
#   NAP_FILE_ID   (opcional)    id del FICHERO GTFS; por defecto 1560
#
# OJO, aquí ya se metió la pata una vez: el NAP tiene DOS numeraciones
# distintas y no coinciden.
#
#   conjuntoDatoId 1363 = "Autobús en Cantabria"  (lo que se ve en la web)
#   ficheroId      1560 = su GTFS                 (lo que quiere esta API)
#   ficheroId      1363 = GTFS de la isla de MENORCA
#
# Pasar el id del conjunto a /Fichero/download devuelve 200 y un ZIP válido,
# solo que de otra provincia: entre julio y septiembre de 2026 esta Action
# publicó los autobuses de Menorca como si fueran los de Cantabria, y ninguna
# capa protestó. Para comprobar cuál es el fichero de un conjunto:
#
#   curl -H "ApiKey: $NAP_API_KEY" -H 'accept: application/json' \
#        https://nap.transportes.gob.es/api/Fichero/GetList
#                               (Autobús interurbano de Cantabria)
#
# Uso: tools/fetch_nap_gtfs.sh /tmp/bus_cantabria.zip
set -euo pipefail

OUT="${1:?uso: fetch_nap_gtfs.sh <salida.zip>}"
: "${NAP_API_KEY:?falta NAP_API_KEY (genérala en nap.transportes.gob.es → Editar Perfil)}"
FILE_ID="${NAP_FILE_ID:-1560}"

BASE="https://nap.transportes.gob.es/api"

echo "Descargando fichero $FILE_ID del NAP…"
HTTP=$(curl -sS -w "%{http_code}" -o "$OUT" \
  -H "ApiKey: $NAP_API_KEY" \
  -H "accept: application/octet-stream" \
  "$BASE/Fichero/download/$FILE_ID")

if [ "$HTTP" != "200" ]; then
  echo "ERROR: HTTP $HTTP al descargar el fichero $FILE_ID." >&2
  echo "Comprueba la ApiKey o localiza el id correcto con:" >&2
  echo "  curl -H \"ApiKey: \$NAP_API_KEY\" -H 'accept: application/json' $BASE/Fichero/GetList" >&2
  exit 1
fi

# Validar que es un ZIP (firma PK) y no un HTML de error.
if [ "$(head -c 2 "$OUT")" != "PK" ]; then
  echo "ERROR: la respuesta no es un ZIP (¿ApiKey inválida o id cambiado?)." >&2
  head -c 300 "$OUT" >&2; echo >&2
  exit 1
fi

echo "OK: $(du -h "$OUT" | cut -f1) → $OUT"
