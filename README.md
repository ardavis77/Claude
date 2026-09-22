# Buscador de vuelos: CVG / IND / SDF -> ELP

Script en Python que busca vuelos en Google Flights (via la libreria
[`fast-flights`](https://pypi.org/project/fast-flights/)) desde:

- **CVG** - Cincinnati / Northern Kentucky
- **IND** - Indianapolis
- **SDF** - Louisville, Kentucky

hacia:

- **ELP** - El Paso, Texas

y se queda solo con los vuelos que caben en tu horario real:

- **Miercoles**: cualquier hora (configurable con `--wednesday-afternoon-only`).
- **Jueves y viernes**: solo vuelos que salen en la tarde (por defecto, desde
  las 12:00), porque esos dias trabajas desde casa y tienes mas flexibilidad.

Los resultados se ordenan del **mas barato al mas caro**.

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

Busca vuelos para las proximas 8 semanas a partir del proximo miercoles:

```bash
python -m flight_search.search
```

Esto imprime una tabla en la terminal con los vuelos mas baratos que cumplen
el horario, y por que dia salen.

## Opciones utiles

```bash
python -m flight_search.search \
  --start-date 2026-10-01 \
  --weeks-ahead 12 \
  --afternoon-hour 13 \
  --max-stops 1 \
  --top 30 \
  --csv resultados.csv
```

| Opcion | Que hace | Default |
|---|---|---|
| `--origins` | Aeropuertos de origen separados por coma | `CVG,IND,SDF` |
| `--destination` | Aeropuerto de destino | `ELP` |
| `--start-date` | Primera fecha a considerar (`YYYY-MM-DD`) | proximo miercoles |
| `--weeks-ahead` | Cuantas semanas buscar hacia adelante | `8` |
| `--afternoon-hour` | Hora (24h) desde la cual jueves/viernes cuenta como "tarde" | `12` |
| `--wednesday-afternoon-only` | Tambien restringe los miercoles a la tarde | desactivado (miercoles = todo el dia) |
| `--max-stops` | Maximo de escalas | sin limite |
| `--seat` | Clase: `economy`, `premium-economy`, `business`, `first` | `economy` |
| `--currency` | Moneda | `USD` |
| `--top` | Cuantos resultados mostrar en la tabla | `20` |
| `--csv archivo.csv` | Exporta **todos** los resultados (con el link de Google Flights de cada uno) | - |
| `--delay` | Segundos de espera entre cada consulta a Google Flights (evita bloqueos) | `1.5` |

## Como funciona

1. Genera todas las fechas miercoles/jueves/viernes dentro del rango pedido.
2. Para cada fecha y cada aeropuerto de origen, hace una busqueda "one-way" en
   Google Flights.
3. Descarta los vuelos que no cumplen tu horario (jueves/viernes en la
   manana quedan fuera).
4. Ordena todo por precio y muestra los mas baratos primero, con aerolinea,
   horario de salida/llegada, duracion y numero de escalas.

## Siguientes pasos posibles

- Agregar busqueda del vuelo de regreso (El Paso -> origen) con su propio
  filtro de dias/horarios.
- Guardar el historial de precios para detectar cuando bajan.
- Mandar una alerta (correo/Slack) cuando aparezca un vuelo bajo cierto
  precio.

Si quieres cualquiera de estas mejoras, dime y las agrego.
