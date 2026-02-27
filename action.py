"""baksteenservice - action.py"""

import html, logging, re, xml.etree.ElementTree as ET
from datetime import datetime
from typing import Dict, List, Optional

import requests
from bs4 import BeautifulSoup
from openai import OpenAI

import secrets as _secrets
import config
import route as _route

logger = logging.getLogger("baksteenservice.action")

IRAIL_BASE       = "https://api.irail.be"
IRAIL_USER_AGENT = "baksteenservice/1.0 (github.com/sakkeprot/baksteenservice)"
IRAIL_RESULTS    = 6

NEWS_FEEDS = [
    "https://www.vrt.be/vrtnws/nl.rss.articles.xml",
    "https://www.demorgen.be/rss.xml",
]

_SKIP_TEXT = {"cookie", "essentieel", "verplicht", "privac", "javascript",
              "openingsuren", "meer info", "toon", "©", "zoek"}

_ADDRESS_RE = re.compile(r'.+\d+.*\d{4}\s+\w+', re.IGNORECASE)


# ── Hulpfuncties ───────────────────────────────────────────────────────────────

def _truncate(text: str, max_len: int) -> str:
    if len(text) <= max_len:
        return text
    return text[:max_len - 1] + "..."


def _ts(unix, delay_sec=0) -> str:
    t = datetime.fromtimestamp(int(unix)).strftime("%H:%M")
    d = int(delay_sec)
    if d > 0:
        t += f" +{d//60}'"
    return t


def _plat(leg: dict) -> str:
    """Geeft ' spoor X' terug als platforminfo beschikbaar is."""
    name = leg.get("platforminfo", {}).get("name", "").strip()
    return f" spoor {name}" if name else ""


def _fmt_train(conn: dict) -> str:
    dep = conn["departure"]; arr = conn["arrival"]; vias = conn.get("vias", {})
    dep_time = _ts(dep["time"], dep.get("delay", 0))
    dep_name = dep.get("stationinfo", {}).get("standardname", dep.get("station", "?"))
    arr_time = _ts(arr["time"], arr.get("delay", 0))
    arr_name = arr.get("stationinfo", {}).get("standardname", arr.get("station", "?"))
    if not vias or int(vias.get("number", 0)) == 0:
        return f"{dep_time} {dep_name}{_plat(dep)} -> {arr_time} {arr_name}{_plat(arr)}"
    via_list = vias["via"]
    if isinstance(via_list, dict):
        via_list = [via_list]
    parts = [f"{dep_time} {dep_name}{_plat(dep)}"]
    for via in via_list:
        v_arr  = via["arrival"]; v_dep = via["departure"]
        v_name = via.get("stationinfo", {}).get("standardname", via.get("station", "?"))
        parts.append(
            f"-> {_ts(v_arr['time'], v_arr.get('delay', 0))} {v_name}{_plat(v_arr)}"
            f" |{_plat(v_dep)} {_ts(v_dep['time'], v_dep.get('delay', 0))}"
        )
    parts.append(f"-> {arr_time} {arr_name}{_plat(arr)}")
    return " ".join(parts)


def _classify_pharmacy_texts(texts: List[str]):
    name = address = phone = None
    for t in texts:
        t = t.strip()
        if not t or len(t) < 2:
            continue
        if any(s in t.lower() for s in _SKIP_TEXT):
            continue
        if re.match(r'^[\d\s/+]{7,15}$', t):
            if not phone:
                phone = t.replace(" ", "")
            continue
        if _ADDRESS_RE.match(t) or re.search(r'\d{4}', t):
            if not address:
                address = t
            continue
        if not name and len(t) > 3:
            name = t
    return name, address, phone


# ── ActionHandler ──────────────────────────────────────────────────────────────

class ActionHandler:

    def __init__(self):
        self.ACTION_MAP = {
            "gpt":            self._action_gpt,
            "gpt_help":       self._action_gpt_help,
            "janee":          self._action_janee,
            "janee_help":     self._action_janee_help,
            "trein":          self._action_trein,
            "trein_help":     self._action_trein_help,
            "route":          self._action_route,
            "route_help":     self._action_route_help,
            "weer":           self._action_weer,
            "weer_help":      self._action_weer_help,
            "nieuws":         self._action_nieuws,
            "vertaling":      self._action_vertaling,
            "vertaling_help": self._action_vertaling_help,
            "apotheker":      self._action_apotheker,
            "apotheker_help": self._action_apotheker_help,
            "unknown":        self._action_unknown,
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
            logger.info(f"Action '{intent}' -> {str(result['message'])[:80]}")
            return result
        except Exception as e:
            logger.error(f"Action '{intent}' raised: {e}", exc_info=True)
            return {"success": False, "message": f"Fout: {e}", "data": {}}


    # ── GPT ───────────────────────────────────────────────────────────────────

    def _action_gpt(self, params):
        prompt = params.get("prompt", "")
        if not prompt:
            return {"success": False, "message": "Geen prompt ontvangen.", "data": {}}
        max_len = config.sms_max("gpt")
        r = self._gpt_client.chat.completions.create(
            model="deepseek-chat", stream=False,
            messages=[
                {"role": "system", "content": (
                    f"U bent de assistent van een inwoner van Belgie. "
                    f"Uw volledige antwoord wordt als sms bezorgd aan de verzoeker. "
                    f"Het antwoord mag maximaal {max_len} tekens lang zijn (inclusief spaties). "
                    f"Herhaal de vraag niet, antwoord direct, bondig en correct. "
                    f"Vermeld de tekenlimiet niet. "
                    f"Antwoord in de taal van de vraagsteller."
                )},
                {"role": "user", "content": prompt},
            ])
        return {"success": True,
                "message": _truncate(r.choices[0].message.content.strip(), max_len),
                "data": {}}

    def _action_gpt_help(self, params):
        return {"success": False, "message": (
            "Gebruik: gpt <vraag>\n"
            "Stel een vraag aan DeepSeek.\n"
            "Voorbeeld: gpt wat is de hoofdstad van Spanje"
        ), "data": {}}


    # ── JANEE ─────────────────────────────────────────────────────────────────

    def _action_janee(self, params):
        q = params.get("question", "")
        if not q:
            return {"success": False, "message": "Geen vraag ontvangen.", "data": {}}
        r = self._gpt_client.chat.completions.create(
            model="deepseek-chat", stream=False,
            messages=[
                {"role": "system", "content": "Reply ONLY with 'Ja' or 'Nee'. Nothing else."},
                {"role": "user",   "content": q},
            ])
        raw = r.choices[0].message.content.strip()
        return {"success": True,
                "message": "Ja" if raw.lower() in ("ja", "yes", "true", "1", "j") else "Nee",
                "data": {}}

    def _action_janee_help(self, params):
        return {"success": False, "message": (
            "Gebruik: janee <vraag>\n"
            "DeepSeek antwoordt alleen met ja of nee.\n"
            "Voorbeeld: janee is Brussel de hoofdstad van Belgie"
        ), "data": {}}


    # ── TREIN (via iRail, ongewijzigd) ────────────────────────────────────────

    def _action_trein(self, params):
        dep      = params.get("departure", "")
        arr      = params.get("arrival",   "")
        dep_time = params.get("time", datetime.now())
        try:
            resp = requests.get(
                f"{IRAIL_BASE}/connections/", timeout=10,
                headers={"User-Agent": IRAIL_USER_AGENT},
                params={
                    "from": dep, "to": arr,
                    "date": dep_time.strftime("%d%m%y"),
                    "time": dep_time.strftime("%H%M"),
                    "timesel": "departure", "format": "json", "lang": "nl",
                    "results": str(IRAIL_RESULTS), "typeOfTransport": "trains",
                })
            resp.raise_for_status()
        except requests.RequestException as e:
            return {"success": False, "message": f"Server fout: {e}", "data": {}}
        conns = resp.json().get("connection", [])
        if not conns:
            return {"success": False, "message": f"Geen treinen {dep}->{arr}.", "data": {}}
        max_len = config.sms_max("trein")
        return {"success": True,
                "message": _truncate("\n".join(_fmt_train(c) for c in conns[:3]), max_len),
                "data": {}}

    def _action_trein_help(self, params):
        hint  = params.get("hint", "")
        extra = f"\nJe vroeg: \"{hint}\"" if hint else ""
        return {"success": False, "message": (
            "Gebruik: trein <van> <naar> [uur]\n"
            "Zoek treinuren via iRail.\n"
            "Voorbeeld: trein gent brussel 14:30\n"
            "Uur weglaten = vertrekt nu" + extra
        ), "data": {}}


    # ── ROUTE (Google Maps) ───────────────────────────────────────────────────

    def _action_route(self, params: Dict) -> Dict:
        origin      = params.get("origin",        "")
        destination = params.get("destination",   "")
        language    = params.get("language",       "nl")

        if not origin or not destination:
            return self._action_route_help(params)

        result = _route.vind_route(
            origin        = origin,
            destination   = destination,
            mode          = params.get("mode",          "transit"),
            transit_modes = params.get("transit_modes", "bus|tram|subway|train"),
            max_routes    = params.get("max_routes",    3),
            vanaf         = params.get("tijd",          None),
            language      = language,
        )
        return {
            "success": result["ok"],
            "message": _truncate(result["msg"], config.sms_max("route")),
            "data": {},
        }


    def _action_route_help(self, params):
        return {"success": False, "message": (
            "Gebruik: <commando> <van> naar <naar> [tijd]\n"
            "route  - alle vervoer (NL)\n"
            "wandel (NL) | pied (FR)\n"
            "bus (NL) of bus f (FR)\n"
            "mivb / stib   - Brussel transit\n"
            "Vb: route leuven naar tienen 17:00\n"
            "Vb: stib gare central vers gare midi"
        ), "data": {}}


    # ── WEER ──────────────────────────────────────────────────────────────────

    def _resolve_city_id(self, city: str) -> Optional[int]:
        def _search(query: str):
            try:
                r = requests.get(
                    "http://api.weatherapi.com/v1/search.json", timeout=10,
                    params={"key": _secrets.OWM_API_KEY, "q": query})
                r.raise_for_status()
                return r.json()
            except requests.RequestException as e:
                logger.error(f"WeatherAPI search error: {e}")
                return []
        city_lower = city.strip().lower()
        results = _search(city)
        for loc in results:
            if loc["name"].lower() == city_lower:
                return loc["id"]
        results_be = _search(f"{city},belgie")
        for loc in results_be:
            if loc["name"].lower() == city_lower:
                return loc["id"]
        return results[0]["id"] if results else None

    def _action_weer(self, params: Dict) -> Dict:
        city = params.get("city", "").strip()
        if not city:
            return {"success": False, "message": "Gebruik: weer <stad>", "data": {}}
        location_id = self._resolve_city_id(city)
        if location_id is None:
            return {"success": False, "message": f"Stad '{city}' niet gevonden.", "data": {}}
        try:
            r = requests.get(
                "http://api.weatherapi.com/v1/forecast.json", timeout=10,
                params={"key": _secrets.OWM_API_KEY, "q": f"id:{location_id}", "days": 1,
                        "lang": "nl", "aqi": "no", "alerts": "no"})
            r.raise_for_status()
        except requests.RequestException as e:
            return {"success": False, "message": f"Weer fout: {e}", "data": {}}
        d        = r.json()
        name     = d["location"]["name"]
        day      = d["forecast"]["forecastday"][0]["day"]
        min_c    = round(day["mintemp_c"])
        max_c    = round(day["maxtemp_c"])
        now_hour = datetime.now().hour
        hours    = d["forecast"]["forecastday"][0]["hour"]
        upcoming = [h for h in hours
                    if int(h["time"].split(" ")[1].split(":")[0]) >= now_hour][:4]
        if not upcoming:
            return {"success": False, "message": "Geen uurlijkse data beschikbaar.", "data": {}}
        lines = [name, f"Vandaag min: {min_c}C max: {max_c}C"]
        for h in upcoming:
            t    = h["time"].split(" ")[1][:5]
            temp = round(h["temp_c"])
            desc = h["condition"]["text"]
            wind = round(h["wind_kph"])
            rain = h.get("chance_of_rain", 0)
            lines.append(f"{t} {temp}C {desc}, wind: {wind}km/h, regen: {rain}%")
        return {"success": True,
                "message": _truncate("\n".join(lines), config.sms_max("weer")),
                "data": {}}

    def _action_weer_help(self, params):
        return {"success": False, "message": (
            "Gebruik: weer <stad>\n"
            "Geeft weersvoorspelling voor de komende uren.\n"
            "Voorbeeld: weer gent"
        ), "data": {}}


    # ── NIEUWS ────────────────────────────────────────────────────────────────

    def _action_nieuws(self, params: Dict) -> Dict:
        max_len = config.sms_max("nieuws")
        for feed_url in NEWS_FEEDS:
            try:
                r = requests.get(feed_url, timeout=10, headers={"User-Agent": "Mozilla/5.0"})
                if r.status_code != 200 or not r.content:
                    continue
                root  = ET.fromstring(r.content)
                items = root.findall(".//item")[:3]
                if not items:
                    continue
                lines = []
                for item in items:
                    title = html.unescape(item.findtext("title", "").strip())
                    if len(title) > 100:
                        title = title[:99] + "..."
                    lines.append(title)
                msg = "\n".join(f"{i+1}. {t}" for i, t in enumerate(lines))
                return {"success": True, "message": _truncate(msg, max_len), "data": {}}
            except Exception as e:
                logger.warning(f"RSS {feed_url} failed: {e}")
        return {"success": False, "message": "Nieuws tijdelijk niet beschikbaar.", "data": {}}


    # ── VERTALING ─────────────────────────────────────────────────────────────

    def _action_vertaling(self, params: Dict) -> Dict:
        lang = params.get("lang", "en")
        text = params.get("text", "")
        if not text:
            return {"success": False, "message": "Geen tekst om te vertalen.", "data": {}}
        lang_names = {
            "en": "English", "fr": "French", "de": "German", "es": "Spanish",
            "nl": "Dutch",   "it": "Italian", "pt": "Portuguese", "pl": "Polish",
            "tr": "Turkish", "ar": "Arabic",  "zh": "Chinese",    "ru": "Russian",
        }
        lang_full = lang_names.get(lang.lower(), lang)
        r = self._gpt_client.chat.completions.create(
            model="deepseek-chat", stream=False,
            messages=[
                {"role": "system", "content": f"Translate to {lang_full}. Return ONLY the translation."},
                {"role": "user",   "content": text},
            ])
        translation = r.choices[0].message.content.strip()
        return {"success": True,
                "message": _truncate(f"{text} -> {translation}", config.sms_max("vertaling")),
                "data": {}}

    def _action_vertaling_help(self, params):
        return {"success": False, "message": (
            "Gebruik: vertaling <taal> <tekst>\n"
            "Taalcodes: en fr de es nl it pt pl tr ar zh ru\n"
            "Voorbeeld: vertaling en fiets"
        ), "data": {}}


    # ── APOTHEKER ─────────────────────────────────────────────────────────────

    def _action_apotheker(self, params: Dict) -> Dict:
        import json
        query = params.get("postcode", "").strip()
        if not query:
            return {"success": False, "message": "Gebruik: apotheker <postcode>", "data": {}}
        try:
            r = requests.get(
                "https://www.apotheek.be/PharmacySearch",
                params={"OnDutyTouched": "true", "Query": query, "OnDuty": "true"},
                headers={"User-Agent": "Mozilla/5.0", "Accept-Language": "nl-BE"},
                timeout=10,
            )
            r.raise_for_status()
        except requests.RequestException as e:
            return {"success": False, "message": f"Apotheek fout: {e}", "data": {}}
        soup    = BeautifulSoup(r.text, "html.parser")
        results: List[str] = []
        for card in soup.select(".pharmacy-accordion-card[data-pharmacy]"):
            raw = card.get("data-pharmacy", "")
            if not raw:
                continue
            try:
                data = json.loads(raw)
            except json.JSONDecodeError:
                continue
            if not data.get("OnDuty", False):
                continue
            name    = data.get("Name",    "").strip()
            address = data.get("Address", "").strip()
            phone   = data.get("Phone",   "").strip()
            line_parts = [p for p in [name, address, phone] if p]
            if line_parts:
                results.append("\n".join(line_parts))
            if len(results) >= 2:
                break
        max_len = config.sms_max("apotheker")
        if results:
            return {"success": True,
                    "message": _truncate("\n---\n".join(results), max_len),
                    "data": {}}
        return {"success": False,
                "message": f"Geen wachtapotheek gevonden voor {query}.",
                "data": {}}

    def _action_apotheker_help(self, params):
        return {"success": False, "message": (
            "Gebruik: apotheker <postcode>\n"
            "Zoekt de wachtapotheek in jouw buurt.\n"
            "Voorbeeld: apotheker 9790"
        ), "data": {}}


    def _action_unknown(self, params):
        return {"success": False,
                "message": "Onbekend commando. Gebruik:  route, trein, wandel / pied, bus, mivb / stib, weer, apotheek, gpt, janee, nieuws, vertaling",
                "data": {}}