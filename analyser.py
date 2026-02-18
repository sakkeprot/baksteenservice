"""
baksteenservice - analyser.py

Commands:
  gpt <prompt>
  janee <question>
  trein <dep> <arr> [time]
  route <from> NAAR <to>
  weer <city>
  nieuws
  vertaling <taal> <tekst>
  apotheker <postcode>
"""
import logging, re
from datetime import datetime
from typing import Dict, List, Optional
from stations import load_stations
from normalise import normalise

logger = logging.getLogger("baksteenservice.analyser")

class SMSAnalyser:
    def __init__(self):
        self.stations, self._ordered_keys = load_stations()

    def analyse(self, message: Dict) -> Dict:
        text  = message.get("text", "").strip()
        now   = datetime.now()
        lower = text.lower()

        if lower.startswith("gpt "):
            return {"intent": "gpt", "params": {"prompt": text[4:].strip()}, "original": message}

        if lower.startswith("janee "):
            return {"intent": "janee", "params": {"question": text[6:].strip()}, "original": message}

        if lower.startswith("trein "):
            params = self._parse_trein(text[6:].strip(), now)
            if params:
                return {"intent": "trein", "params": params, "original": message}
            return {"intent": "trein_parse_error", "params": {"raw": text}, "original": message}

        if lower.startswith("route "):
            params = self._parse_route(text[6:].strip())
            if params:
                return {"intent": "route", "params": params, "original": message}
            return {"intent": "route_parse_error", "params": {"raw": text}, "original": message}

        if lower.startswith("weer "):
            return {"intent": "weer", "params": {"city": text[5:].strip()}, "original": message}

        if lower.strip() == "nieuws":
            return {"intent": "nieuws", "params": {}, "original": message}

        if lower.startswith("vertaling "):
            params = self._parse_vertaling(text[10:].strip())
            if params:
                return {"intent": "vertaling", "params": params, "original": message}
            return {"intent": "vertaling_error", "params": {"raw": text}, "original": message}

        if lower.startswith("apotheker "):
            return {"intent": "apotheker", "params": {"postcode": text[10:].strip()}, "original": message}
        if lower.startswith("apotheek "):
            return {"intent": "apotheker", "params": {"postcode": text[9:].strip()}, "original": message}

        return {"intent": "unknown", "params": {}, "original": message}
    

    def _parse_vertaling(self, body: str) -> Optional[Dict]:
        parts = body.split(None, 1)
        if len(parts) < 2: return None
        return {"lang": parts[0].lower(), "text": parts[1]}

    def _parse_route(self, body: str) -> Optional[Dict]:
        m = re.split(r"\s+naar\s+", body, maxsplit=1, flags=re.IGNORECASE)
        if len(m) != 2: return None
        origin, destination = m[0].strip(), m[1].strip()
        if not origin or not destination: return None
        return {"origin": origin, "destination": destination}

    def _parse_trein(self, body, now):
        words = body.split()
        departure, dep_end = self._match_station(words, 0)
        if departure is None: return None
        arrival, arr_end = self._match_station(words, dep_end)
        if arrival is None: return None
        time_str = " ".join(words[arr_end:]).strip()
        t = self._parse_time(time_str, now)
        return {"departure": departure, "arrival": arrival, "time": t, "time_str": t.strftime("%H:%M")}

    def _match_station(self, words, start):
        time_re = re.compile(r"^\d{1,2}(:\d{2})?$")
        best_exact = best_prefix = best_suffix = (None, start)
        for end in range(start + 1, len(words) + 1):
            if time_re.match(words[end - 1]): break
            candidate = normalise("-".join(words[start:end]))
            if candidate in self.stations and best_exact[0] is None:
                best_exact = (self.stations[candidate], end)
            if best_prefix[0] is None:
                hit = self._first_prefix_match(candidate)
                if hit: best_prefix = (self.stations[hit], end)
            if best_suffix[0] is None:
                hit = self._suffix_or_partial_match(candidate)
                if hit: best_suffix = (self.stations[hit], end)
        if best_exact[0]: return best_exact
        if best_prefix[0]: return best_prefix
        if best_suffix[0]: return best_suffix
        return None, start

    def _first_prefix_match(self, c):
        p = c + "-"
        for k in self._ordered_keys:
            if k.startswith(p): return k

    def _suffix_or_partial_match(self, c):
        for k in self._ordered_keys:
            if c in k.split("-"): return k

    def _parse_time(self, time_str, now):
        if not time_str: return now.replace(second=0, microsecond=0)
        m = re.fullmatch(r"(\d{1,2})(?::(\d{2}))?", time_str.strip())
        if m:
            h, mn = int(m.group(1)), int(m.group(2)) if m.group(2) else 0
            if 0 <= h <= 23 and 0 <= mn <= 59:
                return now.replace(hour=h, minute=mn, second=0, microsecond=0)
        return now.replace(second=0, microsecond=0)