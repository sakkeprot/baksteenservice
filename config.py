"""baksteenservice - config.py"""

import re

DEV_MODE = True

MODEM_PORT = "/dev/ttyUSB0"
MODEM_BAUD = 9600

ALLOWED_SENDERS: list[str] = []
SENDER_PATTERN = re.compile(r"^\+32\d+$")

SMS_MAX_DEFAULT = 160

SMS_MAX: dict[str, int] = {
    "gpt":       306,
    "trein":     306,
    "route":     612,
    "weer":      306,
    "nieuws":    306,
    "vertaling": 160,
    "apotheker": 306,
    "janee":     160,
}

def sms_max(action: str) -> int:
    return SMS_MAX.get(action, SMS_MAX_DEFAULT)
