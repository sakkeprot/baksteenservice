# baksteenservice - stib.py
# STIB/MIVB Brussels routeplanner via Open Data API (opendatasoft).
# Exporteert:
#   vindroutevan, naar, maxroutes, vanaf -> dict
#   vindhaltenaam -> dict
# Beide returnen {ok: bool, msg: str}

import logging
import requests
from datetime import datetime, timezone
from typing import Dict, List, Optional, Set, Tuple
import secrets as secrets

log = logging.getLogger("baksteenservice.stib")

BASE = "https://stibmivb.opendatasoft.com/api/explore/v2.1/catalog/datasets"
STOPS_DS   = "stop-details-production"
WAITING_DS = "waiting-time-rt-production"
LINES_DS   = "stops-by-line-production"

HDR = {
    "User-Agent": "baksteenservice/1.0",
    "Accept": "application/json",
}

# ------------------------------------------------------------------
# Low-level helpers
# ------------------------------------------------------------------

def _get(dataset: str, params: dict) -> Optional[dict]:
    params["apikey"] = secrets.STIB_API_KEY  # set in secrets.py
    try:
        r = requests.get(f"{BASE}/{dataset}/records", headers=HDR, params=params, timeout=10)
        r.raise_for_status()
        return r.json()
    except requests.RequestException as e:
        log.error("STIB GET %s - %s", dataset, e)
        return None


def _zoek_haltes(naam: str, limit: int = 20) -> List[dict]:
    """Zoek haltes op naam (FR of NL), geeft lijst van records terug."""
    naam_upper = naam.upper().strip()
    data = _get(STOPS_DS, {
        "where": f'name like "%{naam_upper}%"',
        "limit": limit,
    })
    if not data:
        return []
    return data.get("results", [])


def _waiting_times(point_id: str) -> List[dict]:
    """Geeft realtime wachttijden terug voor een stop (pointId)."""
    data = _get(WAITING_DS, {
        "where": f'pointid="{point_id}"',
        "limit": 1,
    })
    if not data:
        return []
    results = data.get("results", [])
    passages = []
    for rec in results:
        for p in rec.get("passingtimes", []):
            passages.append(p)
    return passages


def _parse_iso(ts: Optional[str]) -> Optional[datetime]:
    if not ts:
        return None
    try:
        # format: 2024-02-27T16:30:00+01:00 or with Z
        ts_clean = ts[:19]
        return datetime.strptime(ts_clean, "%Y-%m-%dT%H:%M:%S")
    except (ValueError, TypeError):
        return None


def _fmt_passage(p: dict, prefix: str = "") -> str:
    lijn = p.get("lineId", "?")
    dest = p.get("destination", {})
    dest_nl = dest.get("nl", dest.get("fr", "?"))
    exp = _parse_iso(p.get("expectedArrivalTime"))
    aimed = _parse_iso(p.get("aimedArrivalTime"))
    t = exp or aimed
    tijdstr = t.strftime("%H:%M") if t else "?"
    if exp and aimed and exp != aimed:
        diff = int((exp - aimed).total_seconds() / 60)
        if diff > 0:
            tijdstr += f"+{diff}'"
    return f"{prefix}{tijdstr} lijn {lijn} → {dest_nl}"


# ------------------------------------------------------------------
# Public functions
# ------------------------------------------------------------------

def vindroutevan(vannaam: str, naarnaam: str, maxroutes: int = 3,
                 vanaf: datetime = None) -> dict:
    """
    Zoek directe STIB/MIVB lijnen van vannaam naar naarnaam.
    Strategie: zoek haltes voor beide namen, haal wachttijden op voor
    van-haltes, filter op lijnen die ook bij naar-haltes rijden.
    """
    nu = vanaf or datetime.now().replace(second=0, microsecond=0)

    vanhaltes  = _zoek_haltes(vannaam)
    naarhaltes = _zoek_haltes(naarnaam)

    if not vanhaltes:
        return {"ok": False, "msg": f"Geen halte gevonden voor '{vannaam}'."}
    if not naarhaltes:
        return {"ok": False, "msg": f"Geen halte gevonden voor '{naarnaam}'."}

    log.info("STIB van: %d haltes, naar: %d haltes", len(vanhaltes), len(naarhaltes))

    # Bouw set van lijnnummers die langs naar-haltes rijden
    naar_lijnen: Dict[str, str] = {}  # lineId -> haltenaam
    for nh in naarhaltes:
        nid = str(nh.get("id", ""))
        naam_dict = nh.get("name", {})
        naam_str = naam_dict.get("nl", naam_dict.get("fr", naarnaam)) if isinstance(naam_dict, dict) else str(naam_dict)
        passages = _waiting_times(nid)
        for p in passages:
            lid = str(p.get("lineId", ""))
            if lid and lid not in naar_lijnen:
                naar_lijnen[lid] = naam_str
    log.info("Lijnen bij naar-halte: %s", sorted(naar_lijnen))

    vertrekken: List[Tuple[datetime, str]] = []
    seen: Set[str] = set()

    for vh in vanhaltes:
        vid = str(vh.get("id", ""))
        naam_dict = vh.get("name", {})
        vnaam = naam_dict.get("nl", naam_dict.get("fr", vannaam)) if isinstance(naam_dict, dict) else str(naam_dict)
        passages = _waiting_times(vid)
        for p in passages:
            lid = str(p.get("lineId", ""))
            if lid not in naar_lijnen:
                continue
            exp   = _parse_iso(p.get("expectedArrivalTime"))
            aimed = _parse_iso(p.get("aimedArrivalTime"))
            t = exp or aimed
            if not t or t < nu:
                continue
            regel = _fmt_passage(p, prefix=f"{vnaam} ")
            dedup = (t.strftime("%Y-%m-%dT%H:%M"), lid)
            if dedup not in seen and regel not in seen:
                seen.add(dedup)
                seen.add(regel)
                vertrekken.append((t, regel))

    if not vertrekken:
        # Geen directe lijn gevonden: toon gewoon de eerstvolgende van van-halte
        lines = [f"Geen directe lijn van '{vannaam}' naar '{naarnaam}'."]
        for vh in vanhaltes[:2]:
            vid = str(vh.get("id", ""))
            naam_dict = vh.get("name", {})
            vnaam = naam_dict.get("nl", naam_dict.get("fr", vannaam)) if isinstance(naam_dict, dict) else str(naam_dict)
            passages = _waiting_times(vid)
            lines.append(f"Vertrekken {vnaam}:")
            for p in passages[:4]:
                lines.append(_fmt_passage(p))
        return {"ok": False, "msg": "\n".join(lines)}

    vertrekken.sort(key=lambda x: x[0])
    uniek = []
    for _, regel in vertrekken:
        if regel not in uniek:
            uniek.append(regel)
        if len(uniek) >= maxroutes:
            break

    return {"ok": True, "msg": "\n".join(uniek)}


def vindhalte(naam: str) -> dict:
    """Zoekt een halte op naam en toont eerstvolgende vertrekken."""
    haltes = _zoek_haltes(naam, limit=10)
    if not haltes:
        return {"ok": False, "msg": f"Halte '{naam}' niet gevonden."}

    for h in haltes:
        hid = str(h.get("id", ""))
        naam_dict = h.get("name", {})
        hnaam = naam_dict.get("nl", naam_dict.get("fr", naam)) if isinstance(naam_dict, dict) else str(naam_dict)
        passages = _waiting_times(hid)
        if passages:
            lines = [hnaam]
            for p in passages[:6]:
                lines.append(_fmt_passage(p))
            return {"ok": True, "msg": "\n".join(lines)}

    return {"ok": False, "msg": f"Geen vertrektijden voor '{naam}'."}
