"""baksteenservice - action.py"""
import logging
from datetime import datetime
from typing import Dict, List

import requests
from openai import OpenAI
import secrets as _secrets

logger = logging.getLogger("baksteenservice.action")

MAX_SMS_LENGTH   = 306
IRAIL_BASE       = "https://api.irail.be"
IRAIL_USER_AGENT = "baksteenservice/1.0 (github.com/sander/baksteenservice)"
IRAIL_RESULTS    = 6   # fetch 6, display first 3


def _truncate(text: str, max_len: int = MAX_SMS_LENGTH) -> str:
    if len(text) <= max_len:
        return text
    return text[: max_len - 1] + "…"


def _ts(unix, delay_sec=0) -> str:
    """
    Unix timestamp → "HH:MM" with optional delay suffix.
    _ts(t, 180)  →  "12:03 +3'"
    _ts(t, 0)    →  "12:03"
    """
    t = datetime.fromtimestamp(int(unix)).strftime("%H:%M")
    delay = int(delay_sec)
    if delay > 0:
        t += f" +{delay // 60}'"
    return t


def _plat(leg: dict) -> str:
    """Return ' per.X' when platform is known, else empty string."""
    name = leg.get("platforminfo", {}).get("name", "").strip()
    return f" per.{name}" if name else ""


def _fmt(conn: dict) -> str:
    """
    Format one iRail connection.

    No delay, direct:
      12:03 Leuven per.12 -> 13:01 Brussel-Centraal per.2

    With delay on departure:
      12:03 +3' Leuven per.12 -> 13:01 Brussel-Centraal per.2

    With via + delays:
      12:07 +2' Leuven per.13 -> 12:30 Brussel-Noord per.1 | per.4 12:35 +5' -> 12:59 Brussel-Centraal per.6
    """
    dep  = conn["departure"]
    arr  = conn["arrival"]
    vias = conn.get("vias", {})

    dep_time = _ts(dep["time"], dep.get("delay", 0))
    dep_name = dep.get("stationinfo", {}).get("standardname", dep.get("station", "?"))
    dep_plat = _plat(dep)

    arr_time = _ts(arr["time"], arr.get("delay", 0))
    arr_name = arr.get("stationinfo", {}).get("standardname", arr.get("station", "?"))
    arr_plat = _plat(arr)

    if not vias or int(vias.get("number", 0)) == 0:
        return f"{dep_time} {dep_name}{dep_plat} -> {arr_time} {arr_name}{arr_plat}"

    via_list = vias["via"]
    if isinstance(via_list, dict):
        via_list = [via_list]

    parts = [f"{dep_time} {dep_name}{dep_plat}"]
    for via in via_list:
        v_arr      = via["arrival"]
        v_dep      = via["departure"]
        v_name     = via.get("stationinfo", {}).get("standardname", via.get("station", "?"))
        v_arr_time = _ts(v_arr["time"], v_arr.get("delay", 0))
        v_dep_time = _ts(v_dep["time"], v_dep.get("delay", 0))
        v_arr_plat = _plat(v_arr)
        v_dep_plat = _plat(v_dep)
        parts.append(f"-> {v_arr_time} {v_name}{v_arr_plat} |{v_dep_plat} {v_dep_time}")

    parts.append(f"-> {arr_time} {arr_name}{arr_plat}")
    return " ".join(parts)


class ActionHandler:
    def __init__(self):
        self.ACTION_MAP = {
            "gpt":               self._action_gpt,
            "janee":             self._action_janee,
            "trein":             self._action_trein,
            "trein_parse_error": self._action_trein_error,
            "unknown":           self._action_unknown,
        }
        self._gpt_client = OpenAI(
            api_key=_secrets.DEEPSEEK_API_KEY,
            base_url="https://api.deepseek.com",
        )

    def execute(self, analysis: Dict) -> Dict:
        intent = analysis.get("intent", "unknown")
        params = analysis.get("params", {})
        fn     = self.ACTION_MAP.get(intent, self._action_unknown)
        try:
            result = fn(params)
            logger.info(f"Action '{intent}' → {str(result['message'])[:80]}")
            return result
        except Exception as e:
            logger.error(f"Action '{intent}' raised: {e}", exc_info=True)
            return {"success": False, "message": f"Fout: {e}", "data": {}}

    # ------------------------------------------------------------------
    # GPT — free-form, max 160 chars
    # ------------------------------------------------------------------

    def _action_gpt(self, params: Dict) -> Dict:
        prompt = params.get("prompt", "")
        if not prompt:
            return {"success": False, "message": "Geen prompt ontvangen.", "data": {}}
        response = self._gpt_client.chat.completions.create(
            model="deepseek-chat",
            messages=[
                {"role": "system", "content": (
                    "You are a concise assistant. "
                    "Your reply will be sent as an SMS — MUST fit in 160 characters. "
                    "Never exceed 160 characters. Be brief and direct."
                )},
                {"role": "user", "content": prompt},
            ],
            stream=False,
        )
        answer = _truncate(response.choices[0].message.content.strip())
        return {"success": True, "message": answer, "data": {"prompt": prompt}}

    # ------------------------------------------------------------------
    # JANEE — strictly "Ja" or "Nee"
    # ------------------------------------------------------------------

    def _action_janee(self, params: Dict) -> Dict:
        question = params.get("question", "")
        if not question:
            return {"success": False, "message": "Geen vraag ontvangen.", "data": {}}
        response = self._gpt_client.chat.completions.create(
            model="deepseek-chat",
            messages=[
                {"role": "system", "content": (
                    "You are a yes/no oracle. "
                    "Reply with ONLY 'Ja' or 'Nee'. No punctuation, no explanation."
                )},
                {"role": "user", "content": question},
            ],
            stream=False,
        )
        raw    = response.choices[0].message.content.strip()
        answer = "Ja" if raw.lower() in ("ja", "yes", "true", "1", "j") else "Nee"
        return {"success": True, "message": answer, "data": {"question": question, "raw": raw}}

    # ------------------------------------------------------------------
    # TREIN — iRail connections, next 3 with delay info
    # ------------------------------------------------------------------

    def _action_trein(self, params: Dict) -> Dict:
        dep      = params.get("departure", "")
        arr      = params.get("arrival",   "")
        dep_time = params.get("time",      datetime.now())

        date_str = dep_time.strftime("%d%m%y")
        time_str = dep_time.strftime("%H%M")

        logger.info(f"iRail: {dep} → {arr} @ {time_str} {date_str}")

        try:
            resp = requests.get(
                f"{IRAIL_BASE}/connections/",
                params={
                    "from":            dep,
                    "to":              arr,
                    "date":            date_str,
                    "time":            time_str,
                    "timesel":         "departure",
                    "format":          "json",
                    "lang":            "nl",
                    "results":         str(IRAIL_RESULTS),
                    "typeOfTransport": "trains",
                },
                headers={"User-Agent": IRAIL_USER_AGENT},
                timeout=10,
            )
            resp.raise_for_status()
        except requests.RequestException as e:
            logger.error(f"iRail request failed: {e}")
            return {"success": False, "message": f"iRail fout: {e}", "data": {}}

        connections = resp.json().get("connection", [])
        if not connections:
            return {"success": False, "message": f"Geen treinen gevonden van {dep} naar {arr}.", "data": {}}

        lines   = [_fmt(c) for c in connections[:3]]
        message = _truncate("\n".join(lines))
        logger.info(f"iRail reply:\n{message}")
        return {"success": True, "message": message, "data": {"connections": len(lines)}}

    # ------------------------------------------------------------------
    # Error / unknown
    # ------------------------------------------------------------------

    def _action_trein_error(self, params: Dict) -> Dict:
        return {"success": False, "message": "Station niet herkend. Gebruik: trein <vertrek> <aankomst> [uur]", "data": params}

    def _action_unknown(self, params: Dict) -> Dict:
        return {"success": False, "message": "Onbekend commando. Beschikbaar: gpt <tekst>, janee <vraag>, trein <vertrek> <aankomst> [uur]", "data": {}}
