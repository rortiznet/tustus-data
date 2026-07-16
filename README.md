# tustus-data

Datos abiertos que la app **tusTUS+** (transporte y movilidad de Santander/Cantabria)
descarga en caliente vía `raw.githubusercontent.com`, sin necesidad de recompilar
ni publicar una nueva versión de la app.

| Fichero | Contenido | Se actualiza |
|---|---|---|
| `data/cantabria.json` | Horario GTFS de Cercanías RENFE, filtrado al núcleo 62 (Cantabria) | lunes 04:00 UTC ([workflow](.github/workflows/renfe-data.yml)) |
| `data/torrebici.json` | Estaciones de TorreBici (Torrelavega) | lunes 04:15 UTC ([workflow](.github/workflows/torrebici-data.yml)) |
| `data/interurbano.json` | Horario GTFS del autobús interurbano de Cantabria (NAP) | lunes 04:30 UTC ([workflow](.github/workflows/interurbano-data.yml)) — requiere secretos `NAP_EMAIL`/`NAP_PASSWORD` |

Cada workflow solo commitea si el contenido cambió. `data/.last-run` es un
heartbeat semanal para que GitHub no pause los schedules por inactividad (60 días).

Los scripts de generación viven en [`tools/`](tools/) (copiados del repo privado
de la app). La app carga primero su asset embebido y aplica el JSON remoto solo
si su campo `generated` es más reciente.
