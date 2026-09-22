#!/usr/bin/env python3
"""Buscador de vuelos: Cincinnati / Indianapolis / Louisville -> El Paso.

Consulta Google Flights (a traves de la libreria `fast-flights`) para varias
fechas y aeropuertos de origen, y se queda solo con los vuelos que caben en tu
horario: miercoles (cualquier hora, por defecto) o jueves/viernes en la tarde,
ya que esos dias trabajas desde casa y tienes mas flexibilidad.

Ejemplo:
    python -m flight_search.search --weeks-ahead 10 --top 30

Ver `python -m flight_search.search --help` para todas las opciones.
"""

from __future__ import annotations

import argparse
import csv
import random
import sys
import time
from dataclasses import dataclass
from datetime import date, datetime, timedelta

from fast_flights import (
    FlightQuery,
    FlightsNotFound,
    Passengers,
    create_query,
    get_flights,
)
from fast_flights.model import Flights, SimpleDatetime

DEFAULT_ORIGINS = ["CVG", "IND", "SDF"]  # Cincinnati, Indianapolis, Louisville
DEFAULT_DESTINATION = "ELP"  # El Paso, TX

ORIGIN_NAMES = {
    "CVG": "Cincinnati/N. Kentucky",
    "IND": "Indianapolis",
    "SDF": "Louisville",
}

WEEKDAY_ES = ["Lun", "Mar", "Mie", "Jue", "Vie", "Sab", "Dom"]

# 0=Lunes ... 6=Domingo
WEDNESDAY, THURSDAY, FRIDAY = 2, 3, 4


@dataclass
class Candidate:
    origin: str
    destination: str
    query_date: date
    booking_url: str
    price: int
    airlines: str
    stops: int
    departure: datetime
    arrival: datetime
    duration_min: int
    plane_types: str

    @property
    def weekday_es(self) -> str:
        return WEEKDAY_ES[self.departure.weekday()]

    def as_row(self) -> list[str]:
        hours, minutes = divmod(self.duration_min, 60)
        return [
            self.origin,
            self.destination,
            f"{self.departure:%Y-%m-%d} ({self.weekday_es})",
            f"{self.departure:%H:%M}",
            f"{self.arrival:%H:%M}",
            f"{hours}h{minutes:02d}m",
            "directo" if self.stops == 0 else f"{self.stops} escala(s)",
            self.airlines,
            f"${self.price}",
        ]


def to_datetime(dt: SimpleDatetime) -> datetime:
    year, month, day = dt.date
    hour, minute = dt.time
    return datetime(year, month, day, hour, minute)


def eligible_dates(start: date, end: date, weekdays: set[int]) -> list[date]:
    dates = []
    d = start
    while d <= end:
        if d.weekday() in weekdays:
            dates.append(d)
        d += timedelta(days=1)
    return dates


def departure_allowed(dep: datetime, afternoon_hour: int, wednesday_anytime: bool) -> bool:
    weekday = dep.weekday()
    if weekday == WEDNESDAY:
        return True if wednesday_anytime else dep.hour >= afternoon_hour
    if weekday in (THURSDAY, FRIDAY):
        return dep.hour >= afternoon_hour
    return False


def search_one_way(
    origin: str,
    destination: str,
    query_date: date,
    seat: str,
    max_stops: int | None,
    currency: str,
) -> tuple[list[Flights], str]:
    query = create_query(
        flights=[
            FlightQuery(
                date=query_date.isoformat(),
                from_airport=origin,
                to_airport=destination,
                max_stops=max_stops,
            )
        ],
        trip="one-way",
        seat=seat,
        passengers=Passengers(adults=1, children=0, infants_in_seat=0, infants_on_lap=0),
        currency=currency,
    )
    results = get_flights(query)
    return list(results), query.url()


def fetch_with_retry(
    origin: str,
    destination: str,
    query_date: date,
    seat: str,
    max_stops: int | None,
    currency: str,
    retries: int,
    delay: float,
) -> tuple[list[Flights], str] | None:
    for attempt in range(retries + 1):
        try:
            return search_one_way(origin, destination, query_date, seat, max_stops, currency)
        except FlightsNotFound:
            return [], ""
        except Exception as exc:  # noqa: BLE001 - queremos seguir aunque falle una consulta
            wait = delay * (2**attempt) + random.uniform(0, 0.5)
            print(
                f"  [!] {origin}->{destination} {query_date}: {exc!r} "
                f"(reintento {attempt + 1}/{retries} en {wait:.1f}s)",
                file=sys.stderr,
            )
            time.sleep(wait)
    return None


def collect_candidates(
    origins: list[str],
    destination: str,
    dates: list[date],
    seat: str,
    max_stops: int | None,
    currency: str,
    afternoon_hour: int,
    wednesday_anytime: bool,
    delay: float,
    retries: int,
) -> list[Candidate]:
    candidates: list[Candidate] = []
    total = len(origins) * len(dates)
    done = 0

    for query_date in dates:
        for origin in origins:
            done += 1
            print(
                f"[{done}/{total}] Buscando {origin} -> {destination} el {query_date} "
                f"({WEEKDAY_ES[query_date.weekday()]})...",
                file=sys.stderr,
            )
            outcome = fetch_with_retry(
                origin, destination, query_date, seat, max_stops, currency, retries, delay
            )
            time.sleep(delay + random.uniform(0, 0.5))
            if not outcome:
                continue
            flights, booking_url = outcome
            for flight in flights:
                if not flight.flights:
                    continue
                first_leg = flight.flights[0]
                last_leg = flight.flights[-1]
                departure = to_datetime(first_leg.departure)
                arrival = to_datetime(last_leg.arrival)
                if not departure_allowed(departure, afternoon_hour, wednesday_anytime):
                    continue
                candidates.append(
                    Candidate(
                        origin=origin,
                        destination=destination,
                        query_date=query_date,
                        booking_url=booking_url,
                        price=flight.price,
                        airlines=", ".join(dict.fromkeys(flight.airlines)),
                        stops=len(flight.flights) - 1,
                        departure=departure,
                        arrival=arrival,
                        duration_min=sum(leg.duration for leg in flight.flights),
                        plane_types=", ".join(
                            dict.fromkeys(leg.plane_type for leg in flight.flights)
                        ),
                    )
                )
    return candidates


def print_table(candidates: list[Candidate], top: int) -> None:
    headers = [
        "Origen",
        "Destino",
        "Fecha (dia)",
        "Sale",
        "Llega",
        "Duracion",
        "Escalas",
        "Aerolinea(s)",
        "Precio",
    ]
    rows = [c.as_row() for c in candidates[:top]]
    widths = [
        max(len(headers[i]), *(len(row[i]) for row in rows)) if rows else len(headers[i])
        for i in range(len(headers))
    ]

    def fmt_row(values: list[str]) -> str:
        return " | ".join(v.ljust(widths[i]) for i, v in enumerate(values))

    print(fmt_row(headers))
    print("-+-".join("-" * w for w in widths))
    for row in rows:
        print(fmt_row(row))


def write_csv(candidates: list[Candidate], path: str) -> None:
    headers = [
        "origen",
        "origen_nombre",
        "destino",
        "fecha",
        "dia_semana",
        "hora_salida",
        "hora_llegada",
        "duracion_min",
        "escalas",
        "aerolineas",
        "avion",
        "precio",
        "url_google_flights",
    ]
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(headers)
        for c in candidates:
            writer.writerow(
                [
                    c.origin,
                    ORIGIN_NAMES.get(c.origin, c.origin),
                    c.destination,
                    c.departure.date().isoformat(),
                    c.weekday_es,
                    c.departure.strftime("%H:%M"),
                    c.arrival.strftime("%H:%M"),
                    c.duration_min,
                    c.stops,
                    c.airlines,
                    c.plane_types,
                    c.price,
                    c.booking_url,
                ]
            )


def next_weekday(start: date, weekday: int) -> date:
    days_ahead = (weekday - start.weekday()) % 7
    return start + timedelta(days=days_ahead)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--origins",
        default=",".join(DEFAULT_ORIGINS),
        help=f"Aeropuertos de origen separados por coma (default: {','.join(DEFAULT_ORIGINS)})",
    )
    parser.add_argument(
        "--destination",
        default=DEFAULT_DESTINATION,
        help=f"Aeropuerto de destino (default: {DEFAULT_DESTINATION})",
    )
    parser.add_argument(
        "--start-date",
        type=lambda s: date.fromisoformat(s),
        default=None,
        help="Primer dia a considerar (YYYY-MM-DD). Default: el proximo miercoles.",
    )
    parser.add_argument(
        "--weeks-ahead",
        type=int,
        default=8,
        help="Cuantas semanas hacia adelante buscar a partir de start-date (default: 8)",
    )
    parser.add_argument(
        "--afternoon-hour",
        type=int,
        default=12,
        help="Hora (24h) a partir de la cual un vuelo jueves/viernes cuenta como 'tarde' (default: 12)",
    )
    parser.add_argument(
        "--wednesday-any-time",
        dest="wednesday_anytime",
        action="store_true",
        default=True,
        help="Los miercoles se aceptan vuelos a cualquier hora (default: activado)",
    )
    parser.add_argument(
        "--wednesday-afternoon-only",
        dest="wednesday_anytime",
        action="store_false",
        help="Restringe tambien los miercoles a la tarde (usa --afternoon-hour)",
    )
    parser.add_argument("--seat", default="economy", help="Clase (default: economy)")
    parser.add_argument(
        "--max-stops", type=int, default=None, help="Maximo de escalas (default: sin limite)"
    )
    parser.add_argument("--currency", default="USD", help="Moneda (default: USD)")
    parser.add_argument("--top", type=int, default=20, help="Cuantos resultados mostrar (default: 20)")
    parser.add_argument(
        "--delay", type=float, default=1.5, help="Segundos de espera entre consultas (default: 1.5)"
    )
    parser.add_argument(
        "--retries", type=int, default=2, help="Reintentos por consulta fallida (default: 2)"
    )
    parser.add_argument("--csv", default=None, help="Ruta para exportar todos los resultados a CSV")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)

    origins = [o.strip().upper() for o in args.origins.split(",") if o.strip()]
    destination = args.destination.strip().upper()

    start_date = args.start_date or next_weekday(date.today(), WEDNESDAY)
    end_date = start_date + timedelta(weeks=args.weeks_ahead)

    weekdays = {WEDNESDAY, THURSDAY, FRIDAY}
    dates = eligible_dates(start_date, end_date, weekdays)

    print(
        f"Buscando vuelos {'/'.join(origins)} -> {destination} "
        f"entre {start_date} y {end_date} (solo Mie/Jue/Vie)...\n",
        file=sys.stderr,
    )

    candidates = collect_candidates(
        origins=origins,
        destination=destination,
        dates=dates,
        seat=args.seat,
        max_stops=args.max_stops,
        currency=args.currency,
        afternoon_hour=args.afternoon_hour,
        wednesday_anytime=args.wednesday_anytime,
        delay=args.delay,
        retries=args.retries,
    )

    candidates.sort(key=lambda c: c.price)

    print()
    if not candidates:
        print("No se encontraron vuelos que cumplan el horario pedido.")
        return

    print(f"{len(candidates)} vuelos encontrados que caben en tu horario. Los mas baratos primero:\n")
    print_table(candidates, args.top)

    if args.csv:
        write_csv(candidates, args.csv)
        print(f"\nResultados completos exportados a {args.csv}")

    print("\nTip: cada fila usa la URL de busqueda de Google Flights de esa fecha/aeropuerto")
    print("para que puedas entrar y reservar. Corre con --csv resultados.csv para ver todas las URLs.")


if __name__ == "__main__":
    main()
