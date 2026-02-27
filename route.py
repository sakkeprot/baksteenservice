"""baksteenservice - route.py
Google Maps routeplanner voor alle modi.
Exporteert: vind_route(origin, destination, mode, vanaf, language) -> dict
Modi: "transit", "walking"
Returnt {"ok": bool, "msg": str}
"""

import logging
import re
import requests
from datetime import datetime, timezone, timedelta
from typing import Optional

import secrets as _secrets

log = logging.getLogger("baksteenservice.route")

_DIRECTIONS = "https://maps.googleapis.com/maps/api/directions/json"
_GEOCODE    = "https://maps.googleapis.com/maps/api/geocode/json"
_IRAIL      = "https://api.irail.be"
_IRAIL_UA   = "baksteenservice/1.0 (github.com/sakkeprot/baksteenservice)"

_TRAIN_VEHICLES = {"HEAVY_RAIL", "COMMUTER_TRAIN", "RAIL"}

# Platform extractie uit stopnaam (Google encodeert het soms hierin)
_PLATFORM_IN_NAME_RE = re.compile(
    r'\s*[-–]?\s*(?:perron|spoor|quai|voie|platform|track|gleis|binario)\s*([A-Za-z0-9]+)\s*$',
    re.IGNORECASE,
)


# ── Lage-level ─────────────────────────────────────────────────────────────────

def _api_get(url: str, params: dict) -> Optional[dict]:
    try:
        r = requests.get(url, params=params, timeout=10)
        r.raise_for_status()
        data   = r.json()
        status = data.get("status", "")
        if status not in ("OK", "ZERO_RESULTS"):
            log.error("Google API %s: %s", status, data.get("error_message", ""))
            return None
        return data
    except requests.RequestException as e:
        log.error("GET %s -> %s", url, e)
        return None


# ── Geocoding ──────────────────────────────────────────────────────────────────

def _geocode(query: str, language: str = "nl") -> Optional[str]:
    data = _api_get(_GEOCODE, {
        "address":    query,
        "region":     "be",
        "components": "country:BE",
        "language":   language,
        "key":        _secrets.GOOGLE_MAPS_API_KEY,
    })
    if not data or not data.get("results"):
        log.warning("geocode: geen resultaat voor '%s'", query)
        return None
    loc = data["results"][0]["geometry"]["location"]
    log.info("geocode '%s' -> %s,%s", query, loc["lat"], loc["lng"])
    return f"{loc['lat']},{loc['lng']}"


# ── Helpers ────────────────────────────────────────────────────────────────────

def _fmt_duration(seconds: int) -> str:
    m = seconds // 60
    return f"{m}min" if m < 60 else f"{m // 60}u{m % 60:02d}"


def _fmt_distance(metres: int) -> str:
    return f"{metres}m" if metres < 1000 else f"{metres / 1000:.1f}km".rstrip("0").rstrip(".")


def _strip_html(text: str) -> str:
    text = re.sub(r"<[^>]+>", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _split_stop_name(name: str) -> tuple:
    m = _PLATFORM_IN_NAME_RE.search(name)
    if m:
        clean    = name[:m.start()].strip()
        platform = m.group(1)
        return clean, platform   # just the number/letter, no "spoor" prefix
    return name, ""



def _fmt_platform(stop: dict, transit_details: dict = None, is_departure: bool = True) -> str:
    platform = stop.get("platform") or stop.get("track") or stop.get("spoor")
    if not platform and transit_details:
        platform = transit_details.get("departure_platform" if is_departure else "arrival_platform")
    return str(platform) if platform else ""


# ── iRail platform lookup ──────────────────────────────────────────────────────

_STATION_NOISE_RE = re.compile(
    r'\b(station|gare|stazione|bahnhof|halt)\b\s*',
    re.IGNORECASE,
)

def _clean_station_name(name: str) -> str:
    """
    Verwijdert 'Station', 'Gare' etc. uit een Google stopnaam
    zodat iRail het herkent.
    Bv. "Station Tienen" -> "Tienen"
         "Gare de Liège" -> "Liège"
         "Landen"        -> "Landen"
    """
    cleaned = _STATION_NOISE_RE.sub("", name).strip(" -–,")
    return cleaned if cleaned else name


def _irail_platforms(dep_station: str, arr_station: str, dep_unix: int) -> tuple:
    """
    Zoekt vertrek- en aankomstperron op via iRail voor een specifieke treinrit.
    Matcht op vertrektijd (binnen 2 minuten marge).
    Returns (dep_platform, arr_platform) als strings, of ("", "") bij mislukking.
    """
    dep_dt      = datetime.fromtimestamp(dep_unix)
    dep_clean   = _clean_station_name(dep_station)
    arr_clean   = _clean_station_name(arr_station)

    log.info("  iRail lookup: '%s' -> '%s' om %s", dep_clean, arr_clean, dep_dt.strftime("%H:%M"))

    try:
        resp = requests.get(
            f"{_IRAIL}/connections/",          # geen /v1/, wel trailing slash
            headers={"User-Agent": _IRAIL_UA},
            params={
                "from":            dep_clean,
                "to":              arr_clean,
                "date":            dep_dt.strftime("%d%m%y"),
                "time":            dep_dt.strftime("%H%M"),
                "timesel":         "departure",
                "format":          "json",
                "lang":            "nl",
                "results":         "6",
                "typeOfTransport": "trains",
            },
            timeout=8,
        )
        resp.raise_for_status()
    except requests.RequestException as e:
        log.warning("iRail platform lookup mislukt: %s", e)
        return "", ""

    conns = resp.json().get("connection", [])
    if not conns:
        log.info("  iRail: geen verbindingen gevonden")
        return "", ""

    for conn in conns:
        dep      = conn.get("departure", {})
        arr      = conn.get("arrival",   {})
        conn_unix = int(dep.get("time", 0))
        if abs(conn_unix - dep_unix) <= 120:
            dep_plat = dep.get("platforminfo", {}).get("name", "").strip()
            arr_plat = arr.get("platforminfo", {}).get("name", "").strip()
            log.info("  iRail match gevonden: dep spoor=%s arr spoor=%s", dep_plat, arr_plat)
            return dep_plat, arr_plat

    log.info("  iRail: geen tijdmatch voor unix=%d", dep_unix)
    return "", ""



# ── Transit formatter ──────────────────────────────────────────────────────────

def _fmt_transit_route(route: dict, language: str = "nl") -> str:
    leg   = route["legs"][0]
    parts = []

    walk_label = "te voet" if language == "nl" else "a pied"

    for step in leg.get("steps", []):
        mode = step.get("travel_mode", "")

        if mode == "WALKING":
            dist = step.get("distance", {}).get("value", 0)
            if dist > 200:
                parts.append(f"~{_fmt_distance(dist)} {walk_label}")
            continue

        if mode == "TRANSIT":
            td        = step.get("transit_details", {})
            dep_stop  = td.get("departure_stop", {})
            arr_stop  = td.get("arrival_stop",   {})

            dep_name, dep_plat = _split_stop_name(dep_stop.get("name", "?"))
            arr_name, arr_plat = _split_stop_name(arr_stop.get("name", "?"))

            # Fallback naar aparte platform-velden
            if not dep_plat:
                dep_plat = _fmt_platform(dep_stop, td, is_departure=True)
            if not arr_plat:
                arr_plat = _fmt_platform(arr_stop, td, is_departure=False)

            dep_time_text = td.get("departure_time", {}).get("text", "?")
            arr_time_text = td.get("arrival_time",   {}).get("text", "?")
            dep_unix      = td.get("departure_time", {}).get("value")  # Unix timestamp
            arr_unix      = td.get("arrival_time",   {}).get("value")

            line      = td.get("line", {})
            lijn_nr   = line.get("short_name") or line.get("name") or "?"
            vehicle   = line.get("vehicle", {}).get("type", "BUS")
            num_stops = td.get("num_stops", "")

            # iRail platform enrichment voor treinen
            if vehicle in _TRAIN_VEHICLES and dep_unix and not dep_plat and not arr_plat:
                irail_dep_plat, irail_arr_plat = _irail_platforms(
                    dep_name, arr_name, dep_unix
                )
                if irail_dep_plat:
                    dep_plat = f" {irail_dep_plat}"
                if irail_arr_plat:
                    arr_plat = f" {irail_arr_plat}"

            if language == "nl":
                type_label = {
                    "BUS":            "bus",
                    "TRAM":           "tram",
                    "SUBWAY":         "metro",
                    "HEAVY_RAIL":     "trein",
                    "COMMUTER_TRAIN": "trein",
                    "RAIL":           "trein",
                    "FERRY":          "veer",
                    "CABLE_CAR":      "kabelbaan",
                    "FUNICULAR":      "",
                }.get(vehicle, "bus")
            else:
                type_label = {
                    "BUS":            "bus",
                    "TRAM":           "tram",
                    "SUBWAY":         "metro",
                    "HEAVY_RAIL":     "train",
                    "COMMUTER_TRAIN": "train",
                    "RAIL":           "train",
                    "FERRY":          "ferry",
                    "CABLE_CAR":      "telepherique",
                    "FUNICULAR":      "",
                }.get(vehicle, "bus")

            dep_plat_str = f" sp.{dep_plat}" if dep_plat else ""
            arr_plat_str = f" sp.{arr_plat}" if arr_plat else ""
            stop_info    = f" ({num_stops} haltes)" if num_stops else ""

            parts.append(
                f"{dep_time_text} {dep_name}{dep_plat_str} "
                f"{type_label}{stop_info} "
                f"-> {arr_name}{arr_plat_str} {arr_time_text}"
            )

    if not parts:
        dep = leg.get("departure_time", {}).get("text", "?")
        arr = leg.get("arrival_time",   {}).get("text", "?")
        dur = leg.get("duration", {}).get("value", 0)
        return f"{dep} -> {arr} ({_fmt_duration(dur)})"

    dur = leg.get("duration", {}).get("value", 0)
    return " | ".join(parts) + f" ({_fmt_duration(dur)})"


# ── Walking formatter ──────────────────────────────────────────────────────────

def _fmt_walking_route(route: dict, language: str = "nl") -> str:
    leg   = route["legs"][0]
    steps = leg.get("steps", [])
    dist  = leg.get("distance", {}).get("value", 0)
    dur   = leg.get("duration", {}).get("value", 0)

    parts = []
    for step in steps:
        instr = _strip_html(step.get("html_instructions", ""))
        d     = step.get("distance", {}).get("value", 0)
        if d >= 20 and instr:
            parts.append(f"{instr} ({_fmt_distance(d)})")

    summary = f"{_fmt_distance(dist)}, {_fmt_duration(dur)}"
    if not parts:
        return summary
    return ", ".join(parts) + f" -- {summary}"


# ── Publieke functie ───────────────────────────────────────────────────────────

def vind_route(
    origin:        str,
    destination:   str,
    mode:          str      = "transit",
    transit_modes: str      = "bus|tram|subway|train",
    max_routes:    int      = 3,
    vanaf:         datetime = None,
    language:      str      = "nl",
) -> dict:
    nu = vanaf or datetime.now()
    log.info("Route [%s/%s]: '%s' -> '%s' vanaf %s",
             mode, language, origin, destination, nu.strftime("%H:%M"))

    van_ll  = _geocode(origin,      language)
    naar_ll = _geocode(destination, language)

    if not van_ll:
        msg = f"Locatie niet gevonden: '{origin}'." if language == "nl" \
              else f"Lieu introuvable: '{origin}'."
        return {"ok": False, "msg": msg}
    if not naar_ll:
        msg = f"Locatie niet gevonden: '{destination}'." if language == "nl" \
              else f"Lieu introuvable: '{destination}'."
        return {"ok": False, "msg": msg}

    params = {
        "origin":      van_ll,
        "destination": naar_ll,
        "mode":        mode,
        "language":    language,
        "region":      "be",
        "key":         _secrets.GOOGLE_MAPS_API_KEY,
    }

    if mode == "transit":
        params["transit_mode"]   = transit_modes
        params["departure_time"] = int(nu.timestamp())
        params["alternatives"]   = "true"
    else:
        params["departure_time"] = int(nu.timestamp())

    data = _api_get(_DIRECTIONS, params)

    if not data or data.get("status") == "ZERO_RESULTS" or not data.get("routes"):
        msg = f"Geen route van '{origin}' naar '{destination}'." if language == "nl" \
              else f"Aucun itineraire de '{origin}' vers '{destination}'."
        return {"ok": False, "msg": msg}

    routes = data["routes"]

    if mode == "transit":
        regels = [_fmt_transit_route(r, language) for r in routes[:max_routes]]
    else:
        regels = [_fmt_walking_route(routes[0], language)]

    return {"ok": True, "msg": "\n".join(regels)}
