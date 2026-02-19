"""baksteenservice - analyser.py"""


import logging, re
from datetime import datetime
from typing import Dict, List, Optional


from stations import load_stations
from normalise import normalise


logger = logging.getLogger("baksteenservice.analyser")


_BARE_NO_ARG = {"nieuws"}


_KNOWN_COMMANDS = {
    "gpt", "janee", "trein", "route", "weer",
    "nieuws", "vertaling", "apotheker", "apotheek", "bus",
}


_QUESTION_WORDS = {
    "hoe ", "hoeveel ", "wat ", "waarom ", "wanneer ",
    "wie ", "waar ", "welke ", "welk ",
}


_TRAIN_KEYWORDS = re.compile(
    r"\b(trein|treinen|ic|intercity|spoor|nmbs|sncb|perron|station)\b",
    re.IGNORECASE,
)


# Tijdstip aan het einde van een bus-commando: 16:30 / 16.30 / 1630 / 16
_BUS_TIME_RE = re.compile(r"\s+(\d{1,2}[:.](\d{2})|\d{4}|\d{1,2})$")

# "perron" vlak voor het cijfer → geen tijdstip maar perronnummer
_PERRON_BEFORE_RE = re.compile(r"\bperron\s*$", re.IGNORECASE)



class SMSAnalyser:


    def __init__(self):
        self.stations, self._ordered_keys = load_stations()


    def analyse(self, message: Dict) -> Dict:
        text = message.get("text", "").strip()
        if not text:
            return {"intent": "unknown", "params": {}, "original": message}


        lower = text.lower()
        now   = datetime.now()


        # ── Vraagwoord + trein-trefwoord → verwijs naar trein-module ──────────
        if any(lower.startswith(qw) for qw in _QUESTION_WORDS) and _TRAIN_KEYWORDS.search(lower):
            return {
                "intent": "trein_help",
                "params": {"hint": text.strip()},
                "original": message,
            }


        # ── Overige vraagwoorden → GPT ─────────────────────────────────────
        if any(lower.startswith(qw) for qw in _QUESTION_WORDS):
            return {"intent": "gpt", "params": {"prompt": text.strip()}, "original": message}


        # ── gpt ───────────────────────────────────────────────────────────
        if lower.startswith("gpt "):
            return {"intent": "gpt", "params": {"prompt": text[4:].strip()}, "original": message}
        if lower.strip() == "gpt":
            return {"intent": "gpt_help", "params": {}, "original": message}


        # ── janee ─────────────────────────────────────────────────────────
        if lower.startswith("janee "):
            return {"intent": "janee", "params": {"question": text[6:].strip()}, "original": message}
        if lower.strip() == "janee":
            return {"intent": "janee_help", "params": {}, "original": message}


        # ── trein ─────────────────────────────────────────────────────────
        if lower.startswith("trein "):
            params = self._parse_trein(text[6:].strip(), now)
            if params:
                return {"intent": "trein", "params": params, "original": message}
            return {"intent": "trein_help", "params": {"raw": text}, "original": message}
        if lower.strip() == "trein":
            return {"intent": "trein_help", "params": {}, "original": message}


        # ── bus ───────────────────────────────────────────────────────────
        if lower.startswith("bus "):
            params = self._parse_bus(text[4:].strip(), now)
            if params:
                return {"intent": "bus", "params": params, "original": message}
            return {"intent": "bus_help", "params": {"raw": text}, "original": message}
        if lower.strip() == "bus":
            return {"intent": "bus_help", "params": {}, "original": message}


        # ── route ─────────────────────────────────────────────────────────
        if lower.startswith("route "):
            params = self._parse_route(text[6:].strip())
            if params:
                return {"intent": "route", "params": params, "original": message}
            return {"intent": "route_help", "params": {"raw": text}, "original": message}
        if lower.strip() == "route":
            return {"intent": "route_help", "params": {}, "original": message}


        # ── weer ──────────────────────────────────────────────────────────
        if lower.startswith("weer "):
            return {"intent": "weer", "params": {"city": text[5:].strip()}, "original": message}
        if lower.strip() == "weer":
            return {"intent": "weer_help", "params": {}, "original": message}


        # ── nieuws ────────────────────────────────────────────────────────
        if lower.strip() == "nieuws":
            return {"intent": "nieuws", "params": {}, "original": message}


        # ── vertaling ─────────────────────────────────────────────────────
        if lower.startswith("vertaling "):
            params = self._parse_vertaling(text[10:].strip())
            if params:
                return {"intent": "vertaling", "params": params, "original": message}
            return {"intent": "vertaling_help", "params": {"raw": text}, "original": message}
        if lower.strip() == "vertaling":
            return {"intent": "vertaling_help", "params": {}, "original": message}


        # ── apotheker / apotheek ──────────────────────────────────────────
        if lower.startswith("apotheker "):
            return {"intent": "apotheker", "params": {"postcode": text[10:].strip()}, "original": message}
        if lower.startswith("apotheek "):
            return {"intent": "apotheker", "params": {"postcode": text[9:].strip()}, "original": message}
        if lower.strip() in ("apotheker", "apotheek"):
            return {"intent": "apotheker_help", "params": {}, "original": message}


        return {"intent": "unknown", "params": {}, "original": message}


    # ── parsers ───────────────────────────────────────────────────────────────


    def _parse_vertaling(self, body: str) -> Optional[Dict]:
        parts = body.split(None, 1)
        if len(parts) < 2:
            return None
        return {"lang": parts[0].lower(), "text": parts[1]}


    def _parse_route(self, body: str) -> Optional[Dict]:
        m = re.split(r"\s+naar\s+", body, maxsplit=1, flags=re.IGNORECASE)
        if len(m) != 2:
            return None
        origin, destination = m[0].strip(), m[1].strip()
        if not origin or not destination:
            return None
        return {"origin": origin, "destination": destination}


    def _parse_bus(self, body: str, now: datetime) -> Optional[Dict]:
        """
        Syntaxvarianten:
          bus 202485                           -> haltenummer
          bus korenmarkt gent                  -> haltenaam
          bus tienen station naar leuven       -> route (zonder "van")
          bus van tienen station naar leuven   -> route (met "van")
          bus tienen naar leuven 16:30         -> route + tijdstip
          bus tienen naar leuven 1630          -> route + tijdstip (HHMM)
          bus tienen naar leuven 16            -> route + tijdstip (enkel uur)
          bus tienen perron 5 naar leuven      -> route, perron 5 is geen tijd
          bus <haltenaam> <lijnnr>             -> haltenaam + lijnfilter

        Geeft dict terug met:
          {"van": ..., "naar": ..., "tijd": datetime}  -> route (tijd = now als niet opgegeven)
          {"halte": ..., "lijn": ...}                   -> halteopzoeking
        """
        if not body:
            return None

        # ── Strip optioneel tijdstip achteraan ─────────────────────────────
        # Niet strippen als er "perron" vlak voor staat (bv. "perron 5")
        tijd = None
        m_time = _BUS_TIME_RE.search(body)
        if m_time and not _PERRON_BEFORE_RE.search(body[:m_time.start()]):
            parsed = self._parse_bus_time(m_time.group(1), now)
            if parsed:
                tijd  = parsed
                body  = body[:m_time.start()].strip()

        # Geen tijd opgegeven → gebruik now (zelfde gedrag als trein)
        if tijd is None:
            tijd = now.replace(second=0, microsecond=0)

        # ── Routeplanning: optioneel "van", verplicht "naar" ──────────────
        m = re.match(r'^(?:van\s+)?(.+?)\s+naar\s+(.+)$', body, re.IGNORECASE)
        if m:
            van_part  = m.group(1).strip()
            naar_part = m.group(2).strip()
            if van_part and naar_part:
                return {"van": van_part, "naar": naar_part, "tijd": tijd}

        # ── Haltenummer (4-7 cijfers) ─────────────────────────────────────
        if re.fullmatch(r"\d{4,7}", body.strip()):
            return {"halte": body.strip(), "lijn": None}

        # ── Haltenaam + optioneel lijnnummer als laatste token ────────────
        parts = body.split()
        lijn  = None
        if (len(parts) >= 2
                and re.fullmatch(r"[A-Za-z0-9]{1,4}", parts[-1])
                and re.search(r"\d", parts[-1])):
            lijn  = parts[-1]
            halte = " ".join(parts[:-1])
        else:
            halte = body

        return {"halte": halte, "lijn": lijn}


    @staticmethod
    def _parse_bus_time(time_str: str, now: datetime) -> Optional[datetime]:
        """Converteert HH:MM / HH.MM / HHMM / HH naar datetime."""
        time_str = time_str.strip()
        m = re.fullmatch(r"(\d{1,2})[:.](\d{2})", time_str)
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


    def _parse_trein(self, body, now):
        words = body.split()
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