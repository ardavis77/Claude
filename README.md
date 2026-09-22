# Buscador de vuelos redondos: CVG / IND / SDF -> ELP

Script en Python que busca vuelos en Google Flights (via la libreria
[`fast-flights`](https://pypi.org/project/fast-flights/)) desde:

- **CVG** - Cincinnati / Northern Kentucky
- **IND** - Indianapolis
- **SDF** - Louisville, Kentucky

hacia:

- **ELP** - El Paso, Texas

y arma combinaciones de **ida y vuelta**, quedandose solo con las que caben
en tu horario real:

- **Ida - miercoles**: cualquier hora (configurable con `--wednesday-afternoon-only`).
- **Ida - jueves y viernes**: solo vuelos que salen en la tarde (por defecto,
  desde las 12:00), porque esos dias trabajas desde casa y tienes mas
  flexibilidad.
- **Vuelta**: sin restriccion de horario por defecto (usa
  `--return-same-schedule` si tambien la quieres limitar a mie/jue-vie-tarde).

Los resultados se ordenan del **mas barato al mas caro** (precio total = ida +
vuelta).

> **Nota:** este script hace requests en vivo a `google.com/travel/flights`,
> asi que necesitas correrlo en una maquina con acceso normal a internet (no
> funciona dentro de este entorno de sandbox, que tiene bloqueado el trafico
> saliente a Google).

## Instalacion

```bash
python3 -m venv venv
source venv/bin/activate  # en Windows: venv\Scripts\activate
pip install -r requirements.txt
```

## Uso basico

Busca viajes redondos de 4 noches para las proximas 6 semanas a partir del
proximo miercoles:

```bash
python -m flight_search.search
```

Esto imprime una tabla en la terminal con las combinaciones ida+vuelta mas
baratas que cumplen tu horario de ida.

## Opciones utiles

```bash
python -m flight_search.search \
  --start-date 2026-10-01 \
  --weeks-ahead 10 \
  --nights 3,4,5 \
  --afternoon-hour 13 \
  --max-stops 1 \
  --top 30 \
  --csv resultados.csv
```

| Opcion | Que hace | Default |
|---|---|---|
| `--origins` | Aeropuertos de origen separados por coma | `CVG,IND,SDF` |
| `--destination` | Aeropuerto de destino | `ELP` |
| `--start-date` | Primera fecha de ida a considerar (`YYYY-MM-DD`) | proximo miercoles |
| `--weeks-ahead` | Cuantas semanas buscar hacia adelante | `6` |
| `--nights` | Noches de estadia en El Paso. Acepta lista, ej. `3,4,5` para probar varias duraciones | `4` |
| `--one-way` | Busca solo el tramo de ida (ignora `--nights`, comportamiento anterior) | desactivado |
| `--afternoon-hour` | Hora (24h) desde la cual jueves/viernes de ida cuenta como "tarde" | `12` |
| `--wednesday-afternoon-only` | Tambien restringe los miercoles de ida a la tarde | desactivado (miercoles = todo el dia) |
| `--return-same-schedule` | Aplica el mismo filtro mie/jue-vie-tarde a la VUELTA | desactivado (vuelta sin restriccion) |
| `--max-stops` | Maximo de escalas | sin limite |
| `--seat` | Clase: `economy`, `premium-economy`, `business`, `first` | `economy` |
| `--currency` | Moneda | `USD` |
| `--top` | Cuantos resultados mostrar en la tabla | `20` |
| `--csv archivo.csv` | Exporta **todas** las combinaciones (con los links de Google Flights de cada tramo y del viaje completo) | - |
| `--delay` | Segundos de espera entre cada consulta a Google Flights (evita bloqueos) | `1.5` |

## Como funciona

1. Genera todas las fechas de ida miercoles/jueves/viernes dentro del rango
   pedido, y para cada una calcula la(s) fecha(s) de vuelta segun `--nights`.
2. Hace una busqueda "one-way" en Google Flights para cada fecha/aeropuerto,
   tanto de ida (origen -> ELP) como de vuelta (ELP -> origen).
3. Descarta los vuelos de ida que no cumplen tu horario (jueves/viernes en la
   manana quedan fuera).
4. Empareja cada opcion de ida valida con cada opcion de vuelta del mismo
   origen y fecha, sumando los precios como **estimado** del viaje redondo.
5. Ordena todo por precio total y muestra las combinaciones mas baratas, con
   aerolinea, horarios, duracion y escalas de cada tramo.
6. Genera ademas, para cada combinacion, la URL real de busqueda **ida y
   vuelta** en Google Flights (columna `url_ida_y_vuelta_google_flights` del
   CSV) para que verifiques el precio combinado real antes de reservar — a
   veces coincide con la suma de los dos tramos, a veces sale mas barato.

## Notas sobre el numero de consultas

Cada corrida hace una consulta a Google Flights por cada combinacion
(aeropuerto, fecha, direccion). Con la configuracion por defecto (6 semanas,
3 origenes, 1 duracion de estadia) son unas ~100 consultas, ~3-5 minutos con
el `--delay` por defecto. Si usas varias duraciones en `--nights` o subes
`--weeks-ahead`, el numero de consultas crece — bajalo si Google empieza a
bloquear requests (verás reintentos en la terminal).

## Siguientes pasos posibles

- Filtrar tambien la vuelta por dia de la semana (no solo por hora).
- Guardar el historial de precios para detectar cuando bajan.
- Mandar una alerta (correo/Slack) cuando aparezca un vuelo bajo cierto
  precio.

Si quieres cualquiera de estas mejoras, dime y las agrego.
