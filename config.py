"""baksteenservice - config.py"""
import re

DEV_MODE   = True       # ← False when SIM800C connected
MODEM_PORT = "/dev/ttyUSB0"
MODEM_BAUD = 9600
ALLOWED_SENDERS: list[str] = []
SENDER_PATTERN = re.compile(r"^\+32\d+$")

# Max SMS length for route replies.
# 160 = 1 SMS | 306 = 2 SMS (concatenated) | 459 = 3 SMS
ROUTE_MAX_LENGTH = 306

# ORS routing profile — swap to change transport mode:
#   "foot-walking"     → te voet        ← default
#   "foot-hiking"      → wandelen
#   "driving-car"      → auto
#   "cycling-regular"  → fiets
#   "cycling-road"     → racefiets
#   "cycling-mountain" → MTB
#   "wheelchair"       → rolstoel
ROUTE_PROFILE = "foot-walking"
