"""
baksteenservice - config.py
DEV_MODE = True   → terminal  (no hardware needed)
DEV_MODE = False  → SIM800C via USB serial
"""
DEV_MODE   = True       # ← flip to False when SIM800C is connected
MODEM_PORT = "/dev/ttyUSB0"
MODEM_BAUD = 9600
ALLOWED_SENDERS: list[str] = []
