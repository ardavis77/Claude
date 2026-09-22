#!/usr/bin/env python3
"""Buscador de vuelos redondos: Cincinnati / Indianapolis / Louisville -> El Paso.

Consulta Google Flights (a traves de la libreria `fast-flights`) para varias
fechas y aeropuertos de origen, arma combinaciones de **ida y vuelta**, y se
queda solo con las que caben en tu horario: miercoles (cualquier hora, por
defecto) o jueves/viernes en la tarde para la ida, ya que esos dias trabajas
desde casa y tienes mas flexibilidad. La vuelta, por defecto, no tiene
restriccion de horario.

Ejemplo:
    python -m flight_search.search --weeks-ahead 6 --nights 3,4,5 --top 30

Ver `python -m flight_search.search --help` para todas las opciones.
Usa `--one-way` para buscar solo el tramo de ida (comportamiento anterior).
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
WEEKDAY_NAME_TO_INDEX = {name.lower(): i for i, name in enumerate(WEEKDAY_ES)}

# 0=Lunes ... 6=Domingo
WEDNESDAY, THURSDAY, FRIDAY = 2, 3, 4


@dataclass
class Leg:
    """Un tramo (solo ida o solo vuelta)."""

    origin: str
    destination: str
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

    def duration_str(self) -> str:
        hours, minutes = divmod(self.duration_min, 60)
        return f"{hours}h{minutes:02d}m"

    def as_row(self) -> list[str]:
        return [
            self.origin,
            self.destination,
            f"{self.departure:%Y-%m-%d} ({self.weekday_es})",
            f"{self.departure:%H:%M}",
            f"{self.arrival:%H:%M}",
            self.duration_str(),
            "directo" if self.stops == 0 else f"{self.stops} escala(s)",
            self.airlines,
            f"${self.price}",
        ]


@dataclass
class RoundTrip:
    """Combinacion de tramo de ida + tramo de vuelta."""

    origin: str
    destination: str
    nights: int
    outbound: Leg
    ret: Leg
    round_trip_url: str

    @property
    def total_price(self) -> int:
        return self.outbound.price + self.ret.price

    def as_row(self) -> list[str]:
        return [
            self.origin,
            f"{self.outbound.departure:%Y-%m-%d} ({self.outbound.weekday_es}) {self.outbound.departure:%H:%M}",
            f"{self.ret.departure:%Y-%m-%d} ({self.ret.weekday_es}) {self.ret.departure:%H:%M}",
            str(self.nights),
            self._stops_str(self.outbound),
            self._stops_str(self.ret),
            ", ".join(dict.fromkeys([*self.outbound.airlines.split(", "), *self.ret.airlines.split(", ")])),
            f"${self.total_price}",
        ]

    @staticmethod
    def _stops_str(leg: Leg) -> str:
        return "directo" if leg.stops == 0 else f"{leg.stops} esc."


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


def return_allowed(
    dep: datetime,
    allowed_weekdays: set[int] | None,
    afternoon_weekdays: set[int],
    afternoon_hour: int,
) -> bool:
    """Filtro de vuelta: dias permitidos (None = todos) + hora minima en algunos de ellos."""
    weekday = dep.weekday()
    if allowed_weekdays is not None and weekday not in allowed_weekdays:
        return False
    if weekday in afternoon_weekdays and dep.hour < afternoon_hour:
        return False
    return True


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
) -> tuple[list[Flights], str]:
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
    return [], ""


def flight_to_leg(flight: Flights, origin: str, destination: str, booking_url: str) -> Leg | None:
    if not flight.flights:
        return None
    first_leg = flight.flights[0]
    last_leg = flight.flights[-1]
    return Leg(
        origin=origin,
        destination=destination,
        booking_url=booking_url,
        price=flight.price,
        airlines=", ".join(dict.fromkeys(flight.airlines)),
        stops=len(flight.flights) - 1,
        departure=to_datetime(first_leg.departure),
        arrival=to_datetime(last_leg.arrival),
        duration_min=sum(leg.duration for leg in flight.flights),
        plane_types=", ".join(dict.fromkeys(leg.plane_type for leg in flight.flights)),
    )


def fetch_legs(
    jobs: list[tuple[str, str, date]],
    seat: str,
    max_stops: int | None,
    currency: str,
    delay: float,
    retries: int,
) -> dict[tuple[str, str, date], list[Leg]]:
    """jobs: lista de (origin, destination, fecha). Devuelve todas las opciones por job."""
    cache: dict[tuple[str, str, date], list[Leg]] = {}
    total = len(jobs)
    for i, (origin, destination, query_date) in enumerate(jobs, start=1):
        print(
            f"[{i}/{total}] Buscando {origin} -> {destination} el {query_date} "
            f"({WEEKDAY_ES[query_date.weekday()]})...",
            file=sys.stderr,
        )
        flights, booking_url = fetch_with_retry(
            origin, destination, query_date, seat, max_stops, currency, retries, delay
        )
        time.sleep(delay + random.uniform(0, 0.5))
        legs = [
            leg
            for flight in flights
            if (leg := flight_to_leg(flight, origin, destination, booking_url)) is not None
        ]
        cache[(origin, destination, query_date)] = legs
    return cache


def build_round_trip_url(
    origin: str, destination: str, out_date: date, ret_date: date, seat: str, currency: str
) -> str:
    query = create_query(
        flights=[
            FlightQuery(date=out_date.isoformat(), from_airport=origin, to_airport=destination),
            FlightQuery(date=ret_date.isoformat(), from_airport=destination, to_airport=origin),
        ],
        trip="round-trip",
        seat=seat,
        passengers=Passengers(adults=1, children=0, infants_in_seat=0, infants_on_lap=0),
        currency=currency,
    )
    return query.url()


def print_table(rows: list[list[str]], headers: list[str]) -> None:
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


def write_round_trip_csv(trips: list[RoundTrip], path: str) -> None:
    headers = [
        "origen",
        "origen_nombre",
        "destino",
        "noches",
        "fecha_ida",
        "dia_ida",
        "hora_salida_ida",
        "hora_llegada_ida",
        "duracion_ida_min",
        "escalas_ida",
        "aerolineas_ida",
        "precio_ida",
        "fecha_vuelta",
        "dia_vuelta",
        "hora_salida_vuelta",
        "hora_llegada_vuelta",
        "duracion_vuelta_min",
        "escalas_vuelta",
        "aerolineas_vuelta",
        "precio_vuelta",
        "precio_total_estimado",
        "url_ida_google_flights",
        "url_vuelta_google_flights",
        "url_ida_y_vuelta_google_flights",
    ]
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(headers)
        for t in trips:
            o, r = t.outbound, t.ret
            writer.writerow(
                [
                    t.origin,
                    ORIGIN_NAMES.get(t.origin, t.origin),
                    t.destination,
                    t.nights,
                    o.departure.date().isoformat(),
                    o.weekday_es,
                    o.departure.strftime("%H:%M"),
                    o.arrival.strftime("%H:%M"),
                    o.duration_min,
                    o.stops,
                    o.airlines,
                    o.price,
                    r.departure.date().isoformat(),
                    r.weekday_es,
                    r.departure.strftime("%H:%M"),
                    r.arrival.strftime("%H:%M"),
                    r.duration_min,
                    r.stops,
                    r.airlines,
                    r.price,
                    t.total_price,
                    o.booking_url,
                    r.booking_url,
                    t.round_trip_url,
                ]
            )


def write_one_way_csv(legs: list[Leg], path: str) -> None:
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
        for c in legs:
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


def parse_nights(value: str) -> list[int]:
    nights = sorted({int(n.strip()) for n in value.split(",") if n.strip()})
    if not nights:
        raise argparse.ArgumentTypeError("--nights necesita al menos un numero, ej. '4' o '3,4,5'")
    return nights


def parse_weekdays(value: str | None) -> set[int] | None:
    """'Lun,Mar,...' -> {0,1,...}. None o cadena vacia = todos los dias permitidos."""
    if not value:
        return None
    days = set()
    for part in value.split(","):
        key = part.strip().lower()
        if not key:
            continue
        if key not in WEEKDAY_NAME_TO_INDEX:
            valid = ",".join(WEEKDAY_ES)
            raise argparse.ArgumentTypeError(f"dia invalido {part!r}, usa alguno de: {valid}")
        days.add(WEEKDAY_NAME_TO_INDEX[key])
    return days or None


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
        help="Primer dia de ida a considerar (YYYY-MM-DD). Default: el proximo miercoles.",
    )
    parser.add_argument(
        "--weeks-ahead",
        type=int,
        default=6,
        help="Cuantas semanas hacia adelante buscar a partir de start-date (default: 6)",
    )
    parser.add_argument(
        "--nights",
        type=parse_nights,
        default=[4],
        help="Noches de estadia en El Paso. Acepta una lista separada por comas, ej. "
        "'3,4,5' para probar varias duraciones (default: 4)",
    )
    parser.add_argument(
        "--one-way",
        action="store_true",
        help="Busca solo el tramo de ida (ignora --nights, no busca vuelta)",
    )
    parser.add_argument(
        "--afternoon-hour",
        type=int,
        default=12,
        help="Hora (24h) a partir de la cual un vuelo de ida jueves/viernes cuenta como 'tarde' (default: 12)",
    )
    parser.add_argument(
        "--wednesday-any-time",
        dest="wednesday_anytime",
        action="store_true",
        default=True,
        help="Los miercoles de ida se aceptan a cualquier hora (default: activado)",
    )
    parser.add_argument(
        "--wednesday-afternoon-only",
        dest="wednesday_anytime",
        action="store_false",
        help="Restringe tambien los miercoles de ida a la tarde (usa --afternoon-hour)",
    )
    parser.add_argument(
        "--return-weekdays",
        type=parse_weekdays,
        default=None,
        help="Dias permitidos para la VUELTA, separados por coma (Lun,Mar,Mie,Jue,Vie,Sab,Dom). "
        "Default: sin restriccion (cualquier dia).",
    )
    parser.add_argument(
        "--return-afternoon-weekdays",
        type=parse_weekdays,
        default=None,
        help="De los dias en --return-weekdays, cuales requieren salir en la tarde "
        "(usa --return-afternoon-hour). Default: ninguno (toda hora es valida).",
    )
    parser.add_argument(
        "--return-afternoon-hour",
        type=int,
        default=12,
        help="Hora (24h) a partir de la cual la vuelta cuenta como 'tarde' en los dias de "
        "--return-afternoon-weekdays (default: 12)",
    )
    parser.add_argument(
        "--return-same-schedule",
        action="store_true",
        help="Atajo: aplica a la VUELTA el mismo patron que la ida (Mie cualquier hora, "
        "Jue/Vie tarde). Equivale a --return-weekdays Mie,Jue,Vie --return-afternoon-weekdays Jue,Vie. "
        "Se ignora si ya pasaste --return-weekdays.",
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
    args = parser.parse_args(argv)

    if args.return_same_schedule:
        if args.return_weekdays is None:
            args.return_weekdays = {WEDNESDAY, THURSDAY, FRIDAY}
        if args.return_afternoon_weekdays is None:
            args.return_afternoon_weekdays = {THURSDAY, FRIDAY}
        if "--return-afternoon-hour" not in (argv or sys.argv[1:]):
            args.return_afternoon_hour = args.afternoon_hour

    if args.return_afternoon_weekdays is None:
        args.return_afternoon_weekdays = set()

    return args


def run_one_way(args: argparse.Namespace) -> None:
    origins = [o.strip().upper() for o in args.origins.split(",") if o.strip()]
    destination = args.destination.strip().upper()

    start_date = args.start_date or next_weekday(date.today(), WEDNESDAY)
    end_date = start_date + timedelta(weeks=args.weeks_ahead)
    dates = eligible_dates(start_date, end_date, {WEDNESDAY, THURSDAY, FRIDAY})

    print(
        f"Buscando vuelos de ida {'/'.join(origins)} -> {destination} "
        f"entre {start_date} y {end_date} (solo Mie/Jue/Vie)...\n",
        file=sys.stderr,
    )

    jobs = [(origin, destination, d) for d in dates for origin in origins]
    cache = fetch_legs(jobs, args.seat, args.max_stops, args.currency, args.delay, args.retries)

    legs: list[Leg] = []
    for (origin, dest, _d), options in cache.items():
        for leg in options:
            if departure_allowed(leg.departure, args.afternoon_hour, args.wednesday_anytime):
                legs.append(leg)

    legs.sort(key=lambda c: c.price)

    print()
    if not legs:
        print("No se encontraron vuelos de ida que cumplan el horario pedido.")
        return

    print(f"{len(legs)} vuelos de ida encontrados que caben en tu horario. Los mas baratos primero:\n")
    headers = ["Origen", "Destino", "Fecha (dia)", "Sale", "Llega", "Duracion", "Escalas", "Aerolinea(s)", "Precio"]
    print_table([c.as_row() for c in legs[: args.top]], headers)

    if args.csv:
        write_one_way_csv(legs, args.csv)
        print(f"\nResultados completos exportados a {args.csv}")


def run_round_trip(args: argparse.Namespace) -> None:
    origins = [o.strip().upper() for o in args.origins.split(",") if o.strip()]
    destination = args.destination.strip().upper()

    start_date = args.start_date or next_weekday(date.today(), WEDNESDAY)
    end_date = start_date + timedelta(weeks=args.weeks_ahead)
    out_dates = eligible_dates(start_date, end_date, {WEDNESDAY, THURSDAY, FRIDAY})

    return_dates_by_origin: dict[str, set[date]] = {o: set() for o in origins}
    for d in out_dates:
        for n in args.nights:
            ret_date = d + timedelta(days=n)
            if args.return_weekdays is not None and ret_date.weekday() not in args.return_weekdays:
                continue
            for origin in origins:
                return_dates_by_origin[origin].add(ret_date)

    outbound_jobs = [(origin, destination, d) for d in out_dates for origin in origins]
    return_jobs = [
        (destination, origin, d) for origin in origins for d in sorted(return_dates_by_origin[origin])
    ]

    total_jobs = len(outbound_jobs) + len(return_jobs)
    print(
        f"Buscando vuelos redondos {'/'.join(origins)} <-> {destination} "
        f"entre {start_date} y {end_date}, con estadias de {args.nights} noche(s).\n"
        f"({total_jobs} consultas a Google Flights, con {args.delay}s+ de espera entre cada una)\n",
        file=sys.stderr,
    )

    cache = fetch_legs(
        outbound_jobs + return_jobs, args.seat, args.max_stops, args.currency, args.delay, args.retries
    )

    trips: list[RoundTrip] = []
    for d in out_dates:
        for origin in origins:
            out_options = cache.get((origin, destination, d), [])
            out_options = [
                leg
                for leg in out_options
                if departure_allowed(leg.departure, args.afternoon_hour, args.wednesday_anytime)
            ]
            if not out_options:
                continue
            for n in args.nights:
                ret_date = d + timedelta(days=n)
                if args.return_weekdays is not None and ret_date.weekday() not in args.return_weekdays:
                    continue
                ret_options = cache.get((destination, origin, ret_date), [])
                ret_options = [
                    leg
                    for leg in ret_options
                    if return_allowed(
                        leg.departure,
                        args.return_weekdays,
                        args.return_afternoon_weekdays,
                        args.return_afternoon_hour,
                    )
                ]
                if not ret_options:
                    continue
                rt_url = build_round_trip_url(origin, destination, d, ret_date, args.seat, args.currency)
                for out_leg in out_options:
                    for ret_leg in ret_options:
                        trips.append(
                            RoundTrip(
                                origin=origin,
                                destination=destination,
                                nights=n,
                                outbound=out_leg,
                                ret=ret_leg,
                                round_trip_url=rt_url,
                            )
                        )

    trips.sort(key=lambda t: t.total_price)

    print()
    if not trips:
        print("No se encontraron combinaciones de ida y vuelta que cumplan el horario pedido.")
        return

    print(
        f"{len(trips)} combinaciones de ida y vuelta encontradas. Las mas baratas primero "
        "(precio = suma de ambos tramos, estimado):\n"
    )
    headers = ["Origen", "Ida", "Vuelta", "Noches", "Escalas ida", "Escalas vuelta", "Aerolinea(s)", "Precio total"]
    print_table([t.as_row() for t in trips[: args.top]], headers)

    print("\nEntra a la 'Precio total' de tu favorita en el CSV (columna url_ida_y_vuelta_google_flights)")
    print("para ver el precio real combinado en Google Flights y reservar -- a veces es igual, a veces")
    print("mas barato que la suma de los dos tramos por separado.")

    if args.csv:
        write_round_trip_csv(trips, args.csv)
        print(f"\nResultados completos exportados a {args.csv}")


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)
    if args.one_way:
        run_one_way(args)
    else:
        run_round_trip(args)


if __name__ == "__main__":
    main()
