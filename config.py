"""baksteenservice - config.py"""

import re

DEV_MODE = True  # ← False when SIM800C connected

MODEM_PORT = "/dev/ttyUSB0"
MODEM_BAUD = 9600

ALLOWED_SENDERS: list[str] = []
SENDER_PATTERN = re.compile(r"^\+32\d+$")

# ── SMS-lengtelimiet per actie ────────────────────────────────────────────────
# Formule: 160 = 1 sms | 306 = 2 sms | 459 = 3 sms | 612 = 4 sms
# Voeg hier een actienaam toe als sleutel en het maximum aantal tekens als waarde.
# Acties die hier NIET vermeld staan vallen terug op SMS_MAX_DEFAULT.

SMS_MAX_DEFAULT = 160  # 1 sms

SMS_MAX: dict[str, int] = {
    #1 SMS = 160 , 2 SMS = 306, 3 SMS = 459, 4 SMS = 612
    "gpt":       306,   
    "trein":     306,   
    "route":     612,   
    "weer":      306,   
    "nieuws":    306,   
    "vertaling": 160,   
    "apotheker": 306,   
    "bus":       306,   
    "janee":     160,  
}

def sms_max(action: str) -> int:
    """Geeft de maximale berichtlengte (in tekens) voor de gegeven actie."""
    return SMS_MAX.get(action, SMS_MAX_DEFAULT)

# ── ORS routeringprofiel ──────────────────────────────────────────────────────
# "foot-walking"    → te voet ← default
# "foot-hiking"     → wandelen
# "driving-car"     → auto
# "cycling-regular" → fiets
# "cycling-road"    → racefiets
# "cycling-mountain"→ MTB
# "wheelchair"      → rolstoel
ROUTE_PROFILE = "foot-walking"
