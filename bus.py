"""baksteenservice - bus.py
De Lijn routeplanner via Open Data API.
Exporteert: vind_route(van, naar, max_routes, vanaf) -> dict
            vind_halte(naam)                          -> dict
Beide returnen {"ok": bool, "msg": str}
"""

import logging
import requests
from datetime import datetime
from typing import Dict, List, Optional, Set, Tuple

import secrets as _secrets

log = logging.getLogger("baksteenservice.bus")

_ZOEK = "https://api.delijn.be/DLZoekOpenData/v1"
_KERN = "https://api.delijn.be/DLKernOpenData/api/v1"
_HDR  = {
    "Ocp-Apim-Subscription-Key": _secrets.DELIJN_API_KEY,
    "Cache-Control": "no-cache",
    "Accept": "application/json",
    "User-Agent": "baksteenservice/1.0",
}


# ── lage-level ────────────────────────────────────────────────────────────────────────────

def _api_get(url: str, params: dict = None) -> Optional[dict]:
    try:
        r = requests.get(url, headers=_HDR, params=params, timeout=10)
        r.raise_for_status()
        return r.json()
    except requests.RequestException as e:
        log.error("GET %s -> %s", url, e)
        return None


def _zoek_haltes_pagina(naam: str, start: int = 0, max_hits: int = 15) -> Tuple[int, List[dict]]:
    url  = f"{_ZOEK}/zoek/haltes/{requests.utils.quote(naam)}"
    data = _api_get(url, {"startIndex": start, "maxAantalHits": max_hits})
    if not data:
        return 0, []
    return data.get("aantalHits", 0), data.get("haltes", [])


def _zoek_haltes_alle(naam: str, max_total: int = 30) -> List[dict]:
    """Haalt alle haltes op via paginering (max max_total)."""
    totaal, eerste = _zoek_haltes_pagina(naam, start=0, max_hits=15)
    log.info("  zoek '%s': %d totaal, %d in pagina 1", naam, totaal, len(eerste))
    alle = list(eerste)
    start = 15
    while len(alle) < totaal and len(alle) < max_total:
        batch = min(15, max_total - len(alle))
        _, pagina = _zoek_haltes_pagina(naam, start=start, max_hits=batch)
        if not pagina:
            break
        log.info("  pagina start=%d: %d haltes", start, len(pagina))
        alle.extend(pagina)
        start += len(pagina)
    log.info("  totaal opgehaald: %d", len(alle))
    return alle


def _get_lijnrichtingen(e: str, n: str) -> List[dict]:
    data = _api_get(f"{_KERN}/haltes/{e}/{n}/lijnrichtingen")
    return (data or {}).get("lijnrichtingen", [])


def _get_realtime(e: str, n: str, max_dc: int = 12) -> List[dict]:
    data = _api_get(f"{_KERN}/haltes/{e}/{n}/real-time",
                    {"maxAantalDoorkomsten": max_dc})
    result = []
    for hd in (data or {}).get("halteDoorkomsten", []):
        result.extend(hd.get("doorkomsten", []))
    return result


def _get_dienstregeling(e: str, n: str) -> List[dict]:
    data = _api_get(f"{_KERN}/haltes/{e}/{n}/dienstregelingen")
    result = []
    for hd in (data or {}).get("halteDoorkomsten", []):
        result.extend(hd.get("doorkomsten", []))
    return result


def _get_doorkomsten(e: str, n: str, label: str) -> List[dict]:
    """Realtime, met fallback naar dienstregeling."""
    dcs = _get_realtime(e, n, max_dc=12)
    if not dcs:
        log.info("  %s: realtime leeg, probeer dienstregeling", label)
        dcs = _get_dienstregeling(e, n)
        log.info("  %s: dienstregeling %d doorkomsten", label, len(dcs))
    else:
        log.info("  %s: realtime %d doorkomsten", label, len(dcs))
    return dcs


# ── helpers ───────────────────────────────────────────────────────────────────────────────────

def _parse_dt(ts: str) -> Optional[datetime]:
    if not ts:
        return None
    for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M"):
        try:
            return datetime.strptime(ts[:19], fmt)
        except (ValueError, TypeError):
            pass
    return None


def _fmt_tijd(gep: Optional[datetime], rt: Optional[datetime]) -> str:
    """Formatteer tijd met optionele vertraging in minuten."""
    if gep:
        tijd = gep.strftime("%H:%M")
        if rt and rt != gep:
            diff = int((rt - gep).total_seconds() // 60)
            if diff:
                tijd += " %+d'" % diff
    else:
        tijd = "??:??"
    return tijd


def _fmt_dc(d: dict, prefix: str = "  ") -> str:
    lijn = d.get("lijnnummer", "?")
    best = d.get("bestemming", d.get("bestemmingKort", "?"))
    gep  = _parse_dt(d.get("dienstregelingTijdstip", ""))
    rt   = _parse_dt(d.get("real-timeTijdstip", ""))
    return "%s%s lijn %s -> %s" % (prefix, _fmt_tijd(gep, rt), lijn, best)


# ── publieke functies ──────────────────────────────────────────────────────────────────

def vind_route(van_naam: str, naar_naam: str, max_routes: int = 3,
               vanaf: datetime = None) -> dict:
    """
    Zoekt eerstvolgende max_routes vertrekken van van_naam naar naar_naam.
    vanaf: filter op vertrekken >= dit tijdstip (None = now).

    Strategie (2 passes):
      Pass 1 - lijnrichtingen: snel, maar API is soms onvolledig
      Pass 2 - realtime scan:  vangt perrons die pass 1 mist
                                (bv. tijdelijke omleidingen, API-gaps)
    """
    nu = vanaf or datetime.now().replace(second=0, microsecond=0)
    log.info("Route: '%s' -> '%s' vanaf %s", van_naam, naar_naam, nu.strftime("%H:%M"))

    van_haltes  = _zoek_haltes_alle(van_naam,  max_total=30)
    naar_haltes = _zoek_haltes_alle(naar_naam, max_total=30)

    if not van_haltes:
        return {"ok": False, "msg": "Geen halte gevonden voor '%s'." % van_naam}
    if not naar_haltes:
        return {"ok": False, "msg": "Geen halte gevonden voor '%s'." % naar_naam}

    log.info("  van  (%d): %s", len(van_haltes),  [h.get("omschrijving") for h in van_haltes])
    log.info("  naar (%d): %s", len(naar_haltes), [h.get("omschrijving") for h in naar_haltes])

    # Bouw naar_lijnen: (ent, lijn) -> haltenaam
    naar_lijnen: Dict[Tuple, str] = {}
    for nh in naar_haltes:
        ne = str(nh.get("entiteitnummer", ""))
        nn = str(nh.get("haltenummer", ""))
        nm = nh.get("omschrijving", naar_naam)
        for lr in _get_lijnrichtingen(ne, nn):
            lr_ent  = str(lr.get("entiteitnummer", ""))
            lr_lijn = str(lr.get("lijnnummer", ""))
            for key in ((lr_ent, lr_lijn), (ne, lr_lijn)):
                if key not in naar_lijnen:
                    naar_lijnen[key] = nm

    naar_lijn_nrs: Set[str] = set(k[1] for k in naar_lijnen)
    log.info("  Lijnen bij naar: %s", sorted(naar_lijn_nrs))

    # ── Pass 1: lijnrichtingen ────────────────────────────────────────────────────────────────────
    gezien: set = set()
    perron_matches: Dict[Tuple, dict] = {}
    van_met_match:  Set[Tuple] = set()

    for vh in van_haltes:
        ve  = str(vh.get("entiteitnummer", ""))
        vn  = str(vh.get("haltenummer", ""))
        vnm = vh.get("omschrijving", van_naam)
        for lr in _get_lijnrichtingen(ve, vn):
            lr_ent  = str(lr.get("entiteitnummer", ""))
            lr_lijn = str(lr.get("lijnnummer", ""))
            naar_nm = (naar_lijnen.get((lr_ent, lr_lijn))
                       or naar_lijnen.get((ve, lr_lijn)))
            dedup   = (ve, vn, lr_lijn)
            if naar_nm and dedup not in gezien:
                gezien.add(dedup)
                pk = (ve, vn)
                van_met_match.add(pk)
                if pk not in perron_matches:
                    perron_matches[pk] = {"van_naam": vnm, "lijnen": {}}
                perron_matches[pk]["lijnen"][lr_lijn] = naar_nm
                log.info("  P1 MATCH %s lijn %s -> %s", vnm, lr_lijn, naar_nm)

    log.info("  Pass 1: %d perrons met match", len(perron_matches))

    # ── Pass 2: realtime scan voor perrons zonder match ─────────────────────────────
    rt_cache: Dict[Tuple, List[dict]] = {}

    for vh in van_haltes:
        ve  = str(vh.get("entiteitnummer", ""))
        vn  = str(vh.get("haltenummer", ""))
        vnm = vh.get("omschrijving", van_naam)
        pk  = (ve, vn)
        if pk in van_met_match:
            continue
        dcs = _get_doorkomsten(ve, vn, vnm)
        rt_cache[pk] = dcs
        for d in dcs:
            lijn = str(d.get("lijnnummer", ""))
            if lijn in naar_lijn_nrs:
                naar_nm = (naar_lijnen.get((ve, lijn))
                           or next((v for (e2, l2), v in naar_lijnen.items()
                                    if l2 == lijn), naar_naam))
                dedup = (ve, vn, lijn)
                if dedup not in gezien:
                    gezien.add(dedup)
                    if pk not in perron_matches:
                        perron_matches[pk] = {"van_naam": vnm, "lijnen": {}}
                    perron_matches[pk]["lijnen"][lijn] = naar_nm
                    log.info("  P2 MATCH %s lijn %s -> %s (realtime scan)",
                             vnm, lijn, naar_nm)

    log.info("  Na pass 2: %d perrons met match", len(perron_matches))

    if not perron_matches:
        for vh in van_haltes:
            ve = str(vh.get("entiteitnummer", ""))
            vn = str(vh.get("haltenummer", ""))
            dcs = rt_cache.get((ve, vn)) or _get_realtime(ve, vn)
            if dcs:
                lines = [
                    "Geen directe lijn van '%s' naar '%s'." % (van_naam, naar_naam),
                    "Vertrektijden %s:" % vh.get("omschrijving", van_naam),
                ]
                for d in dcs[:4]:
                    lines.append(_fmt_dc(d))
                return {"ok": False, "msg": "\n".join(lines)}
        return {"ok": False,
                "msg": "Geen route gevonden van '%s' naar '%s'." % (van_naam, naar_naam)}

    # ── Verzamel en filter vertrekken ───────────────────────────────────────────────────────
    vertrekken: List[Tuple[datetime, str, str]] = []

    for (ve, vn), info in perron_matches.items():
        if (ve, vn) in rt_cache:
            dcs = rt_cache[(ve, vn)]
            log.info("  %s: gebruik gecachte %d doorkomsten", info["van_naam"], len(dcs))
        else:
            dcs = _get_doorkomsten(ve, vn, info["van_naam"])
            rt_cache[(ve, vn)] = dcs

        for lijn, naar_nm in info["lijnen"].items():
            gefilterd = [d for d in dcs if str(d.get("lijnnummer", "")) == lijn]
            log.info("    lijn %s: %d vertrekken -> %s", lijn, len(gefilterd), naar_nm)
            for d in gefilterd:
                gep = _parse_dt(d.get("dienstregelingTijdstip", ""))
                rt  = _parse_dt(d.get("real-timeTijdstip", ""))
                t   = rt or gep
                if not t:
                    continue
                # ── Tijdfilter: enkel vertrekken >= vanaf ──────────────
                if t < nu:
                    continue
                tijd      = _fmt_tijd(gep, rt)
                regel     = "%s %s lijn %s -> %s" % (tijd, info["van_naam"], lijn, naar_nm)
                dedup_key = (t.strftime("%Y-%m-%dT%H:%M"), lijn)
                vertrekken.append((t, dedup_key, regel))

    if not vertrekken:
        info    = next(iter(perron_matches.values()))
        lijn    = next(iter(info["lijnen"]))
        naar_nm = info["lijnen"][lijn]
        return {"ok": True,
                "msg": "%s -> %s\nLijn %s rijdt hier — geen vertrekken vanaf %s." % (
                    info["van_naam"], naar_nm, lijn, nu.strftime("%H:%M"))}

    # ── Sorteren, dedupliceren, top max_routes ──────────────────────────────────────────────
    vertrekken.sort(key=lambda x: x[0])
    seen_dedup: set = set()
    seen_regel: set = set()
    uniek = []
    for t, dedup_key, regel in vertrekken:
        if dedup_key not in seen_dedup and regel not in seen_regel:
            seen_dedup.add(dedup_key)
            seen_regel.add(regel)
            uniek.append(regel)
        if len(uniek) >= max_routes:
            break

    return {"ok": True, "msg": "\n".join(uniek)}


def vind_halte(naam: str) -> dict:
    """Zoekt een halte op naam en toont de eerstvolgende vertrekken."""
    haltes = _zoek_haltes_alle(naam, max_total=30)
    if not haltes:
        return {"ok": False, "msg": "Halte '%s' niet gevonden." % naam}
    for h in haltes:
        e   = str(h.get("entiteitnummer", ""))
        n   = str(h.get("haltenummer", ""))
        dcs = _get_realtime(e, n)
        log.info("  %s (e=%s,n=%s): %d doorkomsten", h.get("omschrijving"), e, n, len(dcs))
        if dcs:
            lines = [h.get("omschrijving", naam)]
            for d in dcs[:6]:
                lines.append(_fmt_dc(d))
            return {"ok": True, "msg": "\n".join(lines)}
    return {"ok": False, "msg": "Geen vertrektijden voor '%s'." % naam}