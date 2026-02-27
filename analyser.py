"""baksteenservice - analyser.py"""

import logging, re
from datetime import datetime
from typing import Dict, Optional

from stations import load_stations
from normalise import normalise

logger = logging.getLogger("baksteenservice.analyser")

_QUESTION_WORDS = {
    "hoe ", "hoeveel ", "wat ", "waarom ", "wanneer ",
    "wie ", "waar ", "welke ", "welk ",
}

_TRAIN_KEYWORDS = re.compile(
    r"\b(trein|treinen|ic|intercity|spoor|nmbs|sncb|perron|station)\b",
    re.IGNORECASE,
)

_TIME_RE = re.compile(r"\s+(\d{1,2}[:.u](\d{2})|\d{4}|\d{1,2})$")
_PERRON_BEFORE_RE = re.compile(r"\bperron\s*$", re.IGNORECASE)
_SEP_RE = re.compile(r"\s+(?:naar|vers|to)\s+", re.IGNORECASE)

# trigger -> (gmaps_mode, transit_modes, max_routes, location_suffix, language)
_ROUTE_TRIGGERS = {
    "route f":  ("transit", "bus|tram|subway|train", 3, "",            "fr"),
    "route":    ("transit", "bus|tram|subway|train", 3, "",            "nl"),
    "wandel":   ("walking", "",                      1, "",            "nl"),
    "pied":     ("walking", "",                      1, "",            "fr"),
    "bus f":    ("transit", "bus|tram",              3, "",            "fr"),
    "bus":      ("transit", "bus|tram",              3, "",            "nl"),
    "mivb":     ("transit", "bus|subway|tram",       3, " brussel",    "nl"),
    "stib":     ("transit", "bus|subway|tram",       3, " bruxelles",  "fr"),
}

# All bare trigger words that should return help
_BARE_TRIGGERS = set(_ROUTE_TRIGGERS.keys())


class SMSAnalyser:

    def __init__(self):
        self.stations, self._ordered_keys = load_stations()

    def analyse(self, message: Dict) -> Dict:
        text  = message.get("text", "").strip()
        if not text:
            return {"intent": "unknown", "params": {}, "original": message}

        lower = text.lower()
        now   = datetime.now()

        # ── Vraagwoord + trein -> trein_help ───────────────────────────────
        if any(lower.startswith(qw) for qw in _QUESTION_WORDS) and _TRAIN_KEYWORDS.search(lower):
            return {"intent": "trein_help", "params": {"hint": text}, "original": message}

        # ── Vraagwoorden -> GPT ────────────────────────────────────────────
        if any(lower.startswith(qw) for qw in _QUESTION_WORDS):
            return {"intent": "gpt", "params": {"prompt": text}, "original": message}

        # ── GPT ────────────────────────────────────────────────────────────
        if lower.startswith("gpt "):
            return {"intent": "gpt", "params": {"prompt": text[4:].strip()}, "original": message}
        if lower.strip() == "gpt":
            return {"intent": "gpt_help", "params": {}, "original": message}

        # ── JANEE ──────────────────────────────────────────────────────────
        if lower.startswith("janee "):
            return {"intent": "janee", "params": {"question": text[6:].strip()}, "original": message}
        if lower.strip() == "janee":
            return {"intent": "janee_help", "params": {}, "original": message}

        # ── TREIN (iRail) ──────────────────────────────────────────────────
        if lower.startswith("trein "):
            params = self._parse_trein(text[6:].strip(), now)
            if params:
                return {"intent": "trein", "params": params, "original": message}
            return {"intent": "trein_help", "params": {"raw": text}, "original": message}
        if lower.strip() == "trein":
            return {"intent": "trein_help", "params": {}, "original": message}

        # ── Bare route trigger (no body) -> help ───────────────────────────
        if lower.strip() in _BARE_TRIGGERS:
            return {"intent": "route_help", "params": {}, "original": message}

        # ── ROUTE-COMMANDO'S (Google Maps) ─────────────────────────────────
        route_params = self._parse_route_command(lower, text, now)
        if route_params is not None:
            return {"intent": "route", "params": route_params, "original": message}

        # ── WEER ───────────────────────────────────────────────────────────
        if lower.startswith("weer "):
            return {"intent": "weer", "params": {"city": text[5:].strip()}, "original": message}
        if lower.strip() == "weer":
            return {"intent": "weer_help", "params": {}, "original": message}

        # ── NIEUWS ─────────────────────────────────────────────────────────
        if lower.strip() == "nieuws":
            return {"intent": "nieuws", "params": {}, "original": message}

        # ── VERTALING ──────────────────────────────────────────────────────
        if lower.startswith("vertaling "):
            params = self._parse_vertaling(text[10:].strip())
            if params:
                return {"intent": "vertaling", "params": params, "original": message}
            return {"intent": "vertaling_help", "params": {}, "original": message}
        if lower.strip() == "vertaling":
            return {"intent": "vertaling_help", "params": {}, "original": message}

        # ── APOTHEKER ──────────────────────────────────────────────────────
        if lower.startswith("apotheker "):
            return {"intent": "apotheker", "params": {"postcode": text[10:].strip()}, "original": message}
        if lower.startswith("apotheek "):
            return {"intent": "apotheker", "params": {"postcode": text[9:].strip()}, "original": message}
        if lower.strip() in ("apotheker", "apotheek"):
            return {"intent": "apotheker_help", "params": {}, "original": message}

        return {"intent": "unknown", "params": {}, "original": message}


    # ── Route parser ───────────────────────────────────────────────────────

    def _parse_route_command(self, lower: str, original: str, now: datetime) -> Optional[Dict]:
        matched = None
        body_original = None

        # Longest trigger first so "bus f" beats "bus", "route f" beats "route"
        for trigger in sorted(_ROUTE_TRIGGERS, key=len, reverse=True):
            prefix = trigger + " "
            if lower.startswith(prefix):
                matched       = _ROUTE_TRIGGERS[trigger]
                body_original = original[len(prefix):].strip()
                break

        if matched is None:
            return None

        # Body is empty after stripping -> should have been caught by bare-trigger
        # check above, but guard here too
        if not body_original:
            return None

        gmaps_mode, transit_modes, max_routes, loc_suffix, language = matched

        # Strip tijdstip achteraan
        tijd = None
        body_work = body_original
        m_time = _TIME_RE.search(body_work)
        if m_time and not _PERRON_BEFORE_RE.search(body_work[:m_time.start()]):
            parsed = self._parse_time_str(m_time.group(1), now)
            if parsed:
                tijd      = parsed
                body_work = body_work[:m_time.start()].strip()

        if tijd is None:
            tijd = now.replace(second=0, microsecond=0)

        # Splits origin/destination
        sep_match = _SEP_RE.search(body_work)
        if sep_match:
            origin      = body_work[:sep_match.start()].strip()
            destination = body_work[sep_match.end():].strip()
        else:
            # Geen scheidingswoord: alleen splitsen als exact 2 woorden
            words = body_work.split()
            if len(words) == 2:
                origin, destination = words[0], words[1]
            else:
                return None

        if not origin or not destination:
            return None

        if loc_suffix:
            origin      = origin      + loc_suffix
            destination = destination + loc_suffix

        return {
            "origin":        origin,
            "destination":   destination,
            "mode":          gmaps_mode,
            "transit_modes": transit_modes,
            "max_routes":    max_routes,
            "tijd":          tijd,
            "language":      language,
        }


    # ── Tijd parser ────────────────────────────────────────────────────────

    @staticmethod
    def _parse_time_str(time_str: str, now: datetime) -> Optional[datetime]:
        time_str = time_str.strip()
        m = re.fullmatch(r"(\d{1,2})[:.u](\d{2})", time_str)
        if m:
            h, mn = int(m.group(1)), int(m.group(2))
            if 0 <= h <= 23 and 0 <= mn <= 59:
                return now.replace(hour=h, minute=mn, second=0, microsecond=0)
        m = re.fullmatch(r"(\d{2})(\d{2})", time_str)
        if m:
            h, mn = int(m.group(1)), int(m.group(2))
            if 0 <= h <= 23 and 0 <= mn <= 59:
                return now.replace(hour=h, minute=mn, second=0, microsecond=0)
        m = re.fullmatch(r"(\d{1,2})", time_str)
        if m:
            h = int(m.group(1))
            if 0 <= h <= 23:
                return now.replace(hour=h, minute=0, second=0, microsecond=0)
        return None


    # ── Vertaling parser ───────────────────────────────────────────────────

    def _parse_vertaling(self, body: str) -> Optional[Dict]:
        parts = body.split(None, 1)
        if len(parts) < 2:
            return None
        return {"lang": parts[0].lower(), "text": parts[1]}


    # ── Trein parsers (ongewijzigd) ────────────────────────────────────────

    def _parse_trein(self, body, now):
        words = [w for w in body.split() if w.lower() != "naar"]
        departure, dep_end = self._match_station(words, 0)
        if departure is None:
            return None
        arrival, arr_end = self._match_station(words, dep_end)
        if arrival is None:
            return None
        time_str = " ".join(words[arr_end:]).strip()
        t = self._parse_time(time_str, now)
        return {
            "departure": departure,
            "arrival":   arrival,
            "time":      t,
            "time_str":  t.strftime("%H:%M"),
        }

    def _match_station(self, words, start):
        time_re = re.compile(r"^\d{1,2}(:\d{2})?$")
        best_exact = best_prefix = best_suffix = (None, start)
        for end in range(start + 1, len(words) + 1):
            if time_re.match(words[end - 1]):
                break
            candidate = normalise("-".join(words[start:end]))
            if candidate in self.stations and best_exact[0] is None:
                best_exact = (self.stations[candidate], end)
            if best_prefix[0] is None:
                hit = self._first_prefix_match(candidate)
                if hit:
                    best_prefix = (self.stations[hit], end)
            if best_suffix[0] is None:
                hit = self._suffix_or_partial_match(candidate)
                if hit:
                    best_suffix = (self.stations[hit], end)
        if best_exact[0]:  return best_exact
        if best_prefix[0]: return best_prefix
        if best_suffix[0]: return best_suffix
        return None, start

    def _first_prefix_match(self, c):
        p = c + "-"
        for k in self._ordered_keys:
            if k.startswith(p):
                return k

    def _suffix_or_partial_match(self, c):
        for k in self._ordered_keys:
            if c in k.split("-"):
                return k

    def _parse_time(self, time_str, now):
        if not time_str:
            return now.replace(second=0, microsecond=0)
        m = re.fullmatch(r"(\d{1,2})(?::(\d{2}))?", time_str.strip())
        if m:
            h, mn = int(m.group(1)), int(m.group(2)) if m.group(2) else 0
            if 0 <= h <= 23 and 0 <= mn <= 59:
                return now.replace(hour=h, minute=mn, second=0, microsecond=0)
        return now.replace(second=0, microsecond=0)
