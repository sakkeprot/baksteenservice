"""
baksteenservice - analyser.py

Supported commands:
  gpt <prompt>       — free-form AI question, reply max 160 chars
  janee <question>   — yes/no question, reply is only "Ja" or "Nee"
  trein <dep> <arr> [time]

Station matching — three passes (file order wins on ties):
  1. Exact  2. Prefix fallback  3. Suffix/partial fallback
"""
import logging, re
from datetime import datetime
from typing import Dict, List, Optional, Tuple
from stations import load_stations
from normalise import normalise

logger = logging.getLogger("baksteenservice.analyser")

class SMSAnalyser:
    def __init__(self):
        self.stations, self._ordered_keys = load_stations()

    def analyse(self, message: Dict) -> Dict:
        text = message.get("text", "").strip()
        now  = datetime.now()
        lower = text.lower()

        if lower.startswith("gpt "):
            prompt = text[4:].strip()
            logger.info(f"Intent: gpt | prompt: {prompt!r}")
            return {"intent": "gpt", "params": {"prompt": prompt}, "original": message}

        if lower.startswith("janee "):
            question = text[6:].strip()
            logger.info(f"Intent: janee | question: {question!r}")
            return {"intent": "janee", "params": {"question": question}, "original": message}

        if lower.startswith("trein "):
            params = self._parse_trein(text[6:].strip(), now)
            if params:
                logger.info(f"Intent: trein | {params['departure']} → {params['arrival']} @ {params['time_str']}")
                return {"intent": "trein", "params": params, "original": message}
            logger.warning(f"trein parse failed: {text!r}")
            return {"intent": "trein_parse_error", "params": {"raw": text}, "original": message}

        logger.info(f"Intent: unknown | text: {text!r}")
        return {"intent": "unknown", "params": {}, "original": message}

    def _parse_trein(self, body, now):
        words = body.split()
        departure, dep_end = self._match_station(words, 0)
        if departure is None: return None
        arrival, arr_end = self._match_station(words, dep_end)
        if arrival is None: return None
        time_str = " ".join(words[arr_end:]).strip()
        time = self._parse_time(time_str, now)
        return {"departure": departure, "arrival": arrival, "time": time, "time_str": time.strftime("%H:%M")}

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
        if best_prefix[0]: logger.info(f"Prefix fallback → {best_prefix[0]!r}"); return best_prefix
        if best_suffix[0]: logger.info(f"Suffix fallback → {best_suffix[0]!r}"); return best_suffix
        return None, start

    def _first_prefix_match(self, candidate):
        prefix = candidate + "-"
        for key in self._ordered_keys:
            if key.startswith(prefix): return key

    def _suffix_or_partial_match(self, candidate):
        for key in self._ordered_keys:
            if candidate in key.split("-"): return key

    def _parse_time(self, time_str, now):
        if not time_str: return now.replace(second=0, microsecond=0)
        m = re.fullmatch(r"(\d{1,2})(?::(\d{2}))?", time_str.strip())
        if m:
            h, mn = int(m.group(1)), int(m.group(2)) if m.group(2) else 0
            if 0 <= h <= 23 and 0 <= mn <= 59:
                return now.replace(hour=h, minute=mn, second=0, microsecond=0)
        logger.warning(f"Could not parse time {time_str!r} — using now")
        return now.replace(second=0, microsecond=0)
