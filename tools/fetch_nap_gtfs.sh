#!/usr/bin/env bash
# Descarga el GTFS estático del interurbano de Cantabria desde el NAP
# (nap.transportes.gob.es), que requiere login gratuito.
#
# El NAP no tiene API: es un formulario ASP.NET. Este script:
#   1. GET /Account/Login  -> cookie de sesión + __RequestVerificationToken
#   2. POST /Account/LogIn -> autentica (Email/Password + token)
#   3. GET  /Files/Detail/1363 (autenticado) -> extrae el enlace de descarga
#   4. descarga el ZIP
#
# Requiere las variables de entorno NAP_EMAIL y NAP_PASSWORD (regístrate gratis
# en el NAP como "usuario / consumidor de datos"). Uso:
#   NAP_EMAIL=... NAP_PASSWORD=... tools/fetch_nap_gtfs.sh salida.zip
#
# ⚠️ Frágil: si el NAP cambia el formulario o la ruta de descarga, ajústalo.
set -euo pipefail

OUT="${1:-cantabria_bus_gtfs.zip}"
FILE_ID="${NAP_FILE_ID:-1363}"          # id del dataset "BUS Cantabria" en el NAP
BASE="https://nap.transportes.gob.es"
: "${NAP_EMAIL:?Falta NAP_EMAIL}"
: "${NAP_PASSWORD:?Falta NAP_PASSWORD}"

JAR="$(mktemp)"
trap 'rm -f "$JAR"' EXIT

echo "1) Obteniendo token de login…"
LOGIN_HTML="$(curl -sS -c "$JAR" "$BASE/Account/Login")"
TOKEN="$(printf '%s' "$LOGIN_HTML" \
  | grep -oE '__RequestVerificationToken"[^>]*value="[^"]+"' \
  | sed -E 's/.*value="([^"]+)".*/\1/' | head -1)"
[ -n "$TOKEN" ] || { echo "ERROR: no se encontró __RequestVerificationToken"; exit 1; }

echo "2) Autenticando…"
curl -sS -b "$JAR" -c "$JAR" -X POST "$BASE/Account/LogIn" \
  --data-urlencode "Email=$NAP_EMAIL" \
  --data-urlencode "Password=$NAP_PASSWORD" \
  --data-urlencode "__RequestVerificationToken=$TOKEN" \
  --data-urlencode "ReturnUrl=/Files/Detail/$FILE_ID" \
  --data-urlencode "Remember=false" -o /dev/null

echo "3) Localizando enlace de descarga…"
DETAIL="$(curl -sS -b "$JAR" "$BASE/Files/Detail/$FILE_ID")"
# El botón de descarga (autenticado) deja de apuntar a /Account/Login.
DL="$(printf '%s' "$DETAIL" \
  | grep -oiE 'href="[^"]*(Download|Descarga)[^"]*"' \
  | sed -E 's/.*href="([^"]+)".*/\1/' \
  | grep -viE 'Account/Login' | head -1)"
if [ -z "$DL" ]; then
  echo "ERROR: no se encontró el enlace de descarga (¿login fallido? ¿cambió el HTML?)"; exit 1
fi
[ "${DL#http}" = "$DL" ] && DL="$BASE$DL"

echo "4) Descargando $DL"
curl -sS -b "$JAR" "$DL" -o "$OUT"
# Comprobar que es un ZIP (evita guardar una página de error/login).
if ! unzip -tqq "$OUT" >/dev/null 2>&1; then
  echo "ERROR: lo descargado no es un ZIP válido (posible sesión no autenticada)"; exit 1
fi
echo "OK: $OUT ($(wc -c < "$OUT") bytes)"
